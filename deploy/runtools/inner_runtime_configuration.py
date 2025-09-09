from __future__ import annotations

import logging
import yaml
import pprint
from absl import flags
from datetime import timedelta

from runtools.run_farm import RunFarm
from .simulation_configs.tracerv import TracerVConfig
from .simulation_configs.autocounter import AutoCounterConfig
from .simulation_configs.host_debug import HostDebugConfig
from .simulation_configs.synth_print import SynthPrintConfig
from .simulation_configs.partition import PartitionConfig

from util.inheritors import inheritors
from util.deepmerge import deep_merge

from typing import Optional

rootLogger = logging.getLogger()
FLAGS = flags.FLAGS


class InnerRuntimeConfiguration:
    """Pythonic version of config_runtime.yaml"""

    run_farm_requested_name: str
    run_farm_dispatcher: RunFarm
    topology: str
    no_net_num_nodes: int
    linklatency: int
    switchinglatency: int
    netbandwidth: int
    profileinterval: int
    launch_timeout: timedelta
    always_expand: bool
    tracerv_config: TracerVConfig
    autocounter_config: AutoCounterConfig
    hostdebug_config: HostDebugConfig
    synthprint_config: SynthPrintConfig
    partition_config: PartitionConfig
    workload_name: str
    suffixtag: Optional[str]
    terminateoncompletion: bool
    metasimulation_enabled: bool
    metasimulation_host_simulator: str
    metasimulation_only_plusargs: str
    metasimulation_only_vcs_plusargs: str
    default_plusarg_passthrough: str

    def __init__(self) -> None:

        runtime_configfile = None
        with open(FLAGS.runtimeconfigfile, "r") as yaml_file:
            runtime_configfile = yaml.safe_load(yaml_file)

        runtime_dict = runtime_configfile

        # override parts of the runtime conf if specified
        if FLAGS.overrideconfigdata != "":
            ## handle overriding part of the runtime conf
            configoverrideval = FLAGS.overrideconfigdata.split()
            overridesection = configoverrideval[0]
            overridefield = configoverrideval[1]
            overridevalue = configoverrideval[2]
            rootLogger.warning("Overriding part of the runtime config with: ")
            rootLogger.warning(f'"[{overridesection}]"')
            rootLogger.warning(f"{overridefield}={overridevalue}")
            runtime_dict[overridesection][overridefield] = overridevalue

        def dict_assert(key_check, dict_name):
            assert (
                key_check in dict_name
            ), f"FAIL: missing {key_check} in runtime config."

        dict_assert("metasimulation", runtime_dict)
        metasim_dict = runtime_dict["metasimulation"]
        dict_assert("metasimulation_enabled", metasim_dict)
        self.metasimulation_enabled = metasim_dict["metasimulation_enabled"]
        dict_assert("metasimulation_host_simulator", metasim_dict)
        self.metasimulation_host_simulator = metasim_dict[
            "metasimulation_host_simulator"
        ]
        dict_assert("metasimulation_only_plusargs", metasim_dict)
        self.metasimulation_only_plusargs = metasim_dict["metasimulation_only_plusargs"]
        dict_assert("metasimulation_only_vcs_plusargs", metasim_dict)
        self.metasimulation_only_vcs_plusargs = metasim_dict[
            "metasimulation_only_vcs_plusargs"
        ]

        # Setup the run farm
        defaults_file = runtime_dict["run_farm"]["base_recipe"]
        with open(defaults_file, "r") as yaml_file:
            run_farm_configfile = yaml.safe_load(yaml_file)
        run_farm_type = run_farm_configfile["run_farm_type"]
        run_farm_args = run_farm_configfile["args"]

        # add the overrides if it exists

        override_args = runtime_dict["run_farm"].get("recipe_arg_overrides")
        if override_args:
            run_farm_args = deep_merge(run_farm_args, override_args)

        run_farm_dispatch_dict = dict([(x.__name__, x) for x in inheritors(RunFarm)])

        if not run_farm_type in run_farm_dispatch_dict:
            raise Exception(
                f"Unable to find {run_farm_type} in available run farm classes: {run_farm_dispatch_dict.keys()}"
            )

        # create dispatcher object using class given and pass args to it
        self.run_farm_dispatcher = run_farm_dispatch_dict[run_farm_type](
            run_farm_args, self.metasimulation_enabled
        )

        self.topology = runtime_dict["target_config"]["topology"]
        self.no_net_num_nodes = int(runtime_dict["target_config"]["no_net_num_nodes"])
        self.linklatency = int(runtime_dict["target_config"]["link_latency"])
        self.switchinglatency = int(runtime_dict["target_config"]["switching_latency"])
        self.netbandwidth = int(runtime_dict["target_config"]["net_bandwidth"])
        self.profileinterval = int(runtime_dict["target_config"]["profile_interval"])
        self.defaulthwconfig = runtime_dict["target_config"]["default_hw_config"]

        self.tracerv_config = TracerVConfig(runtime_dict.get("tracing", {}))
        self.autocounter_config = AutoCounterConfig(runtime_dict.get("autocounter", {}))
        self.hostdebug_config = HostDebugConfig(runtime_dict.get("host_debug", {}))
        self.synthprint_config = SynthPrintConfig(runtime_dict.get("synth_print", {}))
        self.partition_config = PartitionConfig()

        dict_assert("plusarg_passthrough", runtime_dict["target_config"])
        self.default_plusarg_passthrough = runtime_dict["target_config"][
            "plusarg_passthrough"
        ]

        self.workload_name = runtime_dict["workload"]["workload_name"]
        # an extra tag to differentiate workloads with the same name in results names
        self.suffixtag = (
            runtime_dict["workload"]["suffix_tag"]
            if "suffix_tag" in runtime_dict["workload"]
            else None
        )
        self.terminateoncompletion = (
            runtime_dict["workload"]["terminate_on_completion"] == True
        )

    def __str__(self) -> str:
        return pprint.pformat(vars(self))
