"""Import provenance, replacement safety and authenticated local topic searches."""

import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.knowledge import DOMESTIC_SNAPSHOT, SNAPSHOT, get_topic, import_topics, initialize_knowledge, knowledge_status, search_topics
from app.main import create_app
from app.sync_knowledge import parse_export, plain_text


def bundle():
    return {"schema_version": 1, "source": "MedlinePlus", "source_url": "https://medlineplus.gov/xml.html",
            "generated_at": "2027-01-01T00:00:00", "imported_at": "2027-01-02T00:00:00+00:00",
            "topics": [{"id": "9001", "title": "High Blood Pressure", "summary": "Official summary",
                        "language": "English", "source_url": "https://medlineplus.gov/highbloodpressure.html",
                        "synonyms": ["Hypertension"], "groups": ["Heart"]},
                       {"id": "9002", "title": "Diabetes", "summary": "Another summary",
                        "language": "English", "source_url": "https://medlineplus.gov/diabetes.html",
                        "synonyms": [], "groups": []}]}


@pytest.fixture
def knowledge_path(tmp_path):
    path = tmp_path / "knowledge.sqlite3"
    initialize_knowledge(path, tmp_path / "no-seed.json")
    import_topics(path, bundle())
    return path


def test_literal_search_aliases_pagination_and_full_detail(knowledge_path):
    assert search_topics(knowledge_path, "高血压", 1, 1)["items"][0]["id"] == "9001"
    assert search_topics(knowledge_path, "HYPERTENSION", 1, 10)["total"] == 1
    assert search_topics(knowledge_path, "%", 1, 10)["total"] == 0
    assert search_topics(knowledge_path, "' OR 1=1 --", 1, 10)["total"] == 0
    assert search_topics(knowledge_path, "", 2, 1)["items"][0]["id"] == "9001"
    assert get_topic(knowledge_path, "9001")["generated_at"] == "2027-01-01T00:00:00"
    assert get_topic(knowledge_path, "missing") is None


@pytest.mark.parametrize("mutation", ["duplicate", "foreign_url", "missing_summary"])
def test_bad_import_preserves_previous_complete_dataset(knowledge_path, mutation):
    bad = copy.deepcopy(bundle())
    if mutation == "duplicate":
        bad["topics"].append(bad["topics"][0])
    elif mutation == "foreign_url":
        bad["topics"][0]["source_url"] = "https://medlineplus.gov.attacker.invalid/a"
    else:
        del bad["topics"][0]["summary"]
    with pytest.raises(ValueError):
        import_topics(knowledge_path, bad)
    assert search_topics(knowledge_path, "", 1, 50)["total"] >= 2
    assert get_topic(knowledge_path, "9001")["summary"] == "Official summary"


def test_replacement_retains_other_sources_and_newer_sync_on_restart(knowledge_path):
    domestic_before = search_topics(knowledge_path, "", 1, 50)["total"] - 2
    replacement = bundle()
    replacement["topics"] = replacement["topics"][:1]
    import_topics(knowledge_path, replacement)
    initialize_knowledge(knowledge_path)
    assert get_topic(knowledge_path, "9002") is None
    assert search_topics(knowledge_path, "", 1, 50)["total"] == domestic_before + 1
    status = knowledge_status(knowledge_path, False)
    assert status["topics"]["count"] == domestic_before + 1
    assert status["drugs"]["available"] is False


def test_official_xml_plain_text_and_optional_missing_summary():
    raw = b'''<health-topics date-generated="10/10/2026 02:30:38"><health-topic id="1" title="A" language="English" url="https://medlineplus.gov/a.html"><full-summary>&lt;p&gt;A &lt;b&gt;safe&lt;/b&gt; summary&lt;/p&gt;</full-summary></health-topic><health-topic id="2" title="B" language="English" url="https://medlineplus.gov/b.html"/></health-topics>'''
    parsed = parse_export(raw, "https://medlineplus.gov/xml/a.zip", "2026-10-11T00:00:00Z")
    assert parsed["topics"][0]["summary"] == "A safe summary"
    assert parsed["topics"][1]["summary"] == ""
    assert plain_text("<p>A</p><script>secret()</script><p>B</p>") == "A\nB"
    with pytest.raises(ValueError):
        parse_export(b'<!DOCTYPE x [<!ENTITY e "unsafe">]><health-topics/>', "", "")


def test_real_bundled_export_is_complete_and_redistributable_topics_only():
    data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert len(data["topics"]) == 1017
    assert all(topic["source_url"].startswith("https://medlineplus.gov/") for topic in data["topics"])
    assert all(topic["language"] == "English" for topic in data["topics"])
    domestic = json.loads(DOMESTIC_SNAPSHOT.read_text(encoding="utf-8"))
    assert len(domestic["topics"]) == 4
    assert all(topic["language"] == "Chinese" for topic in domestic["topics"])


def test_authenticated_api_topics_and_query_validation(tmp_path, monkeypatch):
    monkeypatch.delenv("ZHIJI_DATABASE_URL", raising=False)
    monkeypatch.setenv("ZHIJI_OPENFDA_ENABLED", "false")
    monkeypatch.setenv("ZHIJI_KNOWLEDGE_DATABASE_PATH", str(tmp_path / "official.sqlite3"))
    with TestClient(create_app(tmp_path / "business.sqlite3")) as client:
        assert client.get("/api/v1/knowledge/status").status_code == 401
        assert client.get("/api/v1/knowledge/competition/status").status_code == 401
        assert client.get("/api/v1/knowledge/competition").status_code == 401
        assert client.post("/api/v1/auth/register", headers={"X-Zhiji-Client": "1"}, json={
            "username": "knowledgeuser", "display_name": "Test", "password": "Test-private-password-2026", "consent": True,
        }).status_code == 201
        status = client.get("/api/v1/knowledge/status").json()
        assert status["topics"]["count"] == 1021
        assert len(status["topics"]["sources"]) == 2
        result = client.get("/api/v1/knowledge/topics", params={"q": "高血压"}).json()
        assert {item["language"] for item in result["items"]} == {"English", "Chinese"}
        topic = client.get("/api/v1/knowledge/topics/" + result["items"][0]["id"])
        assert topic.status_code == 200 and topic.json()["source_url"].startswith("https://")
        assert client.get("/api/v1/knowledge/topics/no-such-topic").status_code == 404
        for params in ({"page": 0}, {"page_size": 51}, {"q": "a" * 81}):
            assert client.get("/api/v1/knowledge/topics", params=params).status_code == 422
        assert client.get("/api/v1/knowledge/drugs", params={"q": "布洛芬"}).status_code == 503
        assert client.get("/api/v1/knowledge/competition/status").json()["datasets"] == []
        assert client.get("/api/v1/knowledge/competition").json()["items"] == []
        for params in ({"dataset": "unknown"}, {"split": "all"}, {"page": 0}, {"q": "a" * 81}):
            assert client.get("/api/v1/knowledge/competition", params=params).status_code == 422


def test_database_url_and_cache_path_configuration(tmp_path, monkeypatch):
    url = "postgresql://user:local-only@example.invalid/test"
    monkeypatch.setenv("ZHIJI_DATABASE_URL", url)
    monkeypatch.setenv("ZHIJI_KNOWLEDGE_DATABASE_PATH", str(tmp_path / "knowledge.sqlite3"))
    settings = Settings.load()
    assert settings.database_path == url
    assert isinstance(settings.knowledge_database_path, Path)
    assert Settings.load(tmp_path / "explicit.sqlite3").database_path == tmp_path / "explicit.sqlite3"
    monkeypatch.setenv("ZHIJI_KNOWLEDGE_DATABASE_PATH", str(tmp_path / "explicit.sqlite3"))
    with pytest.raises(ValueError):
        Settings.load(tmp_path / "explicit.sqlite3")
