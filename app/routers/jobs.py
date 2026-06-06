from fastapi import APIRouter, HTTPException, Request, Form
from fastapi.responses import RedirectResponse, JSONResponse

from app.models.database import Job, Candidate, get_session
from app.models.schemas import JobCreate, JobResponse

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("/", response_model=JobResponse)
async def create_job_api(data: JobCreate):
    session = get_session()
    try:
        job = Job(title=data.title, description=data.description, threshold=data.threshold)
        session.add(job)
        session.commit()
        session.refresh(job)
        return job
    finally:
        session.close()


@router.post("/create")
async def create_job_form(
    request: Request,
    title: str = Form(...),
    description: str = Form(...),
    threshold: int = Form(60),
):
    session = get_session()
    try:
        job = Job(title=title, description=description, threshold=threshold)
        session.add(job)
        session.commit()
        session.refresh(job)
        return RedirectResponse(url=f"/?job_id={job.id}", status_code=303)
    finally:
        session.close()


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: int):
    session = get_session()
    try:
        job = session.get(Job, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="JD 不存在")
        return job
    finally:
        session.close()


@router.put("/{job_id}")
async def update_job(job_id: int, data: dict):
    session = get_session()
    try:
        job = session.get(Job, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="JD 不存在")

        if "title" in data:
            job.title = data["title"]
        if "description" in data:
            job.description = data["description"]
        if "threshold" in data:
            job.threshold = data["threshold"]

        session.commit()
        return {"status": "ok"}
    finally:
        session.close()


@router.post("/{job_id}/reanalyze-all")
async def reanalyze_all(job_id: int):
    import asyncio
    session = get_session()
    try:
        job = session.get(Job, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="JD 不存在")

        # Set all non-processing candidates to processing status immediately
        # so the UI shows spinners right away
        candidate_ids = []
        for c in job.candidates:
            if c.status not in ("pending", "processing"):
                c.status = "processing"
                c.overall_score = None
                c.passed = None
                c.match_result = None
                c.credibility_result = None
                c.final_summary = None
                c.interview_result = None
                candidate_ids.append(c.id)
        session.commit()

        if not candidate_ids:
            return {"status": "ok", "reanalyzed": 0}

        # Dispatch to background executor
        from app.routers.candidates import _process_candidates, _executor
        loop = asyncio.get_running_loop()
        loop.run_in_executor(_executor, _process_candidates, candidate_ids, job_id)

        return {"status": "ok", "reanalyzed": len(candidate_ids)}
    finally:
        session.close()


@router.delete("/{job_id}")
async def delete_job(job_id: int):
    import os, shutil
    session = get_session()
    try:
        job = session.get(Job, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="JD 不存在")

        # Clean up voice files for all candidates
        for candidate in job.candidates:
            voice_dir = f"uploads/voice/{candidate.id}"
            if os.path.isdir(voice_dir):
                shutil.rmtree(voice_dir, ignore_errors=True)

        # Delete all candidates for this job
        for candidate in job.candidates:
            session.delete(candidate)
        session.delete(job)
        session.commit()
        return {"status": "ok"}
    finally:
        session.close()
