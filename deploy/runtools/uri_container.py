from __future__ import annotations

import re
import logging
import hashlib
from pathlib import Path
from os.path import join as pjoin
from os.path import expanduser

from utils.io import downloadURI

from typing import Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from .runtime_hw_config import RuntimeHWConfig

rootLogger = logging.getLogger()

# from  https://github.com/pandas-dev/pandas/blob/96b036cbcf7db5d3ba875aac28c4f6a678214bfb/pandas/io/common.py#L73
_RFC_3986_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9+\-+.]*://")


class URIContainer:
    """A class which contains the details for downloading a single URI."""

    """a property name on RuntimeHWConfig"""
    hwcfg_prop: str
    """ the final filename inside sim_slot_x, this is a filename, not a path"""
    destination_name: str

    def __init__(self, hwcfg_prop: str, destination_name: str):
        self.hwcfg_prop = hwcfg_prop
        self.destination_name = destination_name

    # this filename will be used when pre-downloading
    @classmethod
    def hashed_name(cls, uri: str) -> str:
        m = hashlib.sha256()
        m.update(bytes(uri, "utf-8"))
        return m.hexdigest()

    def _resolve_vanilla_path(self, hwcfg: RuntimeHWConfig) -> Optional[str]:
        """Allows fallback to a vanilla path. Relative paths are resolved relative to firesim/deploy/.
        This will convert a vanilla path to a URI, or return None."""
        uri: Optional[str] = getattr(hwcfg, self.hwcfg_prop)

        # do nothing if there isn't a URI
        if uri is None:
            return None

        # if already a URI, exit early returning unmodified string
        is_uri = re.match(_RFC_3986_PATTERN, uri)
        if is_uri:
            return uri

        # expanduser() is required to get ~ home directory expansion working
        # relative paths are relative to firesim/deploy
        expanded = Path(expanduser(uri))

        try:
            # strict=True will throw if the file doesn't exist
            resolved = expanded.resolve(strict=True)
        except FileNotFoundError:
            raise Exception(
                f"{self.hwcfg_prop} file fallback at path '{uri}' or '{expanded}' was not found"
            )

        return f"file://{resolved}"

    def _choose_path(
        self, local_dir: str, hwcfg: RuntimeHWConfig
    ) -> Optional[Tuple[str, str]]:
        """Return a deterministic path, given a parent folder and a RuntimeHWConfig object. The URI
        as generated from hwcfg is also returned."""
        uri: Optional[str] = self._resolve_vanilla_path(hwcfg)

        # do nothing if there isn't a URI
        if uri is None:
            return None

        # choose a repeatable, path based on the hash of the URI
        destination = pjoin(local_dir, self.hashed_name(uri))

        return (uri, destination)

    def local_pre_download(
        self, local_dir: str, hwcfg: RuntimeHWConfig
    ) -> Optional[Tuple[str, str]]:
        """Cached download of the URI contained in this class to a user-specified
        destination folder. The destination name is a SHA256 hash of the URI.
        If the file exists this will NOT overwrite."""

        # resolve the URI and the path '/{dir}/{hash}' we should download to
        both = self._choose_path(local_dir, hwcfg)

        # do nothing if there isn't a URI
        if both is None:
            return None

        (uri, destination) = both

        # When it exists, return the same information, but skip the download
        if Path(destination).exists():
            rootLogger.debug(f"Skipping download of uri: '{uri}'")
            return (uri, destination)

        try:
            downloadURI(uri, destination)
        except FileNotFoundError:
            raise Exception(f"{self.hwcfg_prop} path '{uri}' was not found")

        # return, this is not passed to rsync
        return (uri, destination)

    def get_rsync_path(
        self, local_dir: str, hwcfg: RuntimeHWConfig
    ) -> Optional[Tuple[str, str]]:
        """Does not download. Returns the rsync path required to send an already downloaded
        URI to the runhost."""

        # resolve the URI and the path '/{dir}/{hash}' we should download to
        both = self._choose_path(local_dir, hwcfg)

        # do nothing if there isn't a URI
        if both is None:
            return None

        (uri, destination) = both

        # because the local file has a nonsense name (the hash)
        # we are required to specify the destination name to rsync
        return (destination, self.destination_name)
