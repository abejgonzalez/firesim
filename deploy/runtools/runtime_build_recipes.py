from __future__ import annotations

import yaml

from .runtime_hw_db import RuntimeHWDB
from .runtime_build_recipe_config import RuntimeBuildRecipeConfig


class RuntimeBuildRecipes(RuntimeHWDB):
    """Same as RuntimeHWDB, but use information from build recipes entries
    instead of hwdb for metasimulation."""

    def __init__(
        self,
        build_recipes_config_file: str,
        metasim_host_simulator: str,
        metasimulation_only_plusargs: str,
        metasimulation_only_vcs_plusargs: str,
    ) -> None:
        self.config_file_name = build_recipes_config_file
        self.simulation_mode_string = "Metasimulation"

        recipes_configfile = None
        with open(build_recipes_config_file, "r") as yaml_file:
            recipes_configfile = yaml.safe_load(yaml_file)

        recipes_dict = recipes_configfile

        self.hwconf_dict = {
            s: RuntimeBuildRecipeConfig(
                s,
                v,
                build_recipes_config_file,
                metasim_host_simulator,
                metasimulation_only_plusargs,
                metasimulation_only_vcs_plusargs,
            )
            for s, v in recipes_dict.items()
        }
