"""Reproduce a small, attributed collection of Chinese CDC public health text.

This is an allowlisted educational collection, not an NMPA product database or
an exhaustive/current clinical guideline library. No personal data is accepted.
"""

import argparse
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

SOURCE = "国内官方健康科普"
SOURCE_URL = "https://www.chinacdc.cn/jkkp/"
SNAPSHOT = Path(__file__).with_name("resources") / "domestic-topics.json"
MAX_BYTES = 2 * 1024 * 1024
TIMEOUT_SECONDS = 8
SOURCES = (
    {
        "url": "https://www.chinacdc.cn/jkkp/crb/bcr/202502/t20250212_304217.html",
        "synonyms": ["流感", "流行性感冒", "流感误区"], "groups": ["传染病", "呼吸道疾病"],
    },
    {
        "url": "https://www.chinacdc.cn/jkkp/crb/qtcr/202605/t20260511_1835710.html",
        "synonyms": ["呼吸道传染病", "呼吸道防护", "感冒", "流感"], "groups": ["传染病", "呼吸道疾病"],
    },
    {
        "url": "https://www.chinacdc.cn/jkkp/mxfcrb/xxg/202504/t20250414_305925.html",
        "synonyms": ["高血压", "血压高", "中青年高血压"], "groups": ["慢性病", "心血管疾病"],
    },
    {
        "url": "https://www.chinacdc.cn/jkkp/mxfcrb/fpdx/202408/t20240823_295117.html",
        "synonyms": ["糖尿病", "高血糖", "糖尿病预防"], "groups": ["慢性病", "代谢性疾病"],
    },
)
ALLOWED_URLS = frozenset(item["url"] for item in SOURCES)
_VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"})
_BLOCK = frozenset({"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section"})
_SKIP = frozenset({"script", "style", "iframe", "noscript", "nav", "footer"})


class DomesticSourceError(ValueError):
    """Controlled source/download/extraction failure; no partial snapshot written."""


class _FixedSourceRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        if newurl not in ALLOWED_URLS:
            raise DomesticSourceError("官方页面发生未允许的跳转，停止导入。")
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def _download(url: str) -> bytes:
    if url not in ALLOWED_URLS:
        raise DomesticSourceError("仅允许下载代码中列明的官方科普页面。")
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (KnowYourself public health reference importer)",
                                    "Accept": "text/html", "Accept-Encoding": "identity"})
    try:
        with build_opener(_FixedSourceRedirect()).open(request, timeout=TIMEOUT_SECONDS) as response:
            if response.geturl() not in ALLOWED_URLS:
                raise DomesticSourceError("官方页面来源不在允许列表中。")
            length = response.headers.get("Content-Length")
            if length and (not length.isdigit() or int(length) > MAX_BYTES):
                raise DomesticSourceError("官方科普页面超过下载大小限制。")
            raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise DomesticSourceError("官方科普页面超过下载大小限制。")
            content_type = response.headers.get_content_type()
            if content_type not in ("text/html", "application/xhtml+xml"):
                raise DomesticSourceError("官方科普页面不是 HTML，停止导入。")
            return raw
    except (HTTPError, URLError, TimeoutError, OSError):
        raise DomesticSourceError("官方科普页面暂时无法下载，保留现有快照。") from None


class _ArticleParser(HTMLParser):
    """Capture only CDC's verified articleCon container and page metadata."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.body_depth = None
        self.finished = False
        self.text = []
        self.title = []
        self.date = []
        self.image_count = 0

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag not in _VOID:
            self.stack.append((tag, attributes))
        if tag == "div" and attributes.get("id") == "articleCon" and not self.finished:
            self.body_depth = len(self.stack)
        if self.body_depth is not None:
            if tag in _BLOCK:
                self.text.append("\n")
            if tag == "img":
                self.image_count += 1
            if tag == "td":
                self.text.append(" ")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        index = next((i for i in range(len(self.stack) - 1, -1, -1) if self.stack[i][0] == tag), None)
        if index is None:
            return
        if self.body_depth is not None:
            if tag in _BLOCK:
                self.text.append("\n")
            if index + 1 == self.body_depth:
                self.body_depth = None
                self.finished = True
        del self.stack[index:]

    def handle_data(self, data):
        if any(tag in _SKIP for tag, _ in self.stack):
            return
        if self.body_depth is not None:
            self.text.append(data)
        elif not self.finished and any(tag == "h5" for tag, _ in self.stack):
            self.title.append(data)
        if not self.finished and any("fb" in attrs.get("class", "").split() for _, attrs in self.stack):
            self.date.append(data)


def _clean_text(parts) -> str:
    lines = [re.sub(r"[\t\r\f\v \u00a0\u3000]+", " ", line).strip()
             for line in "".join(parts).split("\n")]
    return "\n".join(line for line in lines if line)


def extract_article(raw: bytes) -> dict:
    if len(raw) > MAX_BYTES:
        raise DomesticSourceError("官方科普页面超过下载大小限制。")
    try:
        document = raw.decode("utf-8-sig")
    except UnicodeError:
        raise DomesticSourceError("官方科普页面编码发生变化，停止导入。") from None
    parser = _ArticleParser()
    parser.feed(document)
    parser.close()
    title = _clean_text(parser.title)
    text = _clean_text(parser.text)
    date_match = re.search(r"\d{4}-\d{2}-\d{2}", "".join(parser.date))
    if not parser.finished or not title or len(text) < 150 or len(text) > 150_000 or not date_match:
        raise DomesticSourceError("未识别到完整官方正文、标题或发布日期，停止导入。")
    try:
        published_at = datetime.strptime(date_match.group(), "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise DomesticSourceError("官方科普页面发布日期无效，停止导入。") from None
    return {"title": title, "summary": text, "published_at": published_at,
            "image_count": parser.image_count}


def build_snapshot() -> dict:
    topics = []
    for item in SOURCES:
        raw = _download(item["url"])
        article = extract_article(raw)
        downloaded_at = datetime.now(timezone.utc).isoformat()
        topics.append({
            "id": "cdc-" + hashlib.sha256(item["url"].encode()).hexdigest()[:20],
            "title": article["title"], "summary": article["summary"], "language": "Chinese",
            "source_url": item["url"], "source": "中国疾控中心", "published_at": article["published_at"],
            "synonyms": item["synonyms"], "groups": item["groups"],
            "downloaded_at": downloaded_at, "source_sha256": hashlib.sha256(raw).hexdigest(),
            "image_count": article["image_count"],
        })
    now = datetime.now(timezone.utc).isoformat()
    checksum = hashlib.sha256(json.dumps(topics, ensure_ascii=False, sort_keys=True,
                                         separators=(",", ":")).encode()).hexdigest()
    return {
        "schema_version": 1, "source": SOURCE, "source_url": SOURCE_URL,
        "dataset_url": SOURCE_URL, "generated_at": now, "imported_at": now,
        "sha256": checksum, "topics": topics,
        "notice": "中国疾控中心固定允许列表的少量公开健康科普文字正文，保留官方原文、作者及出处；不代表全库或最新医学指南。图片与图表请查看官方来源。发布日期与下载时间分别记录，历史疫情描述不代表当前流行情况。检索同义词和分类由应用维护。",
    }


def write_snapshot(path: Path) -> dict:
    bundle = build_snapshot()  # Complete validation precedes replacing any file.
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return bundle


def main() -> None:
    parser = argparse.ArgumentParser(description="更新少量国内官方健康科普原文快照（固定允许列表）")
    parser.add_argument("--snapshot", type=Path, default=SNAPSHOT)
    args = parser.parse_args()
    try:
        bundle = write_snapshot(args.snapshot)
    except (DomesticSourceError, OSError) as exc:
        parser.exit(1, f"导入失败：{exc}\n")
    print(f"已保存 {len(bundle['topics'])} 篇国内官方科普原文：{args.snapshot}")


if __name__ == "__main__":
    main()
