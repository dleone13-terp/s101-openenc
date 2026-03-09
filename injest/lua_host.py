import math
import lupa          # pip install lupa  (Python binding to LuaJIT or Lua 5.4)
from pathlib import Path

from .base import FeaturePortrayer
from .parse_di import parse_drawing_instructions, DrawingInstructions

RULES_DIR = Path('portrayal/PortrayalCatalog/Rules')

# All context parameters accessed by portrayal rules (from grep of *.lua).
# Must be pre-populated before PortrayalMain runs — the ContextParameters proxy
# raises an error on any unknown key.
FIXED_CONTEXT = {
    # Depth thresholds
    'SafetyContour':     30.0,
    'SafetyDepth':       30.0,
    'ShallowContour':     5.0,
    'DeepContour':       30.0,
    # Display flags
    'SimplifiedSymbols': False,
    'RadarOverlay':      False,
    'PlainBoundaries':   False,
    'IgnoreScaleMinimum': False,
    'FourShades':        False,
    'FullLightLines':    True,
    'ShallowWaterDangers': False,
    # Text / language
    'NationalLanguage':  'eng',
    # Testing / sounding text size (disabled)
    '_Testing_SoundingsAsText_SizeSafe':   0,
    '_Testing_SoundingsAsText_SizeUnsafe': 0,
}

# Map our geometry type string → PrimitiveType table key name
_GEOM_TO_PRIM = {
    'Point':   'Point',
    'Curve':   'Curve',
    'Surface': 'Surface',
}


class LuaHost(FeaturePortrayer):
    """
    Minimal implementation of the S-100 Part 9 host-side Lua API.

    Execution path per feature:
      portray() → PortrayalMain({featureID})
        → ProcessFeaturePortrayalItem()
          → require(feature.Code)          # loads e.g. Coastline.lua
          → Coastline(feature, featurePortrayal, contextParameters)
          → HostPortrayalEmit(featureRef, diString, observed)
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
        # The Lua rules call it once per feature with the complete DI string.
        captured = self._emitted
        def host_emit(feature_ref, di_string, observed_params=None):
            captured.append((str(feature_ref), str(di_string) if di_string else ''))
        lua.globals().HostPortrayalEmit = host_emit

        # ---- Stub HostFeatureNameParts ----
        lua.globals().HostFeatureNameParts = lambda feature_ref: None

        # ---- Stub host functions needed by PortrayalModel.CreatePortrayalContext() ----
        # HostGetFeatureIDs() is called during context creation to build the feature list.
        # Return empty — we add features manually per-call via AddFeature().
        lua.execute("""
            function HostGetFeatureIDs() return {} end
            function HostFeatureGetCode(id) return '' end
        """)

        # ---- Set package.path so require() resolves to RULES_DIR ----
        rules_dir_abs = str(RULES_DIR.resolve())
        lua.execute(f"package.path = '{rules_dir_abs}/?.lua;' .. package.path")

        # ---- Load framework modules via require() ----
        # require() registers each module in package.loaded so subsequent
        # require() calls inside feature rules return the cached instance.
        # Load order: PortrayalAPI before PortrayalModel (PortrayalModel requires it).
        # main.lua defines PortrayalMain() which orchestrates feature processing.
        for lua_file in ['S100Scripting', 'PortrayalAPI', 'PortrayalModel', 'Default', 'main']:
            path = RULES_DIR / f'{lua_file}.lua'
            if path.exists():
                lua.execute(f"require '{lua_file}'")

        # ---- Create proper portrayalContext via PortrayalModel ----
        # This builds the ContextParameters proxy (with metatable) and
        # FeaturePortrayalItems array (with AddFeature method).
        # HostGetFeatureIDs() returns {} so no features are loaded at this point.
        lua.execute("portrayalContext = PortrayalModel.CreatePortrayalContext()")

        # Pre-populate ALL context parameters that rules access.
        # Write directly to _underlyingTable to bypass the proxy's write-guard
        # (the guard only allows keys that already exist in the underlying table).
        # Use a single lua.execute() string to avoid Pylance issues with lupa table indexing.
        assignments = []
        for k, v in FIXED_CONTEXT.items():
            if isinstance(v, bool):
                assignments.append(f"cp.{k} = {'true' if v else 'false'}")
            elif isinstance(v, str):
                assignments.append(f"cp.{k} = '{v}'")
            elif isinstance(v, float):
                # Depth thresholds (SafetyContour etc.) are compared against
                # ScaledDecimal feature attributes, so they must also be ScaledDecimal.
                assignments.append(f"cp.{k} = StringToScaledDecimal('{v:.10g}')")
            elif isinstance(v, int):
                # Integer context params (testing flags etc.) stay as plain numbers.
                assignments.append(f"cp.{k} = {v}")
            else:
                assignments.append(f"cp.{k} = {v}")
        lua.execute(
            "local cp = portrayalContext.ContextParameters._underlyingTable\n"
            + "\n".join(assignments)
        )

        # ---- Feature stub metatable: 9 methods required by portrayal catalogue ----
        # Defined once as a shared prototype; CreateStubFeature applies it via setmetatable.
        lua.execute("""
            _featureStubMethods = {
                GetInformationAssociation       = function(self, c, r, t) return nil end,
                GetInformationAssociations      = function(self, c, r)    return {} end,
                GetFeatureAssociation           = function(self, c, r, t) return nil end,
                GetFeatureAssociations          = function(self, c, r)    return {} end,
                GetSpatialAssociation           = function(self)
                    return { GetAssociatedFeatures = function(s) return {} end }
                end,
                GetSpatialAssociations          = function(self)          return {} end,
                GetSpatial                      = function(self)          return nil end,
                FlattenSpatialAssociation       = function(self, spas)    return {} end,
                GetFlattenedSpatialAssociations = function(self)
                    return function() return nil end
                end,
                GetInformation                  = function(self, t)       return {} end,
            }
            _featureStubMeta = { __index = _featureStubMethods }

            function CreateStubFeature(code, id, primTypeName)
                local f = {
                    Type          = 'Feature',
                    Code          = code,
                    ID            = id,
                    PrimitiveType = PrimitiveType[primTypeName],
                }
                setmetatable(f, _featureStubMeta)
                return f
            end
        """)

        # ---- Helper: clear FeaturePortrayalItems between portray() calls ----
        lua.execute("""
            function ClearFeaturePortrayalItems()
                local fpi = portrayalContext.FeaturePortrayalItems
                for i = #fpi, 1, -1 do
                    fpi[fpi[i].Feature.ID] = nil
                    fpi[i] = nil
                end
            end
        """)

    def portray(self, feature: dict) -> list[DrawingInstructions]:
        """
        Run the portrayal rule for a single feature and return parsed Drawing Instructions.

        feature dict keys (minimum required):
          'code'        S-101 feature type name e.g. 'DepthArea'
          'id'          feature object identifier string
          'geometry'    geometry type: 'Point' | 'Curve' | 'Surface'
          'attributes'  dict of attribute name → value
        """
        self._emitted.clear()
        lua = self.lua

        # Remove any feature added during the previous call
        lua.execute("ClearFeaturePortrayalItems()")

        prim_name = _GEOM_TO_PRIM.get(feature.get('geometry', 'Point'), 'Point')

        # Build the feature stub via the shared metatable helper.
        # Scalar globals are set from Python; Lua side creates the stub table.
        lua.globals().currentFeatureCode = feature['code']
        lua.globals().currentFeatureID = feature['id']
        lua.globals().currentFeaturePrimType = prim_name
        lua.execute("currentFeature = CreateStubFeature(currentFeatureCode, currentFeatureID, currentFeaturePrimType)")

        # Set scalar and list attributes as flat fields on the feature table.
        # Numeric (non-bool) values must be wrapped in ScaledDecimal so that
        # portrayal rules can compare them with operators like >= and < against
        # scaledDecimalZero and contextParameters thresholds.
        feat = lua.globals().currentFeature
        str_to_sd = lua.globals().StringToScaledDecimal
        for k, v in feature.get('attributes', {}).items():
            if isinstance(v, bool):
                feat[k] = v
            elif isinstance(v, float):
                # Measurement attributes (depth, height, distance) are compared
                # against ScaledDecimal thresholds in portrayal rules.
                if not math.isfinite(v):
                    continue  # skip NaN / Inf — rules can't handle them
                feat[k] = str_to_sd(f'{v:.10g}')
            elif isinstance(v, int):
                # Integer attributes are enum codes (categoryOfCoastline etc.);
                # keep as plain Lua numbers so == comparisons work.
                feat[k] = v
            elif isinstance(v, str):
                feat[k] = v
            elif isinstance(v, list):
                # Convert Python list → Lua sequence table (1-indexed)
                try:
                    feat[k] = lua.table(*v)
                except Exception:
                    pass  # skip unconvertible values

        # Add the feature to PortrayalItems and run the full portrayal machinery.
        try:
            lua.execute("""
                portrayalContext.FeaturePortrayalItems:AddFeature(currentFeature)
                PortrayalMain({currentFeatureID})
            """)
        except Exception as e:
            print(f"  [WARN] Rule error for {feature['code']} id={feature['id']}: {e}")
            return []

        return [parse_drawing_instructions(di) for _, di in self._emitted if di]
