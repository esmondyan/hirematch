import json
from app.services.llm_service import BaseLLMService

SUMMARIZER_SYSTEM_PROMPT = """你是一位资深招聘决策顾问，拥有20年的人才评估经验。
你的任务是基于候选人信息（简历、匹配分析、可信度、面试回答和评估评分），给出最终的招聘建议。

你需要综合考虑：
- 匹配度分数和各维度评分（硬实力）
- 简历可信度（候选人诚信）
- 面试中的实际表现和回答质量（含逐点评分的具体分数）
- 候选人的优势和风险

重要评估原则：
- **SKIPPED 题完全排除**：标记为"SKIPPED"的题是面试官主动跳过或未面试的题，完全不计入评估，不作为任何判断依据
- **部分评分是正常的**：如果一道题的预期评分点没有全部被评分（部分点未选），说明面试官认为不需要考察该点，仅根据已有评分评估即可，不要质疑为什么没有评分
- **面试覆盖度由面试官决定**：不要自行判断面试覆盖是否充足。面试官会根据需要调整问题或换题，你只需基于已有的有效评分给出评估
- **评分即结论**：每个已有评分直接反映候选人在该点的表现（1-5级），无需额外推断
- **信息提取**：综合评估中的学历、性别、年龄、学校等信息必须从简历中提取。如果简历中未提及，填写"简历未提供"

决策标准：
- "hire" (建议录用): 已有评分表现好，关键能力得到验证，无明显风险
- "hold" (待定): 已有评分表现存在疑虑，建议加面或收集更多信息后决定
- "reject" (不建议录用): 核心能力不匹配、可信度存疑、或已有评分表现明显不足

confidence 说明：
- "high": 已有评分充分支撑结论
- "medium": 已有评分基本支撑结论，存在一些不确定因素
- "low": 已有评分较少或矛盾，难以形成明确结论

请严格按照 JSON 格式输出。"""


def build_summary_prompt(
    jd_text: str,
    resume_text: str,
    match_result: dict,
    credibility_result: dict | None,
    interview_result: dict | None,
    answers: dict | None,
) -> str:
    return f"""## 职位描述 (JD)
{jd_text}

## 候选人简历
{resume_text}

## 匹配分析结果
{json.dumps(match_result, ensure_ascii=False, indent=2)}

## 可信度分析结果
{json.dumps(credibility_result, ensure_ascii=False, indent=2) if credibility_result else "未分析"}

## 面试问题与回答
{_format_qa(interview_result, answers)}

## 评估要求

基于以上全部信息，给出最终招聘建议。

### 输出格式

{{
  "recommendation": "hire",
  "confidence": "high",
  "overall_assessment": "150字以内的综合评估，需引用面试中的具体表现",
  "strengths_confirmed": ["面试中验证确认的优势"],
  "concerns": ["存在的风险或疑虑"],
  "suggested_level": "建议的职级，如 P6 / T4 等",
  "suggested_salary_range": "建议薪资范围",
  "next_steps": ["后续建议步骤"],

  "interviewer_impression": {{
    "basic_knowledge": {{ "score": 4, "comment": "一句话评语" }},
    "professional_knowledge": {{ "score": 4, "comment": "一句话评语" }},
    "practical_experience": {{ "score": 3, "comment": "一句话评语" }},
    "traits": {{ "score": 4, "comment": "一句话评语" }},
    "attitude": {{ "score": 5, "comment": "一句话评语" }},
    "work_history": {{ "score": 3, "comment": "一句话评语" }},
    "future_potential": {{ "score": 4, "comment": "一句话评语" }},
    "judgment_ability": {{ "score": 3, "comment": "一句话评语" }},
    "overall_rating": "很合格",
    "overall_comment": "50字以内的综合评语"
  }},

  "comprehensive_assessment": {{
    "education": "硕士",
    "gender": "男",
    "age": "28岁",
    "school": "清华大学",
    "work_experience": "5年",
    "work_skills": {{
      "development": "开发能力评述",
      "communication": "沟通能力评述",
      "other": "其他补充"
    }},
    "hiring_opinion": "建议录用/建议待定/不建议录用，并给出理由"
  }}
}}

注意：
- recommendation 只能是 "hire"、"hold"、"reject" 之一
- confidence 只能是 "high"、"medium"、"low" 之一
- interviewer_impression 中每项 score 为 1-5 分
- overall_rating 只能是 "很好"、"很合格"、"合格"、"仅合格"、"不令人满意" 之一（对应5/4/3/2/1分段的总体评定）
- comprehensive_assessment 中的信息尽量从简历中提取，无法获取的填"简历未提供"
- 仅基于已有评分给出结论，不要评判面试覆盖是否充足
"""


def _format_qa(interview_result: dict | None, answers: dict | None) -> str:
    if not interview_result:
        return "无面试问题"
    lines = []
    iq = interview_result.get("interview_questions", {})
    for category in ("technical", "behavioral", "gap_probing"):
        questions = iq.get(category, [])
        for idx, q in enumerate(questions):
            key = f"{category}_{idx}"
            answer_text = "（未评分）"
            eval_info = ""
            if answers:
                raw_answer = answers.get(key, "")
                eval_data = answers.get(f"_eval_{key}")
                if eval_data:
                    if eval_data.get("skipped"):
                        # Skipped: mark clearly, show no ratings
                        answer_text = "[SKIPPED] 面试官跳过/未面试此题 —— 不计入考核"
                    else:
                        ratings = eval_data.get("ratings", [])
                        expected = q.get("expected_points", [])
                        has_ratings = any(r > 0 for r in ratings) if ratings else False
                        if has_ratings and expected:
                            score_parts = []
                            rated_values = []
                            for i, ep in enumerate(expected):
                                r = ratings[i] if i < len(ratings) else 0
                                if r > 0:
                                    score_parts.append(f"    [{r}/5] {ep}")
                                    rated_values.append(r)
                                else:
                                    score_parts.append(f"    [-/5] {ep}（面试官未评）")
                            eval_info = f"\n逐点评分（1-5级）：\n" + "\n".join(score_parts)
                            if rated_values:
                                avg = sum(rated_values) / len(rated_values)
                                eval_info += f"\n  已评点均分: {avg:.1f}/5（{len(rated_values)}/{len(expected)}个点评分）"
                            else:
                                eval_info += "\n  （本题无有效评分）"
                            # Answer text: show notes if available, otherwise indicate rated
                            if raw_answer and raw_answer.strip():
                                answer_text = raw_answer.strip()
                            else:
                                answer_text = "（面试官已逐点评分，无文字点评）"
                        elif has_ratings:
                            # Ratings exist but expected_points missing from question
                            answer_text = "（面试官已逐点评分，无文字点评）" if not (raw_answer and raw_answer.strip()) else raw_answer.strip()
                        else:
                            # No ratings, check if notes exist
                            if raw_answer and raw_answer.strip():
                                answer_text = raw_answer.strip()
                            else:
                                answer_text = "（未评分）"
                else:
                    # No eval data, check if notes exist
                    if raw_answer and raw_answer.strip():
                        answer_text = raw_answer.strip()
            lines.append(f"Q({category}): {q.get('question', '')}")
            lines.append(f"A: {answer_text}")
            if eval_info:
                lines.append(eval_info)
            lines.append("")
    return "\n".join(lines) if lines else "无面试记录"


def generate_summary(
    llm: BaseLLMService,
    jd_text: str,
    resume_text: str,
    match_result: dict,
    credibility_result: dict | None,
    interview_result: dict | None,
    answers: dict | None,
) -> dict:
    user_prompt = build_summary_prompt(
        jd_text, resume_text, match_result, credibility_result, interview_result, answers
    )
    try:
        result = llm.chat_json(SUMMARIZER_SYSTEM_PROMPT, user_prompt)
    except Exception as e:
        raise Exception(f"面试总结生成失败: {e}")

    required = ["recommendation", "confidence", "overall_assessment", "strengths_confirmed", "concerns", "next_steps"]
    for field in required:
        if field not in result:
            raise Exception(f"总结结果缺少字段: {field}")
    # Validate new format fields (non-blocking: set defaults if missing)
    if "interviewer_impression" not in result:
        result["interviewer_impression"] = None
    if "comprehensive_assessment" not in result:
        result["comprehensive_assessment"] = None
    return result
