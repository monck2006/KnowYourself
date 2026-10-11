"""Local, auditable import of authorized medical competition annotation data.

These samples are research annotations, not clinical guidance. Archives are read
in place, never extracted, and data replacement happens in one SQLite transaction.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import stat
import sys
import tempfile
import zipfile


MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
MAX_TEXT_LENGTH = 100_000
NOTICE = "竞赛标注训练资料，仅供本地科研与数据核验；不作为医学指南、诊断或个性化治疗建议。下载包未提供明确再分发许可，请勿据此再分发原始语料。"
ARCHIVE_ROOT = Path(__file__).resolve().parent.parent / "data" / "competition"
DATASETS = {
    "cmeie": {
        "name": "CMeIE 中文医学信息抽取",
        "source_url": "https://naoqi-data.nanhubrain.cn/#/data-detail/2",
        "members": {
            "CMeIE/", "CMeIE/CMeIE_train.jsonl", "CMeIE/CMeIE_dev.jsonl", "CMeIE/CMeIE_test.jsonl",
            "CMeIE/53_schemas.jsonl", "CMeIE/README.txt", "CMeIE/example_gold.jsonl", "CMeIE/example_pred.jsonl",
        },
        "required": {"CMeIE/CMeIE_train.jsonl", "CMeIE/CMeIE_dev.jsonl", "CMeIE/CMeIE_test.jsonl", "CMeIE/53_schemas.jsonl"},
    },
    "cmeee": {
        "name": "CMeEE-V2 中文医学实体识别",
        "source_url": "https://naoqi-data.nanhubrain.cn/#/data-detail/1",
        "members": {"CMeEE-V2/", "CMeEE-V2/CMeEE-V2_train.json", "CMeEE-V2/CMeEE-V2_dev.json",
                    "CMeEE-V2/CMeEE-V2_test.json", "CMeEE-V2/README.txt", "CMeEE-V2/example_pred.json",
                    "CMeEE-V2/标注规范参考.pdf"},
        "required": {"CMeEE-V2/CMeEE-V2_train.json", "CMeEE-V2/CMeEE-V2_dev.json", "CMeEE-V2/CMeEE-V2_test.json"},
    },
}
CMEEE_TYPES = {"dis", "sym", "dru", "bod", "pro", "mic", "equ", "ite", "dep"}
DDL = (
    """CREATE TABLE IF NOT EXISTS competition_datasets (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, source_url TEXT NOT NULL,
        imported_at TEXT NOT NULL, sha256 TEXT NOT NULL, sample_count INTEGER NOT NULL,
        split_counts TEXT NOT NULL, schema_count INTEGER NOT NULL, entity_count INTEGER NOT NULL,
        source_archive TEXT NOT NULL, notice TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS competition_samples (
        id TEXT PRIMARY KEY, dataset TEXT NOT NULL REFERENCES competition_datasets(id) ON DELETE CASCADE,
        split TEXT NOT NULL CHECK (split IN ('train','dev','test')), ordinal INTEGER NOT NULL,
        text TEXT NOT NULL, relations_json TEXT NOT NULL, entities_json TEXT NOT NULL,
        UNIQUE(dataset,split,ordinal)
    )""",
    "CREATE INDEX IF NOT EXISTS competition_samples_split_idx ON competition_samples(dataset,split,ordinal)",
    """CREATE TABLE IF NOT EXISTS competition_schemas (
        dataset TEXT NOT NULL REFERENCES competition_datasets(id) ON DELETE CASCADE,
        subject_type TEXT NOT NULL, predicate TEXT NOT NULL, object_type TEXT NOT NULL,
        PRIMARY KEY(dataset,subject_type,predicate,object_type)
    )""",
    "CREATE INDEX IF NOT EXISTS competition_schemas_predicate_idx ON competition_schemas(dataset,predicate)",
    """CREATE TABLE IF NOT EXISTS competition_entities (
        sample_id TEXT NOT NULL REFERENCES competition_samples(id) ON DELETE CASCADE,
        text TEXT NOT NULL, type TEXT NOT NULL, start INTEGER NOT NULL, end INTEGER NOT NULL,
        PRIMARY KEY(sample_id,start,end,type)
    )""",
    "CREATE INDEX IF NOT EXISTS competition_entities_text_idx ON competition_entities(text,type)",
    """CREATE TABLE IF NOT EXISTS competition_relations (
        sample_id TEXT NOT NULL REFERENCES competition_samples(id) ON DELETE CASCADE,
        ordinal INTEGER NOT NULL, predicate TEXT NOT NULL,
        PRIMARY KEY(sample_id,ordinal)
    )""",
    "CREATE INDEX IF NOT EXISTS competition_relations_predicate_idx ON competition_relations(predicate,sample_id)",
)


def _string(value, *, maximum=MAX_TEXT_LENGTH):
    if not isinstance(value, str) or not value or len(value) > maximum or "\x00" in value:
        raise ValueError("数据集包含无效文本字段")
    return value


def _jsonl(archive, name):
    with archive.open(name) as stream:
        for line_number, line in enumerate(stream, 1):
            if len(line) > MAX_ARCHIVE_BYTES:
                raise ValueError("数据集单行超过大小限制")
            if not line.strip():
                raise ValueError("JSONL 包含空记录")
            try:
                record = json.loads(line.decode("utf-8-sig"))
            except (ValueError, UnicodeError):
                raise ValueError(f"数据集 JSONL 第 {line_number} 行格式无效") from None
            if not isinstance(record, dict):
                raise ValueError("数据集记录必须是 JSON 对象")
            yield record


def _archive(path, dataset):
    path = Path(path).expanduser().resolve()
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_ARCHIVE_BYTES:
        raise ValueError("ZIP 不存在或超过 100 MB 大小限制")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    archive = zipfile.ZipFile(path)
    try:
        members = archive.infolist()
        names = []
        for entry in members:
            name = entry.filename
            if not entry.flag_bits & 0x800:
                try:
                    # Official CMeEE includes a UTF-8 PDF name without the ZIP flag.
                    name = name.encode("cp437").decode("utf-8")
                except (UnicodeError, LookupError):
                    pass
            names.append(name)
        specification = DATASETS[dataset]
        if len(names) != len(set(names)) or not set(names) <= specification["members"]:
            raise ValueError("ZIP 包含重复成员或未允许的路径")
        if not specification["required"] <= set(names):
            raise ValueError("ZIP 缺少必须的数据文件")
        if sum(entry.file_size for entry in members) > MAX_ARCHIVE_BYTES:
            raise ValueError("ZIP 解压后总大小超过 100 MB 限制")
        if any(entry.flag_bits & 1 or stat.S_ISLNK(entry.external_attr >> 16) for entry in members):
            raise ValueError("不支持加密 ZIP 或符号链接成员")
        return path, digest, archive
    except Exception:
        archive.close()
        raise


def parse_cmeie(path):
    source, digest, archive = _archive(path, "cmeie")
    with archive:
        schemas = []
        for row in _jsonl(archive, "CMeIE/53_schemas.jsonl"):
            if set(row) != {"subject_type", "predicate", "object_type"}:
                raise ValueError("CMeIE schema 字段无效")
            schemas.append(tuple(_string(row[key], maximum=200) for key in ("subject_type", "predicate", "object_type")))
        if not schemas or len(set(schemas)) != len(schemas):
            raise ValueError("CMeIE schema 为空或重复")
        schema_set, samples, counts, entity_count = set(schemas), [], {}, 0
        for split in ("train", "dev", "test"):
            count = 0
            for ordinal, row in enumerate(_jsonl(archive, f"CMeIE/CMeIE_{split}.jsonl"), 1):
                if set(row) != {"text", "spo_list"} or not isinstance(row["spo_list"], list):
                    raise ValueError("CMeIE 样本字段无效")
                text, relations, entities = _string(row["text"]), [], {}
                for relation in row["spo_list"]:
                    if not isinstance(relation, dict) or not {"subject", "predicate", "object", "subject_type", "object_type"} <= set(relation):
                        raise ValueError("CMeIE 关系标注字段无效")
                    if not set(relation) <= {"subject", "predicate", "object", "subject_type", "object_type", "Combined"}:
                        raise ValueError("CMeIE 关系标注包含未知字段")
                    if "Combined" in relation and not isinstance(relation["Combined"], bool):
                        raise ValueError("CMeIE Combined 标记无效")
                    obj, obj_type = relation["object"], relation["object_type"]
                    if not isinstance(obj, dict) or set(obj) != {"@value"} or not isinstance(obj_type, dict) or set(obj_type) != {"@value"}:
                        raise ValueError("CMeIE 客体标注字段无效")
                    normalized = {
                        "subject": _string(relation["subject"]), "predicate": _string(relation["predicate"], maximum=200),
                        "object": _string(obj["@value"]), "subject_type": _string(relation["subject_type"], maximum=200),
                        "object_type": _string(obj_type["@value"], maximum=200),
                    }
                    if (normalized["subject_type"], normalized["predicate"], normalized["object_type"]) not in schema_set:
                        raise ValueError("CMeIE 关系不符合 schema")
                    for value, kind in ((normalized["subject"], normalized["subject_type"]), (normalized["object"], normalized["object_type"])):
                        start = text.find(value)
                        if start < 0:
                            raise ValueError("CMeIE 标注实体无法在原文定位")
                        end = start + len(value)
                        entities[(start, end, kind)] = {"text": value, "type": kind, "start": start, "end": end}
                    relations.append(normalized)
                entity_list = list(entities.values())
                samples.append({"id": f"cmeie:{split}:{ordinal}", "dataset": "cmeie", "split": split,
                                "ordinal": ordinal, "text": text, "relations": relations, "entities": entity_list})
                entity_count += len(entity_list)
                count += 1
            counts[split] = count
        return {"id": "cmeie", "source": source, "sha256": digest, "samples": samples,
                "split_counts": counts, "schemas": schemas, "entity_count": entity_count}


def parse_cmeee(path):
    source, digest, archive = _archive(path, "cmeee")
    with archive:
        samples, counts, entity_count = [], {}, 0
        for split in ("train", "dev", "test"):
            try:
                rows = json.loads(archive.read(f"CMeEE-V2/CMeEE-V2_{split}.json").decode("utf-8-sig"))
            except (ValueError, UnicodeError):
                raise ValueError("CMeEE JSON 格式无效") from None
            if not isinstance(rows, list):
                raise ValueError("CMeEE 文件必须是 JSON 数组")
            for ordinal, row in enumerate(rows, 1):
                if not isinstance(row, dict) or set(row) != {"text", "entities"} or not isinstance(row["entities"], list):
                    raise ValueError("CMeEE 样本字段无效")
                text, entities, spans = _string(row["text"]), [], set()
                for entity in row["entities"]:
                    if not isinstance(entity, dict) or set(entity) != {"start_idx", "end_idx", "type", "entity"}:
                        raise ValueError("CMeEE 实体标注字段无效")
                    start, last, kind = entity["start_idx"], entity["end_idx"], entity["type"]
                    if type(start) is not int or type(last) is not int or not 0 <= start <= last < len(text):
                        raise ValueError("CMeEE 实体标注位置越界")
                    if not isinstance(kind, str) or kind not in CMEEE_TYPES or _string(entity["entity"]) != text[start:last + 1]:
                        raise ValueError("CMeEE 实体类型或标注文本不匹配")
                    if (start, last, kind) in spans:
                        raise ValueError("CMeEE 实体标注重复")
                    spans.add((start, last, kind))
                    entities.append({"text": entity["entity"], "type": kind, "start": start, "end": last + 1})
                samples.append({"id": f"cmeee:{split}:{ordinal}", "dataset": "cmeee", "split": split,
                                "ordinal": ordinal, "text": text, "relations": [], "entities": entities})
                entity_count += len(entities)
            counts[split] = len(rows)
        # CMeEE schemas are entity label types, without relation predicates.
        return {"id": "cmeee", "source": source, "sha256": digest, "samples": samples,
                "split_counts": counts, "schemas": [(kind, "", "") for kind in sorted(CMEEE_TYPES)], "entity_count": entity_count}


def _read_connection(path):
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        return None
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=15)
    connection.row_factory = sqlite3.Row
    if connection.execute("SELECT 1 FROM sqlite_master WHERE name='competition_datasets'").fetchone() is None:
        connection.close()
        return None
    return connection


def _status(connection):
    datasets = []
    if connection:
        for row in connection.execute("SELECT * FROM competition_datasets ORDER BY id"):
            datasets.append({key: row[key] for key in ("id", "name", "source_url", "imported_at", "sha256", "sample_count", "schema_count", "entity_count", "notice")}
                            | {"split_counts": json.loads(row["split_counts"])})
    return {"datasets": datasets, "notice": NOTICE}


def competition_status(path):
    connection = _read_connection(path)
    try:
        return _status(connection)
    finally:
        if connection:
            connection.close()


def _save_archive(dataset, archive_root):
    directory = archive_root / dataset["id"]
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / (dataset["sha256"] + ".zip")
    if destination.exists():
        if hashlib.sha256(destination.read_bytes()).hexdigest() != dataset["sha256"]:
            raise ValueError("已保存原始 ZIP 校验失败")
        return destination
    with tempfile.NamedTemporaryFile(dir=directory, suffix=".tmp", delete=False) as temporary:
        temporary_path = Path(temporary.name)
    try:
        shutil.copyfile(dataset["source"], temporary_path)
        if hashlib.sha256(temporary_path.read_bytes()).hexdigest() != dataset["sha256"]:
            raise ValueError("原始 ZIP 在导入过程中发生变化")
        temporary_path.replace(destination)
    finally:
        temporary_path.unlink(missing_ok=True)
    return destination


def import_competition(database, *, cmeie=None, cmeee=None, archive_dir=None):
    if not cmeie and not cmeee:
        raise ValueError("请提供至少一个已授权下载的竞赛 ZIP")
    parsed = [parse_cmeie(cmeie)] if cmeie else []
    if cmeee:
        parsed.append(parse_cmeee(cmeee))
    archive_root = Path(archive_dir or ARCHIVE_ROOT).expanduser().resolve()
    originals = {entry["id"]: _save_archive(entry, archive_root) for entry in parsed}
    database = Path(database).expanduser().resolve()
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database, timeout=15)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN IMMEDIATE")
        if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name IN ('users','sessions','episodes')").fetchone():
            raise ValueError("请使用独立知识 SQLite 数据库，不能导入账号与病程业务库")
        for statement in DDL:
            connection.execute(statement)
        imported_at = datetime.now(timezone.utc).isoformat()
        for entry in parsed:
            identifier, metadata = entry["id"], DATASETS[entry["id"]]
            connection.execute("DELETE FROM competition_datasets WHERE id=?", (identifier,))
            connection.execute("""INSERT INTO competition_datasets
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (identifier, metadata["name"], metadata["source_url"], imported_at,
                    entry["sha256"], len(entry["samples"]), json.dumps(entry["split_counts"]), len(entry["schemas"]),
                    entry["entity_count"], str(originals[identifier]), NOTICE))
            connection.executemany("INSERT INTO competition_schemas VALUES(?,?,?,?)", [(identifier, *schema) for schema in entry["schemas"]])
            for sample in entry["samples"]:
                connection.execute("INSERT INTO competition_samples VALUES(?,?,?,?,?,?,?)", (
                    sample["id"], identifier, sample["split"], sample["ordinal"], sample["text"],
                    json.dumps(sample["relations"], ensure_ascii=False), json.dumps(sample["entities"], ensure_ascii=False)))
                connection.executemany("INSERT INTO competition_entities VALUES(?,?,?,?,?)", [
                    (sample["id"], entity["text"], entity["type"], entity["start"], entity["end"]) for entity in sample["entities"]])
                connection.executemany("INSERT INTO competition_relations VALUES(?,?,?)", [
                    (sample["id"], ordinal, relation["predicate"]) for ordinal, relation in enumerate(sample["relations"])])
            actual = dict(connection.execute("SELECT split,COUNT(*) FROM competition_samples WHERE dataset=? GROUP BY split", (identifier,)))
            if any(actual.get(split, 0) != count for split, count in entry["split_counts"].items()):
                raise RuntimeError("竞赛数据导入行数核验失败")
        status = _status(connection)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return status


def search_competition(path, query, dataset="cmeie", split="train", page=1, page_size=10):
    if dataset not in DATASETS or split not in {"train", "dev", "test"}:
        raise ValueError("竞赛数据集或 split 无效")
    if not isinstance(query, str) or len(query) > 80:
        raise ValueError("检索关键词最多 80 个字符")
    if isinstance(page, bool) or not isinstance(page, int) or not 1 <= page <= 100_000:
        raise ValueError("页码必须为 1 到 100000")
    if isinstance(page_size, bool) or not isinstance(page_size, int) or not 1 <= page_size <= 50:
        raise ValueError("每页数量必须为 1 到 50")
    result = {"items": [], "total": 0, "page": page, "page_size": page_size, "dataset": dataset, "split": split, "notice": NOTICE}
    connection = _read_connection(path)
    if not connection:
        return result
    try:
        where, parameters = "dataset=? AND split=?", [dataset, split]
        if query.strip():
            literal = query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            where += """ AND (text LIKE ? ESCAPE '\\' OR EXISTS (
                SELECT 1 FROM competition_relations r WHERE r.sample_id=competition_samples.id AND r.predicate LIKE ? ESCAPE '\\'
            ) OR EXISTS (
                SELECT 1 FROM competition_entities e WHERE e.sample_id=competition_samples.id AND e.type LIKE ? ESCAPE '\\'
            ))"""
            parameters += ["%" + literal + "%"] * 3
        result["total"] = connection.execute("SELECT COUNT(*) FROM competition_samples WHERE " + where, parameters).fetchone()[0]
        rows = connection.execute("SELECT * FROM competition_samples WHERE " + where + " ORDER BY ordinal LIMIT ? OFFSET ?",
                                  [*parameters, page_size, (page - 1) * page_size])
        result["items"] = [{"id": row["id"], "dataset": row["dataset"], "split": row["split"], "text": row["text"],
                            "relations": json.loads(row["relations_json"]), "entities": json.loads(row["entities_json"])} for row in rows]
        return result
    finally:
        connection.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="本地导入已授权下载的医学竞赛标注 ZIP")
    commands = parser.add_subparsers(dest="command", required=True)
    importer = commands.add_parser("import")
    importer.add_argument("--cmeie", type=Path)
    importer.add_argument("--cmeee", type=Path)
    importer.add_argument("--database", type=Path, required=True, help="独立知识 SQLite 数据库")
    importer.add_argument("--archive-dir", type=Path, help="本地原始 ZIP 保存目录；SHA 和计数存入知识库元数据表")
    args = parser.parse_args(argv)
    try:
        result = import_competition(args.database, cmeie=args.cmeie, cmeee=args.cmeee, archive_dir=args.archive_dir)
    except (ValueError, OSError, sqlite3.Error, zipfile.BadZipFile, RuntimeError) as error:
        print("导入失败，原有数据库内容已保留：" + str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
