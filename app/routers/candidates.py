import asyncio
import os
import sys
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Request, Body, Depends
from fastapi.responses import RedirectResponse, JSONResponse, FileResponse

from app.config import get_settings
from app.models.database import Job, Candidate, get_session
from app.models.schemas import CandidateResponse, AnswerSaveRequest, ReplaceQuestionRequest, GenerateQuestionsRequest, RegenerateFocusRequest, SaveEvaluationRequest
from app.services.resume_parser import parse_resume, reparse_resume_from_file, ResumeParserError
from app.services.resume_cleaner import clean_resume_text, restructure_resume_markdown
from app.services.llm_service import get_llm_service, LLMServiceError
from app.services.matcher import match_candidate
from app.services.credibility import analyze_credibility
from app.services.interviewer import generate_questions, replace_question, _extract_question_texts
from app.services.summarizer import generate_summary
from app.services.comparator import compare_candidates

router = APIRouter(prefix="/candidates", tags=["candidates"])
_executor = ThreadPoolExecutor(max_workers=3)


def _get_org(request) -> str:
    return request.scope.get("org_name", "")


def _log(msg: str) -> None:
    """Log to both stdout and stderr so it's always visible."""
    print(msg, flush=True)
    print(msg, file=sys.stderr, flush=True)


def _save_original_file(candidate_id: int, raw_bytes: bytes, filename: str) -> str:
    """Save original resume file to disk and update the candidate's DB record."""
    import shutil
    safe_name = "".join(c for c in filename if c.isalnum() or c in "._- ()（）")
    if not safe_name:
        safe_name = "resume"
    dir_path = f"uploads/{candidate_id}"
    os.makedirs(dir_path, exist_ok=True)
    file_path = os.path.join(dir_path, f"original_{safe_name}")
    with open(file_path, "wb") as f:
        f.write(raw_bytes)
    # Update the DB record
    session = get_session()
    try:
        candidate = session.get(Candidate, candidate_id)
        if candidate:
            candidate.resume_file_path = file_path
            session.commit()
    finally:
        session.close()
    _log(f"[upload] Saved original file: {file_path}")
    return file_path


_log("[candidates.py] MODULE LOADED — inline focus generation active")


def _extract_name_from_resume(text: str) -> str | None:
    """Try to extract a Chinese name from the beginning of resume text."""
    import re

    if not text:
        return None

    # Take first 200 chars for name search (name is usually at the very top)
    head = text[:200].strip()

    # Remove common non-name prefixes
    head = re.sub(r'个人简历|个人简历[：:]|简历[：:]|RESUME|姓名[：:]', '', head, flags=re.IGNORECASE)

    # Match explicit "姓名：XXX" or "姓名: XXX" pattern
    m = re.search(r'姓名\s*[：:]\s*([^\s]{2,4})', head)
    if m:
        name = m.group(1).strip()
        if re.match(r'[一-鿿]{2,4}$', name):
            return name

    # Match first line that looks like a Chinese name (2-3 chars, all Chinese)
    lines = [l.strip() for l in head.split('\n') if l.strip()]
    for line in lines[:5]:
        # Clean up common decorations
        clean = re.sub(r'[^一-鿿]', '', line)
        if re.match(r'^[一-鿿]{2,3}$', clean):
            return clean

    return None


def _is_valid_chinese_name(name: str) -> bool:
    """Check if name looks like a valid Chinese name."""
    import re
    if not name:
        return False
    # Name should contain at least one Chinese character
    return bool(re.search(r'[一-鿿]', name))


@router.post("/upload")
async def upload_resumes(
    request: Request,
    job_id: int = Form(...),
    files: list[UploadFile] = File(...),
):
    if not files:
        return RedirectResponse(url=f"/?job_id={job_id}&error=请选择至少一个文件", status_code=303)

    org_name = _get_org(request)
    session = get_session()
    try:
        job = session.get(Job, job_id)
        if not job or job.org_name != org_name:
            return RedirectResponse(url="/?error=JD不存在", status_code=303)

        candidate_ids = []
        for file in files:
            raw = await file.read()
            try:
                text = parse_resume(raw, file.filename or "unknown")
            except ResumeParserError as e:
                candidate = Candidate(
                    job_id=job_id,
                    name=file.filename or "未知",
                    filename=file.filename or "unknown",
                    resume_text="",
                    status="failed",
                    error_message=str(e),
                )
                session.add(candidate)
                session.commit()
                session.refresh(candidate)
                candidate_ids.append(candidate.id)
                continue

            candidate = Candidate(
                job_id=job_id,
                name="解析中...",
                filename=file.filename or "unknown",
                resume_text=text,
                status="pending",
            )
            session.add(candidate)
            session.commit()
            session.refresh(candidate)

            # Save original file to disk for future re-parse / download
            _save_original_file(candidate.id, raw, file.filename or "unknown")

            candidate_ids.append(candidate.id)

        session.commit()
    finally:
        session.close()

    loop = asyncio.get_running_loop()
    loop.run_in_executor(_executor, _process_candidates, candidate_ids, job_id)

    return RedirectResponse(url=f"/results/{job_id}", status_code=303)


def _process_candidates(candidate_ids: list[int], job_id: int):
    settings = get_settings()
    session = get_session()
    try:
        job = session.get(Job, job_id)
        if not job:
            return

        llm = get_llm_service()

        for cid in candidate_ids:
            candidate = session.get(Candidate, cid)
            if not candidate or candidate.status == "failed":
                continue

            candidate.status = "processing"
            session.commit()

            try:
                # Extract name from raw text before cleaning/restructuring
                extracted_name = _extract_name_from_resume(candidate.resume_text)

                # Clean resume text before analysis (remove noise/watermarks/garbled chars)
                cleaned = clean_resume_text(candidate.resume_text)

                # LLM restructuring: reorganize into clean, well-structured markdown
                restructured = restructure_resume_markdown(llm, cleaned)
                if restructured and len(restructured) > 50:
                    candidate.resume_text = restructured
                    working_resume = restructured
                    _log(f"[process] LLM restructured resume: {len(cleaned)} → {len(restructured)} chars")
                else:
                    working_resume = cleaned

                # Phase 0: Credibility analysis
                try:
                    cred_result = analyze_credibility(llm, working_resume)
                    candidate.credibility_result = cred_result
                except Exception as e:
                    candidate.credibility_result = {
                        "credibility_score": 0,
                        "level": "error",
                        "findings": [],
                        "summary": f"分析失败: {e}",
                    }

                # Phase 1: Match analysis
                match_result = match_candidate(llm, job.description, working_resume, job.threshold)
                candidate.match_result = match_result

                # Name: prefer pre-extracted name from raw text, fallback to LLM
                llm_name = match_result.get("candidate_name", "")
                if extracted_name:
                    candidate.name = extracted_name
                elif _is_valid_chinese_name(llm_name):
                    candidate.name = llm_name
                else:
                    candidate.name = llm_name if llm_name else "未知"

                candidate.overall_score = match_result["overall_score"]
                candidate.passed = match_result["passed"]

                # Phase 2: Interview questions are now generated on-demand
                # after the user marks the candidate for interview

                candidate.status = "completed"
            except Exception as e:
                candidate.status = "failed"
                candidate.error_message = str(e)

            session.commit()
    finally:
        session.close()


# ---------- Answer management ----------

@router.post("/{candidate_id}/answers")
async def save_answers(candidate_id: int, data: AnswerSaveRequest):
    session = get_session()
    try:
        candidate = session.get(Candidate, candidate_id)
        if not candidate:
            raise HTTPException(status_code=404, detail="候选人不存在")

        existing = candidate.answers or {}
        existing.update(data.answers)
        candidate.answers = existing
        session.commit()
        return {"status": "ok", "saved": len(data.answers)}
    finally:
        session.close()


# ---------- Evaluation management ----------

@router.post("/{candidate_id}/evaluations")
async def save_evaluations(candidate_id: int, data: SaveEvaluationRequest):
    """Save point-by-point ratings and skip status for a question."""
    session = get_session()
    try:
        candidate = session.get(Candidate, candidate_id)
        if not candidate:
            raise HTTPException(status_code=404, detail="候选人不存在")

        existing = candidate.answers or {}
        eval_key = f"_eval_{data.question_key}"
        existing[eval_key] = {
            "ratings": data.ratings,
            "skipped": data.skipped,
        }
        candidate.answers = existing
        session.commit()
        return {"status": "ok", "question_key": data.question_key}
    finally:
        session.close()


# ---------- Voice upload ----------

@router.post("/{candidate_id}/voice/{question_key}")
async def upload_voice(candidate_id: int, question_key: str, file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename or ".mp3")[1].lower()
    if ext not in (".mp3", ".wav", ".m4a", ".webm", ".ogg"):
        raise HTTPException(status_code=400, detail=f"不支持的音频格式: {ext}")

    raw = await file.read()
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="音频文件不能超过 10MB")

    voice_dir = f"uploads/voice/{candidate_id}"
    os.makedirs(voice_dir, exist_ok=True)
    filepath = f"{voice_dir}/{question_key}{ext}"
    with open(filepath, "wb") as f:
        f.write(raw)

    # Store reference in answers
    session = get_session()
    try:
        candidate = session.get(Candidate, candidate_id)
        if candidate:
            answers = candidate.answers or {}
            answers[f"_voice_{question_key}"] = filepath
            candidate.answers = answers
            session.commit()
    finally:
        session.close()

    return {"status": "ok", "filepath": filepath}


# ---------- Replace question ----------

@router.post("/{candidate_id}/replace-question")
async def replace_question_endpoint(candidate_id: int, data: ReplaceQuestionRequest):
    session = get_session()
    try:
        candidate = session.get(Candidate, candidate_id)
        if not candidate or not candidate.interview_result:
            raise HTTPException(status_code=404, detail="候选人或面试问题不存在")

        job = session.get(Job, candidate.job_id)
        if not job:
            raise HTTPException(status_code=404, detail="JD不存在")

        # Get the parsed dict ONCE (each access creates a new dict from JSON)
        interview_data = candidate.interview_result
        iq = interview_data.get("interview_questions", {})
        questions = iq.get(data.category, [])
        if data.question_index >= len(questions):
            raise HTTPException(status_code=400, detail="问题索引超出范围")

        old_q = questions[data.question_index]

        # Collect sibling questions (all other questions in same category)
        sibling_questions = []
        for i, q in enumerate(questions):
            if i != data.question_index:
                sibling_questions.append(q.get("question", ""))

        llm = get_llm_service()
        working_resume = clean_resume_text(candidate.resume_text)
        new_q = replace_question(
            llm, job.description, working_resume,
            candidate.match_result or {}, data.category, old_q,
            sibling_questions=sibling_questions,
        )

        # Modify the same dict object and re-assign to trigger the setter
        questions[data.question_index] = new_q
        candidate.interview_result = interview_data
        session.commit()

        return new_q
    finally:
        session.close()


FOCUS_SYSTEM_PROMPT = """你是一位资深技术面试官。根据职位描述和简历匹配分析，列出本轮面试需要重点验证的方向。

面试时长约束：本轮面试总时长严格控制在 25 分钟以内。

面试重点的深度和数量应与候选人工作年限匹配（从简历中的工作经历推断年限）：
- 初级（1-3年）：3-4 条重点，侧重基础技能验证、学习能力、成长潜力
- 中级（3-7年）：4-5 条重点，侧重项目深度、独立解决问题能力、技术广度
- 高级（7年以上）：5-6 条重点，侧重架构设计、技术选型、团队管理、业务洞察

每条面试重点的格式：一个简洁方向标题 + 一句简要说明（告诉面试官为什么要验证这个方向、怎么验证）。

输出要求：
- 方向标题要简洁（≤15字），说明部分 20-40 字
- 针对候选人简历中的具体经历设计验证方向
- 针对匹配分析中发现的"能力缺口"设计探查方向
- 问题难度应与候选人实际工作年限成正比：初级多问基础原理和实操细节，高级多问架构、选型、方法论

简历可信度预警处理（极其重要）：
如果输入中包含了"简历可信度预警"部分，说明该候选人的简历存在可疑内容或低可信度评分。你必须：
- 将预警中的每个可疑点和验证点转化为至少一条面试重点
- 验证方向的设计要能有效揭露虚假经历：要求候选人提供具体细节、追问技术决策原因、询问失败经历和踩坑教训
- 虚假项目经历通常经不起追问具体细节——设计问题时要求候选人提供只有真正做过才知道的细节（如具体的表结构、接口定义、异常处理方案、上线后的真实问题等）

简历噪声说明：
简历中可能包含乱码字符、随机英文串、无意义符号等，这些是原始简历文件的DRM防伪水印或格式转换造成的提取噪声，与候选人能力完全无关。绝对不基于噪声内容设计方向。

严格按 JSON 格式输出，不要添加额外文字。"""


# ---------- Generate interview focus (step 1 of 2) ----------

@router.post("/{candidate_id}/generate-focus")
async def generate_focus_endpoint(candidate_id: int, data: RegenerateFocusRequest | None = Body(default=None)):
    _log(f"[generate-focus endpoint] called for candidate {candidate_id}, is_regenerate={data is not None and len(data.current_focus) > 0}")
    session = get_session()
    try:
        candidate = session.get(Candidate, candidate_id)
        if not candidate:
            raise HTTPException(status_code=404, detail="候选人不存在")

        if not candidate.match_result:
            raise HTTPException(status_code=400, detail="尚未完成匹配分析")

        if not candidate.passed:
            raise HTTPException(status_code=400, detail="该候选人未通过初筛，无法生成面试问题")

        job = session.get(Job, candidate.job_id)
        if not job:
            raise HTTPException(status_code=404, detail="JD不存在")

        # Collect previous data for avoidance
        existing = candidate.interview_result
        previous_focus = existing.get("interview_focus") if existing else None
        previous_questions = _extract_question_texts(existing)

        # Compute excluded/blacklisted focus topics
        is_regenerate = data is not None and len(data.current_focus) > 0
        previous_excluded = existing.get("excluded_focus", []) if existing else []
        newly_excluded = []
        if is_regenerate and previous_focus:
            previous_set = set(previous_focus)
            current_set = set(data.current_focus)
            newly_excluded = list(previous_set - current_set)
        all_excluded = previous_excluded + newly_excluded
        _log(f"[generate-focus] previous_excluded={len(previous_excluded)}, newly_excluded={len(newly_excluded)}, total_excluded={len(all_excluded)}")

        # Collect credibility data for verification-driven focus
        cred = candidate.credibility_result
        cred_hint = ""
        if cred:
            pa = cred.get("project_authenticity", {})
            score = cred.get("credibility_score", 100)
            suspicious = pa.get("suspicious_items", [])
            verify_points = pa.get("verification_points", [])
            ai_risk = cred.get("ai_generation_risk", 0)
            if score < 60 or suspicious or verify_points or ai_risk > 50:
                cred_hint = f"""

## 简历可信度预警（极其重要 —— 必须据此设计验证方向）

可信度评分：{score}/100（{"低" if score < 60 else "中"}）
AI 生成风险：{ai_risk}/100
项目经历整体判断：{pa.get("overall", "未知")}

可疑内容：
{chr(10).join(f'- {s}' for s in suspicious) if suspicious else "（无）"}

面试中必须验证的疑点：
{chr(10).join(f'- {v}' for v in verify_points) if verify_points else "（无）"}

**出题指令：以上每个可疑点和验证点都必须在面试重点中至少有一条对应的验证方向。这是硬性要求。**"""
                _log(f"[generate-focus] Credibility alert included: score={score}, ai_risk={ai_risk}, suspicious={len(suspicious)}, verify_points={len(verify_points)}")

        llm = get_llm_service()
        working_resume = clean_resume_text(candidate.resume_text)

        # ===== FOCUS GENERATION =====
        import json as _json

        _focus_user_prompt = f"""## 职位描述 (JD)
{job.description}

## 候选人简历
{working_resume}

## 匹配分析结果
{_json.dumps(candidate.match_result, ensure_ascii=False, indent=2)}{cred_hint}"""

        if all_excluded:
            _focus_user_prompt += f"""

## 面试官已明确排除的方向（绝对禁止生成 —— 这是硬性约束）
以下方向已被面试官删除或明确表示不关注，你绝对不能生成与以下方向相同或语义相似的面试重点：
{chr(10).join(f'[禁止] {f}' for f in all_excluded)}

**如果你生成的面试重点与上述任何方向相似，面试官将无法使用你的输出。请选择完全不同的角度。**"""

        if previous_focus and not is_regenerate:
            _focus_user_prompt += f"""

## 上一轮面试重点（新重点必须与以下方向有本质区别）
{chr(10).join(f'- {f}' for f in previous_focus)}"""

        if previous_questions:
            _focus_user_prompt += f"""

## 已出过的面试题（新重点不要引出相似题目）
{chr(10).join(f'- {q}' for q in previous_questions)}"""

        if (previous_focus and not is_regenerate) or previous_questions:
            _focus_user_prompt += """

**重要：从不同角度提炼方向，与上轮有本质区别。**"""

        _focus_user_prompt += """

请根据候选人的工作年限调整面试重点的深度和数量。每条格式为"方向标题：简要说明"，不是完整的面试题。输出 JSON：
{
  "interview_focus": ["方向标题：说明", "方向标题：说明", ...]
}"""

        _log(f"[generate-focus] Calling LLM with temperature={0.7 if is_regenerate else 0.1}...")
        try:
            _raw_result = llm.chat_json(FOCUS_SYSTEM_PROMPT, _focus_user_prompt, temperature=0.7 if is_regenerate else None)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"面试重点生成失败: {e}")

        if "interview_focus" not in _raw_result:
            raise HTTPException(status_code=500, detail="面试重点结果缺少 interview_focus 字段")

        focus = _raw_result["interview_focus"]
        _log(f"[generate-focus] GENERATED ({sum(len(i) for i in focus)} chars, {len(focus)} items): {focus}")

        # Store as partial interview_result (focus only, no questions yet)
        # Clear old answers/evaluations when regenerating focus
        candidate.answers = None
        candidate.interview_result = {
            "interview_questions": {"technical": [], "behavioral": [], "gap_probing": []},
            "interview_focus": focus,
            "estimated_duration": "25分钟",
            "question_count": 0,
            "excluded_focus": all_excluded,
        }
        candidate.marked_for_interview = True
        session.commit()
        return {"interview_focus": focus}
    finally:
        session.close()


# ---------- Generate interview questions (step 2 of 2, on-demand) ----------

@router.post("/{candidate_id}/generate-questions")
async def generate_questions_endpoint(candidate_id: int, data: GenerateQuestionsRequest | None = Body(default=None)):
    if data is None:
        data = GenerateQuestionsRequest()
    _log(f"[generate-questions] endpoint called for candidate {candidate_id}, focus_count={len(data.interview_focus)}")
    session = get_session()
    try:
        candidate = session.get(Candidate, candidate_id)
        if not candidate:
            raise HTTPException(status_code=404, detail="候选人不存在")

        if not candidate.match_result:
            raise HTTPException(status_code=400, detail="尚未完成匹配分析")

        if not candidate.passed:
            raise HTTPException(status_code=400, detail="该候选人未通过初筛，无法生成面试问题")

        job = session.get(Job, candidate.job_id)
        if not job:
            raise HTTPException(status_code=404, detail="JD不存在")

        interview_focus = data.interview_focus if data.interview_focus else None
        _log(f"[generate-questions] interview_focus from request: {interview_focus}")

        # Collect previous questions and excluded focus for avoidance
        existing = candidate.interview_result
        previous_questions = _extract_question_texts(existing) if existing else None
        excluded_focus = None
        if interview_focus and existing:
            original_focus = existing.get("interview_focus", [])
            if original_focus:
                excluded_focus = [f for f in original_focus if f not in interview_focus]
                _log(f"[generate-questions] excluded_focus ({len(excluded_focus)}): {excluded_focus}")

        llm = get_llm_service()
        working_resume = clean_resume_text(candidate.resume_text)
        interview_result = generate_questions(
            llm, job.description, working_resume, candidate.match_result,
            interview_focus, previous_questions, excluded_focus,
        )
        _log(f"[generate-questions] stored focus: {interview_result.get('interview_focus')}")
        # Preserve excluded_focus from previous state so regenerations remember blacklisted topics
        if existing and existing.get("excluded_focus"):
            interview_result["excluded_focus"] = existing["excluded_focus"]
        # Clear old answers/evaluations when regenerating questions
        candidate.answers = None
        candidate.interview_result = interview_result
        candidate.marked_for_interview = True
        session.commit()
        return interview_result
    finally:
        session.close()


# ---------- Mark for interview ----------

@router.post("/{candidate_id}/mark-for-interview")
async def mark_for_interview(candidate_id: int):
    session = get_session()
    try:
        candidate = session.get(Candidate, candidate_id)
        if not candidate:
            raise HTTPException(status_code=404, detail="候选人不存在")

        candidate.marked_for_interview = not candidate.marked_for_interview
        session.commit()
        return {"status": "ok", "marked": candidate.marked_for_interview}
    finally:
        session.close()


# ---------- Batch mark ----------

@router.post("/batch-mark")
async def batch_mark(data: dict):
    session = get_session()
    try:
        ids = data.get("candidate_ids", [])
        marked = data.get("marked", True)
        updated = 0
        for cid in ids:
            candidate = session.get(Candidate, cid)
            if candidate and candidate.passed:
                candidate.marked_for_interview = marked
                updated += 1
        session.commit()
        return {"status": "ok", "updated": updated}
    finally:
        session.close()


# ---------- Batch generate questions ----------

@router.post("/batch-generate-questions")
async def batch_generate_questions(data: dict):
    candidate_ids = data.get("candidate_ids", [])
    if not candidate_ids:
        raise HTTPException(status_code=400, detail="请提供候选人ID列表")

    session = get_session()
    try:
        results = []
        llm = get_llm_service()
        for cid in candidate_ids:
            candidate = session.get(Candidate, cid)
            if not candidate or not candidate.passed:
                results.append({"candidate_id": cid, "status": "skipped", "reason": "未通过初筛"})
                continue

            job = session.get(Job, candidate.job_id)
            if not job:
                results.append({"candidate_id": cid, "status": "failed", "reason": "JD不存在"})
                continue

            try:
                working_resume = clean_resume_text(candidate.resume_text)
                previous_questions = _extract_question_texts(candidate.interview_result)
                interview_result = generate_questions(
                    llm, job.description, working_resume, candidate.match_result,
                    previous_questions=previous_questions,
                )
                candidate.interview_result = interview_result
                candidate.marked_for_interview = True
                results.append({"candidate_id": cid, "status": "ok", "name": candidate.name})
            except Exception as e:
                results.append({"candidate_id": cid, "status": "failed", "reason": str(e)})

        session.commit()
        return {"status": "ok", "results": results}
    finally:
        session.close()


# ---------- Compare candidates (LLM-driven, all passed) ----------

@router.post("/compare")
async def run_comparison(data: dict):
    job_id = data.get("job_id")
    if not job_id:
        raise HTTPException(status_code=400, detail="请提供 job_id")

    session = get_session()
    try:
        job = session.get(Job, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="JD不存在")

        passed_candidates = (
            session.query(Candidate)
            .filter(Candidate.job_id == job_id, Candidate.passed == True)
            .order_by(Candidate.overall_score.desc().nullslast())
            .all()
        )

        if len(passed_candidates) < 2:
            raise HTTPException(status_code=400, detail="至少需要2名初筛通过的候选人才能进行对比")

        candidates_data = []
        for c in passed_candidates:
            candidates_data.append({
                "id": c.id,
                "name": c.name,
                "filename": c.filename,
                "overall_score": c.overall_score,
                "match_result": c.match_result,
                "credibility_result": c.credibility_result,
                "resume_text": c.resume_text,
                "marked_for_interview": c.marked_for_interview,
                "has_interview": c.interview_result is not None,
            })

        llm = get_llm_service()
        comparison = compare_candidates(llm, job.description, candidates_data)

        # Merge back the candidate IDs into ranked entries for linking
        valid_ids = {c["id"] for c in candidates_data}
        for rc in comparison.get("ranked_candidates", []):
            # Primary: use candidate_id returned by LLM directly (most reliable)
            llm_id = rc.get("candidate_id")
            if llm_id is not None and isinstance(llm_id, int) and llm_id in valid_ids:
                rc["candidate_id"] = llm_id
                continue
            # Fallback: exact name match only (partial matching risks swapping candidates)
            def _normalize(s):
                return s.strip().replace('　', ' ') if s else ''
            name_to_id = {_normalize(c["name"]): c["id"] for c in candidates_data}
            rc_name = _normalize(rc.get("name", ""))
            rc["candidate_id"] = name_to_id.get(rc_name)

        # Enrich ranked candidates with DB status (marked_for_interview, has_interview)
        candidate_map = {c.id: c for c in passed_candidates}
        for rc in comparison.get("ranked_candidates", []):
            cid = rc.get("candidate_id")
            if cid and cid in candidate_map:
                c = candidate_map[cid]
                rc["marked_for_interview"] = c.marked_for_interview
                rc["has_interview"] = c.interview_result is not None
            else:
                rc["marked_for_interview"] = False
                rc["has_interview"] = False

        job.comparison_result = comparison
        session.commit()

        return {"status": "ok", "comparison": comparison}
    finally:
        session.close()


# ---------- Final summary ----------

@router.post("/{candidate_id}/final-summary")
async def final_summary(candidate_id: int):
    session = get_session()
    try:
        candidate = session.get(Candidate, candidate_id)
        if not candidate:
            raise HTTPException(status_code=404, detail="候选人不存在")

        job = session.get(Job, candidate.job_id)
        if not job:
            raise HTTPException(status_code=404, detail="JD不存在")

        if not candidate.match_result:
            raise HTTPException(status_code=400, detail="尚未完成匹配分析")

        llm = get_llm_service()
        working_resume = clean_resume_text(candidate.resume_text)
        summary = generate_summary(
            llm,
            job.description,
            working_resume,
            candidate.match_result,
            candidate.credibility_result,
            candidate.interview_result,
            candidate.answers,
        )
        candidate.final_summary = summary
        session.commit()
        return summary
    finally:
        session.close()


# ---------- Reanalyze single candidate ----------

@router.post("/{candidate_id}/reanalyze")
async def reanalyze_candidate(candidate_id: int, request: Request):
    org_name = _get_org(request)
    session = get_session()
    try:
        candidate = session.get(Candidate, candidate_id)
        if not candidate:
            raise HTTPException(status_code=404, detail="候选人不存在")
        job = session.get(Job, candidate.job_id)
        if not job or job.org_name != org_name:
            raise HTTPException(status_code=404, detail="候选人不存在")
        if candidate.status in ("pending", "processing"):
            raise HTTPException(status_code=400, detail="候选人正在处理中")
        job_id = candidate.job_id

        # Re-parse original file with current parser (catches parser upgrades)
        if candidate.resume_file_path:
            try:
                new_text = reparse_resume_from_file(candidate.resume_file_path)
                if new_text:
                    candidate.resume_text = new_text
                    _log(f"[reanalyze] Re-parsed resume from {candidate.resume_file_path}, {len(new_text)} chars")
            except ResumeParserError as e:
                _log(f"[reanalyze] Re-parse warning (will use stored text): {e}")

        # Set status to processing immediately so UI shows spinner
        candidate.status = "processing"
        candidate.overall_score = None
        candidate.passed = None
        candidate.match_result = None
        candidate.credibility_result = None
        candidate.final_summary = None
        candidate.interview_result = None
        session.commit()
    finally:
        session.close()

    loop = asyncio.get_running_loop()
    loop.run_in_executor(_executor, _process_candidates, [candidate_id], job_id)
    return {"status": "ok", "message": "已开始重新分析"}


# ---------- Download original resume file ----------

@router.get("/{candidate_id}/download")
async def download_resume(candidate_id: int, view: bool = False, request: Request = None):
    session = get_session()
    try:
        candidate = session.get(Candidate, candidate_id)
        if not candidate:
            raise HTTPException(status_code=404, detail="候选人不存在")
        # Verify org ownership via job
        job = session.get(Job, candidate.job_id)
        org_name = _get_org(request) if request else ""
        if not job or job.org_name != org_name:
            raise HTTPException(status_code=404, detail="候选人不存在")
        if not candidate.resume_file_path or not os.path.exists(candidate.resume_file_path):
            raise HTTPException(status_code=404, detail="原始简历文件不存在（可能为旧版本上传）")

        # Determine media type for inline viewing
        ext = os.path.splitext(candidate.filename)[1].lower()
        content_type_map = {
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".txt": "text/plain; charset=utf-8",
        }
        media_type = content_type_map.get(ext, "application/octet-stream")

        # ASCII-safe filename for Content-Disposition header (latin-1 constraint)
        safe_name = "".join(c for c in candidate.filename if c.isascii() and c.isprintable() and c not in '"\\')
        if not safe_name:
            safe_name = f"resume{ext}"

        if view:
            # Inline viewing (PDF shown in browser, not downloaded)
            return FileResponse(
                path=candidate.resume_file_path,
                filename=safe_name,
                media_type=media_type,
                headers={"Content-Disposition": f"inline; filename={safe_name}"},
            )

        return FileResponse(
            path=candidate.resume_file_path,
            filename=safe_name,
            media_type="application/octet-stream",
        )
    finally:
        session.close()


# ---------- Update candidate name ----------

@router.post("/{candidate_id}/reject")
async def reject_candidate(candidate_id: int):
    """Toggle a passed candidate to rejected (X button on passed cards)."""
    session = get_session()
    try:
        candidate = session.get(Candidate, candidate_id)
        if not candidate:
            raise HTTPException(status_code=404, detail="候选人不存在")
        candidate.passed = False
        candidate.overall_score = None
        candidate.status = "completed"
        session.commit()
        return {"status": "ok", "candidate_id": candidate_id, "action": "rejected"}
    finally:
        session.close()


@router.delete("/{candidate_id}")
async def delete_candidate(candidate_id: int, request: Request):
    """Permanently delete a candidate and their uploaded files."""
    import shutil
    org_name = _get_org(request)
    session = get_session()
    try:
        candidate = session.get(Candidate, candidate_id)
        if not candidate:
            raise HTTPException(status_code=404, detail="候选人不存在")
        job = session.get(Job, candidate.job_id)
        if not job or job.org_name != org_name:
            raise HTTPException(status_code=404, detail="候选人不存在")

        # Clean up uploaded files
        if candidate.resume_file_path:
            dir_path = os.path.dirname(candidate.resume_file_path)
            if os.path.exists(dir_path):
                shutil.rmtree(dir_path, ignore_errors=True)
                _log(f"[delete] Removed files: {dir_path}")

        session.delete(candidate)
        session.commit()
        _log(f"[delete] Candidate {candidate_id} permanently deleted")
        return {"status": "ok", "candidate_id": candidate_id, "action": "deleted"}
    finally:
        session.close()


# ---------- Update candidate name ----------

@router.post("/update-name/{candidate_id}")
async def update_name(candidate_id: int, data: dict):
    session = get_session()
    try:
        candidate = session.get(Candidate, candidate_id)
        if not candidate:
            raise HTTPException(status_code=404, detail="候选人不存在")

        new_name = data.get("name", "").strip()
        if not new_name:
            raise HTTPException(status_code=400, detail="姓名不能为空")

        candidate.name = new_name
        session.commit()
        return {"status": "ok", "name": new_name}
    finally:
        session.close()


# ---------- Get candidate ----------

@router.get("/{candidate_id}", response_model=CandidateResponse)
async def get_candidate(candidate_id: int, request: Request):
    org_name = _get_org(request)
    session = get_session()
    try:
        candidate = session.get(Candidate, candidate_id)
        if not candidate:
            raise HTTPException(status_code=404, detail="候选人不存在")
        job = session.get(Job, candidate.job_id)
        if not job or job.org_name != org_name:
            raise HTTPException(status_code=404, detail="候选人不存在")
        return candidate
    finally:
        session.close()
