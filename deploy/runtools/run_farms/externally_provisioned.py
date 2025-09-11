from __future__ import annotations

from absl import logging
import pprint
from collections import defaultdict

from utils.inheritors import inheritors
from runtools.instance_deploy_manager import InstanceDeployManager
from runtools.instance_deploy_managers.ec2 import EC2InstanceDeployManager
from runtools.instance_deploy_managers.xilinx_alveo import (
    XilinxAlveoU200InstanceDeployManager,
    XilinxAlveoU250InstanceDeployManager,
    XilinxAlveoU280InstanceDeployManager,
)
from runtools.instance_deploy_managers.xilinx_vcu118 import (
    XilinxVCU118InstanceDeployManager,
)
from runtools.run_farm import RunFarm, RunHost

from typing import Any, Dict, List, TYPE_CHECKING

if TYPE_CHECKING:
    pass


class ExternallyProvisioned(RunFarm):
    """This manages the set of externally provisioned instances. This class doesn't manage
    launch/terminating instances. It is assumed that the instances are "ready to use".

    Attributes:
    """

    def __init__(self, args: Dict[str, Any], metasimulation_enabled: bool) -> None:
        super().__init__(args, metasimulation_enabled)

        self._parse_args()

        self.init_postprocess()

    def _parse_args(self) -> None:
        dispatch_dict = dict(
            [(x.__name__, x) for x in inheritors(InstanceDeployManager)]
        )

        default_platform = self.args.get("default_platform")
        default_fpga_db = self.args.get("default_fpga_db")

        runhost_specs = dict()
        for specinfo in self.args["run_farm_host_specs"]:
            specinfo_value = next(iter(specinfo.items()))
            runhost_specs[specinfo_value[0]] = specinfo_value[1]

        runhosts_list = self.args["run_farm_hosts_to_use"]

        self.run_farm_hosts_dict = defaultdict(list)
        self.mapper_consumed = defaultdict(int)

        for runhost in runhosts_list:
            if not isinstance(runhost, dict):
                raise Exception(f"Invalid runhost to spec mapping for {runhost}.")

            items = runhost.items()

            assert (
                len(items) == 1
            ), f"dict type 'run_hosts' items map a single host name to a host spec. Not: {pprint.pformat(runhost)}"

            ip_addr, host_spec_name = next(iter(items))

            if host_spec_name not in runhost_specs.keys():
                raise Exception(f"Unknown runhost spec of {host_spec_name}")

            host_spec = runhost_specs[host_spec_name]

            # populate mapping helpers based on runhost_specs:
            self.SIM_HOST_HANDLE_TO_MAX_FPGA_SLOTS[ip_addr] = host_spec["num_fpgas"]
            self.SIM_HOST_HANDLE_TO_MAX_METASIM_SLOTS[ip_addr] = host_spec[
                "num_metasims"
            ]
            self.SIM_HOST_HANDLE_TO_SWITCH_ONLY_OK[ip_addr] = host_spec[
                "use_for_switch_only"
            ]

            num_sims = 0
            if self.metasimulation_enabled:
                num_sims = host_spec.get("num_metasims")
            else:
                num_sims = host_spec.get("num_fpgas")
            platform = host_spec.get("override_platform", default_platform)
            simulation_dir = host_spec.get(
                "override_simulation_dir", self.default_simulation_dir
            )
            fpga_db = host_spec.get("override_fpga_db", default_fpga_db)

            inst = RunHost(
                self,
                num_sims,
                dispatch_dict[platform],
                simulation_dir,
                fpga_db,
                self.metasimulation_enabled,
            )
            inst.set_host(ip_addr)
            assert (
                not ip_addr in self.run_farm_hosts_dict
            ), f"Duplicate host name found in 'run_farm_hosts': {ip_addr}"
            self.run_farm_hosts_dict[ip_addr] = [(inst, None)]
            self.mapper_consumed[ip_addr] = 0

    def post_launch_binding(self, mock: bool = False) -> None:
        return

    def launch_run_farm(self) -> None:
        logging.info(
            f"WARNING: Skipping launchrunfarm since run hosts are externally provisioned."
        )
        return

    def terminate_run_farm(
        self, terminate_some_dict: Dict[str, int], forceterminate: bool
    ) -> None:
        logging.info(
            f"WARNING: Skipping terminaterunfarm since run hosts are externally provisioned."
        )
        return

    def get_all_host_nodes(self) -> List[RunHost]:
        all_insts = []
        for sim_host_handle in sorted(self.SIM_HOST_HANDLE_TO_MAX_FPGA_SLOTS):
            inst_list = self.run_farm_hosts_dict[sim_host_handle]
            for inst, cloudobj in inst_list:
                all_insts.append(inst)
        return all_insts

    def get_all_bound_host_nodes(self) -> List[RunHost]:
        return self.get_all_host_nodes()

    def lookup_by_host(self, host: str) -> RunHost:
        for host_node in self.get_all_bound_host_nodes():
            if host_node.get_host() == host:
                return host_node
        assert False, f"Unable to find host node by {host} host name"

    def terminate_by_inst(self, inst: RunHost) -> None:
        logging.info(
            f"WARNING: Skipping terminate_by_inst since run hosts are externally provisioned."
        )
        return
