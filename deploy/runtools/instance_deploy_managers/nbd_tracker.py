""" NBD Tracker for qcow2 images. """

from __future__ import annotations

from typing import List, Dict


class NBDTracker:
    """Track allocation of NBD devices on an instance. Used for mounting
    qcow2 images."""

    # max number of NBDs allowed by the nbd.ko kernel module
    NBDS_MAX: int = 128
    unallocd: List[str]
    allocated_dict: Dict[str, str]

    def __init__(self) -> None:
        self.unallocd = ["""/dev/nbd{}""".format(x) for x in range(self.NBDS_MAX)]

        # this is a mapping from .qcow2 image name to nbd device.
        self.allocated_dict = {}

    def get_nbd_for_imagename(self, imagename: str) -> str:
        """Call this when you need to allocate an nbd for a particular image,
        or when you need to know what nbd device is for that image.

        This will allocate an nbd for an image if one does not already exist.

        THIS DOES NOT CALL qemu-nbd to actually connect the image to the device"""
        if imagename not in self.allocated_dict.keys():
            # otherwise, allocate it
            assert len(self.unallocd) >= 1, "No NBDs left to allocate on this instance."
            self.allocated_dict[imagename] = self.unallocd.pop(0)

        return self.allocated_dict[imagename]
