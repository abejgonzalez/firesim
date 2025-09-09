""" Xilinx Alveo-specific Run Farm management """

from __future__ import annotations

import logging
import json
import os
from pathlib import Path

from fabric.api import run, cd, put  # type: ignore
from fabric.contrib.project import rsync_project  # type: ignore

from .instance_deploy_manager import InstanceDeployManager
from runtools.utils import check_script, script_path
from buildtools.bitbuilder import get_deploy_dir

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from runtools.run_farms.inst import Inst

rootLogger = logging.getLogger()


class XilinxAlveoInstanceDeployManager(InstanceDeployManager):
    """This class manages a Xilinx Alveo-enabled instance"""

    PLATFORM_NAME: Optional[str]

    def __init__(self, parent_node: Inst) -> None:
        super().__init__(parent_node)
        self.PLATFORM_NAME = None

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

    def unload_xdma(self) -> None:
        """unload the xdma kernel module."""
        if self.instance_assigned_simulations():
            # unload xdma if loaded
            if run("lsmod | grep -wq xdma", warn_only=True).return_code == 0:
                self.instance_logger("Unloading XDMA Driver Kernel Module.")
                cmd = f"{script_path}/firesim-remove-xdma-module"
                check_script(cmd)
                run(f"sudo {cmd}", shell=True)
            else:
                self.instance_logger("XDMA Driver Kernel Module already unloaded.")

    def slot_to_bdf(self, slotno: int, json_db: str) -> str:
        # get fpga information from db
        self.instance_logger(f"""Determine BDF for {slotno}""")
        collect = run(f"cat {json_db}")
        db = json.loads(collect)
        assert slotno < len(
            db
        ), f"Less FPGAs available than slots ({slotno} >= {len(db)})"
        return db[slotno]["bdf"]

    def flash_fpgas(self) -> None:
        if self.instance_assigned_simulations():
            self.instance_logger("""Flash all FPGA Slots.""")

            for slotno, firesimservernode in enumerate(self.parent_node.sim_slots):
                serv = firesimservernode
                hwcfg = serv.get_resolved_server_hardware_config()

                bitstream_tar = hwcfg.get_bitstream_tar_filename()
                remote_sim_dir = self.get_remote_sim_dir_for_slot(slotno)
                bitstream_tar_unpack_dir = os.path.join(
                    remote_sim_dir, str(self.PLATFORM_NAME)
                )
                bit = os.path.join(bitstream_tar_unpack_dir, "firesim.bit")

                # at this point the tar file is in the sim slot
                run(f"rm -rf {bitstream_tar_unpack_dir}")
                run(f"tar xvf {remote_sim_dir}/{bitstream_tar} -C {remote_sim_dir}")

                self.instance_logger(f"""Copying FPGA flashing scripts for {slotno}""")
                rsync_cap = rsync_project(
                    local_dir=f"../platforms/{self.PLATFORM_NAME}/scripts",
                    remote_dir=remote_sim_dir,
                    ssh_opts="-o StrictHostKeyChecking=no",
                    extra_opts="-L -p",
                    capture=True,
                )
                rootLogger.debug(rsync_cap)
                rootLogger.debug(rsync_cap.stderr)

                json_db = self.parent_node.get_fpga_db()
                bdf = self.slot_to_bdf(slotno, json_db)

                self.instance_logger(
                    f"""Flashing FPGA Slot: {slotno} ({bdf}) with bitstream: {bit}"""
                )
                # Use a system wide installed firesim-fpga-util.py
                cmd = f"{script_path}/firesim-fpga-util.py"
                check_script(
                    cmd,
                    Path(
                        f"{get_deploy_dir()}/../platforms/{self.PLATFORM_NAME}/scripts"
                    ),
                )
                run(f"""{cmd} --bitstream {bit} --bdf {bdf} --fpga-db {json_db}""")

    def change_pcie_perms(self) -> None:
        if self.instance_assigned_simulations():
            self.instance_logger("""Change permissions on FPGA slot""")

            for slotno, firesimservernode in enumerate(self.parent_node.sim_slots):
                bdf = self.slot_to_bdf(slotno, self.parent_node.get_fpga_db())

                self.instance_logger(
                    f"""Changing permissions on FPGA Slot: {slotno} (bdf:{bdf})"""
                )
                cmd = f"{script_path}/firesim-change-pcie-perms"
                check_script(cmd)
                run(f"""sudo {cmd} 0000:{bdf}""")

    def change_all_pcie_perms(self) -> None:
        collect = run("lspci | grep -i xilinx")

        bdfs = [
            {"busno": "0x" + i[:2], "devno": "0x" + i[3:5], "capno": "0x" + i[6:7]}
            for i in collect.splitlines()
            if len(i.strip()) >= 0
        ]
        for bdf in bdfs:
            busno = bdf["busno"]
            devno = bdf["devno"]
            capno = bdf["capno"]

            self.instance_logger(
                f"""Changing permissions on FPGA: bus:{busno}, dev:{devno}, cap:{capno}"""
            )
            cmd = f"{script_path}/firesim-change-pcie-perms"
            check_script(cmd)
            run(f"""sudo {cmd} 0000:{busno[2:]}:{devno[2:]}:{capno[2:]}""")

    def infrasetup_instance(self, uridir: str) -> None:
        """Handle infrastructure setup for this platform."""
        metasim_enabled = self.parent_node.metasimulation_enabled

        if self.instance_assigned_simulations():
            # This is a sim-host node.

            # copy sim infrastructure
            for slotno in range(len(self.parent_node.sim_slots)):
                self.copy_sim_slot_infrastructure(slotno, uridir)
                self.extract_driver_tarball(slotno)

            if not metasim_enabled:
                # unload xdma driver
                self.unload_xdma()
                # flash fpgas
                self.flash_fpgas()
                # load xdma driver
                self.load_xdma()
                # change pcie permissions
                self.change_pcie_perms()

        if self.instance_assigned_switches():
            # all nodes could have a switch
            for slotno in range(len(self.parent_node.switch_slots)):
                self.copy_switch_slot_infrastructure(slotno)

        if self.instance_assigned_pipes():
            for slotno in range(len(self.parent_node.pipe_slots)):
                self.copy_pipe_slot_infrastructure(slotno)

    def create_fpga_database(self, uridir: str) -> None:
        self.instance_logger(f"""Creating FPGA database""")

        remote_home_dir = self.parent_node.get_sim_dir()
        remote_sim_dir = f"{remote_home_dir}/enumerate_fpgas_staging"
        remote_sim_rsync_dir = f"{remote_sim_dir}/rsyncdir/"
        run(f"mkdir -p {remote_sim_rsync_dir}")

        # only use the collateral from 1 driver (no need to copy all things)
        assert len(self.parent_node.sim_slots) > 0
        serv = self.parent_node.sim_slots[0]

        files_to_copy = serv.get_required_files_local_paths()

        # Append required URI paths to the end of this list
        hwcfg = serv.get_resolved_server_hardware_config()
        files_to_copy.extend(hwcfg.get_local_uri_paths(uridir))

        for local_path, remote_path in files_to_copy:
            # -z --inplace
            rsync_cap = rsync_project(
                local_dir=local_path,
                remote_dir=os.path.join(remote_sim_rsync_dir, remote_path),
                ssh_opts="-o StrictHostKeyChecking=no",
                extra_opts="-L",
                capture=True,
            )
            rootLogger.debug(rsync_cap)
            rootLogger.debug(rsync_cap.stderr)

        run(f"cp -r {remote_sim_rsync_dir}/* {remote_sim_dir}/", shell=True)

        rsync_cap = rsync_project(
            local_dir=f"../platforms/{self.PLATFORM_NAME}/scripts",
            remote_dir=remote_sim_dir + "/",
            ssh_opts="-o StrictHostKeyChecking=no",
            extra_opts="-L -p",
            capture=True,
        )
        rootLogger.debug(rsync_cap)
        rootLogger.debug(rsync_cap.stderr)

        bitstream_tar = hwcfg.get_bitstream_tar_filename()
        bitstream_tar_unpack_dir = f"{remote_sim_dir}/{self.PLATFORM_NAME}"
        bitstream = f"{remote_sim_dir}/{self.PLATFORM_NAME}/firesim.bit"

        with cd(remote_sim_dir):
            run(f"tar -xf {hwcfg.get_driver_tar_filename()}")

        # at this point the tar file is in the sim slot
        run(f"rm -rf {bitstream_tar_unpack_dir}")
        run(f"tar xvf {remote_sim_dir}/{bitstream_tar} -C {remote_sim_dir}")

        driver = f"{remote_sim_dir}/FireSim-{self.PLATFORM_NAME}"
        json_db = self.parent_node.get_fpga_db()

        with cd(remote_sim_dir):
            # Use a system wide installed firesim-generate-fpga-db.py
            cmd = f"{script_path}/firesim-generate-fpga-db.py"
            check_script(
                cmd,
                Path(f"{get_deploy_dir()}/../platforms/{self.PLATFORM_NAME}/scripts"),
            )
            run(
                f"""{cmd} --bitstream {bitstream} --driver {driver} --out-db-json {json_db}"""
            )

    def enumerate_fpgas(self, uridir: str) -> None:
        """Handle fpga setup for this platform."""

        if self.instance_assigned_simulations():
            # This is a sim-host node.

            # unload xdma driver
            self.unload_xdma()
            # load xdma driver
            self.load_xdma()

            # change all pcie permissions
            self.change_all_pcie_perms()

            # run the passes
            self.create_fpga_database(uridir)

    def terminate_instance(self) -> None:
        """XilinxAlveoInstanceDeployManager machines cannot be terminated."""
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
                bdf = (
                    self.slot_to_bdf(slotno, self.parent_node.get_fpga_db())
                    .replace(".", ":")
                    .split(":")
                )
                extra_args = f"+domain=0x0000 +bus=0x{bdf[0]} +device=0x{bdf[1]} +function=0x{bdf[2]} +bar=0x0 +pci-vendor=0x10ee +pci-device=0x903f"
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


class XilinxAlveoU250InstanceDeployManager(XilinxAlveoInstanceDeployManager):
    def __init__(self, parent_node: Inst) -> None:
        super().__init__(parent_node)
        self.PLATFORM_NAME = "xilinx_alveo_u250"


class XilinxAlveoU280InstanceDeployManager(XilinxAlveoInstanceDeployManager):
    def __init__(self, parent_node: Inst) -> None:
        super().__init__(parent_node)
        self.PLATFORM_NAME = "xilinx_alveo_u280"


class XilinxAlveoU200InstanceDeployManager(XilinxAlveoInstanceDeployManager):
    def __init__(self, parent_node: Inst) -> None:
        super().__init__(parent_node)
        self.PLATFORM_NAME = "xilinx_alveo_u200"


class RHSResearchNitefuryIIInstanceDeployManager(XilinxAlveoInstanceDeployManager):
    def __init__(self, parent_node: Inst) -> None:
        super().__init__(parent_node)
        self.PLATFORM_NAME = "rhsresearch_nitefury_ii"
