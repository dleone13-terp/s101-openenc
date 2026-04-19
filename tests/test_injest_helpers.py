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


def test_prepare_attributes_obstrn_maps_hazard_and_universal_fields():
    mapped, stored, unmapped, associations = prepare_attributes(
        "OBSTRN",
        "Obstruction",
        {
            "VALSOU": 3.2,
            "WATLEV": 5,
            "CATOBS": 2,
            "OBJNAM": "Foo Shoal",
            "INFORM": "Small obstruction",
            "LNAM_REFS": "a,b",
        },
        depth_z=None,
    )

    assert mapped["valueOfSounding"] == 3.2
    assert mapped["waterLevelEffect"] == 5
    assert mapped["categoryOfObstruction"] == 2
    assert mapped["featureName"] == [{"name": "Foo Shoal", "nameUsage": 1}]
    assert mapped["information"] == "Small obstruction"
    assert "defaultClearanceDepth" not in mapped
    assert len(unmapped) == 0
    assert len(associations) == 2
    assert stored["associations"][0]["target_foid"] == "a"


def test_prepare_attributes_universal_objnam_and_inform_on_land_area():
    mapped, stored, unmapped, associations = prepare_attributes(
        "LNDARE",
        "LandArea",
        {
            "OBJNAM": "Cape Test",
            "INFORM": "Example land area",
        },
        depth_z=None,
    )

    assert mapped["featureName"] == [{"name": "Cape Test", "nameUsage": 1}]
    assert mapped["information"] == "Example land area"
    assert len(unmapped) == 0
    assert associations == []
    assert stored["featureName"] == [{"name": "Cape Test", "nameUsage": 1}]


def test_prepare_attributes_land_area_without_objnam_has_empty_feature_name():
    mapped, stored, unmapped, associations = prepare_attributes(
        "LNDARE",
        "LandArea",
        {},
        depth_z=None,
    )

    assert mapped["featureName"] == []
    assert stored["featureName"] == []
    assert len(unmapped) == 0
    assert associations == []


def test_prepare_attributes_wrecks_maps_soundings_and_quality():
    mapped, stored, unmapped, associations = prepare_attributes(
        "WRECKS",
        "Wreck",
        {
            "VALSOU": 18.4,
            "WATLEV": 3,
            "CATWRK": 4,
            "EXPSOU": 2,
            "OBJNAM": "Example Wreck",
        },
        depth_z=None,
    )

    assert mapped["valueOfSounding"] == 18.4
    assert mapped["waterLevelEffect"] == 3
    assert mapped["categoryOfWreck"] == 4
    assert mapped["qualityOfSoundingMeasurement"] == 2
    assert mapped["featureName"] == [{"name": "Example Wreck", "nameUsage": 1}]
    assert "defaultClearanceDepth" not in mapped
    assert len(unmapped) == 0
    assert associations == []


def test_prepare_attributes_dredged_area_includes_date_and_depths():
    mapped, stored, unmapped, associations = prepare_attributes(
        "DRGARE",
        "DredgedArea",
        {
            "DRVAL1": 8.5,
            "DRVAL2": 10.0,
            "DREDGE": "20230115",
            "SORDAT": "20230101",
        },
        depth_z=None,
    )

    assert mapped["depthRangeMinimumValue"] == 8.5
    assert mapped["depthRangeMaximumValue"] == 10.0
    assert mapped["dredgedDate"] == "20230115"
    assert mapped["date"] == "20230101"
    assert stored["date"] == "20230101"
    assert len(unmapped) == 0
    assert associations == []


def test_prepare_attributes_lateral_buoy_collects_colour_array():
    mapped, stored, unmapped, associations = prepare_attributes(
        "BOYLAT",
        "LateralBuoy",
        {
            "BOYSHP": 3,
            "CATLAM": 1,
            "COLOUR": "3",
            "COLOUR2": "4",
            "COLOUR3": "5",
            "OBJNAM": "Test Buoy",
        },
        depth_z=None,
    )

    assert mapped["buoyShape"] == 3
    assert mapped["categoryOfLateralMark"] == 1
    assert mapped["colour"] == [3, 4, 5]
    assert mapped["featureName"] == [{"name": "Test Buoy", "nameUsage": 1}]
    assert len(unmapped) == 0
    assert associations == []
