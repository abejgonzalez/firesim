from __future__ import annotations

from dataclasses import dataclass

from typing import Dict, Any


@dataclass
class AutoCounterConfig:
    readrate: int

    def __init__(self, args: Dict[str, Any]) -> None:
        self.readrate = int(args.get("read_rate", "0"))
