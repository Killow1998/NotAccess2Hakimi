"""Assert filesystem guarantees supported by the current operating system."""
import os
import stat


def assert_storage_access(path):
    """Check POSIX owner-only modes, or Windows read/write access (not DACL privacy)."""
    if os.name == "posix":
        expected = 0o700 if path.is_dir() else 0o600
        assert stat.S_IMODE(path.stat().st_mode) == expected
    elif os.name == "nt":
        # chmod on Windows controls read-only state, not Unix group/other bits.
        if path.is_dir():
            with os.scandir(path):
                pass
        else:
            with path.open("r+b") as handle:
                handle.read(1)
    else:
        raise AssertionError("Define filesystem assertions for this platform")
