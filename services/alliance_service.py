"""Alliance service — sections are nested, posts live inside each section.

In-memory state shape:

    _state = {
      "site": { ... },
      "sections": {
        "ghost":  { "avatar": str | None, "posts": [ ... ] },
        "wagner": { "avatar": str | None, "posts": [ ... ] },
      },
      "loaded": bool,
      "etag":   str | None,
    }

Remote JSON shape (from config.CONTENT_URL):

    {
      "site":     { ... },
      "sections": {
        "ghost":  { "avatar": "https://...", "posts": [ ... ] },
        "wagner": { "avatar": "https://...", "posts": [ ... ] }
      }
    }
"""
import asyncio
import html
import json
import re
import secrets
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Optional

from config import (
    CONTENT_URL, DATA_UUID, SESSION_TTL, DEFAULT_SITE, SECTIONS,
    LOGIN_WINDOW_SECONDS, LOGIN_MAX_ATTEMPTS,
)

# ============================================================
#   IN-MEMORY STATE
# ============================================================
_state = {
    "site": dict(DEFAULT_SITE),
    "sections": {},        # section_id -> {"avatar": str|None, "posts": list}
    "loaded": False,
    "etag": None,
}

_sessions: dict = {}       # token -> {section_id, username, created_at}
_login_attempts: dict = {} # key -> [count, window_start_ts]
_lock = asyncio.Lock()
_post_counter = 0


# ============================================================
#   PUBLIC ACCESSORS (used by routers — do not read _state directly)
# ============================================================
def get_site() -> dict:
    return _state["site"]


def get_sections_state() -> dict:
    return _state["sections"]


def is_loaded() -> bool:
    return _state["loaded"]


# ============================================================
#   FETCH FROM GITHUB (raw JSON)
# ============================================================
def _blocking_fetch(etag: Optional[str]):
    req = urllib.request.Request(CONTENT_URL, headers={
        "User-Agent": "AllianceSite/1.0",
        "Accept": "application/json",
        "Cache-Control": "no-cache",
    })
    if etag:
        req.add_header("If-None-Match", etag)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return ("ok", json.loads(resp.read().decode()), resp.headers.get("ETag"))
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return ("not_modified", None, None)
        raise


async def fetch_content(force: bool = False):
    """Load remote JSON. Always normalises sections to the ones in config."""
    if not force and _state["loaded"]:
        return

    # IMPORTANT: on a forced refresh, drop the ETag so a 304 cannot
    # prevent the new payload from being applied.
    etag = None if force else _state["etag"]

    try:
        status, data, new_etag = await asyncio.to_thread(_blocking_fetch, etag)

        if status == "ok" and data:
            _state["site"] = {**DEFAULT_SITE, **(data.get("site") or {})}

            remote_sections = data.get("sections") or {}
            new_sections = {}
            for sid in SECTIONS:
                rsec = remote_sections.get(sid) or {}
                posts = rsec.get("posts")
                if not isinstance(posts, list):
                    posts = []
                avatar = rsec.get("avatar")
                if not isinstance(avatar, str):
                    avatar = None
                new_sections[sid] = {
                    "avatar": avatar or None,
                    "posts": posts,
                }

            _state["sections"] = new_sections
            _state["etag"] = new_etag
            _state["loaded"] = True
            _recompute_counter()

            total = sum(len(s["posts"]) for s in new_sections.values())
            print(f"📚 Alliance loaded: {total} posts across {len(SECTIONS)} sections")

        elif status == "not_modified":
            _state["loaded"] = True

    except Exception as e:
        print(f"⚠️  Alliance JSON fetch failed: {e}")
        if not _state["loaded"]:
            _state["sections"] = {sid: {"avatar": None, "posts": []} for sid in SECTIONS}
            _state["loaded"] = True


async def on_startup():
    await fetch_content(force=True)


def _recompute_counter():
    global _post_counter
    max_n = 0
    for sdata in _state["sections"].values():
        for p in sdata.get("posts", []):
            if not isinstance(p, dict):
                continue
            pid = p.get("id", "")
            if isinstance(pid, str) and pid.startswith("p_"):
                try:
                    max_n = max(max_n, int(pid[2:]))
                except ValueError:
                    pass
    _post_counter = max_n


def _next_id() -> str:
    global _post_counter
    _post_counter += 1
    return f"p_{_post_counter}"


# ============================================================
#   AUTH
# ============================================================
def find_section_for_admin(username: str, password: str) -> Optional[str]:
    for sid, sec in SECTIONS.items():
        admins = sec.get("admins", {})
        if username in admins and admins[username] == password:
            return sid
    return None


def login_allowed(key: str) -> bool:
    """Simple in-memory sliding-window limiter for login attempts."""
    now = time.time()
    rec = _login_attempts.get(key)
    if not rec or now - rec[1] > LOGIN_WINDOW_SECONDS:
        _login_attempts[key] = [1, now]
        return True
    if rec[0] >= LOGIN_MAX_ATTEMPTS:
        return False
    rec[0] += 1
    return True


def login_succeeded(key: str) -> None:
    _login_attempts.pop(key, None)


def make_token() -> str:
    return secrets.token_urlsafe(32)


def create_session(section_id: str, username: str) -> str:
    token = make_token()
    _sessions[token] = {
        "section_id": section_id,
        "username": username,
        "created_at": time.time(),
    }
    return token


def get_session(token: Optional[str]) -> Optional[dict]:
    if not token:
        return None
    s = _sessions.get(token)
    if not s:
        return None
    if time.time() - s["created_at"] > SESSION_TTL:
        _sessions.pop(token, None)
        return None
    return s


def destroy_session(token: str):
    _sessions.pop(token, None)


# ============================================================
#   POST CRUD — strictly per section
# ============================================================
def slugify(text: str) -> str:
    s = re.sub(r"[^\w\s-]", "", (text or "").lower())
    s = re.sub(r"[-\s]+", "-", s).strip("-")
    return s[:80] or "post"


def ensure_unique_slug(section_id: str, slug: str, exclude_id: Optional[str] = None) -> str:
    posts = _state["sections"].get(section_id, {}).get("posts", [])
    used = {p.get("slug") for p in posts
            if isinstance(p, dict) and p.get("id") != exclude_id and p.get("slug")}
    base, n = slug, 2
    while slug in used:
        slug = f"{base}-{n}"
        n += 1
    return slug


def section_posts(section_id: str) -> list:
    posts = [p for p in _state["sections"].get(section_id, {}).get("posts", [])
             if isinstance(p, dict)]
    posts.sort(key=lambda p: p.get("date", ""), reverse=True)
    return posts


def find_post(section_id: str, post_id: str) -> Optional[dict]:
    for p in _state["sections"].get(section_id, {}).get("posts", []):
        if isinstance(p, dict) and p.get("id") == post_id:
            return p
    return None


def find_post_by_slug(section_id: str, slug: str) -> Optional[dict]:
    for p in _state["sections"].get(section_id, {}).get("posts", []):
        if isinstance(p, dict) and p.get("slug") == slug:
            return p
    return None


def add_post(section_id: str, data: dict) -> Optional[dict]:
    if not _state["loaded"] or section_id not in _state["sections"]:
        return None
    now = datetime.now(timezone.utc).isoformat()
    slug = ensure_unique_slug(section_id, slugify(data.get("title", "")))
    post = {
        "id": _next_id(),
        "slug": slug,
        "title": (data.get("title") or "")[:200],
        "excerpt": (data.get("excerpt") or "")[:300],
        "content": (data.get("content") or "")[:50000],
        "cover": (data.get("cover") or "")[:1000],
        "tags": [t.strip()[:30] for t in (data.get("tags") or []) if t.strip()][:10],
        "author": (data.get("author") or "")[:60],
        "date": data.get("date") or now,
        "featured": bool(data.get("featured")),
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    _state["sections"][section_id]["posts"].append(post)
    return post


def update_post(section_id: str, post_id: str, data: dict) -> Optional[dict]:
    p = find_post(section_id, post_id)
    if not p:
        return None
    if "title" in data:
        p["title"] = (data["title"] or "")[:200]
    if "excerpt" in data:
        p["excerpt"] = (data["excerpt"] or "")[:300]
    if "content" in data:
        p["content"] = (data["content"] or "")[:50000]
    if "cover" in data:
        p["cover"] = (data["cover"] or "")[:1000]
    if "tags" in data:
        p["tags"] = [t.strip()[:30] for t in (data["tags"] or []) if t.strip()][:10]
    if "author" in data:
        p["author"] = (data["author"] or "")[:60]
    if "date" in data:
        p["date"] = data["date"]
    if "featured" in data:
        p["featured"] = bool(data["featured"])
    p["updated_at"] = time.time()
    return p


def delete_post(section_id: str, post_id: str) -> bool:
    posts = _state["sections"].get(section_id, {}).get("posts", [])
    for i, p in enumerate(posts):
        if isinstance(p, dict) and p.get("id") == post_id:
            posts.pop(i)
            return True
    return False


def set_section_avatar(section_id: str, url: Optional[str]) -> bool:
    if section_id not in _state["sections"]:
        return False
    _state["sections"][section_id]["avatar"] = url or None
    return True


# ============================================================
#   EXPORT — the JSON that /data/<uuid> returns
# ============================================================
def export_json() -> dict:
    sections = {}
    for sid, sdata in _state["sections"].items():
        out = {"posts": sdata.get("posts", [])}
        if sdata.get("avatar"):
            out["avatar"] = sdata["avatar"]
        sections[sid] = out
    return {"site": _state["site"], "sections": sections}


# ============================================================
#   PUBLIC MAPPERS
# ============================================================
def section_public(section_id: str, include_count: bool = True) -> dict:
    cfg = SECTIONS[section_id]
    remote = _state["sections"].get(section_id, {})
    out = {
        "id": section_id,
        "name": cfg["name"],
        "desc": cfg["desc"],
        "image": remote.get("avatar") or cfg.get("image") or "",
        "color": cfg.get("color", "#4fd1c5"),
    }
    if include_count:
        out["post_count"] = len(remote.get("posts", []))
    return out


def post_public(section_id: str, p: dict) -> dict:
    return {
        "id": p["id"],
        "section": section_id,
        "slug": p["slug"],
        "title": p["title"],
        "excerpt": p["excerpt"],
        "cover": p.get("cover", ""),
        "tags": p.get("tags", []),
        "author": p.get("author", ""),
        "date": p.get("date", ""),
        "featured": bool(p.get("featured")),
    }


def post_detail(section_id: str, p: dict) -> dict:
    out = post_public(section_id, p)
    out["content"] = p.get("content", "")
    out["content_html"] = render_markdown(p.get("content", ""))
    return out


def site_stats() -> dict:
    total_posts = sum(len(s.get("posts", [])) for s in _state["sections"].values())
    active = sum(1 for s in _state["sections"].values() if s.get("posts"))
    return {
        "total_allies": len(SECTIONS),
        "active_allies": active,
        "total_posts": total_posts,
    }


# ============================================================
#   MARKDOWN (self-contained, sanitised)
# ============================================================
_BLOCK = re.compile(r"^(#{1,6}\s|```|>|\s*[-*+]\s|\s*\d+\.\s)")


def _esc_url(u: str) -> str:
    u = (u or "").strip()
    if u.lower().startswith(("javascript:", "vbscript:", "data:text/html")):
        return "#"
    return html.escape(u, quote=True)


def _esc_attr(s: str) -> str:
    return html.escape(s or "", quote=True)


def _inline(text: str) -> str:
    text = html.escape(text, quote=False)
    spans = []

    def stash(m):
        spans.append(m.group(1))
        return f"\x00C{len(spans)-1}\x00"

    text = re.sub(r"`([^`]+)`", stash, text)
    text = re.sub(
        r"!\[([^\]]*)\]\(([^)\s]+)\)",
        lambda m: f'<img src="{_esc_url(m.group(2))}" alt="{_esc_attr(m.group(1))}" loading="lazy">',
        text,
    )
    text = re.sub(
        r"\[([^\]]+)\]\(([^)\s]+)\)",
        lambda m: f'<a href="{_esc_url(m.group(2))}" target="_blank" rel="noopener">{m.group(1)}</a>',
        text,
    )
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<em>\1</em>", text)
    text = re.sub(r"~~([^~]+)~~", r"<del>\1</del>", text)
    for j, c in enumerate(spans):
        text = text.replace(f"\x00C{j}\x00", f"<code>{c}</code>")
    return text


def render_markdown(text: str) -> str:
    if not text:
        return ""
    lines = text.replace("\r\n", "\n").split("\n")
    out, i, n = [], 0, len(lines)

    while i < n:
        line = lines[i]

        if line.lstrip().startswith("```"):
            lang = line.lstrip()[3:].strip()
            i += 1
            buf = []
            while i < n and not lines[i].lstrip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            cls = f' class="language-{html.escape(lang)}"' if lang else ""
            out.append(f"<pre><code{cls}>{html.escape(chr(10).join(buf))}</code></pre>")
            continue

        m = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if m:
            lvl = len(m.group(1))
            out.append(f"<h{lvl}>{_inline(m.group(2))}</h{lvl}>")
            i += 1
            continue

        if re.match(r"^\s*([-*_]\s*){3,}$", line):
            out.append("<hr>")
            i += 1
            continue

        if line.lstrip().startswith(">"):
            buf = []
            while i < n and lines[i].lstrip().startswith(">"):
                buf.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            out.append(f"<blockquote>{render_markdown(chr(10).join(buf))}</blockquote>")
            continue

        if re.match(r"^\s*[-*+]\s+", line):
            items = []
            while i < n and re.match(r"^\s*[-*+]\s+", lines[i]):
                items.append(f"<li>{_inline(re.sub(r'^\s*[-*+]\s+', '', lines[i]))}</li>")
                i += 1
            out.append("<ul>" + "".join(items) + "</ul>")
            continue

        if re.match(r"^\s*\d+\.\s+", line):
            items = []
            while i < n and re.match(r"^\s*\d+\.\s+", lines[i]):
                items.append(f"<li>{_inline(re.sub(r'^\s*\d+\.\s+', '', lines[i]))}</li>")
                i += 1
            out.append("<ol>" + "".join(items) + "</ol>")
            continue

        if not line.strip():
            i += 1
            continue

        buf = []
        while i < n and lines[i].strip() and not _BLOCK.match(lines[i]):
            buf.append(lines[i])
            i += 1
        if buf:
            rendered = _inline("\n".join(buf)).replace("\n", "<br>")
            out.append(f"<p>{rendered}</p>")

    result = "\n".join(out)
    result = re.sub(
        r"<\s*(script|style|iframe|object|embed|form)[^>]*>.*?<\s*/\s*\1\s*>",
        "", result, flags=re.DOTALL | re.IGNORECASE,
    )
    result = re.sub(
        r"<\s*(script|style|iframe|object|embed|form)[^>]*/?>",
        "", result, flags=re.IGNORECASE,
    )
    return result
