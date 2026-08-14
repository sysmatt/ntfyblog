# ntfyblog — design spec (v1, pre-implementation)

Subscribes to one or more ntfy.sh topics and generates an embeddable live
web blog. Built on the `listen` half of `ntfyer` (stream_json, attachment
handling, INI/profile config), with send/ask/handlers stripped out.

## Architecture

Two independently-servable halves, connected only through the data dir —
no network call between them, no shared process:

1. **Collector** (Python, `ntfyblog` package) — a `restart=always` systemd
   service, non-root user. Subscribes to every configured profile's topic
   concurrently (one thread per profile, each running its own reconnecting
   `stream_json` loop against ntfy's `/topic/json` endpoint), applies
   retention, and writes:
   - `data/entries.json` — the merged feed
   - `data/config.json` — a **public-safe** subset of config (display
     settings only — never a URL, topic, or credential)
   - `data/attachments/<profile>/<file>` — downloaded attachments
   All writes are atomic (write to `.tmp`, `os.replace()`) and
   lock-guarded, since multiple profile threads share one output file.

2. **Web layer** — static HTML/CSS/JS, no build step, no server-side
   component at all. Served by whatever web server you already run,
   pointed at the app's static files with the data dir reachable at a
   `data/` path alongside them (symlink or your web server's alias/proxy
   config — documented at deploy time, not baked into the app). Browser
   JS polls `entries.json` + `config.json` on an interval, diffs by `id`,
   and renders/animates new entries. This means **the web layer never
   talks to ntfy, never sees a topic name or server URL, and needs no
   process of its own** — it's just files.

This split is why the topic-name isolation requirement is easy to
guarantee: topic/URL/credentials exist only inside the collector process
and the INI file it reads. Nothing downstream of `entries.json`/
`config.json` ever has access to them, so there's no code path that
*could* leak one, by construction.

## Config file — `ntfyblog.ini`

One file, read only by the collector (never shipped to the browser).

```ini
[web]
data_dir       = /var/local/ntfyblog/data   ; also the collector's output dir, see [collector] below
display_count  = 10        ; how many entries the blog shows (independent of retention)
poll_interval  = 10        ; seconds between browser polls of entries.json
frame_width    = 400
frame_height   = 600
title          = Live Feed  ; blank = no header shown
show_file_attachments = false  ; non-image/video attachments (pdf, zip, ...): off by default

[collector]
data_dir       = /var/local/ntfyblog/data   ; defaults to [web] data_dir if unset

[profile:home]
url         = https://ntfy.sh
topic       = my-home-topic
username    =
password    =
token       =
keep_entries = 50           ; 0/unset = unlimited by count
keep_hours   =               ; mutually exclusive with keep_days
keep_days    = 7             ; unlimited by age if both unset

[profile:workshop]
url          = https://ntfy.example.com
topic        = shop-sensors
token        = tk_abc123
keep_entries = 20
keep_days    = 3
```

- Profile **section name** (`home`, `workshop`) is the public label stored
  in `entries.json` and shown as the badge on each entry — per your call,
  no separate `display_name` indirection.
- `keep_entries` and `keep_hours`/`keep_days` are independent caps; an
  entry is purged the moment it violates *either* one.
- `[web] data_dir` and `[collector] data_dir` are almost always the same
  path — split into two keys only so the collector's systemd unit and the
  web server's alias config can each read just the section they need if
  you ever want to point them at different mounts (e.g. NFS-shared data
  dir with different local mount points on two hosts).

## `entries.json`

```json
{
  "generated_at": "2026-08-13T19:04:00Z",
  "entries": [
    {
      "id": "home:9AzC3dkP2f",
      "profile": "home",
      "time": 1755111840,
      "title": "Front door",
      "message": "Motion detected",
      "priority": 4,
      "tags": ["warning", "house"],
      "click_url": "https://example.com/camera/front",
      "attachment": {
        "file": "attachments/home/9AzC3dkP2f.jpg",
        "type": "image",
        "name": "snapshot.jpg"
      }
    }
  ]
}
```

- `id` is `{profile}:{ntfy_message_id}` — namespaced defensively even
  though ntfy IDs are already globally random, so merged-feed dedup can
  never collide across profiles even in theory.
- `attachment.type` is `"image"`, `"video"`, or `"file"` (sniffed from
  content-type/extension at download time). Per your call: image/video
  get inline rendering (image → click for full-res lightbox; video →
  inline `<video controls>`, which already has its own native fullscreen).
  A `"file"` type (pdf, zip, anything non-preview-able) is always
  downloaded and recorded by the collector regardless of display
  settings — retention/storage isn't display's concern — but the web
  layer only renders it (as a plain filename+link) when
  `show_file_attachments = true` in `[web]`; **off by default**, per your
  call. With it off, an entry with a non-media attachment displays
  exactly as if it had none.
- No raw `url`/`topic` field exists anywhere in this schema — structurally
  impossible to leak since the collector never puts it there.

## `config.json` (public, browser-facing)

```json
{
  "display_count": 10,
  "poll_interval": 10,
  "frame_width": 400,
  "frame_height": 600,
  "title": "Live Feed",
  "show_file_attachments": false
}
```

Generated fresh by the collector from `[web]` each time it starts (and on
SIGHUP/config reload, if we add that) — the static JS never reads the INI
directly, it only ever sees this.

## Web layer behavior

- Fetch `config.json` once on load, `entries.json` every `poll_interval`
  seconds.
- Merged chronological feed (newest first), capped to `display_count`
  client-side — collector may retain far more than that per profile.
- New entries (present in latest fetch, absent from what's rendered)
  fade/slide in at the top.
- Message/title text: HTML-escaped, then bare URLs auto-linkified. No
  markdown, no raw HTML.
- Priority shown as a subtle left-border/accent color, scaled
  min→urgent.
- `click_url`, if present, makes the entry open that URL in a new tab.
- Optional header bar: `title` from config (hidden if blank) + a small
  live/stale dot — green if the last `entries.json` fetch succeeded
  within ~2× `poll_interval`, amber/red otherwise.
- Light/dark: **gap I filled** — since this is embeddable (likely an
  iframe on another page), I'm defaulting to `prefers-color-scheme`
  auto-detection rather than asking a 5th round about it. Cheap to add a
  `?theme=light|dark` override later if you want to force it from the
  embedding page.
- `frame_width`/`frame_height` from config size the widget's own root
  container (the page itself is responsive/scrollable internally beyond
  that); the actual `<iframe>` tag on your embedding page is still yours
  to size — these just tell the *content* what to lay out for.

## Startup / reconnect backfill

Each profile thread, on initial connect and on every reconnect after a
drop, calls ntfy's replay with `since=` set to the newest `id` (or
timestamp) it has already saved for that profile — so a restart or a
network blip doesn't lose messages the ntfy server still has cached.
First-ever run (no prior entries for that profile) uses `since=all` up to
whatever the server retains, then immediately applies retention so a
large backlog doesn't blow past `keep_entries`/`keep_hours`/`keep_days`
on first write.

## Directory layout

```
/var/local/ntfyblog/data/
  entries.json
  config.json
  attachments/
    home/
      9AzC3dkP2f.jpg
    workshop/
      ...
```

## Package layout (mirrors ntfyer's structure)

```
src/ntfyblog/
  cli.py           # single entry point, no subcommands (only one mode now)
  collector.py     # per-profile thread loop, replaces listen.py
  retention.py     # new — purge logic (count + age caps)
  writer.py        # new — atomic/locked entries.json + config.json + attachments writes
  config.py        # from ntfyer, + retention/web fields on Profile
  ntfy_api.py      # from ntfyer, stream_json gains since= support
  attachments.py   # from ntfyer, minor path changes (per-profile subdir)
  meta.py          # from ntfyer, PROG = "ntfyblog"
  _vendor/applogger.py
web/
  index.html
  app.js
  style.css
systemd/
  ntfyblog.service
templates/
  ntfyblog.ini.example
```

- `send.py`, `ask.py`, `handlers.py`, `tags.py` — not carried over.
- systemd unit: `Restart=always`, runs as a dedicated non-root user/group
  (e.g. `ntfyblog:ntfyblog`), `ReadWritePaths=` scoped to the data dir,
  everything else read-only — standard hardening, worth including by
  default rather than asking.

## Web server wiring (deploy-time, not automated)

The static `web/` files fetch `data/entries.json` etc. relative to
themselves, but the actual data dir almost certainly lives outside your
web root (the collector runs as its own non-root user and shouldn't be
writing inside your web server's docroot). Bridging "the `data/` URL path"
to "the real `data_dir` on disk" is inherently web-server-specific, so
it's a documented one-time step in `DEPLOY.md` rather than something
ntfyblog automates — doing so would mean either shipping our own file
server (ruled out in round 1: you chose fully-static over a bundled
server) or writing config for a web server we don't control. Simplest
option for a same-host setup is a plain symlink:
`ln -s /var/local/ntfyblog/data /var/www/blog/data`; nginx/Apache/Caddy
each have a one-line alias/location equivalent if a symlink doesn't fit
your setup.

**Directory listing must be off wherever `data/` is exposed.** All
rendering metadata comes only from `entries.json` — the app never lists
`attachments/` or infers anything from a filename — but that's an app-side
guarantee, not a server-side one. If autoindex/`Options +Indexes` is on,
a direct request for `/data/attachments/home/` hands back a raw file
listing regardless of what the app does or doesn't do with it. `DEPLOY.md`
will include the explicit off-switch for each server rather than assuming
the default is safe (nginx defaults off; Apache often defaults **on**
inside a bare `<Directory>` block):

```nginx
location /blog/data/ { alias /var/local/ntfyblog/data/; autoindex off; }
```
```apache
<Directory /var/local/ntfyblog/data>
    Options -Indexes
    Require all granted
</Directory>
```

This also means retention purges must delete the attachment file in the
same operation as removing its `entries.json` entry — `writer.py`'s purge
path does both together, so there's never a window where a file lingers
on disk after the JSON that was the only sanctioned way to reach it is
gone.

## Open items I did *not* silently decide

None left blocking — light/dark default and backlog-on-first-run
behavior are filled with a stated default and are cheap to change later.
`show_file_attachments` and the web-server wiring approach above are now
explicit, not silent gaps. Say the word and I'll start scaffolding the
repo against this spec.
