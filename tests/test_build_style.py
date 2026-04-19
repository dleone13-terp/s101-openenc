from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path


def _load_build_style_module():
    file_path = Path(__file__).resolve().parents[1] / "style" / "build_style.py"
    spec = importlib.util.spec_from_file_location("build_style", file_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dash_token_to_dasharray():
    module = _load_build_style_module()

    assert module.dash_token_to_dasharray("0,0.6") == [1.0, 1.8]
    assert module.dash_token_to_dasharray("0,3.6") == [5.4, 3.6]
    assert module.dash_token_to_dasharray("invalid") is None


def test_build_style_contains_extended_layers():
    module = _load_build_style_module()

    args = argparse.Namespace(
        default_line_width=0.32,
        tiles_base_url="http://localhost:3000",
        area_layer="enc_area",
        line_layer="enc_line",
        point_layer="enc_point",
        default_zoom=8.5,
        sprite_base_url="/sprites/out",
    )

    style = module.build_style(
        palette="day",
        colors={"NODTA": "#93AEBB", "DEPCN": "#768C97", "CHBLK": "#101010"},
        fill_tokens=["NODTA"],
        area_pattern_tokens=["PRTSUR01"],
        line_tokens=["DEPCN"],
        dash_tokens=["0,3.6"],
        point_symbols=["QUESMRK1"],
        center=[0.0, 0.0],
        args=args,
    )

    layer_ids = [layer["id"] for layer in style["layers"]]
    assert "enc-area-pattern" in layer_ids
    assert "enc-point-symbol" in layer_ids
    assert "enc-point-text" in layer_ids
    assert style["sprite"] == "/sprites/out/day"
