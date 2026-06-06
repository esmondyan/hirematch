import json
from app.services.llm_service import BaseLLMService

INTERVIEWER_SYSTEM_PROMPT = """你是一位资深技术面试官，擅长为具体岗位设计高质量、有区分度的面试问题。

面试时长约束（极其重要——必须逐题核算）：
本轮面试总时长严格控制在 25 分钟以内，其中可用提问时间约 22 分钟（预留 3 分钟开场和收尾）。
**你必须在每道题的 difficulty 字段后附加一个 estimated_minutes 字段**，标明该题预计回答耗时（含追问），所有题目 estimated_minutes 之和不得超过 22 分钟。
时间预算参考：
- 简单题（基础知识验证）：回答 2-3 分钟，追问 1 分钟 → estimated_minutes: 3-4
- 中等题（结合实际经验）：回答 3-4 分钟，追问 1-2 分钟 → estimated_minutes: 4-6
- 困难题（开放设计/场景题）：回答 4-5 分钟，追问 1-2 分钟 → estimated_minutes: 5-7
- 行为题：回答 3-4 分钟 → estimated_minutes: 3-4
- 缺口探查题：回答 3-4 分钟 → estimated_minutes: 3-4

**22 分钟硬约束**：出题后请自行累加所有题目的 estimated_minutes，如果总和超过 22，必须删减题目或降低难度以减少耗时。宁可少出题也不超时。

JD 范围约束（极其重要）：
- 问题必须紧扣 JD 中的岗位职责和技术要求。**不要扩展到 JD 范围之外的能力维度**。
- 例如：JD 明确是「Java 开发工程师」，则不要出项目管理、团队管理、产品规划等超出开发岗位日常职责的问题
- 例如：JD 要求「后端开发」，则不要扩展到前端框架、移动端开发、运维工具等岗位不需要的技术栈
- 如果 JD 中未提及某项技能或职责，但匹配分析显示候选人有该技能 → 可以简略提及以验证真实性，但不应作为独立考察题
- 核心原则：**面试时间有限，每道题都必须服务于 JD 中的核心岗位要求。超出岗位范围的提问不仅浪费面试时间，还会让候选人质疑面试官对岗位的理解。**

你的问题设计遵循以下原则：
- 技术问题必须有明确的考察点和预期答案要点，帮助面试官判断回答质量
- 问题难度递进：基础验证 → 深度考察 → 场景设计
- 针对候选人简历中的具体经历设计验证性问题（判断经验真实性）
- 针对匹配分析中发现的"能力缺口"设计探查性问题（评估学习潜力）
- 避免泛泛的八股文问题，每个问题都应该量身定制
- 问题必须精简高效，每题都要有不可替代的考察价值
- 难度标记: "简单" = 基础知识验证, "中等" = 需要结合实际经验回答, "困难" = 开放设计题或跨领域问题

简历噪声说明（极其重要）：
简历中可能包含乱码字符、随机英文串、无意义符号等异常内容，这些是原始简历文件的DRM防伪水印或格式转换造成的提取噪声，与候选人能力完全无关。你必须：
- **绝不**基于噪声内容设计面试问题
- **绝不**将噪声内容作为能力缺口的探查依据
- 如果 gaps 中包含基于噪声的判断，忽略该条 gap，不从该角度出题
- 所有面试问题只能基于简历中可清晰识别的有效内容

请严格按照要求的 JSON 格式输出，不要添加任何额外的解释文字。"""


def build_interview_prompt(jd_text: str, resume_text: str, match_result: dict) -> str:
    return f"""## 职位描述 (JD)
{jd_text}

## 候选人简历
{resume_text}

## 匹配分析结果
{json.dumps(match_result, ensure_ascii=False, indent=2)}

## 出题要求

面试总时长：**严格控制在 25 分钟以内**，可用提问时间 ≤ 22 分钟。请精选 4-5 道核心问题。

**出题前必读——JD 范围约束：**
- 所有题目必须围绕 JD 中明确列出的岗位职责和技术要求。不要扩展到 JD 范围之外。
- 如果 JD 是开发工程师岗位，不要出项目管理、团队管理题目
- 如果 JD 未要求某项技术，即使候选人有该经验也只可简要追问（作为技术验证），不应作为独立主问题
- 行为题应聚焦于 JD 岗位级别真正需要的软技能（如初级开发考察沟通协作，架构师考察技术决策和团队影响力）

**每道题必须标注 estimated_minutes（含追问），所有题目 estimated_minutes 之和 ≤ 22。出题后请在心中累加验证。**

基于上述信息，为这位候选人设计一套个性化面试题。需要覆盖以下三类：

### 1. 技术问题 (technical): 1-2题
- 至少1题验证候选人简历中提到的核心技术栈在 JD 相关场景中的真实使用深度
- 难度以简单到中等为主。早期职业生涯候选人不要出架构设计题
- 每题 estimated_minutes: 3-6

### 2. 行为问题 (behavioral): 1题
- 基于简历中与 JD 岗位相关的实际工作情境设计
- 精选最能区分候选人的 1 个情境即可
- 每题 estimated_minutes: 3-4

### 3. 缺口探查 (gap_probing): 1-2题
- 只探查 JD 中要求但候选人匹配分析显示不足的最关键能力短板
- 目的不是为难候选人，而是评估其弥补短板的潜力
- 每题 estimated_minutes: 3-5

### 出题优先级
优先保证：1-2道技术题 + 1道行为题。如有时间余量再加缺口探查题。总时间不得超过 22 分钟。

### 输出格式

严格按以下 JSON 格式输出（即使某类没有题目，也必须输出空数组[]）：

{{
  "interview_questions": {{
    "technical": [
      {{
        "question": "具体问题内容",
        "category": "系统设计 / 编码能力 / 架构 / 技术深度 / 基础知识",
        "difficulty": "简单 / 中等 / 困难",
        "estimated_minutes": 5,
        "purpose": "这道题想考察什么，一句话",
        "expected_points": ["预期回答要点1", "要点2", "要点3"]
      }}
    ],
    "behavioral": [
      {{
        "question": "具体问题内容",
        "category": "团队协作 / 冲突解决 / 职业规划",
        "difficulty": "简单 / 中等 / 困难",
        "estimated_minutes": 4,
        "purpose": "这道题想考察什么，一句话",
        "expected_points": ["预期回答要点1", "要点2"]
      }}
    ],
    "gap_probing": [
      {{
        "question": "具体问题内容",
        "category": "技术潜力 / 学习能力 / 基础认知",
        "difficulty": "简单 / 中等 / 困难",
        "estimated_minutes": 4,
        "purpose": "这道题想考察什么，一句话",
        "expected_points": ["预期回答要点1", "要点2"]
      }}
    ]
  }},
  "interview_focus": ["面试中应重点关注的3个方面"],
  "estimated_duration": "25分钟",
  "question_count": 4
}}"""


def _extract_question_texts(interview_result: dict | None) -> list[str]:
    """Extract all question texts from an interview result."""
    if not interview_result:
        return []
    iq = interview_result.get("interview_questions", {})
    texts = []
    for category in ("technical", "behavioral", "gap_probing"):
        for q in iq.get(category, []):
            t = q.get("question", "")
            if t:
                texts.append(t)
    return texts


def _build_avoidance_section(previous_questions: list[str] | None) -> str:
    """Build the 'avoid similar questions' section for prompts."""
    if not previous_questions:
        return ""
    lines = "\n".join(f"- {q}" for q in previous_questions)
    return f"""

## 已出过的题目（严禁生成相似题目）

{lines}

**极其重要的去重要求：**
- 新题目必须与上述已有题目在**考察角度、具体问法、场景设定**上有本质区别
- **不能**只是换一种措辞问同一个考察点，这不算"换题"
- 如需考察同一能力维度，必须换一个截然不同的场景或切入角度
- 如果实在无法在某个方向找到不重复的题目，宁可换一个完全不同的考察方向"""


def build_focus_questions_prompt(
    jd_text: str, resume_text: str, match_result: dict, interview_focus: list[str],
    previous_questions: list[str] | None = None,
    excluded_focus: list[str] | None = None,
) -> str:
    avoidance = _build_avoidance_section(previous_questions)
    exclusion = ""
    if excluded_focus:
        exclusion = f"""

## 面试官明确排除的方向（绝对不要围绕这些方向出题）

{chr(10).join(f'- {f}' for f in excluded_focus)}

**即使匹配分析结果中提到了与上述方向相关的内容，也绝对不能出题。面试官已经确认不关注这些方向。**"""

    return f"""## 职位描述 (JD)
{jd_text}

## 候选人简历
{resume_text}

## 匹配分析结果（仅供参考）
{json.dumps(match_result, ensure_ascii=False, indent=2)}

## 面试重点（面试官已确认，必须严格据此出题）

{chr(10).join(f"{i+1}. {f}" for i, f in enumerate(interview_focus))}
{exclusion}
## 出题要求

面试总时长：**严格控制在 25 分钟以内**，可用提问时间 ≤ 22 分钟。请围绕上述面试重点设计 4-5 道题目。

**核心约束 —— 请逐条确认后再输出（极其重要）：**

1. 你**只能**围绕上面列出的 {len(interview_focus)} 条面试重点来设计问题
2. **禁止**设计与上述重点无关的问题 —— 哪怕匹配分析结果中提到了某个能力缺口，只要它不在上面的面试重点列表中，就**绝对不能**为它出题
3. 匹配分析结果中的 gaps/highlights 只是背景信息，它们的唯一作用是帮助你理解每条面试重点背后的语境。**它们不是出题清单**
4. 如果某道题不能明确对应到至少一条面试重点，就**不要**出那道题
5. 面试重点中的每一项都要有至少 1 道题来覆盖
6. **每道题的 purpose 字段开头必须注明"对应面试重点第X条"**，以此自检该题确实服务于某条重点
7. **JD 范围约束**：所有问题必须在 JD 岗位职责范围内。JD 是开发岗就不要出项目管理题；JD 未要求的技能栈不要作为独立考点
8. **每道题必须标注 estimated_minutes（含追问）**，所有题目 estimated_minutes 之和 ≤ 22。出题后请在心中累加验证
{avoidance}

**输出前自检清单：**
逐一检查每道题 → 它对应哪条面试重点？→ 在 JD 范围内吗？→ 所有 estimated_minutes 总和 ≤ 22？→ 如任一项不满足，删减或调整题目。

题目可以按以下三类组织，但必须以服务面试重点为前提：
- 技术问题 (technical)：验证重点中涉及的技术能力
- 行为问题 (behavioral)：验证重点中涉及的软技能和项目经验
- 缺口探查 (gap_probing)：探查重点中指出的能力短板

### 输出格式

严格按以下 JSON 格式输出（即使某类没有题目，也必须输出空数组[]）：

{{
  "interview_questions": {{
    "technical": [
      {{
        "question": "具体问题内容",
        "category": "系统设计 / 编码能力 / 架构 / 技术深度 / 基础知识",
        "difficulty": "简单 / 中等 / 困难",
        "estimated_minutes": 5,
        "purpose": "这道题想考察什么，对应哪条面试重点",
        "expected_points": ["预期回答要点1", "要点2", "要点3"]
      }}
    ],
    "behavioral": [
      {{
        "question": "具体问题内容",
        "category": "团队协作 / 冲突解决 / 职业规划",
        "difficulty": "简单 / 中等 / 困难",
        "estimated_minutes": 4,
        "purpose": "这道题想考察什么，对应哪条面试重点",
        "expected_points": ["预期回答要点1", "要点2"]
      }}
    ],
    "gap_probing": [
      {{
        "question": "具体问题内容",
        "category": "技术潜力 / 学习能力 / 基础认知",
        "difficulty": "简单 / 中等 / 困难",
        "estimated_minutes": 4,
        "purpose": "这道题想考察什么，对应哪条面试重点",
        "expected_points": ["预期回答要点1", "要点2"]
      }}
    ]
  }},
  "interview_focus": {json.dumps(interview_focus, ensure_ascii=False)},
  "estimated_duration": "25分钟",
  "question_count": 4
}}"""


def generate_questions(
    llm: BaseLLMService,
    jd_text: str,
    resume_text: str,
    match_result: dict,
    interview_focus: list[str] | None = None,
    previous_questions: list[str] | None = None,
    excluded_focus: list[str] | None = None,
) -> dict:
    if interview_focus:
        user_prompt = build_focus_questions_prompt(
            jd_text, resume_text, match_result, interview_focus,
            previous_questions, excluded_focus,
        )
    else:
        user_prompt = build_interview_prompt(jd_text, resume_text, match_result)
        avoidance = _build_avoidance_section(previous_questions)
        if avoidance:
            user_prompt += avoidance
    try:
        result = llm.chat_json(INTERVIEWER_SYSTEM_PROMPT, user_prompt)
    except Exception as e:
        raise Exception(f"面试问题生成失败: {e}")

    _validate_interview_result(result)
    # Force the interview_focus to be exactly what the user confirmed, never the LLM's version
    if interview_focus:
        result["interview_focus"] = interview_focus
    return result


FOCUS_SYSTEM_PROMPT = """你是面试方向提取器。你的输出会被程序自动截断到10个字，所以请确保核心信息在前10个字内。

你必须严格输出以下JSON格式，每条标签不超过10个中文字符：

{
  "interview_focus": ["动词+名词", "动词+名词", "动词+名词"]
}

正确标签示例（≤10字，纯动词短语）：
- "验证报表开发能力"（8字）
- "深挖SQL调优经验"（8字）
- "评估沟通协作力"（7字）
- "考察架构设计力"（7字）
- "探查学习迁移力"（7字）

绝对禁止的格式：
- 带冒号或解释的："验证XX：要求候选人..." ← 禁止
- 带逗号的："验证XX能力，包括YY和ZZ" ← 禁止
- 疑问句："候选人是否具备XX能力？" ← 禁止
- 完整句子："需要深入了解候选人..." ← 禁止
- 超过10字的标签（会被截断，请保持≤10字）

只输出JSON，不输出任何其他文字。"""


print("[interviewer.py] MODULE LOADED — _trim_focus_labels is active", flush=True)


def generate_focus(
    llm: BaseLLMService,
    jd_text: str,
    resume_text: str,
    match_result: dict,
    previous_focus: list[str] | None = None,
    previous_questions: list[str] | None = None,
) -> list[str]:
    user_prompt = f"""## 职位描述 (JD)
{jd_text}

## 候选人简历
{resume_text}

## 匹配分析结果
{json.dumps(match_result, ensure_ascii=False, indent=2)}"""

    if previous_focus:
        user_prompt += f"""

## 上一轮面试重点（新重点必须与以下方向有本质区别）
{chr(10).join(f'- {f}' for f in previous_focus)}"""

    if previous_questions:
        user_prompt += f"""

## 已出过的面试题（新重点不要引出相似题目）
{chr(10).join(f'- {q}' for q in previous_questions)}"""

    if previous_focus or previous_questions:
        user_prompt += """

**重要：从不同角度提炼方向，与上轮有本质区别。**"""

    user_prompt += """

请列出 3-5 条面试方向标签。记住：只输出极简的动词短语标签，不是面试题描述。"""
    try:
        result = llm.chat_json(FOCUS_SYSTEM_PROMPT, user_prompt)
    except Exception as e:
        raise Exception(f"面试重点生成失败: {e}")

    if "interview_focus" not in result:
        raise Exception("面试重点结果缺少 interview_focus 字段")

    raw = result["interview_focus"]
    trimmed = _trim_focus_labels(raw)
    print(f"[generate_focus] RAW ({sum(len(i) for i in raw)} chars total): {raw}")
    print(f"[generate_focus] TRIMMED: {trimmed}")
    return trimmed


def _trim_focus_labels(items: list[str]) -> list[str]:
    """Mechanically trim each focus item to a short directional label.

    Strategy (in order):
    1. Split on colon/semicolon — keep only the label before it
    2. Strip common verbose prefixes (e.g. "验证候选人的" → "验证")
    3. If still >12 chars, split on comma/period — keep first segment
    4. Hard truncate to 12 chars as final fallback
    """
    import re

    # Strip leading noise words, then remove filler subjects
    _LEADING_NOISE_RE = re.compile(r'^(深入|重点|需要|必须|应该|是否|如何|请|要|的|地)')
    _FILLER_RE = re.compile(
        r'^(验证|深挖|评估|考察|探查|了解|确认|判断|比对|对比)'
        r'(候选人(的|在)?|应聘者(的|在)?|求职者(的|在)?|'
        r'该候选人(的|在)?|其在|其|对方(的|在)?)'
    )

    trimmed = []
    for item in items:
        label = item.strip()
        # Step 1: take only the part before any colon/semicolon
        for sep in ('：', ':', ';', '；', '—', '——'):
            if sep in label:
                label = label.split(sep)[0].strip()
                break
        # Step 2a: strip leading noise words (深入/重点/需要/...)
        _nm = _LEADING_NOISE_RE.match(label)
        if _nm and len(label) > 12:
            label = label[_nm.end():].strip()
        # Step 2b: remove filler subjects (候选人的/应聘者的/...)
        m = _FILLER_RE.match(label)
        if m and len(label) > 12:
            verb = m.group(1)
            rest = label[m.end():].lstrip('的')
            candidate = f"{verb}{rest}" if rest else label
            if len(candidate) >= 4:  # don't make it too short
                label = candidate
        # Step 3: if still long, take first comma-separated segment
        if len(label) > 12:
            parts = re.split(r'[，,。．、]', label)
            if len(parts) > 1 and len(parts[0]) < len(label):
                label = parts[0].strip()
        # Step 4: hard truncate to 12 chars
        if len(label) > 12:
            label = label[:12].rstrip()
        if label:
            trimmed.append(label)
    return trimmed if trimmed else items


def _validate_interview_result(result: dict) -> None:
    if "interview_questions" not in result:
        raise Exception("面试问题结果缺少 interview_questions 字段")
    iq = result["interview_questions"]
    for key in ("technical", "behavioral", "gap_probing"):
        if key not in iq:
            iq[key] = []  # LLM may omit empty categories — set empty list


REPLACE_QUESTION_PROMPT = """你是一位资深技术面试官。现有的一道面试题不够理想，请根据同样的上下文生成一道替换题。

面试时长背景：本轮面试总时长控制在 25 分钟以内，可用提问时间 ≤ 22 分钟。替换题的 estimated_minutes 应与原题相同。

JD 范围约束：替换题必须在岗位 JD 范围内——JD 是开发岗就不要出项目管理题。

要求：
- 保持同一考察方向（category），但换一个不同的具体问题
- 难度级别保持不变
- 问题必须有明确的考察点和预期答案要点
- 避免与已有问题重复
- 如果这是技术题，聚焦实际应用场景而非理论概念
- 如果这是行为题，更换情境但考察同样的能力维度
- 如果这是缺口探查题，换一个角度评估候选人的学习潜力
- **绝不**基于简历中的乱码/噪声内容设计问题（噪声来自原始文件DRM水印/加密保护，与候选人能力无关）

请严格按 JSON 格式输出，只输出一个新的问题对象，不要包含额外文字：
{
  "question": "新问题内容",
  "category": "分类（系统设计/编码能力/架构等）",
  "difficulty": "简单/中等/困难",
  "estimated_minutes": 5,
  "purpose": "考察目的",
  "expected_points": ["要点1", "要点2", "要点3"]
}"""


def replace_question(
    llm: BaseLLMService,
    jd_text: str,
    resume_text: str,
    match_result: dict,
    category: str,
    old_question: dict,
    sibling_questions: list[str] | None = None,
) -> dict:
    user_prompt = f"""## 职位描述
{jd_text}

## 候选人简历
{resume_text}

## 匹配分析
{json.dumps(match_result, ensure_ascii=False, indent=2)}

## 需要替换的题目
- 分类: {category}
- 原问题: {old_question.get("question", "")}
- 难度: {old_question.get("difficulty", "中等")}
- 原考察目的: {old_question.get("purpose", "")}"""

    if sibling_questions:
        user_prompt += f"""

## 同类已有题目（替换题必须与它们都不同）
{chr(10).join(f'- {q}' for q in sibling_questions)}

**去重约束：替换题在考察角度和具体问法上必须与以上所有已有题目有本质区别，不能只是换一种表述。**"""

    user_prompt += """

请生成一道同类型、同难度的替换题。"""
    try:
        result = llm.chat_json(REPLACE_QUESTION_PROMPT, user_prompt)
    except Exception as e:
        raise Exception(f"换题失败: {e}")
    for field in ("question", "category", "difficulty", "purpose", "expected_points"):
        if field not in result:
            raise Exception(f"替换题缺少字段: {field}")
    return result
