import json
import sqlite3
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

import pytest

from app import knowledge_drugs as drugs


@pytest.fixture
def database(tmp_path):
    return tmp_path / "drugs.sqlite3"


@pytest.fixture
def label():
    return {
        "meta": {"last_updated": "2026-10-10", "results": {"total": 8}},
        "results": [{
            "id": "label-1", "set_id": "12345678-1234-1234-1234-123456789abc",
            "effective_time": "20261001",
            "openfda": {"brand_name": ["Example"], "generic_name": ["IBUPROFEN"],
                        "manufacturer_name": ["Example Manufacturer"], "product_ndc": ["12345-678"]},
            "warnings": ["<p>Official warning &amp; precautions.</p>"],
            "dosage_and_administration": ["DO NOT EXPOSE THIS SECTION"],
        }],
    }


def test_chinese_alias_is_exact_and_transmits_only_keyword(monkeypatch, database, label):
    calls = []
    monkeypatch.setattr(drugs, "_fetch_labels", lambda query, key: calls.append((query, key)) or label)
    result = drugs.search_drugs("布洛芬", database, "private-key")
    assert calls == [("ibuprofen", "private-key")]
    assert result["query"] == "布洛芬"
    assert result["normalized_query"] == "ibuprofen"
    assert result["total"] == 8
    assert result["last_updated"] == "2026-10-10"
    item = result["items"][0]
    assert item["source_url"].endswith("setid=12345678-1234-1234-1234-123456789abc")
    assert item["effective_date"] == "2026-10-01"
    assert item["sections"] == [{"key": "warnings", "title": "警告（官方英文原文）",
                                  "text": "Official warning & precautions."}]
    assert "private-key" not in json.dumps(result)
    assert "DO NOT EXPOSE" not in json.dumps(result)
    assert len(set(drugs.CHINESE_ALIASES.values())) >= 10


@pytest.mark.parametrize("query", ["感冒药", 'ibuprofen" OR *', "x:ibuprofen", "ibuprofen*", "12345", "a b c d e f g h i", "x" * 81])
def test_unsafe_or_unknown_queries_never_make_requests(monkeypatch, database, query):
    monkeypatch.setattr(drugs, "_fetch_labels", lambda *args: pytest.fail("must not fetch"))
    with pytest.raises(drugs.DrugLookupError) as error:
        drugs.search_drugs(query, database)
    assert error.value.status_code == 422


def test_normalized_cache_reused_when_network_disabled(monkeypatch, database, label):
    calls = []
    monkeypatch.setattr(drugs, "_fetch_labels", lambda *args: calls.append(args) or label)
    first = drugs.search_drugs("布洛芬", database)
    second = drugs.search_drugs("IBUPROFEN", database, enabled=False)
    assert len(calls) == 1
    assert not first["cached"]
    assert second["cached"] and not second["stale"]
    assert second["query"] == "IBUPROFEN"
    assert "在线查询已关闭" in second["notice"]


def test_negative_result_is_cached(monkeypatch, database):
    calls = []
    monkeypatch.setattr(drugs, "_fetch_labels", lambda *args: calls.append(args) or {"results": []})
    assert drugs.search_drugs("unfindabledrug", database)["items"] == []
    result = drugs.search_drugs("unfindabledrug", database)
    assert result["cached"] and result["total"] == 0 and len(calls) == 1
    assert "未找到" in result["notice"]


def test_corrupt_cache_is_replaced_instead_of_breaking_lookup(monkeypatch, database, label):
    monkeypatch.setattr(drugs, "_fetch_labels", lambda *args: label)
    drugs.search_drugs("ibuprofen", database)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE drug_cache SET payload_json = ?", ('{"items": []}',))
    result = drugs.search_drugs("ibuprofen", database)
    assert not result["cached"] and result["items"][0]["id"] == "label-1"


def test_stale_cache_fallback_and_seven_day_expiry(monkeypatch, database, label):
    start = 1_800_000_000
    monkeypatch.setattr(drugs, "_now", lambda: start)
    monkeypatch.setattr(drugs, "_fetch_labels", lambda *args: label)
    first = drugs.search_drugs("ibuprofen", database)

    def fail(*args):
        raise drugs.DrugLookupError(503, "Network unavailable")

    monkeypatch.setattr(drugs, "_fetch_labels", fail)
    monkeypatch.setattr(drugs, "_now", lambda: start + drugs.FRESH_SECONDS + 1)
    result = drugs.search_drugs("ibuprofen", database)
    assert result["stale"] and result["cached"]
    assert result["fetched_at"] == first["fetched_at"]
    assert "在线更新失败" in result["notice"]
    offline = drugs.search_drugs("ibuprofen", database, enabled=False)
    assert offline["stale"] and "超过 24 小时" in offline["notice"]
    monkeypatch.setattr(drugs, "_now", lambda: start + drugs.STALE_SECONDS + 1)
    with pytest.raises(drugs.DrugLookupError) as error:
        drugs.search_drugs("ibuprofen", database)
    assert error.value.status_code == 503


def test_disabled_lookup_without_cache_is_clear(database):
    with pytest.raises(drugs.DrugLookupError, match="在线药品查询已关闭"):
        drugs.search_drugs("ibuprofen", database, enabled=False)


def test_missing_fields_invalid_source_id_and_truncation(monkeypatch, database):
    raw = {"results": [{"set_id": "bad&api_key=secret", "openfda": None,
                        "effective_time": "20269999", "warnings": ["w" * 7000]}, {}]}
    monkeypatch.setattr(drugs, "_fetch_labels", lambda *args: raw)
    result = drugs.search_drugs("acetaminophen", database, "private-key")
    item = result["items"][0]
    assert item["brand_names"] == [] and item["effective_date"] == ""
    assert item["source_url"].startswith(drugs.API_URL)
    assert "api_key" not in item["source_url"]
    assert "已截断" in item["sections"][0]["text"] and "已截断" in result["notice"]
    assert result["items"][1]["sections"] == []
    assert result["last_updated"] == ""


def test_cache_size_is_bounded_and_request_limit_is_shared(monkeypatch, database, label):
    monkeypatch.setattr(drugs, "_fetch_labels", lambda *args: label)
    monkeypatch.setattr(drugs, "MAX_CACHE_ENTRIES", 2)
    monkeypatch.setattr(drugs, "REQUESTS_PER_MINUTE", 3)
    for name in ["aspirin", "ibuprofen", "acetaminophen"]:
        drugs.search_drugs(name, database)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM drug_cache").fetchone()[0] == 2
    with pytest.raises(drugs.DrugLookupError) as error:
        drugs.search_drugs("loratadine", database)
    assert error.value.status_code == 429
    assert drugs.search_drugs("acetaminophen", database)["cached"]


def test_fetch_request_is_quoted_bounded_and_has_timeout(monkeypatch):
    captured = []

    class Response:
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, size):
            assert size == drugs.MAX_RESPONSE_BYTES + 1
            return b'{"results": []}'

    def open_request(request, timeout):
        captured.append((request.full_url, timeout))
        return Response()

    monkeypatch.setattr(drugs, "urlopen", open_request)
    assert drugs._fetch_labels("sodium chloride", "secret")["results"] == []
    params = parse_qs(urlsplit(captured[0][0]).query)
    assert params["search"] == ['(openfda.generic_name:"sodium chloride" OR openfda.brand_name:"sodium chloride")']
    assert params["limit"] == ["5"] and params["api_key"] == ["secret"]
    assert captured[0][1] <= 8


@pytest.mark.parametrize("code,expected", [(404, None), (429, 503), (403, 503), (500, 503)])
def test_upstream_http_errors_are_safe(monkeypatch, code, expected):
    def fail(*args, **kwargs):
        raise HTTPError("https://example.invalid?api_key=secret", code, "secret", {}, None)

    monkeypatch.setattr(drugs, "urlopen", fail)
    if expected is None:
        assert drugs._fetch_labels("ibuprofen")["results"] == []
    else:
        with pytest.raises(drugs.DrugLookupError) as error:
            drugs._fetch_labels("ibuprofen", "secret")
        assert error.value.status_code == expected and "secret" not in error.value.detail


def test_network_failure_maps_to_service_unavailable(monkeypatch):
    def fail(*args, **kwargs):
        raise URLError("contains private upstream URL")

    monkeypatch.setattr(drugs, "urlopen", fail)
    with pytest.raises(drugs.DrugLookupError) as error:
        drugs._fetch_labels("ibuprofen")
    assert error.value.status_code == 503
    assert "private" not in error.value.detail


def test_oversized_response_rejected_before_read(monkeypatch):
    class Response:
        headers = {"Content-Length": str(drugs.MAX_RESPONSE_BYTES + 1)}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, size):
            pytest.fail("oversized response must not be read")

    monkeypatch.setattr(drugs, "urlopen", lambda *args, **kwargs: Response())
    with pytest.raises(drugs.DrugLookupError) as error:
        drugs._fetch_labels("ibuprofen")
    assert error.value.status_code == 502


@pytest.mark.parametrize("body", [b"not-json", b'{"results": null}', b"[]"])
def test_invalid_upstream_body_has_controlled_error(monkeypatch, body):
    class Response:
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, size):
            return body

    monkeypatch.setattr(drugs, "urlopen", lambda *args, **kwargs: Response())
    with pytest.raises(drugs.DrugLookupError) as error:
        drugs._fetch_labels("ibuprofen")
    assert error.value.status_code == 502
