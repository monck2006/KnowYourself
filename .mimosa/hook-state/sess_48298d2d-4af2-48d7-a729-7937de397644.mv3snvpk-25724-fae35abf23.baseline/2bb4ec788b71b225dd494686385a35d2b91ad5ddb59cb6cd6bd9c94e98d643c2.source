import hashlib
import json

import pytest

from app import domestic_sources as domestic


def article_html(text=None):
    content = text or ("官方健康科普完整正文，保留作者和出处。" * 12)
    return f'''<html><head><script>bad-script</script></head><body>
        <nav>导航不属于正文</nav><h5><a>官方测试标题</a></h5>
        <span class="fb">时间：<em>2025-02-12</em></span>
        <div id="articleCon" class="content"><div class="TRS_Editor">
        <style>.no-css{{display:none}}</style><p>{content}</p>
        <p>作者：中国疾控中心</p><img src="official.png"></div></div>
        <footer>页脚不属于正文</footer></body></html>'''.encode()


def test_only_verified_article_container_is_extracted():
    result = domestic.extract_article(article_html())
    assert result["title"] == "官方测试标题"
    assert result["published_at"] == "2025-02-12"
    assert "作者：中国疾控中心" in result["summary"]
    assert result["image_count"] == 1
    assert not any(word in result["summary"] for word in ["导航", "页脚", "bad-script", ".no-css"])


@pytest.mark.parametrize("raw", [b"<html>site maintenance</html>", article_html().replace(b"articleCon", b"unknownBody"),
                                article_html().replace(b"2025-02-12", b"2025-99-99")])
def test_source_structure_and_dates_fail_closed(raw):
    with pytest.raises(domestic.DomesticSourceError):
        domestic.extract_article(raw)


def test_snapshot_provenance_and_full_text_are_kept(monkeypatch):
    raw = article_html()
    calls = []
    monkeypatch.setattr(domestic, "_download", lambda url: calls.append(url) or raw)
    bundle = domestic.build_snapshot()
    assert len(bundle["topics"]) == len(domestic.SOURCES) == 4
    assert set(calls) == domestic.ALLOWED_URLS
    assert bundle["source"] == "国内官方健康科普" and bundle["schema_version"] == 1
    assert len(bundle["sha256"]) == 64
    for topic in bundle["topics"]:
        assert topic["source"] == "中国疾控中心" and topic["language"] == "Chinese"
        assert topic["source_sha256"] == hashlib.sha256(raw).hexdigest()
        assert topic["summary"] == domestic.extract_article(raw)["summary"]
        assert topic["downloaded_at"] and topic["published_at"] == "2025-02-12"
    assert len({item["id"] for item in bundle["topics"]}) == 4


def test_arbitrary_url_and_redirect_are_rejected_without_network():
    with pytest.raises(domestic.DomesticSourceError):
        domestic._download("https://example.com/private")
    with pytest.raises(domestic.DomesticSourceError):
        domestic._FixedSourceRedirect().redirect_request(None, None, 302, "", {}, "https://example.com/")


def test_failed_import_preserves_previous_snapshot(monkeypatch, tmp_path):
    path = tmp_path / "snapshot.json"
    path.write_text("previous snapshot", encoding="utf-8")

    def fail(url):
        raise domestic.DomesticSourceError("offline")

    monkeypatch.setattr(domestic, "_download", fail)
    with pytest.raises(domestic.DomesticSourceError):
        domestic.write_snapshot(path)
    assert path.read_text(encoding="utf-8") == "previous snapshot"


def test_download_size_and_timeout_are_bounded(monkeypatch):
    class Headers:
        def get(self, key):
            return str(domestic.MAX_BYTES + 1) if key == "Content-Length" else None

        def get_content_type(self):
            return "text/html"

    class Response:
        headers = Headers()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def geturl(self):
            return domestic.SOURCES[0]["url"]

        def read(self, size):
            pytest.fail("must reject declared oversized page without reading")

    class Opener:
        def open(self, request, timeout):
            assert timeout <= 8
            return Response()

    monkeypatch.setattr(domestic, "build_opener", lambda *args: Opener())
    with pytest.raises(domestic.DomesticSourceError, match="大小限制"):
        domestic._download(domestic.SOURCES[0]["url"])


def test_bundled_snapshot_is_real_and_attributed():
    snapshot = json.loads(domestic.SNAPSHOT.read_text(encoding="utf-8"))
    assert len(snapshot["topics"]) == 4
    for topic in snapshot["topics"]:
        assert topic["source_url"] in domestic.ALLOWED_URLS
        assert len(topic["summary"]) >= 150 and "官方测试标题" not in topic["title"]
        assert topic["published_at"] and len(topic["source_sha256"]) == 64
        assert not any(word in topic["summary"] for word in ["网站地图", "网站标识码", "document.write("])
