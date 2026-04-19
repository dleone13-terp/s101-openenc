from injest.helpers import prepare_attributes
from portrayal_engine.host import FeatureRecord, PortrayalHost


def test_land_area_portrayal_handles_structured_feature_name():
    mapped, _, _, _ = prepare_attributes(
        "LNDARE",
        "LandArea",
        {"OBJNAM": "Cape Test"},
        depth_z=None,
    )

    host = PortrayalHost()
    feature = FeatureRecord(
        feature_id="LNDARE:test",
        code="LandArea",
        primitive="Surface",
        attributes=mapped,
    )

    result = host.portray_with_json([feature])
    parsed_instr = result.parsed_json.get("LNDARE:test", [])

    assert parsed_instr
    assert parsed_instr[0].get("ViewingGroup") == 12010
    assert parsed_instr[0].get("ColorFill") == "LANDA"
