import pprint

from buildtools.build_farm import BuildHost

# imports needed for python type checking
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from buildtools.build_config import BuildConfig
    from mypy_boto3_ec2.service_resource import Instance as EC2InstanceResource


class EC2BuildHost(BuildHost):
    """Class representing an EC2-specific build host instance.

    Attributes:
        launched_instance_object: Boto instance object associated with the build host.
    """

    launched_instance_object: EC2InstanceResource

    def __init__(
        self,
        build_config: BuildConfig,
        inst_obj: EC2InstanceResource,
        dest_build_dir: str,
    ) -> None:
        """
        Args:
            build_config: Build config associated with the build host.
            inst_obj: Boto instance object associated with the build host.
            dest_build_dir: Name of build dir on build host.
        """
        super().__init__(build_config=build_config, dest_build_dir=dest_build_dir)
        self.launched_instance_object = inst_obj

    def __repr__(self) -> str:
        return f"{type(self)}(build_config={self.build_config!r}, dest_build_dir={self.dest_build_dir}, ip_address={self.ip_address}, launched_instance_object={self.launched_instance_object!r})"

    def __str__(self) -> str:
        return pprint.pformat(vars(self), width=1, indent=10)
