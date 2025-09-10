""" This file manages the overall configuration of the system for running
simulation tasks. """

from __future__ import annotations

import logging
from absl import flags
from time import strftime, gmtime

from typing import Tuple, List

from runtools.runtime_hwdb import RuntimeHWDB
from runtools.inner_runtime_configuration import InnerRuntimeConfiguration
from runtools.run_farm import RunFarm
from runtools.workload import WorkloadConfig
from runtools.topology.core_with_passes import FireSimTopologyWithPasses
from runtools.runtime_build_recipes import RuntimeBuildRecipes

rootLogger = logging.getLogger()

FLAGS = flags.FLAGS

flags.DEFINE_string(
    "runtimeconfigfile",
    "config_runtime.yaml",
    "Optional custom runtime/workload config file.",
)
flags.DEFINE_string(
    "hwdbconfigfile", "config_hwdb.yaml", "Optional custom HW database config file."
)
flags.DEFINE_string(
    "overrideconfigdata",
    "",
    'Override a single value from one of the the RUNTIME e.g.: --overrideconfigdata "target-config link-latency 6405".',
)

flags.DEFINE_multi_string(
    "terminatesome",
    [],
    "Only used by terminaterunfarm. Used to specify a restriction on how many instances to terminate. E.g., --terminatesome=f1.2xlarge:2 will terminate only 2 of the f1.2xlarge instances in the runfarm, regardless of what other instances are in the runfarm. This argument can be specified multiple times to terminate additional instance types/counts. Behavior when specifying the same instance type multiple times is undefined.",
)


def terminatesomesplitter(raw_arg: str) -> Tuple[str, int]:
    """Splits a string of form 'instance_type:count' into a tuple."""
    split_arg = raw_arg.split(":")
    if len(split_arg) != 2:
        raise ValueError("Argument must be of form 'instance_type:count'")
    try:
        count = int(split_arg[1])
    except ValueError as e:
        raise ValueError(f"Count in '{raw_arg}' is not an integer.") from e
    return split_arg[0], count


@flags.validator("terminatesome")
def _check_terminatesome(terminatesome_list: List[str]) -> bool:
    """Ensures --terminatesome flags are formatted correctly."""
    for terminatesome_arg in terminatesome_list:
        try:
            terminatesomesplitter(terminatesome_arg)
        except ValueError as e:
            raise flags.ValidationError(
                f"Invalid --terminatesome value: '{terminatesome_arg}'. {e}"
            )
    return True


class RuntimeConfig:
    """This class manages the overall configuration of the manager for running
    simulation tasks."""

    launch_time: str
    runtimehwdb: RuntimeHWDB
    innerconf: InnerRuntimeConfiguration
    run_farm: RunFarm
    workload: WorkloadConfig
    firesim_topology_with_passes: FireSimTopologyWithPasses
    runtime_build_recipes: RuntimeBuildRecipes

    def __init__(self) -> None:
        """This reads runtime configuration files, massages them into formats that
        the rest of the manager expects, and keeps track of other info."""
        self.launch_time = strftime("%Y-%m-%d--%H-%M-%S", gmtime())

        # construct pythonic db of hardware configurations available to us at
        # runtime.
        self.runtimehwdb = RuntimeHWDB(FLAGS.hwdbconfigfile)
        rootLogger.debug(self.runtimehwdb)

        self.innerconf = InnerRuntimeConfiguration()
        rootLogger.debug(self.innerconf)

        self.runtime_build_recipes = RuntimeBuildRecipes(
            FLAGS.buildrecipesconfigfile,
            self.innerconf.metasimulation_host_simulator,
            self.innerconf.metasimulation_only_plusargs,
            self.innerconf.metasimulation_only_vcs_plusargs,
        )
        rootLogger.debug(self.runtime_build_recipes)

        self.run_farm = self.innerconf.run_farm_dispatcher

        # setup workload config obj, aka a list of workloads that can be assigned
        # to a server
        if FLAGS.task != "enumeratefpgas":
            self.workload = WorkloadConfig(
                self.innerconf.workload_name, self.launch_time, self.innerconf.suffixtag
            )
        else:
            self.workload = WorkloadConfig(
                "null.json", self.launch_time, self.innerconf.suffixtag
            )

        # start constructing the target configuration tree
        self.firesim_topology_with_passes = FireSimTopologyWithPasses(
            self.innerconf.topology,
            self.innerconf.no_net_num_nodes,
            self.run_farm,
            self.runtimehwdb,
            self.innerconf.defaulthwconfig,
            self.workload,
            self.innerconf.linklatency,
            self.innerconf.switchinglatency,
            self.innerconf.netbandwidth,
            self.innerconf.profileinterval,
            self.innerconf.tracerv_config,
            self.innerconf.autocounter_config,
            self.innerconf.hostdebug_config,
            self.innerconf.synthprint_config,
            self.innerconf.partition_config,
            self.innerconf.terminateoncompletion,
            self.runtime_build_recipes,
            self.innerconf.metasimulation_enabled,
            self.innerconf.default_plusarg_passthrough,
        )

    def launch_run_farm(self) -> None:
        """directly called by top-level launchrunfarm command."""
        self.run_farm.launch_run_farm()

    def terminate_run_farm(self) -> None:
        """directly called by top-level terminaterunfarm command."""
        terminate_some_dict = {}
        if FLAGS.terminatesome:
            for pair in FLAGS.terminatesome:
                key, val = terminatesomesplitter(pair)
                terminate_some_dict[key] = val
        self.run_farm.terminate_run_farm(terminate_some_dict, FLAGS.forceterminate)

    def infrasetup(self) -> None:
        """directly called by top-level infrasetup command."""
        # set this to True if you want to use mock boto3 instances for testing
        # the manager.
        use_mock_instances_for_testing = False
        self.firesim_topology_with_passes.infrasetup_passes(
            use_mock_instances_for_testing
        )

    def build_driver(self) -> None:
        """directly called by top-level builddriver command."""
        self.firesim_topology_with_passes.build_driver_passes()

    def enumerate_fpgas(self) -> None:
        """directly called by top-level enumeratefpgas command."""
        use_mock_instances_for_testing = False
        self.firesim_topology_with_passes.enumerate_fpgas_passes(
            use_mock_instances_for_testing
        )

    def boot(self) -> None:
        """directly called by top-level boot command."""
        use_mock_instances_for_testing = False
        self.firesim_topology_with_passes.boot_simulation_passes(
            use_mock_instances_for_testing
        )

    def kill(self) -> None:
        use_mock_instances_for_testing = False
        self.firesim_topology_with_passes.kill_simulation_passes(
            use_mock_instances_for_testing
        )

    def run_workload(self) -> None:
        use_mock_instances_for_testing = False
        self.firesim_topology_with_passes.run_workload_passes(
            use_mock_instances_for_testing
        )
