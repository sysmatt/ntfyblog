import argparse
import sys

from . import collector, config, meta
from ._vendor.applogger import AppLogger


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=meta.PROG,
        description="Subscribe to ntfy.sh topics and generate a live, embeddable JSON blog feed.",
    )
    p.add_argument(
        "--ini", metavar="PATH",
        help=f"Use PATH instead of the default config file ({meta.DEFAULT_CONFIG_PATH})",
    )
    p.add_argument(
        "--log-file", dest="logfile", metavar="PATH",
        help="Also write log output to PATH",
    )
    p.add_argument(
        "--syslog", dest="syslog", default=True, action=argparse.BooleanOptionalAction,
        help="Log to syslog (default: on; use --no-syslog to disable)",
    )
    p.add_argument(
        "--verbose", "-v", action="store_true",
        help="Print high-level steps and actions taken",
    )
    p.add_argument(
        "--debug", "-d", action="store_true",
        help="Print verbose progress plus full parsed config and data-structure dumps",
    )
    p.add_argument(
        "--trace", action="store_true",
        help="Print everything --debug does, plus every received message in full (topic names too — not for routine use)",
    )
    p.add_argument(
        "--version", action="version", version=f"{meta.PROG} {meta.VERSION}",
    )
    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    try:
        cfg = config.load_ini(args.ini)
    except config.ConfigError as e:
        print(f"{meta.PROG}: {e}", file=sys.stderr)
        return 2

    log = AppLogger.from_args(args, meta.PROG, cfg=cfg)
    log.debug(f"parsed args: {vars(args)}")

    try:
        web_config = config.load_web_config(cfg)
        data_dir = config.load_collector_data_dir(cfg, web_config)
        profiles = config.load_profiles(cfg)
    except config.ConfigError as e:
        log.error(str(e))
        return 2

    log.verbose(f"loaded {len(profiles)} profile(s): {', '.join(p.name for p in profiles)}")
    log.debug(f"web config: {web_config}")

    return collector.run(profiles, web_config, data_dir, log)


if __name__ == "__main__":
    sys.exit(main())
