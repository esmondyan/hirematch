from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import RedirectResponse, Response

from app.models.database import Organization, AccessLog, get_session, generate_client_id

router = APIRouter(tags=["auth"])

CLIENT_ID_COOKIE = "hirematch_cid"
COOKIE_MAX_AGE = 365 * 24 * 3600  # 1 year


def _get_client_ip(request: Request) -> str:
    """Extract real client IP from headers or connection."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    client = request.client
    return client.host if client else "unknown"


def _get_or_set_client_id(request: Request, response: Response | None = None) -> str:
    """Get existing client_id from cookie or generate a new persistent one."""
    cid = request.cookies.get(CLIENT_ID_COOKIE)
    if cid:
        return cid
    cid = generate_client_id()
    if response is not None:
        response.set_cookie(
            CLIENT_ID_COOKIE, cid,
            max_age=COOKIE_MAX_AGE,
            httponly=True,
            samesite="lax",
        )
    return cid


def _log_access(
    org_name: str,
    username: str,
    action: str,
    path: str,
    method: str,
    request: Request,
    detail: str | None = None,
):
    """Record an access log entry (fire-and-forget)."""
    try:
        session = get_session()
        try:
            log = AccessLog(
                org_name=org_name,
                username=username,
                action=action,
                path=path,
                method=method,
                ip=_get_client_ip(request),
                user_agent=request.headers.get("User-Agent", "")[:500],
                client_id=request.cookies.get(CLIENT_ID_COOKIE),
                detail=detail,
            )
            session.add(log)
            session.commit()
        finally:
            session.close()
    except Exception:
        pass  # Never let logging break the app


@router.get("/login")
async def login_page(request: Request):
    """Render login page."""
    from app.main import templates
    error = request.query_params.get("error", "")
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": error},
    )


@router.post("/login")
async def login(
    request: Request,
    org_name: str = Form(...),
    username: str = Form(...),
):
    """Login with org name + username (no password)."""
    org_name = org_name.strip()
    username = username.strip()

    if not org_name or not username:
        from app.main import templates
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "组织名称和用户名不能为空"},
        )

    if len(org_name) > 100 or len(username) > 100:
        from app.main import templates
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "组织名称或用户名过长（最多100字符）"},
        )

    # Ensure org exists (auto-create)
    session = get_session()
    try:
        org = session.query(Organization).filter(Organization.name == org_name).first()
        if not org:
            org = Organization(name=org_name)
            session.add(org)
            session.commit()
    finally:
        session.close()

    # Set session
    request.session["org_name"] = org_name
    request.session["username"] = username

    # Log the login
    _log_access(org_name, username, "LOGIN", "/login", "POST", request, detail="登录")

    # Redirect to home, with persistent client_id cookie
    redirect = RedirectResponse(url="/", status_code=303)
    _get_or_set_client_id(request, redirect)
    return redirect


@router.get("/logout")
async def logout(request: Request):
    """Clear session and redirect to login."""
    org_name = request.session.get("org_name", "")
    username = request.session.get("username", "")
    if org_name and username:
        _log_access(org_name, username, "LOGOUT", "/logout", "GET", request, detail="退出")
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)
