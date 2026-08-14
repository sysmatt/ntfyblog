import os

# Single source of truth for the tool's name. Change this to rename the
# whole tool — prog name, config path, and env var prefix all derive from it.
PROG = "ntfyblog"

VERSION = "0.1.0"

ENV_PREFIX = PROG.upper()

# ntfyblog runs as a system service (not a per-user CLI tool like ntfyer),
# so the default config path lives in /etc rather than ~/.config.
DEFAULT_CONFIG_PATH = f"/etc/{PROG}/{PROG}.ini"

DEFAULT_DATA_DIR = f"/var/local/{PROG}/data"


def env_var(suffix: str) -> str:
    return f"{ENV_PREFIX}_{suffix}"
