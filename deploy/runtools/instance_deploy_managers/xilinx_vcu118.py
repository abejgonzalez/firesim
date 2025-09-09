""" Xilinx VCU118-specific Run Farm management """

from __future__ import annotations

from fabric.api import run, cd, put  # type: ignore

from .instance_deploy_manager import InstanceDeployManager
from runtools.utils import check_script, script_path

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from runtools.run_farms.inst import Inst


class XilinxVCU118InstanceDeployManager(InstanceDeployManager):
    """This class manages a Xilinx VCU118-enabled instance using the
    garnet shell."""

    PLATFORM_NAME: Optional[str]

    def __init__(self, parent_node: Inst) -> None:
        super().__init__(parent_node)
        self.PLATFORM_NAME = "xilinx_vcu118"

    def load_xdma(self) -> None:
        """load the xdma kernel module."""
        if self.instance_assigned_simulations():
            # load xdma if unloaded
            if run("lsmod | grep -wq xdma", warn_only=True).return_code != 0:
                self.instance_logger("Loading XDMA Driver Kernel Module.")
                # must be installed to this path on sim. machine
                cmd = f"{script_path}/firesim-load-xdma-module"
                check_script(cmd)
                run(f"sudo {cmd}", shell=True)
            else:
                self.instance_logger("XDMA Driver Kernel Module already loaded.")
            cmd = f"{script_path}/firesim-chmod-xdma-perm"
            check_script(cmd)
            run(f"sudo {cmd}")

    def load_xvsec(self) -> None:
        """load the xvsec kernel modules."""
        if self.instance_assigned_simulations():
            if run("lsmod | grep -wq xvsec", warn_only=True).return_code != 0:
                self.instance_logger("Loading XVSEC Driver Kernel Module.")
                # must be installed to this path on sim. machine
                cmd = f"{script_path}/firesim-load-xvsec-module"
                check_script(cmd)
                run(f"sudo {cmd}", shell=True)
            else:
                self.instance_logger("XVSEC Driver Kernel Module already loaded.")

    def flash_fpgas(self) -> None:
        if self.instance_assigned_simulations():
            self.instance_logger("""Flash all FPGA Slots.""")

            for slotno, firesimservernode in enumerate(self.parent_node.sim_slots):
                serv = self.parent_node.sim_slots[slotno]
                hwcfg = serv.get_resolved_server_hardware_config()

                bitstream_tar = hwcfg.get_bitstream_tar_filename()
                remote_sim_dir = self.get_remote_sim_dir_for_slot(slotno)
                bitstream_tar_unpack_dir = f"{remote_sim_dir}/{self.PLATFORM_NAME}"
                bit = f"{remote_sim_dir}/{self.PLATFORM_NAME}/firesim.bit"

                # at this point the tar file is in the sim slot
                run(f"rm -rf {bitstream_tar_unpack_dir}")
                run(f"tar xvf {remote_sim_dir}/{bitstream_tar} -C {remote_sim_dir}")

                self.instance_logger(f"""Determine BDF for {slotno}""")
                collect = run("lspci | grep -i xilinx")

                # TODO: is "Partial Reconfig Clear File" useful (see xvsecctl help)?
                bdfs = [
                    # capno is hardcoded to 0x1 otherwise xvsecctl program fails
                    {"busno": "0x" + i[:2], "devno": "0x" + i[3:5], "capno": "0x1"}
                    for i in collect.splitlines()
                    if len(i.strip()) >= 0
                ]
                bdf = bdfs[slotno]

                busno = bdf["busno"]
                devno = bdf["devno"]
                capno = bdf["capno"]

                self.instance_logger(
                    f"""Flashing FPGA Slot: {slotno} (bus:{busno}, dev:{devno}, cap:{capno}) with bit: {bit}"""
                )
                cmd = f"{script_path}/firesim-xvsecctl-flash-fpga"
                check_script(cmd)
                run(f"""sudo {cmd} {busno} {devno} {capno} {bit}""")

    def change_pcie_perms(self) -> None:
        if self.instance_assigned_simulations():
            self.instance_logger("""Change permissions on FPGA slot""")

            for slotno, firesimservernode in enumerate(self.parent_node.sim_slots):
                self.instance_logger(f"""Determine BDF for {slotno}""")
                collect = run("lspci | grep -i xilinx")

                # TODO: is "Partial Reconfig Clear File" useful (see xvsecctl help)?
                bdfs = [
                    # Cannot hardcode capno to 0x1 here, if 0x1 change permissions sometimes cannot find the device in /sys/bus/pci/devices/
                    {
                        "busno": "0x" + i[:2],
                        "devno": "0x" + i[3:5],
                        "capno": "0x" + i[6:7],
                    }
                    for i in collect.splitlines()
                    if len(i.strip()) >= 0
                ]
                bdf = bdfs[slotno]

                busno = bdf["busno"]
                devno = bdf["devno"]
                capno = bdf["capno"]

                self.instance_logger(
                    f"""Changing permissions on FPGA Slot: {slotno} (bus:{busno}, dev:{devno}, cap:{capno})"""
                )
                cmd = f"{script_path}/firesim-change-pcie-perms"
                check_script(cmd)
                run(f"""sudo {cmd} 0000:{busno[2:]}:{devno[2:]}:{capno[2:]}""")

    def infrasetup_instance(self, uridir: str) -> None:
        """Handle infrastructure setup for this platform."""
        if self.instance_assigned_simulations():
            # This is a sim-host node.

            # copy sim infrastructure
            for slotno in range(len(self.parent_node.sim_slots)):
                self.copy_sim_slot_infrastructure(slotno, uridir)
                self.extract_driver_tarball(slotno)

            if not self.parent_node.metasimulation_enabled:
                # load xdma driver
                self.load_xdma()
                self.load_xvsec()
                # flash fpgas
                self.flash_fpgas()
                # change pcie permissions
                self.change_pcie_perms()

        if self.instance_assigned_switches():
            # all nodes could have a switch
            for slotno in range(len(self.parent_node.switch_slots)):
                self.copy_switch_slot_infrastructure(slotno)

        if self.instance_assigned_pipes():
            # all nodes could have a switch
            for slotno in range(len(self.parent_node.pipe_slots)):
                self.copy_pipe_slot_infrastructure(slotno)

    def enumerate_fpgas(self, uridir: str) -> None:
        """FPGAs are enumerated already with VCU118's"""
        return

    def terminate_instance(self) -> None:
        """XilinxVCU118InstanceDeployManager machines cannot be terminated."""
        return

    def start_sim_slot(self, slotno: int) -> None:
        """start a simulation. (same as the default except that you have a mapping from slotno to a specific BDF)"""
        if self.instance_assigned_simulations():
            self.instance_logger(
                f"""Starting {self.sim_type_message} simulation for slot: {slotno}."""
            )
            remote_home_dir = self.parent_node.sim_dir
            remote_sim_dir = f"""{remote_home_dir}/sim_slot_{slotno}/"""
            assert slotno < len(
                self.parent_node.sim_slots
            ), f"{slotno} can not index into sim_slots {len(self.parent_node.sim_slots)} on {self.parent_node.host}"
            server = self.parent_node.sim_slots[slotno]

            if not self.parent_node.metasimulation_enabled:
                self.instance_logger(f"""Determine BDF for {slotno}""")
                collect = run("lspci | grep -i xilinx")
                bdfs = [i[:7] for i in collect.splitlines() if len(i.strip()) >= 0]
                bdf = bdfs[slotno].replace(".", ":").split(":")
                extra_args = f"+domain=0x0000 +bus=0x{bdf[0]} +device=0x{bdf[1]} +function=0x0 +bar=0x0 +pci-vendor=0x10ee +pci-device=0x903f"
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
