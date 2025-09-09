from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from fabric.api import local, run, prefix  # type: ignore
from fabric.operations import _stdoutString  # type: ignore
from tempfile import TemporaryDirectory
from os.path import join as pjoin

from awstools.afitools import (
    get_firesim_deploy_quintuplet_for_agfi,
    firesim_description_to_tags,
)
from runtools.utils import is_on_aws
from util.targetprojectutils import extra_target_project_make_args, resolve_path
from buildtools.utils import get_deploy_dir
from util.streamlogger import InfoStreamLogger
from util.export import create_export_string
from .uri_container import URIContainer

from typing import Optional, Dict, Any, List, Sequence, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from runtools.utils import MacAddress
    from .simulation_configs.tracerv import TracerVConfig
    from .simulation_configs.autocounter import AutoCounterConfig
    from .simulation_configs.host_debug import HostDebugConfig
    from .simulation_configs.synth_print import SynthPrintConfig
    from .simulation_configs.partition import PartitionConfig

rootLogger = logging.getLogger()

LOCAL_DRIVERS_BASE = "../sim/output"
LOCAL_DRIVERS_GENERATED_SRC = "../sim/generated-src"
CUSTOM_RUNTIMECONFS_BASE = "../sim/custom-runtime-configs"


class RuntimeHWConfig:
    """A pythonic version of the entires in config_hwdb.yaml"""

    name: str
    platform: Optional[str]

    hwdb_file: str

    # TODO: should be abstracted out between platforms with a URI
    agfi: Optional[str]
    """User-specified, URI path to bitstream tar file"""
    bitstream_tar: Optional[str]

    deploy_quintuplet: Optional[str]
    deploy_makefrag: Optional[str]
    customruntimeconfig: str
    # note whether we've built a copy of the simulation driver for this hwconf
    driver_built: bool
    tarball_built: bool
    additional_required_files: List[Tuple[str, str]]
    driver_name_prefix: str
    local_driver_base_dir: str
    driver_type_message: str
    """User-specified, URI path to driver tarball"""
    driver_tar: Optional[str]

    """ A list of URIContainer objects, one for each URI that is able to be specified """
    uri_list: list[URIContainer]

    # Members that are initialized here also need to be initialized in
    # RuntimeBuildRecipeConfig.__init__
    def __init__(
        self,
        name: str,
        hwconfig_dict: Dict[str, Any],
        hwdb_file: str,
    ) -> None:
        self.name = name

        self.hwdb_file = hwdb_file

        if sum(["agfi" in hwconfig_dict, "bitstream_tar" in hwconfig_dict]) > 1:
            raise Exception(
                f"Must only have 'agfi' or 'bitstream_tar' HWDB entry {name}."
            )

        self.agfi = hwconfig_dict.get("agfi")
        self.bitstream_tar = hwconfig_dict.get("bitstream_tar")
        self.driver_tar = hwconfig_dict.get("driver_tar")

        self.platform = None
        self.driver_built = False
        self.tarball_built = False
        self.additional_required_files = []
        self.driver_name_prefix = ""
        self.driver_type_message = "FPGA software"
        self.local_driver_base_dir = LOCAL_DRIVERS_BASE

        self.uri_list = []

        if self.agfi is not None:
            self.platform = "f1"
        else:
            self.uri_list.append(
                URIContainer("bitstream_tar", self.get_bitstream_tar_filename())
            )

        if (
            "deploy_triplet_override" in hwconfig_dict.keys()
            and "deploy_quintuplet_override" in hwconfig_dict.keys()
        ):
            rootLogger.error(
                "Cannot have both 'deploy_quintuplet_override' and 'deploy_triplet_override' in hwdb entry. Define only 'deploy_quintuplet_override'."
            )
            sys.exit(1)
        elif "deploy_triplet_override" in hwconfig_dict.keys():
            rootLogger.warning(
                "Please rename your 'deploy_triplet_override' key in your hwdb entry to 'deploy_quintuplet_override'. Support for 'deploy_triplet_override' will be removed in the future."
            )

        hwconfig_override_build_quintuplet = hwconfig_dict.get(
            "deploy_quintuplet_override"
        )
        if hwconfig_override_build_quintuplet is None:
            # temporary backwards compat for old key
            hwconfig_override_build_quintuplet = hwconfig_dict.get(
                "deploy_triplet_override"
            )

        if (
            hwconfig_override_build_quintuplet is not None
            and len(hwconfig_override_build_quintuplet.split("-")) == 3
        ):
            # convert old build_triplet into buildquintuplet
            hwconfig_override_build_quintuplet = (
                "f1-firesim-" + hwconfig_override_build_quintuplet
            )

        self.deploy_quintuplet = hwconfig_override_build_quintuplet
        if self.deploy_quintuplet is not None:
            rootLogger.warning(
                f"{name} is overriding a deploy quintuplet in your config_hwdb.yaml file. Make sure you understand why!"
            )

        hwconfig_override_build_makefrag = hwconfig_dict.get("deploy_makefrag_override")
        self.deploy_makefrag = hwconfig_override_build_makefrag
        if self.deploy_makefrag is not None:
            rootLogger.warning(
                f"{name} is overriding a deploy makefrag in your config_hwdb.yaml file. Make sure you understand why!"
            )

        self.customruntimeconfig = hwconfig_dict["custom_runtime_config"]

        self.additional_required_files = []

        self.uri_list.append(URIContainer("driver_tar", self.get_driver_tar_filename()))
        rootLogger.debug(f"RuntimeHWConfig self.platform {self.platform}")

    def get_deploytriplet_for_config(self) -> str:
        """Get the deploytriplet for this configuration."""
        quin = self.get_deployquintuplet_for_config()
        return "-".join(quin.split("-")[2:])

    @classmethod
    def get_driver_tar_filename(cls) -> str:
        """Get the name of the tarball inside the sim_slot_X directory on the run host."""
        return "driver-bundle.tar.gz"

    @classmethod
    def get_bitstream_tar_filename(cls) -> str:
        """Get the name of the bit tar file inside the sim_slot_X directory on the run host."""
        return "firesim.tar.gz"

    def get_platform(self) -> str:
        assert self.platform is not None
        return self.platform

    def get_driver_name_suffix(self) -> str:
        return "-" + self.get_platform()

    def get_driver_build_target(self) -> str:
        return self.get_platform()

    def set_check(self, lhs: Optional[str], rhs: str, name: str) -> None:
        if lhs is not None:
            assert (
                lhs == rhs
            ), f"{name} is already set to {lhs} (cannot set it to {rhs})"
        return

    def set_platform(self, platform: str) -> None:
        self.set_check(self.platform, platform, "platform")
        self.platform = platform

    def set_deploy_quintuplet(self, deploy_quintuplet: str) -> None:
        self.set_check(self.deploy_quintuplet, deploy_quintuplet, "deploy_quintuplet")
        self.deploy_quintuplet = deploy_quintuplet

    def set_deploy_makefrag(self, deploy_makefrag: Optional[str]) -> None:
        if self.deploy_makefrag is not None:
            # self.deploy_makefrag comes from the override and thus takes precedent (can't override)
            return
        # otherwise, you can override from deploy_makefrag (which should come from metadata)
        self.deploy_makefrag = deploy_makefrag

    def get_deployquintuplet_for_config(self) -> str:
        """Get the deployquintuplet for this configuration. This memoizes the request
        to the AWS AGFI API."""
        rootLogger.debug(
            f"get_deployquintuplet_for_config {self.deploy_quintuplet} {self.get_platform}"
        )
        if self.deploy_quintuplet is not None:
            return self.deploy_quintuplet

        if self.get_platform() == "f1":
            rootLogger.debug(
                "Setting deployquintuplet by querying the AGFI's description."
            )
            self.deploy_quintuplet = get_firesim_deploy_quintuplet_for_agfi(self.agfi)
        else:
            assert False, "Unable to obtain deploy_quintuplet"

        return self.deploy_quintuplet

    def get_deployquintuplet_pieces_for_config(self) -> List[str]:
        return self.get_deployquintuplet_for_config().split("-")

    def get_deploymakefrag_for_config(self) -> Optional[str]:
        if self.deploy_makefrag:
            base = self.hwdb_file
            abs_deploy_makefrag = resolve_path(self.deploy_makefrag, base)
            if abs_deploy_makefrag is None:
                raise Exception(
                    f"Unable to find deploy_makefrag ({self.deploy_makefrag}) either as an absolute path or relative to {base}"
                )
            else:
                self.deploy_makefrag = abs_deploy_makefrag

        return self.deploy_makefrag

    def get_design_name(self) -> str:
        """Returns the name used to prefix MIDAS-emitted files. (The DESIGN make var)"""
        return self.get_deployquintuplet_pieces_for_config()[2]

    def get_local_driver_binaryname(self) -> str:
        """Get the name of the driver binary."""
        return (
            self.driver_name_prefix
            + self.get_design_name()
            + self.get_driver_name_suffix()
        )

    def get_local_driver_dir(self) -> str:
        """Get the relative local directory that contains the driver used to
        run this sim."""
        rootLogger.info(
            f"get_local_driver_dir {self.get_deployquintuplet_for_config()}"
        )
        return (
            self.local_driver_base_dir
            + "/"
            + self.get_platform()
            + "/"
            + self.get_deployquintuplet_for_config()
            + "/"
        )

    def get_local_driver_path(self) -> str:
        """return relative local path of the driver used to run this sim."""
        return self.get_local_driver_dir() + self.get_local_driver_binaryname()

    def local_quintuplet_path(self) -> Path:
        """return the local path of the quintuplet folder. the tarball that is created goes inside this folder"""
        quintuplet = self.get_deployquintuplet_for_config()
        return (
            Path(get_deploy_dir()) / "../sim/output" / self.get_platform() / quintuplet
        )

    def local_tarball_path(self, name: str) -> Path:
        """return the local path of the tarball"""
        return self.local_quintuplet_path() / name

    def get_local_runtimeconf_binaryname(self) -> str:
        """Get the name of the runtimeconf file."""
        if self.customruntimeconfig is None:
            return None
        return os.path.basename(self.customruntimeconfig)

    def get_local_runtime_conf_path(self) -> str:
        """return relative local path of the runtime conf used to run this sim."""
        if self.customruntimeconfig is None:
            return None
        return CUSTOM_RUNTIMECONFS_BASE + self.customruntimeconfig

    def get_additional_required_sim_files(self) -> List[Tuple[str, str]]:
        """return list of any additional files required to run a simulation."""
        return self.additional_required_files

    def get_boot_simulation_command(
        self,
        slotid: int,
        all_macs: Sequence[MacAddress],
        all_rootfses: Sequence[Optional[str]],
        all_linklatencies: Sequence[int],
        all_netbws: Sequence[int],
        profile_interval: int,
        all_bootbinaries: List[str],
        all_shmemportnames: List[str],
        tracerv_config: TracerVConfig,
        autocounter_config: AutoCounterConfig,
        hostdebug_config: HostDebugConfig,
        synthprint_config: SynthPrintConfig,
        partition_config: PartitionConfig,
        cutbridge_idxs: List[int],
        extra_plusargs: str,
        extra_args: str,
    ) -> str:
        """return the command used to boot the simulation. this has to have
        some external params passed to it, because not everything is contained
        in a runtimehwconfig. TODO: maybe runtimehwconfig should be renamed to
        pre-built runtime config? It kinda contains a mix of pre-built and
        runtime parameters currently."""

        # TODO: supernode support
        tracefile = "+tracefile=TRACEFILE" if tracerv_config.enable else ""
        autocounterfile = "+autocounter-filename-base=AUTOCOUNTERFILE"

        # this monstrosity boots the simulator, inside screen, inside script
        # the sed is in there to get rid of newlines in runtime confs
        driver = self.get_local_driver_binaryname()
        runtimeconf = self.get_local_runtimeconf_binaryname()

        def array_to_plusargs(
            valuesarr: Sequence[Optional[Any]], plusarg: str
        ) -> List[str]:
            args = []
            for index, arg in enumerate(valuesarr):
                if arg is not None:
                    args.append('{}{}="{}"'.format(plusarg, index, arg))
            return args

        def array_to_lognames(
            values: Sequence[Optional[Any]], prefix: str
        ) -> List[str]:
            names = [
                f"{prefix}{i}" if val is not None else None
                for (i, val) in enumerate(values)
            ]
            return array_to_plusargs(names, "+" + prefix)

        command_macs = array_to_plusargs(all_macs, "+macaddr")
        command_rootfses = array_to_plusargs(all_rootfses, "+blkdev")
        command_linklatencies = array_to_plusargs(all_linklatencies, "+linklatency")
        command_netbws = array_to_plusargs(all_netbws, "+netbw")
        command_shmemportnames = array_to_plusargs(all_shmemportnames, "+shmemportname")

        command_niclogs = array_to_lognames(all_macs, "niclog")
        command_blkdev_logs = array_to_lognames(all_rootfses, "blkdev-log")

        command_bootbinaries = array_to_plusargs(all_bootbinaries, "+prog")
        zero_out_dram = "+zero-out-dram" if (hostdebug_config.zero_out_dram) else ""
        disable_asserts = (
            "+disable-asserts" if (hostdebug_config.disable_synth_asserts) else ""
        )
        print_cycle_prefix = (
            "+print-no-cycle-prefix" if not synthprint_config.cycle_prefix else ""
        )

        # TODO supernode support
        dwarf_file_name = "+dwarf-file-name=" + all_bootbinaries[0] + "-dwarf"

        need_sudo = "sudo" if is_on_aws() else ""

        screen_name = "fsim{}".format(slotid)

        # TODO: supernode support (tracefile, trace-select.. etc)
        permissive_driver_args = []
        permissive_driver_args += (
            [f"$(sed ':a;N;$!ba;s/\n/ /g' {runtimeconf})"] if runtimeconf else []
        )
        if profile_interval != -1:
            permissive_driver_args += [f"+profile-interval={profile_interval}"]
        permissive_driver_args += [zero_out_dram]
        permissive_driver_args += [disable_asserts]
        permissive_driver_args += command_macs
        permissive_driver_args += command_rootfses
        permissive_driver_args += command_niclogs
        permissive_driver_args += command_blkdev_logs
        permissive_driver_args += [
            f"{tracefile}",
            f"+trace-select={tracerv_config.select}",
            f"+trace-start={tracerv_config.start}",
            f"+trace-end={tracerv_config.end}",
            f"+trace-output-format={tracerv_config.output_format}",
            dwarf_file_name,
        ]
        permissive_driver_args += [
            f"+autocounter-readrate={autocounter_config.readrate}",
            autocounterfile,
        ]
        permissive_driver_args += [
            print_cycle_prefix,
            f"+print-start={synthprint_config.start}",
            f"+print-end={synthprint_config.end}",
        ]
        permissive_driver_args += command_linklatencies
        permissive_driver_args += command_netbws
        permissive_driver_args += command_shmemportnames

        if partition_config.is_partitioned():
            assert partition_config.node is not None

            # For QSFP metasims, assume that the partitions are connected in a ring-topology.
            # Then, when you know your FPGA idx & the total number of FPGAs, you know
            # your lhs & rhs neighbors to communicate with.
            permissive_driver_args += [
                f"+partition-fpga-topo={partition_config.metasim_partition_topo_args()}"
            ]
            permissive_driver_args += [
                f"+partition-fpga-cnt={partition_config.fpga_cnt}"
            ]
            permissive_driver_args += [
                f"+partition-fpga-idx={partition_config.node.pidx}"
            ]

            # Disable heartbeat checking for partitions
            permissive_driver_args += [f"+partitioned=1"]

            permissive_driver_args += [f"+slotid={slotid}"]
            permissive_driver_args += [f"+batch-size={partition_config.batch_size()}"]

            command_cutbridgeidxs = array_to_plusargs(cutbridge_idxs, "+cutbridgeidx")
            permissive_driver_args += command_cutbridgeidxs

            peer_pcis_offsets = partition_config.get_pcim_slot_and_bridge_offsets()
            command_pcisoffsets = array_to_plusargs(
                peer_pcis_offsets, "+peer-pcis-offset"
            )
            permissive_driver_args += command_pcisoffsets

        driver_call = f"""{need_sudo} ./{driver} +permissive {" ".join(permissive_driver_args)} {extra_plusargs} +permissive-off {" ".join(command_bootbinaries)} {extra_args} """
        base_command = (
            f"script -f -c 'stty intr ^] && {driver_call} && stty intr ^c'uartlog"
        )
        screen_wrapped = (
            f'screen -S {screen_name} -d -m bash -c "{base_command}"; sleep 1'
        )

        return screen_wrapped

    def get_kill_simulation_command(self) -> str:
        driver = self.get_local_driver_binaryname()
        need_sudo = "sudo" if is_on_aws() else ""
        # Note that pkill only works for names <=15 characters
        return f"{need_sudo} pkill -SIGKILL {driver[:15]}"

    def handle_failure(
        self,
        buildresult: _stdoutString,
        what: str,
        dir: Path | str,
        cmd: str,
    ) -> None:
        """A helper function for a nice error message when used in conjunction with the run() function"""
        if buildresult.failed:
            rootLogger.info(
                f"{self.driver_type_message} {what} failed. Exiting. See log for details."
            )
            rootLogger.info(
                f"\nYou can also re-run '{cmd}' in the '{dir}' directory to debug this error."
            )
            sys.exit(1)

    def fetch_all_URI(self, dir: str) -> None:
        """Downloads all URI. Local filenames use a hash which will be re-calculated later. Duplicate downloads
        are skipped via an exists() check on the filesystem."""
        for container in self.uri_list:
            container.local_pre_download(dir, self)

    def get_local_uri_paths(self, dir: str) -> list[Tuple[str, str]]:
        """Get all paths of local URIs that were previously downloaded."""

        ret = list()
        for container in self.uri_list:
            maybe_file = container.get_rsync_path(dir, self)
            if maybe_file is not None:
                ret.append(maybe_file)
        return ret

    def resolve_hwcfg_values(self, dir: str) -> None:
        # must be done after fetch_all_URIs
        # based on the platform, read the URI, fill out values

        if self.platform == "f1":
            return
        else:  # bitstream_tar platforms
            for container in self.uri_list:
                both = container._choose_path(dir, self)

                # do nothing if there isn't a URI
                if both is None:
                    uri = self.bitstream_tar
                    destination = self.bitstream_tar
                else:
                    (uri, destination) = both

                if uri == self.bitstream_tar and uri is not None:
                    # unpack destination value
                    temp_dir = f"{dir}/{URIContainer.hashed_name(uri)}-dir"
                    local(f"mkdir -p {temp_dir}")
                    local(f"tar xvf {destination} -C {temp_dir}")

                    # read string from metadata
                    cap = local(f"cat {temp_dir}/*/metadata", capture=True)
                    metadata = firesim_description_to_tags(cap)

                    self.set_platform(
                        metadata["firesim-deployquintuplet"].split("-")[0]
                    )
                    self.set_deploy_quintuplet(metadata["firesim-deployquintuplet"])
                    deploy_makefrag = metadata.get(
                        "firesim-deploymakefrag", "None"
                    )  # support old metadatas that don't have this
                    rootLogger.debug(f"Got {deploy_makefrag} from metadata")
                    self.set_deploy_makefrag(
                        deploy_makefrag if deploy_makefrag != "None" else None
                    )

                    break

    def get_partition_fpga_cnt(self) -> int:
        quintuplet_pieces = self.get_deployquintuplet_pieces_for_config()
        target_split_fpga_cnt = quintuplet_pieces[5]
        return int(target_split_fpga_cnt)

    def get_partition_fpga_idx(self) -> int:
        quintuplet_pieces = self.get_deployquintuplet_pieces_for_config()
        target_split_fpga_idx = quintuplet_pieces[6]
        if target_split_fpga_idx.isnumeric():
            return int(target_split_fpga_idx)
        else:
            rootLogger.warning(f"FPGA index {target_split_fpga_idx} is not a number")
            return self.get_partition_fpga_cnt() - 1

    def build_sim_driver(self) -> None:
        """Build driver for running simulation"""
        if self.driver_built:
            # we already built the driver at some point
            return
        # TODO there is a duplicate of this in runtools
        quintuplet_pieces = self.get_deployquintuplet_pieces_for_config()
        target_project_makefrag = self.get_deploymakefrag_for_config()

        target_project = quintuplet_pieces[1]
        design = quintuplet_pieces[2]
        target_config = quintuplet_pieces[3]
        platform_config = quintuplet_pieces[4]
        rootLogger.info(
            f"Building {self.driver_type_message} driver for {str(self.get_deployquintuplet_for_config())}"
        )

        deploy_dir = get_deploy_dir()
        with InfoStreamLogger("stdout"), prefix(f"cd {deploy_dir}/.."), prefix(
            create_export_string({"RISCV", "PATH", "LD_LIBRARY_PATH"})
        ), prefix("source sourceme-manager.sh --skip-ssh-setup"), prefix("cd sim/"):
            driverbuildcommand = f"make PLATFORM={self.get_platform()} TARGET_PROJECT={target_project} {extra_target_project_make_args(target_project, target_project_makefrag, deploy_dir)} DESIGN={design} TARGET_CONFIG={target_config} PLATFORM_CONFIG={platform_config} {self.get_driver_build_target()}"
            buildresult = run(driverbuildcommand)
            self.handle_failure(
                buildresult, "driver build", "firesim/sim", driverbuildcommand
            )

        self.driver_built = True

    def build_sim_tarball(
        self,
        paths: List[Tuple[str, str]],
        tarball_name: str,
    ) -> None:
        """Take the simulation driver and tar it. build_sim_driver()
        must run before this function.  Rsync is used in a mode where it's copying
        from local paths to a local folder. This is confusing as rsync traditionally is
        used for copying from local folders to a remote folder. The variable local_remote_dir is
        named as a reminder that it's actually pointing at this local machine"""
        if self.tarball_built:
            # we already built it
            return

        # builddir is a temporary directory created by TemporaryDirectory()
        # the path a folder is under /tmp/ with a random name
        # After this scope block exists, the entire folder is deleted
        with TemporaryDirectory() as builddir:

            with InfoStreamLogger("stdout"), prefix(f"cd {get_deploy_dir()}"):
                for local_path, remote_path in paths:
                    # The `rsync_project()` function does not allow
                    # copying between two local directories.
                    # This uses the same option flags but operates rsync in local->local mode
                    options = "-pthrvz -L"
                    local_dir = local_path
                    local_remote_dir = pjoin(builddir, remote_path)
                    cmd = f"rsync {options} {local_dir} {local_remote_dir}"

                    results = run(cmd)
                    self.handle_failure(results, "local rsync", get_deploy_dir(), cmd)

            # This must be taken outside of a cd context
            cmd = f"mkdir -p {self.local_quintuplet_path()}"
            results = run(cmd)
            self.handle_failure(results, "local mkdir", builddir, cmd)
            absolute_tarball_path = self.local_quintuplet_path() / tarball_name

            with InfoStreamLogger("stdout"), prefix(f"cd {builddir}"):
                findcmd = 'find . -mindepth 1 -maxdepth 1 -printf "%P\n"'
                taroptions = "-czvf"

                # Running through find and xargs is the most simple way I've found to meet these requirements:
                #   * create the tar with no leading ./ or foldername
                #   * capture all types of hidden files (.a ..a .aa)
                #   * avoid capturing the parent folder (..) with globs looking for hidden files
                cmd = f"{findcmd} | xargs tar {taroptions} {absolute_tarball_path}"

                results = run(cmd)
                self.handle_failure(results, "tarball", builddir, cmd)

            self.tarball_built = True

    def __str__(self) -> str:
        return """RuntimeHWConfig: {}\nDeployQuintuplet: {}\nDeployMakefrag: {}\nAGFI: {}\nBitstream tar: {}\nCustomRuntimeConf: {}""".format(
            self.name,
            self.deploy_quintuplet,
            self.deploy_makefrag,
            self.agfi,
            self.bitstream_tar,
            str(self.customruntimeconfig),
        )
