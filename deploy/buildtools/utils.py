from fabric.api import local  # type: ignore


def get_deploy_dir() -> str:
    """Determine where the firesim/deploy directory is and return its path.

    Returns:
        Path to firesim/deploy directory.
    """
    deploydir = local("pwd", capture=True)
    return deploydir
