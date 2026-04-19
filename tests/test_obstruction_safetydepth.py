from portrayal_engine.host import FeatureRecord, PortrayalHost


def _instructions_for(host: PortrayalHost, feature: FeatureRecord) -> list[str]:
    raw = host.portray([feature]).get(feature.feature_id, [])
    return [entry for entry in raw if entry]


def _has_instruction(raw_instructions: list[str], needle: str) -> bool:
    return any(needle in entry for entry in raw_instructions)


def test_obstruction_point_zero_sounding_exposed_changes_with_safetydepth() -> None:
    feature = FeatureRecord(
        feature_id="obs-point-1",
        code="Obstruction",
        primitive="Point",
        attributes={
            "valueOfSounding": 0.0,
            "waterLevelEffect": 1,
            "categoryOfObstruction": 1,
        },
    )

    conservative = PortrayalHost(context={"SafetyDepth": -100.0})
    updated = PortrayalHost(context={"SafetyDepth": 0.0})

    conservative_raw = _instructions_for(conservative, feature)
    updated_raw = _instructions_for(updated, feature)

    # Historical -100 SafetyDepth can route this edge case to unknown mark.
    assert _has_instruction(conservative_raw, "PointInstruction:QUESMRK1")
    assert _has_instruction(updated_raw, "PointInstruction:OBSTRN11")


def test_obstruction_point_submerged_hazard_path_unchanged_by_safetydepth() -> None:
    feature = FeatureRecord(
        feature_id="obs-point-2",
        code="Obstruction",
        primitive="Point",
        attributes={
            "valueOfSounding": 2.0,
            "waterLevelEffect": 5,
            "categoryOfObstruction": 1,
        },
    )

    conservative = PortrayalHost(context={"SafetyDepth": -100.0})
    updated = PortrayalHost(context={"SafetyDepth": 0.0})

    conservative_raw = _instructions_for(conservative, feature)
    updated_raw = _instructions_for(updated, feature)

    # Most obstruction symbolization is dominated by SafetyContour/categorical
    # branches, so this common submerged case should not change.
    assert conservative_raw == updated_raw
    assert _has_instruction(updated_raw, "PointInstruction:ISODGR01")
