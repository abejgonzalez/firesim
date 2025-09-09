from __future__ import annotations

import logging
import abc

from runtools.firesim_topology_elements import (
    FireSimPipeNode,
    FireSimSwitchNode,
    FireSimServerNode,
)
from runtools.instance_deploy_managers.instance_deploy_manager import (
    InstanceDeployManager,
)

from typing import Optional, List, Type, TYPE_CHECKING

if TYPE_CHECKING:
    from .run_farm import RunFarm

rootLogger = logging.getLogger()


class Inst(metaclass=abc.ABCMeta):
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
        """Return True iff any simulation on this Inst requires qcow2."""
        return any([x.qcow2_support_required() for x in self.sim_slots])

    def terminate_self(self) -> None:
        """Terminate the current host for the Inst."""
        self.run_farm.terminate_by_inst(self)
