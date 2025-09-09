from __future__ import annotations

from dataclasses import dataclass

from typing import Dict, Any


@dataclass
class SynthPrintConfig:
    start: str
    end: str
    cycle_prefix: bool

    def __init__(self, args: Dict[str, Any]) -> None:
        self.start = args.get("start", "0")
        self.end = args.get("end", "-1")
        self.cycle_prefix = args.get("cycle_prefix", True) == True
