from __future__ import annotations

import logging

from runtools.runtime_hw_config import RuntimeHWConfig, LOCAL_DRIVERS_GENERATED_SRC
from utils.targetprojectutils import resolve_path

from typing import Any, Dict, List, Optional, Sequence, TYPE_CHECKING

if TYPE_CHECKING:
    from runtools.utils import MacAddress
    from runtools.simulation_configs.tracerv import TracerVConfig
    from runtools.simulation_configs.autocounter import AutoCounterConfig
    from runtools.simulation_configs.host_debug import HostDebugConfig
    from runtools.simulation_configs.synth_print import SynthPrintConfig
    from runtools.simulation_configs.partition import PartitionConfig

rootLogger = logging.getLogger()


class RuntimeBuildRecipeConfig(RuntimeHWConfig):
    """A pythonic version of the entires in config_build_recipes.yaml"""

    def __init__(
        self,
        name: str,
        build_recipe_dict: Dict[str, Any],
        build_recipes_config_file: str,
        default_metasim_host_sim: str,
        metasimulation_only_plusargs: str,
        metasimulation_only_vcs_plusargs: str,
    ) -> None:
        self.name = name

        self.agfi = None
        self.bitstream_tar = None
        self.driver_tar = None
        self.tarball_built = False

        self.uri_list = []

        self.deploy_quintuplet = (
            build_recipe_dict.get("PLATFORM", "f1")
            + "-"
            + build_recipe_dict.get("TARGET_PROJECT", "firesim")
            + "-"
            + build_recipe_dict["DESIGN"]
            + "-"
            + build_recipe_dict["TARGET_CONFIG"]
            + "-"
            + build_recipe_dict["PLATFORM_CONFIG"]
        )

        # resolve the path as an absolute path if set
        self.deploy_makefrag = build_recipe_dict.get("TARGET_PROJECT_MAKEFRAG")
        # TODO: rename this since this can either be the hwdb or the build recipes file (in metasim or normal fpga sim)
        self.hwdb_file = build_recipes_config_file
        if self.deploy_makefrag:
            base = build_recipes_config_file
            abs_deploy_makefrag = resolve_path(self.deploy_makefrag, base)
            if abs_deploy_makefrag is None:
                raise Exception(
                    f"Unable to find TARGET_PROJECT_MAKEFRAG ({self.deploy_makefrag}) either as an absolute path or relative to {base}"
                )
            else:
                self.deploy_makefrag = abs_deploy_makefrag

        self.customruntimeconfig = build_recipe_dict["metasim_customruntimeconfig"]
        # note whether we've built a copy of the simulation driver for this hwconf
        self.driver_built = False
        self.metasim_host_simulator = default_metasim_host_sim

        # currently only f1 metasims supported
        self.platform = build_recipe_dict.get("PLATFORM", "f1")
        self.driver_name_prefix = ""
        if self.metasim_host_simulator in ["verilator", "verilator-debug"]:
            self.driver_name_prefix = "V"

        self.local_driver_base_dir = LOCAL_DRIVERS_GENERATED_SRC

        self.driver_type_message = "Metasim"

        self.metasimulation_only_plusargs = metasimulation_only_plusargs
        self.metasimulation_only_vcs_plusargs = metasimulation_only_vcs_plusargs

        self.additional_required_files = []

        if self.metasim_host_simulator in ["vcs", "vcs-debug"]:
            self.additional_required_files.append(
                (self.get_local_driver_path() + ".daidir", "")
            )

    def get_driver_name_suffix(self) -> str:
        driver_name_suffix = ""
        if self.metasim_host_simulator in ["verilator-debug", "vcs-debug"]:
            driver_name_suffix = "-debug"
        return driver_name_suffix

    def get_driver_build_target(self) -> str:
        return self.metasim_host_simulator

    def get_boot_simulation_command(
        self,
        slotid: int,
        all_macs: Sequence[MacAddress],
        all_rootfses: Sequence[Optional[str]],
        all_linklatencies: Sequence[int],
        all_netbws: Sequence[int],
        profile_interval: int,
        all_bootbinaries: List[str],
        all_shmemportnames: List[str],
        tracerv_config: TracerVConfig,
        autocounter_config: AutoCounterConfig,
        hostdebug_config: HostDebugConfig,
        synthprint_config: SynthPrintConfig,
        partition_config: PartitionConfig,
        cutbridge_idxs: List[int],
        extra_plusargs: str,
        extra_args: str,
    ) -> str:
        """return the command used to boot the meta simulation."""
        full_extra_plusargs = (
            " " + self.metasimulation_only_plusargs + " " + extra_plusargs
        )
        if self.metasim_host_simulator in ["vcs", "vcs-debug"]:
            full_extra_plusargs = (
                " " + self.metasimulation_only_vcs_plusargs + " " + full_extra_plusargs
            )
        if self.metasim_host_simulator == "verilator-debug":
            full_extra_plusargs += " +waveformfile=metasim_waveform.vcd "
        if self.metasim_host_simulator == "vcs-debug":
            full_extra_plusargs += " +fsdbfile=metasim_waveform.fsdb "
        # TODO: spike-dasm support
        full_extra_args = " 2> metasim_stderr.out " + extra_args
        return super(RuntimeBuildRecipeConfig, self).get_boot_simulation_command(
            slotid,
            all_macs,
            all_rootfses,
            all_linklatencies,
            all_netbws,
            profile_interval,
            all_bootbinaries,
            all_shmemportnames,
            tracerv_config,
            autocounter_config,
            hostdebug_config,
            synthprint_config,
            partition_config,
            cutbridge_idxs,
            full_extra_plusargs,
            full_extra_args,
        )
