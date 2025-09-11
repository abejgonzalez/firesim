""" EC2-specific Run Farm management """

from __future__ import annotations

from absl import logging
from fabric.api import prefix, local, run, cd, warn_only, put, settings  # type: ignore
import os

from runtools.instance_deploy_manager import InstanceDeployManager
from runtools.nbd_tracker import NBDTracker

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from runtools.run_farm import RunHost


class EC2InstanceDeployManager(InstanceDeployManager):
    """This class manages actually deploying/running stuff based on the
    definition of an instance and the simulations/switches assigned to it.

    This is in charge of managing the locations of stuff on remote nodes.
    """

    def __init__(self, parent_node: RunHost) -> None:
        super().__init__(parent_node)
        self.nbd_tracker = NBDTracker()

    def remote_kmsg(self, message: str) -> None:
        """This will let you write whatever is passed as message into the kernel
        log of the remote machine.  Useful for figuring what the manager is doing
        w.r.t output from kernel stuff on the remote node."""
        commd = """echo '{}' | sudo tee /dev/kmsg""".format(message)
        run(commd, shell=True)

    def get_and_install_aws_fpga_sdk(self) -> None:
        """Installs the aws-sdk. This gets us access to tools to flash the fpga."""
        if self.instance_assigned_simulations():
            with prefix("cd ../"):
                # use local version of aws_fpga on run farm nodes
                aws_fpga_upstream_version = local(
                    "git -C platforms/f1/aws-fpga describe --tags --always --dirty",
                    capture=True,
                )
                if "-dirty" in aws_fpga_upstream_version:
                    logging.fatal(
                        "Unable to use local changes to aws-fpga. Continuing without them."
                    )
            self.instance_logger(
                """Installing AWS FPGA SDK on remote nodes. Upstream hash: {}""".format(
                    aws_fpga_upstream_version
                )
            )
            with warn_only():
                run("git clone https://github.com/aws/aws-fpga")
                run("cd aws-fpga && git checkout " + aws_fpga_upstream_version)
            with cd(f"/home/{os.environ['USER']}/aws-fpga"):
                run("source sdk_setup.sh")

    def fpga_node_xdma(self) -> None:
        """Copy XDMA infra to remote node. This assumes that the driver was
        already built and that a binary exists in the directory on this machine
        """
        if self.instance_assigned_simulations():
            self.instance_logger("""Copying AWS FPGA XDMA driver to remote node.""")
            run(f"mkdir -p /home/{os.environ['USER']}/xdma/")
            put(
                "../platforms/f1/aws-fpga/sdk/linux_kernel_drivers",
                f"/home/{os.environ['USER']}/xdma/",
                mirror_local_mode=True,
            )
            with cd(
                f"/home/{os.environ['USER']}/xdma/linux_kernel_drivers/xdma/"
            ), prefix("export PATH=/usr/bin:$PATH"):
                # prefix only needed if conda env is earlier in PATH
                # see build-setup-nolog.sh for explanation.
                run("make clean")
                run("make")

    def unload_xrt_and_xocl(self) -> None:
        if self.instance_assigned_simulations():
            self.instance_logger("Unloading XRT-related Kernel Modules.")

            with warn_only():
                # fpga mgmt tools seem to force load xocl after a flash now...
                # so we just remove everything for good measure:
                self.remote_kmsg("removing_xrt_start")
                run("sudo systemctl stop mpd")
                run("sudo yum remove -y xrt xrt-aws")
                self.remote_kmsg("removing_xrt_end")

    def unload_xdma(self) -> None:
        if self.instance_assigned_simulations():
            self.instance_logger("Unloading XDMA Driver Kernel Module.")

            with warn_only():
                # fpga mgmt tools seem to force load xocl after a flash now...
                # so we just remove everything for good measure:
                self.remote_kmsg("removing_xdma_start")
                run("sudo rmmod xdma")
                self.remote_kmsg("removing_xdma_end")

            # self.instance_logger("Waiting 10 seconds after removing kernel modules (esp. xocl).")
            # time.sleep(10)

    def clear_fpgas(self) -> None:
        if self.instance_assigned_simulations():
            # we always clear ALL fpga slots
            for slotno in range(self.parent_node.MAX_SIM_SLOTS_ALLOWED):
                self.instance_logger("""Clearing FPGA Slot {}.""".format(slotno))
                self.remote_kmsg("""about_to_clear_fpga{}""".format(slotno))
                run("""sudo fpga-clear-local-image -S {} -A""".format(slotno))
                self.remote_kmsg("""done_clearing_fpga{}""".format(slotno))

            for slotno in range(self.parent_node.MAX_SIM_SLOTS_ALLOWED):
                self.instance_logger(
                    """Checking for Cleared FPGA Slot {}.""".format(slotno)
                )
                self.remote_kmsg("""about_to_check_clear_fpga{}""".format(slotno))
                run(
                    """until sudo fpga-describe-local-image -S {} -R -H | grep -q "cleared"; do  sleep 1;  done""".format(
                        slotno
                    )
                )
                self.remote_kmsg("""done_checking_clear_fpga{}""".format(slotno))

    def flash_fpgas(self) -> None:
        if self.instance_assigned_simulations():
            dummyagfi = None
            for slotno, firesimservernode in enumerate(self.parent_node.sim_slots):
                agfi = firesimservernode.get_agfi()
                dummyagfi = agfi
                self.instance_logger(
                    """Flashing FPGA Slot: {} with agfi: {}.""".format(slotno, agfi)
                )
                run(
                    """sudo fpga-load-local-image -S {} -I {} -A""".format(slotno, agfi)
                )

            # We only do this because XDMA hangs if some of the FPGAs on the instance
            # are left in the cleared state. So, if you're only using some of the
            # FPGAs on an instance, we flash the rest with one of your images
            # anyway. Since the only interaction we have with an FPGA right now
            # is over PCIe where the software component is mastering, this can't
            # break anything.
            for slotno in range(
                len(self.parent_node.sim_slots), self.parent_node.MAX_SIM_SLOTS_ALLOWED
            ):
                self.instance_logger(
                    """Flashing FPGA Slot: {} with dummy agfi: {}.""".format(
                        slotno, dummyagfi
                    )
                )
                run(
                    """sudo fpga-load-local-image -S {} -I {} -A""".format(
                        slotno, dummyagfi
                    )
                )

            for slotno, firesimservernode in enumerate(self.parent_node.sim_slots):
                self.instance_logger(
                    """Checking for Flashed FPGA Slot: {} with agfi: {}.""".format(
                        slotno, agfi
                    )
                )
                run(
                    """until sudo fpga-describe-local-image -S {} -R -H | grep -q "loaded"; do  sleep 1;  done""".format(
                        slotno
                    )
                )

            for slotno in range(
                len(self.parent_node.sim_slots), self.parent_node.MAX_SIM_SLOTS_ALLOWED
            ):
                self.instance_logger(
                    """Checking for Flashed FPGA Slot: {} with agfi: {}.""".format(
                        slotno, dummyagfi
                    )
                )
                run(
                    """until sudo fpga-describe-local-image -S {} -R -H | grep -q "loaded"; do  sleep 1;  done""".format(
                        slotno
                    )
                )

    def load_xdma(self) -> None:
        """load the xdma kernel module."""
        if self.instance_assigned_simulations():
            # fpga mgmt tools seem to force load xocl after a flash now...
            # xocl conflicts with the xdma driver, which we actually want to use
            # so we just remove everything for good measure before loading xdma:
            self.unload_xdma()
            # now load xdma
            self.instance_logger("Loading XDMA Driver Kernel Module.")
            # TODO: can make these values automatically be chosen based on link lat
            run(
                f"sudo insmod /home/{os.environ['USER']}/xdma/linux_kernel_drivers/xdma/xdma.ko poll_mode=1"
            )

    def start_ila_server(self) -> None:
        """start the vivado hw_server and virtual jtag on simulation instance."""
        if self.instance_assigned_simulations():
            self.instance_logger("Starting Vivado hw_server.")
            run(
                """screen -S hw_server -d -m bash -c "script -f -c 'hw_server'"; sleep 1"""
            )
            self.instance_logger("Starting Vivado virtual JTAG.")
            run(
                """screen -S virtual_jtag -d -m bash -c "script -f -c 'sudo fpga-start-virtual-jtag -P 10201 -S 0'"; sleep 1"""
            )

    def kill_ila_server(self) -> None:
        """Kill the vivado hw_server and virtual jtag"""
        if self.instance_assigned_simulations():
            with warn_only():
                run("sudo pkill -SIGKILL hw_server")
            with warn_only():
                run("sudo pkill -SIGKILL fpga-local-cmd")

    def infrasetup_instance(self, uridir: str) -> None:
        """Handle infrastructure setup for this instance."""

        metasim_enabled = self.parent_node.metasimulation_enabled

        if self.instance_assigned_simulations():
            # This is a sim-host node.

            # copy sim infrastructure
            for slotno in range(len(self.parent_node.sim_slots)):
                self.copy_sim_slot_infrastructure(slotno, uridir)
                self.extract_driver_tarball(slotno)

            if not metasim_enabled:
                self.get_and_install_aws_fpga_sdk()
                # unload any existing edma/xdma/xocl
                self.unload_xrt_and_xocl()
                # copy xdma driver
                self.fpga_node_xdma()
                # load xdma
                self.load_xdma()

            # setup nbd/qcow infra
            self.sim_node_qcow()
            # load nbd module
            self.load_nbd_module()

            if not metasim_enabled:
                # clear/flash fpgas
                self.clear_fpgas()
                self.flash_fpgas()

                # re-load XDMA
                self.load_xdma()

                # restart (or start form scratch) ila server
                self.kill_ila_server()
                self.start_ila_server()

        if self.instance_assigned_switches():
            # all nodes could have a switch
            for slotno in range(len(self.parent_node.switch_slots)):
                self.copy_switch_slot_infrastructure(slotno)

        if self.instance_assigned_pipes():
            for slotno in range(len(self.parent_node.pipe_slots)):
                self.copy_pipe_slot_infrastructure(slotno)

    def enumerate_fpgas(self, uridir: str) -> None:
        """FPGAs are enumerated already with F1"""
        return

    def terminate_instance(self) -> None:
        self.instance_logger("Terminating instance", debug=True)
        self.parent_node.terminate_self()
