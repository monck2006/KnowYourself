"""Research import validation, split isolation and atomic local replacement."""

import hashlib
import json
from pathlib import Path
import sqlite3
import zipfile

import pytest

from app import competition_data as data


def write_cmeie(path, *, invalid_entity=False, extra=None):
    text = "科研例句甲关联乙，literal 100%_match"
    relation = {"subject": "不存在" if invalid_entity else "甲", "predicate": "关联", "object": {"@value": "乙"},
                "subject_type": "演示类型", "object_type": {"@value": "演示类型"}, "Combined": False}
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("CMeIE/53_schemas.jsonl", json.dumps({"subject_type": "演示类型", "predicate": "关联", "object_type": "演示类型"}))
        for split in ("train", "dev", "test"):
            archive.writestr(f"CMeIE/CMeIE_{split}.jsonl", json.dumps({"text": text + split, "spo_list": [] if split == "test" else [relation]}, ensure_ascii=False))
        if extra:
            archive.writestr(extra, "not permitted")
    return path


def write_cmeee(path, *, start=0, end=1, entity="演示", kind="dis"):
    with zipfile.ZipFile(path, "w") as archive:
        for split in ("train", "dev", "test"):
            sample = {"text": "演示科研材料" + split, "entities": [] if split == "test" else [
                {"start_idx": start, "end_idx": end, "type": kind, "entity": entity}]}
            archive.writestr(f"CMeEE-V2/CMeEE-V2_{split}.json", json.dumps([sample], ensure_ascii=False))
    return path


@pytest.fixture
def imported(tmp_path):
    database = tmp_path / "knowledge.sqlite3"
    archive_dir = tmp_path / "originals"
    source = write_cmeie(tmp_path / "cmeie.zip")
    result = data.import_competition(database, cmeie=source, archive_dir=archive_dir)
    return database, source, archive_dir, result


def test_import_metadata_original_hash_and_indexed_relations(imported):
    database, source, originals, result = imported
    metadata = result["datasets"][0]
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    assert metadata["sha256"] == digest
    assert metadata["split_counts"] == {"train": 1, "dev": 1, "test": 1}
    assert metadata["sample_count"] == 3 and metadata["schema_count"] == 1
    assert (originals / "cmeie" / (digest + ".zip")).read_bytes() == source.read_bytes()
    assert metadata["source_url"] == data.DATASETS["cmeie"]["source_url"]
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM competition_entities").fetchone()[0] == 4
        assert connection.execute("SELECT COUNT(*) FROM competition_relations").fetchone()[0] == 2


def test_literal_search_pagination_and_split_separation(imported):
    database, *_ = imported
    assert data.search_competition(database, "")['items'][0]['split'] == "train"
    assert data.search_competition(database, "test")['total'] == 0
    assert data.search_competition(database, "test", split="test")['total'] == 1
    assert data.search_competition(database, "%_")['total'] == 1
    assert data.search_competition(database, "%")['total'] == 1
    assert data.search_competition(database, "%' OR 1=1 --")['total'] == 0
    assert data.search_competition(database, "关联", split="dev")['items'][0]['split'] == "dev"
    assert data.search_competition(database, "", page=2)['items'] == []
    item = data.search_competition(database, "演示类型")['items'][0]
    for entity in item['entities']:
        assert item['text'][entity['start']:entity['end']] == entity['text']
    assert item['relations'][0]['subject'] == "甲"


@pytest.mark.parametrize("options", [{"query": "x" * 81}, {"split": "all"}, {"dataset": "unknown"}, {"page": 0}, {"page_size": 51}])
def test_search_rejects_invalid_controls(imported, options):
    database, *_ = imported
    with pytest.raises(ValueError):
        data.search_competition(database, **({"query": ""} | options))


@pytest.mark.parametrize("extra", ["../escape.jsonl", "/absolute.jsonl", "CMeIE/not-allowed.jsonl"])
def test_zip_path_whitelist_never_extracts(tmp_path, extra):
    source = write_cmeie(tmp_path / "bad.zip", extra=extra)
    with pytest.raises(ValueError, match="路径"):
        data.parse_cmeie(source)
    assert not (tmp_path / "escape.jsonl").exists()


def test_bad_annotation_keeps_previous_dataset(imported, tmp_path):
    database, _, originals, before = imported
    bad = write_cmeie(tmp_path / "bad.zip", invalid_entity=True)
    with pytest.raises(ValueError, match="定位"):
        data.import_competition(database, cmeie=bad, archive_dir=originals)
    assert data.competition_status(database) == before
    assert data.search_competition(database, "甲")['total'] == 1


def test_database_failure_rolls_back_previous_dataset(imported, tmp_path):
    database, source, originals, before = imported
    with sqlite3.connect(database) as connection:
        connection.execute("""CREATE TRIGGER reject_competition_import BEFORE INSERT ON competition_samples
                              BEGIN SELECT RAISE(ABORT,'simulated insertion failure'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        data.import_competition(database, cmeie=source, archive_dir=originals)
    assert data.competition_status(database) == before
    assert data.search_competition(database, "甲")['total'] == 1


def test_archive_size_boundary(imported, monkeypatch):
    _, source, *_ = imported
    monkeypatch.setattr(data, "MAX_ARCHIVE_BYTES", 10)
    with pytest.raises(ValueError, match="大小限制"):
        data.parse_cmeie(source)


def test_duplicate_zip_member_rejected(imported, tmp_path):
    _, source, *_ = imported
    duplicate = tmp_path / "duplicate.zip"
    duplicate.write_bytes(source.read_bytes())
    with zipfile.ZipFile(duplicate, "a") as archive, pytest.warns(UserWarning, match="Duplicate name"):
        archive.writestr("CMeIE/53_schemas.jsonl", "{}")
    with pytest.raises(ValueError, match="重复"):
        data.parse_cmeie(duplicate)


def test_cmeee_inclusive_source_offsets_become_exclusive_display_offsets(tmp_path):
    source = write_cmeee(tmp_path / "cmeee.zip")
    database = tmp_path / "knowledge.sqlite3"
    result = data.import_competition(database, cmeee=source, archive_dir=tmp_path / "originals")
    assert result['datasets'][0]['split_counts'] == {"train": 1, "dev": 1, "test": 1}
    assert result['datasets'][0]['schema_count'] == 9
    item = data.search_competition(database, "演示", dataset="cmeee")['items'][0]
    assert item['relations'] == []
    assert item['entities'] == [{"text": "演示", "type": "dis", "start": 0, "end": 2}]
    assert data.search_competition(database, "test", dataset="cmeee")['total'] == 0


@pytest.mark.parametrize("options", [{"start": -1}, {"end": 999}, {"entity": "错误标注"}, {"kind": "unknown"}, {"start": True}])
def test_cmeee_rejects_invalid_annotation_spans(tmp_path, options):
    source = write_cmeee(tmp_path / "bad.zip", **options)
    with pytest.raises(ValueError):
        data.parse_cmeee(source)


def test_two_datasets_import_atomically_and_preserve_other_knowledge_tables(tmp_path):
    database = tmp_path / "knowledge.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE official_topics(id TEXT)")
        connection.execute("INSERT INTO official_topics VALUES('preserve-me')")
    cmeie = write_cmeie(tmp_path / "cmeie.zip")
    cmeee = write_cmeee(tmp_path / "cmeee.zip")
    result = data.import_competition(database, cmeie=cmeie, cmeee=cmeee, archive_dir=tmp_path / "originals")
    assert {item['id'] for item in result['datasets']} == {"cmeie", "cmeee"}
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT id FROM official_topics").fetchone()[0] == "preserve-me"
    before = data.competition_status(database)
    bad = write_cmeee(tmp_path / "bad.zip", end=999)
    with pytest.raises(ValueError):
        data.import_competition(database, cmeie=cmeie, cmeee=bad, archive_dir=tmp_path / "originals")
    assert data.competition_status(database) == before


def test_business_database_is_rejected_without_changes(imported, tmp_path):
    _, source, originals, _ = imported
    business = tmp_path / "business.sqlite3"
    with sqlite3.connect(business) as connection:
        connection.execute("CREATE TABLE users(id TEXT)")
        connection.execute("INSERT INTO users VALUES('keep')")
    with pytest.raises(ValueError, match="业务库"):
        data.import_competition(business, cmeie=source, archive_dir=originals)
    with sqlite3.connect(business) as connection:
        assert connection.execute("SELECT * FROM users").fetchall() == [('keep',)]
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='competition_datasets'").fetchone() is None


@pytest.mark.parametrize("identifier,path,counts,schemas,entities,digest", [
    ("cmeie", "D:/Download/CMeIE.zip", {"train": 14339, "dev": 3585, "test": 4482}, 53, 72047,
     "def00cab6e93a2a3475b0f354bb7626ceda51a92bbb31eb75f834539adae7b8c"),
    ("cmeee", "D:/Download/CMeEE-V2.zip", {"train": 15000, "dev": 5000, "test": 3000}, 9, 108730,
     "f99529d5356d2eb4cd760ff1a89f53249927b6715c2107e3ac193f3bc13dce86"),
])
def test_authorized_original_archives_counts_hashes_and_import(tmp_path, identifier, path, counts, schemas, entities, digest):
    source = Path(path)
    if not source.is_file():
        pytest.skip("Authorized local download is not present; no corpus is bundled with tests")
    database = tmp_path / "real.sqlite3"
    result = data.import_competition(database, **{identifier: source}, archive_dir=tmp_path / "originals")
    metadata = result['datasets'][0]
    assert metadata['split_counts'] == counts
    assert metadata['sample_count'] == sum(counts.values())
    assert metadata['schema_count'] == schemas
    assert metadata['entity_count'] == entities
    assert metadata['sha256'] == digest
    assert data.search_competition(database, "", dataset=identifier)['total'] == counts['train']
    assert data.search_competition(database, "", dataset=identifier, split="test")['total'] == counts['test']
