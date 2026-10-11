"""Bounded, source-aware follow-up assessment. No diagnosis or model calls."""

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
import math
import re

from .services import DANGER_TERMS, RULE_VERSION, symptom_set


TZ = timezone(timedelta(hours=8))
OPTIONS = [{"value": "yes", "label": "是"}, {"value": "no", "label": "否"}, {"value": "unknown", "label": "不清楚"}]
QUESTION_BANK = {
    "breathing_difficulty": ("本次现在是否严重呼吸困难，例如喘不过气或不能完整说话？", "先确认需要立即处理的呼吸信号。", "now"),
    "chest_pain": ("本次现在是否有胸痛或胸部压迫感？", "先确认本次正在发生的胸部危险信号。", "now"),
    "confusion": ("本次是否新出现意识不清、难以唤醒或明显反应异常？", "意识变化需要优先处理。", "now"),
    "dehydration": ("本次是否无法正常饮水、喝下即反复呕吐，或尿量明显少于平常？", "饮水和尿量有助于确定是否需要及时核实脱水风险。", "today"),
    "worsening": ("本次症状与此前相比是否正在加重，或更难完成平常活动？", "补充变化方向，不能仅用起病天数判断。", "today"),
    "exposure": ("起病前近期是否接触过有相似症状的人？", "接触对象与时间可供就医沟通，不能据此确定感染。", "observe"),
    "fever_persistent": ("本次发热在居家处理后是否仍不改善或正在加重？", "单次体温不能说明持续时间，需要你补充病程变化。", "today"),
    "pregnancy": ("你是否处于妊娠期（不适用可选否）？", "妊娠情况影响医生对检查和用药的个别评估。", "today"),
    "immunosuppression": ("是否有医生告知的免疫功能受损，或正在接受抑制免疫的治疗？", "需向医生说明相关疾病与治疗，不由症状推断。", "today"),
    "medication_reaction": ("本次用药期间是否出现新的明显不适，或原有不适明显加重？", "核对发生时间，时间先后不能证明药物因果。", "today"),
}
QUESTION_SYMPTOMS = {
    "breathing_difficulty": {"呼吸困难", "喘不上气", "喘不过气"},
    "chest_pain": {"胸痛", "胸口疼", "胸口痛"},
    "confusion": {"意识不清", "意识改变", "昏迷"},
}
METRICS = {"temperature": ("体温", "C", 30, 45), "spo2": ("血氧", "%", 50, 100),
           "heart_rate": ("心率", "bpm", 20, 250), "steps": ("步数", "count", 0, 200000),
           "sleep_minutes": ("睡眠时长", "min", 0, 1440),
           "dietary_energy": ("饮食摄入", "kcal", 0, 10000), "hydration": ("饮水", "ml", 0, 20000),
           "active_energy": ("活动消耗", "kcal", 0, 20000), "basal_energy": ("静息消耗", "kcal", 0, 20000),
           "hrv_sdnn": ("心率变异性 SDNN", "ms", 1, 500), "hrv_rmssd": ("心率变异性 RMSSD", "ms", 1, 500),
           "vo2max": ("最大摄氧量", "mL/kg/min", 5, 100),
           "distance_run": ("跑步距离", "m", 0, 200000), "distance_cycle": ("骑行距离", "m", 0, 500000),
           "exercise_minutes": ("运动时长", "min", 0, 1440)}


def _when(value):
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.astimezone(timezone.utc) if result.tzinfo is not None else None
    except (ValueError, TypeError, AttributeError):
        return None


def _monitoring(episode, analysis, context):
    now = _when(context.get("_assessment_now")) or datetime.now(timezone.utc)
    end_day = min(date.fromisoformat(episode.get("ended_at") or now.astimezone(TZ).date().isoformat()), now.astimezone(TZ).date())
    start_day = max(date.fromisoformat(episode["started_at"]), end_day - timedelta(days=6))
    start = datetime.combine(start_day, time.min, TZ).astimezone(timezone.utc)
    end = min(now, datetime.combine(end_day + timedelta(days=1), time.min, TZ).astimezone(timezone.utc))
    observations = context.get("observations") or {}
    raw = [*observations.get("items", []), *observations.get("latest", {}).values(), *context.get("_assessment_observations", [])]
    linked = set(episode.get("observation_ids") or [])
    daily = {}
    for item in raw:
        metric, at = item.get("metric"), _when(item.get("measured_at"))
        value = item.get("value")
        if metric not in METRICS or at is None or not start <= at <= end:
            continue
        if linked and item.get("id") not in linked:
            continue
        _, unit, low, high = METRICS[metric]
        if (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                or not low <= value <= high or item.get("unit") != unit):
            continue
        if metric == "steps" and not float(value).is_integer():
            continue
        # Resting HR is a separate series. Active/unknown HR never enters it.
        series = (metric, "resting" if metric == "heart_rate" and item.get("context") == "resting" else "other")
        day = at.astimezone(TZ).date().isoformat()
        aggregate_day = re.match(r"(?:steps|sleep)-utc-day-(\d{4}-\d{2}-\d{2}):", item.get("source_id", ""))
        if aggregate_day and metric in {"steps", "sleep_minutes"}:
            day = aggregate_day.group(1)
        key = (*series, day)
        previous = daily.get(key)
        if previous is None or (at, str(item.get("id", ""))) > (previous[0], str(previous[1].get("id", ""))):
            daily[key] = (at, item)
    series_points = defaultdict(list)
    for (metric, category, _), point in daily.items():
        series_points[(metric, category)].append(point)
    # Keep one recent point for every metric before filling older days; 14 total.
    chosen, remaining = [], []
    for series, points in sorted(series_points.items()):
        points.sort(key=lambda point: point[0], reverse=True)
        chosen.append((series, *points[0]))
        remaining.extend((series, *point) for point in points[1:])
    chosen.extend(sorted(remaining, key=lambda point: point[1], reverse=True)[:max(0, 14 - len(chosen))])
    metrics = []
    for series in sorted(series_points):
        metric, category = series
        label, unit, *_ = METRICS[metric]
        note = "每个日期取最新实际读数，不代表日均值；不同来源不能直接视为同等准确。"
        if metric == "heart_rate":
            label += "（静息）" if category == "resting" else "（活动或场景未知）"
            note += "仅平台明确标记的静息记录进入静息曲线，其他心率不用于推断静息基线。"
        if metric in {"steps", "sleep_minutes"}:
            note = "取当天最新记录或日总量修订，不叠加多次同步；原生日总量按 UTC 日期。"
        if metric == "sleep_minutes":
            note += "记录可能不完整，睡眠时长本身不能用于判断睡眠疾病。"
        points = [{"at": at.isoformat(), "value": item["value"], "source": item.get("source", "unknown")}
                  for key, at, item in sorted(chosen, key=lambda point: point[1]) if key == series]
        metrics.append({"metric": metric, "label": label, "points": points, "unit": unit, "note": note})
    level = analysis["level"]
    next_check = ("若危险症状正在发生，立即求助，不等待下一次打卡或设备同步。" if level == "emergency"
                  else "今天联系医生评估，并在就诊前补充最新症状、饮水和用药变化。" if level == "attention"
                  else "今天稍后或症状变化时更新一次；没有设备也可记录饮水、活动和症状趋势。")
    if episode.get("status") == "ended" and level != "emergency":
        next_check = "这是已结束病程的回顾；若目前仍有危险症状，立即求助，不等待新的记录。"
    return {"metrics": metrics, "next_check_in": next_check,
            "escalation_signs": ["正在发生的严重呼吸困难、胸痛或新出现意识异常：立即拨打 120 或前往急诊。",
                                 "症状加重、无法正常饮水、尿量明显减少，或发热仍不改善：及时联系医生。",
                                 "用药期间出现新的明显不适：记录药名、时间和症状，联系医生或药师核实。"]}, chosen


def _medication_checks(episode):
    medications = episode.get("medications") or []
    counts = Counter(item["name"] for item in medications)
    checks, reported = [], set()
    for item in medications:
        name = item["name"]
        if counts[name] > 1 and name not in reported:
            checks.append({"name": name, "status": "duplicate", "detail": "相同药名重复记录，请核对是否重复填写或实际重复使用；未核实成分，不据此认定过量。"})
            reported.add(name)
        if item.get("response") == "worsened":
            checks.append({"name": name, "status": "reported_reaction", "detail": "你自报用药期间症状加重，请向医生或药师说明时间与症状；这不能确定药物导致了反应。"})
        missing = [label for key, label in (("dose", "实际剂量"), ("frequency", "频次"), ("started_at", "开始日期")) if not item.get(key)]
        if missing:
            checks.append({"name": name, "status": "review", "detail": "请补充" + "、".join(missing) + "，用于就医核对；系统不据此计算剂量或检查成分相互作用。"})
    if any(item.get("question_id") == "medication_reaction" and item.get("answer") == "yes" for item in episode.get("assessment_answers", [])):
        checks.append({"name": "尚未指定对应药品", "status": "reported_reaction", "detail": "补问自报用药期间出现新的明显不适，请补充对应药名与发生时间；不能归因到清单中的任一药品。"})
    return checks


def build_assessment(episode: dict, analysis: dict, context: dict, knowledge: list[dict]) -> dict:
    answers = {item["question_id"]: item["answer"] for item in episode.get("assessment_answers", [])}
    names = symptom_set(episode)
    description = " ".join((episode.get("chief_complaint", ""), episode.get("notes", "")))
    respiratory = bool(names & {"咳嗽", "咽痛", "发热", "流鼻涕", "呼吸困难"}) or any(term in description for term in ("咳嗽", "咽痛", "呼吸困难")) or episode.get("infection_group") == "respiratory"
    gastrointestinal = bool(names & {"腹泻", "呕吐", "腹痛"}) or any(term in description for term in ("腹泻", "呕吐", "腹痛")) or episode.get("infection_group") == "gastrointestinal"
    temperatures = [item["value"] for item in analysis.get("device_context", {}).get("readings", []) if item.get("metric") == "temperature"]
    if (episode.get("vitals") or {}).get("temperature") is not None:
        temperatures.append(episode["vitals"]["temperature"])
    fever = "发热" in names or "发热" in description or "发烧" in description or any(value >= 38 for value in temperatures)
    applicable = {"breathing_difficulty", "chest_pain", "confusion", "dehydration", "worsening"}
    if respiratory or gastrointestinal or episode.get("disease_category") == "infectious":
        applicable.add("exposure")
    if fever:
        applicable.add("fever_persistent")
    if fever or episode.get("medications"):
        applicable.add("pregnancy")
    if respiratory or gastrointestinal or episode.get("medications"):
        applicable.add("immunosuppression")
    if episode.get("medications"):
        applicable.add("medication_reaction")
    applicable.update(key for key in answers if key in QUESTION_BANK)
    questions = [{"id": key, "text": text, "reason": reason, "priority": priority,
                  "answer": answers.get(key), "options": deepcopy(OPTIONS)}
                 for key, (text, reason, priority) in QUESTION_BANK.items() if key in applicable]
    evidence, limitations = [], ["这是依据自报与设备记录整理的原型评估，不能确诊或替代医疗评估。",
                                 "未回答或不清楚表示资料不足，不代表没有症状；否定答案不能覆盖已明确记录的危险信号。",
                                 "趋势仅展示本次病程最近 7 个北京时间日内的有限读数；最多 14 个日点，不补造缺失数据。"]
    evidence.append({"id": "course:current", "kind": "course", "label": "本次病程阶段与变化",
                     "value": {"duration_days": analysis.get("duration_days"), "status": episode.get("status"), "outcome": episode.get("outcome")},
                     "state": "present", "source": "本次病程记录"})
    for index, medication in enumerate(episode.get("medications", [])):
        evidence.append({"id": f"medication:{index}", "kind": "medication", "label": "本次自报用药与变化",
                         "value": {key: medication.get(key) for key in ("name", "started_at", "response", "adherence")},
                         "state": "present", "source": "本次用药自报（不能判断疗效或药物因果）"})
    for index, name in enumerate(episode.get("symptoms", [])):
        evidence.append({"id": f"symptom:{index}", "kind": "symptom", "label": "明确记录的症状", "value": name, "state": "present", "source": "本次病程自报"})
    if any(term in description for term in DANGER_TERMS):
        evidence.append({"id": "danger:free_text", "kind": "mention", "label": "文字中的危险信号提及", "value": "需确认是否为本次正在发生的症状", "state": "unknown", "source": "本次主要不适或备注"})
    for question in questions:
        key, answer = question["id"], question["answer"]
        asserted = any(term in symptom for term in QUESTION_SYMPTOMS.get(key, set()) for symptom in names)
        asserted = asserted or (key == "worsening" and episode.get("outcome") == "worsened")
        asserted = asserted or (key == "medication_reaction" and any(med.get("response") == "worsened" for med in episode.get("medications", [])))
        conflict = answer == "no" and asserted
        state = "conflicting" if conflict else {"yes": "present", "no": "absent"}.get(answer, "unknown")
        evidence.append({"id": f"answer:{key}", "kind": "answer", "label": question["text"],
                         "value": answer if answer is not None else "未回答", "state": state, "source": "本次结构化补问"})
        if conflict:
            limitations.append(question["text"] + "：否定答案与已有明确记录冲突，请核对；本次保留较高优先级。")
    for metric, value in (episode.get("vitals") or {}).items():
        if metric in METRICS and value is not None:
            evidence.append({"id": f"vital:{metric}", "kind": "vital", "label": f"{METRICS[metric][0]}（{METRICS[metric][1]}）", "value": value, "state": "present", "source": "本次病程手动填写（未提供测量时刻）"})
    monitoring, points = _monitoring(episode, analysis, context)
    for _, at, item in points:
        evidence.append({"id": "observation:" + str(item.get("id") or item.get("source_id")), "kind": "observation",
                         "label": f"{METRICS[item['metric']][0]}（{METRICS[item['metric']][1]}）" + (" · 静息" if item["metric"] == "heart_rate" and item.get("context") == "resting" else " · 非静息或场景未知" if item["metric"] == "heart_rate" else ""),
                         "value": item["value"], "state": "present",
                         "source": item.get("source", "unknown"), "measured_at": at.isoformat()})
    profile = context.get("profile") or {}
    for key, label in (("chronic_conditions", "已记录基础病"), ("family_history", "已记录家族史")):
        if profile.get(key):
            evidence.append({"id": "profile:" + key, "kind": "profile", "label": label, "value": profile[key], "state": "present", "source": "健康档案自报"})
    references = []
    for item in knowledge[:5]:
        text = str(item.get("excerpt", item.get("summary", "")))
        references.append({key: item.get(key, "") for key in ("id", "title", "source_url", "source", "published_at", "imported_at")}
                          | {"excerpt": text[:1200], "matched_terms": list(item.get("matched_terms") or [])})
        if len(text) > 1200:
            limitations.append("知识条目「" + str(item.get("title", "")) + "」展示片段已截取，请查看官方原文。")
    if not references:
        limitations.append("本地知识库暂无直接匹配资料，不能由模型补造引用。")
    return {"rule_version": analysis.get("rule_version", RULE_VERSION), "episode_version": episode.get("version", 1),
            "generated_at": (_when(context.get("_assessment_now")) or datetime.now(timezone.utc)).isoformat(),
            "triage": deepcopy({key: analysis[key] for key in ("level", "label", "summary", "action_plan", "reasons")}),
            "questions": questions, "evidence": evidence, "knowledge": references, "limitations": limitations,
            "monitoring": monitoring, "medication_checks": _medication_checks(episode)}
