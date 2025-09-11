from __future__ import with_statement, annotations

import yaml
import json
import time
import random
import string
from absl import logging
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
from typing import Optional, Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from buildtools.build_config import BuildConfig


class F1BitBuilder(BitBuilder):
    """Bit builder class that builds a AWS EC2 F1 AGFI (bitstream) from the build config.

    Attributes:
        s3_bucketname: S3 bucketname for AFI builds.
    """

    s3_bucketname: str

    def __init__(self, build_config: BuildConfig, args: Dict[str, Any]) -> None:
        super().__init__(build_config, args)
        self._parse_args()

    def _parse_args(self) -> None:
        """Parse bitbuilder arguments."""
        self.s3_bucketname = self.args["s3_bucket_name"]
        if valid_aws_configure_creds():
            if self.args["append_userid_region"]:
                self.s3_bucketname += "-" + get_aws_userid() + "-" + get_aws_region()

            aws_resource_names_dict = aws_resource_names()
            if aws_resource_names_dict["s3bucketname"] is not None:
                # in tutorial mode, special s3 bucket name
                self.s3_bucketname = aws_resource_names_dict["s3bucketname"]

    def setup(self) -> None:
        auto_create_bucket(self.s3_bucketname)

        # check to see email notifications can be subscribed
        get_snsname_arn()

    def cl_dir_setup(self, chisel_quintuplet: str, dest_build_dir: str) -> str:
        """Setup CL_DIR on build host.

        Args:
            chisel_quintuplet: Build config chisel quintuplet used to uniquely identify build dir.
            dest_build_dir: Destination base directory to use.

        Returns:
            Path to CL_DIR directory (that is setup) or `None` if invalid.
        """
        fpga_build_postfix = f"hdk/cl/developer_designs/cl_{chisel_quintuplet}"

        # local paths
        local_awsfpga_dir = f"{get_deploy_dir()}/../platforms/f1/aws-fpga"

        dest_f1_platform_dir = f"{dest_build_dir}/platforms/f1/"
        dest_awsfpga_dir = f"{dest_f1_platform_dir}/aws-fpga"

        # copy aws-fpga to the build instance.
        # do the rsync, but ignore any checkpoints that might exist on this machine
        # (in case builds were run locally)
        # extra_opts -l preserves symlinks
        run(f"mkdir -p {dest_f1_platform_dir}")
        rsync_cap = rsync_project(
            local_dir=local_awsfpga_dir,
            remote_dir=dest_f1_platform_dir,
            ssh_opts="-o StrictHostKeyChecking=no",
            exclude=["hdk/cl/developer_designs/cl_*"],
            extra_opts="-l",
            capture=True,
        )
        logging.debug(rsync_cap)
        logging.debug(rsync_cap.stderr)
        rsync_cap = rsync_project(
            local_dir=f"{local_awsfpga_dir}/{fpga_build_postfix}/*",
            remote_dir=f"{dest_awsfpga_dir}/{fpga_build_postfix}",
            exclude=["build/checkpoints"],
            ssh_opts="-o StrictHostKeyChecking=no",
            extra_opts="-l",
            capture=True,
        )
        logging.debug(rsync_cap)
        logging.debug(rsync_cap.stderr)

        return f"{dest_awsfpga_dir}/{fpga_build_postfix}"

    def build_bitstream(self, bypass: bool = False) -> bool:
        """Run Vivado, convert tar -> AGFI/AFI, and then terminate the instance at the end.

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

            message_title = "FireSim FPGA Build Failed"

            message_body = (
                "Your FPGA build failed for quintuplet: "
                + self.build_config.get_chisel_quintuplet()
            )

            send_firesim_notification(message_title, message_body)

            logging.info(message_title)
            logging.info(message_body)

            build_farm.release_build_host(self.build_config)

        logging.info("Building AWS F1 AGFI from Verilog")

        local_deploy_dir = get_deploy_dir()
        fpga_build_postfix = (
            f"hdk/cl/developer_designs/cl_{self.build_config.get_chisel_quintuplet()}"
        )
        local_results_dir = (
            f"{local_deploy_dir}/results-build/{self.build_config.get_build_dir_name()}"
        )

        # 'cl_dir' holds the eventual directory in which vivado will run.
        cl_dir = self.cl_dir_setup(
            self.build_config.get_chisel_quintuplet(),
            build_farm.get_build_host(self.build_config).dest_build_dir,
        )

        vivado_rc = 0

        # copy script to the cl_dir and execute
        rsync_cap = rsync_project(
            local_dir=f"{local_deploy_dir}/../platforms/f1/build-bitstream.sh",
            remote_dir=f"{cl_dir}/",
            ssh_opts="-o StrictHostKeyChecking=no",
            extra_opts="-l",
            capture=True,
        )
        logging.debug(rsync_cap)
        logging.debug(rsync_cap.stderr)

        # get the frequency and strategy
        fpga_frequency = self.build_config.get_frequency()
        build_strategy = self.build_config.get_strategy().name

        with InfoStreamLogger("stdout"), settings(warn_only=True):
            vivado_result = run(
                f"{cl_dir}/build-bitstream.sh --cl_dir {cl_dir} --frequency {fpga_frequency} --strategy {build_strategy}"
            )
            vivado_rc = vivado_result.return_code

            if vivado_result != 0:
                logging.info("Printing error output:")
                for line in vivado_result.splitlines()[-100:]:
                    logging.info(line)

        # put build results in the result-build area

        rsync_cap = rsync_project(
            local_dir=f"{local_results_dir}/",
            remote_dir=cl_dir,
            ssh_opts="-o StrictHostKeyChecking=no",
            upload=False,
            extra_opts="-l",
            capture=True,
        )
        logging.debug(rsync_cap)
        logging.debug(rsync_cap.stderr)

        if vivado_rc != 0:
            on_build_failure()
            return False

        if not self.aws_create_afi():
            on_build_failure()
            return False

        build_farm.release_build_host(self.build_config)

        return True

    def aws_create_afi(self) -> Optional[bool]:
        """Convert the tarball created by Vivado build into an Amazon Global FPGA Image (AGFI).

        Args:
            build_config: Build config to determine paths.

        Returns:
            `True` on success, `None` on error.
        """
        local_deploy_dir = get_deploy_dir()
        local_results_dir = (
            f"{local_deploy_dir}/results-build/{self.build_config.get_build_dir_name()}"
        )

        afi = None
        agfi = None
        s3bucket = self.s3_bucketname
        afiname = self.build_config.name

        description = self.get_metadata_string()

        # if we're unlucky, multiple vivado builds may launch at the same time. so we
        # append the build node IP + a random string to diff them in s3
        global_append = (
            "-"
            + str(env.host_string)
            + "-"
            + "".join(
                random.SystemRandom().choice(string.ascii_uppercase + string.digits)
                for _ in range(10)
            )
            + ".tar"
        )

        with lcd(
            f"{local_results_dir}/cl_{self.build_config.get_chisel_quintuplet()}/build/checkpoints/to_aws/"
        ):
            files = local("ls *.tar", capture=True)
            logging.debug(files)
            logging.debug(files.stderr)
            tarfile = files.split()[-1]
            s3_tarfile = tarfile + global_append
            localcap = local(
                "aws s3 cp " + tarfile + " s3://" + s3bucket + "/dcp/" + s3_tarfile,
                capture=True,
            )
            logging.debug(localcap)
            logging.debug(localcap.stderr)
            agfi_afi_ids = local(
                f"""aws ec2 create-fpga-image --input-storage-location Bucket={s3bucket},Key={"dcp/" + s3_tarfile} --logs-storage-location Bucket={s3bucket},Key={"logs/"} --name "{afiname}" --description "{description}" """,
                capture=True,
            )
            logging.debug(agfi_afi_ids)
            logging.debug(agfi_afi_ids.stderr)
            logging.debug("create-fpge-image result: " + str(agfi_afi_ids))
            ids_as_dict = json.loads(agfi_afi_ids)
            agfi = ids_as_dict["FpgaImageGlobalId"]
            afi = ids_as_dict["FpgaImageId"]
            logging.info("Resulting AGFI: " + str(agfi))
            logging.info("Resulting AFI: " + str(afi))

        logging.info("Waiting for create-fpga-image completion.")
        checkstate = "pending"
        with lcd(local_results_dir):
            while checkstate == "pending":
                imagestate = local(
                    f"aws ec2 describe-fpga-images --fpga-image-id {afi} | tee AGFI_INFO",
                    capture=True,
                )
                state_as_dict = json.loads(imagestate)
                checkstate = state_as_dict["FpgaImages"][0]["State"]["Code"]
                logging.info("Current state: " + str(checkstate))
                time.sleep(10)

        if checkstate == "available":
            # copy the image to all regions for the current user
            copy_afi_to_all_regions(afi)

            message_title = "FireSim FPGA Build Completed"
            agfi_entry = afiname + ":\n"
            agfi_entry += "    agfi: " + agfi + "\n"
            agfi_entry += "    deploy_quintuplet_override: null\n"
            agfi_entry += "    custom_runtime_config: null\n"
            message_body = (
                "Your AGFI has been created!\nAdd\n\n"
                + agfi_entry
                + "\nto your config_hwdb.yaml to use this hardware configuration."
            )

            send_firesim_notification(message_title, message_body)

            logging.info(message_title)
            logging.info(message_body)

            # for convenience when generating a bunch of images. you can just
            # cat all the files in this directory after your builds finish to get
            # all the entries to copy into config_hwdb.yaml
            hwdb_entry_file_location = f"{local_deploy_dir}/built-hwdb-entries/"
            local("mkdir -p " + hwdb_entry_file_location)
            with open(hwdb_entry_file_location + "/" + afiname, "w") as outputfile:
                outputfile.write(agfi_entry)

            if self.build_config.post_build_hook:
                localcap = local(
                    f"{self.build_config.post_build_hook} {local_results_dir}",
                    capture=True,
                )
                logging.debug("[localhost] " + str(localcap))
                logging.debug("[localhost] " + str(localcap.stderr))

            logging.info(
                f"Build complete! AFI ready. See {os.path.join(hwdb_entry_file_location,afiname)}."
            )
            return True
        else:
            return None
