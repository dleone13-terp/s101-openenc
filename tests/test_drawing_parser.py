from portrayal_engine.host import parse_drawing_instruction


def test_parse_core_fields():
    di = parse_drawing_instruction(
        "ViewingGroup:13030;DrawingPriority:3;DisplayPlane:UnderRadar;"
        "AreaFillReference:PRTSUR01;ColorFill:NODTA;LineStyle:SOLD;LineColor:CHGRD"
    )

    assert di["ViewingGroup"] == 13030
    assert di["DrawingPriority"] == 3
    assert di["DisplayPlane"] == "UnderRadar"
    assert di["AreaFillReference"] == "PRTSUR01"
    assert di["ColorFill"] == "NODTA"
    assert di["LineStyle"] == "SOLD"
    assert di["LineColor"] == "CHGRD"


def test_parse_unknown_tokens_and_numbers():
    di = parse_drawing_instruction("LineWidth:0.5;Foo:Bar;LooseToken")

    assert di["LineWidth"] == 0.5
    assert di["Foo"] == "Bar"
    assert di["LooseToken"] == ""


def test_parse_dash_and_text_fields():
    di = parse_drawing_instruction(
        "Dash:0,0.6;ColorFill:NODTA,0.5;TextInstruction:WRECK;"
        "TextAlignHorizontal:left;LocalOffset:1.0,2.0;Rotation:45;FontColor:CHBLK;FontSize:3.5"
    )

    assert di["Dash"] == "0,0.6"
    assert di["ColorFill"] == "NODTA,0.5"
    assert di["TextInstruction"] == "WRECK"
    assert di["TextAlignHorizontal"] == "left"
    assert di["LocalOffset"] == "1.0,2.0"
    assert di["Rotation"] == 45
    assert di["FontColor"] == "CHBLK"
    assert di["FontSize"] == 3.5
