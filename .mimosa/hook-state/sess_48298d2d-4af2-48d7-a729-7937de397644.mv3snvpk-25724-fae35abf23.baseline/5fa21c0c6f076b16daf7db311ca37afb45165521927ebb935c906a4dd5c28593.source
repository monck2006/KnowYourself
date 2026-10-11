"""Local, source-attributed MedlinePlus topics; never reads personal records."""

from contextlib import closing
import json
from pathlib import Path
from urllib.parse import urlsplit

from .db import connect

SNAPSHOT = Path(__file__).with_name("resources") / "medlineplus-topics.json"
DOMESTIC_SNAPSHOT = Path(__file__).with_name("resources") / "domestic-topics.json"
SOURCE = "美国国家医学图书馆 · MedlinePlus"
SOURCE_URL = "https://medlineplus.gov/xml.html"
DIRECTORIES = [
    {"name": "脑启 · 官方数据平台", "url": "https://naoqi-data.nanhubrain.cn/#/home",
     "description": "参赛平台数据目录，需要脑启账号登录；本地导入状态与样本见“参赛数据”。"},
    {"name": "国家药品监督管理局 · 数据查询", "url": "https://www.nmpa.gov.cn/datasearch/home-index.html",
     "description": "国内药品批准信息官方查询；当前提供外链入口，未批量导入。"},
    {"name": "国家卫生健康委员会", "url": "https://www.nhc.gov.cn/",
     "description": "国内卫生健康政策、诊疗文件和健康科普官方入口；未批量导入。"},
    {"name": "中国疾病预防控制中心", "url": "https://www.chinacdc.cn/",
     "description": "已导入 4 篇中文科普文字；更多防控与健康科普可到官方入口查阅。"},
    {"name": "世界卫生组织 · 中文事实清单", "url": "https://www.who.int/zh/news-room/fact-sheets",
     "description": "WHO 中文疾病与公共卫生资料；当前提供官方原文入口。"},
]

# Application-maintained search aliases, not official translations or diagnoses.
ALIASES = {
    "High Blood Pressure": ["高血压", "血压高"], "Diabetes": ["糖尿病"],
    "Diabetes Type 1": ["1型糖尿病", "一型糖尿病"], "Diabetes Type 2": ["2型糖尿病", "二型糖尿病"],
    "Asthma": ["哮喘"], "Flu": ["流感", "流行性感冒"], "Common Cold": ["感冒", "普通感冒"],
    "Cough": ["咳嗽"], "Fever": ["发热", "发烧"], "Headache": ["头痛"],
    "Chest Pain": ["胸痛"], "Abdominal Pain": ["腹痛", "肚子痛"],
    "Back Pain": ["背痛", "腰痛"], "Diarrhea": ["腹泻", "拉肚子"],
    "Constipation": ["便秘"], "Nausea and Vomiting": ["恶心", "呕吐"],
    "Pneumonia": ["肺炎"], "Acute Bronchitis": ["急性支气管炎", "支气管炎"],
    "Chronic Bronchitis": ["慢性支气管炎"],
    "COVID-19 (Coronavirus Disease 2019)": ["新冠", "新型冠状病毒"],
    "Tuberculosis": ["结核病", "肺结核"], "Hepatitis B": ["乙肝", "乙型肝炎"],
    "Hepatitis C": ["丙肝", "丙型肝炎"], "HIV": ["艾滋病", "HIV感染"],
    "Stroke": ["卒中", "中风"], "Heart Attack": ["心肌梗死", "心梗"],
    "Heart Diseases": ["心脏病"], "Coronary Artery Disease": ["冠心病"],
    "Cholesterol": ["胆固醇", "高胆固醇", "血脂高"], "Obesity": ["肥胖"],
    "Allergy": ["过敏"], "Hay Fever": ["过敏性鼻炎", "花粉症"],
    "Eczema": ["湿疹"], "Acne": ["痤疮", "青春痘"], "Anemia": ["贫血"],
    "Depression": ["抑郁症"], "Anxiety": ["焦虑"], "Insomnia": ["失眠"],
    "Sleep Disorders": ["睡眠障碍"], "Migraine": ["偏头痛"],
    "Arthritis": ["关节炎"], "Gout": ["痛风"], "Osteoporosis": ["骨质疏松"],
    "Kidney Diseases": ["肾脏病"], "Kidney Stones": ["肾结石"],
    "Urinary Tract Infections": ["尿路感染"], "Gastroesophageal Reflux": ["胃食管反流"],
    "Stomach Disorders": ["胃病"], "Peptic Ulcer": ["消化性溃疡", "胃溃疡"],
    "Sore Throat": ["咽痛", "喉咙痛"], "Dizziness and Vertigo": ["头晕", "眩晕"],
    "Fatigue": ["疲劳", "乏力"], "Breathing Problems": ["呼吸困难"],
    "Dehydration": ["脱水"], "Dengue": ["登革热"], "Malaria": ["疟疾"],
    "Measles": ["麻疹"], "Chickenpox": ["水痘"], "Hand, Foot, and Mouth Disease": ["手足口病"],
}


def official_topic_url(value: str) -> bool:
    parsed = urlsplit(value)
    return parsed.scheme == "https" and parsed.netloc in {
        "medlineplus.gov", "www.nhc.gov.cn", "www.chinacdc.cn", "chinacdc.cn"
    } and not parsed.query and not parsed.fragment


def initialize_knowledge(path: Path, snapshot: Path = SNAPSHOT) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(path)) as db:
        db.execute("PRAGMA journal_mode = WAL")
        with db:
            db.execute("""CREATE TABLE IF NOT EXISTS knowledge_sources (
                source_key TEXT PRIMARY KEY, content_json TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS knowledge_topics (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, search_text TEXT NOT NULL, content_json TEXT NOT NULL,
                source_key TEXT NOT NULL DEFAULT 'medlineplus')""")
            if "source_key" not in {row[1] for row in db.execute("PRAGMA table_info(knowledge_topics)")}:
                db.execute("ALTER TABLE knowledge_topics ADD COLUMN source_key TEXT NOT NULL DEFAULT 'medlineplus'")
        current = metadata(db).get("datasets", {})
    for source_key, source_path in (("medlineplus", snapshot), ("domestic", DOMESTIC_SNAPSHOT)):
        if source_path.is_file():
            bundle = json.loads(source_path.read_bytes())
            # A later CLI synchronization must survive application restarts.
            if bundle["generated_at"] > current.get(source_key, {}).get("generated_at", ""):
                import_topics(path, bundle, source_key)


def metadata(db) -> dict:
    datasets = {row[0]: json.loads(row[1]) for row in db.execute("SELECT source_key,content_json FROM knowledge_sources")}
    return {"datasets": datasets, "count": sum(item["count"] for item in datasets.values()),
            "generated_at": max((item["generated_at"] for item in datasets.values()), default=""),
            "imported_at": max((item["imported_at"] for item in datasets.values()), default="")}


def import_topics(path: Path, bundle: dict, source_key: str = "medlineplus") -> int:
    topics = bundle.get("topics", [])
    if bundle.get("schema_version") != 1 or not topics or not bundle.get("generated_at") or not bundle.get("imported_at"):
        raise ValueError("官方主题快照缺少数据或版本信息")
    rows, ids = [], set()
    for topic in topics:
        valid_id = topic.get("id", "").isdigit() if source_key == "medlineplus" else topic.get("id", "").startswith(("nhc-", "cdc-"))
        if (not valid_id or topic["id"] in ids or not topic.get("title")
                or not isinstance(topic.get("summary"), str) or topic.get("language") not in {"English", "Chinese"}
                or not official_topic_url(topic.get("source_url", ""))):
            raise ValueError("官方主题快照含无效或重复条目")
        ids.add(topic["id"])
        aliases = ALIASES.get(topic["title"], []) if topic["language"] == "English" else []
        content = {"source": bundle["source"], "generated_at": bundle["generated_at"], "imported_at": bundle["imported_at"],
                   **topic, "aliases": aliases, "display_title": aliases[0] if aliases else topic["title"]}
        search_text = " ".join([topic["title"], *topic.get("synonyms", []), *aliases, *topic.get("groups", [])]).casefold()
        rows.append((topic["id"], topic["title"], search_text, json.dumps(content, ensure_ascii=False), source_key))
    meta = {key: value for key, value in bundle.items() if key != "topics"}
    meta["count"] = len(rows)
    meta["language"] = topics[0]["language"]
    # All validation precedes deletion; readers see either complete old or new snapshot.
    with closing(connect(path)) as db, db:
        db.execute("DELETE FROM knowledge_topics WHERE source_key=?", (source_key,))
        db.executemany("INSERT INTO knowledge_topics(id,title,search_text,content_json,source_key) VALUES(?,?,?,?,?)", rows)
        db.execute("INSERT OR REPLACE INTO knowledge_sources VALUES(?,?)", (source_key, json.dumps(meta, ensure_ascii=False)))
    return len(rows)


def knowledge_status(path: Path, drugs_enabled: bool) -> dict:
    with closing(connect(path)) as db:
        meta = metadata(db)
    return {
        "topics": {"source": "官方健康资料", "url": SOURCE_URL, "count": meta.get("count", 0),
                   "generated_at": meta.get("generated_at", ""), "imported_at": meta.get("imported_at", ""),
                   "language": "English / Chinese", "available": bool(meta["datasets"]),
                   "sources": [{k: value.get(k, "") for k in ("source", "source_url", "count", "generated_at", "imported_at", "language")}
                               for value in meta["datasets"].values()]},
        "drugs": {"source": "美国 FDA · openFDA", "url": "https://open.fda.gov/apis/drug/label/",
                  "available": drugs_enabled, "language": "English"},
        "directories": DIRECTORIES,
    }


def search_topics(path: Path, query: str, page: int, page_size: int) -> dict:
    terms = query.casefold().split()
    # Bound LIKE expressions; literal escaping prevents wildcards becoming a full scan query.
    if len(terms) > 8:
        raise ValueError("请使用不超过 8 个检索词")
    where = " AND ".join("search_text LIKE ? ESCAPE '\\'" for _ in terms) or "1=1"
    parameters = ["%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%" for term in terms]
    with closing(connect(path)) as db:
        # One read transaction keeps count, page and metadata on the same import version.
        db.execute("BEGIN")
        meta = metadata(db)
        total = db.execute(f"SELECT COUNT(*) FROM knowledge_topics WHERE {where}", parameters).fetchone()[0]
        rows = db.execute(f"SELECT content_json FROM knowledge_topics WHERE {where} ORDER BY title,id LIMIT ? OFFSET ?",
                          [*parameters, page_size, (page - 1) * page_size]).fetchall()
    items = [json.loads(row[0]) for row in rows]
    for item in items:
        item["summary"] = item["summary"][:260] + ("…" if len(item["summary"]) > 260 else "")
    return {"items": items, "total": total, "page": page, "page_size": page_size,
            "generated_at": meta.get("generated_at", ""), "imported_at": meta.get("imported_at", "")}


def get_topic(path: Path, topic_id: str) -> dict | None:
    with closing(connect(path)) as db:
        db.execute("BEGIN")
        row = db.execute("SELECT content_json FROM knowledge_topics WHERE id=?", (topic_id,)).fetchone()
        meta = metadata(db)
    if not row:
        return None
    return json.loads(row[0])
