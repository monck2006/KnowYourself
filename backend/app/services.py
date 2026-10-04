"""Local, explainable record summaries. No diagnosis, prescriptions or model calls.

Rules are prototype safety prompts, not a clinically validated triage system.
Historical similarity must never reduce the priority of a safety prompt.
"""

from collections import Counter, defaultdict

RULE_VERSION = "record-safety-1.0"
DISCLAIMER = (
    "仅用于健康记录与信息整理，不能诊断疾病、判断用药效果或排除急症。"
    "症状相似不代表病因相同；儿童、孕产妇及有基础病者需专业评估。"
)
SOURCES = {
    "breathing": {
        "title": "NHS：呼吸困难与紧急求助信号",
        "url": "https://www.nhs.uk/symptoms/shortness-of-breath/",
    },
    "heart": {
        "title": "NHS：胸痛等紧急求助信号",
        "url": "https://www.nhs.uk/conditions/heart-attack/",
    },
    "stroke": {
        "title": "NHS：卒中症状识别",
        "url": "https://www.nhs.uk/conditions/stroke/symptoms/",
    },
    "firstaid": {
        "title": "St John Ambulance：急救知识",
        "url": "https://www.sja.org.uk/first-aid-advice/",
    },
    "oxygen": {
        "title": "NHS England：COVID-19 居家血氧监测（适用范围有限）",
        "url": "https://www.england.nhs.uk/coronavirus/documents/covid-19-standard-operating-procedure-covid-oximetry-home/",
    },
    "fever": {
        "title": "NHS：成人发热",
        "url": "https://www.nhs.uk/symptoms/fever-in-adults/",
    },
}
# Selected symptoms are explicit user assertions. Free text is flagged as a
# mention, never interpreted as a confirmed positive or reliable negative.
DANGER_TERMS = {
    "胸痛": "heart", "胸口疼": "heart", "胸口痛": "heart",
    "呼吸困难": "breathing", "喘不上气": "breathing", "喘不过气": "breathing",
    "意识不清": "breathing", "意识改变": "breathing", "昏迷": "firstaid",
    "抽搐": "firstaid", "大出血": "firstaid", "口角歪斜": "stroke",
    "言语不清": "stroke", "说话含糊": "stroke",
}
ALIASES = {"流涕": "流鼻涕", "嗓子痛": "咽痛", "喉咙痛": "咽痛", "发烧": "发热"}


def symptom_set(episode: dict) -> set[str]:
    return {ALIASES.get(name.strip(), name.strip()) for name in episode.get("symptoms", []) if name.strip()}


def _danger_mentions(episode: dict) -> tuple[list[str], list[str]]:
    symptoms = "、".join(episode.get("symptoms", []))
    description = " ".join([episode.get("chief_complaint", ""), episode.get("notes", "")])
    selected = sorted(term for term in DANGER_TERMS if term in symptoms)
    mentioned = sorted(term for term in DANGER_TERMS if term in description and term not in selected)
    return selected, mentioned


def build_patterns(episodes: list[dict]) -> list[dict]:
    """Describe repeated completed symptom sets, without assigning diseases."""
    groups: dict[tuple[str, ...], list[dict]] = defaultdict(list)
    for episode in episodes:
        if episode.get("status") != "ended" or episode.get("outcome") == "worsened":
            continue
        selected, mentioned = _danger_mentions(episode)
        if selected or mentioned:
            continue
        names = tuple(sorted(symptom_set(episode)))
        if names:
            groups[names].append(episode)
    return sorted([
        {
            "symptoms": list(names),
            "occurrences": len(items),
            "last_seen": max(str(item["started_at"]) for item in items),
        }
        for names, items in groups.items() if len(items) >= 2
    ], key=lambda item: (-item["occurrences"], item["symptoms"]))


def analyze_episode(episode: dict, history: list[dict]) -> dict:
    """Produce a deterministic snapshot using preceding, completed records only."""
    earlier = [
        item for item in history
        if item.get("id") != episode.get("id")
        and item.get("status") == "ended"
        and item.get("ended_at")
        and str(item["ended_at"]) < str(episode["started_at"])
    ]
    names = symptom_set(episode)
    matches = sum(
        1 for item in earlier
        if names and len(names & symptom_set(item)) / len(names | symptom_set(item)) >= 0.6
    )
    selected, mentioned = _danger_mentions(episode)
    vitals = episode.get("vitals") or {}
    reasons: list[str] = []
    source_keys: list[str] = []
    emergency = bool(selected or mentioned)
    if selected:
        reasons.append("症状记录包含需警惕的信号：" + "、".join(selected) + "。")
    if mentioned:
        reasons.append(
            "文字描述提及「" + "、".join(mentioned)
            + "」。系统不能可靠识别否定、既往或他人病情；请确认是否为本次实际症状。"
        )
    source_keys.extend(DANGER_TERMS[term] for term in selected + mentioned)
    oxygen = vitals.get("spo2")
    if oxygen is not None and oxygen <= 92:
        emergency = True
        reasons.append(
            f"记录的血氧为 {oxygen}%。请立即核实测量；若仍低或伴不适，请立即寻求急诊评估。"
            "参考阈值源自 COVID-19 成人居家监测，并不适用于所有人；已有个人目标值者应联系治疗团队。"
        )
        source_keys.append("oxygen")
    attention = episode.get("severity", 1) >= 4 or episode.get("outcome") == "worsened"
    if episode.get("severity", 1) >= 4:
        reasons.append("你将症状影响程度记录为较重，建议及时联系医生评估。")
    if episode.get("outcome") == "worsened":
        reasons.append("记录显示症状在加重，建议及时就医。")
    temperature = vitals.get("temperature")
    if temperature is not None and temperature >= 38:
        reasons.append(f"记录体温 {temperature}℃；单次读数不能说明发热持续时间。若持续不改善或加重，应及时就医。")
        source_keys.append("fever")
    if matches:
        reasons.append(f"此前有 {matches} 次已结束病程出现相近症状。相似记录只用于回顾，不能证明本次安全或病因相同。")
    else:
        reasons.append("暂无可对照的相近已结束病程，继续记录有助于就医时说明变化。")
    if not any(value is not None for value in vitals.values()):
        reasons.append("本次未记录体征，不能据此判断体征正常。")
    if episode.get("medications"):
        reasons.append("用药内容按你的输入保存，不代表疗效判断，也不构成继续、停止或调整用药的建议。")
    if emergency:
        label = "请确认并及时处理危险信号"
        summary = "如这些危险症状正在发生，请立即就医或拨打当地急救电话（中国大陆 120），不要等待系统分析。"
    elif attention:
        label = "建议及时就医评估"
        summary = "症状较重或在加重，请结合实际情况及时联系医生。"
    else:
        label = "记录已整理"
        summary = "当前规则未识别到已覆盖的危险词或低血氧信号；这不表示没有风险，也不能据此决定居家观察。"
    if episode.get("status") == "ended":
        summary = "这是已结束病程的回顾提示。" + summary
    return {
        "level": "emergency" if emergency else "attention" if attention else "recorded",
        "label": label, "summary": summary, "reasons": reasons,
        "matched_count": matches, "disclaimer": DISCLAIMER,
        "rule_version": RULE_VERSION,
        "sources": [SOURCES[key] for key in dict.fromkeys(source_keys)],
    }
