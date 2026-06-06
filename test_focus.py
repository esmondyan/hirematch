"""Test focus generation independently (bypasses the web server).
Run:  python test_focus.py
This will call the LLM directly and show raw vs trimmed output."""
import sys
sys.path.insert(0, ".")

from app.services.llm_service import get_llm_service
from app.services.interviewer import generate_focus, _trim_focus_labels, FOCUS_SYSTEM_PROMPT
from app.models.database import init_db, get_session, Job, Candidate

init_db()
session = get_session()

c = (
    session.query(Candidate)
    .filter(Candidate.passed == True, Candidate.match_result != None)
    .order_by(Candidate.created_at.desc())
    .first()
)
if not c:
    print("ERROR: No passed candidate with match_result found.")
    session.close()
    sys.exit(1)

job = session.get(Job, c.job_id)
session.close()

print(f"Candidate: {c.name}")
print(f"Job: {job.title}")
print()

llm = get_llm_service()

# Call generate_focus directly (has internal prints for RAW + TRIMMED)
focus = generate_focus(
    llm, job.description, c.resume_text, c.match_result,
    previous_focus=None,
    previous_questions=None,
)

print()
print("=== FINAL TRIMMED RESULT ===")
for i, f in enumerate(focus):
    print(f"  [{i}] '{f}' ({len(f)} chars)")

# Test edge cases
print()
print("=== TRIM UNIT TESTS ===")
test_cases = [
    "验证FineReport开发能力：要求候选人详细描述项目经验",
    "深入评估候选人的HiveSQL复杂查询调优经验",
    "验证Spring Boot微服务架构设计能力，包括分布式事务处理",
    "评估沟通协作能力",
    "考察Oracle到MySQL的数据库迁移实战经验；了解数据一致性保障方案",
    "验证候选人的报表开发实际项目经验和能力",
]
for tc in test_cases:
    result = _trim_focus_labels([tc])
    print(f"  IN:  '{tc}' ({len(tc)} chars)")
    print(f"  OUT: '{result[0]}' ({len(result[0])} chars)")
    print()
