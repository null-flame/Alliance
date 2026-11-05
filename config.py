"""Central config for the Alliance site.

Everything you might want to change lives here:
  • CONTENT_URL  — raw GitHub URL of the remote JSON
  • DATA_UUID    — secret long UUID for /data/<uuid> export
  • SECTIONS     — allied groups + their admin credentials + default image

Remote JSON structure (see README at bottom):
  {
    "site": {...},
    "sections": {
      "ghost":  { "avatar": "https://...", "posts": [...] },
      "wagner": { "avatar": "https://...", "posts": [...] }
    }
  }
"""

# ============================================================
#   REMOTE CONTENT
# ============================================================
CONTENT_URL = "https://raw.githubusercontent.com/YOUR_ORG/YOUR_REPO/main/alliance.json"

# Long secret — the ONLY key for /data/<uuid>.
# Replace with your own 64-char hex. Keep it PRIVATE.
# Generate: python -c "import secrets; print(secrets.token_hex(32))"
DATA_UUID = "6b1e9f4c2a7d8e3f5c0b1a9d8e7f6c5b4a3d2e1f0c9b8a7d6e5f4c3b2a1d0e9f"

# Session lifetime (seconds)
SESSION_TTL = 7 * 24 * 3600

# Login rate-limit (simple in-memory, per IP + username)
LOGIN_WINDOW_SECONDS = 300
LOGIN_MAX_ATTEMPTS   = 10


# ============================================================
#   SITE DEFAULTS
# ============================================================
DEFAULT_SITE = {
    "name": "Alliance",
    "tagline": "United. Silent. Precise.",
    "description": "A coalition of allied guards and groups, moving as one.",
    "lang": "en",
}


# ============================================================
#   ALLIED GROUPS
#   ─────────────────────────────────────────────────────────
#   Each key is the section id used in URLs (/s/<id>).
#   "image"  → default emblem; can be overridden per-section
#              via the remote JSON "avatar" field or admin panel.
#   "admins" → username → password (change before deploy!)
# ============================================================
SECTIONS = {
    "wagner": {
        "name": "Wagner Group",
        "desc": "Iron discipline. Unbroken resolve.",
        "image": "https://cdn.imgurl.ir/uploads/v203237_.jpg",
        "color": "#8b5cf6",
        "admins": {
            "wagner_admin": "change-wagner-pass",
        },
    }
}
