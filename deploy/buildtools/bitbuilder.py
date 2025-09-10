from __future__ import with_statement, annotations

import abc
import yaml
import logging
from fabric.api import prefix, local, run, env, lcd, parallel, settings  # type: ignore
from fabric.contrib.console import confirm  # type: ignore
from fabric.contrib.project import rsync_project  # type: ignore

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


class BitBuilder(metaclass=abc.ABCMeta):
    """Abstract class to manage how to build a bitstream for a build config.

    Attributes:
        build_config: Build config to build a bitstream for.
        args: Args (i.e. options) passed to the bitbuilder.
    """

    build_config: BuildConfig
    args: Dict[str, Any]

    def __init__(self, build_config: BuildConfig, args: Dict[str, Any]) -> None:
        """
        Args:
            build_config: Build config to build a bitstream for.
            args: Args (i.e. options) passed to the bitbuilder.
        """
        self.build_config = build_config
        self.args = args

    @abc.abstractmethod
    def setup(self) -> None:
        """Any setup needed before `replace_rtl`, `build_driver`, and `build_bitstream` is run."""
        raise NotImplementedError

    def replace_rtl(self) -> None:
        """Generate Verilog from build config. Should run on the manager host."""
        rootLogger.info(
            f"Building Verilog for {self.build_config.get_chisel_quintuplet()}"
        )

        deploy_dir = get_deploy_dir()
        with InfoStreamLogger("stdout"), prefix(f"cd {deploy_dir}/../"), prefix(
            create_export_string({"RISCV", "PATH", "LD_LIBRARY_PATH"})
        ), prefix("source sourceme-manager.sh --skip-ssh-setup"), InfoStreamLogger(
            "stdout"
        ), prefix(
            "cd sim/"
        ):
            run(self.build_config.make_recipe("replace-rtl", deploy_dir))

    def build_driver(self) -> None:
        """Build FireSim FPGA driver from build config. Should run on the manager host."""
        rootLogger.info(
            f"Building FPGA driver for {self.build_config.get_chisel_quintuplet()}"
        )

        deploy_dir = get_deploy_dir()
        with InfoStreamLogger("stdout"), prefix(f"cd {deploy_dir}/../"), prefix(
            create_export_string({"RISCV", "PATH", "LD_LIBRARY_PATH"})
        ), prefix("source sourceme-manager.sh --skip-ssh-setup"), prefix("cd sim/"):
            run(self.build_config.make_recipe("driver", deploy_dir))

    @abc.abstractmethod
    def build_bitstream(self, bypass: bool = False) -> bool:
        """Run bitstream build and terminate the build host at the end.
        Must run after `replace_rtl` and `build_driver` are run.

        Args:
            bypass: If true, immediately return and terminate build host. Used for testing purposes.

        Returns:
            Boolean indicating if the build passed or failed.
        """
        raise NotImplementedError

    def get_metadata_string(self) -> str:
        """Standardized metadata format used across different FPGA platforms"""
        # construct the "tags" we store in the metadata description
        tag_build_quintuplet = self.build_config.get_chisel_quintuplet()
        tag_deploy_quintuplet = self.build_config.get_effective_deploy_quintuplet()

        tag_build_triplet = self.build_config.get_chisel_triplet()
        tag_deploy_triplet = self.build_config.get_effective_deploy_triplet()

        tag_build_makefrag = self.build_config.get_deploy_makefrag()
        tag_deploy_makefrag = self.build_config.get_deploy_makefrag()

        # the asserts are left over from when we tried to do this with tags
        # - technically I don't know how long these descriptions are allowed to be,
        # but it's at least 2048 chars, so I'll leave these here for now as sanity
        # checks.
        assert (
            len(tag_build_quintuplet) <= 255
        ), "ERR: does not support tags longer than 256 chars for build_quintuplet"
        assert (
            len(tag_deploy_quintuplet) <= 255
        ), "ERR: does not support tags longer than 256 chars for deploy_quintuplet"
        assert (
            len(tag_build_triplet) <= 255
        ), "ERR: does not support tags longer than 256 chars for build_triplet"
        assert (
            len(tag_deploy_triplet) <= 255
        ), "ERR: does not support tags longer than 256 chars for deploy_triplet"
        if tag_build_makefrag:
            assert (
                len(tag_build_makefrag) <= 255
            ), "ERR: does not support tags longer than 256 chars for build_makefrag"
        if tag_deploy_makefrag:
            assert (
                len(tag_deploy_makefrag) <= 255
            ), "ERR: does not support tags longer than 256 chars for deploy_makefrag"

        is_dirty_str = local(
            "if [[ $(git status --porcelain) ]]; then echo '-dirty'; fi", capture=True
        )
        hash = local("git rev-parse HEAD", capture=True)
        tag_fsimcommit = hash + is_dirty_str

        assert (
            len(tag_fsimcommit) <= 255
        ), "ERR: aws does not support tags longer than 256 chars for fsimcommit"

        # construct the serialized description from these tags.
        return firesim_tags_to_description(
            tag_build_quintuplet,
            tag_deploy_quintuplet,
            tag_build_triplet,
            tag_deploy_triplet,
            tag_fsimcommit,
            tag_build_makefrag,
            tag_deploy_makefrag,
        )
