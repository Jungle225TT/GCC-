#!/usr/bin/env python3
"""
Build a per-article data pack from GCC scraper exports.

Default output is compliance-safe: article metadata, source URL pointers,
and per-article AI summary files. Full-text HTML/PDF fetching is off unless
explicitly requested, and still respects compliance_rules.yaml by default.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse


def _bootstrap_local_venv_site_packages() -> None:
    here = Path(__file__).resolve().parents[1]
    pyver = f"python{sys.version_info.major}.{sys.version_info.minor}"
    site_packages = here / ".venv" / "lib" / pyver / "site-packages"
    if site_packages.exists() and str(site_packages) not in sys.path:
        sys.path.insert(0, str(site_packages))


_bootstrap_local_venv_site_packages()

try:
    import requests
except ImportError:  # pragma: no cover - handled at runtime
    requests = None

try:
    import yaml
except ImportError:  # pragma: no cover - handled at runtime
    yaml = None

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - handled at runtime
    BeautifulSoup = None

try:
    import trafilatura
except ImportError:  # pragma: no cover - handled at runtime
    trafilatura = None

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer
except ImportError:  # pragma: no cover - handled at runtime
    colors = None
    A4 = None
    ParagraphStyle = None
    cm = None
    pdfmetrics = None
    UnicodeCIDFont = None
    PageBreak = None
    Paragraph = None
    SimpleDocTemplate = None
    Spacer = None


ROOT = Path(__file__).resolve().parents[1]
LOG = logging.getLogger("article_data_pack")
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _load_json_export(path: Path) -> tuple[dict, list[dict]]:
    data = json.loads(_read_text(path))
    if isinstance(data, list):
        return {}, data
    return data.get("metadata", {}), data.get("articles", [])


def _find_latest_json() -> Path:
    candidates = sorted(
        ROOT.glob("output*/gcc_research_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError("No output*/gcc_research_*.json export found")
    return candidates[0]


def _find_summary_for_json(json_path: Path) -> Path | None:
    stamp = re.search(r"gcc_research_(\d{8}_\d{4})\.json$", json_path.name)
    if stamp:
        direct = json_path.with_name(f"gcc_summary_{stamp.group(1)}.md")
        if direct.exists():
            return direct
    candidates = sorted(
        json_path.parent.glob("gcc_summary_*.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _date_sort_key(article: dict) -> tuple[int, str]:
    value = str(article.get("date") or "")
    if re.match(r"^\d{4}-\d{2}-\d{2}", value):
        return (1, value[:10])
    if re.match(r"^\d{4}-\d{2}", value):
        return (1, value[:7] + "-99")
    if re.match(r"^\d{4}", value):
        return (1, value[:4] + "-99-99")
    return (0, "")


def _summary_order(articles: list[dict]) -> list[tuple[int, dict]]:
    indexed = list(enumerate(articles, start=1))
    indexed.sort(key=lambda item: _date_sort_key(item[1]), reverse=True)
    strong = [item for item in indexed if float(item[1].get("topic_relevance_score") or 0) >= 4.0]
    medium = [item for item in indexed if float(item[1].get("topic_relevance_score") or 0) < 4.0]
    return strong + medium


def _split_ai_summary(summary_text: str) -> dict[int, str]:
    if not summary_text:
        return {}
    matches = list(re.finditer(r'<a id="article-(\d+)"></a>', summary_text))
    sections: dict[int, str] = {}
    for pos, match in enumerate(matches):
        idx = int(match.group(1))
        start = match.start()
        end = matches[pos + 1].start() if pos + 1 < len(matches) else len(summary_text)
        block = summary_text[start:end].strip()
        tail = re.search(r"\n---\s*\n\s*##\s*[三四五六七八九十]", block)
        if tail:
            block = block[: tail.start()].strip()
        sections[idx] = block
    return sections


def _fallback_summary(seq: int, article: dict) -> str:
    title = article.get("title_cn") or article.get("title") or f"Article {seq}"
    lines = [
        f'<a id="article-{seq}"></a>',
        f"### [{seq}] {title}",
        "",
        "| Field | Value |",
        "|------|------|",
        f"| Original title | {article.get('title') or ''} |",
        f"| Source | {article.get('source') or ''} ({article.get('source_country') or ''}) |",
        f"| Date | {article.get('date') or 'unknown'} |",
        f"| URL | [{article.get('url') or ''}]({article.get('url') or ''}) |",
        "",
        "> No per-article AI summary was found in the supplied summary file.",
    ]
    return "\n".join(lines)


def _summary_failed(summary: str) -> bool:
    markers = (
        "AI 解析失败",
        "本批次 AI 解析失败",
        "curl fallback failed",
        "Connection error",
        "Could not resolve host",
        "Operation timed out",
    )
    return any(marker in summary for marker in markers)


def _topic_label(article: dict) -> str:
    labels = {
        "energy": "能源与转型",
        "security": "安全与战略",
        "economy": "经济与财政",
        "politics": "政治与治理",
        "society": "社会与人口",
        "technology": "技术与产业",
    }
    topics = article.get("source_topics") or []
    mapped = [labels.get(topic, str(topic)) for topic in topics if topic]
    if mapped:
        return "、".join(mapped)
    title = (article.get("title") or "").lower()
    if any(word in title for word in ("energy", "oil", "lng", "hydrogen", "climate", "emissions")):
        return "能源与气候"
    if any(word in title for word in ("war", "security", "militia", "nuclear", "iran", "israel")):
        return "区域安全"
    if any(word in title for word in ("cost", "subsidy", "market", "fiscal", "econom")):
        return "经济政策"
    return "区域研究"


def _clean_metadata_text(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\[[&#0-9a-zA-Z;]+\]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _metadata_based_summary(seq: int, article: dict) -> str:
    """Create a structured local AI-style brief from scraper metadata only."""
    title = _clean_metadata_text(article.get("title") or f"Article {seq}")
    title_cn = _clean_metadata_text(article.get("title_cn") or title)
    source = article.get("source") or ""
    country = article.get("source_country") or ""
    date = article.get("date") or "日期不详"
    url = article.get("url") or ""
    snippet = _clean_metadata_text(article.get("snippet") or "")
    topic = _topic_label(article)
    score = float(article.get("topic_relevance_score") or 0)
    tier = "强相关" if score >= 4.0 else "中等相关"
    keywords = article.get("matched_keywords") or []
    keyword_text = "、".join(str(k) for k in keywords[:8]) if keywords else "未记录明确关键词"
    evidence = snippet if snippet else "当前导出的元数据未包含摘要，以下判断主要依据标题、来源、日期和关键词。"

    return f"""<a id="article-{seq}"></a>
### [{'⭐ ' if score >= 4.0 else ''}{seq}] {title_cn}

| 字段 | 内容 |
|------|------|
| **原标题** | {title} |
| **来源平台** | {source}（{country}） |
| **发布日期** | {date} |
| **相关性** | {tier} · {score:.1f} |
| **原文链接** | [查看原文]({url}) |

**核心议题**
本文聚焦“{topic}”相关问题，题名显示其讨论对象为“{title_cn}”。元数据摘要/线索如下：{evidence[:420]}【待核实】这篇文章被系统归为{tier}，说明其与 GCC 研究议题存在可跟踪关联。

**主要判断**
基于标题、摘要、来源和关键词的本地 AI 兜底判断：文章可能围绕政策变化、区域风险、能源转型或经济治理中的一个具体切口展开，适合先纳入研究线索池。【AI推断】关键词命中包括：{keyword_text}。【原文元数据】由于当前未重新获取全文，作者论证链、数据口径和结论强度仍需打开原文复核。【待核实】

**对GCC地区的影响**
若文章涉及能源、财政、区域安全或治理改革，其影响通常会通过政策议程设置、投资预期、能源市场定价或安全合作机制传导至海湾国家。【AI推断】对强相关条目，可优先核验其是否直接涉及沙特、阿联酋、卡塔尔、巴林、科威特、阿曼或 GCC 机制本身。【待核实】

**对华关联**
当前元数据未必显示直接对华线索，但可从中海能源合作、基础设施与产业投资、区域安全外溢、全球南方治理和技术标准扩散等角度继续核验。【AI推断】若文章涉及能源转型、交通、电动车、LNG、油价或中东安全格局，应进一步检查是否影响中国企业、进口安全或政策沟通窗口。【待核实】

**关键数据或事件**
本地数据包尚未抓取全文；可核验线索包括发布日期（{date}）、来源机构（{source}）、相关性评分（{score:.1f}）和关键词命中（{keyword_text}）。原文中的具体数字、百分比、模型设定或事件节点需以原文为准。

---"""


def _slugify(text: str, fallback: str) -> str:
    ascii_text = text.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    if not slug:
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]
        slug = f"{fallback}-{digest}"
    return slug[:80]


def _load_compliance_rules() -> dict:
    path = ROOT / "compliance_rules.yaml"
    defaults = {
        "risk_level": "unknown",
        "allow_scrape": True,
        "fulltext_scraping_allowed": False,
        "crawl_delay_seconds": 1.0,
        "requires_permission": False,
    }
    if not path.exists() or yaml is None:
        return {"defaults": defaults, "domains": {}}
    try:
        raw = yaml.safe_load(_read_text(path)) or {}
    except Exception as exc:  # pragma: no cover - diagnostic path
        LOG.warning("Could not load compliance_rules.yaml: %s", exc)
        return {"defaults": defaults, "domains": {}}
    merged_defaults = dict(defaults)
    merged_defaults.update(raw.get("defaults") or {})
    return {"defaults": merged_defaults, "domains": raw.get("domains") or {}}


def _with_defaults(rule: dict, defaults: dict) -> dict:
    merged = dict(defaults)
    merged.update(rule or {})
    return merged


def _domain_for_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _compliance_for_url(url: str, rules: dict) -> tuple[str, dict]:
    domain = _domain_for_url(url)
    defaults = rules.get("defaults") or {}
    for configured, rule in rules.get("domains", {}).items():
        key = configured.lower()
        if domain == key or domain.endswith("." + key):
            return key, _with_defaults(rule, defaults)
    return domain, _with_defaults({}, defaults)


def _may_fetch_fulltext(rule: dict, args: argparse.Namespace) -> tuple[bool, str]:
    if not args.fetch_fulltext:
        return False, "fulltext_fetch_disabled"
    if args.force_fulltext:
        return True, "forced_by_user"
    if rule.get("fulltext_scraping_allowed", False):
        return True, "fulltext_allowed_by_rule"
    if (
        args.allow_unknown_fulltext
        and rule.get("allow_scrape", True)
        and not rule.get("requires_permission", False)
        and str(rule.get("risk_level", "unknown")).lower() in {"unknown", "low"}
    ):
        return True, "allowed_unknown_or_low_risk"
    return False, "blocked_by_fulltext_compliance_rule"


def _fetch(url: str, timeout: int) -> requests.Response:
    if requests is None:
        raise RuntimeError("requests is not installed")
    response = requests.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    return response


def _extract_text_from_html(html_text: str, url: str) -> str:
    if trafilatura is not None:
        text = trafilatura.extract(
            html_text,
            url=url,
            include_comments=False,
            include_tables=False,
            no_fallback=False,
        )
        if text and len(text.strip()) > 120:
            return text.strip()
    if BeautifulSoup is None:
        return ""
    soup = BeautifulSoup(html_text, "html.parser")
    for tag in soup.select(
        "nav, header, footer, aside, script, style, "
        "[class*='menu'], [class*='sidebar'], [class*='related'], "
        "[class*='share'], [class*='social'], [class*='comment'], "
        "[class*='subscribe'], [class*='newsletter'], [class*='cookie']"
    ):
        tag.decompose()
    paragraphs = [
        p.get_text(" ", strip=True)
        for p in soup.find_all("p")
        if len(p.get_text(" ", strip=True)) > 40
    ]
    return "\n\n".join(paragraphs).strip()


def _find_pdf_links(html_text: str, base_url: str) -> list[str]:
    if BeautifulSoup is None:
        return []
    soup = BeautifulSoup(html_text, "html.parser")
    links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href", "").strip()
        label = anchor.get_text(" ", strip=True).lower()
        target = urljoin(base_url, href)
        marker = (href + " " + label).lower()
        if ".pdf" in marker or "download pdf" in marker or label == "pdf":
            if target not in links:
                links.append(target)
    return links


def _safe_pdf_text(text: str) -> str:
    text = html.escape(text or "")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return text


def _register_pdf_font() -> str:
    if pdfmetrics is None or UnicodeCIDFont is None:
        return "Helvetica"
    try:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        return "STSong-Light"
    except Exception:
        return "Helvetica"


def _write_text_pdf(title: str, body: str, output_path: Path, *, subtitle: str = "") -> bool:
    if SimpleDocTemplate is None:
        return False
    font_name = _register_pdf_font()
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=2.2 * cm,
        rightMargin=2.2 * cm,
        topMargin=2.0 * cm,
        bottomMargin=2.0 * cm,
        title=title[:120],
        author="Chengdu Institute of Innovative Finance",
    )
    styles = {
        "title": ParagraphStyle(
            "Title",
            fontName=font_name,
            fontSize=15,
            leading=21,
            spaceAfter=8,
            textColor=colors.HexColor("#1a1a2e"),
        ),
        "meta": ParagraphStyle(
            "Meta",
            fontName=font_name,
            fontSize=8,
            leading=12,
            spaceAfter=10,
            textColor=colors.HexColor("#666666"),
        ),
        "body": ParagraphStyle(
            "Body",
            fontName=font_name,
            fontSize=9.5,
            leading=14,
            spaceAfter=5,
            textColor=colors.HexColor("#1a1a2e"),
        ),
    }
    story = [Paragraph(_safe_pdf_text(title), styles["title"])]
    if subtitle:
        story.append(Paragraph(_safe_pdf_text(subtitle), styles["meta"]))
    for para in re.split(r"\n{2,}", body.strip()):
        para = para.strip()
        if not para:
            continue
        story.append(Paragraph(_safe_pdf_text(para), styles["body"]))
    if len(story) == 1:
        story.append(Paragraph("[No content]", styles["body"]))
    doc.build(story)
    return True


def _markdown_to_plain(markdown: str) -> str:
    text = re.sub(r'<a id="[^"]+"></a>\s*', "", markdown)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)
    text = re.sub(r"(?m)^#{1,6}\s*", "", text)
    text = re.sub(r"(?m)^\|[-:\s|]+\|?$", "", text)
    text = text.replace("&nbsp;", " ")
    return text.strip()


def _write_url_shortcut(path: Path, url: str) -> None:
    _write_text(path, f"[InternetShortcut]\nURL={url}\n")


def _export_index(rows: list[dict], output_dir: Path) -> None:
    table_rows = []
    for row in rows:
        rel_dir = html.escape(row["folder"])
        title = html.escape(row["title"])
        source = html.escape(row["source"])
        status = html.escape(row["fulltext_status"])
        links = [
            f'<a href="{rel_dir}/metadata.json">metadata</a>',
            f'<a href="{rel_dir}/ai_summary.md">ai md</a>',
        ]
        if row.get("ai_summary_pdf"):
            links.append(f'<a href="{rel_dir}/ai_summary.pdf">ai pdf</a>')
        if row.get("original_html"):
            links.append(f'<a href="{rel_dir}/original.html">html</a>')
        if row.get("rendered_original_pdf"):
            links.append(f'<a href="{rel_dir}/rendered_original.pdf">rendered pdf</a>')
        if row.get("source_original_pdf"):
            links.append(f'<a href="{rel_dir}/source_original.pdf">source pdf</a>')
        table_rows.append(
            "<tr>"
            f"<td>{row['seq']}</td><td>{title}</td><td>{source}</td>"
            f"<td>{status}</td><td>{' | '.join(links)}</td>"
            "</tr>"
        )
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>GCC Article Data Pack</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; color: #111; }}
    h1 {{ font-size: 24px; margin-bottom: 6px; }}
    .meta {{ color: #666; font-size: 13px; margin-bottom: 22px; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
    th, td {{ border-bottom: 1px solid #ddd; padding: 8px 10px; text-align: left; vertical-align: top; }}
    th {{ background: #f6f6f6; }}
    td:nth-child(1) {{ width: 48px; color: #666; }}
    td:nth-child(4) {{ width: 220px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }}
    a {{ color: #1557c0; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <h1>GCC Article Data Pack</h1>
  <div class="meta">Generated: {html.escape(now)} | Articles: {len(rows)}</div>
  <table>
    <thead><tr><th>#</th><th>Title</th><th>Source</th><th>Fulltext status</th><th>Files</th></tr></thead>
    <tbody>
      {''.join(table_rows)}
    </tbody>
  </table>
</body>
</html>
"""
    _write_text(output_dir / "index.html", doc)


def _write_manifest(rows: list[dict], output_dir: Path) -> None:
    with (output_dir / "manifest.json").open("w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=2)
    fieldnames = [
        "seq",
        "original_json_index",
        "title",
        "title_cn",
        "source",
        "date",
        "url",
        "domain",
        "risk_level",
        "fulltext_status",
        "folder",
        "metadata_json",
        "ai_summary_md",
        "ai_summary_pdf",
        "original_html",
        "original_text",
        "rendered_original_pdf",
        "source_original_pdf",
    ]
    with (output_dir / "manifest.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _process_fulltext(article: dict, article_dir: Path, rule: dict, reason: str, args: argparse.Namespace) -> dict:
    status = {
        "fulltext_status": reason,
        "original_html": "",
        "original_text": "",
        "rendered_original_pdf": "",
        "source_original_pdf": "",
        "source_pdf_url": "",
        "fetch_error": "",
    }
    if not reason.startswith(("fulltext_allowed", "allowed_unknown", "forced")):
        return status

    url = article.get("url") or ""
    try:
        response = _fetch(url, args.timeout)
        content_type = response.headers.get("content-type", "").lower()
        is_pdf = "application/pdf" in content_type or urlparse(url).path.lower().endswith(".pdf")
        if is_pdf:
            pdf_path = article_dir / "source_original.pdf"
            pdf_path.write_bytes(response.content)
            status["source_original_pdf"] = pdf_path.name
            status["fulltext_status"] = reason + ":source_pdf_saved"
            return status

        html_text = response.text
        html_path = article_dir / "original.html"
        _write_text(html_path, html_text)
        status["original_html"] = html_path.name

        text = _extract_text_from_html(html_text, url)
        if text:
            text_path = article_dir / "original_text.txt"
            _write_text(text_path, text)
            status["original_text"] = text_path.name
            pdf_path = article_dir / "rendered_original.pdf"
            if _write_text_pdf(
                article.get("title") or "Article",
                text,
                pdf_path,
                subtitle=f"{article.get('source') or ''} | {article.get('date') or ''} | {url}",
            ):
                status["rendered_original_pdf"] = pdf_path.name

        pdf_links = _find_pdf_links(html_text, url)
        if pdf_links and not status["source_original_pdf"]:
            pdf_url = pdf_links[0]
            try:
                pdf_response = _fetch(pdf_url, args.timeout)
                pdf_path = article_dir / "source_original.pdf"
                pdf_path.write_bytes(pdf_response.content)
                status["source_original_pdf"] = pdf_path.name
                status["source_pdf_url"] = pdf_url
            except Exception as exc:
                status["fetch_error"] = f"pdf_link_failed: {exc}"

        status["fulltext_status"] = reason + ":html_saved"
        if not text:
            status["fulltext_status"] += ":text_empty"
        return status
    except Exception as exc:
        status["fulltext_status"] = reason + ":fetch_failed"
        status["fetch_error"] = str(exc)
        LOG.warning("Fulltext fetch failed for %s: %s", url, exc)
        return status
    finally:
        delay = max(0.0, float(rule.get("crawl_delay_seconds", args.delay) or args.delay))
        if delay:
            time.sleep(delay)


def build_pack(args: argparse.Namespace) -> Path:
    json_path = Path(args.json).resolve() if args.json else _find_latest_json()
    summary_path = Path(args.summary).resolve() if args.summary else _find_summary_for_json(json_path)
    metadata, articles = _load_json_export(json_path)
    if args.limit:
        articles = articles[: args.limit]
    if not articles:
        raise RuntimeError(f"No articles found in {json_path}")

    summary_text = _read_text(summary_path) if summary_path and summary_path.exists() else ""
    summary_sections = _split_ai_summary(summary_text)
    ordered_articles = _summary_order(articles)
    rules = _load_compliance_rules()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    output_dir = Path(args.output_dir).resolve() if args.output_dir else ROOT / f"output_article_data_pack_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    pack_meta = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "json_export": str(json_path),
        "summary_export": str(summary_path) if summary_path else "",
        "source_metadata": metadata,
        "article_count": len(ordered_articles),
        "fetch_fulltext": bool(args.fetch_fulltext),
        "allow_unknown_fulltext": bool(args.allow_unknown_fulltext),
        "force_fulltext": bool(args.force_fulltext),
        "replace_failed_ai_summary": not bool(args.keep_failed_ai_summary),
    }
    _write_text(output_dir / "pack_metadata.json", json.dumps(pack_meta, ensure_ascii=False, indent=2))

    rows: list[dict] = []
    for seq, (original_index, article) in enumerate(ordered_articles, start=1):
        title = article.get("title") or f"article-{seq}"
        slug = _slugify(title, f"article-{seq}")
        folder_name = f"{seq:03d}_{slug}"
        article_dir = output_dir / folder_name
        article_dir.mkdir(parents=True, exist_ok=True)

        domain, rule = _compliance_for_url(article.get("url") or "", rules)
        may_fetch, fulltext_reason = _may_fetch_fulltext(rule, args)

        article_meta = dict(article)
        article_meta.update(
            {
                "pack_sequence": seq,
                "original_json_index": original_index,
                "domain": domain,
                "compliance_rule": {
                    "risk_level": rule.get("risk_level"),
                    "allow_scrape": rule.get("allow_scrape"),
                    "fulltext_scraping_allowed": rule.get("fulltext_scraping_allowed"),
                    "requires_permission": rule.get("requires_permission"),
                    "fulltext_allowed_path": rule.get("fulltext_allowed_path", ""),
                    "notes": rule.get("notes", ""),
                },
            }
        )
        metadata_path = article_dir / "metadata.json"
        _write_text(metadata_path, json.dumps(article_meta, ensure_ascii=False, indent=2))
        _write_url_shortcut(article_dir / "source.url", article.get("url") or "")

        ai_summary = summary_sections.get(seq) or _metadata_based_summary(seq, article)
        if not args.keep_failed_ai_summary and _summary_failed(ai_summary):
            ai_summary = _metadata_based_summary(seq, article)
        ai_md_path = article_dir / "ai_summary.md"
        _write_text(ai_md_path, ai_summary + "\n")
        ai_pdf_path = article_dir / "ai_summary.pdf"
        ai_pdf_written = _write_text_pdf(
            article.get("title_cn") or article.get("title") or f"Article {seq}",
            _markdown_to_plain(ai_summary),
            ai_pdf_path,
            subtitle=f"{article.get('source') or ''} | {article.get('date') or ''}",
        )

        fulltext_status = _process_fulltext(article, article_dir, rule, fulltext_reason, args)
        if not may_fetch:
            LOG.info("[%03d] Skipped fulltext for %s: %s", seq, domain, fulltext_reason)

        row = {
            "seq": seq,
            "original_json_index": original_index,
            "title": article.get("title") or "",
            "title_cn": article.get("title_cn") or "",
            "source": article.get("source") or "",
            "date": article.get("date") or "",
            "url": article.get("url") or "",
            "domain": domain,
            "risk_level": rule.get("risk_level", ""),
            "folder": folder_name,
            "metadata_json": "metadata.json",
            "ai_summary_md": "ai_summary.md",
            "ai_summary_pdf": "ai_summary.pdf" if ai_pdf_written else "",
            **fulltext_status,
        }
        rows.append(row)

    _write_manifest(rows, output_dir)
    _export_index(rows, output_dir)
    return output_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export per-article GCC data packs")
    parser.add_argument("--json", help="Path to gcc_research_*.json. Defaults to newest output*/ export.")
    parser.add_argument("--summary", help="Path to gcc_summary_*.md. Defaults to matching/newest in JSON folder.")
    parser.add_argument("--output-dir", help="Destination directory. Defaults to output_article_data_pack_TIMESTAMP.")
    parser.add_argument("--limit", type=int, default=0, help="Limit article count for testing.")
    parser.add_argument("--fetch-fulltext", action="store_true", help="Fetch article HTML/PDF when compliance permits it.")
    parser.add_argument(
        "--allow-unknown-fulltext",
        action="store_true",
        help="With --fetch-fulltext, also fetch unknown/low risk domains that do not require permission.",
    )
    parser.add_argument(
        "--force-fulltext",
        action="store_true",
        help="With --fetch-fulltext, fetch regardless of fulltext_scraping_allowed. Use only with authorization.",
    )
    parser.add_argument(
        "--keep-failed-ai-summary",
        action="store_true",
        help="Keep upstream AI failure placeholders instead of replacing them with local metadata-based briefs.",
    )
    parser.add_argument("--timeout", type=int, default=20, help="HTTP timeout in seconds.")
    parser.add_argument("--delay", type=float, default=1.0, help="Fallback delay between fulltext requests.")
    parser.add_argument("--debug", action="store_true", help="Verbose logging.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    if args.force_fulltext:
        LOG.warning("--force-fulltext enabled. Use only for authorized fulltext collection.")
    output_dir = build_pack(args)
    print(f"Data pack written to: {output_dir}")


if __name__ == "__main__":
    main()
