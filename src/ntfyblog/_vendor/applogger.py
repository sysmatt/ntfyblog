# Vendored from ../mattlib/applogger.py — keep in sync manually if that copy changes.
# DEFAULT_CONFIG below is unused by ntfyblog; see ntfyblog.meta for its own config path.

import argparse
import configparser
from datetime import date, datetime, timedelta
import logging
import logging.handlers
import os
import re
import sys

# Replace MyProgram with the name of the project
DEFAULT_CONFIG = "/etc/ntfyblog/ntfyblog.ini"


# =============================================================================
# BEGIN APPLOG
# =============================================================================

class AppLogger:
    """
    Application logger with TRACE/VERBOSE/DEBUG/INFO levels and configurable destinations.

    Custom levels:
        TRACE   =  5   super-verbose full dumps
        VERBOSE = 15   informative detail beyond normal INFO

    Destinations: console stream (stderr by default), log file, syslog.
    Console output: plain message for INFO, [LEVEL] prefix for all other levels.
    File/syslog output: includes program name, timestamp, and level.

    Construction:
        log = AppLogger("myprog", level=AppLogger.VERBOSE)
        log = AppLogger.from_args(args, "myprog")
        log = AppLogger.from_args(args, "myprog", cfg=config)  # args > cfg > defaults

    Config file ([logging] section):
        [logging]
        level   = verbose    # trace | debug | verbose | info
        logfile = /path/to/myprog.log
        syslog  = false
    """

    TRACE   = 5
    VERBOSE = 15

    # Register custom levels at class-definition time
    logging.addLevelName(TRACE,   "TRACE")
    logging.addLevelName(VERBOSE, "VERBOSE")

    # Inject .trace() and .verbose() into logging.Logger
    def _trace_m(self, msg, *a, **kw):
        if self.isEnabledFor(5):  self._log(5,  msg, a, **kw)
    def _verbose_m(self, msg, *a, **kw):
        if self.isEnabledFor(15): self._log(15, msg, a, **kw)
    logging.Logger.trace   = _trace_m
    logging.Logger.verbose = _verbose_m
    del _trace_m, _verbose_m

    class _ConsoleFormatter(logging.Formatter):
        """Plain message for INFO; [LEVEL] prefix for everything else."""
        def __init__(self, plain_levels=None):
            super().__init__()
            self._plain = frozenset(plain_levels if plain_levels is not None else [logging.INFO])

        def format(self, record):
            msg = record.getMessage()
            if record.levelno not in self._plain:
                msg = f"[{record.levelname}] {msg}"
            if record.exc_info:
                if not record.exc_text:
                    record.exc_text = self.formatException(record.exc_info)
            if record.exc_text:
                msg = f"{msg}\n{record.exc_text}"
            return msg

    def __init__(
        self,
        name: str,
        level: int = logging.INFO,
        *,
        stream=sys.stderr,
        logfile: str | None = None,
        use_syslog: bool = False,
        plain_levels: list[int] | None = None,
    ):
        self._logger = logging.getLogger(name)
        self._logger.setLevel(level)
        self._logger.handlers.clear()
        self._logger.propagate = False

        if stream is not None:
            h = logging.StreamHandler(stream)
            h.setLevel(level)
            h.setFormatter(self._ConsoleFormatter(plain_levels=plain_levels))
            self._logger.addHandler(h)

        if logfile:
            h = logging.FileHandler(logfile, encoding="utf-8")
            h.setLevel(level)
            h.setFormatter(logging.Formatter(
                fmt=f"%(asctime)s {name} [%(levelname)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            ))
            self._logger.addHandler(h)

        if use_syslog:
            address = "/dev/log" if os.path.exists("/dev/log") else ("localhost", 514)
            h = logging.handlers.SysLogHandler(address=address)
            h.setLevel(level)
            h.setFormatter(logging.Formatter(f"{name}: [%(levelname)s] %(message)s"))
            self._logger.addHandler(h)

    @classmethod
    def from_args(
        cls,
        args,
        program_name: str,
        cfg: configparser.ConfigParser | None = None,
        **kwargs,
    ) -> "AppLogger":
        """
        Build from an argparse Namespace, optionally merging a ConfigParser.
        Args take precedence over the [logging] config section.

        Namespace attrs read (all optional):
            trace, debug, verbose  log level — most verbose flag wins
            logfile                log file path
            syslog                 enable syslog

        ConfigParser [logging] keys (used when the corresponding arg is absent):
            level   = trace | debug | verbose | info
            logfile = /path/to/file
            syslog  = true | false
        """
        _lvl = {"trace": cls.TRACE, "debug": logging.DEBUG,
                "verbose": cls.VERBOSE, "info": logging.INFO}

        cfg_level   = _lvl.get((cfg.get("logging", "level", fallback="") if cfg else "").lower(), logging.INFO)
        cfg_logfile = cfg.get("logging", "logfile", fallback=None)        if cfg else None
        cfg_syslog  = cfg.getboolean("logging", "syslog", fallback=False) if cfg else False

        if   getattr(args, "trace",   False): level = cls.TRACE
        elif getattr(args, "debug",   False): level = logging.DEBUG
        elif getattr(args, "verbose", False): level = cls.VERBOSE
        else:                                 level = cfg_level

        logfile    = getattr(args, "logfile", None) or cfg_logfile
        use_syslog = getattr(args, "syslog", False) or cfg_syslog

        return cls(name=program_name, level=level, logfile=logfile, use_syslog=use_syslog, **kwargs)

    def trace(self,   msg, *a, **kw): self._logger.trace(msg,   *a, **kw)
    def verbose(self, msg, *a, **kw): self._logger.verbose(msg, *a, **kw)
    def debug(self,   msg, *a, **kw): self._logger.debug(msg,   *a, **kw)
    def info(self,    msg, *a, **kw): self._logger.info(msg,    *a, **kw)
    def warning(self, msg, *a, **kw): self._logger.warning(msg, *a, **kw)
    def error(self,   msg, *a, **kw): self._logger.error(msg,   *a, **kw)
    def critical(self,msg, *a, **kw): self._logger.critical(msg,*a, **kw)

# =============================================================================
# END APPLOG
# =============================================================================

