import configparser
import dataclasses
import os

from . import meta


class ConfigError(Exception):
    pass


@dataclasses.dataclass
class Profile:
    name: str
    url: str = "https://ntfy.sh"
    topic: str | None = None
    username: str | None = None
    password: str | None = None
    token: str | None = None
    keep_entries: int | None = None
    keep_age_hours: float | None = None

    @property
    def auth_type(self) -> str:
        if self.token:
            return "token"
        if self.username or self.password:
            return "basic"
        return "none"


@dataclasses.dataclass
class WebConfig:
    data_dir: str = meta.DEFAULT_DATA_DIR
    display_count: int = 10
    poll_interval: int = 10
    frame_width: int = 400
    frame_height: int = 600
    title: str = ""
    show_file_attachments: bool = False

    def to_public_dict(self) -> dict:
        """The subset written to config.json — display settings only, nothing
        that could identify a topic, server, or credential."""
        return {
            "display_count": self.display_count,
            "poll_interval": self.poll_interval,
            "frame_width": self.frame_width,
            "frame_height": self.frame_height,
            "title": self.title,
            "show_file_attachments": self.show_file_attachments,
        }


def load_ini(ini_path: str | None) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()

    if ini_path:
        if not os.path.isfile(ini_path):
            raise ConfigError(f"--ini path does not exist: {ini_path}")
        cfg.read(ini_path)
    elif os.path.isfile(meta.DEFAULT_CONFIG_PATH):
        cfg.read(meta.DEFAULT_CONFIG_PATH)

    return cfg


def load_web_config(cfg: configparser.ConfigParser) -> WebConfig:
    section = "web"
    web = WebConfig()

    if not cfg.has_section(section):
        return web

    try:
        return WebConfig(
            data_dir=cfg.get(section, "data_dir", fallback=web.data_dir),
            display_count=cfg.getint(section, "display_count", fallback=web.display_count),
            poll_interval=cfg.getint(section, "poll_interval", fallback=web.poll_interval),
            frame_width=cfg.getint(section, "frame_width", fallback=web.frame_width),
            frame_height=cfg.getint(section, "frame_height", fallback=web.frame_height),
            title=cfg.get(section, "title", fallback=web.title),
            show_file_attachments=cfg.getboolean(
                section, "show_file_attachments", fallback=web.show_file_attachments,
            ),
        )
    except ValueError as e:
        raise ConfigError(f"invalid value in [{section}]: {e}") from e


def load_collector_data_dir(cfg: configparser.ConfigParser, web: WebConfig) -> str:
    """[collector] data_dir, falling back to [web] data_dir, falling back to the built-in default."""
    return cfg.get("collector", "data_dir", fallback=web.data_dir)


def _parse_profile(cfg: configparser.ConfigParser, section: str, name: str) -> Profile:
    def get(key):
        return cfg.get(section, key, fallback=None) or None

    profile = Profile(
        name=name,
        url=get("url") or "https://ntfy.sh",
        topic=get("topic"),
        username=get("username"),
        password=get("password"),
        token=get("token"),
    )

    if not profile.topic:
        raise ConfigError(f"profile '{name}' has no topic= set (required)")

    has_basic = bool(profile.username or profile.password)
    if profile.token and has_basic:
        raise ConfigError(
            f"profile '{name}' has both a token and username/password set — "
            "ambiguous auth, remove one"
        )
    if has_basic and not (profile.username and profile.password):
        raise ConfigError(
            f"profile '{name}' has only one of username/password set — both are required for basic auth"
        )

    try:
        keep_entries = cfg.getint(section, "keep_entries", fallback=0)
    except ValueError as e:
        raise ConfigError(f"profile '{name}': invalid keep_entries: {e}") from e
    profile.keep_entries = keep_entries if keep_entries > 0 else None

    keep_hours_raw = get("keep_hours")
    keep_days_raw = get("keep_days")
    if keep_hours_raw and keep_days_raw:
        raise ConfigError(
            f"profile '{name}' has both keep_hours and keep_days set — mutually exclusive, remove one"
        )

    try:
        if keep_hours_raw:
            profile.keep_age_hours = float(keep_hours_raw)
        elif keep_days_raw:
            profile.keep_age_hours = float(keep_days_raw) * 24
    except ValueError as e:
        raise ConfigError(f"profile '{name}': invalid keep_hours/keep_days: {e}") from e

    return profile


def load_profiles(cfg: configparser.ConfigParser) -> list[Profile]:
    """Every [profile:NAME] section, in file order. Raises ConfigError if none exist."""
    profiles = []
    for section in cfg.sections():
        if not section.startswith("profile:"):
            continue
        name = section[len("profile:"):]
        if not name:
            raise ConfigError(f"section [{section}] has an empty profile name")
        profiles.append(_parse_profile(cfg, section, name))

    if not profiles:
        raise ConfigError(
            "no [profile:NAME] sections found — configure at least one topic to monitor"
        )

    names = [p.name for p in profiles]
    if len(names) != len(set(names)):
        raise ConfigError("duplicate profile name found across [profile:NAME] sections")

    return profiles
