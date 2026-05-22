#!/usr/bin/env python3
"""
GCC智库研究抓取系统 v2.4
成都创新金融研究院 — 姜亭汀
四层漏斗筛选：来源可信度 → 关键词评分 → 内容类型 → AI辅助
数据源：HTML抓取 + RSS订阅

依赖安装：
  pip install requests beautifulsoup4 feedparser playwright openai
  playwright install chromium

AI Provider 切换（默认 DeepSeek）：
  export DEEPSEEK_API_KEY="sk-xxxxx"          # 使用 DeepSeek
  export AI_PROVIDER=anthropic                 # 切换回 Claude
  export ANTHROPIC_API_KEY="sk-ant-xxxxx"
"""

import json, re, os, time, logging, sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import Optional
from pathlib import Path
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup
import ai_client

HAS_AI = ai_client.HAS_AI

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    print("⚠️  未安装 Playwright\n   pip install playwright && playwright install chromium\n")

try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False
    print("⚠️  未安装 feedparser，RSS不可用\n   pip install feedparser\n")

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')
log = logging.getLogger("gcc_scraper")

# ── SQLite 增量去重 ──────────────────────────────────────────────

DEDUP_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "gcc_dedup.db")

def load_seen_urls(db_path=DEDUP_DB_PATH, days=1):
    """
    从本地 SQLite 数据库加载已处理文章的 URL 集合。

    days: 只过滤 days 天内首次处理过的文章（默认1天）。
          设为 None 表示过滤全部历史记录（永不重复）。
          设为 0 相当于关闭去重（返回空集合）。

    逻辑说明：
      - 每日运行一次时，1天窗口可防止当天重复推送；
      - 第二天运行时，昨天的文章已超出窗口，不再被过滤，
        确保新一天能抓到完整内容；
      - 测试时若多次运行，加 --no-dedup 即可。
    """
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS seen_articles "
        "(url TEXT PRIMARY KEY, title TEXT, source TEXT, first_seen TEXT)"
    )
    conn.commit()
    if days == 0:
        conn.close()
        return set()
    if days is not None:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        urls = {row[0] for row in conn.execute(
            "SELECT url FROM seen_articles WHERE first_seen >= ?", (cutoff,)
        )}
    else:
        urls = {row[0] for row in conn.execute("SELECT url FROM seen_articles")}
    conn.close()
    return urls

def save_new_urls(articles, db_path=DEDUP_DB_PATH):
    """将新处理的文章 URL 写入本地 SQLite 数据库"""
    if not articles:
        return
    conn = sqlite3.connect(db_path)
    now = datetime.now().isoformat()
    conn.executemany(
        "INSERT OR IGNORE INTO seen_articles (url, title, source, first_seen) VALUES (?,?,?,?)",
        [(a.url, a.title, a.source, now) for a in articles],
    )
    conn.commit()
    conn.close()
    log.info(f"💾 已将 {len(articles)} 篇文章写入去重数据库 ({db_path})")

@dataclass
class Article:
    title: str
    url: str
    source: str
    source_country: str
    source_tier: str
    source_region: str = ""        # gcc / mena / western
    source_org_type: str = ""      # official / university / independent
    source_topics: list = field(default_factory=list)  # energy/security/economy/politics/society/technology
    date: Optional[str] = None
    snippet: Optional[str] = None
    title_cn: Optional[str] = None
    keyword_score: float = 0.0
    content_type: str = "unknown"
    priority: str = "normal"
    topic_relevance_score: float = 0.0   # 主题相关性综合评分 0–5，叠加在三维分类之上
    ai_verdict: Optional[str] = None
    matched_keywords: list = field(default_factory=list)
    fetch_method: str = "html"
    def to_dict(self):
        return asdict(self)

_THINK_TANKS_YAML_PATH = Path(__file__).parent / "think_tanks.yaml"
_REQUIRED_TANK_FIELDS = {
    "name", "country", "tier", "region", "org_type",
    "topics", "base_url", "pages", "selectors",
}
_REQUIRED_SELECTOR_FIELDS = {"article", "title", "link"}


def _load_think_tanks(path: Path = _THINK_TANKS_YAML_PATH):
    """从 think_tanks.yaml 加载智库信源配置。"""
    try:
        import yaml as _yaml
    except ImportError as e:
        raise RuntimeError("缺少 PyYAML，无法加载 think_tanks.yaml；请先安装 requirements.txt") from e

    try:
        with open(path, encoding="utf-8") as f:
            data = _yaml.safe_load(f) or []
    except FileNotFoundError as e:
        raise RuntimeError(f"缺少智库信源配置文件: {path}") from e

    if not isinstance(data, list):
        raise RuntimeError("think_tanks.yaml 顶层必须是列表，每个元素是一条智库配置")

    loaded = []
    names = set()
    for idx, raw in enumerate(data, start=1):
        if not isinstance(raw, dict):
            raise RuntimeError(f"think_tanks.yaml 第 {idx} 条不是对象/dict")
        missing = sorted(_REQUIRED_TANK_FIELDS - set(raw))
        if missing:
            label = raw.get("name", f"第 {idx} 条")
            raise RuntimeError(f"智库配置 {label} 缺少字段: {', '.join(missing)}")

        tank = dict(raw)
        name = str(tank["name"]).strip()
        if not name:
            raise RuntimeError(f"think_tanks.yaml 第 {idx} 条 name 为空")
        if name in names:
            raise RuntimeError(f"think_tanks.yaml 中存在重复智库名称: {name}")
        names.add(name)
        tank["name"] = name

        for field in ("topics", "pages"):
            if not isinstance(tank.get(field), list):
                raise RuntimeError(f"智库配置 {name} 的 {field} 必须是列表")
        if "rss_feeds" in tank and tank["rss_feeds"] is None:
            tank["rss_feeds"] = []
        if "rss_feeds" in tank and not isinstance(tank.get("rss_feeds"), list):
            raise RuntimeError(f"智库配置 {name} 的 rss_feeds 必须是列表")

        selectors = tank.get("selectors")
        if not isinstance(selectors, dict):
            raise RuntimeError(f"智库配置 {name} 的 selectors 必须是对象/dict")
        missing_selectors = sorted(_REQUIRED_SELECTOR_FIELDS - set(selectors))
        if missing_selectors:
            raise RuntimeError(f"智库配置 {name} 的 selectors 缺少字段: {', '.join(missing_selectors)}")

        loaded.append(tank)

    return loaded


THINK_TANKS = _load_think_tanks()

# === v2.4.1 新增：外置关键词配置加载（对应 5.1 节落地）===
_KEYWORDS_YAML_PATH = Path(__file__).parent / "keywords.yaml"

def _load_keywords_config():
    """加载 keywords.yaml，拍平为 set 便于匹配。所有词都先 .lower()。
    返回 dict: {filter_set, demote_set, title_only_demote_set, max_penalty,
               filter_title_only, demote_check_summary}
    文件缺失或 yaml 未安装时返回空集，保持系统按 v2.4 原逻辑运行。
    """
    try:
        import yaml as _yaml
    except ImportError:
        return {"filter_set": set(), "demote_set": set(), "title_only_demote_set": set(),
                "max_penalty": -2, "filter_title_only": True, "demote_check_summary": True}
    if not _KEYWORDS_YAML_PATH.exists():
        return {"filter_set": set(), "demote_set": set(), "title_only_demote_set": set(),
                "max_penalty": -2, "filter_title_only": True, "demote_check_summary": True}
    with open(_KEYWORDS_YAML_PATH, encoding="utf-8") as _f:
        _cfg = _yaml.safe_load(_f)
    _filter_set = set()
    for _words in (_cfg.get("hard_filter_words") or {}).values():
        _filter_set.update((w or "").lower() for w in (_words or []) if w)
    _demote_set = set()
    for _words in (_cfg.get("demote_words") or {}).values():
        _demote_set.update((w or "").lower() for w in (_words or []) if w)
    _title_only_demote_set = set()
    for _words in (_cfg.get("title_only_demote_words") or {}).values():
        _title_only_demote_set.update((w or "").lower() for w in (_words or []) if w)
    _params = _cfg.get("parameters", {})
    return {
        "filter_set": _filter_set,
        "demote_set": _demote_set,
        "title_only_demote_set": _title_only_demote_set,
        "max_penalty": _params.get("max_demote_penalty", -2),
        "filter_title_only": _params.get("filter_title_only", True),
        "demote_check_summary": _params.get("demote_check_summary", True),
    }

_KW = _load_keywords_config()

def reload_keywords():
    """运行时重载 keywords.yaml（试运行调参用）。"""
    global _KW
    _KW = _load_keywords_config()

# ── 合规规则（从 compliance_rules.yaml 加载）────────────────────

_COMPLIANCE_RULES_PATH = Path(__file__).parent / "compliance_rules.yaml"

def _load_compliance_rules():
    try:
        import yaml as _yaml
    except ImportError:
        return {"defaults": {"allow_scrape": True, "crawl_delay_seconds": 1.0}, "domains": {}}
    try:
        with open(_COMPLIANCE_RULES_PATH, encoding="utf-8") as f:
            data = _yaml.safe_load(f) or {}
        return {
            "defaults": data.get("defaults") or {"allow_scrape": True, "crawl_delay_seconds": 1.0},
            "domains": data.get("domains") or {},
        }
    except FileNotFoundError:
        return {"defaults": {"allow_scrape": True, "crawl_delay_seconds": 1.0}, "domains": {}}
    except Exception as e:
        log.warning(f"⚠️  compliance_rules.yaml 加载失败（{e}），使用默认合规策略")
        return {"defaults": {"allow_scrape": True, "crawl_delay_seconds": 1.0}, "domains": {}}

_COMPLIANCE = _load_compliance_rules()

def _hostname(url):
    return (urlparse(url).hostname or "").lower().removeprefix("www.")

def _with_compliance_defaults(rule: dict) -> dict:
    """域名规则自动继承 defaults，避免旧规则缺少新增合规字段。"""
    merged = dict(_COMPLIANCE.get("defaults", {}) or {})
    merged.update(rule or {})
    return merged

def get_compliance_rule(url):
    host = _hostname(url)
    domains = _COMPLIANCE.get("domains", {})
    for domain, rule in domains.items():
        d = str(domain).lower().removeprefix("www.")
        if host == d or host.endswith("." + d):
            return _with_compliance_defaults(rule)
    return _with_compliance_defaults({})

def _join_url(base_url: str, path: str) -> str:
    """拼接官网栏目路径，保留已给出的完整 URL。"""
    if not path:
        return base_url
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return base_url.rstrip("/") + "/" + path.lstrip("/")

def _manual_link_label(path: str) -> str:
    """给人工浏览入口生成通俗标签。"""
    p = (path or "").lower()
    if "program" in p:
        return "项目页面"
    if "topic" in p or "region" in p:
        return "议题页面"
    if "research" in p:
        return "研究页面"
    if "publication" in p or "analysis" in p:
        return "出版物页面"
    if "center" in p:
        return "中心页面"
    return "栏目入口"

def _manual_reading_links_for_source(domain: str, source_name: str, official_url: str) -> list[dict]:
    """为合规跳过来源整理人工阅读入口，不抓取页面内容。"""
    host = str(domain).lower().removeprefix("www.")
    matched_tank = None
    for tank in THINK_TANKS:
        tank_host = _hostname(tank.get("base_url", ""))
        if tank_host == host or tank.get("name") == source_name:
            matched_tank = tank
            break

    links = [{"label": "官网", "url": official_url}]
    if matched_tank:
        base_url = matched_tank.get("base_url") or official_url
        for path in matched_tank.get("pages", [])[:3]:
            url = _join_url(base_url, path)
            if any(item["url"] == url for item in links):
                continue
            links.append({"label": _manual_link_label(path), "url": url})
    return links[:4]

def _format_markdown_links(links: list[dict]) -> str:
    """把人工阅读入口格式化为 Markdown 链接串。"""
    return "；".join(f"[{item['label']}]({item['url']})" for item in links)

def _active_source_names_for_rule(domain: str, rule: dict) -> list[str]:
    """返回当前 THINK_TANKS 中受该域名规则影响的来源名。"""
    host = str(domain).lower().removeprefix("www.")
    active_names = {tank["name"] for tank in THINK_TANKS}
    names = [
        str(name)
        for name in (rule.get("matched_think_tanks") or [])
        if str(name) in active_names
    ]
    for tank in THINK_TANKS:
        if _hostname(tank.get("base_url", "")) == host and tank["name"] not in names:
            names.append(tank["name"])
    return names

def _cn_section_no(num: int) -> str:
    """把简报章节序号转成中文数字。"""
    labels = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]
    return labels[num] if 0 <= num < len(labels) else str(num)

def _md_cell(text) -> str:
    """清理 Markdown 表格单元格，避免标题中的竖线破坏表格。"""
    return str(text or "").replace("|", "–").replace("\n", " ").strip()

def filtered_out_notice(filtered_out_records: Optional[list] = None, section_no: int = 4) -> str:
    """生成简报末尾的关键词硬过滤复核清单。"""
    records = filtered_out_records or []
    if not records:
        return ""

    lines = [
        f"## {_cn_section_no(section_no)}、关键词硬过滤复核清单",
        "",
        "以下链接在抓取阶段命中了硬过滤规则，因此未进入正式文章池，也未交给 AI 做逐篇分析。该清单用于人工复核关键词规则是否过严；出现在这里不代表推荐阅读。",
        "",
        f"共 {len(records)} 条被硬过滤记录：",
        "",
        "| 来源 | 过滤命中 | 标题 | 链接 |",
        "|------|----------|------|------|",
    ]
    seen = set()
    for rec in records:
        title = _md_cell(rec.get("title", ""))
        url = str(rec.get("url", "") or "").strip()
        source = _md_cell(rec.get("source", ""))
        filter_hit = _md_cell(rec.get("filter_hit") or rec.get("filter_word") or "exclude_pattern")
        key = (title, url, source, filter_hit)
        if key in seen:
            continue
        seen.add(key)
        link = f"[查看]({url})" if url else "-"
        lines.append(f"| {source} | {filter_hit} | {title} | {link} |")
    lines.extend([
        "",
        "> 注：该清单主要服务关键词调参和人工质检。若后续确认某类内容有研究价值，应优先调整硬过滤词或改为降权，而不是直接人工复制进正式文章池。",
    ])
    return "\n".join(lines)

def high_risk_sources_records(include_high_risk=False, active_only=True):
    """返回因合规规则默认跳过的高风险来源。"""
    if include_high_risk:
        return []

    records = []
    domains = _COMPLIANCE.get("domains", {})
    for domain, raw_rule in domains.items():
        rule = _with_compliance_defaults(raw_rule)
        if rule.get("allow_scrape", True):
            continue
        if active_only:
            names = _active_source_names_for_rule(str(domain), rule)
            if not names:
                continue
        else:
            names = rule.get("matched_think_tanks") or rule.get("matched_csv_sites") or [domain]
        base_url = f"https://{domain}"
        for tank in THINK_TANKS:
            if _hostname(tank.get("base_url", "")) == str(domain).lower().removeprefix("www."):
                base_url = tank.get("base_url") or base_url
                break
        for name in names:
            manual_links = _manual_reading_links_for_source(str(domain), str(name), base_url)
            records.append({
                "source": str(name),
                "domain": str(domain),
                "official_url": base_url,
                "manual_links": manual_links,
                "risk_level": str(rule.get("risk_level", "")),
                "scraping_policy": str(rule.get("scraping_policy", "")),
                "robots_summary": str(rule.get("robots_summary", "")),
                "metadata_allowed_path": str(rule.get("metadata_allowed_path", "")),
                "fulltext_allowed_path": str(rule.get("fulltext_allowed_path", "")),
                "fulltext_scraping_allowed": bool(rule.get("fulltext_scraping_allowed", False)),
                "requires_permission": bool(rule.get("requires_permission", False)),
                "analysis_source": str(rule.get("analysis_source", "")),
                "reason": str(rule.get("notes", "")),
            })

    return sorted(records, key=lambda item: (item["source"], item["domain"]))

def high_risk_sources_notice(include_high_risk=False, section_no: int = 4, active_only=True):
    """生成简报末尾的高风险来源说明。"""
    blocked = high_risk_sources_records(include_high_risk=include_high_risk, active_only=active_only)

    if not blocked:
        return ""

    lines = [
        f"## {_cn_section_no(section_no)}、合规未自动抓取但建议人工关注的来源",
        "",
        "以下来源研究质量较高，但因网站服务条款、robots 或自动化访问政策存在风险，本系统默认不自动抓取，也不收录其文章标题、摘要或正文。为方便人工补充阅读，简报保留官方入口，读者可自行打开官网查看最新文章。",
        "",
        "| 来源 | 建议人工浏览入口 | 合规替代路径 | 未自动抓取原因 |",
        "|------|------------------|----------------|----------------|",
    ]
    seen = set()
    for rec in blocked:
        name = rec["source"]
        links = _format_markdown_links(rec.get("manual_links") or [{"label": "官网", "url": rec["official_url"]}])
        alternative = rec.get("metadata_allowed_path") or "人工阅读 / 官方授权路径"
        reason = rec.get("scraping_policy") or rec.get("reason") or "合规规则默认跳过"
        if (name, links) in seen:
            continue
        seen.add((name, links))
        lines.append(
            f"| {_md_cell(name)} | {links} | {_md_cell(alternative)} | {_md_cell(reason)} |"
        )
    lines.extend([
        "",
        "> 注：该部分仅提供人工阅读入口，不代表系统已抓取或分析这些来源的具体文章；合规跳过不代表对机构研究质量的负面评价。",
    ])
    return "\n".join(lines)

# v2.4.1：补充关键救回词（必须）+ 高价值锚点词（建议），详见 keywords.yaml strong_signal_supplement
STRONG_KEYWORDS=[
    "gcc","gulf cooperation council","海合会","مجلس التعاون الخليجي",
    # 关键救回词：确保绿色样本不被降权词误杀
    "mutually assured destruction",  # 救 #25 含「Lessons from History」
    "arabian gulf",                  # 救 #6  含「1979 Revolution」
    "regional security",             # 救 #6  第二保险
    # 高价值议题锚点
    "opec","hormuz","strait of hormuz",
    "gulf states","arab gulf","iran-gulf","u.s.-gulf","us-gulf",
    "regional bloc","axis of resistance","regional integration",
    "energy security","hormuz crisis","hormuz disruption","chokepoint",
]
COUNTRY_KEYWORDS=["saudi arabia","saudi","kingdom of saudi arabia","ksa","uae","united arab emirates","emirates","qatar","qatari","kuwait","kuwaiti","bahrain","bahraini","oman","omani","السعودية","الإمارات","قطر","الكويت","البحرين","عمان","riyadh","jeddah","dubai","abu dhabi","doha","muscat","manama"]
WEAK_KEYWORDS=["gulf","middle east","mena","arabian peninsula","الخليج","الشرق الأوسط"]
SCORE_STRONG,SCORE_COUNTRY,SCORE_WEAK=3,2,1
TITLE_MULTIPLIER=2
RELEVANCE_THRESHOLD=3

def compute_keyword_score(title, snippet=""):
    """
    计算文章相关性评分。
    标题命中得分 × 2，正文命中得分 × 1。
    返回 (总分, 命中关键词列表)。
    """
    title_lower = title.lower()
    snippet_lower = (snippet or "").lower()
    total = 0.0
    matched = []

    def _check_keywords(keywords, base_score):
        nonlocal total
        for kw in keywords:
            kw_lower = kw.lower()
            if kw_lower in title_lower:
                score = base_score * TITLE_MULTIPLIER
                total += score
                matched.append(f"{kw}(标题,+{score})")
            elif kw_lower in snippet_lower:
                total += base_score
                matched.append(f"{kw}(正文,+{base_score})")

    _check_keywords(STRONG_KEYWORDS, SCORE_STRONG)
    _check_keywords(COUNTRY_KEYWORDS, SCORE_COUNTRY)
    _check_keywords(WEAK_KEYWORDS, SCORE_WEAK)
    return total, matched

EXCLUDE_PATTERNS=[r'\bregister\s+for\b',r'\bjoin\s+us\b',r'\bcall\s+for\s+papers\b',r'\bvacancy\b',r'\bjob\s+posting\b',r'\bjob\s+opening\b',r'\bapply\s+now\b',r'\bcareer\s+paths?\s+workshop\b',r'\bcareer\s+fair\b',r'\bcareer\s+opportunit(?:y|ies)\b',r'\bcareers\b',r'\brecruitment\b',r'\bsign\s+up\b',r'\benroll\b']
HIGH_VALUE_PATTERNS=[r'\breport\b',r'\bpolicy\s+brief\b',r'\bresearch\s+paper\b',r'\banalysis\b',r'\bcommentary\b',r'\bworking\s+paper\b',r'\bwhite\s+paper\b',r'\bstudy\b',r'\bin-depth\b',r'\bstrategic\s+assessment\b',r'\bforecast\b']
MEDIUM_VALUE_PATTERNS=[r'\bblog\b',r'\bopinion\b',r'\beditorial\b',r'\bnews\s+update\b',r'\binterview\b',r'\bperspective\b',r'\binsight\b',r'\bbriefing\b']
LOW_VALUE_PATTERNS=[r'\bpress\s+release\b',r'\bmedia\s+coverage\b',r'\bnewsletter\b',r'\bannouncement\b',r'\bdigest\b']

def classify_content_type(title, url):
    """
    根据标题和 URL 的关键词模式判断内容类型和优先级。
    返回 (content_type, priority)。
    """
    combined = f"{title} {url}".lower()
    title_clean = title.strip()
    if re.match(r'^[A-Za-z][A-Za-z &,\-/]+?\(\d+\)$', title_clean):
        return "excluded", "excluded"

    # 外置硬过滤词必须优先于 high/medium/low 判断。
    # 例如 "internship program announcement" 同时命中 announcement(low)，
    # 若低价值判断先返回，会绕过硬过滤。
    title_lower = title.lower()
    text_for_filter = title_lower if _KW["filter_title_only"] else f"{title_lower} {url.lower()}"
    for w in _KW["filter_set"]:
        if w in text_for_filter:
            return "excluded", "excluded"

    for pattern in EXCLUDE_PATTERNS:
        if re.search(pattern, combined):
            return "excluded", "excluded"

    for pattern in HIGH_VALUE_PATTERNS:
        if re.search(pattern, combined):
            return "high", "priority_read"

    for pattern in MEDIUM_VALUE_PATTERNS:
        if re.search(pattern, combined):
            return "medium", "normal"

    for pattern in LOW_VALUE_PATTERNS:
        if re.search(pattern, combined):
            return "low", "low"

    return "unknown", "normal"

def compute_topic_relevance_score(
    keyword_score: float,
    content_type: str,
    source_tier: str = "",
    actual_keyword_score: Optional[float] = None,
) -> float:
    """
    基于关键词评分与内容类型计算主题相关性综合评分（0–5），
    作为第四维度叠加在三维分类（地区×机构×内容类型）之上。

    keyword_score 映射：
      >= 90 (非 core_gcc 特殊保留) → 基础分 3.5
      >= 6                         → 基础分 3.0
      >= 4                         → 基础分 2.5
      >= RELEVANCE_THRESHOLD(3)    → 基础分 2.0

    core_gcc 来源仍自动保留，但强/中分层改看标题/摘要里的真实议题信号，
    避免来源权重把泛中东/全球议题直接推成强相关。

    content_type 加成：
      high    → +1.5   medium  → +0.5
      unknown →  0.0   low     → -0.5
    """
    scoring_score = keyword_score
    if source_tier == "core_gcc" and actual_keyword_score is not None:
        scoring_score = actual_keyword_score

    if scoring_score >= 90:
        base = 3.5
    elif scoring_score >= 6:
        base = 3.0
    elif scoring_score >= 4:
        base = 2.5
    elif scoring_score >= RELEVANCE_THRESHOLD:
        base = 2.0
    else:
        base = 2.0 if source_tier == "core_gcc" else 1.5
    ct_bonus = {"high": 1.5, "medium": 0.5, "unknown": 0.0, "low": -0.5}
    return min(5.0, max(0.0, base + ct_bonus.get(content_type, 0.0)))


def _stars(score: float) -> str:
    """将 0–5 分转为五星字符串，精度 0.5（半颗星用 '½' 表示，Markdown 纯文本场景）。"""
    full = int(score)
    half = 1 if (score - full) >= 0.5 else 0
    empty = 5 - full - half
    return "★" * full + ("½" if half else "") + "☆" * empty



def _relevance_tier(score: float) -> str:
    """将相关性评分映射到两档分流标签：强相关 / 中等相关。"""
    if score >= 4.0:
        return "强相关"
    else:
        return "中等相关"

def apply_source_relevance_adjustments(article: Article, tank: dict, actual_keyword_score: float, actual_matches: list):
    """
    来源保底只负责不漏文章；强相关仍应由标题/摘要里的真实议题信号决定。
    这样避免 deep_topic/core_gcc 把泛中东或全球议题直接推到强相关。
    """
    if not tank.get("deep_topic"):
        return article

    has_title_strong_signal = any(
        "(标题,+" in m and kw.lower() in m.lower()
        for kw in STRONG_KEYWORDS
        for m in actual_matches
    )
    if has_title_strong_signal:
        article.topic_relevance_score = max(article.topic_relevance_score, 4.0)
    elif actual_keyword_score < 4.0:
        article.topic_relevance_score = min(article.topic_relevance_score, 3.5)
    return article


HEADERS={"User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36","Accept-Language":"en-US,en;q=0.9,ar;q=0.8"}

def fetch_html_requests(url,timeout=10):
    try:r=requests.get(url,headers=HEADERS,timeout=timeout);r.raise_for_status();return r.text
    except Exception as e:log.warning(f"  requests 失败 {url}: {e}");return None

def fetch_html_playwright(url, timeout=20000, browser=None):
    """
    用 Playwright 渲染并返回 HTML。
    browser: 传入已有的 Browser 实例可复用（避免每页重启浏览器），
             为 None 时自动创建独立实例。
    """
    if not HAS_PLAYWRIGHT:
        return None
    try:
        if browser is not None:
            ctx = browser.new_context(user_agent=HEADERS["User-Agent"], locale="en-US")
            pg = ctx.new_page()
            pg.goto(url, timeout=timeout, wait_until="domcontentloaded")
            pg.wait_for_timeout(2000)
            html = pg.content()
            ctx.close()
            return html
        else:
            with sync_playwright() as p:
                b = p.chromium.launch(headless=True)
                c = b.new_context(user_agent=HEADERS["User-Agent"], locale="en-US")
                pg = c.new_page()
                pg.goto(url, timeout=timeout, wait_until="domcontentloaded")
                pg.wait_for_timeout(2000)
                html = pg.content()
                b.close()
                return html
    except Exception as e:
        log.warning(f"  Playwright 失败 {url}: {e}")
        return None

def fetch_html(url, use_playwright=False, req_timeout=10, pw_timeout=20000, browser=None):
    html = fetch_html_requests(url, timeout=req_timeout)
    if use_playwright or (html and len(html) < 2000):
        pw = fetch_html_playwright(url, timeout=pw_timeout, browser=browser)
        if pw and len(pw) > len(html or ""):
            html = pw
    return html

def _clean_article_title(title):
    """清理卡片标题中粘连的栏目、日期和标签元数据。"""
    if not title:
        return title
    t = re.sub(r'\s+', ' ', title.replace("\xa0", " ").replace("&nbsp;", " ").replace("&nbsp", " ")).strip()
    t = re.sub(r'#\S.*$', '', t).strip()
    t = re.sub(
        r'\b(?:Commentary|Analysis|Research|Report|Book|Event|Podcast|Opinion|Interview|Brief|Expert comment|Explainer)\s*'
        r'\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}.*$',
        '',
        t,
        flags=re.IGNORECASE,
    ).strip()
    t = re.sub(r'\s*[—-]\s*$', '', t).strip()
    t = re.sub(r'\s*[—-]\s*(?:[A-Z][A-Za-z.\'’ -]{2,80})?\s*\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}.*$', '', t).strip()
    t = re.sub(r'\s*[—-]\s*[A-Z][A-Za-z.\'’ -]{2,80}\s*/\s*$', '', t).strip()
    t = re.sub(r'\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}.*$', '', t).strip()
    t = re.sub(r'\s*[—-]\s*$', '', t).strip()
    return t or title.strip()

def extract_articles_from_page(html,base_url,page_url,selectors,tank_name):
    soup=BeautifulSoup(html,"html.parser");articles=[];seen=set()
    for c in soup.select(selectors.get("article","article")):
        te=c.select_one(selectors.get("title","h2 a, h3 a"))
        t="";h=""
        if te:
            t=te.get_text(strip=True);h=te.get("href","")
        # 标题在链接内但无文本（如图片链接）→ 尝试 heading+link 组合（适配 React 卡片式布局）
        if not t or len(t)<5:
            heading=c.select_one("h2,h3,h4,[class*='title'],[class*='heading']")
            link_el=c.select_one("a[href]")
            if heading and link_el:
                t=heading.get_text(strip=True);h=link_el.get("href","")
            elif not te:
                te=c.select_one("a[href]")
                if not te:continue
                t=te.get_text(strip=True);h=te.get("href","")
        if not t or len(t)<5:continue
        ds_from_title=normalize_date(t)
        t=_clean_article_title(t)
        if h.startswith("/"):h=base_url.rstrip("/")+h
        elif not h.startswith("http"):h=base_url.rstrip("/")+"/"+h
        if h in seen:continue
        # 在第一轮就过滤导航项，避免污染 seen 集合，防止阻断后续兜底扫描
        if not _is_likely_article(t,h):continue
        seen.add(h)
        se=c.select_one(selectors.get("snippet","p"));sn=se.get_text(strip=True) if se else ""
        de=c.select_one(selectors.get("date","time"));ds=None
        if de:ds=normalize_date(de.get("datetime") or de.get_text(strip=True))
        if not ds and ds_from_title:
            ds=ds_from_title
        # 日期选择器未命中时，扫描卡片内所有小元素寻找日期文本
        if not ds or len(ds) < 7:
            for el in c.find_all(["span","time","em","small","p","div"],limit=20):
                txt=el.get_text(strip=True)
                if 5 < len(txt) < 60:
                    cand=normalize_date(txt)
                    if cand and len(cand) >= 7:
                        ds=cand;break
        articles.append({"title":t,"url":h,"snippet":sn[:500],"date":ds})
    for lk in soup.find_all("a",href=True):
        t=lk.get_text(strip=True);h=lk["href"]
        if len(t)<10 or len(t)>300:continue
        if any(s in t.lower() for s in ["home","about","contact","menu","login","search","privacy","cookie","terms","©","copyright","facebook","twitter","linkedin","instagram"]):continue
        if any(s in h.lower() for s in ["#","javascript:","mailto:","tel:","facebook.com","twitter.com","linkedin.com"]):continue
        if h.startswith("/"):h=base_url.rstrip("/")+h
        elif not h.startswith("http"):h=base_url.rstrip("/")+"/"+h
        if h in seen:continue
        if not _is_likely_article(t,h):continue
        seen.add(h)
        pa=lk.parent;sn="";ds=normalize_date(t)
        if pa:
            pt=pa.find_next_sibling("p") or pa.find("p")
            sn=pt.get_text(strip=True)[:500] if pt else ""
            if not ds:
                for el in pa.find_all(["span","time","em","small","p","div"],limit=20):
                    cand=normalize_date(el.get_text(strip=True))
                    if cand and len(cand) >= 7:
                        ds=cand;break
        t=_clean_article_title(t)
        articles.append({"title":t,"url":h,"snippet":sn,"date":ds})
    # 最终过滤（主要针对兜底扫描的结果）
    articles=[a for a in articles if _is_likely_article(a["title"],a["url"])]
    return articles

# ── 过滤规则（从 filter_rules.yaml 加载，缺失时用内置默认值） ────────

_FILTER_RULES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "filter_rules.yaml")

# 内置默认值（与 filter_rules.yaml 保持同步，作为 fallback）
_NAV_EXACT_DEFAULT = {
    "publications","research","our experts","experts","advisory services",
    "solutions","data portal","event calendar","events","job opportunities","jobs",
    "careers","life at","work with us","newsroom","media center","about us","about",
    "our offerings","school of public policy","today","story","our story","history",
    "board of trustees","contact us","newsletter","subscribe","archives","library",
    "programs","projects","blog","podcasts","podcast","videos","video","gallery","press",
    "donate","faq","sitemap","resources","services","overview","mission","vision",
    "team","staff","fellows","scholars","partnerships","sponsors","annual report",
    "annual reports","journal","journals","books","book","magazine","proceedings",
    "commentary","opinion","editorial","press releases","media","news","all news",
    "more","read more","see more","view all","show more","load more","next","previous",
    "research & commentary","diversity, equity, and inclusion","analysis",
    "policy briefs","opinions","workshops","interviews","multimedia","infographics",
    "recent news","all articles","all publications","all research","all reports",
    "political transformations","security studies","economic trends",
    "technological developments","socio-cultural interactions","media trends",
    "strategic foresight","climate change","majority world",
    "latin america","africa","russia","asia trends","sharepoint",
    "education & community development","message from his highness",
    "message from the chairman","our team","our partners","our mission",
    "expo 2020 dubai","youthinkgulf",
    "strategic and international studies","sound of thought podcast",
    "للمزيد","المزيد","الرئيسية","اتصل بنا","من نحن","الأخبار",
    "مجلة التنمية والسياسات الاقتصادية",
    "in the news","agsiw in the news","media mentions","press coverage",
    "our fellows","agsiw fellows","senior fellows","visiting fellows",
    "board of directors","board of advisors","advisory board",
    "support our work","get involved",
    "who we are","mission and history","our history","our mission",
    "in memoriam","memoriam",
    "commercialization","geoinformatics","technology economics",
    "sme center","sme centre","small and medium enterprises",
    "entrepreneurship and sme development","entrepreneurship",
    "local, regional and international cooperation",
    "economic policy modeling","economic policy modelling",
    "training and capacity building","capacity building",
    "information and communication technology",
    "environment and natural resources","food and water security",
    "energy and environment","marine and fisheries",
    "biotechnology","petroleum research","refining and petrochemicals",
    "water resources","agriculture","aridland agriculture",
    "periodic reports","regular reports","technical reports","annual reports",
    "working papers","working paper series","occasional papers",
    "economic policy modeling and formulation","economic policy modelling and formulation",
    "smes development","center for smes","centre for smes","sme development center",
    "arab planning institute","arab planning institute (api)",
    "kuwait arab planning institute",
    "malcolm h. kerr carnegie middle east center",
    "the malcolm kerr carnegie middle east center",
    "carnegie middle east center",
    "king abdullah petroleum studies and research centre",
    "king faisal center for research and islamic studies",
    "emirates center for strategic studies and research",
    "gulf research center","dubai public policy research center",
    "al jazeera centre for studies",
    "arab center for research and policy studies",
    "publications and reports","reports and publications",
    "research and analysis","papers and reports",
    "latest publications","recent publications","all publications",
    "featured research","highlights",
}

_NAV_URL_PATTERNS_DEFAULT = [
    r'/category/', r'/categories/', r'/index/', r'/mainpage/category/',
    r'/mainpage/index/', r'/list/', r'/tag/', r'/tags/', r'/topic/',
    r'/topics/', r'/activity/category/', r'/multimedia/', r'/release/category/',
    r'/release/index/', r'sharepoint\.com', r'\.sharepoint\.',
    r'^tel:', r'^mailto:',
    r'/author/', r'/authors/', r'/researcher/', r'/researchers/',
    r'/profile/', r'/staff/', r'/team/', r'/experts/',
    r'/podcast', r'/podcasts',
    r'/featured/', r'/units/', r'/about-us/',
    r'/biography/', r'/bio/', r'/in-the-news/', r'/media-mention',
    r'/leadership/', r'/board/', r'/fellows/',
    r'/event/', r'/events/', r'/webinar/', r'/conference/',
    r'/newsletter/', r'/newsletters/', r'/subscribe',
    r'[?&]tabid=',
    r'/sector[s]?/', r'/division[s]?/', r'/department[s]?/',
    r'/research-center[s]?/', r'/research-centre[s]?/',
    r'/center[s]?/(?!brookings|carnegie|doha|gulf)',
    r'/service[s]?/', r'/program[s]?/', r'/about/?$',
]

def _load_filter_rules():
    """从 filter_rules.yaml 加载黑名单规则；文件缺失或 pyyaml 未装时用内置默认值。"""
    try:
        import yaml
    except ImportError:
        log.warning("⚠️  未安装 pyyaml，使用内置过滤规则（pip install pyyaml 可启用外置配置）")
        return _NAV_EXACT_DEFAULT, _NAV_URL_PATTERNS_DEFAULT
    try:
        with open(_FILTER_RULES_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        exact    = {str(x).lower().strip() for x in data.get("nav_exact", [])}
        patterns = [str(x) for x in data.get("nav_url_patterns", [])]
        log.info(f"📋 过滤规则已加载：{len(exact)} 条精确匹配，{len(patterns)} 条 URL 模式")
        return exact, patterns
    except FileNotFoundError:
        log.debug("filter_rules.yaml 未找到，使用内置默认规则")
    except Exception as e:
        log.warning(f"⚠️  filter_rules.yaml 加载失败（{e}），使用内置默认规则")
    return _NAV_EXACT_DEFAULT, _NAV_URL_PATTERNS_DEFAULT

_NAV_EXACT, _NAV_URL_PATTERNS = _load_filter_rules()

def _is_likely_article(title,url):
    """判断是否可能是真正的文章（而非导航/菜单链接）"""
    tl=title.lower().strip()
    ul=url.lower()
    # 0. 标题是电话号码或纯数字
    if re.match(r'^[\d\s\-\+\(\)]+$',tl):return False
    # 0a. 分类/专题页标题常带计数，如 "Economic Security(2085)"
    if re.match(r'^[A-Za-z][A-Za-z &,\-/]+?\(\d+\)$',title.strip()):return False
    # 0b. 标题是物理地址（含 building/road/street/block/P.O. 等）
    if re.search(r'\b(building|road|street|block|floor|p\.?\s*o\.?\s*box|awali|manama|riyadh|doha)\b',tl) and re.search(r'\d',tl):return False
    # 1. URL含分类/索引/作者路径 → 不是文章
    for pat in _NAV_URL_PATTERNS:
        if re.search(pat,ul):return False
    # 2. 标题完全匹配导航黑名单
    if tl in _NAV_EXACT:return False
    # 3. 标题以 "view all" / "see all" / "browse" 开头
    if re.match(r'^(view all|see all|browse|show all|all )\b',tl):return False
    # 3b. 标题是"XXX Now Available"格式（期刊上新通知）
    if re.search(r'\bnow available\b',tl):return False
    # 3c. 标题看起来像人名（2-4个首字母大写单词，无常见文章词汇）
    orig_words=title.strip().split()
    if 2<=len(orig_words)<=4:
        all_capitalized=all(w[0].isupper() and w.isalpha() for w in orig_words if len(w)>1)
        has_article_words=any(w.lower() in {"the","a","an","of","in","on","for","and","to","by","with","from","how","why","what","new","key"} for w in orig_words)
        if all_capitalized and not has_article_words:
            # 大概率是人名，除非URL含 article/report/paper 等关键词（路径段或slug片段均可）
            if not re.search(r'[/\-](article|report|paper|study|brief|analysis|opinion|blog)[s/\-]', ul):
                return False
    # 4. 标题太短（≤3个词且无数字/年份）→ 检查URL深度
    words=tl.split()
    if len(words)<=3 and not re.search(r'\d{4}',tl):
        from urllib.parse import urlparse
        path=urlparse(url).path.strip("/")
        segments=[s for s in path.split("/") if s]
        if len(segments)<3:return False
        last_seg=segments[-1] if segments else ""
        if len(last_seg)<15:return False
    # 5. URL路径指向通用顶层页面
    from urllib.parse import urlparse
    path=urlparse(url).path.strip("/").lower()
    nav_paths={"research","publications","about","contact","events","newsroom",
        "media","careers","jobs","work-with-us","our-offerings","programs",
        "our-experts","school-of-public-policy","about-kapsarc",
        "en","en-us","ar","","en/publications","en/research"}
    if path in nav_paths:return False
    return True

_MONTH_MAP = {
    "jan":"01","feb":"02","mar":"03","apr":"04","may":"05","jun":"06",
    "jul":"07","aug":"08","sep":"09","oct":"10","nov":"11","dec":"12",
    "january":"01","february":"02","march":"03","april":"04","june":"06",
    "july":"07","august":"08","september":"09","october":"10",
    "november":"11","december":"12",
}

def normalize_date(date_str):
    """
    将任意格式日期字符串统一为 YYYY-MM-DD（或 YYYY-MM / YYYY）。
    无法解析则返回 None。
    支持：ISO 8601、英文月名、数字斜线/点号分隔、纯年份等。
    """
    if not date_str:
        return None
    d = re.sub(
        r'\b(Commentary|Analysis|Research|Report|Book|Event|Podcast|Opinion|Interview|Brief|Explainer)(?=\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})',
        r'\1 ',
        date_str.strip(),
        flags=re.IGNORECASE,
    )
    # 已是标准格式
    if re.match(r'^\d{4}-\d{2}-\d{2}$', d):
        return d
    if re.match(r'^\d{4}-\d{2}$', d):
        return d
    if re.match(r'^\d{4}$', d) and 1990 <= int(d) <= 2035:
        return d
    # ISO 8601 含时间：2024-03-15T10:30:00Z
    m = re.match(r'^(\d{4}-\d{2}-\d{2})[T ]', d)
    if m:
        return m.group(1)
    dl = d.lower()
    # "March 15, 2024" 或 "Mar 15 2024"
    m = re.match(r'^([a-z]+)\s+(\d{1,2})[,\s]+(\d{4})', dl)
    if m:
        mn = _MONTH_MAP.get(m.group(1)) or _MONTH_MAP.get(m.group(1)[:3])
        if mn:
            return f"{m.group(3)}-{mn}-{int(m.group(2)):02d}"
    # "15 March 2024" 或 "15 Mar 2024"
    m = re.match(r'^(\d{1,2})\s+([a-z]+)\s+(\d{4})', dl)
    if m:
        mn = _MONTH_MAP.get(m.group(2)) or _MONTH_MAP.get(m.group(2)[:3])
        if mn:
            return f"{m.group(3)}-{mn}-{int(m.group(1)):02d}"
    # "March 2024"（无日）
    m = re.match(r'^([a-z]+)\s+(\d{4})$', dl)
    if m:
        mn = _MONTH_MAP.get(m.group(1)) or _MONTH_MAP.get(m.group(1)[:3])
        if mn:
            return f"{m.group(2)}-{mn}"
    # "2024/03/15" 或 "2024.03.15"
    m = re.match(r'^(\d{4})[/.](\d{1,2})[/.](\d{1,2})$', d)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    # "15/03/2024" 或 "15.03.2024"（DD/MM/YYYY）
    m = re.match(r'^(\d{1,2})[/.](\d{1,2})[/.](\d{4})$', d)
    if m and int(m.group(2)) <= 12:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    # 混合文本中搜索完整日期（如 "Studies 20 April, 2026" 或 "Published: March 15, 2024"）
    m = re.search(r'\b(\d{1,2})\s+([a-z]+)\s+(\d{4})\b', dl)
    if m:
        mn = _MONTH_MAP.get(m.group(2)) or _MONTH_MAP.get(m.group(2)[:3])
        if mn:
            return f"{m.group(3)}-{mn}-{int(m.group(1)):02d}"
    m = re.search(r'\b([a-z]+)\s+(\d{1,2})[,\s]+(\d{4})\b', dl)
    if m:
        mn = _MONTH_MAP.get(m.group(1)) or _MONTH_MAP.get(m.group(1)[:3])
        if mn:
            return f"{m.group(3)}-{mn}-{int(m.group(2)):02d}"
    # 含年份的混合字符串，提取最靠前的 4 位年份作兜底
    m = re.search(r'\b(20\d{2}|19\d{2})\b', d)
    if m:
        return m.group(1)
    return None

def fetch_rss_articles(feed_url,tank_name):
    if not HAS_FEEDPARSER:return []
    try:
        feed=feedparser.parse(feed_url)
        if feed.bozo and not feed.entries:log.warning(f"  RSS 解析失败 {feed_url}");return []
        arts=[]
        for e in feed.entries[:30]:
            t=e.get("title","").strip();lk=e.get("link","").strip()
            if not t or not lk:continue
            ds=None
            for df in["published","updated","created"]:
                pa=df+"_parsed"
                if hasattr(e,pa) and getattr(e,pa):
                    try:ds=datetime(*getattr(e,pa)[:6]).strftime("%Y-%m-%d")
                    except:pass
                    break
            if not ds:ds=normalize_date(e.get("published",e.get("updated","")))
            sn=""
            if hasattr(e,"summary"):sn=re.sub(r'<[^>]+>','',e.summary).strip()[:500]
            elif hasattr(e,"description"):sn=re.sub(r'<[^>]+>','',e.description).strip()[:500]
            arts.append({"title":t,"url":lk,"snippet":sn,"date":ds,"fetch_method":"rss"})
        log.info(f"  📡 RSS获取 {len(arts)} 条: {feed_url}");return arts
    except Exception as e:log.warning(f"  RSS失败 {feed_url}: {e}");return []

RSS_MIN_THRESHOLD = 3  # RSS获取≥3篇则跳过HTML

# GCC 六国规范名称集合（用于匹配 Carnegie metadata）
CARNEGIE_GCC_REGIONS = {
    "saudi arabia", "united arab emirates", "qatar",
    "kuwait", "bahrain", "oman", "gulf",
}

def verify_carnegie_metadata(article_url, req_timeout=10, browser=None, pw_timeout=20000):
    """
    拉取 Carnegie 文章详情页，提取嵌入的 JSON metadata 中的 regions 字段，
    判断是否与 GCC 六国相关。返回 True/False/None（None = 拉取失败，保守保留）。
    """
    html = fetch_html_requests(article_url, timeout=req_timeout)
    if not html and browser is not None:
        html = fetch_html_playwright(article_url, timeout=pw_timeout, browser=browser)
    if not html:
        return None
    m = re.search(r'"regions"\s*:\s*\[([^\]]*)\]', html)
    if not m:
        return None
    regions_raw = m.group(1).lower()
    return any(r in regions_raw for r in CARNEGIE_GCC_REGIONS)

def scrape_think_tank(tank, use_playwright=False, max_per_tank=50, browser=None, dry_run=False,
                     include_high_risk=False, filter_undated=True, max_age_days=30):
    nm, co, ti, bu = tank["name"], tank["country"], tank["tier"], tank["base_url"]
    compliance = get_compliance_rule(bu)
    if not compliance.get("allow_scrape", True) and not include_high_risk:
        alt_path = compliance.get("metadata_allowed_path") or "人工阅读 / 官方授权路径"
        log.warning(
            f"⛔ {nm}: 合规规则禁止自动抓取（risk={compliance.get('risk_level','unknown')}），已跳过；"
            f"替代路径：{alt_path}；如需人工覆盖使用 --include-high-risk"
        )
        return [], []
    crawl_delay = float(compliance.get("crawl_delay_seconds", 1.0) or 1.0)
    # 站点级 Playwright 开关：Carnegie 这类 SPA 站点强制启用
    use_playwright = use_playwright or tank.get("use_playwright", False)
    log.info(f"📚 {nm} ({co}) [{ti}]")
    raw = []
    req_to = tank.get("requests_timeout", 10)
    pw_to  = tank.get("playwright_timeout", 20000)

    # ── 第一优先级：RSS ──
    rss_feeds = tank.get("rss_feeds", [])
    if rss_feeds:
        for fu in rss_feeds:
            raw.extend(fetch_rss_articles(fu, nm))
        if len(raw) >= RSS_MIN_THRESHOLD:
            log.info(f"  📡 RSS获取 {len(raw)} 条（≥{RSS_MIN_THRESHOLD}），跳过HTML抓取")
        else:
            if raw:
                log.info(f"  📡 RSS仅获取 {len(raw)} 条（<{RSS_MIN_THRESHOLD}），补充HTML抓取")
            else:
                log.info(f"  📡 RSS无结果，回退HTML抓取")
            # RSS不够，补充HTML
            for pp in tank["pages"]:
                url = bu.rstrip("/") + pp
                log.info(f"  🌐 抓取: {url}")
                try:
                    html = fetch_html(url, use_playwright=use_playwright, req_timeout=req_to, pw_timeout=pw_to, browser=browser)
                    if not html: continue
                    items = extract_articles_from_page(html, bu, url, tank["selectors"], nm)
                    max_per_page = tank.get("max_per_page", 20 if tank.get("deep_topic") else 50)
                    if len(items) > max_per_page:
                        items = items[:max_per_page]
                    log.info(f"    发现 {len(items)} 个候选条目（已限 {max_per_page}/页）")
                    for it in items[:3]: log.debug(f"    [候选] {it['title'][:80]}")
                    raw.extend(items)
                except Exception as e:
                    log.warning(f"  ⚠️ 单页抓取失败 {url}: {e}")
                    continue
                time.sleep(crawl_delay)
    else:
        # ── 无RSS，直接HTML ──
        for pp in tank["pages"]:
            url = bu.rstrip("/") + pp
            log.info(f"  🌐 抓取: {url}")
            try:
                html = fetch_html(url, use_playwright=use_playwright, req_timeout=req_to, pw_timeout=pw_to, browser=browser)
                if not html: continue
                items = extract_articles_from_page(html, bu, url, tank["selectors"], nm)
                max_per_page = tank.get("max_per_page", 20 if tank.get("deep_topic") else 50)
                if len(items) > max_per_page:
                    items = items[:max_per_page]
                log.info(f"    发现 {len(items)} 个候选条目（已限 {max_per_page}/页）")
                for it in items[:3]: log.debug(f"    [候选] {it['title'][:80]}")
                raw.extend(items)
            except Exception as e:
                log.warning(f"  ⚠️ 单页抓取失败 {url}: {e}")
                continue
            time.sleep(crawl_delay)

    # ── 去重 ──
    seen = set(); unique = []
    for it in raw:
        if it["url"] not in seen: seen.add(it["url"]); unique.append(it)

    # ── 四层漏斗筛选 ──
    results = []
    filtered_out = []  # v2.4.1: 试运行模式收集第三层硬过滤剔除的文章
    for it in unique:
        t, sn, u = it["title"], it.get("snippet", ""), it["url"]
        ct, pr = classify_content_type(t, u)
        if ct == "excluded":
            log.debug(f"    ❌ 排除: {t[:60]}")
            # === v2.4.1 新增：试运行模式下收集被硬过滤的文章 ===
            if dry_run:
                t_lower = t.lower()
                filter_hit = next((w for w in _KW["filter_set"] if w in t_lower), "exclude_pattern")
                filtered_out.append({"title": t, "url": u, "source": nm, "filter_hit": filter_hit})
            continue
        actual_ks, actual_mk = compute_keyword_score(t, sn)
        if ti == "core_gcc":
            ks, mk = 99.0, ["core_gcc_auto_pass"] + actual_mk
        elif tank.get("deep_topic"):
            # 深层专题页来源本身是 GCC 主题，但不能遮蔽标题真实强信号。
            if actual_ks >= 5.0:
                ks, mk = actual_ks, actual_mk + ["deep_topic_auto_pass"]
            else:
                ks, mk = 5.0, (actual_mk or []) + ["deep_topic_auto_pass"]
        else:
            ks, mk = actual_ks, actual_mk
            if ks < RELEVANCE_THRESHOLD: log.debug(f"    ⏭️ 评分不足({ks}): {t[:60]}"); continue
        article = Article(title=t, url=u, source=nm, source_country=co, source_tier=ti,
            source_region=tank.get("region",""),
            source_org_type=tank.get("org_type",""),
            source_topics=list(tank.get("topics",[])),
            date=normalize_date(it.get("date")), snippet=sn, keyword_score=ks, content_type=ct,
            priority=pr, topic_relevance_score=compute_topic_relevance_score(
                ks, ct, source_tier=ti, actual_keyword_score=actual_ks,
            ),
            matched_keywords=mk, fetch_method=it.get("fetch_method", "html"))
        apply_source_relevance_adjustments(article, tank, actual_ks, actual_mk)
        # === v2.4.1 新增：检测降权词命中，写入 _funnel_debug（供试运行模式输出）===
        # demote_set：标题+摘要均检查（demote_check_summary=True 时）
        # title_only_demote_set：仅检查标题（避免摘要引用误触发，如 NATO）
        _title_lower = t.lower()
        _text_demote = _title_lower
        if _KW["demote_check_summary"]:
            _text_demote += " " + sn.lower()
        _demote_hits = [w for w in _KW["demote_set"] if w in _text_demote]
        _demote_hits += [w for w in _KW["title_only_demote_set"] if w in _title_lower]
        if _demote_hits:
            article._funnel_debug = {
                "demote_hits": _demote_hits,
                "demote_penalty": _KW["max_penalty"],
            }
        results.append(article)

    # ── Carnegie 二次验证：用官方 regions metadata 替代关键词匹配 ──
    # 仅验证最终时间窗口内可能保留的文章；旧文和无日期文章后续会被全局过滤，
    # 无需逐篇访问详情页，避免在 30 天日报场景里验证大量历史链接。
    if "Carnegie" in nm and tank.get("deep_topic"):
        verified = []
        verify_total = 0
        skipped_final_filter = 0
        cutoff = None
        if max_age_days and max_age_days > 0:
            cutoff = (datetime.now() - timedelta(days=max_age_days)).strftime('%Y-%m-%d')
        for a in results:
            if filter_undated and not a.date:
                verified.append(a)
                skipped_final_filter += 1
                continue
            if cutoff and a.date and not _date_gte(a.date, cutoff):
                verified.append(a)
                skipped_final_filter += 1
                continue
            verify_total += 1
            v = verify_carnegie_metadata(a.url, browser=browser, pw_timeout=pw_to)
            if v is False:
                log.debug(f"    🚫 Carnegie metadata 排除: {a.title[:60]}")
                continue
            verified.append(a)
            time.sleep(max(0.3, min(crawl_delay, 2.0)))  # 礼貌延迟
        log.info(
            f"  🔍 Carnegie metadata 验证: {len(results)} → {len(verified)}"
            f"（实际访问 {verify_total} 篇，跳过后续必过滤 {skipped_final_filter} 篇）"
        )
        results = verified

    # ── 按日期排序（最新优先），有日期的排前面 ──
    def _sort_key(a):
        d = a.date or ""
        # 标准化日期用于排序（越新越靠前）
        if re.match(r'\d{4}-\d{2}-\d{2}', d): return (0, d)  # 有标准日期
        if re.match(r'\d{4}', d): return (0, d)               # 有年份
        return (1, "")                                          # 无日期排最后
    results.sort(key=_sort_key, reverse=True)

    # ── 限制每站最大数量 ──
    total_before = len(results)
    if len(results) > max_per_tank:
        results = results[:max_per_tank]
        log.info(f"  ✂️  截取最新 {max_per_tank} 篇（共 {total_before} 篇通过筛选）")

    rss_n = sum(1 for r in results if r.fetch_method == "rss")
    html_n = len(results) - rss_n
    log.info(f"  ✅ {nm}: {len(unique)} 篇候选 → {len(results)} 篇保留（RSS:{rss_n} HTML:{html_n}）\n")
    return results, filtered_out  # v2.4.1: 返回元组（兼容 dry_run 模式）

def _date_gte(date_str: str, cutoff: str) -> bool:
    """
    判断 date_str（YYYY-MM-DD / YYYY-MM / YYYY）是否 >= cutoff（YYYY-MM-DD）。
    不完整日期取最早可能值（月初 / 年初），保守保留。
    """
    if not date_str:
        return False
    if re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
        cmp = date_str
    elif re.match(r'^\d{4}-\d{2}$', date_str):
        cmp = date_str + "-28"   # 取月末（28日所有月通用），保守保留当月文章
    elif re.match(r'^\d{4}$', date_str):
        cmp = date_str + "-12-31"  # 取年末，保守保留（不确定具体月份时不误删）
    else:
        return True  # 格式未知，保守保留
    return cmp >= cutoff

def run_scraper(tanks=None, use_playwright=False, enable_ai=False, api_key=None,
                countries=None, regions=None, org_types=None, topics=None,
                max_per_tank=50, dedup_db=DEDUP_DB_PATH, dedup_days=1,
                filter_undated=True, max_age_days=30, dry_run=False,
                include_high_risk=False):
    if tanks is None:
        tanks = THINK_TANKS
    if countries:
        country_filter = [c.lower() for c in countries]
        tanks = [t for t in tanks if t["country"].lower() in country_filter]
    if regions:
        region_filter = [r.lower() for r in regions]
        tanks = [t for t in tanks if t.get("region","").lower() in region_filter]
    if org_types:
        otype_filter = [o.lower() for o in org_types]
        tanks = [t for t in tanks if t.get("org_type","").lower() in otype_filter]
    if topics:
        topic_filter = [tp.lower() for tp in topics]
        tanks = [t for t in tanks if any(tp in [x.lower() for x in t.get("topics",[])] for tp in topic_filter)]

    print("=" * 60)
    print(f"GCC智库研究抓取系统 v2.4\n运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n目标智库: {len(tanks)} 个")
    # 分维度统计
    _r = {}
    for t in tanks:
        _r.setdefault(t.get("region","?"), 0); _r[t.get("region","?")] += 1
    print(f"  地区分布: " + " | ".join(f"{k}×{v}" for k,v in sorted(_r.items())))
    needs_playwright = use_playwright or any(t.get("use_playwright") for t in tanks)
    print(f"JS渲染: {'✅ Playwright' if needs_playwright and HAS_PLAYWRIGHT else '❌ 仅requests'}")
    print(f"AI筛选: {'✅ 已启用 (' + ai_client.provider_info() + ')' if enable_ai and HAS_AI else '❌ 未启用'}")
    print(f"RSS:    {'✅ feedparser' if HAS_FEEDPARSER else '❌ 未安装'}")
    if dedup_db:
        print(f"去重DB: {dedup_db}（窗口 {dedup_days} 天）")
    else:
        print(f"去重DB: ❌ 已禁用")
    print(f"每站上限: {max_per_tank} 篇")
    if max_age_days:
        cutoff_display = (datetime.now() - timedelta(days=max_age_days)).strftime('%Y-%m-%d')
        print(f"时效过滤: 近 {max_age_days} 天（{cutoff_display} 之后）")
    print("=" * 60 + "\n")

    all_articles = []
    all_filtered_out = []  # v2.4.1: 汇总所有被第三层硬过滤的文章（试运行模式用）

    # ── 抓取阶段：如果启用 Playwright 或有站点强制需要，复用一个浏览器实例 ──
    if needs_playwright and HAS_PLAYWRIGHT:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            for tk in tanks:
                try:
                    _arts, _fout = scrape_think_tank(
                        tk, use_playwright=use_playwright, max_per_tank=max_per_tank,
                        browser=browser, dry_run=dry_run, include_high_risk=include_high_risk,
                        filter_undated=filter_undated, max_age_days=max_age_days
                    )
                    all_articles.extend(_arts)
                    all_filtered_out.extend(_fout)
                except Exception as e:
                    log.error(f"❌ 抓取 {tk['name']} 失败: {e}")
            browser.close()
    else:
        for tk in tanks:
            try:
                _arts, _fout = scrape_think_tank(
                    tk, use_playwright=False, max_per_tank=max_per_tank, dry_run=dry_run,
                    include_high_risk=include_high_risk,
                    filter_undated=filter_undated, max_age_days=max_age_days
                )
                all_articles.extend(_arts)
                all_filtered_out.extend(_fout)
            except Exception as e:
                log.error(f"❌ 抓取 {tk['name']} 失败: {e}")

    # ── 跨智库 URL 去重（防同一文章被多个来源重复收录，与 SQLite 去重互补）──
    _seen_in_run: set = set()
    _unique_in_run = []
    for _a in all_articles:
        if _a.url not in _seen_in_run:
            _seen_in_run.add(_a.url)
            _unique_in_run.append(_a)
    if len(_unique_in_run) < len(all_articles):
        log.info(f"🔁 跨来源去重: 去除 {len(all_articles) - len(_unique_in_run)} 篇重复文章")
    all_articles = _unique_in_run

    # ── AI 辅助筛选 ──
    if enable_ai:
        all_articles = ai_classify_batch(all_articles, api_key)
        all_articles = [a for a in all_articles if a.ai_verdict != "not_relevant"]

    # ── SQLite 增量去重：过滤 dedup_days 天内已处理过的文章 ──
    dedup_filtered = 0
    if dedup_db:
        seen_urls = load_seen_urls(dedup_db, days=dedup_days)
        before_dedup = len(all_articles)
        all_articles = [a for a in all_articles if a.url not in seen_urls]
        dedup_filtered = before_dedup - len(all_articles)
        if dedup_filtered:
            log.info(f"🔁 去重过滤: 跳过 {dedup_filtered} 篇（{dedup_days}天内已处理），剩余 {len(all_articles)} 篇新文章")

    # ── 无日期过滤：机构介绍页/导航页通常无发布日期，以此兜底过滤残余噪声 ──
    if filter_undated:
        before_ud = len(all_articles)
        all_articles = [a for a in all_articles if a.date]
        removed_ud = before_ud - len(all_articles)
        if removed_ud:
            log.info(f"📅 无日期过滤: 移除 {removed_ud} 篇无日期文章，剩余 {len(all_articles)} 篇")

    # ── 时效过滤：只保留 max_age_days 天内的文章 ──
    if max_age_days and max_age_days > 0:
        cutoff = (datetime.now() - timedelta(days=max_age_days)).strftime('%Y-%m-%d')
        before_age = len(all_articles)
        all_articles = [a for a in all_articles if _date_gte(a.date, cutoff)]
        removed_age = before_age - len(all_articles)
        if removed_age:
            log.info(f"⏰ 时效过滤: 移除 {removed_age} 篇 {max_age_days} 天前的文章（截止 {cutoff}），剩余 {len(all_articles)} 篇")

    # ── 按优先级排序 ──
    priority_order = {"priority_read": 0, "normal": 1, "low": 2}
    all_articles.sort(key=lambda a: priority_order.get(a.priority, 1))

    print("\n" + "=" * 60 + f"\n抓取完成: 共 {len(all_articles)} 篇相关文章")
    by_priority = {}
    for a in all_articles:
        by_priority.setdefault(a.priority, []).append(a)
    for p, ar in by_priority.items():
        print(f"  {p}: {len(ar)} 篇")
    rss_count = sum(1 for a in all_articles if a.fetch_method == "rss")
    if rss_count:
        print(f"  (其中 RSS 获取: {rss_count} 篇)")
    print("=" * 60)
    return all_articles, dedup_filtered, all_filtered_out  # v2.4.1: 三元组

_REGION_LABEL = {"gcc":"🇦🇪 GCC核心", "mena":"🌍 泛MENA", "western":"🌐 域外英美", "":"其他"}
_ORGTYPE_LABEL = {"official":"🏛️ 官方/政府", "university":"🎓 大学研究", "independent":"🔬 独立智库", "":"其他"}
_TOPIC_LABEL   = {"energy":"⚡能源","security":"🛡️安全","economy":"💰经济","politics":"🏛政治","society":"👥社会","technology":"💻技术"}

def export_markdown(articles, filepath=None, group_by=None):
    now=datetime.now().strftime("%Y-%m-%d %H:%M")
    filepath=filepath or f"gcc_research_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
    L=[f"# GCC智库研究动态\n",f"> 抓取时间: {now} | 文章总数: {len(articles)} 篇 | 系统: v2.4 — 成都创新金融研究院\n"]

    def _table_rows(ar):
        rows=[]
        rows.append("| 日期 | 平台 | 区域 | 类型 | 议题 | 相关性 | 标题 | 中文标题 | 链接 |")
        rows.append("|------|------|------|------|------|--------|------|----------|------|")
        for a in ar:
            d=a.date if a.date else "-"
            tc=a.title.replace("|","–").replace("\n"," ").strip()
            if a.topic_relevance_score >= 4.0:
                tc = "⭐ " + tc
            cn=(a.title_cn or "-").replace("|","–").replace("\n"," ").strip()
            rg=_REGION_LABEL.get(a.source_region, a.source_region or "-")
            ot=_ORGTYPE_LABEL.get(a.source_org_type, a.source_org_type or "-")
            tps=" ".join(_TOPIC_LABEL.get(tp,tp) for tp in a.source_topics) or "-"
            rel=f"{_stars(a.topic_relevance_score)} {a.topic_relevance_score:.1f}"
            rows.append(f"| {d} | {a.source.replace('|','–')} | {rg} | {ot} | {tps} | {rel} | {tc} | {cn} | [原文]({a.url}) |")
        return rows

    if group_by == "region":
        groups = {}
        for a in articles:
            k = a.source_region or "other"
            groups.setdefault(k, []).append(a)
        for k in ["gcc","mena","western","other"]:
            ar = groups.get(k,[])
            if not ar: continue
            L.append(f"---\n## {_REGION_LABEL.get(k,k)} ({len(ar)} 篇)\n")
            L.extend(_table_rows(ar)); L.append("")
    elif group_by == "org_type":
        groups = {}
        for a in articles:
            k = a.source_org_type or "other"
            groups.setdefault(k, []).append(a)
        for k in ["official","university","independent","other"]:
            ar = groups.get(k,[])
            if not ar: continue
            L.append(f"---\n## {_ORGTYPE_LABEL.get(k,k)} ({len(ar)} 篇)\n")
            L.extend(_table_rows(ar)); L.append("")
    elif group_by == "topic":
        groups = {}
        for a in articles:
            for tp in (a.source_topics or ["other"]):
                groups.setdefault(tp, []).append(a)
        for k in ["energy","security","economy","politics","society","technology","other"]:
            ar = groups.get(k,[])
            if not ar: continue
            L.append(f"---\n## {_TOPIC_LABEL.get(k,k)} 议题 ({len(ar)} 篇)\n")
            L.extend(_table_rows(ar)); L.append("")
    else:
        # 默认：按相关性评分两档分流（强相关 / 中等相关）
        gs={
            "强相关": ("⭐ 推荐阅读（强相关 · 核心议题）", []),
            "中等相关": ("📄 中等相关（常规研究 · 背景参考）", []),
        }
        for a in articles:
            gs[_relevance_tier(a.topic_relevance_score)][1].append(a)
        for key in ["强相关", "中等相关"]:
            lb, ar = gs[key]
            if not ar: continue
            L.append(f"---\n## {lb} ({len(ar)} 篇)\n")
            L.extend(_table_rows(ar)); L.append("")

    with open(filepath,"w",encoding="utf-8") as f:f.write("\n".join(L))
    log.info(f"📝 Markdown 报告已保存: {filepath}");return filepath

def export_json(articles,filepath=None):
    filepath=filepath or f"gcc_research_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    data={"metadata":{"scraped_at":datetime.now().isoformat(),"total_articles":len(articles),"system":"GCC Think Tank Scraper v2.4"},"articles":[a.to_dict() for a in articles]}
    with open(filepath,"w",encoding="utf-8") as f:json.dump(data,f,ensure_ascii=False,indent=2)
    log.info(f"💾 JSON 数据已保存: {filepath}");return filepath

def check_ai_ready(api_key=None):
    """委托给 ai_client，保持接口不变（返回 (bool, key_or_error)）"""
    return ai_client.check_ready(api_key)

def ai_classify_batch(articles, api_key=None):
    ready, key = check_ai_ready(api_key)
    if not ready:
        print(f"\n⚠️  AI辅助筛选跳过: {key}")
        return articles

    client = ai_client.create_client(key)
    borderline = [a for a in articles if a.content_type == "unknown" and 2 <= a.keyword_score <= 4]
    if not borderline:
        log.info("无边界模糊文章，跳过AI辅助筛选")
        return articles

    log.info(f"🤖 AI辅助筛选 {len(borderline)} 篇边界文章（{ai_client.provider_info()}）...")
    items_text = "\n".join(
        f"{i+1}. [{a.source}] {a.title}" + (f"\n   摘要: {a.snippet[:200]}" if a.snippet else "")
        for i, a in enumerate(borderline)
    )
    prompt = (
        "你是GCC政治经济研究助手。判断以下文章是否与GCC六国相关。\n"
        "对每篇回答：1.是否相关(yes/no) 2.类型(research/opinion/news/event/other)\n"
        "严格按JSON数组返回：[{\"id\":1,\"relevant\":true,\"type\":\"research\"},...]\n\n"
        + items_text
    )
    try:
        tx = ai_client.chat(client, prompt, tier="fast", max_tokens=1000)
        tx = re.sub(r'^```json\s*', '', tx.strip())
        tx = re.sub(r'\s*```$', '', tx)
        m = re.search(r'\[.*?\]', tx, re.DOTALL)
        if m:
            tx = m.group(0)
        results = json.loads(tx)
        for r in results:
            idx = r["id"] - 1
            if 0 <= idx < len(borderline):
                borderline[idx].ai_verdict = "relevant" if r.get("relevant") else "not_relevant"
                if r.get("type") == "research":
                    borderline[idx].priority = "priority_read"
                elif r.get("type") == "event":
                    borderline[idx].content_type = "excluded"
        log.info(f"  AI分类完成: {len(results)} 篇")
    except Exception as e:
        log.error(f"  AI分类失败: {e}")
    return articles

def batch_translate_titles(articles, api_key=None):
    ready, key = check_ai_ready(api_key)
    if not ready:
        return articles

    client = ai_client.create_client(key)
    need = [a for a in articles if a.title_cn is None and a.title]
    if not need:
        return articles

    BATCH_SIZE = 15   # 小批次，避免响应截断
    MAX_RETRIES = 2
    print(f"\n🌐 批量翻译 {len(need)} 个标题（每批{BATCH_SIZE}条，{ai_client.provider_info()}）...")

    def _translate_batch(batch):
        titles_text = "\n".join(f"{j+1}. {a.title}" for j, a in enumerate(batch))
        prompt = (
            f"将以下{len(batch)}个英文标题翻译为简洁中文，保留专有名词。"
            f"必须返回{len(batch)}条结果。严格按JSON数组返回，无其他文字：\n"
            f'[{{"id":1,"cn":"中文标题"}}, ...]\n\n{titles_text}'
        )
        tx = ai_client.chat(client, prompt, tier="fast", max_tokens=3000)
        tx = re.sub(r'^```json\s*', '', tx.strip())
        tx = re.sub(r'\s*```$', '', tx)
        m = re.search(r'\[.*?\]', tx, re.DOTALL)
        if m:
            tx = m.group(0)
        return json.loads(tx)

    for i in range(0, len(need), BATCH_SIZE):
        batch = need[i:i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        for attempt in range(MAX_RETRIES + 1):
            try:
                results = _translate_batch(batch)
                ok = 0
                for r in results:
                    idx = r.get("id", 0) - 1
                    if 0 <= idx < len(batch) and r.get("cn"):
                        batch[idx].title_cn = r["cn"]
                        ok += 1
                log.info(f"  批次{batch_num}: {ok}/{len(batch)} 条翻译成功")
                break
            except Exception as e:
                if attempt < MAX_RETRIES:
                    log.warning(f"  批次{batch_num} 第{attempt+1}次失败，重试: {e}")
                    time.sleep(2)
                else:
                    log.error(f"  批次{batch_num} 翻译失败（已重试{MAX_RETRIES}次）: {e}")
        time.sleep(0.5)  # 批次间隔，避免限频

    # 第二轮：对仍未翻译的逐条补译
    still_need = [a for a in need if a.title_cn is None]
    if still_need:
        print(f"  🔄 补译剩余 {len(still_need)} 条...")
        for a in still_need:
            try:
                a.title_cn = ai_client.chat(
                    client,
                    f"将以下英文标题翻译为简洁中文，只返回翻译结果，不要其他文字：\n{a.title}",
                    tier="fast",
                    max_tokens=200,
                )
            except Exception:
                pass
            time.sleep(0.3)

    translated = sum(1 for a in articles if a.title_cn)
    print(f"  ✅ 已翻译 {translated}/{len(need)} 个标题")
    return articles

def _backfill_dates_from_analysis(all_analyses: list, articles: list):
    """
    从 AI 生成的分析文本里提取「发布日期」，回填到 articles 中
    日期为 None 或空字符串的条目。仅接受含四位年份的日期字符串。
    """
    full_text = "\n\n".join(all_analyses)
    # 匹配 ### [N] 开头的块，捕获到下一个 ### [N] 或文末
    for block_m in re.finditer(r'###\s*\[(\d+)\][^\n]*\n((?:(?!###\s*\[).)+)', full_text, re.DOTALL):
        idx = int(block_m.group(1)) - 1  # 转为 0-based
        block = block_m.group(2)
        date_m = re.search(r'\|\s*\*\*发布日期\*\*\s*\|\s*([^|\n]+?)\s*\|', block)
        if not date_m:
            continue
        date_str = date_m.group(1).strip()
        # 只接受含年份（4位数字）、且不是占位词的日期
        if (re.search(r'\d{4}', date_str)
                and date_str not in ('未知', '日期不详', '-', '不详', '未提供', 'N/A', 'n/a')):
            if 0 <= idx < len(articles) and not articles[idx].date:
                normalized = normalize_date(date_str)
                if normalized:
                    articles[idx].date = normalized
                    log.debug(f"  📅 回填日期 [{idx+1}]: {normalized}")

def _ensure_summary_anchors(summary_text: str, total_articles: int) -> str:
    """补齐 AI 偶尔漏写的文章锚点，避免 PDF 目录内链渲染失败。"""
    for idx in range(1, total_articles + 1):
        anchor = f'<a id="article-{idx}"></a>'
        if anchor in summary_text:
            continue
        heading_re = re.compile(rf'(?m)^### \[(?:⭐\s*)?{idx}\] ')
        if heading_re.search(summary_text):
            summary_text = heading_re.sub(anchor + "\n" + r"\g<0>", summary_text, count=1)
    return summary_text

def generate_ai_summary(
    articles,
    api_key=None,
    summary_workers=2,
    include_high_risk=False,
    filtered_out_records: Optional[list] = None,
):
    """
    分三步生成结构化研究简报：
      1. 分批调用 AI，每批 10 篇完整解析（解决 token 超限问题）
      2. 从 AI 输出回填缺失的发布日期，再本地构建目录（带锚点超链接）
      3. 一次额外调用生成跨文章趋势信号
    """
    ready, key = check_ai_ready(api_key)
    if not ready:
        print(f"\n⚠️  AI汇总跳过: {key}")
        return None
    if not articles:
        print("\n⚠️  AI汇总跳过: 没有文章")
        return None

    n = len(articles)
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    BATCH_SIZE = 10  # 每批 10 篇，8000 token 足够覆盖全部字段
    summary_workers = max(1, int(summary_workers or 1))

    # ── 预处理：按日期降序排列，有日期的在前，日期未知的在后 ──────────
    def _date_sort_key(a):
        d = a.date or ""
        # (1, date_str) 表示有日期，(0, "") 表示无日期
        # reverse=True 时：有日期 > 无日期，较新日期 > 较旧日期
        if re.match(r'\d{4}-\d{2}-\d{2}', d): return (1, d)
        if re.match(r'\d{4}-\d{2}', d):        return (1, d + "-99")
        if re.match(r'\d{4}', d):               return (1, d[:4] + "-99-99")
        return (0, "")  # 无日期排最后
    articles = sorted(articles, key=_date_sort_key, reverse=True)
    # 强相关优先：tier 内保持日期降序
    _strong = [a for a in articles if a.topic_relevance_score >= 4.0]
    _medium = [a for a in articles if a.topic_relevance_score < 4.0]
    articles = _strong + _medium
    n_strong = len(_strong)

    print(
        f"\n🤖 正在生成结构化研究简报（{n} 篇文章，分 {(n + BATCH_SIZE - 1) // BATCH_SIZE} 批，"
        f"并发 {min(summary_workers, (n + BATCH_SIZE - 1) // BATCH_SIZE)}，{ai_client.provider_info()}）..."
    )

    # ── 第一步：分批调用 AI ──────────────────────────────────────────
    all_analyses: list[str] = []
    total_batches = (n + BATCH_SIZE - 1) // BATCH_SIZE

    def _placeholder_for_batch(batch_idx, batch, error):
        start = batch_idx * BATCH_SIZE
        placeholder_lines = []
        for j, a in enumerate(batch, 1):
            abs_idx = start + j
            placeholder_lines.append(
                f'<a id="article-{abs_idx}"></a>\n'
                f"### [{abs_idx}] {a.title_cn or a.title}\n\n"
                f"> ❌ 本批次 AI 解析失败：{error}\n\n---"
            )
        return "\n\n".join(placeholder_lines)

    def _build_batch_prompt(batch_idx, batch):
        start = batch_idx * BATCH_SIZE
        articles_input = ""
        for j, a in enumerate(batch, 1):
            abs_idx = start + j
            cn_note = f"（中文：{a.title_cn}）" if a.title_cn else ""
            articles_input += f"{abs_idx}. {a.title}{cn_note}\n"
            articles_input += f"   来源：{a.source}（{a.source_country}）| 日期：{a.date or '待推断'}\n"
            articles_input += f"   链接：{a.url}\n"
            if a.snippet:
                articles_input += f"   摘要：{a.snippet[:400]}\n"
            articles_input += "\n"

        return f"""你是GCC地区研究专家，为成都创新金融研究院撰写内部研究简报。

对以下 {len(batch)} 篇文章（全局序号 {start+1} 至 {start+len(batch)}），每篇独立输出完整结构化解析。

## 分析规则
1. 全部中文输出
2. 每项判断末尾标注来源类型：【原文直述】【AI推断】【待核实】
3. "对华关联"若无明显关联，写"暂无直接关联线索，但可关注……（补充潜在联系）"
4. "关键数据或事件"若无具体数字，写"原文未提供具体数据"
5. 必须覆盖全部 {len(batch)} 篇，严禁合并或省略任何一篇
6. 发布日期：优先使用已提供日期；若标注"待推断"，请从URL路径（如/2024/03/）、摘要或标题中推断，确实无法判断则填"日期不详"

## 每篇输出格式（严格执行，字段顺序不变）

<a id="article-{{全局序号}}"></a>
### [{{全局序号}}] {{中文标题}}

| 字段 | 内容 |
|------|------|
| **原标题** | {{英文原标题}} |
| **来源平台** | {{智库名称（国家/地区）}} |
| **发布日期** | {{日期，格式尽量为YYYY-MM-DD或YYYY-MM，确实不明则填"日期不详"}} |
| **原文链接** | [查看原文]({{URL}}) |

**核心议题**
（3-5句。先点明文章聚焦的具体问题或政策领域，再交代背景与驱动因素，最后说明该议题在当前GCC/全球格局中的政策或学术意义。）

**主要判断**
（3-5句。系统梳理作者核心论点及其论证逻辑：主张是什么→依据是什么→结论如何推导，重要分歧或质疑也应点出。）【原文直述/AI推断/待核实】

**对GCC地区的影响**
（2-3句。从经济、政治、安全或社会维度中选最相关的2个维度深度展开，指明影响路径与潜在后果，避免泛泛而谈。）【原文直述/AI推断/待核实】

**对华关联**
（2-3句。结合中海/中阿经贸、能源合作、"一带一路"、地缘竞争、技术转让等具体维度分析，若关联间接也应指出潜在传导机制。）【原文直述/AI推断/待核实】

**关键数据或事件**
（列举文章中出现的具体数字、百分比、时间节点或标志性事件，若无则写"原文未提供具体数据"。）

---

文章列表：
{articles_input}"""

    def _analyze_batch(batch_idx):
        start = batch_idx * BATCH_SIZE
        batch = articles[start:start + BATCH_SIZE]
        try:
            worker_client = ai_client.create_client(key)
            result = ai_client.chat(worker_client, _build_batch_prompt(batch_idx, batch), tier="smart", max_tokens=8000)
            return batch_idx, result.strip(), None
        except Exception as e:
            return batch_idx, _placeholder_for_batch(batch_idx, batch, e), e

    if summary_workers > 1 and total_batches > 1:
        batch_outputs = [None] * total_batches
        max_workers = min(summary_workers, total_batches)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            for batch_idx in range(total_batches):
                start = batch_idx * BATCH_SIZE
                batch = articles[start:start + BATCH_SIZE]
                print(f"  📖 提交第 {batch_idx + 1}/{total_batches} 批（第 {start+1}–{start+len(batch)} 篇）...")
                futures[executor.submit(_analyze_batch, batch_idx)] = batch_idx
            for fut in as_completed(futures):
                batch_idx, text, error = fut.result()
                batch_outputs[batch_idx] = text
                if error:
                    log.error(f"  第 {batch_idx+1} 批解析失败: {error}")
                else:
                    log.info(f"  第 {batch_idx+1}/{total_batches} 批解析完成")
        all_analyses = [text for text in batch_outputs if text is not None]
    else:
        for batch_idx in range(total_batches):
            start = batch_idx * BATCH_SIZE
            batch = articles[start:start + BATCH_SIZE]
            print(f"  📖 分析第 {batch_idx + 1}/{total_batches} 批（第 {start+1}–{start+len(batch)} 篇）...")
            batch_idx, text, error = _analyze_batch(batch_idx)
            if error:
                log.error(f"  第 {batch_idx+1} 批解析失败: {error}")
            all_analyses.append(text)
            time.sleep(0.5)

    # ── 第二步：从 AI 输出回填缺失日期，再生成目录 ───────────────────
    _backfill_dates_from_analysis(all_analyses, articles)

    toc_lines = []
    if n_strong > 0:
        toc_lines.append(f"**⭐ 推荐阅读（强相关 · {n_strong} 篇）**\n")
        for i, a in enumerate(articles[:n_strong], 1):
            title_display = a.title_cn or a.title
            date_str = a.date or "日期不详"
            toc_lines.append(f"{i}. [⭐ {title_display}](#article-{i}) — {a.source} · {date_str}")
        toc_lines.append("")
    if n_strong < n:
        toc_lines.append(f"**📄 中等相关（{n - n_strong} 篇）**\n")
        for i, a in enumerate(articles[n_strong:], n_strong + 1):
            title_display = a.title_cn or a.title
            date_str = a.date or "日期不详"
            toc_lines.append(f"{i}. [{title_display}](#article-{i}) — {a.source} · {date_str}")

    header = (
        f"# GCC研究动态内部简报\n\n"
        f"> **生成时间**：{now_str} &nbsp;|&nbsp; **收录文章**：{n} 篇（⭐ 强相关 {n_strong} 篇 · 📄 中等相关 {n - n_strong} 篇）&nbsp;|&nbsp; 成都创新金融研究院\n\n"
        "---\n\n"
        "## 一、文章目录\n\n"
        + "\n".join(toc_lines)
        + "\n\n---\n\n"
        "## 二、逐篇内容解析\n\n"
    )

    # ── 第三步：生成趋势信号 ─────────────────────────────────────────
    print(f"  📊 生成跨文章趋势信号...")
    brief_list = "\n".join(
        f"{i+1}. [{a.source}] {a.title_cn or a.title}"
        for i, a in enumerate(articles)
    )
    trend_prompt = f"""基于以下 {n} 篇 GCC 智库文章，归纳 3-5 条跨平台趋势信号。

格式：

## 三、本期趋势信号

### 信号X：[趋势名称]
- **支撑依据**：（引用2-3篇文章，注明序号）
- **判断类型**：【AI推断】
- **对研究院的提示**：（1句话行动建议）

文章列表：
{brief_list}"""

    try:
        client = ai_client.create_client(key)
        trends = ai_client.chat(client, trend_prompt, tier="smart", max_tokens=2000)
    except Exception as e:
        trends = f"## 三、本期趋势信号\n\n> ❌ 趋势信号生成失败：{e}"

    full_summary = header + "\n\n".join(all_analyses) + "\n\n---\n\n" + trends.strip()
    next_section = 4
    filtered_notice = filtered_out_notice(filtered_out_records, section_no=next_section)
    if filtered_notice:
        full_summary += "\n\n---\n\n" + filtered_notice
        next_section += 1
    high_risk_notice = high_risk_sources_notice(
        include_high_risk=include_high_risk,
        section_no=next_section,
    )
    if high_risk_notice:
        full_summary += "\n\n---\n\n" + high_risk_notice
    # ── 为强相关文章的章节标题注入 ⭐ ──────────────────────────────────
    for idx in range(1, n_strong + 1):
        full_summary = full_summary.replace(f"### [{idx}]", f"### [⭐ {idx}]")
    full_summary = _ensure_summary_anchors(full_summary, n)
    print(f"✅ AI研究简报生成成功（{n} 篇 / {total_batches} 批，其中强相关 {n_strong} 篇）")
    return full_summary


def export_summary_pdf(summary_text: str, filepath: str) -> str:
    """
    将 AI 研究简报的 Markdown 文本渲染为 PDF。
    使用 reportlab 内置的 STSong-Light（宋体）CID 字体支持中文。
    目录条目生成可点击的 PDF 内部跳转链接。
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer,
            HRFlowable, Table, TableStyle, KeepTogether,
        )
        from reportlab.lib import colors
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    except ImportError:
        log.warning("⚠️  reportlab 未安装，跳过 PDF 生成\n   pip install reportlab")
        return ""

    # ── 注册宋体（STSong-Light） ───────────────────────────────────
    try:
        pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
        cn_font = 'STSong-Light'
    except Exception as font_err:
        log.warning(f"⚠️  宋体加载失败，PDF 中文可能显示异常: {font_err}")
        cn_font = 'Helvetica'

    # ── 颜色常量 ─────────────────────────────────────────────────
    C_TITLE   = colors.HexColor("#0D2137")   # 深海军蓝，标题
    C_H2      = colors.HexColor("#1B4F72")   # 蓝，二级标题
    C_H3_BG   = colors.HexColor("#EBF5FB")   # 淡蓝背景，文章标题行
    C_H3_TEXT = colors.HexColor("#1A5276")   # 文章标题文字
    C_BODY    = colors.HexColor("#1a1a1a")   # 正文
    C_META    = colors.HexColor("#7F8C8D")   # 灰，副文本
    C_LINK    = colors.HexColor("#1A5276")   # 蓝，链接
    C_RULE    = colors.HexColor("#BDC3C7")   # 浅灰，分隔线
    C_TBL_H   = colors.HexColor("#D6EAF8")   # 表头背景
    C_TBL_ROW = colors.HexColor("#FDFEFE")   # 表格行背景

    # ── 样式工厂 ─────────────────────────────────────────────────
    def _style(name, size, leading, *, before=4, after=6,
               indent=0, color=C_BODY, bold=False, align="LEFT"):
        from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
        al = {"LEFT": TA_LEFT, "CENTER": TA_CENTER, "JUSTIFY": TA_JUSTIFY}.get(align, TA_LEFT)
        return ParagraphStyle(
            name, fontName=cn_font, fontSize=size, leading=leading,
            spaceBefore=before, spaceAfter=after,
            leftIndent=indent, textColor=color,
            alignment=al,
            allowWidows=1,   # 允许链接标签
        )

    s_h1     = _style("H1",    20, 28, before=0,  after=10, color=C_TITLE)
    s_h2     = _style("H2",    13, 19, before=16, after=5,  color=C_H2)
    s_h3     = _style("H3",    11, 16, before=6,  after=4,  color=C_H3_TEXT)
    s_body   = _style("Body",  10, 16, before=2,  after=3,  color=C_BODY, align="JUSTIFY")
    s_bold   = _style("Bold",  10, 16, before=5,  after=2,  color=C_BODY)
    s_bullet = _style("Bul",   10, 15, before=1,  after=2,  indent=14, color=C_BODY)
    s_toc    = _style("TOC",   10, 16, before=2,  after=2,  indent=6,  color=C_BODY)
    s_meta   = _style("Meta",   9, 14, before=0,  after=3,  color=C_META)
    s_cell   = _style("Cell",   9, 13, before=2,  after=2,  color=C_BODY)
    # 逐篇解析字段标签（核心议题 / 主要判断 / 对GCC地区的影响 / 对华关联 / 关键数据或事件）
    from reportlab.lib.enums import TA_LEFT as _TA_LEFT
    s_label  = ParagraphStyle(
        "Label", fontName=cn_font, fontSize=10, leading=16,
        spaceBefore=10, spaceAfter=3,
        leftIndent=0, rightIndent=0,
        textColor=colors.HexColor("#1B4F72"),
        backColor=colors.HexColor("#EBF5FB"),
        borderPadding=(4, 8, 4, 8),
        alignment=_TA_LEFT, allowWidows=1,
    )

    # ── XML 工具 ─────────────────────────────────────────────────
    def _esc(text: str) -> str:
        """仅转义 & < >，不动其他内容（用于已知安全片段）"""
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _colored_symbols(text: str) -> str:
        """将 emoji 符号替换为带颜色的实心圆（STSong-Light 不支持 emoji）。"""
        text = text.replace('⭐', '<font color="#C0392B">●</font>')   # 红色圆 = 强相关
        text = text.replace('📄', '<font color="#2980B9">●</font>')   # 蓝色圆 = 中等相关
        return text

    def _safe(text: str) -> str:
        """转义 XML 特殊字符，**粗体** → <b>，*斜体* → <i>"""
        text = _esc(text)
        text = _colored_symbols(text)
        text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
        text = re.sub(r'\*([^*]+?)\*',  r'<i>\1</i>', text)
        return text

    def _with_links(text: str) -> str:
        """
        将 Markdown 链接 [label](url_or_#anchor) 转为 reportlab XML <a> 标签。
        非链接部分做 XML 转义，href 属性中的 & < > 也单独转义（防止 XML 格式错误）。
        """
        parts = []
        last = 0
        for m in re.finditer(r'\[([^\]]+)\]\(\s*([^)]+?)\s*\)', text):
            before = _colored_symbols(_esc(text[last:m.start()]))
            label  = _colored_symbols(_esc(m.group(1)))
            # URL 里 & 必须转为 &amp;，否则 XML 非法 → reportlab 中途崩溃 → 文件损坏
            href   = (m.group(2).strip()
                      .replace("&", "&amp;")
                      .replace("<", "&lt;")
                      .replace(">", "&gt;"))
            parts.append(before)
            parts.append(f'<a href="{href}" color="{C_LINK.hexval()}">'
                         f'<u>{label}</u></a>')
            last = m.end()
        parts.append(_colored_symbols(_esc(text[last:])))
        result = ''.join(parts)
        result = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', result)
        result = re.sub(r'\*([^*\n]+?)\*',  r'<i>\1</i>', result)
        return result

    def _plain(text: str) -> str:
        """去掉所有 Markdown 标记，返回纯文本（用于表格单元格）"""
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        text = re.sub(r'\*(.+?)\*',     r'\1', text)
        text = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', text)
        return text.strip()

    # ── 表格渲染 ─────────────────────────────────────────────────
    story: list = []
    table_rows: list[str] = []
    in_table = False

    def flush_table():
        nonlocal table_rows, in_table
        if not table_rows:
            in_table = False
            return
        data = []
        for raw in table_rows:
            cells = [c.strip() for c in raw.strip('|').split('|')]
            if all(re.match(r'^[-: ]+$', c) for c in cells):
                continue
            data.append(cells)
        table_rows.clear()
        in_table = False
        if not data:
            return
        n_cols = max(len(r) for r in data)
        padded = [r + [''] * (n_cols - len(r)) for r in data]
        # 第一列宽略窄（字段名），其余列平分
        page_w = A4[0] - 5 * cm
        if n_cols == 2:
            col_ws = [page_w * 0.22, page_w * 0.78]
        else:
            col_ws = [page_w / n_cols] * n_cols
        tbl_data = []
        for ri, row in enumerate(padded):
            tbl_data.append([
                Paragraph(_with_links(c), s_cell) for c in row  # 保留链接，不预先调 _plain
            ])
        tbl = Table(tbl_data, colWidths=col_ws, repeatRows=1, hAlign='LEFT')
        tbl.setStyle(TableStyle([
            ('BACKGROUND',    (0, 0), (-1, 0),   C_TBL_H),
            ('BACKGROUND',    (0, 1), (-1, -1),  C_TBL_ROW),
            ('FONTNAME',      (0, 0), (-1, -1),  cn_font),
            ('FONTSIZE',      (0, 0), (-1, -1),  9),
            ('GRID',          (0, 0), (-1, -1),  0.4, C_RULE),
            ('VALIGN',        (0, 0), (-1, -1),  'TOP'),
            ('TOPPADDING',    (0, 0), (-1, -1),  4),
            ('BOTTOMPADDING', (0, 0), (-1, -1),  4),
            ('LEFTPADDING',   (0, 0), (-1, -1),  6),
            ('RIGHTPADDING',  (0, 0), (-1, -1),  6),
        ]))
        story.append(tbl)
        story.append(Spacer(1, 0.25 * cm))

    # ── PDF 锚点支持 ─────────────────────────────────────────────
    try:
        from reportlab.platypus.flowables import AnchorFlowable
        has_anchor = True
    except ImportError:
        has_anchor = False

    # ── 逐行解析 ─────────────────────────────────────────────────
    for line in summary_text.splitlines():
        # 表格行
        if line.strip().startswith('|'):
            in_table = True
            table_rows.append(line)
            continue
        if in_table:
            flush_table()

        stripped = line.strip()

        # <a id="article-N"></a> → PDF 命名锚点（不渲染文字）
        anchor_m = re.match(r'^<a\s+id="([^"]+)"\s*></a>$', stripped)
        if anchor_m:
            if has_anchor:
                story.append(AnchorFlowable(anchor_m.group(1)))
            continue

        # H1
        if line.startswith('# ') and not line.startswith('## '):
            story.append(Paragraph(_safe(line[2:]), s_h1))
            story.append(HRFlowable(width="100%", thickness=2,
                                    color=C_TITLE, spaceAfter=8))
        # H2
        elif line.startswith('## '):
            story.append(Spacer(1, 0.4 * cm))
            story.append(Paragraph(_safe(line[3:]), s_h2))
            story.append(HRFlowable(width="100%", thickness=1,
                                    color=C_H2, spaceAfter=4))
        # H3：文章标题，加淡蓝色底框
        elif line.startswith('### '):
            heading_text = _safe(line[4:])
            # 用单行表格模拟色块背景
            tbl = Table([[Paragraph(heading_text, s_h3)]],
                        colWidths=[A4[0] - 5 * cm], hAlign='LEFT')
            tbl.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), C_H3_BG),
                ('TOPPADDING',    (0, 0), (-1, -1), 5),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
                ('LEFTPADDING',   (0, 0), (-1, -1), 8),
                ('RIGHTPADDING',  (0, 0), (-1, -1), 8),
                ('BOX', (0, 0), (-1, -1), 0.8, C_H2),
            ]))
            story.append(Spacer(1, 0.2 * cm))
            story.append(tbl)
            story.append(Spacer(1, 0.1 * cm))
        # 引用块（元信息行）
        elif stripped.startswith('> '):
            story.append(Paragraph(_with_links(stripped[2:]), s_meta))
        # 无序列表
        elif re.match(r'^[-*] ', line):
            story.append(Paragraph("• " + _with_links(line[2:]), s_bullet))
        # 有序列表（含目录跳转链接）
        elif re.match(r'^\d+\. ', line):
            m = re.match(r'^(\d+)\. (.+)$', line)
            num  = m.group(1)
            rest = m.group(2)
            # 目录行：rest 含 [title]( #article-N ) — *source* · date
            if re.search(r'\[.+\]\(', rest):
                story.append(Paragraph(f"{num}. " + _with_links(rest), s_toc))
            else:
                story.append(Paragraph(f"{num}. " + _safe(rest), s_bullet))
        # 分隔线
        elif re.match(r'^---+$', stripped):
            story.append(Spacer(1, 0.1 * cm))
            story.append(HRFlowable(width="100%", thickness=0.5,
                                    color=C_RULE, spaceBefore=2, spaceAfter=6))
        # 空行
        elif not stripped:
            story.append(Spacer(1, 0.15 * cm))
        # **粗体** 独占行（字段标签，如 **核心议题**）→ 蓝底蓝字标签样式
        elif re.match(r'^\*\*.+\*\*$', stripped):
            story.append(Paragraph(_safe(stripped), s_label))
        # 普通正文（含行内粗体/链接）
        else:
            story.append(Paragraph(_with_links(line), s_body))

    if in_table:
        flush_table()

    # ── 构建 PDF ─────────────────────────────────────────────────
    doc = SimpleDocTemplate(
        filepath, pagesize=A4,
        leftMargin=2.5 * cm, rightMargin=2.5 * cm,
        topMargin=2.5 * cm, bottomMargin=2.5 * cm,
        title="GCC研究动态内部简报",
        author="成都创新金融研究院",
    )
    def _strip_pdf_links(s: list) -> list:
        """降级：将 story 中所有 Paragraph 的 <a href=...> 标签去掉，保留文字"""
        import copy
        clean = []
        for item in s:
            if isinstance(item, Paragraph):
                text = re.sub(r'<a [^>]+>(.+?)</a>', r'\1', item.text, flags=re.DOTALL)
                clean.append(Paragraph(text, item.style))
            else:
                clean.append(item)
        return clean

    import os as _os
    try:
        doc.build(story)
        log.info(f"📄 PDF 简报已保存: {filepath}")
        return filepath
    except Exception as e:
        # 任何异常都可能导致文件半写损坏，先删除残留文件
        log.warning(f"⚠️  PDF 首次生成失败（{e}），降级为纯文本链接模式重试...")
        try:
            if _os.path.exists(filepath):
                _os.remove(filepath)
        except OSError:
            pass
        try:
            doc2 = SimpleDocTemplate(
                filepath, pagesize=A4,
                leftMargin=2.5 * cm, rightMargin=2.5 * cm,
                topMargin=2.5 * cm, bottomMargin=2.5 * cm,
                title="GCC研究动态内部简报",
                author="成都创新金融研究院",
            )
            doc2.build(_strip_pdf_links(story))
            log.info(f"📄 PDF 简报已保存（纯文本链接模式）: {filepath}")
            return filepath
        except Exception as e2:
            try:
                if _os.path.exists(filepath):
                    _os.remove(filepath)
            except OSError:
                pass
            log.error(f"❌ PDF 生成彻底失败: {e2}")
            return ""

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="GCC智库研究抓取系统 v2.1")
    parser.add_argument("--countries", nargs="+", default=None, help="只抓指定国家")
    parser.add_argument("--regions", nargs="+", metavar="REGION",
        help="只抓指定区域：gcc / mena / western（可多选）")
    parser.add_argument("--org-types", nargs="+", metavar="TYPE", dest="org_types",
        help="只抓指定机构类型：official / university / independent（可多选）")
    parser.add_argument("--topics", nargs="+", metavar="TOPIC",
        help="只抓包含指定议题的智库：energy / security / economy / politics / society / technology（可多选）")
    parser.add_argument("--group-by", choices=["region","org_type","topic"], dest="group_by", default=None,
        help="Markdown输出分组方式：region / org_type / topic（默认按优先级分组）")
    parser.add_argument("--playwright", action="store_true", help="启用JS渲染")
    parser.add_argument("--ai", action="store_true", help="启用AI筛选、翻译、汇总")
    parser.add_argument("--summary-workers", type=int, default=2,
                        help="AI简报分批生成的并发数（默认2；如遇API限流可设为1）")
    parser.add_argument("--api-key", default=None, help="Anthropic API Key（建议改用 ANTHROPIC_API_KEY 环境变量）")
    parser.add_argument("--output-dir", default="./output", help="输出目录")
    parser.add_argument("--max-per-tank", type=int, default=50, help="每个智库最多保留条数（默认50）")
    parser.add_argument("--no-dedup", action="store_true", help="禁用SQLite增量去重（每次全量处理）")
    parser.add_argument("--dedup-db", default=DEDUP_DB_PATH, help=f"去重数据库路径（默认: {DEDUP_DB_PATH}）")
    parser.add_argument("--dedup-days", type=int, default=1,
                        help="去重时间窗口（天），只过滤该天数内已处理的文章，默认1天。"
                             "0=关闭去重效果，None效果同--no-dedup")
    parser.add_argument("--days", type=int, default=30,
                        help="只收录近 N 天内发布的文章（默认30天；常用值：3/10/30；0=不限）")
    parser.add_argument("--keep-undated", action="store_true",
                        help="保留无发布日期的文章（默认过滤，用于调试）")
    parser.add_argument("--include-high-risk", action="store_true",
                        help="人工覆盖 compliance_rules.yaml 中 allow_scrape=false 的高风险来源")
    parser.add_argument("--debug", action="store_true", help="调试日志")
    parser.add_argument(
        "--dry-run-keywords",
        action="store_true",
        dest="dry_run_keywords",
        help="试运行模式：输出每篇文章的命中关键词与评分明细到 keyword_dryrun.json，"
             "并额外导出被硬过滤的文章到 filtered_out.csv，便于回查",
    )
    args = parser.parse_args()

    if args.debug:
        logging.getLogger("gcc_scraper").setLevel(logging.DEBUG)

    if args.ai:
        ready, info = check_ai_ready(args.api_key)
        if not ready:
            print("\n" + "=" * 60 + f"\n⚠️  --ai 已启用但AI不可用：\n{info}\n" + "=" * 60)
            if input("\n继续（不用AI）？[y/N] ").strip().lower() != "y":
                print("已退出。")
                exit(0)
            args.ai = False

    od = Path(args.output_dir)
    od.mkdir(parents=True, exist_ok=True)
    dedup_db = None if args.no_dedup else args.dedup_db
    t_total = time.time()

    # ── 抓取阶段（含增量去重） ──
    t_scrape = time.time()
    articles, dedup_filtered, _filtered_out = run_scraper(
        use_playwright=args.playwright,
        enable_ai=args.ai,
        api_key=args.api_key,
        countries=args.countries,
        regions=args.regions,
        org_types=args.org_types,
        topics=args.topics,
        max_per_tank=args.max_per_tank,
        dedup_db=dedup_db,
        dedup_days=args.dedup_days,
        filter_undated=not args.keep_undated,
        max_age_days=args.days,
        dry_run=args.dry_run_keywords,
        include_high_risk=args.include_high_risk,
    )
    scrape_sec = time.time() - t_scrape

    # === v2.4.1 新增：试运行模式输出 ===
    if args.dry_run_keywords:
        import csv
        dryrun_records = []
        for art in articles:
            debug = getattr(art, "_funnel_debug", {}) or {}
            dryrun_records.append({
                "title": art.title,
                "url": art.url,
                "source": art.source,
                "source_region": getattr(art, "source_region", ""),
                "final_score": art.keyword_score,
                "demote_hits": debug.get("demote_hits", []),
                "demote_penalty": debug.get("demote_penalty", 0),
            })
        dryrun_path = os.path.join(str(od), "keyword_dryrun.json")
        with open(dryrun_path, "w", encoding="utf-8") as _f:
            json.dump(dryrun_records, _f, ensure_ascii=False, indent=2)
        print(f"  📊 试运行模式：keyword_dryrun.json 已写入 ({len(dryrun_records)} 篇)")
        fout_path = os.path.join(str(od), "filtered_out.csv")
        with open(fout_path, "w", encoding="utf-8", newline="") as _f:
            _w = csv.writer(_f)
            _w.writerow(["title", "url", "source", "filter_word"])
            for _rec in _filtered_out:
                _w.writerow([_rec["title"], _rec["url"], _rec["source"], _rec["filter_hit"]])
        print(f"  🚫 试运行模式：filtered_out.csv 已写入 ({len(_filtered_out)} 篇被硬过滤)")

        blocked_path = os.path.join(str(od), "blocked_sources.csv")
        blocked_sources = high_risk_sources_records(include_high_risk=args.include_high_risk)
        with open(blocked_path, "w", encoding="utf-8", newline="") as _f:
            _w = csv.writer(_f)
            _w.writerow([
                "source", "domain", "official_url", "manual_links",
                "risk_level", "scraping_policy", "robots_summary",
                "metadata_allowed_path", "fulltext_allowed_path",
                "requires_permission", "fulltext_scraping_allowed",
                "analysis_source", "reason",
            ])
            for _rec in blocked_sources:
                _w.writerow([
                    _rec["source"], _rec["domain"], _rec["official_url"],
                    _format_markdown_links(_rec.get("manual_links") or []),
                    _rec["risk_level"],
                    _rec["scraping_policy"], _rec["robots_summary"],
                    _rec["metadata_allowed_path"], _rec["fulltext_allowed_path"],
                    _rec["requires_permission"], _rec["fulltext_scraping_allowed"],
                    _rec["analysis_source"], _rec["reason"],
                ])
        print(f"  🧭 试运行模式：blocked_sources.csv 已写入 ({len(blocked_sources)} 个默认跳过来源)")

    if articles:
        ts = datetime.now().strftime('%Y%m%d_%H%M')

        # ── AI翻译阶段 ──
        t_ai = time.time()
        if args.ai:
            articles = batch_translate_titles(articles, args.api_key)
        translate_sec = time.time() - t_ai if args.ai else 0

        # ── 导出阶段 ──
        md_path = export_markdown(articles, filepath=os.path.join(str(od), f"gcc_research_{ts}.md"), group_by=args.group_by)
        json_path = export_json(articles, str(od / f"gcc_research_{ts}.json"))

        # ── AI简报阶段 ──
        t_summary = time.time()
        sp_md = sp_pdf = None
        if args.ai:
            sm = generate_ai_summary(
                articles,
                args.api_key,
                summary_workers=args.summary_workers,
                include_high_risk=args.include_high_risk,
                filtered_out_records=_filtered_out,
            )
            if sm:
                sp_md = od / f"gcc_summary_{ts}.md"
                with open(sp_md, "w", encoding="utf-8") as f:
                    f.write(sm)
                sp_pdf = export_summary_pdf(sm, str(od / f"gcc_summary_{ts}.pdf"))
        summary_sec = time.time() - t_summary if args.ai else 0

        # ── 写入去重数据库（所有处理完成后再标记，防止半途而废导致重复写入） ──
        if dedup_db:
            save_new_urls(articles, dedup_db)

        total_sec = time.time() - t_total
        print(f"\n{'=' * 60}")
        print(f"📂 输出文件:")
        print(f"  📝 Markdown报告: {md_path}")
        print(f"  💾 JSON数据:     {json_path}")
        if args.ai:
            if sp_md:
                print(f"  🤖 AI简报(MD):   {sp_md}")
                print(f"  📄 AI简报(PDF):  {sp_pdf if sp_pdf else '❌ PDF生成失败（pip install reportlab）'}")
            else:
                print("  🤖 AI研究简报:   ❌ 生成失败")
        print(f"\n⏱️  耗时统计:")
        print(f"  抓取+筛选:  {scrape_sec:.1f}s")
        if args.ai:
            print(f"  AI标题翻译: {translate_sec:.1f}s")
            print(f"  AI简报生成: {summary_sec:.1f}s")
        print(f"  ────────────")
        print(f"  总计:       {total_sec:.1f}s ({total_sec / 60:.1f}min)")
        print("=" * 60)
    else:
        total_sec = time.time() - t_total
        if dedup_filtered > 0:
            print(f"\n📭 无新文章（耗时 {total_sec:.1f}s）")
            print(f"  去重过滤了 {dedup_filtered} 篇（{args.dedup_days}天窗口内已处理过）")
            print(f"  • 如需重新处理同批文章，添加 --no-dedup")
            print(f"  • 如需生成AI简报，添加 --no-dedup --ai")
            print(f"  • 次日运行将自动抓取新文章（超出{args.dedup_days}天窗口）")
        else:
            print(f"\n⚠️ 未抓取到文章（耗时 {total_sec:.1f}s）。\n  1. 检查网络\n  2. 添加 --playwright\n  3. 添加 --debug")
