from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Protocol, Sequence

from lupa import LuaRuntime

# The portrayal catalogue lives here relative to repo root.
RULES_DIR = Path("portrayal/PortrayalCatalog/Rules")
CATALOG_CORE_MODULES = [
    "S100Scripting",
    "PortrayalModel",
    "PortrayalAPI",
    "Default",
    "main",
]

# Opinionated fixed context parameters (ingest-time, not mariner configurable here).
DEFAULT_CONTEXT: Mapping[str, Any] = {
    "SafetyContour": 4.0,
    "SafetyDepth": -100.0,
    "ShallowContour": 2.0,
    "DeepContour": 6.0,
    "DisplayDepthUnits": 1,
    "FourShades": True,
    "SimplifiedSymbols": False,
    "RadarOverlay": False,
    "PlainBoundaries": False,
}


@dataclass
class FeatureRecord:
    """Host-side representation of a single feature sent to the Lua catalogue."""

    feature_id: str
    code: str
    primitive: str  # Point | Curve | Surface (S-101 primitive)
    attributes: Dict[str, Any]
    spatial_id: str | None = None

    def to_simple_attribute(self, attribute_code: str) -> List[str]:
        value = self.attributes.get(attribute_code)
        if value is None:
            return []
        if isinstance(value, (list, tuple)):
            return [str(v) for v in value]
        return [str(value)]


@dataclass
class PortrayalResult:
    raw: Dict[str, List[str]]
    parsed: Dict[str, List[Dict[str, Any]]]
    parsed_json: Dict[str, List[Dict[str, Any]]] | None = None


class FeatureSource(Protocol):
    def __iter__(self) -> Iterable[FeatureRecord]:
        ...


class DrawingSink(Protocol):
    def write(
        self, feature_id: str, raw_instructions: List[str], instructions: List[Dict[str, Any]]
    ) -> None:
        ...


class CollectingSink:
    """In-memory sink useful for callers that just want the parsed output."""

    def __init__(self) -> None:
        self.data: Dict[str, List[Dict[str, Any]]] = {}

    def write(
        self, feature_id: str, raw_instructions: List[str], instructions: List[Dict[str, Any]]
    ) -> None:
        self.data[feature_id] = instructions


class PortrayalHost:
    """Minimal host implementation for running the S-101 Lua portrayal catalogue.

    Captures the DEF (Drawing Instructions) string emitted per feature via HostPortrayalEmit.
    Currently geared toward ingest-time portrayal of raw S-57 features mapped to S-101 names.
    """

    def __init__(self, context: Mapping[str, Any] | None = None):
        self.context = dict(DEFAULT_CONTEXT)
        if context:
            self.context.update(context)

        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self._features: Dict[str, FeatureRecord] = {}
        self._spatial_index: Dict[str, FeatureRecord] = {}
        self._emitted: Dict[str, List[str]] = {}
        self._debug_logs: List[str] = []
        self._feature_type_codes: List[str] = []
        self._simple_attribute_codes: List[str] = []
        self._feature_attribute_bindings: Dict[str, set[str]] = {}
        self._attribute_value_types: Dict[str, str] = {}
        self._catalog_available = True

        self._setup_lua()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def portray(self, features: Iterable[FeatureRecord]) -> Dict[str, List[str]]:
        """Run portrayal for the provided features and return DEF strings per feature_id."""
        feature_list = list(features)
        if not self._catalog_available:
            self._emitted = self._fallback_portray(feature_list)
            return self._emitted

        self._features = {f.feature_id: f for f in feature_list}
        self._spatial_index = {}
        self._emitted = {}
        self._feature_type_codes = sorted({f.code for f in feature_list})
        self._simple_attribute_codes = sorted(
            {attr for f in feature_list for attr in f.attributes.keys()}
        )
        self._feature_attribute_bindings = {
            code: {attr for f in feature_list if f.code == code for attr in f.attributes}
            for code in self._feature_type_codes
        }
        self._attribute_value_types = self._infer_attribute_value_types(feature_list)

        # DepthArea rule expects restriction to exist even if absent in the source.
        if "DepthArea" in self._feature_attribute_bindings:
            self._feature_attribute_bindings["DepthArea"].update(
                {"depthRangeMinimumValue", "depthRangeMaximumValue", "restriction"}
            )
            for attr in ["depthRangeMinimumValue", "depthRangeMaximumValue", "restriction"]:
                if attr not in self._simple_attribute_codes:
                    self._simple_attribute_codes.append(attr)

        # Hazard rules (UnderwaterAwashRock/Obstruction) expect these optional
        # attributes to exist, even if they are empty in the source data.
        hazard_attrs = {"defaultClearanceDepth", "surroundingDepth", "waterLevelEffect"}
        for hazard_code in ["UnderwaterAwashRock", "Obstruction", "Wreck"]:
            if hazard_code in self._feature_attribute_bindings:
                self._feature_attribute_bindings[hazard_code].update(hazard_attrs)
                for attr in hazard_attrs:
                    if attr not in self._simple_attribute_codes:
                        self._simple_attribute_codes.append(attr)

        # SeabedArea rules expect waterLevelEffect even when absent in data.
        seabed_attrs = {"waterLevelEffect", "surfaceCharacteristics"}
        if "SeabedArea" in self._feature_attribute_bindings:
            self._feature_attribute_bindings["SeabedArea"].update(seabed_attrs)
            for attr in seabed_attrs:
                if attr not in self._simple_attribute_codes:
                    self._simple_attribute_codes.append(attr)

        # ShorelineConstruction rules reference condition/category/waterLevelEffect.
        shore_attrs = {"condition", "categoryOfShorelineConstruction", "waterLevelEffect"}
        if "ShorelineConstruction" in self._feature_attribute_bindings:
            self._feature_attribute_bindings["ShorelineConstruction"].update(shore_attrs)
            for attr in shore_attrs:
                if attr not in self._simple_attribute_codes:
                    self._simple_attribute_codes.append(attr)
        self._simple_attribute_codes.sort()

        # Reset cached Lua type info so the upcoming feature/attribute codes are seen.
        self.lua.execute("typeInfo = nil")

        self._initialize_context_parameters()

        feature_ids = self.lua.table_from(list(self._features.keys()))
        print(f"[PORTRAY] feature codes={[f.code for f in self._features.values()]}")
        portray_main = self.lua.globals().PortrayalMain
        portray_main(feature_ids)
        return self._emitted

    def portray_with_json(
        self,
        source: Iterable[FeatureRecord] | FeatureSource,
        sinks: Sequence[DrawingSink] | DrawingSink | None = None,
        *,
        compact_json: bool = True,
    ) -> PortrayalResult:
        """Run portrayal, parse DEF strings into structured JSON, and fan out to sinks.

        Returns a PortrayalResult containing both raw DEF strings and parsed instructions.
        """

        raw_map = self.portray(source)
        parsed_map = self._parse_emitted(raw_map)
        parsed_json = {
            fid: [self._compact_json(instr, compact=compact_json) for instr in instructions]
            for fid, instructions in parsed_map.items()
        }

        sink_list: List[DrawingSink] = []
        if sinks:
            if isinstance(sinks, Sequence) and not isinstance(sinks, (str, bytes)):
                sink_list = list(sinks)  # type: ignore[arg-type]
            else:
                sink_list = [sinks]  # type: ignore[list-item]

        for feature_id, raw_instr in raw_map.items():
            parsed_instr = parsed_map.get(feature_id, [])
            for sink in sink_list:
                sink.write(feature_id, raw_instr, parsed_instr)

        return PortrayalResult(raw=raw_map, parsed=parsed_map, parsed_json=parsed_json)

    # ------------------------------------------------------------------
    # Lua environment setup
    # ------------------------------------------------------------------
    def _setup_lua(self) -> None:
        lua = self.lua

        # Make catalogue files importable.
        lua.execute(
            f"package.path = package.path .. ';{RULES_DIR.as_posix()}/?.lua'"
        )

        # Harden the Lua runtime a bit: drop OS/file access, stub Debug hooks.
        def _trace(msg):
            text = f"[Lua] {msg}"
            self._debug_logs.append(text)
            print(text)

        def _trace_err(msg, depth=None):
            text = f"[Lua-err] {msg}"
            self._debug_logs.append(text)
            print(text)

        lua.globals().Debug = lua.table()
        lua.globals().Debug.Trace = _trace
        lua.globals().Debug.StartPerformance = lambda label=None: None
        lua.globals().Debug.StopPerformance = lambda label=None: None
        lua.globals().Debug.Break = lambda: None
        lua.globals().Debug.FirstChanceError = _trace_err
        lua.execute("os=nil; io=nil; debug=nil; package.loadlib=nil; loadfile=nil; dofile=nil")

        # HostPortrayalEmit: capture DEF strings.
        def host_portrayal_emit(feature_ref, di_string, observed=None):
            feature_ref = str(feature_ref)
            di_string = str(di_string) if di_string else ""
            self._emitted.setdefault(feature_ref, []).append(di_string)
            return True

        lua.globals().HostPortrayalEmit = host_portrayal_emit

        # Host data accessors (minimal for ingest pipeline).
        lua.globals().HostGetFeatureIDs = self._host_get_feature_ids
        lua.globals().HostFeatureGetCode = self._host_feature_get_code
        lua.globals().HostGetFeatureTypeCodes = self._host_get_feature_type_codes
        lua.globals().HostGetInformationTypeCodes = lambda: self.lua.table()
        lua.globals().HostGetSimpleAttributeTypeCodes = (
            self._host_get_simple_attribute_type_codes
        )
        lua.globals().HostGetComplexAttributeTypeCodes = lambda: self.lua.table()
        lua.globals().HostGetRoleTypeCodes = lambda: self.lua.table()
        lua.globals().HostGetInformationAssociationTypeCodes = lambda: self.lua.table()
        lua.globals().HostGetFeatureAssociationTypeCodes = lambda: self.lua.table()

        lua.globals().HostGetFeatureTypeInfo = self._host_get_feature_type_info
        lua.globals().HostGetInformationTypeInfo = lambda code: None
        lua.globals().HostGetSimpleAttributeTypeInfo = (
            self._host_get_simple_attribute_type_info
        )
        lua.globals().HostGetComplexAttributeTypeInfo = lambda code: None
        lua.globals().HostGetRoleTypeInfo = lambda code: None
        lua.globals().HostGetInformationAssociationTypeInfo = lambda code: None
        lua.globals().HostGetFeatureAssociationTypeInfo = lambda code: None
        lua.globals().HostFeatureGetSimpleAttribute = self._host_feature_get_simple_attribute
        lua.globals().HostFeatureGetComplexAttributeCount = lambda feature_id, path, code: 0
        lua.globals().HostFeatureGetSpatialAssociations = (
            self._host_feature_get_spatial_associations
        )
        lua.globals().HostFeatureGetAssociatedFeatureIDs = (
            lambda feature_id, association_code, role_code=None: self.lua.table()
        )
        lua.globals().HostFeatureGetAssociatedInformationIDs = (
            lambda feature_id, association_code, role_code=None: self.lua.table()
        )
        lua.globals().HostSpatialGetAssociatedInformationIDs = (
            lambda spatial_id, association_code, role_code=None: self.lua.table()
        )
        lua.globals().HostSpatialGetAssociatedFeatureIDs = (
            lambda spatial_id: self.lua.table()
        )
        lua.globals().HostInformationTypeGetSimpleAttribute = (
            lambda information_id, path, code: self.lua.table()
        )
        lua.globals().HostInformationTypeGetComplexAttributeCount = (
            lambda information_id, path, code: 0
        )
        lua.globals().HostInformationGetAssociatedInformationIDs = (
            lambda information_id, association_code, role_code=None: self.lua.table()
        )
        lua.globals().HostGetSpatial = self._host_get_spatial

        # Optional helper used by some rules.
        lua.globals().HostFeatureNameParts = lambda feature_ref: None

        # Load Lua catalogue core files.
        if not RULES_DIR.exists():
            self._catalog_available = False
            print(
                f"[PORTRAY] rules dir missing at {RULES_DIR}. "
                "Using built-in fallback portrayal."
            )
            return

        try:
            for module_name in CATALOG_CORE_MODULES:
                lua.execute(f"require('{module_name}')")
        except Exception as exc:
            self._catalog_available = False
            print(
                f"[PORTRAY] failed to load S-101 catalogue modules ({exc}). "
                "Using built-in fallback portrayal."
            )
            return

        # Reinstall debug hooks (S100Scripting overrides Debug table).
        lua.globals().Debug.Trace = _trace
        lua.globals().Debug.FirstChanceError = _trace_err

    def _initialize_context_parameters(self) -> None:
        lua = self.lua

        # Build the Lua initialization script to avoid Python list indexing inside Lua.
        lines = ["local params = {}"]
        idx = 1
        for name, value in self.context.items():
            param_type = self._context_type(value)
            default_str = self._context_value_to_string(value)
            lines.append(
                f"params[{idx}] = PortrayalCreateContextParameter('" +
                name + "','" + param_type + "','" + default_str + "')"
            )
            idx += 1

        lines.append("PortrayalInitializeContextParameters(params)")

        # Apply explicit values (ConvertEncodedValue handles typing in Lua)
        for name, value in self.context.items():
            value_str = self._context_value_to_string(value)
            lines.append(
                f"PortrayalSetContextParameter('" + name + "','" + value_str + "')"
            )

        script = "\n".join(lines)
        try:
            lua.execute(script)
        except Exception:
            print("[PORTRAY] Failed to init context with script:\n" + script)
            raise

    # ------------------------------------------------------------------
    # Host callbacks (Python → Lua)
    # ------------------------------------------------------------------
    def _host_get_feature_ids(self) -> Any:
        return self.lua.table_from(list(self._features.keys()))

    def _host_feature_get_code(self, feature_id: str) -> str:
        return self._features[feature_id].code

    def _host_get_feature_type_codes(self):
        print(f"[PORTRAY] HostGetFeatureTypeCodes -> {self._feature_type_codes}")
        return self.lua.table_from(self._feature_type_codes)

    def _host_get_simple_attribute_type_codes(self):
        return self.lua.table_from(self._simple_attribute_codes)

    def _host_get_feature_type_info(self, code: str):
        print(f"[PORTRAY] HostGetFeatureTypeInfo({code}) with bindings {self._feature_attribute_bindings.get(code)}")
        bindings = self.lua.table()
        for attr in self._feature_attribute_bindings.get(code, []):
            upper = 10 if attr == "restriction" else 1
            bindings[attr] = self.lua.table(UpperMultiplicity=upper)

        return self.lua.table(AttributeBindings=bindings)

    def _host_get_simple_attribute_type_info(self, code: str):
        value_type = self._attribute_value_types.get(code)
        if value_type is None and "depthRange" in code:
            value_type = "real"
        return self.lua.table(ValueType=value_type or "text")

    def _host_feature_get_simple_attribute(
        self, feature_id: str, path: str, attribute_code: str
    ) -> Any:
        feature = self._features[feature_id]
        return self.lua.table_from(feature.to_simple_attribute(attribute_code))

    def _host_feature_get_spatial_associations(self, feature_id: str):
        feature = self._features[feature_id]
        spatial_id = feature.spatial_id or feature.feature_id
        self._spatial_index[spatial_id] = feature

        create_spatial_assoc = self.lua.globals().CreateSpatialAssociation
        orientation = self.lua.globals().Orientation.Forward
        assoc = create_spatial_assoc(feature.primitive, spatial_id, orientation)

        tbl = self.lua.table()
        tbl[1] = assoc
        return tbl

    def _host_get_spatial(self, spatial_id: str):
        """Return a minimal Spatial object so FlattenSpatialAssociation succeeds.

        For now, only surfaces are constructed because DepthArea is the pilot feature.
        Surface geometry is represented by a single curve association placeholder.
        """

        feature = self._spatial_index.get(spatial_id)
        if not feature:
            return None

        if feature.primitive == "Surface":
            create_surface = self.lua.globals().CreateSurface
            create_spatial_assoc = self.lua.globals().CreateSpatialAssociation
            orientation = self.lua.globals().Orientation.Forward

            exterior_assoc = create_spatial_assoc(
                self.lua.globals().SpatialType.Curve,
                f"{spatial_id}:outer",
                orientation,
            )
            interior_rings = self.lua.table()
            return create_surface(exterior_assoc, interior_rings)

        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _context_type(value: Any) -> str:
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int):
            return "integer"
        if isinstance(value, float):
            return "real"
        return "text"

    @staticmethod
    def _context_value_to_string(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    @staticmethod
    def _parse_emitted(raw_map: Mapping[str, List[str]]) -> Dict[str, List[Dict[str, Any]]]:
        parsed: Dict[str, List[Dict[str, Any]]] = {}
        for feature_id, instructions in raw_map.items():
            parsed[feature_id] = [parse_drawing_instruction(di) for di in instructions if di]
        return parsed

    @staticmethod
    def _compact_json(instr: Dict[str, Any], *, compact: bool) -> Dict[str, Any]:
        if not compact:
            return dict(instr)
        return {k: v for k, v in instr.items() if v is not None and v != ""}

    @staticmethod
    def _infer_attribute_value_types(features: List[FeatureRecord]) -> Dict[str, str]:
        value_types: Dict[str, str] = {}

        def classify(value: Any) -> str:
            if isinstance(value, bool):
                return "boolean"
            if isinstance(value, (int, float)):
                return "real"
            return "text"

        for feature in features:
            for attr, raw_value in feature.attributes.items():
                # Preserve strongest numeric classification if mixed types appear.
                new_type = classify(raw_value)
                current = value_types.get(attr)
                if current == "real":
                    continue
                if current == "boolean" and new_type == "text":
                    continue
                value_types[attr] = new_type

        return value_types

    @staticmethod
    def _fallback_portray(features: List[FeatureRecord]) -> Dict[str, List[str]]:
        """Fallback portrayal when the external Lua catalogue is unavailable."""

        emitted: Dict[str, List[str]] = {}
        for feature in features:
            base = [
                "ViewingGroup:21010",
                "DrawingPriority:15",
                "DisplayPlane:UnderRadar",
            ]
            if feature.code == "DepthArea":
                color = _fallback_depth_fill(feature.attributes)
                base[0] = "ViewingGroup:13030"
                base[1] = "DrawingPriority:3"
                base.append(f"ColorFill:{color}")
            elif feature.primitive == "Curve":
                base.append("LineInstruction:QUESMRK1")
                base.append("LineColor:CHBLK")
            elif feature.primitive == "Point":
                base.append("PointInstruction:QUESMRK1")
            else:
                base.append("NullInstruction")
            emitted[feature.feature_id] = [";".join(base)]
        return emitted


def _fallback_depth_fill(attributes: Mapping[str, Any]) -> str:
    depth = attributes.get("depthRangeMinimumValue")
    try:
        value = float(depth)
    except (TypeError, ValueError):
        return "NODTA"
    if value < 0:
        return "DEPIT"
    if value < 2:
        return "DEPVS"
    if value < 5:
        return "DEPMS"
    if value < 10:
        return "DEPMD"
    return "DEPDW"


def parse_drawing_instruction(di_string: str) -> Dict[str, Any]:
    """Parse a semicolon-delimited DEF string into a flat key/value map (no raw echo)."""

    tokens = [token for token in di_string.split(";") if token]
    fields: MutableMapping[str, Any] = {}

    for token in tokens:
        if ":" not in token:
            fields[token.strip()] = ""
            continue

        key, value = token.split(":", 1)
        key = key.strip()
        value = value.strip()

        parsed = _parse_di_value(value)
        fields[key] = parsed

    return dict(fields)


def _as_int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_di_value(value: str) -> Any:
    parts = _split_def_csv(value)
    parsed_parts = [_parse_scalar(p) for p in parts]
    if len(parsed_parts) == 1:
        return parsed_parts[0]
    return parsed_parts


def _split_def_csv(value: str) -> List[str]:
    if "," not in value:
        return [_decode_def_string(value)]
    return [_decode_def_string(part.strip()) for part in value.split(",")]


def _parse_scalar(value: str) -> Any:
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    num = _as_int(value)
    if num is not None:
        return num
    num = _as_float(value)
    if num is not None and re.match(r"^-?\d+(\.\d+)?$", value):
        return num
    return value


def _decode_def_string(value: str) -> str:
    # Decode order matters: &a must be last.
    return (
        value.replace("&s", ";")
        .replace("&c", ":")
        .replace("&m", ",")
        .replace("&a", "&")
    )
