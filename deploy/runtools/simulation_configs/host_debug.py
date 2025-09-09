from __future__ import annotations

from dataclasses import dataclass

from typing import Dict, Any


@dataclass
class HostDebugConfig:
    zero_out_dram: bool
    disable_synth_asserts: bool

    def __init__(self, args: Dict[str, Any]) -> None:
        self.zero_out_dram = args.get("zero_out_dram", False) == True
        self.disable_synth_asserts = args.get("disable_synth_asserts", False) == True
