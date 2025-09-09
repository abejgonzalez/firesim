from __future__ import annotations

import logging
import abc
import os

from util.inheritors import inheritors

from typing import Any, Dict, Type, Optional, List, Union, Tuple, TYPE_CHECKING
from mypy_boto3_ec2.service_resource import Instance as EC2InstanceResource
from runtools.instance_deploy_manager import InstanceDeployManager
from runtools.topology.elements import (
    FireSimPipeNode,
    FireSimSwitchNode,
    FireSimServerNode,
)

if TYPE_CHECKING:
    from awstools.awstools import MockBoto3Instance
    from runtools.topology.elements import FireSimSwitchNode, FireSimServerNode

rootLogger = logging.getLogger()


class RunHost(metaclass=abc.ABCMeta):
    """Run farm hosts that can hold simulations or switches.

    Attributes:
        run_farm: handle to run farm this instance is a part of
        MAX_SWITCH_AND_PIPE_SLOTS_ALLOWED: max switch slots allowed (hardcoded)
        switch_slots: switch node slots
        _next_switch_port: next switch port to assign
        MAX_SIM_SLOTS_ALLOWED: max simulations allowed. given by `config_runfarm.yaml`
        sim_slots: simulation node slots
        sim_dir: name of simulation directory on the run host
        instance_deploy_manager: platform specific implementation
        host: hostname or ip address of the instance
        metasimulation_enabled: true if this instance will be running metasimulations
    """

    run_farm: RunFarm

    # switch variables
    # restricted by default security group network model port alloc (10000 to 11000)
    MAX_SWITCH_AND_PIPE_SLOTS_ALLOWED: int = 1000
    switch_slots: List[FireSimSwitchNode]
    _next_switch_port: int

    # pipe variables
    pipe_slots: List[FireSimPipeNode]

    # simulation variables (e.g. maximum supported number of {fpga,meta}-sims)
    MAX_SIM_SLOTS_ALLOWED: int
    sim_slots: List[FireSimServerNode]

    sim_dir: Optional[str]

    # location of fpga db file specifying fpga's available
    fpga_db: Optional[str]

    # instances parameterized by this
    instance_deploy_manager: InstanceDeployManager

    host: Optional[str]

    metasimulation_enabled: bool

    def __init__(
        self,
        run_farm: RunFarm,
        max_sim_slots_allowed: int,
        instance_deploy_manager: Type[InstanceDeployManager],
        sim_dir: Optional[str] = None,
        fpga_db: Optional[str] = None,
        metasimulation_enabled: bool = False,
    ) -> None:
        super().__init__()

        self.run_farm = run_farm

        self.switch_slots = []
        self._next_switch_port = (
            10000  # track ports to allocate for server switch model ports
        )

        self.pipe_slots = []

        self.MAX_SIM_SLOTS_ALLOWED = max_sim_slots_allowed
        self.sim_slots = []

        self.sim_dir = sim_dir
        self.fpga_db = fpga_db
        self.metasimulation_enabled = metasimulation_enabled

        self.instance_deploy_manager = instance_deploy_manager(self)

        self.host = None

    def switch_and_pipe_slots(self) -> int:
        return len(self.switch_slots) + len(self.pipe_slots)

    def set_sim_dir(self, drctry: str) -> None:
        self.sim_dir = drctry

    def get_sim_dir(self) -> str:
        assert self.sim_dir is not None
        return self.sim_dir

    def set_fpga_db(self, f: str) -> None:
        self.fpga_db = f

    def get_fpga_db(self) -> str:
        assert self.fpga_db is not None
        return self.fpga_db

    def get_host(self) -> str:
        assert self.host is not None
        return self.host

    def set_host(self, host: str) -> None:
        self.host = host

    def add_switch(self, firesimswitchnode: FireSimSwitchNode) -> None:
        """Add a switch to the next available switch slot."""
        assert self.switch_and_pipe_slots() < self.MAX_SWITCH_AND_PIPE_SLOTS_ALLOWED
        self.switch_slots.append(firesimswitchnode)
        firesimswitchnode.assign_host_instance(self)

    def add_pipe(self, firesimpipenode: FireSimPipeNode) -> None:
        """Add a pipe to the next available pipe slot."""
        assert self.switch_and_pipe_slots() < self.MAX_SWITCH_AND_PIPE_SLOTS_ALLOWED
        self.pipe_slots.append(firesimpipenode)
        firesimpipenode.assign_host_instance(self)

    def allocate_host_port(self) -> int:
        """Allocate a port to use for something on the host. Successive calls
        will return a new port."""
        retport = self._next_switch_port
        assert (
            retport < 11000
        ), "Exceeded number of ports used on host. You will need to modify your security groups to increase this value."
        self._next_switch_port += 1
        return retport

    def add_simulation(self, firesimservernode: FireSimServerNode) -> None:
        """Add a simulation to the next available slot."""
        assert len(self.sim_slots) < self.MAX_SIM_SLOTS_ALLOWED
        self.sim_slots.append(firesimservernode)
        firesimservernode.assign_host_instance(self)

    def qcow2_support_required(self) -> bool:
        """Return True iff any simulation on this RunHost requires qcow2."""
        return any([x.qcow2_support_required() for x in self.sim_slots])

    def terminate_self(self) -> None:
        """Terminate the current host for the RunHost."""
        self.run_farm.terminate_by_inst(self)


class RunFarm(metaclass=abc.ABCMeta):
    """Abstract class to represent how to manage run farm hosts (similar to `BuildFarm`).
    In addition to having to implement how to spawn/terminate nodes, the child classes must
    implement helper functions to help topologies map run farm hosts (`RunHost`s) to `FireSimNodes`.

    Attributes:
        args: Set of options from the 'args' section of the YAML associated with the run farm.
        default_simulation_dir: default location of the simulation dir on the run farm host
        SIM_HOST_HANDLE_TO_MAX_FPGA_SLOTS: dict of host handles to number of FPGAs available
        SIM_HOST_HANDLE_TO_MAX_METASIM_SLOTS: dict of host handles to number of metasim slots available
        SIM_HOST_HANDLE_TO_SWITCH_ONLY_OK: dict of host handles to whether an instance is allowed to be used to hold only a switch simulation and nothing else

        SORTED_SIM_HOST_HANDLE_TO_MAX_FPGA_SLOTS: sorted 'SIM_HOST_HANDLE_TO_MAX_FPGA_SLOTS' by FPGAs available
        SORTED_SIM_HOST_HANDLE_TO_MAX_METASIM_SLOTS: sorted 'SIM_HOST_HANDLE_TO_MAX_METASIM_SLOTS' by metasim slots available

        run_farm_hosts_dict: list of instances requested (RunHost object and one of [None, boto3 object, mock boto3 object, other cloud-specific obj]). TODO: improve this later
        mapper_consumed: dict of allocated instance names to number of allocations of that instance name.
            this mapping API tracks instances allocated not sim slots (it is possible to allocate an instance
            that has some sim slots unassigned)
        metasimulation_enabled: true if this run farm will be running metasimulations

    """

    SIM_HOST_HANDLE_TO_MAX_FPGA_SLOTS: Dict[str, int]
    SIM_HOST_HANDLE_TO_MAX_METASIM_SLOTS: Dict[str, int]
    SIM_HOST_HANDLE_TO_SWITCH_ONLY_OK: Dict[str, bool]

    SORTED_SIM_HOST_HANDLE_TO_MAX_FPGA_SLOTS: List[Tuple[int, str]]
    SORTED_SIM_HOST_HANDLE_TO_MAX_METASIM_SLOTS: List[Tuple[int, str]]

    run_farm_hosts_dict: Dict[
        str,
        List[Tuple[RunHost, Optional[Union[EC2InstanceResource, MockBoto3Instance]]]],
    ]
    mapper_consumed: Dict[str, int]

    default_simulation_dir: str
    metasimulation_enabled: bool

    def __init__(self, args: Dict[str, Any], metasimulation_enabled: bool) -> None:
        self.args = args
        self.metasimulation_enabled = metasimulation_enabled
        self.default_simulation_dir = self.args.get(
            "default_simulation_dir", f"/home/{os.environ['USER']}"
        )
        self.SIM_HOST_HANDLE_TO_MAX_FPGA_SLOTS = dict()
        self.SIM_HOST_HANDLE_TO_MAX_METASIM_SLOTS = dict()
        self.SIM_HOST_HANDLE_TO_SWITCH_ONLY_OK = dict()

    def invert_filter_sort(self, input_dict: Dict[str, int]) -> List[Tuple[int, str]]:
        """Take a dict, convert to list of pairs, flip key and value,
        remove all keys equal to zero, then sort on the new key."""
        out_list = [(y, x) for x, y in list(input_dict.items())]
        out_list = list(filter(lambda x: x[0] != 0, out_list))
        return sorted(out_list, key=lambda x: x[0])

    def init_postprocess(self) -> None:
        self.SORTED_SIM_HOST_HANDLE_TO_MAX_FPGA_SLOTS = self.invert_filter_sort(
            self.SIM_HOST_HANDLE_TO_MAX_FPGA_SLOTS
        )
        self.SORTED_SIM_HOST_HANDLE_TO_MAX_METASIM_SLOTS = self.invert_filter_sort(
            self.SIM_HOST_HANDLE_TO_MAX_METASIM_SLOTS
        )

    def get_smallest_sim_host_handle(self, num_sims: int) -> str:
        """Return the smallest run host handle (unique string to identify a run host type) that
        supports greater than or equal to num_sims simulations AND has available run hosts
        of that type (according to run host counts you've specified in config_run_farm.ini).
        """
        sorted_slots = None
        if self.metasimulation_enabled:
            sorted_slots = self.SORTED_SIM_HOST_HANDLE_TO_MAX_METASIM_SLOTS
        else:
            sorted_slots = self.SORTED_SIM_HOST_HANDLE_TO_MAX_FPGA_SLOTS

        for max_simcount, sim_host_handle in sorted_slots:
            if max_simcount < num_sims:
                # instance doesn't support enough sims
                continue
            num_consumed = self.mapper_consumed[sim_host_handle]
            num_allocated = len(self.run_farm_hosts_dict[sim_host_handle])
            if num_consumed >= num_allocated:
                # instance supports enough sims but none are available
                continue
            return sim_host_handle

        rootLogger.critical(
            f"ERROR: No hosts are available to satisfy the request for a host with support for {num_sims} simulation slots. Add more hosts in your run farm configuration (e.g., config_runtime.yaml)."
        )
        raise Exception

    def allocate_sim_host(self, sim_host_handle: str) -> RunHost:
        """Let user allocate and use an run host (assign sims, etc.) given it's handle."""
        rootLogger.info(f"run_farm_hosts_dict {self.run_farm_hosts_dict}")
        inst_tup = self.run_farm_hosts_dict[sim_host_handle][
            self.mapper_consumed[sim_host_handle]
        ]
        inst_ret = inst_tup[0]
        self.mapper_consumed[sim_host_handle] += 1
        return inst_ret

    def get_switch_only_host_handle(self) -> str:
        """Get the default run host handle (unique string to identify a run host type) that can
        host switch simulations.
        """
        for sim_host_handle, switch_ok in sorted(
            self.SIM_HOST_HANDLE_TO_SWITCH_ONLY_OK.items(), key=lambda x: x[0]
        ):
            if not switch_ok:
                # cannot use this handle for switch-only mapping
                continue

            num_consumed = self.mapper_consumed[sim_host_handle]
            num_allocated = len(self.run_farm_hosts_dict[sim_host_handle])
            if num_consumed >= num_allocated:
                # instance supports enough sims but none are available
                continue
            return sim_host_handle

        rootLogger.critical(
            f"ERROR: No hosts are available to satisfy the request for a host with support for running only switches. Add more hosts in your run farm configuration (e.g., config_runtime.yaml)."
        )
        raise Exception

    @abc.abstractmethod
    def post_launch_binding(self, mock: bool = False) -> None:
        """Bind launched platform API objects to run hosts (only used in firesim-managed runfarms).

        Args:
            mock: In AWS case, for testing, assign mock boto objects.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def launch_run_farm(self) -> None:
        """Launch run hosts for simulations."""
        raise NotImplementedError

    @abc.abstractmethod
    def terminate_run_farm(
        self, terminate_some_dict: Dict[str, int], forceterminate: bool
    ) -> None:
        """Terminate run hosts for simulations.

        Args:
            terminate_some_dict: Dict of run host handles to amount of that type to terminate.
            forceterminate: Don't prompt user to terminate.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def get_all_host_nodes(self) -> List[RunHost]:
        """Return all run host nodes."""
        raise NotImplementedError

    @abc.abstractmethod
    def get_all_bound_host_nodes(self) -> List[RunHost]:
        """Return all run host nodes that are ready to use (bound to relevant objects)."""
        raise NotImplementedError

    @abc.abstractmethod
    def lookup_by_host(self, host: str) -> RunHost:
        """Return run farm host based on host."""
        raise NotImplementedError

    @abc.abstractmethod
    def terminate_by_inst(self, inst: RunHost) -> None:
        """Terminate run farm host based on RunHost object."""
        raise NotImplementedError
