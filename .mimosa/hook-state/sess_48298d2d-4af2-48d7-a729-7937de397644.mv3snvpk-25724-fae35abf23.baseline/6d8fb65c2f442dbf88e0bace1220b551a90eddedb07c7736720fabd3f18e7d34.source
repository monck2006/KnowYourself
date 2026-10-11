"""Download the official MedlinePlus export, then atomically replace local topics."""

import argparse
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import re
import urllib.request
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET
import zipfile

from .config import Settings
from .knowledge import initialize_knowledge, import_topics, official_topic_url, SOURCE, SOURCE_URL


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"p", "li", "br", "h2", "h3", "div"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        if tag in {"p", "li", "div"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain_text(value: str) -> str:
    parser = PlainText()
    parser.feed(value)
    return "\n".join(line.strip() for line in re.sub(r"[^\S\n]+", " ", "".join(parser.parts)).splitlines() if line.strip())


def fetch_bytes(url: str, maximum: int) -> bytes:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "medlineplus.gov":
        raise ValueError("只允许下载 MedlinePlus 官方 HTTPS 数据")
    request = urllib.request.Request(url, headers={"User-Agent": "KnowYourself/1.0 (MedlinePlus XML import)"})
    with urllib.request.urlopen(request, timeout=30) as response:
        final = urlsplit(response.url)
        if final.scheme != "https" or final.netloc != "medlineplus.gov":
            raise ValueError("官方数据下载发生非可信重定向")
        content = response.read(maximum + 1)
    if len(content) > maximum:
        raise ValueError("官方数据文件超过大小限制")
    return content


def parse_export(raw: bytes, dataset_url: str, imported_at: str) -> dict:
    if len(raw) > 64 * 1024 * 1024 or b"<!ENTITY" in raw.upper():
        raise ValueError("XML 超出限制或包含自定义实体")
    root = ET.fromstring(raw)
    if root.tag != "health-topics":
        raise ValueError("不是 MedlinePlus 健康主题导出")
    generated = root.get("date-generated") or root.get("dategenerated", "")
    generated_at = datetime.strptime(generated, "%m/%d/%Y %H:%M:%S").isoformat()
    topics = []
    for node in root.findall("health-topic"):
        if node.get("language") != "English":
            continue
        summary_node = node.find("full-summary")
        # Some exports use escaped HTML, others may use actual child elements.
        content = "" if summary_node is None else (summary_node.text or "") + "".join(
            ET.tostring(child, encoding="unicode") for child in summary_node)
        url = node.get("url", "")
        if not official_topic_url(url):
            raise ValueError("主题来源不是官方 HTTPS 地址")
        topics.append({"id": node.get("id", ""), "title": node.get("title", ""),
                       "summary": plain_text(content), "language": "English", "source_url": url,
                       "synonyms": [item.text for item in node.findall("also-called") if item.text],
                       "groups": [item.text for item in node.findall("group") if item.text]})
    if not topics:
        raise ValueError("导出中没有英文主题")
    return {"schema_version": 1, "source": SOURCE, "source_url": SOURCE_URL, "dataset_url": dataset_url,
            "generated_at": generated_at, "imported_at": imported_at,
            "sha256": hashlib.sha256(raw).hexdigest(), "topics": topics}


def download_export() -> dict:
    index = fetch_bytes(SOURCE_URL, 2 * 1024 * 1024).decode("utf-8")
    candidates = re.findall(r'https://medlineplus\.gov/xml/mplus_topics_compressed_(\d{4}-\d{2}-\d{2})\.zip', index)
    if not candidates:
        raise ValueError("官方索引未提供可识别的健康主题下载")
    url = f"https://medlineplus.gov/xml/mplus_topics_compressed_{max(candidates)}.zip"
    compressed = fetch_bytes(url, 10 * 1024 * 1024)
    with zipfile.ZipFile(io.BytesIO(compressed)) as archive:
        members = [item for item in archive.infolist() if item.filename.endswith(".xml")]
        if len(members) != 1 or members[0].file_size > 64 * 1024 * 1024:
            raise ValueError("官方压缩包结构或大小异常")
        raw = archive.read(members[0])
    bundle = parse_export(raw, url, datetime.now(timezone.utc).isoformat(timespec="seconds"))
    if len(bundle["topics"]) < 500:
        raise ValueError("官方主题数量异常，保留现有数据")
    return bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, help="独立知识库 SQLite 路径，默认读取配置")
    parser.add_argument("--snapshot", type=Path, help="另存可随代码分发的规范化 JSON 快照")
    args = parser.parse_args()
    try:
        bundle = download_export()
        path = args.database or Settings.load().knowledge_database_path
        initialize_knowledge(path)
        count = import_topics(path, bundle)
        if args.snapshot:
            args.snapshot.parent.mkdir(parents=True, exist_ok=True)
            temporary = args.snapshot.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(bundle, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            temporary.replace(args.snapshot)
        print(f"MedlinePlus: imported {count} English topics; generated {bundle['generated_at']}; SHA-256 {bundle['sha256']}")
    except Exception:
        # Do not print connection configuration or credentials from environment.
        parser.exit(1, "官方数据同步失败；现有完整数据保留。请检查网络、官方文件结构和本地路径权限。\n")


if __name__ == "__main__":
    main()
