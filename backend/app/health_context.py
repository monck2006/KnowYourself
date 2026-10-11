"""Private health profiles, source-labelled observations and coarse regional signals."""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
import math
import re
from statistics import median
from uuid import uuid4

from .db import connect


BEIJING = timezone(timedelta(hours=8))
METRICS = {"heart_rate": "bpm", "spo2": "%", "temperature": "C", "steps": "count", "sleep_minutes": "min",
           "dietary_energy": "kcal", "hydration": "ml", "active_energy": "kcal", "basal_energy": "kcal",
           "hrv_sdnn": "ms", "hrv_rmssd": "ms", "vo2max": "mL/kg/min",
           "distance_run": "m", "distance_cycle": "m", "exercise_minutes": "min"}
SOURCES = {"health_connect", "healthkit", "bluetooth", "manual"}
CONTEXTS = {"resting", "active", "unknown"}
REGIONAL_NOTICE = (
    "区域提示仅统计自愿参与者的自报症状组合，每组至少 5 位不同用户后才显示人数档位；"
    "不代表人口患病率，不能确认流行、诊断或排除疾病。撤回同意后立即停止参与。"
)
DDL = (
    """CREATE TABLE IF NOT EXISTS health_profiles (
        user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        version INTEGER NOT NULL, content_json TEXT NOT NULL, updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS observations (
        id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        source TEXT NOT NULL, source_id TEXT NOT NULL, metric TEXT NOT NULL,
        value DOUBLE PRECISION NOT NULL, unit TEXT NOT NULL, measured_at TEXT NOT NULL,
        context TEXT NOT NULL, device_name TEXT NOT NULL,
        UNIQUE(user_id,source,source_id,metric)
    )""",
    "CREATE INDEX IF NOT EXISTS observations_user_time_idx ON observations(user_id,measured_at DESC)",
    "CREATE INDEX IF NOT EXISTS observations_baseline_idx ON observations(user_id,context,measured_at,metric)",
)


class HealthError(Exception):
    def __init__(self, status_code, detail):
        super().__init__(detail)
        self.status_code, self.detail = status_code, detail


def _now():
    return datetime.now(timezone.utc)


def _iso(value):
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def initialize_health(database_path):
    connection = connect(database_path)
    try:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            for statement in DDL:
                connection.execute(statement)
    finally:
        connection.close()


def _empty_region():
    return {"province": "", "city": "", "district": "", "code": "", "label": ""}


def _default_profile():
    return {"version": 0, "birth_year": None, "chronic_conditions": [], "family_history": [],
            "region": _empty_region(), "regional_consent": False, "updated_at": ""}


def _region_part(value):
    if not isinstance(value, str) or len(value) > 60 or any(character in value for character in "/:\x00\r\n"):
        raise HealthError(422, "行政区域文字无效")
    return " ".join(value.split())


def normalize_region(region):
    if not isinstance(region, dict):
        raise HealthError(422, "区域格式无效")
    parts = {key: _region_part(region.get(key, "")) for key in ("province", "city", "district")}
    code = region.get("code", "")
    if not isinstance(code, str):
        raise HealthError(422, "区域代码无效")
    if code.startswith("grid:"):
        match = re.fullmatch(r"grid:(-?\d{1,4}):(-?\d{1,4})", code)
        if not match:
            raise HealthError(422, "只接受约 10 公里的整数位置网格")
        latitude, longitude = map(int, match.groups())
        if not -900 <= latitude <= 900 or not -1800 <= longitude <= 1800:
            raise HealthError(422, "位置网格超出范围")
        return parts | {"code": f"grid:{latitude}:{longitude}", "label": f"约10公里网格 {latitude}:{longitude}"}
    if not any(parts.values()) and code.startswith("area:"):
        values = code[5:].split("/")
        if len(values) != 3:
            raise HealthError(422, "行政区域代码无效")
        parts = {key: _region_part(value) for key, value in zip(parts, values)}
    elif code and not code.startswith("area:"):
        raise HealthError(422, "区域代码无效")
    if not any(parts.values()):
        return _empty_region()
    if not parts["province"] or not parts["city"]:
        raise HealthError(422, "请填写省份和城市")
    return parts | {"code": "area:" + "/".join(parts.values()), "label": " · ".join(value for value in parts.values() if value)}


def get_profile(db, user_id):
    row = db.execute("SELECT version,content_json,updated_at FROM health_profiles WHERE user_id=?", (user_id,)).fetchone()
    if row is None:
        return _default_profile()
    return json.loads(row["content_json"]) | {"version": row["version"], "updated_at": row["updated_at"]}


def _condition_list(values):
    if not isinstance(values, list) or len(values) > 50 or any(not isinstance(value, str) or not value.strip() or len(value) > 100 for value in values):
        raise HealthError(422, "健康档案条目无效")
    return list(dict.fromkeys(value.strip() for value in values))


def save_profile(db, user_id, data):
    expected = data.get("version")
    if type(expected) is not int or expected < 0:
        raise HealthError(422, "档案版本无效")
    birth_year = data.get("birth_year")
    current_year = _now().astimezone(BEIJING).year
    if birth_year is not None and (type(birth_year) is not int or not current_year - 130 <= birth_year <= current_year):
        raise HealthError(422, "出生年份无效")
    consent = data.get("regional_consent", False)
    if type(consent) is not bool:
        raise HealthError(422, "区域统计同意选项无效")
    content = {"birth_year": birth_year, "chronic_conditions": _condition_list(data.get("chronic_conditions", [])),
               "family_history": _condition_list(data.get("family_history", [])),
               "region": normalize_region(data.get("region", {})), "regional_consent": consent}
    with db:
        db.execute("BEGIN IMMEDIATE")
        current = get_profile(db, user_id)
        if current["version"] != expected:
            raise HealthError(409, "健康档案已在另一端修改，请刷新后重试")
        if db.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone() is None:
            raise HealthError(401, "登录已失效，请重新登录")
        version, updated_at = expected + 1, _iso(_now())
        encoded = json.dumps(content, ensure_ascii=False, allow_nan=False)
        if expected == 0:
            db.execute("INSERT INTO health_profiles(user_id,version,content_json,updated_at) VALUES(?,?,?,?)", (user_id, version, encoded, updated_at))
        else:
            changed = db.execute("UPDATE health_profiles SET version=?,content_json=?,updated_at=? WHERE user_id=? AND version=?",
                                 (version, encoded, updated_at, user_id, expected))
            if changed.rowcount != 1:
                raise HealthError(409, "健康档案已在另一端修改，请刷新后重试")
    return content | {"version": version, "updated_at": updated_at}


def _observation(item):
    required = {"source", "source_id", "metric", "value", "unit", "measured_at", "context", "device_name"}
    if not isinstance(item, dict) or set(item) != required:
        raise HealthError(422, "设备观察字段无效")
    result = dict(item)
    if item["source"] not in SOURCES or item["metric"] not in METRICS or item["unit"] != METRICS[item["metric"]] or item["context"] not in CONTEXTS:
        raise HealthError(422, "设备观察来源、指标或单位无效")
    if type(item["value"]) not in (int, float) or not math.isfinite(item["value"]):
        raise HealthError(422, "设备观察必须为有限数值")
    for key, maximum in (("source_id", 200), ("device_name", 100)):
        if not isinstance(item[key], str) or len(item[key]) > maximum or "\x00" in item[key] or (key == "source_id" and not item[key].strip()):
            raise HealthError(422, "设备观察来源标识无效")
        result[key] = item[key].strip()
    try:
        measured = item["measured_at"] if isinstance(item["measured_at"], datetime) else datetime.fromisoformat(item["measured_at"].replace("Z", "+00:00"))
        if measured.tzinfo is None or measured.utcoffset() is None:
            raise ValueError("timezone required")
    except (ValueError, AttributeError, TypeError):
        raise HealthError(422, "设备观察时间须包含时区") from None
    if measured > _now() + timedelta(minutes=5):
        raise HealthError(422, "设备观察时间不能晚于当前时间")
    result["measured_at"] = _iso(measured)
    return result


def import_observations(db, user_id, items):
    if not isinstance(items, list) or len(items) > 1000:
        raise HealthError(422, "单次最多导入 1000 条设备观察")
    normalized = [_observation(item) for item in items]
    inserted = duplicates = 0
    with db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone() is None:
            raise HealthError(401, "登录已失效，请重新登录")
        for item in normalized:
            existing = db.execute("SELECT * FROM observations WHERE user_id=? AND source=? AND source_id=? AND metric=?",
                                  (user_id, item["source"], item["source_id"], item["metric"])).fetchone()
            if existing is not None:
                if any(existing[key] != value for key, value in item.items()):
                    raise HealthError(409, "相同来源标识已有不同观察内容，请核对后重试")
                duplicates += 1
                continue
            db.execute("""INSERT INTO observations(id,user_id,source,source_id,metric,value,unit,measured_at,context,device_name)
                          VALUES(?,?,?,?,?,?,?,?,?,?)""", (str(uuid4()), user_id, *(item[key] for key in
                              ("source", "source_id", "metric", "value", "unit", "measured_at", "context", "device_name"))))
            inserted += 1
    return {"inserted": inserted, "duplicates": duplicates}


def _percentile(values, fraction):
    values = sorted(values)
    index = (len(values) - 1) * fraction
    left, right = math.floor(index), math.ceil(index)
    return values[left] + (values[right] - values[left]) * (index - left)


def get_observations(db, user_id, limit=200, days=30, ids=None):
    if type(limit) is not int or not 1 <= limit <= 500 or type(days) is not int or not 1 <= days <= 365:
        raise HealthError(422, "观察查询范围无效")
    now = _now()
    lower, upper = _iso(now - timedelta(days=days)), _iso(now)
    parameters = (user_id, lower, upper)
    where = "user_id=? AND measured_at>=? AND measured_at<=?"
    if ids is not None:
        if not isinstance(ids, list) or len(ids) > 500 or any(not isinstance(identifier, str) or len(identifier) > 100 for identifier in ids):
            raise HealthError(422, "观察 ID 列表无效")
        if ids:
            where += " AND id IN (" + ",".join("?" for _ in ids) + ")"
            parameters += tuple(ids)
        else:
            where += " AND 1=0"
    total = db.execute("SELECT COUNT(*) FROM observations WHERE " + where, parameters).fetchone()[0]
    rows = db.execute("SELECT * FROM observations WHERE " + where + " ORDER BY measured_at DESC,id LIMIT ?", (*parameters, limit)).fetchall()
    items = [{key: row[key] for key in ("id", "source", "source_id", "metric", "value", "unit", "measured_at", "context", "device_name")} for row in rows]
    latest = {}
    for metric in METRICS:
        row = db.execute("SELECT * FROM observations WHERE " + where + " AND metric=? ORDER BY measured_at DESC,id LIMIT 1", (*parameters, metric)).fetchone()
        if row:
            latest[metric] = {key: row[key] for key in ("id", "source", "source_id", "metric", "value", "unit", "measured_at", "context", "device_name")}
    grouped = defaultdict(lambda: defaultdict(list))
    resting = db.execute("""SELECT metric,value,measured_at FROM observations
        WHERE user_id=? AND context='resting' AND measured_at>=? AND measured_at<=?""", (user_id, _iso(now - timedelta(days=30)), upper))
    for row in resting:
        day = datetime.fromisoformat(row["measured_at"]).astimezone(BEIJING).date().isoformat()
        grouped[row["metric"]][day].append(row["value"])
    baseline = {}
    for metric, unit in METRICS.items():
        daily = [median(values) for values in grouped[metric].values()]
        enough = len(daily) >= 3
        baseline[metric] = {"sample_count": len(daily), "reading_count": sum(map(len, grouped[metric].values())), "unit": unit,
                            "median": median(daily) if enough else None,
                            "p10": round(_percentile(daily, .1), 2) if enough else None,
                            "p90": round(_percentile(daily, .9), 2) if enough else None}
    return {"items": items, "total": total, "limit": limit, "days": days, "baseline_days": 30,
            "baseline": baseline, "latest": latest,
            "notice": "观察保留手动与设备来源；静息基线仅描述最近30天、至少3个不同日期的日中位数，不是诊断阈值。"}


def _clusters(episode):
    aliases = {"流涕": "流鼻涕", "喉咙痛": "咽痛", "嗓子痛": "咽痛", "发烧": "发热", "拉肚子": "腹泻"}
    symptoms = {aliases.get(value, value) for value in episode.get("symptoms", []) if isinstance(value, str)}
    result = set()
    infectious = episode.get("disease_category") == "infectious"
    if len(symptoms & {"咳嗽", "咽痛", "发热", "流鼻涕"}) >= 2 or (infectious and episode.get("infection_group") == "respiratory"):
        result.add("respiratory")
    if len(symptoms & {"腹泻", "呕吐", "腹痛"}) >= 2 or (infectious and episode.get("infection_group") == "gastrointestinal"):
        result.add("gastrointestinal")
    return result


def region_summary(db, user_id):
    profile = get_profile(db, user_id)
    region = profile["region"]
    enabled = bool(profile["regional_consent"] and region["code"])
    result = {"enabled": enabled, "region_label": region["label"], "status": "insufficient" if enabled else "disabled",
              "window_days": 7, "signals": [], "notice": REGIONAL_NOTICE}
    if not enabled:
        return result
    participants = set()
    for row in db.execute("SELECT user_id,content_json FROM health_profiles"):
        content = json.loads(row["content_json"])
        if content.get("regional_consent") is True and content.get("region", {}).get("code") == region["code"]:
            participants.add(row["user_id"])
    today = _now().astimezone(BEIJING).date()
    first_day, previous_day = today - timedelta(days=6), today - timedelta(days=13)
    groups = {"current": defaultdict(set), "previous": defaultdict(set)}
    for row in db.execute("SELECT user_id,started_at,content_json FROM episodes WHERE started_at>=? AND started_at<=?", (previous_day.isoformat(), today.isoformat())):
        if row["user_id"] not in participants:
            continue
        window = "current" if row["started_at"] >= first_day.isoformat() else "previous"
        for cluster in _clusters(json.loads(row["content_json"])):
            groups[window][cluster].add(row["user_id"])
    for cluster, label in (("respiratory", "呼吸道症状组合"), ("gastrointestinal", "胃肠道症状组合")):
        current, previous = len(groups["current"][cluster]), len(groups["previous"][cluster])
        if current < 5:
            continue
        trend = "increased" if previous >= 5 and current >= previous * 1.5 else "stable" if previous >= 5 else "unknown"
        band = "5–9" if current < 10 else "10–19" if current < 20 else "20+"
        result["signals"].append({"cluster": cluster, "label": label, "level": "elevated" if trend == "increased" else "present",
                                  "people_band": band, "trend": trend,
                                  "description": f"近7天同一区域有 {band} 位自愿参与者记录了这组症状；仅反映自报记录，不能据此确诊感染或流行。"})
    if result["signals"]:
        result["status"] = "available"
    return result


def get_health_context(db, user_id):
    return {"profile": get_profile(db, user_id), "observations": get_observations(db, user_id, limit=500), "region": region_summary(db, user_id)}
