"""Read-only official FDA labels, with bounded requests and a shared SQLite cache.

Only an explicitly entered drug keyword is transmitted. This module never accepts
an episode or generates prescribing/dose recommendations.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import re
import sqlite3
import threading
import time
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import UUID


API_URL = "https://api.fda.gov/drug/label.json"
SOURCE = "美国 FDA · openFDA"
FRESH_SECONDS = 24 * 60 * 60
STALE_SECONDS = 7 * 24 * 60 * 60
MAX_CACHE_ENTRIES = 200
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
MAX_SECTION_CHARS = 6000
REQUESTS_PER_MINUTE = 30
_LOOKUP_LOCK = threading.RLock()

# Explicit ingredient aliases only; never infer an ingredient from a symptom or
# Chinese brand name. English labels describe US products and formulations.
CHINESE_ALIASES = {
    "对乙酰氨基酚": "acetaminophen",
    "扑热息痛": "acetaminophen",
    "布洛芬": "ibuprofen",
    "阿司匹林": "aspirin",
    "阿莫西林": "amoxicillin",
    "氯雷他定": "loratadine",
    "西替利嗪": "cetirizine",
    "奥美拉唑": "omeprazole",
    "二甲双胍": "metformin",
    "阿托伐他汀": "atorvastatin",
    "氯沙坦": "losartan",
    "赖诺普利": "lisinopril",
    "阿奇霉素": "azithromycin",
    "多西环素": "doxycycline",
    "氨氯地平": "amlodipine",
    "孟鲁司特": "montelukast",
}

SECTIONS = (
    ("indications_and_usage", "适应证（官方英文原文）"),
    ("warnings", "警告（官方英文原文）"),
    ("boxed_warning", "黑框警告（官方英文原文）"),
    ("contraindications", "禁忌（官方英文原文）"),
    ("drug_interactions", "药物相互作用（官方英文原文）"),
    ("adverse_reactions", "不良反应（官方英文原文）"),
)


class DrugLookupError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _now() -> float:
    return time.time()


def _normalize_query(query: str) -> str:
    if not isinstance(query, str) or not 2 <= len(query.strip()) <= 80:
        raise DrugLookupError(422, "请输入 2–80 个字符的药品通用名或英文商品名。")
    query = " ".join(unicodedata.normalize("NFKC", query).strip().split())
    if query in CHINESE_ALIASES:
        return CHINESE_ALIASES[query]
    if re.search(r"[\u3400-\u9fff]", query):
        raise DrugLookupError(422, "暂不支持该中文名称，请输入准确的英文通用名（例如 ibuprofen）；不会猜测药品成分。")
    # Quotes, colons, wildcard characters, brackets and other query-language
    # syntax are forbidden. The entire term is also quoted in the FDA query.
    if not re.fullmatch(r"[A-Za-z0-9]+(?:[ -][A-Za-z0-9]+)*", query) or len(query.split()) > 8:
        raise DrugLookupError(422, "英文药品名称仅支持字母、数字、空格和单词间的连字符，最多 8 个词。")
    if not re.search(r"[A-Za-z]", query):
        raise DrugLookupError(422, "请输入药品英文通用名或英文商品名。")
    return query.lower()


def _query_url(query: str, api_key: str = "") -> str:
    params = {
        "search": f'(openfda.generic_name:"{query}" OR openfda.brand_name:"{query}")',
        "limit": "5",
    }
    if api_key:
        params["api_key"] = api_key
    return API_URL + "?" + urlencode(params)


def _fetch_labels(query: str, api_key: str = "") -> dict:
    request = Request(_query_url(query, api_key), headers={
        "Accept": "application/json", "User-Agent": "KnowYourself-OfficialDrugLookup/1.0",
    })
    try:
        with urlopen(request, timeout=8) as response:
            length = response.headers.get("Content-Length")
            if length and (not length.isdigit() or int(length) > MAX_RESPONSE_BYTES):
                raise DrugLookupError(502, "官方药品数据响应过大，请使用更具体的药品名称。")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise DrugLookupError(502, "官方药品数据响应过大，请使用更具体的药品名称。")
        result = json.loads(raw)
        if not isinstance(result, dict) or not isinstance(result.get("results"), list):
            raise DrugLookupError(502, "官方药品数据格式异常，请稍后重试。")
        return result
    except HTTPError as exc:
        if exc.code == 404:
            return {"results": [], "meta": {"results": {"total": 0}}}
        if exc.code == 429:
            raise DrugLookupError(503, "官方药品数据库访问额度暂时受限，请稍后重试。") from None
        raise DrugLookupError(503, "官方药品数据库暂时不可用，请稍后重试。") from None
    except (URLError, TimeoutError, OSError):
        raise DrugLookupError(503, "无法连接官方药品数据库，请检查网络后重试。") from None
    except (UnicodeError, ValueError):
        raise DrugLookupError(502, "官方药品数据格式异常，请稍后重试。") from None


@contextmanager
def _database(path: Path):
    connection = None
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(path), timeout=5)
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("""CREATE TABLE IF NOT EXISTS drug_cache (
            query TEXT PRIMARY KEY, payload_json TEXT NOT NULL, fetched_at REAL NOT NULL
        )""")
        connection.execute("CREATE TABLE IF NOT EXISTS drug_request_log (requested_at REAL NOT NULL)")
        yield connection
        connection.commit()
    except (sqlite3.Error, OSError):
        if connection is not None:
            connection.rollback()
        raise DrugLookupError(503, "本地药品缓存暂时不可用，请稍后重试。") from None
    finally:
        if connection is not None:
            connection.close()


def _read_cache(path: Path, query: str, now: float):
    with _database(path) as connection:
        row = connection.execute("SELECT payload_json, fetched_at FROM drug_cache WHERE query = ?", (query,)).fetchone()
        if row and 0 <= now - row[1] <= STALE_SECONDS:
            try:
                payload = json.loads(row[0])
                if (isinstance(payload, dict) and isinstance(payload.get("items"), list)
                        and isinstance(payload.get("notice"), str)
                        and isinstance(payload.get("fetched_at"), str)
                        and payload.get("source") == SOURCE
                        and payload.get("normalized_query") == query
                        and isinstance(payload.get("total"), int)
                        and isinstance(payload.get("source_url"), str)
                        and isinstance(payload.get("last_updated"), str)):
                    return payload, row[1]
            except (ValueError, TypeError):
                pass
        if row:
            connection.execute("DELETE FROM drug_cache WHERE query = ?", (query,))
    return None


def _reserve_request(path: Path, now: float) -> None:
    # BEGIN IMMEDIATE makes the limit atomic across workers/processes sharing
    # this database, without holding a DB transaction during network I/O.
    with _database(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("DELETE FROM drug_request_log WHERE requested_at <= ?", (now - 60,))
        count = connection.execute("SELECT COUNT(*) FROM drug_request_log").fetchone()[0]
        if count >= REQUESTS_PER_MINUTE:
            raise DrugLookupError(429, "药品查询较频繁，请在一分钟后重试。")
        connection.execute("INSERT INTO drug_request_log(requested_at) VALUES (?)", (now,))


def _write_cache(path: Path, query: str, payload: dict, now: float) -> None:
    with _database(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("INSERT OR REPLACE INTO drug_cache(query, payload_json, fetched_at) VALUES (?, ?, ?)",
                           (query, json.dumps(payload, ensure_ascii=False), now))
        connection.execute("DELETE FROM drug_cache WHERE fetched_at < ?", (now - STALE_SECONDS,))
        connection.execute("""DELETE FROM drug_cache WHERE query NOT IN (
            SELECT query FROM drug_cache ORDER BY fetched_at DESC, query LIMIT ?
        )""", (MAX_CACHE_ENTRIES,))


def _plain_text(value: str) -> str:
    value = re.sub(r"<script\b[^>]*>.*?</script\s*>", "", value, flags=re.IGNORECASE | re.DOTALL)
    value = re.sub(r"<[^>]*>", " ", value)
    value = html.unescape(value)
    return " ".join(value.replace("\x00", "").split())


def _strings(value) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(_plain_text(item)[:500] for item in value[:20]
                             if isinstance(item, str) and item.strip()))


def _date(value) -> str:
    if not isinstance(value, str):
        return ""
    for pattern in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, pattern).date().isoformat()
        except ValueError:
            pass
    return ""


def _prepare_payload(raw: dict, query: str, now: float) -> dict:
    items, truncated = [], False
    official_url = _query_url(query)  # Never put the API key in data or links.
    for record in raw.get("results", [])[:5]:
        if not isinstance(record, dict):
            continue
        openfda = record.get("openfda")
        if not isinstance(openfda, dict):
            openfda = {}
        source_url = official_url
        try:
            set_id = str(UUID(str(record.get("set_id", ""))))
            source_url = f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={set_id}"
        except (ValueError, AttributeError):
            pass
        sections = []
        for key, title in SECTIONS:
            value = record.get(key, [])
            if isinstance(value, str):
                value = [value]
            if not isinstance(value, list):
                continue
            text = _plain_text("\n".join(part for part in value if isinstance(part, str)))
            if not text:
                continue
            if len(text) > MAX_SECTION_CHARS:
                truncated = True
                text = text[:MAX_SECTION_CHARS] + " … [原文已截断，请查看官方完整标签]"
            sections.append({"key": key, "title": title, "text": text})
        record_id = record.get("id")
        if not isinstance(record_id, str) or not record_id:
            record_id = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()[:24]
        items.append({
            "id": record_id[:200],
            "brand_names": _strings(openfda.get("brand_name")),
            "generic_names": _strings(openfda.get("generic_name")),
            "manufacturer_names": _strings(openfda.get("manufacturer_name")),
            "product_ndcs": _strings(openfda.get("product_ndc")),
            "effective_date": _date(record.get("effective_time")),
            "source_url": source_url,
            "sections": sections,
        })
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    result_meta = meta.get("results") if isinstance(meta.get("results"), dict) else {}
    total = result_meta.get("total")
    if not isinstance(total, int) or isinstance(total, bool) or total < len(items):
        total = len(items)
    notice = "美国 FDA 药品标签英文原文，仅供查阅；适用产品和批准范围可能与中国不同。未列出某项内容不代表不存在相关风险，请核对完整官方标签。"
    if not items:
        notice += " 未找到匹配标签，请核对英文通用名；无结果不代表该药品安全或未获其他地区批准。"
    if truncated:
        notice += " 部分原文已截断，请通过官方链接查看完整内容。"
    return {
        "items": items, "normalized_query": query, "source": SOURCE,
        "source_url": official_url, "last_updated": _date(meta.get("last_updated")),
        "fetched_at": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
        "stale": False, "cached": False, "notice": notice, "total": total,
    }


def search_drugs(query: str, database_path: Path, api_key: str = "", enabled: bool = True) -> dict:
    normalized = _normalize_query(query)
    with _LOOKUP_LOCK:
        now = _now()
        cached = _read_cache(database_path, normalized, now)
        if cached and (now - cached[1] < FRESH_SECONDS or not enabled):
            payload = dict(cached[0], query=query.strip(), cached=True,
                           stale=now - cached[1] >= FRESH_SECONDS)
            if not enabled:
                payload["notice"] += " 在线查询已关闭，当前展示本地缓存。"
            if payload["stale"]:
                payload["notice"] += " 缓存已超过 24 小时，可能落后于官方最新标签。"
            return payload
        if not enabled:
            raise DrugLookupError(503, "在线药品查询已关闭，且没有七天内可用的缓存。")
        try:
            _reserve_request(database_path, now)
            raw = _fetch_labels(normalized, api_key)
            payload = _prepare_payload(raw, normalized, now)
            _write_cache(database_path, normalized, payload, now)
            return dict(payload, query=query.strip())
        except DrugLookupError:
            if cached:
                return dict(cached[0], query=query.strip(), cached=True, stale=True,
                            notice=cached[0]["notice"] + " 在线更新失败，展示七天内的旧缓存，可能落后于官方最新标签。")
            raise
