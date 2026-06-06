import hashlib
import hmac as _hmac
import json as _json
import base64 as _base64
import time as _time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader

from app.config import get_settings
from app.models.database import init_db, get_session, Job, Candidate, AccessLog
from app.routers import jobs, candidates, auth
from app.services.resume_cleaner import resume_to_html, jd_to_html

# ── Session cookie helpers ──────────────────────────────────────────────
SESSION_COOKIE = "hirematch_session"
SESSION_MAX_AGE = 7 * 24 * 3600

def _sign_session(data: str, secret: bytes) -> str:
    payload = data.encode()
    ts = str(int(_time.time())).encode()
    msg = payload + b'.' + ts
    sig = _hmac.new(secret, msg, hashlib.sha256).hexdigest()
    return _base64.urlsafe_b64encode(msg + b'.' + sig.encode()).decode().rstrip('=')

def _unsign_session(cookie: str, secret: bytes) -> dict | None:
    try:
        raw = _base64.urlsafe_b64decode(cookie + '===')
        parts = raw.split(b'.')
        if len(parts) != 3:
            return None
        payload, ts, sig = parts
        age = int(_time.time()) - int(ts)
        if age > SESSION_MAX_AGE or age < 0:
            return None
        msg = payload + b'.' + ts
        expected = _hmac.new(secret, msg, hashlib.sha256).hexdigest().encode()
        if not _hmac.compare_digest(sig, expected):
            return None
        return _json.loads(payload)
    except Exception:
        return None


# ── Simple session middleware ───────────────────────────────────────────
class SimpleSessionMiddleware:
    """Parses signed session cookie into scope['session']; saves changes on response."""
    def __init__(self, app, secret: bytes):
        self.app = app
        self.secret = secret

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        scope["session"] = {}
        headers = dict(scope.get("headers", []))
        cookie_str = headers.get(b"cookie", b"").decode()
        for c in cookie_str.split(";"):
            c = c.strip()
            if c.startswith(SESSION_COOKIE + "="):
                val = c.split("=", 1)[1]
                data = _unsign_session(val, self.secret)
                if data:
                    scope["session"] = data
                break

        original_session = dict(scope["session"])

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                current = scope.get("session", {})
                if current and current != original_session:
                    cookie_val = _sign_session(_json.dumps(current, ensure_ascii=False), self.secret)
                    cookie_hdr = f"{SESSION_COOKIE}={cookie_val}; Path=/; Max-Age={SESSION_MAX_AGE}; HttpOnly; SameSite=Lax"
                    hl = list(message.get("headers", []))
                    hl.append((b"set-cookie", cookie_hdr.encode()))
                    message["headers"] = hl
            await send(message)

        await self.app(scope, receive, send_wrapper)


# ── Auth middleware ─────────────────────────────────────────────────────
class AuthMiddleware:
    """Requires valid session; stores org_name/username in scope; logs access."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path.startswith("/static") or path.startswith("/voice") or path in ("/login", "/logout"):
            await self.app(scope, receive, send)
            return

        session = scope.get("session", {})
        org_name = session.get("org_name")
        username = session.get("username", "")
        if not org_name:
            from starlette.responses import RedirectResponse as RR
            response = RR(url="/login", status_code=303)
            await response(scope, receive, send)
            return

        scope["org_name"] = org_name
        scope["username"] = username

        # Access log (fire-and-forget)
        try:
            headers = dict(scope.get("headers", []))
            ip = headers.get(b"x-forwarded-for", b"").decode()
            if not ip:
                ip = headers.get(b"x-real-ip", b"").decode()
            if not ip:
                client = scope.get("client")
                ip = client[0] if client else "unknown"
            ua = headers.get(b"user-agent", b"").decode()[:500] if headers.get(b"user-agent") else ""
            cid = ""
            cookie_str = headers.get(b"cookie", b"").decode()
            for c in cookie_str.split(";"):
                c = c.strip()
                if c.startswith("hirematch_cid="):
                    cid = c.split("=", 1)[1]
                    break
            db = get_session()
            try:
                db.add(AccessLog(
                    org_name=org_name, username=username,
                    action="API" if (path.startswith("/candidates/") or path.startswith("/jobs/")) else "PAGE",
                    path=path, method=scope.get("method", "GET"),
                    ip=ip, user_agent=ua, client_id=cid or None,
                ))
                db.commit()
            finally:
                db.close()
        except Exception:
            pass

        await self.app(scope, receive, send)


# ── Template helpers ────────────────────────────────────────────────────
class Templates:
    def __init__(self, directory: str):
        self.env = Environment(loader=FileSystemLoader(directory), auto_reload=True, cache_size=0)

    def TemplateResponse(self, name: str, context: dict):
        from starlette.templating import _TemplateResponse
        return _TemplateResponse(self.env.get_template(name), context)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


# ── App setup ───────────────────────────────────────────────────────────
settings = get_settings()
BASE_DIR = Path(__file__).resolve().parent.parent
app = FastAPI(title="HireMatch - 智能面试助手", lifespan=lifespan)

# FastAPI add_middleware uses insert(0,...) — LAST call becomes OUTERMOST.
# Auth must be inner (added first), Session must be outer (added last).
app.add_middleware(AuthMiddleware)
app.add_middleware(SimpleSessionMiddleware, secret=settings.session_secret_key.encode())

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
voice_dir = str(BASE_DIR / "uploads" / "voice")
if not Path(voice_dir).exists():
    Path(voice_dir).mkdir(parents=True, exist_ok=True)
app.mount("/voice", StaticFiles(directory=voice_dir), name="voice")
templates = Templates(directory=str(BASE_DIR / "app" / "templates"))

app.include_router(auth.router)
app.include_router(jobs.router)
app.include_router(candidates.router)


# ── Helper ──────────────────────────────────────────────────────────────
def _ctx(request: Request, **extra):
    """Build template context with org/user from scope."""
    return {
        "request": request,
        "org_name": request.scope.get("org_name", ""),
        "username": request.scope.get("username", ""),
        **extra,
    }


# ── Routes ──────────────────────────────────────────────────────────────
@app.get("/")
async def index(request: Request):
    org_name = request.scope.get("org_name", "")
    job_id = request.query_params.get("job_id")
    error = request.query_params.get("error")
    job = None
    session = get_session()
    try:
        if job_id:
            j = session.get(Job, int(job_id))
            if j and j.org_name == org_name:
                job = j

        from sqlalchemy import func
        job_stats = (
            session.query(Job,
                func.count(Candidate.id).label("total"),
                func.sum(Candidate.passed == True).label("passed_count"))
            .outerjoin(Candidate, Job.id == Candidate.job_id)
            .filter(Job.org_name == org_name)
            .group_by(Job.id)
            .order_by(Job.created_at.desc())
            .all()
        )
        previous_jobs = []
        for j, total, passed_count in job_stats:
            if job and j.id == job.id:
                continue
            previous_jobs.append({
                "id": j.id, "title": j.title, "description": j.description,
                "total": total or 0, "passed": passed_count or 0,
                "created_at": j.created_at,
            })
    finally:
        session.close()

    return templates.TemplateResponse("index.html", _ctx(request, job=job, error=error, previous_jobs=previous_jobs,
        jd_html=jd_to_html(job.description) if job else ""))


@app.get("/results/{job_id}")
async def results(request: Request, job_id: int):
    org_name = request.scope.get("org_name", "")
    session = get_session()
    try:
        job = session.get(Job, job_id)
        if not job or job.org_name != org_name:
            return templates.TemplateResponse("index.html", _ctx(request, error="JD 不存在"))

        candidates_list = (
            session.query(Candidate)
            .filter(Candidate.job_id == job_id)
            .order_by(Candidate.overall_score.desc().nullslast(), Candidate.created_at.desc())
            .all()
        )
        passed = [c for c in candidates_list if c.passed is True]
        rejected = [c for c in candidates_list if c.passed is False]
        failed = [c for c in candidates_list if c.status == "failed"]
        pending = [c for c in candidates_list if c.status in ("pending", "processing")]

        return templates.TemplateResponse("results.html", _ctx(request,
            job=job, passed=passed, rejected=rejected, failed=failed, pending=pending,
            total=len(candidates_list), jd_html=jd_to_html(job.description) if job.description else "",
        ))
    finally:
        session.close()


@app.get("/detail/{candidate_id}")
async def detail(request: Request, candidate_id: int):
    org_name = request.scope.get("org_name", "")
    session = get_session()
    try:
        candidate = session.get(Candidate, candidate_id)
        if not candidate:
            return templates.TemplateResponse("index.html", _ctx(request, error="候选人不存在"))
        job = session.get(Job, candidate.job_id)
        if not job or job.org_name != org_name:
            return templates.TemplateResponse("index.html", _ctx(request, error="候选人不存在"))

        resume_html = resume_to_html(candidate.resume_text) if candidate.resume_text else ""

        has_evaluations = False
        if candidate.answers:
            for key, val in candidate.answers.items():
                if key.startswith("_eval_") and isinstance(val, dict):
                    if not val.get("skipped") and val.get("ratings") and any(r > 0 for r in val["ratings"]):
                        has_evaluations = True
                        break

        return templates.TemplateResponse("detail.html", _ctx(request,
            candidate=candidate, job=job, resume_html=resume_html, has_evaluations=has_evaluations,
        ))
    finally:
        session.close()


@app.get("/compare/{job_id}")
async def compare(request: Request, job_id: int):
    org_name = request.scope.get("org_name", "")
    session = get_session()
    try:
        job = session.get(Job, job_id)
        if not job or job.org_name != org_name:
            return templates.TemplateResponse("index.html", _ctx(request, error="JD 不存在"))

        passed_candidates = (
            session.query(Candidate)
            .filter(Candidate.job_id == job_id, Candidate.passed == True)
            .order_by(Candidate.overall_score.desc().nullslast())
            .all()
        )

        if len(passed_candidates) < 2:
            return templates.TemplateResponse("compare.html", _ctx(request,
                job=job, candidates=passed_candidates, comparison=None,
                count=len(passed_candidates), not_enough=len(passed_candidates) < 2,
            ))

        candidates_data = []
        for c in passed_candidates:
            candidates_data.append({
                "id": c.id, "name": c.name, "filename": c.filename,
                "overall_score": c.overall_score, "passed": c.passed,
                "marked_for_interview": c.marked_for_interview,
                "match_result": c.match_result, "credibility_result": c.credibility_result,
                "has_interview": c.interview_result is not None, "status": c.status,
            })

        comparison = job.comparison_result
        if comparison:
            candidate_map = {c.id: c for c in passed_candidates}
            def _normalize(s):
                return s.strip().replace('　', ' ') if s else ''
            name_to_id = {_normalize(c["name"]): c["id"] for c in candidates_data}
            for rc in comparison.get("ranked_candidates", []):
                cid = rc.get("candidate_id")
                if not cid or cid not in candidate_map:
                    fixed_id = name_to_id.get(_normalize(rc.get("name", "")))
                    if fixed_id:
                        rc["candidate_id"] = fixed_id
                        cid = fixed_id
                if cid and cid in candidate_map:
                    c = candidate_map[cid]
                    rc["marked_for_interview"] = c.marked_for_interview
                    rc["has_interview"] = c.interview_result is not None
                else:
                    rc["marked_for_interview"] = False
                    rc["has_interview"] = False

        return templates.TemplateResponse("compare.html", _ctx(request,
            job=job, candidates=candidates_data, comparison=comparison,
            count=len(candidates_data), not_enough=False,
        ))
    finally:
        session.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
