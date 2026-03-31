from injest.helpers import apply_depth_enrichment, extract_associations, prepare_attributes, strip_meta_fields


def test_strip_meta_and_associations():
    raw = {
        "RCID": 5,
        "LNAM": "abc",
        "LNAM_REFS": "foo,bar",
        "DRVAL1": 12.0,
    }

    cleaned = strip_meta_fields(raw)
    assert "RCID" not in cleaned
    assert "LNAM" not in cleaned

    associations = extract_associations(cleaned)
    assert cleaned == {"DRVAL1": 12.0}
    assert [a["target_foid"] for a in associations] == ["foo", "bar"]


def test_apply_depth_enrichment_soundg_and_hazard():
    soundg = apply_depth_enrichment("SOUNDG", "DepthArea", {}, 1.5)
    assert soundg["valueOfSounding"] == 1.5

    hazard = apply_depth_enrichment("OBSTRN", "Obstruction", {}, None)
    assert hazard["defaultClearanceDepth"] == 0.0


def test_prepare_attributes_maps_and_preserves_associations():
    mapped, stored, unmapped, associations = prepare_attributes(
        "DEPARE",
        "DepthArea",
        {"DRVAL1": 2.0, "RCID": 99, "LNAM_REFS": ["x", "y"]},
        depth_z=None,
    )

    assert mapped["depthRangeMinimumValue"] == 2.0
    assert "RCID" not in stored
    assert len(unmapped) == 0
    assert len(associations) == 2
    assert stored["associations"][0]["target_foid"] == "x"
