#!/usr/bin/env python3
"""
GCC Think Tank Full-text Scraper → PDF
AI 训练数据采集工具

爬取单个网站的文章全文（标题 + 正文），合并输出为一个 PDF 文件。
一个网站 = 一个 PDF。

用法:
    python fulltext_to_pdf.py                     # 默认站点: KAPSARC
    python fulltext_to_pdf.py --site ajcs         # Al Jazeera Centre for Studies
    python fulltext_to_pdf.py --site carnegie     # Carnegie Middle East Center
    python fulltext_to_pdf.py --site rasanah      # Rasanah IIIS
    python fulltext_to_pdf.py --max 30            # 最多抓 30 篇
    python fulltext_to_pdf.py --playwright        # 启用 JS 渲染（SPA 网站）
    python fulltext_to_pdf.py --list              # 列出所有可用站点

依赖安装:
    pip install requests beautifulsoup4 feedparser trafilatura reportlab
    pip install playwright && playwright install chromium   # 可选，JS 渲染
"""

import re
import time
import logging
import argparse
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# ── 可选依赖 ────────────────────────────────────────────────────────────────
try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False
    print("⚠️  pip install feedparser")

try:
    import trafilatura
    HAS_TRAFILATURA = True
except ImportError:
    HAS_TRAFILATURA = False
    print("⚠️  pip install trafilatura  (强烈推荐，正文提取更准确)")

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, HRFlowable, PageBreak
    )
    from reportlab.lib import colors
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False
    print("⚠️  pip install reportlab")

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("fulltext_pdf")

# ── 站点配置 ────────────────────────────────────────────────────────────────
SITES = {
    "kapsarc": {
        "name": "King Abdullah Petroleum Studies and Research Centre (KAPSARC)",
        "country": "Saudi Arabia",
        "base_url": "https://www.kapsarc.org",
        "rss_feeds": ["https://www.kapsarc.org/feed/"],
        "listing_pages": [
            "/our-offerings/publications/",
            "/newsroom/news/",
        ],
        "selectors": {
            "article": "article, .publication-item, .research-item, .card, [class*='post'], [class*='article'], [class*='publication']",
            "title": "h4 a, h3 a, h2 a, .title a, [class*='title'] a",
        },
        "content_selectors": [
            "article .entry-content",
            ".publication-content",
            ".post-content",
            "main article",
            "[class*='content'] p",
        ],
    },
    "ajcs": {
        "name": "Al Jazeera Centre for Studies (AJCS)",
        "country": "Qatar",
        "base_url": "https://studies.aljazeera.net",
        "rss_feeds": ["https://studies.aljazeera.net/en/rss.xml"],
        "listing_pages": ["/en/", "/en/reports"],
        "selectors": {
            "article": "article, .card, [class*='post'], [class*='item']",
            "title": "h2 a, h3 a, [class*='title'] a",
        },
        "content_selectors": [
            "article .wysiwyg",
            ".article-body",
            ".entry-content",
            "article",
        ],
    },
    "carnegie": {
        "name": "Carnegie Middle East Center",
        "country": "Lebanon",
        "base_url": "https://carnegie-mec.org",
        "rss_feeds": ["https://carnegie-mec.org/feed"],
        "listing_pages": ["/", "/middle-east/research"],
        "selectors": {
            "article": "article, [class*='card'], [class*='item'], [class*='post']",
            "title": "h2 a, h3 a, [class*='title'] a",
        },
        "content_selectors": [
            ".article-body",
            ".entry-content",
            "article .content",
            "main article",
        ],
    },
    "rasanah": {
        "name": "International Institute for Iranian Studies (Rasanah IIIS)",
        "country": "Saudi Arabia",
        "base_url": "https://rasanah-iiis.org/english",
        "rss_feeds": ["https://rasanah-iiis.org/english/feed/"],
        "listing_pages": ["/", "/category/publications/"],
        "selectors": {
            "article": "article, .post, .entry",
            "title": "h2 a, h3 a, .entry-title a",
        },
        "content_selectors": [
            ".entry-content",
            "article .post-content",
            ".article-body",
        ],
    },
    "brookings-doha": {
        "name": "Brookings Doha Center",
        "country": "Qatar",
        "base_url": "https://www.brookings.edu",
        "rss_feeds": ["https://www.brookings.edu/feed/?center=brookings-doha-center"],
        "listing_pages": ["/center/brookings-doha-center/"],
        "selectors": {
            "article": "article, [class*='card'], [class*='item']",
            "title": "h2 a, h3 a, h4 a, [class*='title'] a",
        },
        "content_selectors": [
            ".report-content",
            ".entry-content",
            "article .prose",
            "main article",
        ],
    },
    "derasat": {
        "name": "Bahrain Center for Strategic, International and Energy Studies (Derasat)",
        "country": "Bahrain",
        "base_url": "https://www.derasat.org.bh",
        "rss_feeds": [
            "https://www.derasat.org.bh/en/feed/",
            "https://www.derasat.org.bh/feed/",
        ],
        "listing_pages": ["/en/home_en/", "/knowledge-center/publications-page/"],
        "selectors": {
            "article": "article, .card, [class*='item'], [class*='post'], [class*='publication']",
            "title": "h2 a, h3 a, h4 a, [class*='title'] a",
        },
        "content_selectors": [
            ".entry-content",
            ".post-content",
            "article .content",
        ],
    },
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
}

# ── HTML 获取 ────────────────────────────────────────────────────────────────

def fetch_html_requests(url: str, timeout: int = 15) -> str | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        return r.text
    except Exception as e:
        log.warning(f"  requests 失败 {url}: {e}")
        return None


def fetch_html_playwright(url: str, timeout: int = 25000) -> str | None:
    if not HAS_PLAYWRIGHT:
        return None
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            c = b.new_context(user_agent=HEADERS["User-Agent"], locale="en-US")
            pg = c.new_page()
            pg.goto(url, timeout=timeout, wait_until="networkidle")
            pg.wait_for_timeout(2000)
            html = pg.content()
            b.close()
            return html
    except Exception as e:
        log.warning(f"  Playwright 失败 {url}: {e}")
        return None


def fetch_html(url: str, use_playwright: bool = False) -> str | None:
    html = fetch_html_requests(url)
    if use_playwright or (html and len(html) < 2000):
        pw = fetch_html_playwright(url)
        if pw and len(pw) > len(html or ""):
            html = pw
    return html

# ── 文章列表发现 ─────────────────────────────────────────────────────────────

def get_article_urls_from_rss(feed_url: str) -> list[dict]:
    """从 RSS 获取文章 URL 列表"""
    if not HAS_FEEDPARSER:
        return []
    try:
        feed = feedparser.parse(feed_url)
        results = []
        for entry in feed.entries:
            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()
            if title and link:
                results.append({"title": title, "url": link})
        log.info(f"  📡 RSS 获取 {len(results)} 条: {feed_url}")
        return results
    except Exception as e:
        log.warning(f"  RSS 失败 {feed_url}: {e}")
        return []


def get_article_urls_from_html(
    html: str,
    base_url: str,
    selectors: dict,
) -> list[dict]:
    """从 HTML 列表页提取文章 URL"""
    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen = set()

    article_sel = selectors.get("article", "article")
    title_sel = selectors.get("title", "h2 a, h3 a")

    for card in soup.select(article_sel):
        title_el = card.select_one(title_sel)
        title, href = "", ""
        if title_el:
            title = title_el.get_text(strip=True)
            href = title_el.get("href", "")

        if not title or len(title) < 8:
            heading = card.select_one("h2, h3, h4, [class*='title']")
            link_el = card.select_one("a[href]")
            if heading and link_el:
                title = heading.get_text(strip=True)
                href = link_el.get("href", "")

        if not title or len(title) < 8 or not href:
            continue

        url = _make_absolute(href, base_url)
        if url in seen or not url.startswith("http"):
            continue
        seen.add(url)
        results.append({"title": title, "url": url})

    log.info(f"  🌐 HTML 提取 {len(results)} 个候选链接")
    return results


def _make_absolute(href: str, base_url: str) -> str:
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        parsed = urlparse(base_url)
        return f"{parsed.scheme}://{parsed.netloc}{href}"
    return urljoin(base_url, href)

# ── 全文提取 ─────────────────────────────────────────────────────────────────

def extract_fulltext(html: str, _url: str, content_selectors: list[str]) -> str:
    """从文章页 HTML 提取正文"""

    # 方法1：trafilatura（专为文章提取设计，最准确）
    if HAS_TRAFILATURA:
        text = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=False,
            no_fallback=False,
        )
        if text and len(text.strip()) > 200:
            return text.strip()

    # 方法2：BeautifulSoup 按配置选择器提取
    soup = BeautifulSoup(html, "html.parser")

    # 移除干扰元素
    for tag in soup.select(
        "nav, header, footer, aside, script, style, "
        "[class*='menu'], [class*='sidebar'], [class*='related'], "
        "[class*='share'], [class*='social'], [class*='comment'], "
        "[class*='subscribe'], [class*='newsletter'], [class*='cookie']"
    ):
        tag.decompose()

    for sel in content_selectors:
        el = soup.select_one(sel)
        if el:
            text = el.get_text(separator="\n", strip=True)
            if len(text) > 200:
                return _clean_text(text)

    # 方法3：找最长 <article> 或 <main>
    for tag_name in ["article", "main", "[role='main']"]:
        el = soup.select_one(tag_name)
        if el:
            text = el.get_text(separator="\n", strip=True)
            if len(text) > 200:
                return _clean_text(text)

    # 方法4：兜底——取所有 <p> 段落
    paragraphs = soup.find_all("p")
    text = "\n\n".join(p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 40)
    return _clean_text(text) if len(text) > 100 else ""


def _clean_text(text: str) -> str:
    """清理多余空行和空格"""
    lines = text.splitlines()
    cleaned = []
    prev_blank = False
    for line in lines:
        line = line.strip()
        if not line:
            if not prev_blank:
                cleaned.append("")
            prev_blank = True
        else:
            cleaned.append(line)
            prev_blank = False
    return "\n".join(cleaned).strip()

# ── PDF 生成 ─────────────────────────────────────────────────────────────────

def _safe_text(text: str) -> str:
    """移除 reportlab 不支持的控制字符，保留 Unicode 文字"""
    # reportlab Paragraph 不支持裸 & < >，需转义
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # 移除 ASCII 控制字符（\x00-\x08, \x0b-\x1f 等）
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return text


def build_pdf(articles: list[dict], output_path: str, site_name: str) -> None:
    """将文章列表写入 PDF"""
    if not HAS_REPORTLAB:
        # 降级：输出纯文本
        txt_path = output_path.replace(".pdf", ".txt")
        log.warning(f"reportlab 未安装，降级输出纯文本: {txt_path}")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(f"Source: {site_name}\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
            f.write(f"Articles: {len(articles)}\n")
            f.write("=" * 80 + "\n\n")
            for i, art in enumerate(articles, 1):
                f.write(f"[{i}] {art['title']}\n")
                f.write(f"URL: {art['url']}\n")
                f.write("-" * 60 + "\n")
                f.write(art.get("fulltext", "(无正文)") + "\n\n")
                f.write("=" * 80 + "\n\n")
        log.info(f"📄 纯文本已保存: {txt_path}")
        return

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=2.5 * cm,
        rightMargin=2.5 * cm,
        topMargin=2.5 * cm,
        bottomMargin=2.5 * cm,
        title=site_name,
        author="成都创新金融研究院",
    )

    styles = getSampleStyleSheet()

    # 自定义样式
    style_cover_title = ParagraphStyle(
        "CoverTitle",
        parent=styles["Title"],
        fontSize=20,
        leading=28,
        spaceAfter=12,
        textColor=colors.HexColor("#1a1a2e"),
    )
    style_cover_sub = ParagraphStyle(
        "CoverSub",
        parent=styles["Normal"],
        fontSize=11,
        leading=16,
        textColor=colors.HexColor("#555555"),
        spaceAfter=6,
    )
    style_article_title = ParagraphStyle(
        "ArticleTitle",
        parent=styles["Heading1"],
        fontSize=14,
        leading=20,
        spaceBefore=6,
        spaceAfter=8,
        textColor=colors.HexColor("#1a1a2e"),
        keepWithNext=True,
    )
    style_meta = ParagraphStyle(
        "Meta",
        parent=styles["Normal"],
        fontSize=8,
        leading=12,
        textColor=colors.HexColor("#888888"),
        spaceAfter=10,
    )
    style_body = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontSize=10,
        leading=15,
        spaceAfter=6,
        firstLineIndent=0,
    )
    style_no_content = ParagraphStyle(
        "NoContent",
        parent=styles["Normal"],
        fontSize=9,
        leading=14,
        textColor=colors.HexColor("#aaaaaa"),
        spaceAfter=10,
    )

    story = []

    # ── 封面页 ──
    story.append(Spacer(1, 3 * cm))
    story.append(Paragraph(_safe_text(site_name), style_cover_title))
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph("Full-text Article Collection", style_cover_sub))
    story.append(Paragraph(f"For AI Training Data — 成都创新金融研究院", style_cover_sub))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} &nbsp;|&nbsp; "
        f"Articles: {len(articles)}",
        style_cover_sub,
    ))
    story.append(PageBreak())

    # ── 目录 ──
    story.append(Paragraph("Table of Contents", style_article_title))
    story.append(Spacer(1, 0.3 * cm))
    for i, art in enumerate(articles, 1):
        toc_style = ParagraphStyle(
            f"TOC{i}",
            parent=styles["Normal"],
            fontSize=9,
            leading=14,
            spaceAfter=3,
        )
        title_text = _safe_text(art["title"][:120])
        story.append(Paragraph(f"{i}. {title_text}", toc_style))
    story.append(PageBreak())

    # ── 正文：每篇文章 ──
    for i, art in enumerate(articles, 1):
        title = _safe_text(art["title"])
        url = art.get("url", "")
        fulltext = art.get("fulltext", "").strip()

        # 文章标题
        story.append(Paragraph(f"{i}. {title}", style_article_title))

        # 元信息
        story.append(Paragraph(
            f"URL: {_safe_text(url)}",
            style_meta,
        ))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#dddddd")))
        story.append(Spacer(1, 0.2 * cm))

        # 正文
        if fulltext:
            # 按段落拆分，逐段添加
            paragraphs = [p.strip() for p in fulltext.split("\n\n") if p.strip()]
            if not paragraphs:
                paragraphs = [p.strip() for p in fulltext.split("\n") if p.strip()]
            for para in paragraphs:
                safe_para = _safe_text(para)
                if safe_para:
                    story.append(Paragraph(safe_para, style_body))
        else:
            story.append(Paragraph("[Full text not available]", style_no_content))

        # 文章间分隔
        story.append(Spacer(1, 0.8 * cm))
        if i < len(articles):
            story.append(HRFlowable(
                width="100%", thickness=1.5,
                color=colors.HexColor("#cccccc"),
                spaceAfter=10,
            ))
            # 每5篇换页，保持文件可读性
            if i % 5 == 0:
                story.append(PageBreak())

    doc.build(story)
    log.info(f"📄 PDF 已保存: {output_path}")

# ── HTML 导出 ─────────────────────────────────────────────────────────────────

def build_html(articles: list[dict], output_path: str, site_name: str) -> None:
    """将文章列表写入单个静态 HTML 文件"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 目录条目
    toc_items = "".join(
        f'<li><a href="#article-{i}">{i}. {_html_esc(art["title"])}</a></li>\n'
        for i, art in enumerate(articles, 1)
    )

    # 文章正文块
    article_blocks = []
    for i, art in enumerate(articles, 1):
        title = _html_esc(art["title"])
        url = _html_esc(art.get("url", ""))
        fulltext = art.get("fulltext", "").strip()

        if fulltext:
            # 段落化
            paras = [p.strip() for p in re.split(r"\n{2,}", fulltext) if p.strip()]
            if not paras:
                paras = [p.strip() for p in fulltext.split("\n") if p.strip()]
            body_html = "\n".join(f"<p>{_html_esc(p)}</p>" for p in paras)
        else:
            body_html = '<p class="no-content">[Full text not available]</p>'

        article_blocks.append(f"""
    <article id="article-{i}">
      <h2><span class="num">{i}.</span> {title}</h2>
      <div class="meta">
        <a href="{url}" target="_blank" rel="noopener">{url}</a>
      </div>
      <div class="body">{body_html}</div>
    </article>""")

    articles_html = "\n".join(article_blocks)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{_html_esc(site_name)}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: Georgia, "Times New Roman", serif;
      font-size: 16px;
      line-height: 1.7;
      color: #1a1a2e;
      background: #fafaf8;
      max-width: 860px;
      margin: 0 auto;
      padding: 40px 24px 80px;
    }}
    header {{
      border-bottom: 3px solid #1a1a2e;
      padding-bottom: 24px;
      margin-bottom: 36px;
    }}
    header h1 {{
      font-size: 1.6rem;
      font-weight: 700;
      line-height: 1.3;
      margin-bottom: 8px;
    }}
    header .meta-info {{
      font-size: 0.85rem;
      color: #666;
      font-family: monospace;
    }}
    nav {{
      background: #f0f0ec;
      border-left: 4px solid #1a1a2e;
      padding: 20px 24px;
      margin-bottom: 48px;
      border-radius: 0 4px 4px 0;
    }}
    nav h2 {{
      font-size: 0.95rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-bottom: 12px;
      color: #444;
    }}
    nav ol {{
      padding-left: 1.4em;
    }}
    nav li {{
      font-size: 0.88rem;
      margin-bottom: 4px;
      line-height: 1.4;
    }}
    nav a {{
      color: #1a1a2e;
      text-decoration: none;
    }}
    nav a:hover {{ text-decoration: underline; }}
    article {{
      border-top: 2px solid #ddd;
      padding-top: 36px;
      margin-top: 36px;
    }}
    article h2 {{
      font-size: 1.25rem;
      font-weight: 700;
      line-height: 1.4;
      margin-bottom: 10px;
    }}
    article h2 .num {{
      color: #888;
      font-weight: 400;
      font-size: 1rem;
      margin-right: 4px;
    }}
    .meta {{
      font-size: 0.78rem;
      font-family: monospace;
      color: #888;
      margin-bottom: 20px;
      word-break: break-all;
    }}
    .meta a {{ color: #2a6dd9; text-decoration: none; }}
    .meta a:hover {{ text-decoration: underline; }}
    .body p {{
      margin-bottom: 1em;
    }}
    .no-content {{
      color: #aaa;
      font-style: italic;
    }}
    footer {{
      margin-top: 60px;
      border-top: 1px solid #ddd;
      padding-top: 16px;
      font-size: 0.78rem;
      color: #999;
      text-align: center;
    }}
  </style>
</head>
<body>
  <header>
    <h1>{_html_esc(site_name)}</h1>
    <div class="meta-info">
      Full-text Article Collection &nbsp;|&nbsp;
      Generated: {now} &nbsp;|&nbsp;
      Articles: {len(articles)} &nbsp;|&nbsp;
      成都创新金融研究院
    </div>
  </header>

  <nav>
    <h2>Table of Contents</h2>
    <ol>
{toc_items}    </ol>
  </nav>

  {articles_html}

  <footer>
    AI Training Data Collection — 成都创新金融研究院 — {now}
  </footer>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    log.info(f"🌐 HTML 已保存: {output_path}")


def _html_esc(text: str) -> str:
    """HTML 转义"""
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
    )

# ── 主流程 ────────────────────────────────────────────────────────────────────

def _scrape_and_export(
    site_key: str,
    max_articles: int = 20,
    use_playwright: bool = False,
    output_dir: str = "./output_fulltext",
) -> dict:
    """核心流程：抓取全文，同时输出 PDF + HTML。返回输出路径字典。"""
    if site_key not in SITES:
        raise ValueError(f"未知站点: {site_key}。可用: {list(SITES.keys())}")

    site = SITES[site_key]
    name = site["name"]
    base_url = site["base_url"]

    print("=" * 65)
    print(f"  站点: {name}")
    print(f"  国家: {site['country']}")
    print(f"  最多抓取: {max_articles} 篇")
    print(f"  JS渲染: {'✅ Playwright' if use_playwright and HAS_PLAYWRIGHT else '❌ 仅requests'}")
    print(f"  正文提取: {'✅ trafilatura' if HAS_TRAFILATURA else '⚠️ BeautifulSoup 兜底'}")
    print("=" * 65 + "\n")

    # ── Step 1: 发现文章 URL ──
    log.info("Step 1/3: 发现文章 URL...")
    article_list = []
    seen_urls: set = set()

    for feed_url in site.get("rss_feeds", []):
        for item in get_article_urls_from_rss(feed_url):
            if item["url"] not in seen_urls:
                seen_urls.add(item["url"])
                article_list.append(item)

    if len(article_list) < 5:
        for page_path in site.get("listing_pages", []):
            page_url = base_url.rstrip("/") + page_path
            log.info(f"  抓取列表页: {page_url}")
            html = fetch_html(page_url, use_playwright=use_playwright)
            if not html:
                continue
            for item in get_article_urls_from_html(html, base_url, site["selectors"]):
                if item["url"] not in seen_urls:
                    seen_urls.add(item["url"])
                    article_list.append(item)
            time.sleep(1)

    log.info(f"  共发现 {len(article_list)} 篇文章（取前 {max_articles} 篇）\n")
    article_list = article_list[:max_articles]

    if not article_list:
        log.error("未发现任何文章，请检查网络或尝试 --playwright")
        return {}

    # ── Step 2: 逐篇抓取全文 ──
    log.info("Step 2/3: 逐篇抓取全文...")
    content_selectors = site.get("content_selectors", [])
    success_count = 0

    for i, art in enumerate(article_list, 1):
        art_url = art["url"]
        log.info(f"  [{i:2d}/{len(article_list)}] {art['title'][:70]}")
        log.info(f"         {art_url}")

        page_html = fetch_html(art_url, use_playwright=use_playwright)
        if page_html:
            text = extract_fulltext(page_html, art_url, content_selectors)
            art["fulltext"] = text
            char_count = len(text)
            if char_count > 200:
                log.info(f"         ✅ 提取 {char_count} 字符")
                success_count += 1
            else:
                log.warning(f"         ⚠️  正文偏短 ({char_count} 字符)")
        else:
            art["fulltext"] = ""
            log.warning(f"         ❌ 页面获取失败")

        time.sleep(1.5)

    log.info(f"\n  全文提取成功: {success_count}/{len(article_list)} 篇\n")

    # ── Step 3: 输出 PDF + HTML ──
    log.info("Step 3/3: 生成 PDF + HTML...")
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    safe_key = re.sub(r"[^\w\-]", "_", site_key)
    base_name = f"{safe_key}_{timestamp}"

    pdf_path = str(Path(output_dir) / f"{base_name}.pdf")
    html_path = str(Path(output_dir) / f"{base_name}.html")

    build_pdf(article_list, pdf_path, name)
    build_html(article_list, html_path, name)

    print("\n" + "=" * 65)
    print(f"  ✅ 完成!")
    print(f"  📄 PDF:  {pdf_path}")
    print(f"  🌐 HTML: {html_path}")
    print(f"  📊 文章数: {len(article_list)} 篇（成功提取正文: {success_count} 篇）")
    print("=" * 65)

    return {"pdf": pdf_path, "html": html_path, "articles": len(article_list), "success": success_count}


# 兼容旧调用
def scrape_site_to_pdf(
    site_key: str,
    max_articles: int = 20,
    use_playwright: bool = False,
    output_dir: str = "./output_fulltext",
) -> str:
    result = _scrape_and_export(site_key, max_articles, use_playwright, output_dir)
    return result.get("pdf", "")


# ── 全量合并模式 ──────────────────────────────────────────────────────────────

def _scrape_all_combined(
    max_per_site: int = 30,
    use_playwright: bool = False,
    output_dir: str = "./output_fulltext",
) -> None:
    """抓取全部站点，将所有文章合并为一个 PDF + 一个 HTML。"""
    print("\n" + "=" * 65)
    print(f"  模式: 全量合并（{len(SITES)} 个站点，每站最多 {max_per_site} 篇）")
    print("=" * 65 + "\n")

    all_articles: list[dict] = []

    for site_key, site_cfg in SITES.items():
        print(f"\n>>> [{site_key}] {site_cfg['name']} ({site_cfg['country']})")
        base_url = site_cfg["base_url"]
        seen_urls: set = set()
        article_list: list[dict] = []

        # Step 1: 发现 URL
        for feed_url in site_cfg.get("rss_feeds", []):
            for item in get_article_urls_from_rss(feed_url):
                if item["url"] not in seen_urls:
                    seen_urls.add(item["url"])
                    article_list.append(item)

        if len(article_list) < 5:
            for page_path in site_cfg.get("listing_pages", []):
                page_url = base_url.rstrip("/") + page_path
                html = fetch_html(page_url, use_playwright=use_playwright)
                if not html:
                    continue
                for item in get_article_urls_from_html(html, base_url, site_cfg["selectors"]):
                    if item["url"] not in seen_urls:
                        seen_urls.add(item["url"])
                        article_list.append(item)
                time.sleep(1)

        article_list = article_list[:max_per_site]
        log.info(f"  发现 {len(article_list)} 篇文章，开始逐篇抓取全文...")

        # Step 2: 抓取全文，附加来源标注
        content_selectors = site_cfg.get("content_selectors", [])
        success = 0
        for i, art in enumerate(article_list, 1):
            log.info(f"  [{i:2d}/{len(article_list)}] {art['title'][:65]}")
            page_html = fetch_html(art["url"], use_playwright=use_playwright)
            if page_html:
                text = extract_fulltext(page_html, art["url"], content_selectors)
                art["fulltext"] = text
                if len(text) > 200:
                    success += 1
            else:
                art["fulltext"] = ""
            # 附加来源信息（用于合并 PDF/HTML 标注）
            art["source_name"] = site_cfg["name"]
            art["source_country"] = site_cfg["country"]
            time.sleep(1.2)

        log.info(f"  成功提取正文: {success}/{len(article_list)} 篇")
        all_articles.extend(article_list)

    print(f"\n>>> 全部站点抓取完成，共 {len(all_articles)} 篇文章")

    if not all_articles:
        log.error("未抓到任何文章，退出")
        return

    # Step 3: 合并输出
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    combined_name = "GCC_Fulltext_Combined"
    pdf_path = str(Path(output_dir) / f"{combined_name}_{timestamp}.pdf")
    html_path = str(Path(output_dir) / f"{combined_name}_{timestamp}.html")

    _build_combined_pdf(all_articles, pdf_path)
    _build_combined_html(all_articles, html_path)

    print("\n" + "=" * 65)
    print(f"  ✅ 全量合并完成！")
    print(f"  📄 PDF:  {pdf_path}")
    print(f"  🌐 HTML: {html_path}")
    print(f"  📊 总文章数: {len(all_articles)} 篇")
    print("=" * 65)


def _build_combined_pdf(articles: list[dict], output_path: str) -> None:
    """合并版 PDF：封面 + 来源索引 + 全文，每篇标注来源智库。"""
    if not HAS_REPORTLAB:
        txt_path = output_path.replace(".pdf", ".txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(f"GCC Think Tank Full-text Combined Collection\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} | Articles: {len(articles)}\n")
            f.write("=" * 80 + "\n\n")
            for i, art in enumerate(articles, 1):
                f.write(f"[{i}] {art['title']}\n")
                f.write(f"Source: {art.get('source_name','')}\n")
                f.write(f"URL: {art['url']}\n")
                f.write("-" * 60 + "\n")
                f.write(art.get("fulltext", "(no fulltext)") + "\n\n")
        log.info(f"📄 纯文本已保存: {txt_path}")
        return

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    try:
        pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
        cn_font = 'STSong-Light'
    except Exception:
        cn_font = 'Helvetica'

    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        leftMargin=2.5*cm, rightMargin=2.5*cm,
        topMargin=2.5*cm, bottomMargin=2.5*cm,
        title="GCC Think Tank Full-text Combined",
        author="成都创新金融研究院",
    )

    C_DARK   = colors.HexColor("#1a1a2e")
    C_GREY   = colors.HexColor("#555555")
    C_LIGHT  = colors.HexColor("#aaaaaa")
    C_RULE   = colors.HexColor("#cccccc")
    C_SOURCE = colors.HexColor("#2a6dd9")

    def _sty(name, size, leading, *, before=4, after=6, color=C_DARK, indent=0):
        return ParagraphStyle(
            name, fontName=cn_font, fontSize=size, leading=leading,
            spaceBefore=before, spaceAfter=after,
            leftIndent=indent, textColor=color,
        )

    s_cover_title = _sty("CT", 20, 28, before=0, after=10)
    s_cover_sub   = _sty("CS", 11, 16, before=2, after=4, color=C_GREY)
    s_toc         = _sty("TC", 9,  13, before=1, after=2, indent=6, color=C_DARK)
    s_art_title   = _sty("AT", 13, 19, before=10, after=4)
    s_source_tag  = _sty("SRC", 8, 12, before=0, after=6, color=C_SOURCE)
    s_body        = _sty("BD", 10, 15, before=2, after=3, color=C_DARK)
    s_empty       = _sty("EM", 9,  13, before=2, after=4, color=C_LIGHT)

    story = []

    # 封面
    story.append(Spacer(1, 3*cm))
    story.append(Paragraph("GCC Think Tank Full-text Collection", s_cover_title))
    story.append(Spacer(1, 0.4*cm))
    story.append(Paragraph("AI Training Data — Combined from All Sources", s_cover_sub))
    story.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}  |  Total Articles: {len(articles)}", s_cover_sub))
    story.append(Paragraph("成都创新金融研究院", s_cover_sub))
    story.append(PageBreak())

    # 目录
    story.append(Paragraph("Table of Contents", s_art_title))
    story.append(Spacer(1, 0.3*cm))
    for i, art in enumerate(articles, 1):
        src = art.get("source_country", "")
        label = f"{i}. [{src}] {_safe_text(art['title'][:100])}"
        story.append(Paragraph(label, s_toc))
    story.append(PageBreak())

    # 正文
    for i, art in enumerate(articles, 1):
        story.append(Paragraph(f"{i}. {_safe_text(art['title'])}", s_art_title))
        src_line = f"{art.get('source_name','')}  |  {art.get('source_country','')}  |  {_safe_text(art.get('url',''))}"
        story.append(Paragraph(src_line, s_source_tag))
        story.append(HRFlowable(width="100%", thickness=0.5, color=C_RULE, spaceAfter=6))

        fulltext = art.get("fulltext", "").strip()
        if fulltext:
            for para in re.split(r"\n{2,}", fulltext):
                para = para.strip()
                if para:
                    story.append(Paragraph(_safe_text(para), s_body))
        else:
            story.append(Paragraph("[Full text not available]", s_empty))

        story.append(Spacer(1, 0.6*cm))
        if i < len(articles):
            story.append(HRFlowable(width="100%", thickness=1, color=C_RULE, spaceAfter=6))
            if i % 5 == 0:
                story.append(PageBreak())

    doc.build(story)
    log.info(f"📄 合并 PDF 已保存: {output_path}")


def _build_combined_html(articles: list[dict], output_path: str) -> None:
    """合并版 HTML：带来源标注，适合浏览器阅读和文本提取。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    toc_items = "".join(
        f'<li><a href="#article-{i}"><span class="src">[{_html_esc(art.get("source_country",""))}]</span> '
        f'{_html_esc(art["title"])}</a></li>\n'
        for i, art in enumerate(articles, 1)
    )

    article_blocks = []
    for i, art in enumerate(articles, 1):
        title    = _html_esc(art["title"])
        url      = _html_esc(art.get("url", ""))
        src_name = _html_esc(art.get("source_name", ""))
        src_ctry = _html_esc(art.get("source_country", ""))
        fulltext = art.get("fulltext", "").strip()

        if fulltext:
            paras = [p.strip() for p in re.split(r"\n{2,}", fulltext) if p.strip()]
            if not paras:
                paras = [p.strip() for p in fulltext.split("\n") if p.strip()]
            body_html = "\n".join(f"<p>{_html_esc(p)}</p>" for p in paras)
        else:
            body_html = '<p class="no-content">[Full text not available]</p>'

        article_blocks.append(f"""
    <article id="article-{i}">
      <h2><span class="num">{i}.</span> {title}</h2>
      <div class="source-tag">{src_name} &nbsp;·&nbsp; {src_ctry}</div>
      <div class="meta"><a href="{url}" target="_blank" rel="noopener">{url}</a></div>
      <div class="body">{body_html}</div>
    </article>""")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>GCC Think Tank Full-text Combined Collection</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: Georgia, "Times New Roman", serif;
      font-size: 16px; line-height: 1.7; color: #1a1a2e;
      background: #fafaf8; max-width: 900px;
      margin: 0 auto; padding: 40px 24px 80px;
    }}
    header {{ border-bottom: 3px solid #1a1a2e; padding-bottom: 24px; margin-bottom: 36px; }}
    header h1 {{ font-size: 1.5rem; font-weight: 700; margin-bottom: 8px; }}
    header .meta-info {{ font-size: 0.82rem; color: #666; font-family: monospace; }}
    nav {{
      background: #f0f0ec; border-left: 4px solid #1a1a2e;
      padding: 20px 24px; margin-bottom: 48px; border-radius: 0 4px 4px 0;
    }}
    nav h2 {{ font-size: 0.9rem; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 12px; color: #444; }}
    nav ol {{ padding-left: 1.4em; }}
    nav li {{ font-size: 0.84rem; margin-bottom: 4px; line-height: 1.4; }}
    nav a {{ color: #1a1a2e; text-decoration: none; }}
    nav a:hover {{ text-decoration: underline; }}
    nav .src {{ color: #2a6dd9; font-family: monospace; font-size: 0.78rem; }}
    article {{ border-top: 2px solid #ddd; padding-top: 36px; margin-top: 36px; }}
    article h2 {{ font-size: 1.2rem; font-weight: 700; line-height: 1.4; margin-bottom: 6px; }}
    article h2 .num {{ color: #888; font-weight: 400; font-size: 0.95rem; margin-right: 4px; }}
    .source-tag {{ font-size: 0.8rem; font-family: monospace; color: #2a6dd9; margin-bottom: 4px; }}
    .meta {{ font-size: 0.75rem; font-family: monospace; color: #999; margin-bottom: 18px; word-break: break-all; }}
    .meta a {{ color: #2a6dd9; text-decoration: none; }}
    .meta a:hover {{ text-decoration: underline; }}
    .body p {{ margin-bottom: 1em; }}
    .no-content {{ color: #aaa; font-style: italic; }}
    footer {{ margin-top: 60px; border-top: 1px solid #ddd; padding-top: 16px; font-size: 0.75rem; color: #999; text-align: center; }}
  </style>
</head>
<body>
  <header>
    <h1>GCC Think Tank Full-text Combined Collection</h1>
    <div class="meta-info">
      AI Training Data &nbsp;|&nbsp; Generated: {now} &nbsp;|&nbsp;
      Total Articles: {len(articles)} &nbsp;|&nbsp; 成都创新金融研究院
    </div>
  </header>
  <nav>
    <h2>Table of Contents ({len(articles)} articles)</h2>
    <ol>
{toc_items}    </ol>
  </nav>
  {"".join(article_blocks)}
  <footer>AI Training Data Collection — 成都创新金融研究院 — {now}</footer>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    log.info(f"🌐 合并 HTML 已保存: {output_path}")


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="GCC Think Tank 全文抓取 → PDF（AI 训练数据采集）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python fulltext_to_pdf.py                      # 默认抓 KAPSARC
  python fulltext_to_pdf.py --site ajcs          # Al Jazeera Centre
  python fulltext_to_pdf.py --site carnegie      # Carnegie MEC
  python fulltext_to_pdf.py --max 50             # 最多50篇
  python fulltext_to_pdf.py --playwright         # 启用JS渲染
  python fulltext_to_pdf.py --list               # 列出所有站点
        """,
    )
    parser.add_argument(
        "--site",
        default="kapsarc",
        choices=list(SITES.keys()),
        help=f"目标站点（默认: kapsarc）",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="all_sites",
        help="抓取全部站点，合并输出为一个 PDF + 一个 HTML",
    )
    parser.add_argument(
        "--max",
        type=int,
        default=20,
        dest="max_articles",
        help="每个站点最多抓取文章数（默认: 20）",
    )
    parser.add_argument(
        "--playwright",
        action="store_true",
        help="启用 Playwright JS 渲染（SPA 网站必须）",
    )
    parser.add_argument(
        "--output-dir",
        default="./output_fulltext",
        help="PDF 输出目录（默认: ./output_fulltext）",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="列出所有可用站点后退出",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="显示详细调试日志",
    )

    args = parser.parse_args()

    if args.debug:
        logging.getLogger("fulltext_pdf").setLevel(logging.DEBUG)

    if args.list:
        print("\n可用站点:\n")
        for key, cfg in SITES.items():
            print(f"  {key:<18}  {cfg['name']}  [{cfg['country']}]")
        print()
        return

    # 依赖检查
    if not HAS_REPORTLAB:
        print("\n❌ 缺少 reportlab，请先安装:")
        print("   pip install reportlab\n")
        print("（也可先运行，会降级输出 .txt 文件）\n")

    if args.all_sites:
        _scrape_all_combined(
            max_per_site=args.max_articles,
            use_playwright=args.playwright,
            output_dir=args.output_dir,
        )
    else:
        _scrape_and_export(
            site_key=args.site,
            max_articles=args.max_articles,
            use_playwright=args.playwright,
            output_dir=args.output_dir,
        )


if __name__ == "__main__":
    main()
