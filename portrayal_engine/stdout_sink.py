from __future__ import annotations

"""Stdout sink for drawing instructions."""

import json
import sys
from typing import List

from .host import DrawingSink


class StdoutSink(DrawingSink):
    """Stream drawing instructions to a text stream for inspection."""

    def __init__(
        self,
        *,
        show_raw: bool = True,
        show_parsed: bool = True,
        stream=None,
    ) -> None:
        self.show_raw = show_raw
        self.show_parsed = show_parsed
        self.stream = stream or sys.stdout

    def write(
        self, feature_id: str, raw_instructions: List[str], instructions: List[dict]
    ) -> None:
        if self.show_raw:
            for di in raw_instructions:
                print(f"{feature_id}: {di}", file=self.stream)

        if self.show_parsed:
            for instr in instructions:
                payload = json.dumps(instr, indent=2)
                print(f"{feature_id} (parsed): {payload}", file=self.stream)
