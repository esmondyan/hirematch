import json
from app.services.llm_service import BaseLLMService

COMPARATOR_SYSTEM_PROMPT = """你是一位资深招聘顾问，擅长横向对比多位候选人，为企业挑选最匹配职位的人选。

你的对比分析遵循以下原则：
- 基于职位描述的实际需求进行评判，而非简历的表面亮点
- 综合考量：技能匹配度、项目经验相关性、工作年限、行业背景、简历可信度
- 明确指出每位候选人的相对优势和相对劣势（横向对比）
- 给出明确的排序，排序要有充分依据
- 避免平均主义，敢于指出差距
- 对比不仅要看"谁更好"，更要说明"为什么更适合这个特定职位"

简历噪声说明：
候选人匹配分析中如出现因简历噪声（原始文件DRM水印/加密保护造成的乱码）导致的信息标注（如"有效信息不足"），不应将其视为候选人的劣势。对比时应聚焦于可验证的实际能力差异，而非因文件质量问题造成的信息缺失。

请严格按照要求的 JSON 格式输出，不要添加任何额外的解释文字。"""


def build_comparison_prompt(jd_text: str, candidates: list[dict]) -> str:
    candidates_json = []
    for i, c in enumerate(candidates):
        candidates_json.append({
            "编号": i + 1,
            "ID": c.get("id"),
            "姓名": c.get("name", "未知"),
            "初筛分数": c.get("overall_score"),
            "匹配分析": c.get("match_result", {}),
            "可信度分析": c.get("credibility_result"),
        })

    return f"""## 职位描述 (JD)
{jd_text}

## 候选人列表（已通过初筛）

{json.dumps(candidates_json, ensure_ascii=False, indent=2)}

## 对比要求

请综合对比以上 {len(candidates)} 位候选人，按照谁最适合这个职位进行排序，并输出完整对比分析。

**重要：candidate_id 字段必须使用输入数据中每位候选人的 "ID" 值，不能使用编号或自行编造。**

### 分析要点：
1. **综合排序**：按最适合此职位的程度排序，不是简单按初筛分数排序
2. **横向对比**：指出每位候选人相对于其他人的优势和劣势
3. **岗位匹配度**：针对此 JD 的具体要求，评估谁最匹配
4. **风险提示**：每位候选人的潜在风险或不确定性
5. **面试建议**：对每位候选人给出面试时需要重点验证的方向

### 输出格式

严格按以下 JSON 格式输出：

{{
  "comparison_summary": "整体对比结论，2-3句话概括",
  "ranked_candidates": [
    {{
      "rank": 1,
      "candidate_id": 1,
      "name": "候选人姓名",
      "overall_fit_score": 92,
      "fit_level": "非常适合 / 比较适合 / 基本适合",
      "strengths_vs_others": ["相对于其他候选人的优势1", "优势2"],
      "weaknesses_vs_others": ["相对于其他候选人的劣势1"],
      "jd_match_analysis": "针对此JD的具体匹配情况分析，2-3句",
      "risk_factors": ["潜在风险点"],
      "interview_focus": ["面试时应重点验证的方向1", "方向2"],
      "recommendation": "强烈推荐面试 / 推荐面试 / 可考虑面试"
    }}
  ],
  "comparison_matrix": {{
    "维度1名称": {{
      "候选人A": 分数,
      "候选人B": 分数
    }}
  }},
  "final_recommendation": "最终的招聘建议，包括推荐面试的人数和优先级"
}}"""


def compare_candidates(llm: BaseLLMService, jd_text: str, candidates: list[dict]) -> dict:
    if len(candidates) < 2:
        raise Exception("需要至少2名候选人进行对比")

    user_prompt = build_comparison_prompt(jd_text, candidates)
    # Use high token limit: need enough room for comprehensive multi-candidate comparison
    max_tokens = max(8192, 4096 * len(candidates))
    try:
        result = llm.chat_json(COMPARATOR_SYSTEM_PROMPT, user_prompt, max_tokens=max_tokens)
    except Exception as e:
        raise Exception(f"候选人对比分析失败: {e}")

    _validate_comparison_result(result)
    return result


def _validate_comparison_result(result: dict) -> None:
    if "ranked_candidates" not in result:
        raise Exception("对比结果缺少 ranked_candidates 字段")
    if not isinstance(result["ranked_candidates"], list):
        raise Exception("ranked_candidates 必须是数组")
    if len(result["ranked_candidates"]) == 0:
        raise Exception("ranked_candidates 不能为空")
    for rc in result["ranked_candidates"]:
        for field in ("rank", "name", "overall_fit_score", "strengths_vs_others", "recommendation"):
            if field not in rc:
                raise Exception(f"排序候选人缺少字段: {field}")
        # Ensure candidate_id is present (newer LLM responses will include it)
        if "candidate_id" not in rc:
            rc["candidate_id"] = None
