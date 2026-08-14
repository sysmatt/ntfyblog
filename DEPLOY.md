# Deploying ntfyblog

Two independent pieces to install: the Python collector (a systemd
service) and the static web layer (served by whatever web server you
already run). Neither needs the other running to install.

## 1. Collector

```bash
# Dedicated non-root user — the service never needs a login shell or home dir.
sudo useradd --system --no-create-home --shell /usr/sbin/nologin ntfyblog

sudo mkdir -p /var/local/ntfyblog/data /etc/ntfyblog
sudo chown -R ntfyblog:ntfyblog /var/local/ntfyblog

# From a checkout of this repo:
sudo pip install .   # or pipx, or a venv — installs the `ntfyblog` entry point

sudo cp templates/ntfyblog.ini.example /etc/ntfyblog/ntfyblog.ini
sudo $EDITOR /etc/ntfyblog/ntfyblog.ini   # set your real topic(s), profiles, retention

sudo cp systemd/ntfyblog.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ntfyblog
sudo systemctl status ntfyblog
```

Check it's actually writing:

```bash
sudo -u ntfyblog cat /var/local/ntfyblog/data/entries.json
sudo -u ntfyblog cat /var/local/ntfyblog/data/config.json
sudo journalctl -u ntfyblog -f -n 50
```

`journalctl` shows stdout/stderr; syslog is also on by default (see
`[logging]` in the INI to disable/redirect).

## 2. Web layer

The `web/` directory (`index.html`, `app.js`, `style.css`, `emoji.json`) is
plain static files — copy it wherever your web server already serves static
content. `emoji.json` maps ntfy tag short codes to emoji for the title-prefix
rendering; regenerate it with `python scripts/update-emoji.py` when new emoji
land upstream in [gemoji](https://github.com/github/gemoji).

```bash
sudo mkdir -p /var/www/blog
sudo cp -r web/* /var/www/blog/
```

The app fetches `data/entries.json`, `data/config.json`, and attachment
files relative to itself, so `data/` needs to resolve to the collector's
actual `data_dir` (`/var/local/ntfyblog/data` by default). Pick **one** of:

**Symlink (simplest, same host):**
```bash
sudo ln -s /var/local/ntfyblog/data /var/www/blog/data
```
Your web server needs `+FollowSymLinks` (Apache) or nothing special
(nginx/Caddy follow symlinks by default).

**nginx alias:**
```nginx
server {
    location /blog/ {
        root /var/www/blog;
    }
    location /blog/data/ {
        alias /var/local/ntfyblog/data/;
        autoindex off;   # required — see "Directory listing" below
    }
}
```

**Apache alias:**
```apache
Alias /blog /var/www/blog
Alias /blog/data /var/local/ntfyblog/data
<Directory /var/local/ntfyblog/data>
    Options -Indexes
    Require all granted
</Directory>
```

**Caddy:**
```
handle_path /blog/data/* {
    root * /var/local/ntfyblog/data
    file_server            # browsing is off by default — no `browse` directive
}
handle /blog/* {
    root * /var/www/blog
    file_server
}
```

### Directory listing must be off

All entry metadata comes from `entries.json` — the app never lists
`attachments/` itself — but that's an app-side guarantee, not a
server-side one. If the web server is configured to autoindex the `data/`
path, a direct request for e.g. `/blog/data/attachments/home/` hands back
a raw file listing regardless. **nginx defaults this off; Apache often
defaults it ON inside a bare `<Directory>` block** — the config snippets
above include the explicit off-switch; don't skip it if you write your own.

### Embedding

```html
<iframe src="https://yourhost/blog/index.html" width="400" height="600" style="border:0"></iframe>
```

`frame_width`/`frame_height` in the INI size the widget's *own* internal
layout — the `<iframe>` tag itself is still sized by whatever page embeds
it; keep the two roughly matched.

## Updating

Collector: `git pull && sudo pip install . && sudo systemctl restart ntfyblog`.
Web layer: `sudo cp -r web/* /var/www/blog/` (data dir / symlink don't need
touching, they're untouched by an app-file update).
