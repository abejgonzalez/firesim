import logging
import os
import pprint

from awstools.awstools import (
    aws_resource_names,
    launch_instances,
    wait_on_instance_launches,
    get_instance_ids_for_instances,
    terminate_instances,
)
from buildtools.build_farm import BuildFarm
from buildtools.build_hosts.ec2 import EC2BuildHost
from buildtools.build_config import BuildConfig

# imports needed for python type checking
from typing import cast, Any, Dict, TYPE_CHECKING
from mypy_boto3_ec2.service_resource import Instance as EC2InstanceResource

rootLogger = logging.getLogger()


class AWSEC2(BuildFarm):
    """Build farm to manage AWS EC2 instances as the build hosts.

    Attributes:
        build_farm_tag: tag given to instances launched in this build farm
        instance_type: instance object type
        build_instance_market: instance market type
        spot_interruption_behavior: if spot instance, the interruption behavior
        spot_max_price: if spot instance, the max price
    """

    build_farm_tag: str
    instance_type: str
    build_instance_market: str
    spot_interruption_behavior: str
    spot_max_price: str

    def __init__(self, args: Dict[str, Any]) -> None:
        """
        Args:
            args: Args (i.e. options) passed to the build farm.
        """
        super().__init__(args)

        self._parse_args()

    def _parse_args(self) -> None:
        """Parse build host arguments."""
        # get aws specific args
        build_farm_tag_prefix = (
            ""
            if "FIRESIM_BUILDFARM_PREFIX" not in os.environ
            else os.environ["FIRESIM_BUILDFARM_PREFIX"]
        )
        if build_farm_tag_prefix != "":
            build_farm_tag_prefix += "-"

        self.build_farm_tag = build_farm_tag_prefix + self.args["build_farm_tag"]

        aws_resource_names_dict = aws_resource_names()
        if aws_resource_names_dict["buildfarmprefix"] is not None:
            # if specified, further prefix buildfarmtag
            self.build_farm_tag = (
                aws_resource_names_dict["buildfarmprefix"] + "-" + self.build_farm_tag
            )

        self.instance_type = self.args["instance_type"]
        self.build_instance_market = self.args["build_instance_market"]
        self.spot_interruption_behavior = self.args["spot_interruption_behavior"]
        self.spot_max_price = self.args["spot_max_price"]

        self.dest_build_dir = self.args["default_build_dir"]
        if not self.dest_build_dir:
            raise Exception("ERROR: Invalid null build dir")

    def request_build_host(self, build_config: BuildConfig) -> None:
        """Launch an AWS EC2 instance for the build config.

        Args:
            build_config: Build config to request build host for.
        """
        inst_obj = launch_instances(
            self.instance_type,
            1,
            self.build_instance_market,
            self.spot_interruption_behavior,
            self.spot_max_price,
            blockdevices=[
                {
                    "DeviceName": "/dev/sda1",
                    "Ebs": {
                        "VolumeSize": 200,
                        "VolumeType": "gp2",
                    },
                },
            ],
            tags={"fsimbuildcluster": self.build_farm_tag},
            randomsubnet=True,
        )[0]

        self.build_hosts.append(
            EC2BuildHost(
                build_config=build_config,
                inst_obj=inst_obj,
                dest_build_dir=self.dest_build_dir,
            )
        )

    def wait_on_build_host_initialization(self, build_config: BuildConfig) -> None:
        """Wait for EC2 instance launch.

        Args:
            build_config: Build config used to find build host that must ready.
        """
        build_host = cast(EC2BuildHost, self.get_build_host(build_config))
        wait_on_instance_launches([build_host.launched_instance_object])
        build_host.ip_address = build_host.launched_instance_object.private_ip_address

    def release_build_host(self, build_config: BuildConfig) -> None:
        """Terminate the EC2 instance running this build.

        Args:
            build_config: Build config to find build host to terminate.
        """
        build_host = cast(EC2BuildHost, self.get_build_host(build_config))
        instance_ids = get_instance_ids_for_instances(
            [build_host.launched_instance_object]
        )
        rootLogger.info(
            f"Terminating build instance {instance_ids}. Please confirm in your AWS Management Console"
        )
        terminate_instances(instance_ids, dryrun=False)

    def __repr__(self) -> str:
        return f"< {type(self)}(build_hosts={self.build_hosts!r} instance_type={self.instance_type} build_instance_market={self.build_instance_market} spot_interruption_behavior={self.spot_interruption_behavior} spot_max_price={self.spot_max_price}) >"

    def __str__(self) -> str:
        return pprint.pformat(vars(self), width=1, indent=10)
