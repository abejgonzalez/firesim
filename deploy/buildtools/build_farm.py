import logging
import abc
import pprint

from buildtools.build_config import BuildConfig

# imports needed for python type checking
from typing import Any, Dict, Optional, List, TYPE_CHECKING


rootLogger = logging.getLogger()


class BuildHost:
    """Class representing a single basic platform-agnostic build host which holds a single build config.

    Attributes:
        build_config: Build config associated with the build host.
        dest_build_dir: Name of build dir on build host.
        ip_address: IP address of build host.
    """

    build_config: Optional[BuildConfig]
    dest_build_dir: str
    ip_address: Optional[str]

    def __init__(
        self,
        dest_build_dir: str,
        build_config: Optional[BuildConfig] = None,
        ip_address: Optional[str] = None,
    ) -> None:
        """
        Args:
            dest_build_dir: Name of build dir on build host.
            build_config: Build config associated with the build host.
            ip_address: IP address of build host.
        """
        self.build_config = build_config
        self.ip_address = ip_address
        self.dest_build_dir = dest_build_dir

    def __repr__(self) -> str:
        return f"{type(self)}(build_config={self.build_config!r}, dest_build_dir={self.dest_build_dir} ip_address={self.ip_address})"

    def __str__(self) -> str:
        return pprint.pformat(vars(self), width=1, indent=10)


class BuildFarm(metaclass=abc.ABCMeta):
    """Abstract class representing a build farm managing multiple build hosts (request, wait, release, etc).

    Attributes:
        build_hosts: List of build hosts used for builds.
        args: Set of options from the 'args' section of the YAML associated with the build farm.
    """

    build_hosts: List[
        Any
    ]  # Use Any for now to avoid circular dependency with BuildHost
    args: Dict[str, Any]

    def __init__(self, args: Dict[str, Any]) -> None:
        """
        Args:
            args: Args (i.e. options) passed to the build farm.
        """
        self.args = args
        self.build_hosts = []

    @abc.abstractmethod
    def request_build_host(self, build_config: BuildConfig) -> None:
        """Request build host to use for build config.

        Args:
            build_config: Build config to request build host for.
        """
        return

    @abc.abstractmethod
    def wait_on_build_host_initialization(self, build_config: BuildConfig) -> None:
        """Ensure build host is launched and ready to be used.

        Args:
            build_config: Build config used to find build host that must ready.
        """
        return

    def get_build_host(self, build_config: BuildConfig) -> Any:  # Use Any for now
        """Get build host associated with the build config.

        Args:
            build_config: Build config used to find build host for.

        Returns:
            Build host associated with the build config.
        """
        for build_host in self.build_hosts:
            if build_host.build_config == build_config:
                return build_host

        raise Exception(f"Unable to find build host for {build_config.name}")

    def get_build_host_ip(self, build_config: BuildConfig) -> str:
        """Get IP address associated with this dispatched build host.

        Args:
            build_config: Build config to find build host for.

        Returns:
            IP address for the specific build host.
        """
        build_host = self.get_build_host(build_config)
        ip_address = build_host.ip_address
        assert (
            ip_address is not None
        ), f"Unassigned IP address for build host: {build_host}"
        return ip_address

    @abc.abstractmethod
    def release_build_host(self, build_config: BuildConfig) -> None:
        """Release the build host.

        Args:
            build_config: Build config to find build host to terminate.
        """
        return

    def __repr__(self) -> str:
        return f"< {type(self)}(build_hosts={self.build_hosts!r} args={self.args!r}) >"

    def __str__(self) -> str:
        return pprint.pformat(vars(self), width=1, indent=10)
