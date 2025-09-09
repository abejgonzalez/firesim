from __future__ import annotations

from dataclasses import dataclass

from typing import Dict, Any


@dataclass
class TracerVConfig:
    enable: bool
    select: str
    start: str
    end: str
    output_format: str

    def __init__(self, args: Dict[str, Any]) -> None:
        self.enable = args.get("enable", False) == True
        self.select = args.get("selector", "0")
        self.start = args.get("start", "0")
        self.end = args.get("end", "-1")
        self.output_format = args.get("output_format", "0")
