""" Run Farm management base class """

from __future__ import annotations

import re
import logging
import abc
from fabric.api import prefix, local, run, env, cd, warn_only, put, settings, hide  # type: ignore
from fabric.contrib.project import rsync_project  # type: ignore
from os.path import join as pjoin
import os

from util.streamlogger import StreamLogger
from awstools.awstools import terminate_instances, get_instance_ids_for_instances
from runtools.utils import has_sudo, run_only_aws, check_script, is_on_aws, script_path
from buildtools.utils import get_deploy_dir
from .nbd_tracker import NBDTracker

from typing import List, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from runtools.run_farm import RunHost
    from awstools.awstools import MockBoto3Instance

rootLogger = logging.getLogger()


class InstanceDeployManager(metaclass=abc.ABCMeta):
    """Class used to represent different "run platforms" and how to start/stop and setup simulations.

    Attributes:
        parent_node: Run farm host associated with this platform implementation.
    """

    parent_node: RunHost
    nbd_tracker: Optional[NBDTracker]

    def __init__(self, parent_node: RunHost) -> None:
        """
        Args:
            parent_node: Run farm host to associate with this platform implementation
        """
        self.parent_node = parent_node
        self.sim_type_message = (
            "FPGA" if not parent_node.metasimulation_enabled else "Metasim"
        )
        # Set this to self.nbd_tracker = NBDTracker() in the __init__ of your
        # subclass if your system supports the NBD kernel module.
        self.nbd_tracker = None

    @abc.abstractmethod
    def infrasetup_instance(self, uridir: str) -> None:
        """Run platform specific implementation of how to setup simulations.

        Anything that should only be executed if prepping for an actual FPGA-based
        simulation (i.e. not metasim mode) should be gated by:

        if not self.parent_node.metasimulation_enabled:
            [FPGA-specific logic, e.g. flashing FPGAs]

        """
        raise NotImplementedError

    @abc.abstractmethod
    def enumerate_fpgas(self, uridir: str) -> None:
        """Run platform specific implementation of how to enumerate FPGAs for FireSim."""
        raise NotImplementedError

    @abc.abstractmethod
    def terminate_instance(self) -> None:
        """Run platform specific implementation of how to terminate host
        machines.

        Platforms that do not have a notion of terminating a machine should
        override this to do nothing.

        """
        raise NotImplementedError

    def instance_logger(self, logstr: str, debug: bool = False) -> None:
        """Log with this host's info as prefix."""
        if debug:
            rootLogger.debug("""[{}] """.format(env.host_string) + logstr)
        else:
            rootLogger.info("""[{}] """.format(env.host_string) + logstr)

    def sim_node_qcow(self) -> None:
        """If NBD is available and qcow2 support is required, install qemu-img
        management tools and copy NBD infra to remote node. This assumes that
        the kernel module was already built and exists in the directory on this
        machine."""
        if self.nbd_tracker is not None and self.parent_node.qcow2_support_required():
            self.instance_logger("""Setting up remote node for qcow2 disk images.""")
            # get qemu-nbd
            run_only_aws("sudo yum -y install qemu-img")
            # copy over kernel module
            put(
                "../build/nbd.ko",
                f"/home/{os.environ['USER']}/nbd.ko",
                mirror_local_mode=True,
            )

    def load_nbd_module(self) -> None:
        """If NBD is available and qcow2 support is required, load the nbd
        module. always unload the module first to ensure it is in a clean
        state."""
        if self.nbd_tracker is not None and self.parent_node.qcow2_support_required():
            self.instance_logger("Loading NBD Kernel Module.")
            self.unload_nbd_module()
            run_only_aws(
                f"""sudo insmod /home/{os.environ['USER']}/nbd.ko nbds_max={self.nbd_tracker.NBDS_MAX}"""
            )

    def unload_nbd_module(self) -> None:
        """If NBD is available and qcow2 support is required, unload the nbd
        module."""
        if self.nbd_tracker is not None and self.parent_node.qcow2_support_required():
            self.instance_logger("Unloading NBD Kernel Module.")

            # disconnect all /dev/nbdX devices before rmmod
            self.disconnect_all_nbds_instance()
            with warn_only():
                run_only_aws("sudo rmmod nbd")

    def disconnect_all_nbds_instance(self) -> None:
        """If NBD is available and qcow2 support is required, disconnect all
        nbds on the instance."""
        if self.nbd_tracker is not None and self.parent_node.qcow2_support_required():
            self.instance_logger("Disconnecting all NBDs.")

            # warn_only, so we can call this even if there are no nbds
            with warn_only():
                # build up one large command with all the disconnects
                fullcmd = []
                for nbd_index in range(self.nbd_tracker.NBDS_MAX):
                    fullcmd.append(
                        """sudo qemu-nbd -d /dev/nbd{nbdno}""".format(nbdno=nbd_index)
                    )

                run_only_aws("; ".join(fullcmd))

    def get_remote_sim_dir_for_slot(self, slotno: int) -> str:
        """Returns the path on the remote for a given slot number."""
        remote_home_dir = self.parent_node.get_sim_dir()
        remote_sim_dir = f"{remote_home_dir}/sim_slot_{slotno}/"

        # so that callers can reliably concatenate folders to the returned value
        assert (
            remote_sim_dir[-1] == "/"
        ), f"Return value of get_remote_sim_dir_for_slot({slotno}) must end with '/'."

        return remote_sim_dir

    def copy_sim_slot_infrastructure(self, slotno: int, uridir: str) -> None:
        """copy all the simulation infrastructure to the remote node."""
        if self.instance_assigned_simulations():
            assert slotno < len(
                self.parent_node.sim_slots
            ), f"{slotno} can not index into sim_slots {len(self.parent_node.sim_slots)} on {self.parent_node.host}"
            serv = self.parent_node.sim_slots[slotno]

            self.instance_logger(
                f"""Copying {self.sim_type_message} simulation infrastructure for slot: {slotno}."""
            )

            remote_sim_dir = self.get_remote_sim_dir_for_slot(slotno)
            remote_sim_rsync_dir = remote_sim_dir + "rsyncdir/"
            run(f"mkdir -p {remote_sim_rsync_dir}")

            files_to_copy = serv.get_required_files_local_paths()

            # Append required URI paths to the end of this list
            hwcfg = serv.get_resolved_server_hardware_config()
            files_to_copy.extend(hwcfg.get_local_uri_paths(uridir))

            for local_path, remote_path in files_to_copy:
                # -z --inplace
                rsync_cap = rsync_project(
                    local_dir=local_path,
                    remote_dir=pjoin(remote_sim_rsync_dir, remote_path),
                    ssh_opts="-o StrictHostKeyChecking=no",
                    extra_opts="-L",
                    capture=True,
                )
                rootLogger.debug(rsync_cap)
                rootLogger.debug(rsync_cap.stderr)

            run(f"cp -r {remote_sim_rsync_dir}/* {remote_sim_dir}/", shell=True)

    def extract_driver_tarball(self, slotno: int) -> None:
        """extract tarball that already exists on the remote node."""
        if self.instance_assigned_simulations():
            assert slotno < len(self.parent_node.sim_slots)
            serv = self.parent_node.sim_slots[slotno]

            hwcfg = serv.get_resolved_server_hardware_config()

            remote_sim_dir = self.get_remote_sim_dir_for_slot(slotno)
            options = "-xf"

            with cd(remote_sim_dir):
                run(f"tar {options} {hwcfg.get_driver_tar_filename()}")

    def copy_switch_slot_infrastructure(self, switchslot: int) -> None:
        """copy all the switch infrastructure to the remote node."""
        if self.instance_assigned_switches():
            self.instance_logger(
                """Copying switch simulation infrastructure for switch slot: {}.""".format(
                    switchslot
                )
            )
            remote_home_dir = self.parent_node.get_sim_dir()
            remote_switch_dir = """{}/switch_slot_{}/""".format(
                remote_home_dir, switchslot
            )
            run("""mkdir -p {}""".format(remote_switch_dir))

            assert switchslot < len(self.parent_node.switch_slots)
            switch = self.parent_node.switch_slots[switchslot]
            files_to_copy = switch.get_required_files_local_paths()
            for local_path, remote_path in files_to_copy:
                put(
                    local_path,
                    pjoin(remote_switch_dir, remote_path),
                    mirror_local_mode=True,
                )

    def start_switch_slot(self, switchslot: int) -> None:
        """start a switch simulation."""
        if self.instance_assigned_switches():
            self.instance_logger(
                """Starting switch simulation for switch slot: {}.""".format(switchslot)
            )
            remote_home_dir = self.parent_node.get_sim_dir()
            remote_switch_dir = """{}/switch_slot_{}/""".format(
                remote_home_dir, switchslot
            )
            assert switchslot < len(self.parent_node.switch_slots)
            switch = self.parent_node.switch_slots[switchslot]
            with cd(remote_switch_dir):
                run(switch.get_switch_start_command())

    def copy_pipe_slot_infrastructure(self, pipeslot: int) -> None:
        """copy all the pipe infrastructure to the remote node."""
        if self.instance_assigned_pipes():
            self.instance_logger(
                """Copying pipe simulation infrastructure for pipe slot: {}.""".format(
                    pipeslot
                )
            )
            remote_home_dir = self.parent_node.get_sim_dir()
            remote_pipe_dir = """{}/pipe_slot_{}/""".format(remote_home_dir, pipeslot)
            run("""mkdir -p {}""".format(remote_pipe_dir))

            assert pipeslot < len(self.parent_node.pipe_slots)
            pipe = self.parent_node.pipe_slots[pipeslot]
            files_to_copy = pipe.get_required_files_local_paths()
            for local_path, remote_path in files_to_copy:
                put(
                    local_path,
                    pjoin(remote_pipe_dir, remote_path),
                    mirror_local_mode=True,
                )

    def start_pipe_slot(self, pipeslot: int) -> None:
        """start a pipe simulation."""
        if self.instance_assigned_pipes():
            self.instance_logger(
                """Starting pipe simulation for pipe slot: {}.""".format(pipeslot)
            )
            remote_home_dir = self.parent_node.get_sim_dir()
            remote_pipe_dir = """{}/pipe_slot_{}/""".format(remote_home_dir, pipeslot)
            assert pipeslot < len(self.parent_node.pipe_slots)
            pipe = self.parent_node.pipe_slots[pipeslot]
            with cd(remote_pipe_dir):
                run(pipe.get_pipe_start_command(has_sudo()))

    def start_sim_slot(self, slotno: int) -> None:
        """start a simulation."""
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
            rootLogger.info(
                f"start_sim_slot slotno: {slotno} server_id {server.server_id_internal} remote_sim_dir {remote_sim_dir} {remote_home_dir}"
            )

            # make the local job results dir for this sim slot
            server.mkdir_and_prep_local_job_results_dir()
            sim_start_script_local_path = server.write_sim_start_script(
                slotno, f"+slotid={slotno}"
            )
            put(sim_start_script_local_path, remote_sim_dir)

            with cd(remote_sim_dir):
                run("chmod +x sim-run.sh")
                run("./sim-run.sh")

    def kill_switch_slot(self, switchslot: int) -> None:
        """kill the switch in slot switchslot."""
        if self.instance_assigned_switches():
            self.instance_logger(
                """Killing switch simulation for switchslot: {}.""".format(switchslot)
            )
            assert switchslot < len(self.parent_node.switch_slots)
            switch = self.parent_node.switch_slots[switchslot]
            with warn_only():
                run(switch.get_switch_kill_command())

    def kill_pipe_slot(self, pipeslot: int) -> None:
        """kill the pipe in slot pipeslot."""
        if self.instance_assigned_pipes():
            self.instance_logger(
                """Killing pipe simulation for pipeslot: {}.""".format(pipeslot)
            )
            assert pipeslot < len(self.parent_node.pipe_slots)
            pipe = self.parent_node.pipe_slots[pipeslot]
            with warn_only():
                if has_sudo():
                    run("sudo " + pipe.get_pipe_kill_command())
                else:
                    run(pipe.get_pipe_kill_command())

    def kill_sim_slot(self, slotno: int) -> None:
        """kill the simulation in slot slotno."""
        if self.instance_assigned_simulations():
            self.instance_logger(
                f"""Killing {self.sim_type_message} simulation for slot: {slotno}."""
            )
            assert slotno < len(
                self.parent_node.sim_slots
            ), f"{slotno} can not index into sim_slots {len(self.parent_node.sim_slots)} on {self.parent_node.host}"
            server = self.parent_node.sim_slots[slotno]
            with warn_only():
                run(server.get_sim_kill_command(slotno))

    def instance_assigned_simulations(self) -> bool:
        """return true if this instance has any assigned fpga simulations."""
        return len(self.parent_node.sim_slots) != 0

    def instance_assigned_switches(self) -> bool:
        """return true if this instance has any assigned switch simulations."""
        return len(self.parent_node.switch_slots) != 0

    def instance_assigned_pipes(self) -> bool:
        """return true if this instance has any assigned pipe simulations."""
        return len(self.parent_node.pipe_slots) != 0

    def remove_shm_files(self) -> None:
        if is_on_aws():
            run("sudo rm -rf /dev/shm/*")
        else:
            cmd = f"{script_path}/firesim-remove-dev-shm"
            check_script(cmd)
            run(f"sudo {cmd}")

    def start_pipe_slots(self) -> None:
        for slotno in range(len(self.parent_node.pipe_slots)):
            self.start_pipe_slot(slotno)

    def start_switch_slots(self) -> None:
        for slotno in range(len(self.parent_node.switch_slots)):
            self.start_switch_slot(slotno)

    def start_switches_and_pipes_instance(self) -> None:
        """Boot up all the switches and pipes on this host in screens."""
        if self.instance_assigned_pipes() or self.instance_assigned_switches():
            self.remove_shm_files()

        if self.instance_assigned_pipes() and self.instance_assigned_switches():
            self.start_switch_slots()
            self.start_pipe_slots()
        elif self.instance_assigned_pipes():
            self.start_pipe_slots()
        elif self.instance_assigned_switches():
            self.start_switch_slots()

    def start_simulations_instance(self) -> None:
        """Boot up all the sims on this host in screens."""
        if self.instance_assigned_simulations():
            # only on sim nodes
            rootLogger.info(
                f"start_simulations_instance {len(self.parent_node.sim_slots)}"
            )
            for slotno in range(len(self.parent_node.sim_slots)):
                self.start_sim_slot(slotno)

    def kill_switches_instance(self) -> None:
        """Kill all the switches on this host."""
        if self.instance_assigned_switches():
            for slotno in range(len(self.parent_node.switch_slots)):
                self.kill_switch_slot(slotno)
            self.remove_shm_files()

    def kill_pipes_instance(self) -> None:
        if self.instance_assigned_pipes():
            for slotno in range(len(self.parent_node.pipe_slots)):
                self.kill_pipe_slot(slotno)
            self.remove_shm_files()  # TODO : remove shm files for only this instance

    def kill_simulations_instance(self, disconnect_all_nbds: bool = True) -> None:
        """Kill all simulations on this host."""
        if self.instance_assigned_simulations():
            # only on sim nodes
            for slotno in range(len(self.parent_node.sim_slots)):
                self.kill_sim_slot(slotno)
        if disconnect_all_nbds:
            # disconnect all NBDs
            self.disconnect_all_nbds_instance()

    def running_simulations(self) -> Dict[str, List[str]]:
        """collect screen results from this host to see what's running on it."""
        simdrivers = []
        switches = []
        pipes = []
        with settings(warn_only=True), hide("everything"):
            collect = run("screen -ls")
            for line in collect.splitlines():
                if "(Detached)" in line or "(Attached)" in line:
                    line_stripped = line.strip()
                    if "fsim" in line:
                        re_search_results = re.search(
                            "fsim([0-9][0-9]*)", line_stripped
                        )
                        assert re_search_results is not None
                        line_stripped = re_search_results.group(0)
                        line_stripped = line_stripped.replace("fsim", "")
                        simdrivers.append(line_stripped)
                    elif "switch" in line:
                        re_search_results = re.search(
                            "switch([0-9][0-9]*)", line_stripped
                        )
                        assert re_search_results is not None
                        line_stripped = re_search_results.group(0)
                        switches.append(line_stripped)
                    elif "pipe" in line:
                        re_search_results = re.search(
                            "pipe([0-9][0-9]*)", line_stripped
                        )
                        assert re_search_results is not None
                        line_stripped = re_search_results.group(0)
                        pipes.append(line_stripped)
        return {"switches": switches, "simdrivers": simdrivers, "pipes": pipes}

    def monitor_jobs_instance(
        self,
        prior_completed_jobs: List[str],
        is_final_loop: bool,
        is_networked: bool,
        terminateoncompletion: bool,
        job_results_dir: str,
    ) -> Dict[str, Dict[str, bool]]:
        """Job monitoring for this host."""
        self.instance_logger(
            f"Final loop?: {is_final_loop} Is networked?: {is_networked} Terminateoncomplete: {terminateoncompletion}",
            debug=True,
        )
        self.instance_logger(
            f"Prior completed jobs: {prior_completed_jobs}", debug=True
        )

        def do_terminate():
            if (not is_networked) or (is_networked and is_final_loop):
                if terminateoncompletion:
                    self.terminate_instance()

        if not self.instance_assigned_simulations() and (
            self.instance_assigned_switches() or self.instance_assigned_pipes()
        ):
            self.instance_logger(f"Polling switch/pipe-only node", debug=True)

            # just confirm that our switches are still running
            # switches will never trigger shutdown in the cycle-accurate -
            # they should run forever until torn down
            if is_final_loop:
                self.instance_logger(
                    f"Completing copies for switch-only node", debug=True
                )

                for counter in range(len(self.parent_node.switch_slots)):
                    switchsim = self.parent_node.switch_slots[counter]
                    switchsim.copy_back_switchlog_from_run(job_results_dir, counter)

                for counter in range(len(self.parent_node.pipe_slots)):
                    pipesim = self.parent_node.pipe_slots[counter]
                    pipesim.copy_back_pipelog_from_run(job_results_dir, counter)

                do_terminate()

                return {"switches": {}, "sims": {}}
            else:
                # get the status of the switch sims
                switchescompleteddict = {
                    k: False for k in self.running_simulations()["switches"]
                }
                for switchsim in self.parent_node.switch_slots:
                    swname = switchsim.switch_builder.switch_binary_name()
                    if swname not in switchescompleteddict.keys():
                        switchescompleteddict[swname] = True

                pipescompleteddict = {
                    k: False for k in self.running_simulations()["pipes"]
                }
                for pipesim in self.parent_node.pipe_slots:
                    pipename = pipesim.pipe_builder.pipe_binary_name()
                    if pipename not in pipescompleteddict.keys():
                        pipescompleteddict[pipename] = True

                return {
                    "switches": switchescompleteddict,
                    "sims": {},
                    "pipes": pipescompleteddict,
                }

        if self.instance_assigned_simulations():
            # this node has sims attached
            self.instance_logger(
                f"Polling node with simulations (and potentially switches)", debug=True
            )

            sim_slots = self.parent_node.sim_slots
            jobnames = [slot.get_job_name() for slot in sim_slots]
            all_jobs_completed = all(
                [(job in prior_completed_jobs) for job in jobnames]
            )

            self.instance_logger(f"jobnames: {jobnames}", debug=True)
            self.instance_logger(
                f"All jobs completed?: {all_jobs_completed}", debug=True
            )

            if all_jobs_completed:
                do_terminate()

                # in this case, all of the nodes jobs have already completed. do nothing.
                # this can never happen in the cycle-accurate case at a point where we care
                # about switch status, so don't bother to populate it
                jobnames_to_completed = {jname: True for jname in jobnames}
                return {"sims": jobnames_to_completed, "switches": {}}

            # at this point, all jobs are NOT completed. so, see how they're doing now:
            instance_screen_status = self.running_simulations()

            switchescompleteddict = {
                k: False for k in instance_screen_status["switches"]
            }
            pipescompleteddict = {k: False for k in instance_screen_status["pipes"]}
            slotsrunning = [x for x in instance_screen_status["simdrivers"]]
            self.instance_logger(
                f"Switch Slots running: {switchescompleteddict}", debug=True
            )
            self.instance_logger(
                f"pipe Slots running: {pipescompleteddict}", debug=True
            )
            self.instance_logger(f"Sim Slots running: {slotsrunning}", debug=True)

            if self.instance_assigned_switches():
                # fill in whether switches have terminated
                for switchsim in self.parent_node.switch_slots:
                    sw_name = switchsim.switch_builder.switch_binary_name()
                    if sw_name not in switchescompleteddict.keys():
                        switchescompleteddict[sw_name] = True

            if self.instance_assigned_pipes():
                for pipesim in self.parent_node.pipe_slots:
                    pipename = pipesim.pipe_builder.pipe_binary_name()
                    if pipename not in pipescompleteddict.keys():
                        pipescompleteddict[pipename] = True

            # fill in whether sims have terminated
            completed_jobs = (
                prior_completed_jobs.copy()
            )  # create local copy to append to
            for slotno, jobname in enumerate(jobnames):
                if (str(slotno) not in slotsrunning) and (
                    jobname not in completed_jobs
                ):
                    self.instance_logger(f"Slot {slotno}, Job {jobname} completed!")
                    completed_jobs.append(jobname)

                    # this writes the job monitoring file
                    sim_slots[slotno].copy_back_job_results_from_run(slotno)

            jobs_complete_dict = {job: job in completed_jobs for job in jobnames}
            now_all_jobs_complete = all(jobs_complete_dict.values())
            self.instance_logger(f"Now done?: {now_all_jobs_complete}", debug=True)

            if now_all_jobs_complete:
                if self.instance_assigned_switches():
                    # we have switches running here, so kill them,
                    # then copy off their logs. this handles the case where you
                    # have a node with one simulation and some switches, to make
                    # sure the switch logs are copied off.
                    #
                    # the other cases are when you have multiple sims and a cycle-acc network,
                    # in which case the all() will never actually happen (unless someone builds
                    # a workload where two sims exit at exactly the same time, which we should
                    # advise users not to do)
                    #
                    # a last use case is when there's no network, in which case
                    # instance_assigned_switches won't be true, so this won't be called

                    self.kill_switches_instance()

                    for counter, switch_slot in enumerate(
                        self.parent_node.switch_slots
                    ):
                        switch_slot.copy_back_switchlog_from_run(
                            job_results_dir, counter
                        )

                if self.instance_assigned_pipes():
                    self.kill_pipes_instance()
                    for counter, pipe_slot in enumerate(self.parent_node.pipe_slots):
                        pipe_slot.copy_back_pipelog_from_run(job_results_dir, counter)

                do_terminate()

            return {
                "switches": switchescompleteddict,
                "sims": jobs_complete_dict,
                "pipes": pipescompleteddict,
            }

        assert False
