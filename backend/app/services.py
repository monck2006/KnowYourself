"""Local, explainable record summaries. No diagnosis, prescriptions or model calls.

Rules are prototype safety prompts, not a clinically validated triage system.
Historical similarity must never reduce the priority of a safety prompt.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from statistics import median

RULE_VERSION = "personal-health-2.1"
DISCLAIMER = (
    "依据你的记录整理下一步；相似病程和区域信号不能确定病因，用药后的变化不等于药物疗效。"
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
    "prevention": {
        "title": "CDC：出现呼吸道症状时的防护措施",
        "url": "https://www.cdc.gov/respiratory-viruses/prevention/precautions-when-sick.html",
    },
    "family": {
        "title": "NIH MedlinePlus：家族健康史与遗传风险",
        "url": "https://medlineplus.gov/genetics/understanding/inheritance/familyhistory/",
    },
    "device": {
        "title": "FDA：血氧仪读数的准确性与局限",
        "url": "https://www.fda.gov/medical-devices/products-and-medical-procedures/pulse-oximeters",
    },
    "hydration": {
        "title": "NHS：脱水与需要及时求助的信号",
        "url": "https://www.nhs.uk/conditions/dehydration/",
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
DANGER_ANSWERS = {"breathing_difficulty": ("严重呼吸困难", "breathing"),
                  "chest_pain": ("正在发生的胸痛或胸部压迫感", "heart"),
                  "confusion": ("新出现的意识异常", "breathing")}


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
        if selected or mentioned or any(item.get("answer") == "yes" and item.get("question_id") in DANGER_ANSWERS
                                        for item in episode.get("assessment_answers", [])):
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


def _duration(item: dict, today: date) -> int:
    end = date.fromisoformat(item.get("ended_at") or today.isoformat())
    return max(1, (end - date.fromisoformat(str(item["started_at"]))).days + 1)


def _device_context(episode: dict, history: list[dict], context: dict, now: datetime) -> dict:
    """Compare like-for-like resting readings before onset, excluding known illnesses."""
    observations = context.get("observations") or {}
    items = list({item["id"]: item for item in [*observations.get("items", []), *observations.get("latest", {}).values()]}.values())
    tz = timezone(timedelta(hours=8))
    start = date.fromisoformat(episode["started_at"])
    end = date.fromisoformat(episode.get("ended_at") or now.astimezone(tz).date().isoformat())
    reference = min(now, datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=tz))
    linked = set(episode.get("observation_ids") or [])
    latest = {}
    resting = None
    for item in items:
        when = datetime.fromisoformat(item["measured_at"].replace("Z", "+00:00"))
        if linked and item["id"] not in linked:
            continue
        if not (start <= when.astimezone(tz).date() <= end and reference - timedelta(hours=24) <= when <= reference):
            continue
        if item["metric"] not in latest or when > datetime.fromisoformat(latest[item["metric"]]["measured_at"].replace("Z", "+00:00")):
            latest[item["metric"]] = item
        if item["metric"] == "heart_rate" and item.get("context") == "resting":
            if resting is None or when > datetime.fromisoformat(resting["measured_at"].replace("Z", "+00:00")):
                resting = item
    readings = list(latest.values())
    if resting is not None and all(item["id"] != resting["id"] for item in readings):
        readings.append(resting)
    deviations = []
    for reading in readings:
        metric = reading["metric"]
        if metric != "heart_rate" or reading.get("context") != "resting":
            continue
        daily = defaultdict(list)
        for item in context.get("_baseline_observations", items):
            day = datetime.fromisoformat(item["measured_at"].replace("Z", "+00:00")).astimezone(tz).date()
            if not start - timedelta(days=30) <= day < start:
                continue
            if any(date.fromisoformat(old["started_at"]) <= day <= date.fromisoformat(old.get("ended_at") or day.isoformat()) for old in history):
                continue
            if (item["metric"] == metric and item.get("context") == "resting"
                    and item["source"] == reading["source"] and item.get("device_name") == reading.get("device_name")):
                daily[day].append(item["value"])
        if len(daily) >= 3:
            baseline = median(median(values) for values in daily.values())
            difference = reading["value"] - baseline
            deviations.append(f"本次静息心率 {reading['value']:g} bpm，发病前 {len(daily)} 天同来源静息中位数 {baseline:g} bpm，相差 {difference:+g} bpm。")
    return {"readings": readings, "deviations": deviations,
            "baseline_note": "仅比较发病前至少 3 天、同来源同设备的静息读数，并排除已记录病程；数值差异不直接判定疾病。"}


def analyze_episode(episode: dict, history: list[dict], context: dict | None = None, *, now: datetime | None = None) -> dict:
    """Produce a deterministic snapshot using preceding, completed records only."""
    context = context or {}
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(timezone(timedelta(hours=8))).date()
    has_start = bool(episode.get("started_at"))
    earlier = [
        item for item in history
        if has_start and item.get("id") != episode.get("id")
        and item.get("status") == "ended"
        and item.get("ended_at")
        and str(item["ended_at"]) < str(episode["started_at"])
    ]
    names = symptom_set(episode)
    matching = [
        item for item in earlier
        if names and len(names & symptom_set(item)) / len(names | symptom_set(item)) >= 0.6
    ]
    matches = len(matching)
    durations = [_duration(item, today) for item in matching]
    device = (_device_context(episode, history, context, now) if has_start else
              {"readings": [], "deviations": [], "baseline_note": "起病时间尚未确认，暂不关联设备读数。"})
    selected, mentioned = _danger_mentions(episode)
    answers = {item["question_id"]: item["answer"] for item in episode.get("assessment_answers", [])}
    vitals = dict(episode.get("vitals") or {})
    for reading in device["readings"]:
        if reading["metric"] in {"temperature", "heart_rate", "spo2"} and vitals.get(reading["metric"]) is None:
            vitals[reading["metric"]] = reading["value"]
    reasons: list[str] = []
    source_keys: list[str] = []
    confirmed_danger = [value for key, value in DANGER_ANSWERS.items() if answers.get(key) == "yes"]
    emergency = bool(selected or mentioned or confirmed_danger)
    for label, source_key in confirmed_danger:
        reasons.append("补问确认本次存在「" + label + "」，请优先处理，不等待进一步分析。")
        source_keys.append(source_key)
    if selected:
        reasons.append("症状记录包含需警惕的信号：" + "、".join(selected) + "。")
    if mentioned:
        reasons.append(
            "文字描述提及「" + "、".join(mentioned)
            + "」。系统不能可靠识别否定、既往或他人病情；请确认是否为本次实际症状。"
        )
    source_keys.extend(DANGER_TERMS[term] for term in selected + mentioned)
    oxygen_readings = [reading["value"] for reading in device["readings"] if reading["metric"] == "spo2"]
    oxygen = min([vitals["spo2"], *oxygen_readings]) if vitals.get("spo2") is not None else None
    if oxygen is not None and oxygen <= 92:
        emergency = True
        reasons.append(
            f"记录的血氧为 {oxygen}%。请立即核实测量；若仍低或伴不适，请立即寻求急诊评估。"
            "手表读数应使用指夹式血氧仪复核；此成人参考阈值并不适用于所有人，不能覆盖个人医嘱。"
        )
        source_keys.append("oxygen")
        source_keys.append("device")
    severity = episode.get("severity")
    severe = isinstance(severity, int) and not isinstance(severity, bool) and severity >= 4
    attention = severe or episode.get("outcome") == "worsened"
    answer_attention = {
        "dehydration": ("补问记录无法正常饮水或尿量明显减少，请今天联系医生评估。", "hydration"),
        "worsening": ("补问记录本次症状较此前加重，请今天安排医疗评估。", None),
        "fever_persistent": ("补问记录发热在居家处理后仍不改善或加重，请今天联系医生。", "fever"),
        "medication_reaction": ("补问记录用药期间出现新的明显不适，请今天向医生或药师说明时间和症状；不能据此确定药物因果。", None),
    }
    for key, (detail, source_key) in answer_attention.items():
        if answers.get(key) == "yes":
            attention = True
            reasons.append(detail)
            if source_key:
                source_keys.append(source_key)
    if severe:
        reasons.append("你将症状影响程度记录为较重，建议及时联系医生评估。")
    if episode.get("outcome") == "worsened":
        reasons.append("记录显示症状在加重，建议及时就医。")
    temperature_readings = [reading["value"] for reading in device["readings"] if reading["metric"] == "temperature"]
    temperature = max([vitals["temperature"], *temperature_readings]) if vitals.get("temperature") is not None else None
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
        reasons.append("以下用药变化来自你的自报，不代表疗效判断；请把实际用药情况与病程一并用于就医沟通。")
    reasons.extend(device["deviations"])
    duration = _duration(episode, today) if has_start else None
    profile = context.get("profile") or {}
    age = today.year - profile["birth_year"] if profile.get("birth_year") else None
    region = context.get("region") or {"enabled": False, "status": "disabled", "signals": []}
    actions = []
    def action(priority, title, detail):
        actions.append({"priority": priority, "title": title, "detail": detail})
    if emergency:
        action("now", "先处理危险信号", "若胸痛、呼吸困难、意识异常等正在发生，立即拨打 120 或前往急诊；不要等待新的设备数据。血氧偏低请马上复测，仍低或伴不适立即求助。")
    elif attention:
        action("today", "今天安排医疗评估", "本次有需要及时核实的情况。带上起病日期、体征变化、补问答案和用药清单，向医生说明变化。")
    else:
        elapsed = f"本次已记录第 {duration} 天。" if duration is not None else "起病时间尚未确认。"
        action("observe", "更新今天的病程变化", elapsed + "补充今天比昨天好转、持平还是加重，以及能否正常饮水、进食和活动；若加重或出现危险信号及时就医。")
    for key, (detail, _) in answer_attention.items():
        if answers.get(key) == "yes":
            action("today", {"dehydration": "核实饮水和尿量", "worsening": "说明症状如何加重",
                             "fever_persistent": "说明发热的持续与变化", "medication_reaction": "核对用药期间的新不适"}[key], detail)
    if temperature is not None and temperature >= 38:
        if age is not None and age <= 18:
            action("today", "按儿童实际年龄咨询发热处理", "向儿科说明实际年龄、测温方式、起病时间、饮水和精神状态；这里的成人发热参考不能用于判断儿童病情。")
        else:
            detail = "记录测量时间、方式和退热药使用时间；适当休息、补水。发热在居家处理后仍不改善或加重时，就医评估。单次读数不代表发热持续天数。"
            if age is None:
                detail += "儿童请按实际年龄向儿科咨询。"
            action("today", "补充体温变化并休息补水", detail)
    if not any(value is not None for value in vitals.values()):
        action("observe", "补齐可获得的体征", "测量并记录体温；如果已有心率或血氧设备，可同步读数并注明是否静息。没有设备时先记录症状变化和饮水、活动情况。")
    if device["deviations"]:
        action("observe", "复测与自身基线不同的读数", "在相同设备、相近条件下安静休息后再测一次，记录是否持续偏离及伴随症状；伴胸痛、气促或晕厥立即求助。")
    if len(durations) >= 2 and duration is not None and duration > max(durations) and episode.get("status") == "ongoing":
        attention = True
        action("today", "这次持续时间超过你的既往记录", f"相近病程过去记录为 {min(durations)}–{max(durations)} 天，本次第 {duration} 天。若仍未明显改善，联系医生评估并展示这些对比。")
    respiratory = len(names & {"咳嗽", "咽痛", "发热", "流鼻涕"}) >= 2 or (episode.get("disease_category") == "infectious" and episode.get("infection_group") == "respiratory")
    if any(answers.get(key) == "yes" for key in ("pregnancy", "immunosuppression")):
        action("today", "说明妊娠或免疫相关情况", "补问提示存在需个别评估的情况。向医生说明实际孕周，或免疫相关疾病和治疗；系统不推断具体风险或调整用药。")
    if answers.get("exposure") == "yes":
        action("today", "补充接触的对象、时间与场所", "你在补问中记录近期接触过相似症状者。就医时说明接触时间及症状；接触史不能确定已感染。")
    if respiratory:
        action("today", "减少把呼吸道症状传给家人", "减少与他人近距离接触，保持通风，接触他人时佩戴合适口罩。整体症状好转且不用退热药已至少 24 小时无发热后再恢复日常活动，随后 5 天继续加强防护；当地规定或医嘱优先。")
        source_keys.append("prevention")
        if profile.get("chronic_conditions"):
            action("today", "结合基础病尽早咨询", "你记录了「" + "、".join(profile["chronic_conditions"]) + "」。向医生说明基础病、起病时间和当前用药，以便判断是否需要更早检查或治疗。")
    if episode.get("disease_category") == "hereditary" or profile.get("family_history"):
        action("observe", "把家族线索整理成可评估的信息", "补充患病亲属关系、发病年龄、明确诊断及已有检测报告；就诊时讨论是否需要遗传咨询。家族史本身不等于你已患遗传病。")
        source_keys.append("family")
    relevant = {"respiratory"} if respiratory else ({"gastrointestinal"} if len(names & {"腹泻", "呕吐", "腹痛"}) >= 2 else set())
    if any(signal.get("cluster") in relevant and signal.get("level") == "elevated" for signal in region.get("signals", [])):
        action("today", "就诊时补充近期接触与出行史", "你所在粗略区域的相似症状自报有所增加。补充家庭、学校或工作场所接触史，必要时由医生决定检测；区域信号不能确定个人感染。")
    medication_review = []
    for medication in episode.get("medications", []):
        start = medication.get("started_at")
        end = medication.get("ended_at") or episode.get("ended_at") or today.isoformat()
        days = max(1, (date.fromisoformat(end) - date.fromisoformat(start)).days + 1) if start else None
        response = medication.get("response", "unknown")
        adherence = medication.get("adherence", "unknown")
        note = {"improving": "记录为用药期间好转，不能仅凭时间先后确定疗效。", "unchanged": "记录为未见变化，补充观察时间和症状程度。", "worsened": "记录为用药期间加重，请及时联系医生或药师说明症状和用药时间。", "unknown": "补充实际起止时间及用药期间的症状变化。"}[response]
        medication_review.append({"name": medication["name"], "days": days, "adherence": adherence, "response": response, "note": note})
        if response == "worsened":
            attention = True
            action("today", "核对用药期间的加重", medication["name"] + "：" + note + "不能仅凭自报认定是药物引起；如有呼吸困难等立即急诊。")
        if adherence == "missed":
            action("today", "记录漏服并核对该药说明", medication["name"] + "：补充漏服时间，查看该药说明书或向药师确认后续安排，系统不会自动计算补服剂量。")
    actions.sort(key=lambda item: {"now": 0, "today": 1, "observe": 2}[item["priority"]])
    if episode.get("status") == "ended":
        elapsed = f"本次记录持续 {duration} 天。" if duration is not None else "本次起止日期尚未确认。"
        actions = [{"priority": "observe", "title": "回顾本次病程与用药", "detail": elapsed + "保留起止日期、用药期间变化与测量来源，供下次发病对照；若上述危险症状仍在发生，应立即求助。"}]
        if confirmed_danger:
            actions.insert(0, {"priority": "now", "title": "先处理当前危险信号", "detail": "虽然病程标记为已结束，你在补问中确认当前危险症状；立即拨打 120 或前往急诊，不等待回顾分析。"})
    if emergency:
        label = "请确认并及时处理危险信号"
        summary = "如这些危险症状正在发生，请立即就医或拨打当地急救电话（中国大陆 120），不要等待系统分析。"
    elif attention:
        label = "今天需要优先处理的事项"
        summary = actions[0]["detail"]
    else:
        label = "今天的下一步"
        summary = actions[0]["detail"]
    if episode.get("status") == "ended":
        summary = "这是已结束病程的回顾提示。" + summary
    return {
        "level": "emergency" if emergency else "attention" if attention else "recorded",
        "label": label, "summary": summary, "reasons": reasons,
        "matched_count": matches, "disclaimer": DISCLAIMER,
        "rule_version": RULE_VERSION,
        "sources": [SOURCES[key] for key in dict.fromkeys(source_keys)],
        "duration_days": duration, "action_plan": actions,
        "history_comparison": {"matched_count": matches, "typical_duration_days": median(durations) if durations else None,
                               "range_days": [min(durations), max(durations)] if durations else None,
                               "records": [{"id": item.get("id"), "started_at": item["started_at"], "duration_days": _duration(item, today),
                                            "medications": [med["name"] for med in item.get("medications", [])]} for item in matching[:5]]},
        "device_context": device, "regional_context": region,
        "profile_context": {"birth_year": profile.get("birth_year"), "chronic_conditions": profile.get("chronic_conditions", []), "family_history": profile.get("family_history", []),
                            "disease_category": episode.get("disease_category", "unknown"), "diagnosis_name": episode.get("diagnosis_name", ""),
                            "diagnosis_source": episode.get("diagnosis_source", "unknown")},
        "medication_review": medication_review,
    }
