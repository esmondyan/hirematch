from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader

from app.models.database import init_db, get_session, Job, Candidate
from app.routers import jobs, candidates
from app.services.resume_cleaner import resume_to_html, jd_to_html


class Templates:
    def __init__(self, directory: str):
        self.env = Environment(
            loader=FileSystemLoader(directory),
            auto_reload=True,
            cache_size=0,  # Workaround for Python 3.14 + Jinja2 cache issue
        )

    def TemplateResponse(self, name: str, context: dict):
        from starlette.templating import _TemplateResponse
        template = self.env.get_template(name)
        return _TemplateResponse(template, context)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


BASE_DIR = Path(__file__).resolve().parent.parent
app = FastAPI(title="HireMatch - 智能面试助手", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
# Mount voice uploads for playback
voice_dir = str(BASE_DIR / "uploads" / "voice")
voice_dir_path = Path(voice_dir)
if not voice_dir_path.exists():
    voice_dir_path.mkdir(parents=True, exist_ok=True)
app.mount("/voice", StaticFiles(directory=voice_dir), name="voice")
templates = Templates(directory=str(BASE_DIR / "app" / "templates"))

app.include_router(jobs.router)
app.include_router(candidates.router)


@app.get("/")
async def index(request: Request):
    job_id = request.query_params.get("job_id")
    error = request.query_params.get("error")
    job = None
    session = get_session()
    try:
        if job_id:
            job = session.get(Job, int(job_id))

        # Fetch all previous jobs with candidate counts for history
        from sqlalchemy import func
        job_stats = (
            session.query(
                Job,
                func.count(Candidate.id).label("total"),
                func.sum(Candidate.passed == True).label("passed_count"),
            )
            .outerjoin(Candidate, Job.id == Candidate.job_id)
            .group_by(Job.id)
            .order_by(Job.created_at.desc())
            .all()
        )
        previous_jobs = []
        for j, total, passed_count in job_stats:
            if job and j.id == job.id:
                continue  # Skip current job in history
            # Truncate description for preview
            desc_preview = j.description[:200] + "..." if len(j.description) > 200 else j.description
            previous_jobs.append({
                "id": j.id,
                "title": j.title,
                "description": j.description,
                "desc_preview": desc_preview,
                "total": total or 0,
                "passed": passed_count or 0,
                "created_at": j.created_at,
            })
    finally:
        session.close()

    return templates.TemplateResponse(
        "index.html",
        {"request": request, "job": job, "error": error, "previous_jobs": previous_jobs},
    )


@app.get("/results/{job_id}")
async def results(request: Request, job_id: int):
    session = get_session()
    try:
        job = session.get(Job, job_id)
        if not job:
            return templates.TemplateResponse("index.html", {"request": request, "error": "JD 不存在"})

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

        jd_html = jd_to_html(job.description) if job.description else ""

        return templates.TemplateResponse(
            "results.html",
            {
                "request": request,
                "job": job,
                "passed": passed,
                "rejected": rejected,
                "failed": failed,
                "pending": pending,
                "total": len(candidates_list),
                "jd_html": jd_html,
            },
        )
    finally:
        session.close()


@app.get("/detail/{candidate_id}")
async def detail(request: Request, candidate_id: int):
    session = get_session()
    try:
        candidate = session.get(Candidate, candidate_id)
        if not candidate:
            return templates.TemplateResponse("index.html", {"request": request, "error": "候选人不存在"})

        job = session.get(Job, candidate.job_id)
        resume_html = resume_to_html(candidate.resume_text) if candidate.resume_text else ""

        # Check if any question has been evaluated (rated and not skipped)
        has_evaluations = False
        if candidate.answers:
            for key, val in candidate.answers.items():
                if key.startswith("_eval_") and isinstance(val, dict):
                    if not val.get("skipped") and val.get("ratings") and any(r > 0 for r in val["ratings"]):
                        has_evaluations = True
                        break

        return templates.TemplateResponse(
            "detail.html",
            {
                "request": request, "candidate": candidate, "job": job,
                "resume_html": resume_html, "has_evaluations": has_evaluations,
            },
        )
    finally:
        session.close()


@app.get("/compare/{job_id}")
async def compare(request: Request, job_id: int):
    session = get_session()
    try:
        job = session.get(Job, job_id)
        if not job:
            return templates.TemplateResponse("index.html", {"request": request, "error": "JD 不存在"})

        passed_candidates = (
            session.query(Candidate)
            .filter(Candidate.job_id == job_id, Candidate.passed == True)
            .order_by(Candidate.overall_score.desc().nullslast())
            .all()
        )

        if len(passed_candidates) < 2:
            return templates.TemplateResponse(
                "compare.html",
                {
                    "request": request,
                    "job": job,
                    "candidates": passed_candidates,
                    "comparison": None,
                    "count": len(passed_candidates),
                    "not_enough": len(passed_candidates) < 2,
                },
            )

        candidates_data = []
        for c in passed_candidates:
            candidates_data.append({
                "id": c.id,
                "name": c.name,
                "filename": c.filename,
                "overall_score": c.overall_score,
                "passed": c.passed,
                "marked_for_interview": c.marked_for_interview,
                "match_result": c.match_result,
                "credibility_result": c.credibility_result,
                "has_interview": c.interview_result is not None,
                "status": c.status,
            })

        # Refresh live status in comparison result (mark status may have changed since analysis)
        comparison = job.comparison_result
        if comparison:
            candidate_map = {c.id: c for c in passed_candidates}
            # Also build name lookup for repairing broken candidate_id values
            def _normalize(s):
                return s.strip().replace('　', ' ') if s else ''
            name_to_id = {_normalize(c.name): c.id for c in passed_candidates}
            for rc in comparison.get("ranked_candidates", []):
                cid = rc.get("candidate_id")
                # Repair: if candidate_id is missing or invalid, try exact name match
                if not cid or cid not in candidate_map:
                    rc_name = _normalize(rc.get("name", ""))
                    fixed_id = name_to_id.get(rc_name)
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

        return templates.TemplateResponse(
            "compare.html",
            {
                "request": request,
                "job": job,
                "candidates": candidates_data,
                "comparison": comparison,
                "count": len(candidates_data),
                "not_enough": False,
            },
        )
    finally:
        session.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=53500, reload=True)
