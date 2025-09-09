import logging
import pprint

from buildtools.build_farm import BuildHost, BuildFarm

# imports needed for python type checking
from typing import Any, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from buildtools.build_config import BuildConfig

rootLogger = logging.getLogger()


class ExternallyProvisioned(BuildFarm):
    """Build farm that selects from a set of user-determined IPs to allocate a new build host.

    Attributes:
        build_hosts_allocated: Count of build hosts assigned with builds (`BuildConfig`s).
    """

    build_hosts_allocated: int

    def __init__(self, args: Dict[str, Any]) -> None:
        """
        Args:
            args: Args (i.e. options) passed to the build farm.
        """
        super().__init__(args)

        self._parse_args()

    def _parse_args(self) -> None:
        """Parse build host arguments."""
        self.build_hosts_allocated = 0

        build_farm_hosts_key = "build_farm_hosts"
        build_farm_hosts_list = self.args[build_farm_hosts_key]

        default_build_dir = self.args["default_build_dir"]

        # allocate N build hosts
        for build_farm_host in build_farm_hosts_list:
            if type(build_farm_host) is dict:
                # add element { ip-addr: { arg1: val1, arg2: val2, ... } }

                items = build_farm_host.items()

                assert (
                    len(items) == 1
                ), f"dict type '{build_farm_hosts_key}' items map a single IP address to a dict of options. Not: {pprint.pformat(build_farm_host)}"

                ip_addr, ip_args = next(iter(items))

                dest_build_dir = ip_args.get("override_build_dir", default_build_dir)
            elif type(build_farm_host) is str:
                # add element w/ defaults

                ip_addr = build_farm_host
                dest_build_dir = default_build_dir
            else:
                raise Exception(
                    f"""Unexpected YAML type provided in "{build_farm_hosts_key}" list. Must be dict or str."""
                )

            if not dest_build_dir:
                raise Exception("ERROR: Invalid null build dir")

            self.build_hosts.append(
                BuildHost(ip_address=ip_addr, dest_build_dir=dest_build_dir)
            )

    def request_build_host(self, build_config: BuildConfig) -> None:
        """Request build host to use for build config. Just assigns build config to build host since IP address
        is already granted by something outside of FireSim."

        Args:
            build_config: Build config to request build host for.
        """

        if len(self.build_hosts) > self.build_hosts_allocated:
            self.build_hosts[self.build_hosts_allocated].build_config = build_config
            self.build_hosts_allocated += 1
        else:
            bcf = build_config.build_config_file
            error_msg = f"ERROR: {bcf.num_builds} builds requested in `config_build.yaml` but {self.__class__.__name__} build farm only provides {len(self.build_hosts)} build hosts (i.e. IPs)."
            rootLogger.critical(error_msg)
            raise Exception(error_msg)

        return

    def wait_on_build_host_initialization(self, build_config: BuildConfig) -> None:
        """Nothing happens since the provided IP address is already granted by something outside FireSim.

        Args:
            build_config: Build config used to find build host that must ready.
        """
        return

    def release_build_host(self, build_config: BuildConfig) -> None:
        """Nothing happens. Up to the IP address provider to cleanup after itself.

        Args:
            build_config: Build config to find build host to terminate.
        """
        return

    def __repr__(self) -> str:
        return f"< {type(self)}(build_hosts={self.build_hosts!r} build_hosts_allocated={self.build_hosts_allocated}) >"

    def __str__(self) -> str:
        return pprint.pformat(vars(self), width=1, indent=10)
