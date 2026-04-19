from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, Iterable, Iterator, List, Mapping, MutableMapping, Protocol, Sequence

from lupa import LuaRuntime

# The portrayal catalogue lives here relative to repo root.
RULES_DIR = Path("portrayal/PortrayalCatalog/Rules")

# Opinionated fixed context parameters (ingest-time, not mariner configurable here).
DEFAULT_CONTEXT: Mapping[str, Any] = {
    "SafetyContour": 4.0,
    "SafetyDepth": 0.0,
    "ShallowContour": 2.0,
    "DeepContour": 6.0,
    "DisplayDepthUnits": 1,
    "FourShades": True,
    "SimplifiedSymbols": False,
    "RadarOverlay": False,
    "PlainBoundaries": False,
}

# Attributes that are enumerations in the S-101 catalogue; keep them as numbers
# when sending into Lua so catalogue comparisons (e.g., colour == 3) behave.
ENUMERATED_ATTRIBUTES: set[str] = {
    "buoyShape",
    "categoryOfLateralMark",
    "categoryOfCardinalMark",
    "categoryOfSpecialPurposeMark",
    "categoryOfObstruction",
    "categoryOfWreck",
    "categoryOfWeedKelp",
    "categoryOfCoastline",
    "categoryOfShorelineConstruction",
    "categoryOfAnchorage",
    "colour",
    "qualityOfPosition",
    "qualityOfSoundingMeasurement",
    "techniqueOfSoundingMeasurement",
    "waterLevelEffect",
}

# Attributes that may legitimately carry multiple values.
MULTIVALUED_ATTRIBUTES: set[str] = {
    "colour",
    "featureName",
    "information",
}

COMMON_OPTIONAL_ATTRIBUTES: set[str] = {"featureName", "information"}
FEATURE_OPTIONAL_ATTRIBUTES: dict[str, set[str]] = {
    "DepthArea": {"depthRangeMinimumValue", "depthRangeMaximumValue", "restriction"},
    "UnderwaterAwashRock": {"defaultClearanceDepth", "surroundingDepth", "waterLevelEffect"},
    "Obstruction": {"defaultClearanceDepth", "surroundingDepth", "waterLevelEffect"},
    "Wreck": {"defaultClearanceDepth", "surroundingDepth", "waterLevelEffect"},
    "SeabedArea": {"waterLevelEffect", "surfaceCharacteristics"},
    "ShorelineConstruction": {
        "condition",
        "categoryOfShorelineConstruction",
        "waterLevelEffect",
    },
}
BUOY_CODES: set[str] = {
    "LateralBuoy",
    "CardinalBuoy",
    "IsolatedDangerBuoy",
    "SafeWaterBuoy",
    "SpecialPurposeGeneralBuoy",
}


@dataclass
class FeatureRecord:
    """Host-side representation of a single feature sent to the Lua catalogue."""

    feature_id: str
    code: str
    primitive: str  # Point | Curve | Surface (S-101 primitive)
    attributes: Dict[str, Any]
    spatial_id: str | None = None

    def to_simple_attribute(self, attribute_code: str) -> List[Any]:
        value = self.attributes.get(attribute_code)
        if value is None:
            return []
        if isinstance(value, (list, tuple)):
            return [self._coerce_attribute_value(v) for v in value]
        return [self._coerce_attribute_value(value)]

    @staticmethod
    def _coerce_attribute_value(value: Any) -> Any:
        if isinstance(value, bytes):
            return value.decode("utf-8", "replace")
        if isinstance(value, (list, tuple)):
            return list(value)
        if isinstance(value, (bool, int, float, str, dict)):
            return value
        return str(value)


@dataclass
class PortrayalResult:
    raw: Dict[str, List[str]]
    parsed: Dict[str, List[Dict[str, Any]]]
    parsed_json: Dict[str, List[Dict[str, Any]]] | None = None


class FeatureSource(Protocol):
    def __iter__(self) -> Iterator[FeatureRecord]:
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

    def __init__(self, context: Mapping[str, Any] | None = None, *, debug: bool = False):
        self.context = dict(DEFAULT_CONTEXT)
        if context:
            self.context.update(context)
        self.debug = debug

        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self._features: Dict[str, FeatureRecord] = {}
        self._spatial_index: Dict[str, FeatureRecord] = {}
        self._emitted: MutableMapping[str, List[str]] = defaultdict(list)
        self._debug_logs: List[str] = []
        self._feature_type_codes: List[str] = []
        self._simple_attribute_codes: List[str] = []
        self._feature_attribute_bindings: Dict[str, set[str]] = {}
        self._attribute_value_types: Dict[str, str] = {}
        self._last_portray_timing: Dict[str, float] = {}

        self._setup_lua()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def portray(self, features: Iterable[FeatureRecord], *, profile: bool = False) -> Dict[str, List[str]]:
        """Run portrayal for the provided features and return DEF strings per feature_id."""
        start_total = perf_counter() if profile else 0.0
        t_after_list = 0.0
        t_after_metadata = 0.0
        t_after_types = 0.0
        t_after_context = 0.0
        feature_list = list(features)
        if profile:
            t_after_list = perf_counter()
        self._features = {f.feature_id: f for f in feature_list}
        self._spatial_index = {}
        self._emitted = defaultdict(list)
        self._initialize_feature_type_metadata(feature_list)
        self._apply_optional_attribute_bindings()
        if profile:
            t_after_metadata = perf_counter()
        self._attribute_value_types = self._infer_attribute_value_types(feature_list)
        if profile:
            t_after_types = perf_counter()

        # Reset cached Lua type info so the upcoming feature/attribute codes are seen.
        self.lua.execute("typeInfo = nil")

        self._initialize_context_parameters()
        if profile:
            t_after_context = perf_counter()

        feature_ids = self.lua.table_from(list(self._features.keys()))
        self._log_debug(f"[PORTRAY] feature codes={[f.code for f in self._features.values()]}")
        portray_main = self.lua.globals().PortrayalMain
        portray_main(feature_ids)
        if profile:
            t_after_lua = perf_counter()
            self._last_portray_timing = {
                "feature_list_s": t_after_list - start_total,
                "metadata_s": t_after_metadata - t_after_list,
                "type_inference_s": t_after_types - t_after_metadata,
                "context_init_s": t_after_context - t_after_types,
                "lua_portray_s": t_after_lua - t_after_context,
                "total_s": t_after_lua - start_total,
                "feature_count": float(len(feature_list)),
            }
        else:
            self._last_portray_timing = {}
        return self._emitted

    def portray_with_json(
        self,
        source: Iterable[FeatureRecord] | FeatureSource,
        sinks: Sequence[DrawingSink] | DrawingSink | None = None,
        *,
        compact_json: bool = True,
        profile: bool = False,
    ) -> PortrayalResult:
        """Run portrayal, parse DEF strings into structured JSON, and fan out to sinks.

        Returns a PortrayalResult containing both raw DEF strings and parsed instructions.
        """

        raw_map = self.portray(source, profile=profile)
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

    def get_last_portray_timing(self) -> Dict[str, float]:
        """Return the most recent portrayal timing sample collected with profile=True."""
        return dict(self._last_portray_timing)

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
            self._log_debug(text)

        def _trace_err(msg, depth=None):
            text = f"[Lua-err] {msg}"
            self._debug_logs.append(text)
            self._log_debug(text)

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
            self._emitted[feature_ref].append(di_string)
            return True

        lua.globals().HostPortrayalEmit = host_portrayal_emit

        # Host data accessors (minimal for ingest pipeline).
        lua.globals().HostGetFeatureIDs = self._host_get_feature_ids
        lua.globals().HostFeatureGetCode = self._host_feature_get_code
        lua.globals().HostGetFeatureTypeCodes = self._host_get_feature_type_codes
        lua.globals().HostGetInformationTypeCodes = self._lua_empty_table
        lua.globals().HostGetSimpleAttributeTypeCodes = (
            self._host_get_simple_attribute_type_codes
        )
        lua.globals().HostGetComplexAttributeTypeCodes = self._lua_empty_table
        lua.globals().HostGetRoleTypeCodes = self._lua_empty_table
        lua.globals().HostGetInformationAssociationTypeCodes = self._lua_empty_table
        lua.globals().HostGetFeatureAssociationTypeCodes = self._lua_empty_table

        lua.globals().HostGetFeatureTypeInfo = self._host_get_feature_type_info
        lua.globals().HostGetInformationTypeInfo = self._lua_none
        lua.globals().HostGetSimpleAttributeTypeInfo = (
            self._host_get_simple_attribute_type_info
        )
        lua.globals().HostGetComplexAttributeTypeInfo = self._lua_none
        lua.globals().HostGetRoleTypeInfo = self._lua_none
        lua.globals().HostGetInformationAssociationTypeInfo = self._lua_none
        lua.globals().HostGetFeatureAssociationTypeInfo = self._lua_none
        lua.globals().HostFeatureGetSimpleAttribute = self._host_feature_get_simple_attribute
        lua.globals().HostFeatureGetComplexAttributeCount = self._lua_zero
        lua.globals().HostFeatureGetSpatialAssociations = (
            self._host_feature_get_spatial_associations
        )
        lua.globals().HostFeatureGetAssociatedFeatureIDs = (
            self._lua_empty_table
        )
        lua.globals().HostFeatureGetAssociatedInformationIDs = (
            self._lua_empty_table
        )
        lua.globals().HostSpatialGetAssociatedInformationIDs = (
            self._lua_empty_table
        )
        lua.globals().HostSpatialGetAssociatedFeatureIDs = (
            self._lua_empty_table
        )
        lua.globals().HostInformationTypeGetSimpleAttribute = (
            self._lua_empty_table
        )
        lua.globals().HostInformationTypeGetComplexAttributeCount = (
            self._lua_zero
        )
        lua.globals().HostInformationGetAssociatedInformationIDs = (
            self._lua_empty_table
        )
        lua.globals().HostGetSpatial = self._host_get_spatial

        # Optional helper used by some rules.
        lua.globals().HostFeatureNameParts = self._lua_none

        # Load Lua catalogue core files.
        for module_name in [
            "S100Scripting",
            "PortrayalModel",
            "PortrayalAPI",
            "Default",
            "main",
        ]:
            lua.execute(f"require('{module_name}')")

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
                f"params[{idx}] = PortrayalCreateContextParameter('{name}','{param_type}','{default_str}')"
            )
            idx += 1

        lines.append("PortrayalInitializeContextParameters(params)")

        # Apply explicit values (ConvertEncodedValue handles typing in Lua)
        for name, value in self.context.items():
            value_str = self._context_value_to_string(value)
            lines.append(f"PortrayalSetContextParameter('{name}','{value_str}')")

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

    def _log_debug(self, message: str) -> None:
        if self.debug:
            print(message)

    def _lua_empty_table(self, *args, **kwargs):
        del args, kwargs
        return self.lua.table()

    @staticmethod
    def _lua_none(*args, **kwargs):
        del args, kwargs
        return None

    @staticmethod
    def _lua_zero(*args, **kwargs):
        del args, kwargs
        return 0

    def _initialize_feature_type_metadata(self, feature_list: List[FeatureRecord]) -> None:
        feature_codes: set[str] = set()
        simple_attrs: set[str] = set()
        bindings: dict[str, set[str]] = defaultdict(set)

        for feature in feature_list:
            feature_codes.add(feature.code)
            attr_codes = set(feature.attributes.keys())
            simple_attrs.update(attr_codes)
            bindings[feature.code].update(attr_codes)

        self._feature_type_codes = sorted(feature_codes)
        self._simple_attribute_codes = sorted(simple_attrs)
        self._feature_attribute_bindings = {
            code: bindings.get(code, set()) for code in self._feature_type_codes
        }

    def _apply_optional_attribute_bindings(self) -> None:
        all_attrs = set(self._simple_attribute_codes)

        for bindings in self._feature_attribute_bindings.values():
            bindings.update(COMMON_OPTIONAL_ATTRIBUTES)
        all_attrs.update(COMMON_OPTIONAL_ATTRIBUTES)

        for code, attrs in FEATURE_OPTIONAL_ATTRIBUTES.items():
            if code in self._feature_attribute_bindings:
                self._feature_attribute_bindings[code].update(attrs)
                all_attrs.update(attrs)

        for code in BUOY_CODES:
            if code in self._feature_attribute_bindings:
                self._feature_attribute_bindings[code].add("topmark")
                all_attrs.add("topmark")

        self._simple_attribute_codes = sorted(all_attrs)

    def _host_feature_get_code(self, feature_id: str) -> str:
        return self._features[feature_id].code

    def _host_get_feature_type_codes(self):
        self._log_debug(f"[PORTRAY] HostGetFeatureTypeCodes -> {self._feature_type_codes}")
        return self.lua.table_from(self._feature_type_codes)

    def _host_get_simple_attribute_type_codes(self):
        return self.lua.table_from(self._simple_attribute_codes)

    def _host_get_feature_type_info(self, code: str):
        self._log_debug(
            f"[PORTRAY] HostGetFeatureTypeInfo({code}) with bindings {self._feature_attribute_bindings.get(code)}"
        )
        bindings = self.lua.table()
        for attr in sorted(self._feature_attribute_bindings.get(code, [])):
            upper = 10 if attr == "restriction" or attr in MULTIVALUED_ATTRIBUTES else 1
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
        values = feature.to_simple_attribute(attribute_code)

        # Convert numerics to strings only when Lua expects encoded numeric
        # types; keep enumerations numeric so catalogue comparisons succeed.
        value_type = self._attribute_value_types.get(attribute_code)
        if value_type in {"real", "integer"}:
            values = [str(v) if isinstance(v, (int, float)) else v for v in values]
        return self._to_lua_sequence(values)

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
    def _to_lua_value(self, value: Any):
        if isinstance(value, dict):
            tbl = self.lua.table()
            for k, v in value.items():
                tbl[k] = self._to_lua_value(v)
            return tbl
        if isinstance(value, (list, tuple)):
            return self._to_lua_sequence(value)
        return value

    def _to_lua_sequence(self, seq: Iterable[Any]):
        tbl = self.lua.table()
        for idx, item in enumerate(seq, start=1):
            tbl[idx] = self._to_lua_value(item)
        return tbl

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
    def _classify_attribute_value_type(attr: str, value: Any) -> str:
        if attr in ENUMERATED_ATTRIBUTES:
            return "enumeration"
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, (int, float)):
            return "real"
        return "text"

    @staticmethod
    def _infer_attribute_value_types(features: List[FeatureRecord]) -> Dict[str, str]:
        value_types: Dict[str, str] = {}

        for feature in features:
            for attr, raw_value in feature.attributes.items():
                # Preserve strongest numeric classification if mixed types appear.
                new_type = PortrayalHost._classify_attribute_value_type(attr, raw_value)
                current = value_types.get(attr)
                if current == "real":
                    continue
                if current == "boolean" and new_type == "text":
                    continue
                value_types[attr] = new_type

        return value_types


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

        num = _as_int(value)
        if num is None:
            num = _as_float(value)
        fields[key] = num if num is not None else value

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
