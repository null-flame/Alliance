"""REST API for the Alliance site + secret /data/<uuid> export."""
import json

from fastapi import APIRouter, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from config import DATA_UUID, SECTIONS
from services import alliance_service as al

router = APIRouter()


# ============================================================
#   helpers
# ============================================================
def _require_admin(token: str | None) -> dict:
    sess = al.get_session(token)
    if not sess:
        raise HTTPException(401, "Unauthorized")
    return sess


def _section_or_404(section_id: str) -> dict:
    sec = SECTIONS.get(section_id)
    if not sec:
        raise HTTPException(404, "Section not found")
    return sec


# ============================================================
#   PUBLIC
# ============================================================
@router.get("/api/alliance/site")
async def site():
    return {
        "site": al.get_site(),
        "sections": [al.section_public(sid) for sid in SECTIONS],
        "stats": al.site_stats(),
    }


@router.get("/api/alliance/sections/{section_id}")
async def section_detail(section_id: str):
    _section_or_404(section_id)
    return {
        "section": al.section_public(section_id, include_count=False),
        "posts": [al.post_public(section_id, p)
                  for p in al.section_posts(section_id)],
    }


@router.get("/api/alliance/sections/{section_id}/posts/{slug}")
async def post_detail(section_id: str, slug: str):
    _section_or_404(section_id)
    p = al.find_post_by_slug(section_id, slug)
    if not p:
        raise HTTPException(404, "Post not found")
    return {
        "post": al.post_detail(section_id, p),
        "section": al.section_public(section_id, include_count=False),
    }


# ============================================================
#   AUTH
# ============================================================
@router.post("/api/alliance/login")
async def login(payload: dict, request: Request):
    username = (payload.get("username") or "").strip()[:60]
    password = (payload.get("password") or "").strip()
    if not username or not password:
        return JSONResponse({"ok": False, "error": "نام کاربری و رمز الزامی است"}, 400)

    ip = request.client.host if request.client else "?"
    rate_key = f"{ip}:{username}"

    if not al.login_allowed(rate_key):
        return JSONResponse(
            {"ok": False, "error": "تعداد تلاش بیش از حد؛ بعداً امتحان کنید"}, 429)

    section_id = al.find_section_for_admin(username, password)
    if not section_id:
        return JSONResponse({"ok": False, "error": "نام کاربری یا رمز اشتباه"}, 401)

    al.login_succeeded(rate_key)
    token = al.create_session(section_id, username)
    return {
        "ok": True,
        "token": token,
        "section_id": section_id,
        "section_name": SECTIONS[section_id]["name"],
        "username": username,
    }


@router.post("/api/alliance/logout")
async def logout(payload: dict):
    al.destroy_session(payload.get("token") or "")
    return {"ok": True}


# ============================================================
#   ADMIN (isolated per section)
# ============================================================
@router.get("/api/alliance/admin/posts")
async def admin_list_posts(x_alliance_token: str | None = Header(default=None)):
    sess = _require_admin(x_alliance_token)
    sid = sess["section_id"]
    return {
        "section": al.section_public(sid, include_count=False),
        "posts": [al.post_public(sid, p) for p in al.section_posts(sid)],
    }


@router.post("/api/alliance/admin/posts")
async def admin_create_post(
    payload: dict,
    x_alliance_token: str | None = Header(default=None),
):
    sess = _require_admin(x_alliance_token)
    title = (payload.get("title") or "").strip()
    if not title:
        return JSONResponse({"ok": False, "error": "عنوان الزامی است"}, 400)
    post = al.add_post(sess["section_id"], payload)
    if not post:
        return JSONResponse({"ok": False, "error": "بخش نامعتبر"}, 400)
    return {"ok": True, "post": al.post_public(sess["section_id"], post)}


@router.put("/api/alliance/admin/posts/{post_id}")
async def admin_update_post(
    post_id: str,
    payload: dict,
    x_alliance_token: str | None = Header(default=None),
):
    sess = _require_admin(x_alliance_token)
    post = al.update_post(sess["section_id"], post_id, payload)
    if not post:
        return JSONResponse({"ok": False, "error": "پست پیدا نشد"}, 404)
    return {"ok": True, "post": al.post_public(sess["section_id"], post)}


@router.delete("/api/alliance/admin/posts/{post_id}")
async def admin_delete_post(
    post_id: str,
    x_alliance_token: str | None = Header(default=None),
):
    sess = _require_admin(x_alliance_token)
    if not al.delete_post(sess["section_id"], post_id):
        return JSONResponse({"ok": False, "error": "پست پیدا نشد"}, 404)
    return {"ok": True}


@router.post("/api/alliance/admin/avatar")
async def admin_set_avatar(
    payload: dict,
    x_alliance_token: str | None = Header(default=None),
):
    sess = _require_admin(x_alliance_token)
    url = (payload.get("avatar") or "").strip()[:1000]
    if url and not url.startswith(("http://", "https://", "data:")):
        return JSONResponse({"ok": False, "error": "URL نامعتبر"}, 400)
    al.set_section_avatar(sess["section_id"], url or None)
    return {"ok": True, "section": al.section_public(sess["section_id"], include_count=False)}


# ============================================================
#   SECRET EXPORT — /data/<uuid>
# ============================================================
@router.get("/data/{uuid}")
async def secret_export(uuid: str):
    if uuid != DATA_UUID:
        raise HTTPException(404)
    return Response(
        content=json.dumps(al.export_json(), ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )
