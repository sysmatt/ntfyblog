# ntfyblog

Subscribes to one or more [ntfy.sh](https://ntfy.sh) / self-hosted
[ntfy](https://docs.ntfy.sh/) topics and generates a live, embeddable web
blog. Built on the `listen` half of the sibling `ntfyer` project, with
send/ask/handler-execution stripped out — this tool only ever reads.

**Status:** see `DESIGN.md` for the full architecture and every design
decision behind it, and `DEPLOY.md` for installation.

## What it is

Two independent pieces, connected only through a shared data directory —
no network call between them:

1. **Collector** (`ntfyblog`, a Python package) — a `restart=always`
   systemd service running as a non-root user. Subscribes to every
   configured topic concurrently, applies per-topic retention (both
   count- and age-based), downloads attachments, and writes
   `entries.json` + `config.json` + attachment files to a data directory.
2. **Web layer** (`web/`) — plain static HTML/CSS/JS, no build step, no
   server-side component. Polls `entries.json` and renders/animates the
   live feed client-side. Served by whatever web server you already run.

**Topic names and server URLs never reach the browser** — only the
profile name you chose in the config is stored in `entries.json`/shown on
the blog. Nothing downstream of the JSON files has access to the real
topic, so there's no code path that could leak one.

## Quick start

```bash
pip install .
cp templates/ntfyblog.ini.example /etc/ntfyblog/ntfyblog.ini
$EDITOR /etc/ntfyblog/ntfyblog.ini   # set your topic(s)
ntfyblog --ini /etc/ntfyblog/ntfyblog.ini
```

Then point a static web server at `web/`, with `data/` resolving to
`data_dir` from the INI (symlink is simplest). Full instructions,
including nginx/Apache/Caddy config, in `DEPLOY.md`.

## Configuration

See `templates/ntfyblog.ini.example` for a fully-commented example. Two
kinds of section:

- `[web]` — display settings (how many entries to show, poll interval,
  widget size, title, whether non-image/video attachments show a
  download link). This entire section is copied into the public
  `config.json` the browser reads — nothing sensitive belongs here.
- `[profile:NAME]` — one per topic to monitor: `url`, `topic`,
  auth (`username`/`password` *or* `token`), and retention
  (`keep_entries`, `keep_hours`/`keep_days` — independent caps, an entry
  is purged the moment it violates either one). `NAME` **is** shown
  publicly as that entry's source badge, so don't use your real topic
  name as the section name unless you're fine with that being visible.

## Logging

Same vendored `AppLogger` as ntfyer: `-v`/`--verbose`, `-d`/`--debug`,
`--trace` (also logs full message contents, including topic names at
debug — not for routine use), `--log-file PATH`, `--syslog`/`--no-syslog`
(on by default). `[logging]` in the INI is a fallback for whichever of
these isn't given on the CLI.

## Design docs

- `DESIGN.md` — full architecture, JSON schemas, and the reasoning behind
  every non-obvious decision (retention semantics, attachment handling,
  why the web layer is fully static, etc).
- `DEPLOY.md` — step-by-step install, including the web-server wiring
  that connects the static app to the collector's data directory.
