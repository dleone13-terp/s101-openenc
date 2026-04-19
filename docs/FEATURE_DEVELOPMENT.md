# Feature Development Guide (LLM-oriented)

This guide explains how to add support for new S-57 features in this repository without modifying the upstream portrayal catalogue.

## Pipeline recap
- Ingestion entrypoint: `injest/s57_to_s101.py` loads S-57 cells, maps objects/attributes, runs portrayal, and writes to PostGIS.
- Mapping layer: `injest/mappings.py` converts S-57 codes to S-101 feature codes and attribute names; unknowns are dropped unless explicitly carried through.
- Attribute prep: `injest/helpers.py` cleans metadata, normalizes `featureName`, adds hazard defaults, and attaches associations before storage/portrayal.
- Portrayal host: `portrayal_engine/host.py` feeds structured attributes into the Lua catalogue and parses drawing instructions; do not edit catalogue rules.
- Tests: `tests/` holds unit and integration coverage for mappings, helpers, and portrayal host behavior.

## Adding a new S-57 feature
1) Map the feature code
- Add the S-57 object acronym to `FEATURE_MAP` in `injest/mappings.py`, pointing to the correct S-101 code and primitive. Use `None` to preserve the incoming primitive when S-57 allows multiple.

2) Map attributes
- Extend `ATTRIBUTE_MAP` for that S-57 code with Annex A attribute crosswalks. Keep keys uppercase, values camelCase S-101 names.
- If an attribute should be globally ignored, add it to `DROP_ATTRIBUTES`.
- Global fields `OBJNAM` → `featureName` and `INFORM` → `information` are already handled; no extra work needed.

3) Validate attribute shapes
- `prepare_attributes()` in `injest/helpers.py` normalizes `featureName` into a list of tables (`[{"name": "…", "nameUsage": 1, ...}]`) so Lua rules can index `feature.featureName[1].name` safely.
- Hazard features get default clearance depth when none is present; depth Z is also injected where applicable.

4) Keep portrayal catalogue untouched
- The Lua catalogue in `portrayal/PortrayalCatalog/Rules/` should not be edited. If a rule expects optional attributes, ensure the host provides them via helpers/host bindings instead of changing Lua.

5) Add tests
- Unit tests: add mapping/helper coverage in `tests/test_injest_helpers.py` (and new files as needed) to confirm attribute normalization and hazard logic.
- Portrayal tests: add a minimal `FeatureRecord` case (see `tests/test_feature_name_portrayal.py`) to ensure the host returns valid DEF/parsed instructions for the new feature.
- Integration: if geometry or DB write paths are affected, extend existing integration tests under `tests/` or add new ones.

6) Run checks
- Fast loop: `python -m pytest tests/test_injest_helpers.py tests/test_feature_name_portrayal.py`
- Full suite: `python -m pytest`
- End-to-end (requires Postgres env): `.venv/bin/python -m injest.s57_to_s101 test_encs/US3WA01M/US3WA01M.000 --apply`

## Debugging tips
- If portrayal falls back to default symbology, check the host bindings in `portrayal_engine/host.py` to ensure expected optional attributes exist.
- When JSON insertion fails, confirm floats are finite; `_sanitize` in `injest/s57_to_s101.py` handles NaN/Infinity.
- Avoid touching topology/info coverages listed in `SKIP_LAYERS` inside `injest/s57_to_s101.py` unless you also add catalogue coverage.

## Checklist (copy/paste)
- [ ] Added S-57 code to `FEATURE_MAP`
- [ ] Added attribute crosswalk entries
- [ ] Confirmed `featureName`/`information` handling is adequate
- [ ] Added/updated unit tests
- [ ] Added portrayal host regression (if applicable)
- [ ] Ran pytest locally
- [ ] Ran ingestion against sample cell with `--apply` and validated with psql that the drawing instructions looked good
