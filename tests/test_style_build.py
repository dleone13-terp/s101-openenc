from __future__ import annotations

import json

from style.build_style import build_all_styles, collect_tokens


def test_collect_tokens_reads_instruction_fields():
    payload = {
        "feat-1": [
            {"ColorFill": "DEPVS", "LineColor": "CHGRD", "PointInstruction": "BOYCAR01"},
            {"FontColor": "CHBLK"},
        ]
    }

    tokens = collect_tokens(payload)

    assert "DEPVS" in tokens["fill"]
    assert "CHGRD" in tokens["line"]
    assert "CHBLK" in tokens["font"]
    assert "BOYCAR01" in tokens["point_symbols"]


def test_build_all_styles_writes_three_outputs(tmp_path):
    outputs = build_all_styles(out_dir=tmp_path, tokens_payload={"f": [{"ColorFill": "DEPVS"}]})

    assert len(outputs) == 3
    day = tmp_path / "enc-day.json"
    assert day.exists()
    data = json.loads(day.read_text(encoding="utf-8"))
    assert data["version"] == 8
    assert any(layer["id"] == "enc-area-fill" for layer in data["layers"])

