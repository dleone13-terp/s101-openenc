import lupa          # pip install lupa  (Python binding to LuaJIT or Lua 5.4)
from pathlib import Path
from parse_di import parse_drawing_instructions, DrawingInstructions
import psycopg2

RULES_DIR = Path('portrayal/PortrayalCatalog/Rules')

# Fixed context parameters — opinionated, never change
FIXED_CONTEXT = {
    'SafetyContour':     30.0,
    'SafetyDepth':       30.0,
    'ShallowContour':    5.0,
    'DeepContour':       30.0,
    'DisplayDepthUnits': 1,
    'TwoDepthShades':    False,
    'SimplifiedSymbols': False,
}


class LuaHost:
    """
    Minimal implementation of the S-100 Part 9 host-side Lua API.

    The Lua rules expect the host to provide:
      - portrayalContext.ContextParameters  (we inject fixed values)
      - portrayalContext.FeaturePortrayalItems  (we inject one feature at a time)
      - HostPortrayalEmit(featureRef, diString, observedParams) callback
      - Debug.Trace / Debug.StartPerformance stubs

    The output we care about is the diString passed to HostPortrayalEmit.
    """

    def __init__(self):
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        self._emitted: list[tuple[str, str]] = []  # (featureRef, diString)
        self._setup_lua_environment()

    def _setup_lua_environment(self):
        lua = self.lua

        # ---- Security: disable dangerous Lua stdlib ----
        lua.execute("""
            os = nil; io = nil; debug = nil
            package.loadlib = nil; loadfile = nil; dofile = nil
        """)

        # ---- Stub out Debug module ----
        lua.execute("""
            Debug = {}
            function Debug.Trace(msg) end
            function Debug.StartPerformance(label) end
            function Debug.StopPerformance(label) end
        """)

        # ---- Implement HostPortrayalEmit ----
        # This is the single most important host function.
        # The Lua rules call it once per feature with the complete Drawing Instructions string.
        captured = self._emitted
        def host_emit(feature_ref, di_string, observed_params=None):
            captured.append((str(feature_ref), str(di_string) if di_string else ''))
        lua.globals().HostPortrayalEmit = host_emit

        # ---- Stub HostFeatureNameParts (used by GetFeatureName helper in rules) ----
        def host_feature_name(feature_ref):
            return None  # labels from attributes handled in parse_di
        lua.globals().HostFeatureNameParts = host_feature_name

        # ---- Inject fixed context parameters ----
        lua.execute("""
            portrayalContext = {}
            portrayalContext.ContextParameters = {}
        """)
        ctx = lua.globals().portrayalContext.ContextParameters
        for k, v in FIXED_CONTEXT.items():
            ctx[k] = v

        # ---- Load the portrayal catalogue Lua modules ----
        # S100Scripting.lua, PortrayalModel.lua, PortrayalAPI.lua, Default.lua
        # These are the framework files that ship alongside the feature rules.
        for lua_file in ['S100Scripting', 'PortrayalModel', 'PortrayalAPI', 'Default']:
            path = RULES_DIR / f'{lua_file}.lua'
            if path.exists():
                lua.execute(path.read_text())

    def portray_feature(self, feature: dict) -> list[DrawingInstructions]:
        """
        Run the portrayal rule for a single feature and return parsed Drawing Instructions.

        feature dict keys (minimum required):
          'code'        S-101 feature type name e.g. 'DepthArea'
          'id'          feature object identifier string
          'geometry'    geometry type: 'Point' | 'Line' | 'Surface'
          'attributes'  dict of attribute name → value
        """
        self._emitted.clear()

        # Build a Lua feature object
        lua = self.lua
        lua.globals().currentFeature = lua.table(
            Code=feature['code'],
            ID=feature['id'],
            GeometryType=feature.get('geometry', 'Point'),
            Primitive=feature.get('geometry', 'Point'),
        )

        # Inject attributes into the Lua feature object
        attrs_table = lua.table()
        for k, v in feature.get('attributes', {}).items():
            attrs_table[k] = v
        lua.globals().currentFeature.Attributes = attrs_table

        # Load and execute the specific rule file for this feature type
        rule_file = RULES_DIR / f'{feature["code"]}.lua'
        if not rule_file.exists():
            # Fallback: use Default rule
            rule_file = RULES_DIR / 'Default.lua'

        try:
            lua.execute(f"""
                local feature = currentFeature
                local featurePortrayal = {{
                    FeatureReference = feature.ID,
                    DrawingInstructions = {{}}
                }}
                portrayalContext.FeaturePortrayalItems = {{ {{ Feature = feature, Portrayal = featurePortrayal }} }}
            """)
            lua.execute(rule_file.read_text())
        except Exception as e:
            # Rule error: return empty — don't crash the entire ingest
            print(f"  [WARN] Rule error for {feature['code']} id={feature['id']}: {e}")
            return []

        return [parse_drawing_instructions(di) for _, di in self._emitted]


class Ingester:
    """Runs LuaHost over all features and writes results to PostGIS."""

    def __init__(self, db_url: str):
        self.conn = psycopg2.connect(db_url)
        self.host = LuaHost()

    def ingest_feature(self, feature: dict, cell_file: str):
        dis = self.host.portray_feature(feature)
        if not dis:
            return

        # Merge all DIs for this feature (a feature can emit multiple)
        # Last-write-wins for scalar fields; texts accumulate.
        merged = DrawingInstructions()
        all_texts = []
        for di in dis:
            if di.vg is not None:  merged.vg = di.vg
            if di.dp is not None:  merged.dp = di.dp
            if di.ac is not None:  merged.ac = di.ac
            if di.ap is not None:  merged.ap = di.ap
            if di.lc is not None:  merged.lc = di.lc
            if di.ls is not None:  merged.ls = di.ls
            if di.lw is not None:  merged.lw = di.lw
            if di.sy is not None:  merged.sy = di.sy
            if di.sy_rot is not None: merged.sy_rot = di.sy_rot
            if di.sy_rot_type is not None: merged.sy_rot_type = di.sy_rot_type
            all_texts.extend(di.texts)

        geom_type = feature.get('geometry', 'Point')
        wkt       = feature['wkt']  # WKT geometry from cell reader
        foid      = feature['id']
        fcode     = feature['code']

        cur = self.conn.cursor()

        if geom_type == 'Surface':
            cur.execute("""
                INSERT INTO enc_area
                  (foid, feature_code, cell_file, geom,
                   di_vg, di_dp, di_ac, di_ap, di_lc, di_ls, di_lw,
                   drval1, drval2)
                VALUES (%s,%s,%s, ST_Multi(ST_GeomFromText(%s,4326)),
                        %s,%s,%s,%s,%s,%s,%s, %s,%s)
                ON CONFLICT (foid) DO UPDATE SET
                  di_vg=EXCLUDED.di_vg, di_dp=EXCLUDED.di_dp,
                  di_ac=EXCLUDED.di_ac, di_lc=EXCLUDED.di_lc
            """, (
                foid, fcode, cell_file, wkt,
                merged.vg, merged.dp, merged.ac, merged.ap,
                merged.lc, merged.ls, merged.lw,
                feature['attributes'].get('depthRangeMinimumValue'),
                feature['attributes'].get('depthRangeMaximumValue'),
            ))

        elif geom_type == 'Curve':
            cur.execute("""
                INSERT INTO enc_line
                  (foid, feature_code, cell_file, geom,
                   di_vg, di_dp, di_lc, di_ls, di_lw, di_ac)
                VALUES (%s,%s,%s, ST_Multi(ST_GeomFromText(%s,4326)),
                        %s,%s,%s,%s,%s,%s)
                ON CONFLICT (foid) DO UPDATE SET
                  di_vg=EXCLUDED.di_vg, di_dp=EXCLUDED.di_dp,
                  di_lc=EXCLUDED.di_lc
            """, (
                foid, fcode, cell_file, wkt,
                merged.vg, merged.dp, merged.lc, merged.ls, merged.lw, merged.ac,
            ))

        elif geom_type == 'Point':
            if fcode == 'Sounding':
                cur.execute("""
                    INSERT INTO enc_sounding (foid, cell_file, geom, depth_m)
                    VALUES (%s,%s, ST_GeomFromText(%s,4326), %s)
                """, (foid, cell_file, wkt,
                      feature['attributes'].get('valueOfSounding', 0)))
            else:
                cur.execute("""
                    INSERT INTO enc_point
                      (foid, feature_code, cell_file, geom,
                       di_vg, di_dp, di_sy, di_sy_rot, di_sy_rot_type)
                    VALUES (%s,%s,%s, ST_GeomFromText(%s,4326),
                            %s,%s,%s,%s,%s)
                    ON CONFLICT (foid) DO UPDATE SET
                      di_sy=EXCLUDED.di_sy, di_vg=EXCLUDED.di_vg
                """, (
                    foid, fcode, cell_file, wkt,
                    merged.vg, merged.dp, merged.sy, merged.sy_rot, merged.sy_rot_type,
                ))

        # Write text labels
        for txt in all_texts:
            if txt['text']:
                cur.execute("""
                    INSERT INTO enc_label
                      (foid, cell_file, geom, di_vg, di_dp,
                       label_text, offset_x, offset_y, font_colour, font_size)
                    VALUES (%s,%s, ST_GeomFromText(%s,4326), %s,%s, %s,%s,%s,%s,%s)
                """, (
                    foid, cell_file, wkt,
                    merged.vg, merged.dp,
                    txt['text'], txt['offset_x'], txt['offset_y'],
                    txt['colour'], txt['size'],
                ))

        self.conn.commit()
        cur.close()