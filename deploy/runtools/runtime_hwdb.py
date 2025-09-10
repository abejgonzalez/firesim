from __future__ import annotations

import pprint
import yaml

from runtools.runtime_hw_config import RuntimeHWConfig

from typing import Dict


class RuntimeHWDB:
    """This class manages the hardware configurations that are available
    as endpoints on the simulation."""

    hwconf_dict: Dict[str, RuntimeHWConfig]
    config_file_name: str
    simulation_mode_string: str

    def __init__(self, hardwaredbconfigfile: str) -> None:
        self.config_file_name = hardwaredbconfigfile
        self.simulation_mode_string = "FPGA simulation"

        agfidb_configfile = None
        with open(hardwaredbconfigfile, "r") as yaml_file:
            agfidb_configfile = yaml.safe_load(yaml_file)

        agfidb_dict = agfidb_configfile

        self.hwconf_dict = {
            s: RuntimeHWConfig(s, v, hardwaredbconfigfile)
            for s, v in agfidb_dict.items()
        }

    def keyerror_message(self, name: str) -> str:
        """Return the error message for lookup errors."""
        return f"'{name}' not found in '{self.config_file_name}', which is used to specify target design descriptions for {self.simulation_mode_string}s."

    def get_runtimehwconfig_from_name(self, name: str) -> RuntimeHWConfig:
        if name not in self.hwconf_dict:
            raise KeyError(self.keyerror_message(name))
        return self.hwconf_dict[name]

    def __str__(self) -> str:
        return pprint.pformat(vars(self))
