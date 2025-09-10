from __future__ import with_statement, annotations

import yaml
import logging
import os
from fabric.api import prefix, local, run, env, lcd, parallel, settings  # type: ignore
from fabric.contrib.console import confirm  # type: ignore
from fabric.contrib.project import rsync_project  # type: ignore

from buildtools.bitbuilder import BitBuilder
from buildtools.utils import get_deploy_dir
from utils.streamlogger import InfoStreamLogger
from utils.export import create_export_string
from awstools.afitools import firesim_tags_to_description, copy_afi_to_all_regions
from awstools.awstools import (
    send_firesim_notification,
    get_aws_userid,
    get_aws_region,
    auto_create_bucket,
    valid_aws_configure_creds,
    aws_resource_names,
    get_snsname_arn,
)

# imports needed for python type checking
from typing import Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from buildtools.build_config import BuildConfig

rootLogger = logging.getLogger()


class VitisBitBuilder(BitBuilder):
    """Bit builder class that builds a Vitis bitstream from the build config.

    Attributes:
        device: vitis fpga platform string to use for building the bitstream
    """

    device: str

    def __init__(self, build_config: BuildConfig, args: Dict[str, Any]) -> None:
        super().__init__(build_config, args)
        self._parse_args()

    def _parse_args(self) -> None:
        """Parse bitbuilder arguments."""
        self.device = self.args["device"]

    def setup(self) -> None:
        return

    def cl_dir_setup(self, chisel_quintuplet: str, dest_build_dir: str) -> str:
        """Setup CL_DIR on build host.

        Args:
            chisel_quintuplet: Build config chisel quintuplet used to uniquely identify build dir.
            dest_build_dir: Destination base directory to use.

        Returns:
            Path to CL_DIR directory (that is setup) or `None` if invalid.
        """
        fpga_build_postfix = f"cl_{chisel_quintuplet}"

        # local paths
        local_vitis_dir = f"{get_deploy_dir()}/../platforms/vitis"

        dest_vitis_dir = "{}/platforms/vitis".format(dest_build_dir)

        # copy vitis to the build instance.
        # do the rsync, but ignore any checkpoints that might exist on this machine
        # (in case builds were run locally)
        # extra_opts -l preserves symlinks

        run("mkdir -p {}".format(dest_vitis_dir))
        run("rm -rf {}/{}".format(dest_vitis_dir, fpga_build_postfix))
        rsync_cap = rsync_project(
            local_dir=local_vitis_dir,
            remote_dir=dest_vitis_dir,
            ssh_opts="-o StrictHostKeyChecking=no",
            exclude="cl_*",
            extra_opts="-l",
            capture=True,
        )
        rootLogger.debug(rsync_cap)
        rootLogger.debug(rsync_cap.stderr)
        rsync_cap = rsync_project(
            local_dir="{}/{}/".format(local_vitis_dir, fpga_build_postfix),
            remote_dir="{}/{}".format(dest_vitis_dir, fpga_build_postfix),
            ssh_opts="-o StrictHostKeyChecking=no",
            extra_opts="-l",
            capture=True,
        )
        rootLogger.debug(rsync_cap)
        rootLogger.debug(rsync_cap.stderr)

        return f"{dest_vitis_dir}/{fpga_build_postfix}"

    def build_bitstream(self, bypass: bool = False) -> bool:
        """Run Vitis to generate an xclbin. Then terminate the instance at the end.

        Args:
            bypass: If true, immediately return and terminate build host. Used for testing purposes.

        Returns:
            Boolean indicating if the build passed or failed.
        """
        build_farm = self.build_config.build_config_file.build_farm

        if bypass:
            build_farm.release_build_host(self.build_config)
            return True

        # The default error-handling procedure. Send an email and teardown instance
        def on_build_failure():
            """Terminate build host and notify user that build failed"""

            message_title = "FireSim Vitis FPGA Build Failed"

            message_body = (
                "Your FPGA build failed for quintuplet: "
                + self.build_config.get_chisel_quintuplet()
            )

            rootLogger.info(message_title)
            rootLogger.info(message_body)

            build_farm.release_build_host(self.build_config)

        rootLogger.info("Building Vitis Bitstream from Verilog")

        local_deploy_dir = get_deploy_dir()
        fpga_build_postfix = f"cl_{self.build_config.get_chisel_quintuplet()}"
        local_results_dir = (
            f"{local_deploy_dir}/results-build/{self.build_config.get_build_dir_name()}"
        )

        # 'cl_dir' holds the eventual directory in which vivado will run.
        cl_dir = self.cl_dir_setup(
            self.build_config.get_chisel_quintuplet(),
            build_farm.get_build_host(self.build_config).dest_build_dir,
        )

        vitis_rc = 0
        # copy script to the cl_dir and execute
        rsync_cap = rsync_project(
            local_dir=f"{local_deploy_dir}/../platforms/vitis/build-bitstream.sh",
            remote_dir=f"{cl_dir}/",
            ssh_opts="-o StrictHostKeyChecking=no",
            extra_opts="-l",
            capture=True,
        )
        rootLogger.debug(rsync_cap)
        rootLogger.debug(rsync_cap.stderr)

        fpga_frequency = self.build_config.get_frequency()
        build_strategy = self.build_config.get_strategy().name

        with InfoStreamLogger("stdout"), settings(warn_only=True):
            vitis_result = run(
                f"{cl_dir}/build-bitstream.sh --build_dir {cl_dir} --device {self.device} --frequency {fpga_frequency} --strategy {build_strategy}"
            )
            vitis_rc = vitis_result.return_code

            if vitis_rc != 0:
                rootLogger.info("Printing error output:")
                for line in vitis_result.splitlines()[-100:]:
                    rootLogger.info(line)

        # put build results in the result-build area

        rsync_cap = rsync_project(
            local_dir=f"{local_results_dir}/",
            remote_dir=cl_dir,
            ssh_opts="-o StrictHostKeyChecking=no",
            upload=False,
            extra_opts="-l",
            capture=True,
        )
        rootLogger.debug(rsync_cap)
        rootLogger.debug(rsync_cap.stderr)

        if vitis_rc != 0:
            on_build_failure()
            return False

        hwdb_entry_name = self.build_config.name
        local_cl_dir = f"{local_results_dir}/{fpga_build_postfix}"

        bit_path = f"{local_cl_dir}/bitstream/build_dir.{self.device}/firesim.xclbin"
        tar_staging_path = f"{local_cl_dir}/{self.build_config.PLATFORM}"
        tar_name = "firesim.tar.gz"

        # store files into staging dir
        local(f"rm -rf {tar_staging_path}")
        local(f"mkdir -p {tar_staging_path}")

        # store bitfile
        local(f"cp {bit_path} {tar_staging_path}")

        # store metadata string
        local(f"""echo '{self.get_metadata_string()}' >> {tar_staging_path}/metadata""")

        # form tar.gz
        with prefix(f"cd {local_cl_dir}"):
            local(f"tar zcvf {tar_name} {self.build_config.PLATFORM}/")

        hwdb_entry = hwdb_entry_name + ":\n"
        hwdb_entry += f"    bitstream_tar: file://{local_cl_dir}/{tar_name}\n"
        hwdb_entry += f"    deploy_quintuplet_override: null\n"
        hwdb_entry += "    custom_runtime_config: null\n"

        message_title = "FireSim FPGA Build Completed"
        message_body = (
            "Your bitstream has been created!\nAdd\n\n"
            + hwdb_entry
            + "\nto your config_hwdb.yaml to use this hardware configuration."
        )

        rootLogger.info(message_title)
        rootLogger.info(message_body)

        # for convenience when generating a bunch of images. you can just
        # cat all the files in this directory after your builds finish to get
        # all the entries to copy into config_hwdb.yaml
        hwdb_entry_file_location = f"{local_deploy_dir}/built-hwdb-entries/"
        local("mkdir -p " + hwdb_entry_file_location)
        with open(hwdb_entry_file_location + "/" + hwdb_entry_name, "w") as outputfile:
            outputfile.write(hwdb_entry)

        if self.build_config.post_build_hook:
            localcap = local(
                f"{self.build_config.post_build_hook} {local_results_dir}", capture=True
            )
            rootLogger.debug("[localhost] " + str(localcap))
            rootLogger.debug("[localhost] " + str(localcap.stderr))

        rootLogger.info(
            f"Build complete! Vitis bitstream ready. See {os.path.join(hwdb_entry_file_location,hwdb_entry_name)}."
        )

        build_farm.release_build_host(self.build_config)

        return True
