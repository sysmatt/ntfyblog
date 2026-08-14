/*
 * ntfyblog web layer — fully static, no build step.
 *
 * Fetches data/config.json once, then polls data/entries.json on an
 * interval. Never talks to ntfy directly and never sees a topic name or
 * server URL — those exist only inside the collector process. All entry
 * text (title/message) is rendered via DOM text nodes, never innerHTML, so
 * nothing in a received message can inject markup.
 */

(() => {
  "use strict";

  const DATA_URL = "data/";
  const STALE_MULTIPLIER = 2.5; // fetch age beyond poll_interval * this = "stale"

  const DEFAULT_CONFIG = {
    display_count: 10,
    poll_interval: 10,
    frame_width: 400,
    frame_height: 600,
    title: "",
    show_file_attachments: false,
  };

  const PRIORITY_LABEL = { 1: "min", 2: "low", 3: "default", 4: "high", 5: "urgent" };

  const root = document.getElementById("ntfyblog-root");
  const headerEl = document.getElementById("ntfyblog-header");
  const titleEl = document.getElementById("ntfyblog-title");
  const statusEl = document.getElementById("ntfyblog-status");
  const feedEl = document.getElementById("ntfyblog-feed");
  const emptyEl = document.getElementById("ntfyblog-empty");
  const lightboxEl = document.getElementById("ntfyblog-lightbox");
  const lightboxImgEl = document.getElementById("ntfyblog-lightbox-img");

  let config = DEFAULT_CONFIG;
  let emojiMap = {};
  const renderedNodes = new Map(); // entry id -> card element currently in the DOM

  const URL_RE = /(https?:\/\/[^\s<>"']+)/g;

  function linkify(text) {
    const frag = document.createDocumentFragment();
    let lastIndex = 0;
    text.replace(URL_RE, (match, _url, offset) => {
      if (offset > lastIndex) {
        frag.appendChild(document.createTextNode(text.slice(lastIndex, offset)));
      }
      const a = document.createElement("a");
      a.href = match;
      a.textContent = match;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      frag.appendChild(a);
      lastIndex = offset + match.length;
      return match;
    });
    if (lastIndex < text.length) {
      frag.appendChild(document.createTextNode(text.slice(lastIndex)));
    }
    return frag;
  }

  function splitTags(tags) {
    const emojis = [];
    const textTags = [];
    for (const tag of tags || []) {
      const emoji = emojiMap[tag];
      if (emoji) emojis.push(emoji);
      else textTags.push(tag);
    }
    return { emojis, textTags };
  }

  function buildCard(entry) {
    const card = document.createElement("article");
    card.className = "entry";
    card.dataset.id = entry.id;

    const priority = entry.priority || 3;
    card.classList.add(`priority-${priority}`);

    const { emojis, textTags } = splitTags(entry.tags);

    const meta = document.createElement("div");
    meta.className = "entry-meta";

    const badge = document.createElement("span");
    badge.className = "entry-badge";
    badge.textContent = entry.profile;
    meta.appendChild(badge);

    const time = document.createElement("time");
    const when = entry.time ? new Date(entry.time * 1000) : null;
    if (when) {
      time.dateTime = when.toISOString();
      time.textContent = when.toLocaleString();
    }
    meta.appendChild(time);

    if (PRIORITY_LABEL[priority] && priority !== 3) {
      const prio = document.createElement("span");
      prio.className = "entry-priority";
      prio.textContent = PRIORITY_LABEL[priority];
      meta.appendChild(prio);
    }

    card.appendChild(meta);

    const body = document.createElement(entry.click_url ? "a" : "div");
    body.className = "entry-body";
    if (entry.click_url) {
      body.href = entry.click_url;
      body.target = "_blank";
      body.rel = "noopener noreferrer";
    }

    const emojiPrefix = emojis.length ? emojis.join(" ") + " " : "";

    if (entry.title) {
      const h = document.createElement("h3");
      h.className = "entry-title";
      h.textContent = emojiPrefix + entry.title;
      body.appendChild(h);
    }

    if (entry.message) {
      const p = document.createElement("p");
      p.className = "entry-message";
      if (!entry.title && emojiPrefix) {
        p.appendChild(document.createTextNode(emojiPrefix));
      }
      p.appendChild(linkify(entry.message));
      body.appendChild(p);
    }

    card.appendChild(body);

    if (textTags.length) {
      const tags = document.createElement("div");
      tags.className = "entry-tags";
      for (const tag of textTags) {
        const t = document.createElement("span");
        t.className = "entry-tag";
        t.textContent = tag;
        tags.appendChild(t);
      }
      card.appendChild(tags);
    }

    if (entry.attachment) {
      card.appendChild(buildAttachment(entry.attachment));
    }

    return card;
  }

  function buildAttachment(attachment) {
    const wrap = document.createElement("div");
    wrap.className = "entry-attachment";
    const src = DATA_URL + attachment.file;

    if (attachment.type === "image") {
      const img = document.createElement("img");
      img.src = src;
      img.alt = attachment.name || "";
      img.loading = "lazy";
      img.className = "entry-image";
      img.addEventListener("click", () => openLightbox(src, attachment.name || ""));
      wrap.appendChild(img);
    } else if (attachment.type === "video") {
      const video = document.createElement("video");
      video.src = src;
      video.controls = true;
      video.className = "entry-video";
      wrap.appendChild(video);
    } else if (config.show_file_attachments) {
      const a = document.createElement("a");
      a.href = src;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.className = "entry-file";
      a.textContent = attachment.name || "attachment";
      wrap.appendChild(a);
    } else {
      return document.createDocumentFragment();
    }

    return wrap;
  }

  function openLightbox(src, alt) {
    lightboxImgEl.src = src;
    lightboxImgEl.alt = alt;
    lightboxEl.hidden = false;
  }

  function closeLightbox() {
    lightboxEl.hidden = true;
    lightboxImgEl.src = "";
  }

  lightboxEl.addEventListener("click", closeLightbox);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !lightboxEl.hidden) closeLightbox();
  });

  function render(entries) {
    const shown = entries.slice(0, config.display_count);
    const shownIds = new Set(shown.map((e) => e.id));

    for (const [id, node] of renderedNodes) {
      if (!shownIds.has(id)) {
        node.remove();
        renderedNodes.delete(id);
      }
    }

    emptyEl.hidden = shown.length > 0;

    let anchor = feedEl.firstChild;
    for (const entry of shown) {
      let node = renderedNodes.get(entry.id);
      if (!node) {
        node = buildCard(entry);
        node.classList.add("entering");
        renderedNodes.set(entry.id, node);
        requestAnimationFrame(() => {
          requestAnimationFrame(() => node.classList.remove("entering"));
        });
      }
      if (node !== anchor) {
        feedEl.insertBefore(node, anchor);
      } else {
        anchor = anchor.nextSibling;
      }
    }
  }

  function setStatus(ok) {
    statusEl.classList.remove("status-live", "status-stale", "status-unknown");
    statusEl.classList.add(ok ? "status-live" : "status-stale");
    statusEl.title = ok ? "Live" : "Not updating";
  }

  async function fetchConfig() {
    try {
      const resp = await fetch(DATA_URL + "config.json", { cache: "no-store" });
      if (resp.ok) {
        config = Object.assign({}, DEFAULT_CONFIG, await resp.json());
      }
    } catch (e) {
      // fall back to defaults silently — the feed still works without config.json
    }

    if (config.title) {
      titleEl.textContent = config.title;
      headerEl.hidden = false;
    }
    if (config.frame_width) root.style.maxWidth = `${config.frame_width}px`;
    if (config.frame_height) root.style.maxHeight = `${config.frame_height}px`;
  }

  async function fetchEmojiMap() {
    try {
      const resp = await fetch("emoji.json", { cache: "force-cache" });
      if (resp.ok) emojiMap = await resp.json();
    } catch (e) {
      // fall back to no emoji translation — tags still render as text
    }
  }

  let lastFetchAt = 0;

  async function fetchEntries() {
    try {
      const resp = await fetch(DATA_URL + "entries.json", { cache: "no-store" });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      render(data.entries || []);
      lastFetchAt = Date.now();
      setStatus(true);
    } catch (e) {
      setStatus(false);
    }
  }

  function checkStale() {
    const maxAge = (config.poll_interval || DEFAULT_CONFIG.poll_interval) * 1000 * STALE_MULTIPLIER;
    if (lastFetchAt && Date.now() - lastFetchAt > maxAge) setStatus(false);
  }

  async function start() {
    await Promise.all([fetchConfig(), fetchEmojiMap()]);
    await fetchEntries();
    const intervalMs = (config.poll_interval || DEFAULT_CONFIG.poll_interval) * 1000;
    setInterval(fetchEntries, intervalMs);
    setInterval(checkStale, 1000);
  }

  start();
})();
