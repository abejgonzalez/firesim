""" Vitis-specific Run Farm management """

from __future__ import annotations

import logging
import json
from fabric.api import run, cd, settings, hide, put  # type: ignore

from .instance_deploy_manager import InstanceDeployManager

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from runtools.run_farms.inst import Inst


rootLogger = logging.getLogger()


class VitisInstanceDeployManager(InstanceDeployManager):
    """This class manages a Vitis-enabled instance"""

    PLATFORM_NAME: str = "vitis"

    def __init__(self, parent_node: Inst) -> None:
        super().__init__(parent_node)

    def clear_fpgas(self) -> None:
        if self.instance_assigned_simulations():
            self.instance_logger("Clearing all FPGA Slots.")

            card_bdfs = []
            with settings(warn_only=True), hide("everything"):
                # Examine forcibly puts the JSON in an output file (on the remote); The stdout
                # it produces is difficult to parse so use process substitution
                # to pipe JSON to stdout instead.
                # combine_stderr=False allows separate stdout and stderr streams
                xbutil_examine_json = run(
                    "xbutil examine --force --format JSON -o >(cat) > /dev/null",
                    pty=False,
                    combine_stderr=False,
                )
                if xbutil_examine_json.stderr != "":
                    rootLogger.critical(
                        f"xbutil returned:\n{xbutil_examine_json.stderr}"
                    )
                try:
                    json_dict = json.loads(xbutil_examine_json.stdout)
                except json.JSONDecodeError as e:
                    rootLogger.critical(
                        f"JSONDecodeError when parsing output from xbutil."
                    )
                    raise e
                card_bdfs = [d["bdf"] for d in json_dict["system"]["host"]["devices"]]

            for card_bdf in card_bdfs:
                run(f"xbutil reset -d {card_bdf} --force")

    def copy_bitstreams(self) -> None:
        if self.instance_assigned_simulations():
            self.instance_logger("Copy bitstreams to flash.")

            for slotno, firesimservernode in enumerate(self.parent_node.sim_slots):
                serv = firesimservernode
                hwcfg = serv.get_resolved_server_hardware_config()

                bitstream_tar = hwcfg.get_bitstream_tar_filename()
                remote_sim_dir = self.get_remote_sim_dir_for_slot(slotno)
                bitstream_tar_unpack_dir = f"{remote_sim_dir}/{self.PLATFORM_NAME}"
                bit = f"{remote_sim_dir}/{self.PLATFORM_NAME}/firesim.xclbin"

                # at this point the tar file is in the sim slot
                run(f"rm -rf {bitstream_tar_unpack_dir}")
                run(f"tar xvf {remote_sim_dir}/{bitstream_tar} -C {remote_sim_dir}")

    def infrasetup_instance(self, uridir: str) -> None:
        """Handle infrastructure setup for this platform."""
        if self.instance_assigned_simulations():
            # This is a sim-host node.

            # copy sim infrastructure
            for slotno in range(len(self.parent_node.sim_slots)):
                self.copy_sim_slot_infrastructure(slotno, uridir)
                self.extract_driver_tarball(slotno)

            if not self.parent_node.metasimulation_enabled:
                # clear/flash fpgas
                self.clear_fpgas()
                # copy bitstreams to use in run
                self.copy_bitstreams()

        if self.instance_assigned_switches():
            # all nodes could have a switch
            for slotno in range(len(self.parent_node.switch_slots)):
                self.copy_switch_slot_infrastructure(slotno)

        if self.instance_assigned_pipes():
            for slotno in range(len(self.parent_node.pipe_slots)):
                self.copy_pipe_slot_infrastructure(slotno)

    def start_sim_slot(self, slotno: int) -> None:
        """start a simulation. (same as default except that you pass in the bitstream file)"""
        if self.instance_assigned_simulations():
            self.instance_logger(
                f"""Starting {self.sim_type_message} simulation for slot: {slotno}."""
            )
            remote_home_dir = self.parent_node.sim_dir
            remote_sim_dir = self.get_remote_sim_dir_for_slot(slotno)
            assert slotno < len(
                self.parent_node.sim_slots
            ), f"{slotno} can not index into sim_slots {len(self.parent_node.sim_slots)} on {self.parent_node.host}"
            server = self.parent_node.sim_slots[slotno]
            hwcfg = server.get_resolved_server_hardware_config()

            bit = f"{remote_sim_dir}/{self.PLATFORM_NAME}/firesim.xclbin"

            if not self.parent_node.metasimulation_enabled:
                extra_args = f"+slotid={slotno} +binary_file={bit}"
            else:
                extra_args = None

            # make the local job results dir for this sim slot
            server.mkdir_and_prep_local_job_results_dir()
            sim_start_script_local_path = server.write_sim_start_script(
                slotno, extra_args
            )
            put(sim_start_script_local_path, remote_sim_dir)

            with cd(remote_sim_dir):
                run("chmod +x sim-run.sh")
                run("./sim-run.sh")

    def enumerate_fpgas(self, uridir: str) -> None:
        """FPGAs are enumerated already with Vitis"""
        return

    def terminate_instance(self) -> None:
        """VitisInstanceDeployManager machines cannot be terminated."""
        return
