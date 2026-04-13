#!/usr/bin/env python3
"""
GCC智库研究抓取系统 v2.1
成都创新金融研究院 — 姜亭汀
四层漏斗筛选：来源可信度 → 关键词评分 → 内容类型 → AI辅助
数据源：HTML抓取 + RSS订阅

依赖安装：
  pip install requests beautifulsoup4 feedparser playwright anthropic
  playwright install chromium
"""

import json, re, os, time, logging
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import Optional
from pathlib import Path
import requests
from bs4 import BeautifulSoup

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    print("⚠️  未安装 Playwright\n   pip install playwright && playwright install chromium\n")

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False
    print("⚠️  未安装 feedparser，RSS不可用\n   pip install feedparser\n")

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')
log = logging.getLogger("gcc_scraper")

@dataclass
class Article:
    title: str
    url: str
    source: str
    source_country: str
    source_tier: str
    date: Optional[str] = None
    snippet: Optional[str] = None
    title_cn: Optional[str] = None
    keyword_score: float = 0.0
    content_type: str = "unknown"
    priority: str = "normal"
    ai_verdict: Optional[str] = None
    matched_keywords: list = field(default_factory=list)
    fetch_method: str = "html"
    def to_dict(self):
        return asdict(self)

THINK_TANKS = [
    {"name":"King Abdullah Petroleum Studies and Research Centre (KAPSARC)","country":"Saudi Arabia","tier":"core_gcc","base_url":"https://www.kapsarc.org","pages":["/research"],"rss_feeds":["https://www.kapsarc.org/feed/"],"selectors":{"article":"article, .publication-item, .research-item, .card, [class*='post'], [class*='article'], [class*='publication']","title":"h2 a, h3 a, h4 a, .title a, [class*='title'] a","link":"a[href]","snippet":"p, .excerpt, .summary, [class*='excerpt'], [class*='summary'], [class*='description']","date":"time, .date, [class*='date'], [datetime]"}},
    {"name":"International Institute for Iranian Studies (Rasanah)","country":"Saudi Arabia","tier":"core_gcc","base_url":"https://rasanah-iiis.org/english","pages":["/","/category/publications/","/category/publications/monthly-reports/","/category/the-journal/"],"rss_feeds":["https://rasanah-iiis.org/english/feed/"],"selectors":{"article":"article, .post, .entry, [class*='post'], [class*='article']","title":"h2 a, h3 a, .entry-title a, [class*='title'] a","link":"a[href]","snippet":".entry-content p, .excerpt, [class*='excerpt']","date":"time, .date, [class*='date']"}},
    {"name":"King Faisal Center for Research and Islamic Studies","country":"Saudi Arabia","tier":"core_gcc","base_url":"https://www.kfcris.com/en","pages":["/research","/publications","/research/dirasat"],"selectors":{"article":"article, .card, [class*='publication'], [class*='research']","title":"h2 a, h3 a, h4 a, [class*='title'] a","link":"a[href]","snippet":"p, [class*='excerpt'], [class*='summary']","date":"time, .date, [class*='date']"}},
    {"name":"Emirates Policy Center (EPC)","country":"UAE","tier":"core_gcc","base_url":"https://www.epc.ae","pages":["/en/publications","/en/research"],"selectors":{"article":"article, .card, [class*='publication'], [class*='item'], [class*='post']","title":"h2 a, h3 a, h4 a, [class*='title'] a","link":"a[href]","snippet":"p, [class*='excerpt'], [class*='summary'], [class*='description']","date":"time, .date, [class*='date']"}},
    {"name":"Emirates Center for Strategic Studies and Research (ECSSR)","country":"UAE","tier":"core_gcc","base_url":"https://www.ecssr.ae","pages":["/en/research-programs","/en/publications"],"selectors":{"article":"article, .card, [class*='publication'], [class*='research'], [class*='item']","title":"h2 a, h3 a, [class*='title'] a","link":"a[href]","snippet":"p, [class*='excerpt'], [class*='summary']","date":"time, .date, [class*='date']"}},
    {"name":"Gulf Research Center (GRC)","country":"UAE","tier":"core_gcc","base_url":"https://www.grc.ae","pages":["/research","/publications"],"selectors":{"article":"article, .card, [class*='publication'], [class*='research'], [class*='item']","title":"h2 a, h3 a, [class*='title'] a","link":"a[href]","snippet":"p, [class*='excerpt'], [class*='summary']","date":"time, .date, [class*='date']"}},
    {"name":"Dubai Public Policy Research Center (Bhuth)","country":"UAE","tier":"core_gcc","base_url":"https://bhuth.ae","pages":["/en/publications","/en/research"],"selectors":{"article":"article, .card, [class*='publication'], [class*='research'], [class*='item'], [class*='post']","title":"h2 a, h3 a, h4 a, [class*='title'] a","link":"a[href]","snippet":"p, [class*='excerpt'], [class*='summary']","date":"time, .date, [class*='date']"}},
    {"name":"Sheikh Saud bin Saqr Al Qasimi Foundation","country":"UAE","tier":"core_gcc","base_url":"https://www.alqasimifoundation.com","pages":["/research","/publications-library"],"selectors":{"article":"article, .card, [class*='publication'], [class*='research'], [class*='item']","title":"h2 a, h3 a, [class*='title'] a","link":"a[href]","snippet":"p, [class*='excerpt'], [class*='summary']","date":"time, .date, [class*='date']"}},
    {"name":"Future Center for Advanced Researches and Studies","country":"UAE","tier":"core_gcc","base_url":"https://futureuae.com","pages":["/en-US","/en-US/Release/Index/2/publications"],"selectors":{"article":"article, .card, [class*='item'], [class*='post'], [class*='research']","title":"h2 a, h3 a, [class*='title'] a","link":"a[href]","snippet":"p, [class*='excerpt'], [class*='summary']","date":"time, .date, [class*='date']"}},
    {"name":"Al Jazeera Centre for Studies (AJCS)","country":"Qatar","tier":"core_gcc","base_url":"https://studies.aljazeera.net","pages":["/en/","/en/reports"],"rss_feeds":["https://studies.aljazeera.net/en/rss.xml"],"selectors":{"article":"article, .card, [class*='post'], [class*='item'], [class*='article']","title":"h2 a, h3 a, [class*='title'] a","link":"a[href]","snippet":"p, [class*='excerpt'], [class*='summary']","date":"time, .date, [class*='date']"}},
    {"name":"Brookings Doha Center","country":"Qatar","tier":"core_gcc","base_url":"https://www.brookings.edu","pages":["/center/brookings-doha-center/"],"rss_feeds":["https://www.brookings.edu/feed/?center=brookings-doha-center"],"selectors":{"article":"article, [class*='card'], [class*='item'], [class*='post']","title":"h2 a, h3 a, h4 a, [class*='title'] a","link":"a[href]","snippet":"p, [class*='excerpt'], [class*='summary'], [class*='description']","date":"time, .date, [class*='date']"}},
    {"name":"Arab Center for Research and Policy Studies (Doha Institute)","country":"Qatar","tier":"core_gcc","base_url":"https://www.dohainstitute.org","pages":["/en/Pages/index.aspx"],"selectors":{"article":"article, .card, [class*='item'], [class*='post']","title":"h2 a, h3 a, [class*='title'] a","link":"a[href]","snippet":"p, [class*='excerpt'], [class*='summary']","date":"time, .date, [class*='date']"}},
    {"name":"Arab Planning Institute (API)","country":"Kuwait","tier":"core_gcc","base_url":"https://www.arab-api.org","pages":["/default.aspx"],"selectors":{"article":"article, .card, [class*='item'], [class*='post']","title":"h2 a, h3 a, [class*='title'] a","link":"a[href]","snippet":"p, [class*='excerpt']","date":"time, .date, [class*='date']"}},
    {"name":"Kuwait Institute for Scientific Research (KISR)","country":"Kuwait","tier":"core_gcc","base_url":"https://www.kisr.edu.kw","pages":["/en/"],"selectors":{"article":"article, .card, [class*='item'], [class*='post'], [class*='research']","title":"h2 a, h3 a, [class*='title'] a","link":"a[href]","snippet":"p, [class*='excerpt'], [class*='summary']","date":"time, .date, [class*='date']"}},
    {"name":"Bahrain Center for Strategic, International and Energy Studies (Derasat)","country":"Bahrain","tier":"core_gcc","base_url":"https://www.derasat.org.bh","pages":["/"],"rss_feeds":["https://www.derasat.org.bh/feed/"],"selectors":{"article":"article, .card, [class*='item'], [class*='post'], [class*='publication']","title":"h2 a, h3 a, [class*='title'] a","link":"a[href]","snippet":"p, [class*='excerpt'], [class*='summary']","date":"time, .date, [class*='date']"}},
    {"name":"Tawasul","country":"Oman","tier":"core_gcc","base_url":"https://tawasul.co.om","pages":["/"],"selectors":{"article":"article, .card, [class*='item'], [class*='post']","title":"h2 a, h3 a, [class*='title'] a","link":"a[href]","snippet":"p, [class*='excerpt']","date":"time, .date, [class*='date']"}},
    {"name":"Carnegie Middle East Center","country":"Lebanon","tier":"pan_mena","base_url":"https://carnegie-mec.org","pages":["/"],"rss_feeds":["https://carnegie-mec.org/feed","https://carnegieendowment.org/feeds/middle-east"],"selectors":{"article":"article, [class*='card'], [class*='item'], [class*='post']","title":"h2 a, h3 a, [class*='title'] a","link":"a[href]","snippet":"p, [class*='excerpt'], [class*='summary'], [class*='description']","date":"time, .date, [class*='date']"}},
    {"name":"Al-Ahram Center for Political and Strategic Studies","country":"Egypt","tier":"pan_mena","base_url":"https://acpss.ahram.org.eg","pages":["/"],"selectors":{"article":"article, [class*='item'], [class*='post']","title":"h2 a, h3 a, [class*='title'] a","link":"a[href]","snippet":"p, [class*='excerpt']","date":"time, .date, [class*='date']"}},
    {"name":"Al Sharq Forum","country":"Turkey","tier":"pan_mena","base_url":"https://www.sharqforum.org","pages":["/"],"selectors":{"article":"article, [class*='card'], [class*='item'], [class*='post']","title":"h2 a, h3 a, [class*='title'] a","link":"a[href]","snippet":"p, [class*='excerpt'], [class*='summary']","date":"time, .date, [class*='date']"}},
    {"name":"Arab Reform Initiative","country":"France","tier":"pan_mena","base_url":"https://www.arab-reform.net","pages":["/"],"rss_feeds":["https://www.arab-reform.net/feed/"],"selectors":{"article":"article, [class*='card'], [class*='item'], [class*='post']","title":"h2 a, h3 a, [class*='title'] a","link":"a[href]","snippet":"p, [class*='excerpt'], [class*='summary']","date":"time, .date, [class*='date']"}},
]

STRONG_KEYWORDS=["gcc","gulf cooperation council","海合会","مجلس التعاون الخليجي"]
COUNTRY_KEYWORDS=["saudi arabia","saudi","kingdom of saudi arabia","ksa","uae","united arab emirates","emirates","qatar","qatari","kuwait","kuwaiti","bahrain","bahraini","oman","omani","السعودية","الإمارات","قطر","الكويت","البحرين","عمان","riyadh","jeddah","dubai","abu dhabi","doha","muscat","manama"]
WEAK_KEYWORDS=["gulf","middle east","mena","arabian peninsula","الخليج","الشرق الأوسط"]
SCORE_STRONG,SCORE_COUNTRY,SCORE_WEAK=3,2,1
TITLE_MULTIPLIER=2
RELEVANCE_THRESHOLD=3

def compute_keyword_score(title,snippet=""):
    tl,sl=title.lower(),(snippet or"").lower()
    total,matched=0.0,[]
    def ck(kws,bs):
        nonlocal total
        for k in kws:
            kl=k.lower()
            if kl in tl:s=bs*TITLE_MULTIPLIER;total+=s;matched.append(f"{k}(标题,+{s})")
            elif kl in sl:s=bs;total+=s;matched.append(f"{k}(正文,+{s})")
    ck(STRONG_KEYWORDS,SCORE_STRONG);ck(COUNTRY_KEYWORDS,SCORE_COUNTRY);ck(WEAK_KEYWORDS,SCORE_WEAK)
    return total,matched

EXCLUDE_PATTERNS=[r'\bregister\s+for\b',r'\bjoin\s+us\b',r'\bcall\s+for\s+papers\b',r'\bvacancy\b',r'\bjob\s+posting\b',r'\bjob\s+opening\b',r'\bapply\s+now\b',r'\bcareer\b',r'\brecruitment\b',r'\bsign\s+up\b',r'\benroll\b']
HIGH_VALUE_PATTERNS=[r'\breport\b',r'\bpolicy\s+brief\b',r'\bresearch\s+paper\b',r'\banalysis\b',r'\bcommentary\b',r'\bworking\s+paper\b',r'\bwhite\s+paper\b',r'\bstudy\b',r'\bin-depth\b',r'\bstrategic\s+assessment\b',r'\bforecast\b']
MEDIUM_VALUE_PATTERNS=[r'\bblog\b',r'\bopinion\b',r'\beditorial\b',r'\bnews\s+update\b',r'\binterview\b',r'\bperspective\b',r'\binsight\b',r'\bbriefing\b']
LOW_VALUE_PATTERNS=[r'\bpress\s+release\b',r'\bmedia\s+coverage\b',r'\bnewsletter\b',r'\bannouncement\b',r'\bdigest\b']

def classify_content_type(title,url):
    t=f"{title} {url}".lower()
    for p in EXCLUDE_PATTERNS:
        if re.search(p,t):return "excluded","excluded"
    for p in HIGH_VALUE_PATTERNS:
        if re.search(p,t):return "high","priority_read"
    for p in MEDIUM_VALUE_PATTERNS:
        if re.search(p,t):return "medium","normal"
    for p in LOW_VALUE_PATTERNS:
        if re.search(p,t):return "low","low"
    return "unknown","normal"

HEADERS={"User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36","Accept-Language":"en-US,en;q=0.9,ar;q=0.8"}

def fetch_html_requests(url,timeout=20):
    try:r=requests.get(url,headers=HEADERS,timeout=timeout);r.raise_for_status();return r.text
    except Exception as e:log.warning(f"  requests 失败 {url}: {e}");return None

def fetch_html_playwright(url,timeout=30000):
    if not HAS_PLAYWRIGHT:return None
    try:
        with sync_playwright() as p:
            b=p.chromium.launch(headless=True);c=b.new_context(user_agent=HEADERS["User-Agent"],locale="en-US")
            pg=c.new_page();pg.goto(url,timeout=timeout,wait_until="networkidle");pg.wait_for_timeout(2000)
            h=pg.content();b.close();return h
    except Exception as e:log.warning(f"  Playwright 失败 {url}: {e}");return None

def fetch_html(url,use_playwright=False):
    html=fetch_html_requests(url)
    if use_playwright or(html and len(html)<2000):
        pw=fetch_html_playwright(url)
        if pw and len(pw)>len(html or""):html=pw
    return html

def extract_articles_from_page(html,base_url,page_url,selectors,tank_name):
    soup=BeautifulSoup(html,"html.parser");articles=[];seen=set()
    for c in soup.select(selectors.get("article","article")):
        te=c.select_one(selectors.get("title","h2 a, h3 a"))
        if not te:te=c.select_one("a[href]")
        if not te:continue
        t=te.get_text(strip=True);h=te.get("href","")
        if not t or len(t)<5:continue
        if h.startswith("/"):h=base_url.rstrip("/")+h
        elif not h.startswith("http"):h=base_url.rstrip("/")+"/"+h
        if h in seen:continue
        seen.add(h)
        se=c.select_one(selectors.get("snippet","p"));sn=se.get_text(strip=True) if se else ""
        de=c.select_one(selectors.get("date","time"));ds=None
        if de:ds=de.get("datetime") or de.get_text(strip=True)
        articles.append({"title":t,"url":h,"snippet":sn[:500],"date":ds})
    if not articles:
        for lk in soup.find_all("a",href=True):
            t=lk.get_text(strip=True);h=lk["href"]
            if len(t)<10 or len(t)>300:continue
            if any(s in t.lower() for s in ["home","about","contact","menu","login","search","privacy","cookie","terms","©","copyright","facebook","twitter","linkedin","instagram"]):continue
            if any(s in h.lower() for s in ["#","javascript:","mailto:","tel:","facebook.com","twitter.com","linkedin.com"]):continue
            if h.startswith("/"):h=base_url.rstrip("/")+h
            elif not h.startswith("http"):h=base_url.rstrip("/")+"/"+h
            if h in seen:continue
            seen.add(h)
            pa=lk.parent;sn=""
            if pa:pt=pa.find_next_sibling("p") or pa.find("p");sn=pt.get_text(strip=True)[:500] if pt else ""
            articles.append({"title":t,"url":h,"snippet":sn,"date":None})
    return articles

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
            if not ds:ds=e.get("published",e.get("updated",""))
            sn=""
            if hasattr(e,"summary"):sn=re.sub(r'<[^>]+>','',e.summary).strip()[:500]
            elif hasattr(e,"description"):sn=re.sub(r'<[^>]+>','',e.description).strip()[:500]
            arts.append({"title":t,"url":lk,"snippet":sn,"date":ds,"fetch_method":"rss"})
        log.info(f"  📡 RSS获取 {len(arts)} 条: {feed_url}");return arts
    except Exception as e:log.warning(f"  RSS失败 {feed_url}: {e}");return []

def scrape_think_tank(tank,use_playwright=False):
    nm,co,ti,bu=tank["name"],tank["country"],tank["tier"],tank["base_url"]
    log.info(f"📚 {nm} ({co}) [{ti}]")
    raw=[]
    for pp in tank["pages"]:
        url=bu.rstrip("/")+pp;log.info(f"  🌐 抓取: {url}")
        html=fetch_html(url,use_playwright=use_playwright)
        if not html:continue
        items=extract_articles_from_page(html,bu,url,tank["selectors"],nm)
        log.info(f"    发现 {len(items)} 个候选条目")
        for it in items[:3]:log.debug(f"    [候选] {it['title'][:80]}")
        raw.extend(items);time.sleep(1)
    for fu in tank.get("rss_feeds",[]):raw.extend(fetch_rss_articles(fu,nm))
    seen=set();unique=[]
    for it in raw:
        if it["url"] not in seen:seen.add(it["url"]);unique.append(it)
    results=[]
    for it in unique:
        t,sn,u=it["title"],it.get("snippet",""),it["url"]
        ct,pr=classify_content_type(t,u)
        if ct=="excluded":log.debug(f"    ❌ 排除: {t[:60]}");continue
        if ti=="core_gcc":ks,mk=99.0,["core_gcc_auto_pass"]
        else:
            ks,mk=compute_keyword_score(t,sn)
            if ks<RELEVANCE_THRESHOLD:log.debug(f"    ⏭️ 评分不足({ks}): {t[:60]}");continue
        results.append(Article(title=t,url=u,source=nm,source_country=co,source_tier=ti,date=it.get("date"),snippet=sn,keyword_score=ks,content_type=ct,priority=pr,matched_keywords=mk,fetch_method=it.get("fetch_method","html")))
    log.info(f"  ✅ {nm}: {len(unique)} 篇候选 → {len(results)} 篇通过筛选\n");return results

def run_scraper(tanks=None,use_playwright=False,enable_ai=False,api_key=None,countries=None):
    if tanks is None:tanks=THINK_TANKS
    if countries:cl=[c.lower() for c in countries];tanks=[t for t in tanks if t["country"].lower() in cl]
    print("="*60)
    print(f"GCC智库研究抓取系统 v2.1\n运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n目标智库: {len(tanks)} 个")
    print(f"JS渲染: {'✅ Playwright' if use_playwright and HAS_PLAYWRIGHT else '❌ 仅requests'}")
    print(f"AI筛选: {'✅ 已启用' if enable_ai and HAS_ANTHROPIC else '❌ 未启用'}")
    print(f"RSS:    {'✅ feedparser' if HAS_FEEDPARSER else '❌ 未安装'}")
    print("="*60+"\n")
    all_a=[]
    for tk in tanks:
        try:all_a.extend(scrape_think_tank(tk,use_playwright=use_playwright))
        except Exception as e:log.error(f"❌ 抓取 {tk['name']} 失败: {e}")
    if enable_ai:all_a=ai_classify_batch(all_a,api_key);all_a=[a for a in all_a if a.ai_verdict!="not_relevant"]
    po={"priority_read":0,"normal":1,"low":2};all_a.sort(key=lambda a:po.get(a.priority,1))
    print("\n"+"="*60+f"\n抓取完成: 共 {len(all_a)} 篇相关文章")
    bp={}
    for a in all_a:bp.setdefault(a.priority,[]).append(a)
    for p,ar in bp.items():print(f"  {p}: {len(ar)} 篇")
    rc=sum(1 for a in all_a if a.fetch_method=="rss")
    if rc:print(f"  (其中 RSS 获取: {rc} 篇)")
    print("="*60);return all_a

def export_markdown(articles,filepath=None):
    now=datetime.now().strftime("%Y-%m-%d %H:%M")
    filepath=filepath or f"gcc_research_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
    L=[f"# GCC智库研究动态\n",f"> 抓取时间: {now} | 文章总数: {len(articles)} 篇 | 系统: v2.1 — 成都创新金融研究院\n"]
    gs={"priority_read":("⭐ 优先阅读（深度报告/政策分析）",[]),"normal":("📄 常规文章",[]),"low":("📋 简讯/公告",[])}
    for a in articles:k=a.priority if a.priority in gs else "normal";gs[k][1].append(a)
    for key in["priority_read","normal","low"]:
        lb,ar=gs[key]
        if not ar:continue
        L.append(f"---\n## {lb} ({len(ar)} 篇)\n")
        L.append("| 日期 | 平台 | 标题 | 中文标题 | 链接 |")
        L.append("|------|------|------|----------|------|")
        for a in ar:
            d=a.date if a.date else "-"
            tc=a.title.replace("|","–").replace("\n"," ").strip()
            cn=(a.title_cn or "-").replace("|","–").replace("\n"," ").strip()
            L.append(f"| {d} | {a.source.replace('|','–')} | {tc} | {cn} | [原文]({a.url}) |")
        L.append("")
    with open(filepath,"w",encoding="utf-8") as f:f.write("\n".join(L))
    log.info(f"📝 Markdown 报告已保存: {filepath}");return filepath

def export_json(articles,filepath=None):
    filepath=filepath or f"gcc_research_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    data={"metadata":{"scraped_at":datetime.now().isoformat(),"total_articles":len(articles),"system":"GCC Think Tank Scraper v2.1"},"articles":[a.to_dict() for a in articles]}
    with open(filepath,"w",encoding="utf-8") as f:json.dump(data,f,ensure_ascii=False,indent=2)
    log.info(f"💾 JSON 数据已保存: {filepath}");return filepath

def check_ai_ready(api_key=None):
    if not HAS_ANTHROPIC:return False,"❌ 未安装 anthropic 包\n   pip install anthropic"
    key=api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:return False,"❌ 未设置 API Key\n   export ANTHROPIC_API_KEY=\"sk-ant-xxx...\"\n   或 --api-key sk-ant-xxx..."
    return True,key

def ai_classify_batch(articles,api_key=None):
    ready,info=check_ai_ready(api_key)
    if not ready:print(f"\n⚠️  AI辅助筛选跳过: {info}");return articles
    key=info;client=anthropic.Anthropic(api_key=key)
    bl=[a for a in articles if a.content_type=="unknown" and 2<=a.keyword_score<=4]
    if not bl:log.info("无边界模糊文章，跳过AI辅助筛选");return articles
    log.info(f"🤖 AI辅助筛选 {len(bl)} 篇边界文章...")
    it="\n".join(f"{i+1}. [{a.source}] {a.title}"+(f"\n   摘要: {a.snippet[:200]}" if a.snippet else "") for i,a in enumerate(bl))
    prompt=f"你是GCC政治经济研究助手。判断以下文章是否与GCC六国相关。\n对每篇回答：1.是否相关(yes/no) 2.类型(research/opinion/news/event/other)\n严格按JSON数组返回：[{{\"id\":1,\"relevant\":true,\"type\":\"research\"}},...]\n\n{it}"
    try:
        resp=client.messages.create(model="claude-haiku-4-5-20251001",max_tokens=1000,messages=[{"role":"user","content":prompt}])
        tx=resp.content[0].text.strip();tx=re.sub(r'^```json\s*','',tx);tx=re.sub(r'\s*```$','',tx);rs=json.loads(tx)
        for r in rs:
            idx=r["id"]-1
            if 0<=idx<len(bl):bl[idx].ai_verdict="relevant" if r.get("relevant") else "not_relevant";
            if r.get("type")=="research":bl[idx].priority="priority_read"
            elif r.get("type")=="event":bl[idx].content_type="excluded"
        log.info(f"  AI分类完成: {len(rs)} 篇")
    except Exception as e:log.error(f"  AI分类失败: {e}")
    return articles

def batch_translate_titles(articles,api_key=None):
    ready,info=check_ai_ready(api_key)
    if not ready:return articles
    key=info;need=[a for a in articles if a.title_cn is None and a.title]
    if not need:return articles
    BS=30;client=anthropic.Anthropic(api_key=key);print(f"\n🌐 批量翻译 {len(need)} 个标题...")
    for i in range(0,len(need),BS):
        batch=need[i:i+BS];tt="\n".join(f"{j+1}. {a.title}" for j,a in enumerate(batch))
        try:
            resp=client.messages.create(model="claude-haiku-4-5-20251001",max_tokens=2000,messages=[{"role":"user","content":f"将以下英文标题翻译为简洁中文，保留专有名词。严格按JSON数组返回，无其他文字：\n[{{\"id\":1,\"cn\":\"中文标题\"}},...]\n\n{tt}"}])
            tx=resp.content[0].text.strip();tx=re.sub(r'^```json\s*','',tx);tx=re.sub(r'\s*```$','',tx);rs=json.loads(tx)
            for r in rs:
                idx=r["id"]-1
                if 0<=idx<len(batch):batch[idx].title_cn=r.get("cn","")
        except Exception as e:log.warning(f"  翻译批次 {i//BS+1} 失败: {e}")
    tr=sum(1 for a in articles if a.title_cn);print(f"  ✅ 已翻译 {tr}/{len(need)} 个标题");return articles

def generate_ai_summary(articles,api_key=None):
    ready,info=check_ai_ready(api_key)
    if not ready:print(f"\n⚠️  AI汇总跳过: {info}");return None
    if not articles:print("\n⚠️  AI汇总跳过: 没有文章");return None
    key=info
    pa=[a for a in articles if a.priority=="priority_read"][:20]
    oa=[a for a in articles if a.priority!="priority_read"][:20]
    sel=pa+oa
    if not sel:print("\n⚠️  AI汇总跳过: 筛选后无文章");return None
    at=""
    for i,a in enumerate(sel,1):
        at+=f"{i}. [{a.source}] {a.title}\n   URL: {a.url}\n"
        if a.snippet:at+=f"   摘要: {a.snippet[:300]}\n"
    prompt=f"""你是GCC（海湾合作委员会）区域研究分析师，为成都创新金融研究院撰写内部简报。

严格规则：
- 每条判断后必须标注信息来源类型：
  【原文直述】= 文章标题/摘要中直接可见的事实
  【AI推断】= 你根据多篇文章交叉分析得出的推测
  【待核实】= 信息不完整、可能过时、或仅凭标题无法确认
- 不要空泛总结，每一条必须落到具体文章，附上文章标题和URL
- 中文输出，精炼，适合5分钟快速浏览

请按以下结构输出：

## 一、本期关键发现（3-5条）

每条格式：
### 发现X：[一句话标题]
- 核心内容：（2-3句精准描述）
- 信息来源标注：【原文直述/AI推断/待核实】
- 关联文章：[文章标题](URL)

## 二、重点文章推荐（5篇）

每条格式：
### [中文标题]
- 原标题：[英文原标题]
- 来源：[智库名称]
- 链接：[URL]
- 推荐理由：（1-2句）
- 中文摘要：（3-5句，提炼关键论点和结论）
- 信息来源标注：【原文直述/AI推断/待核实】

## 三、趋势信号（2-3条）

每条格式：
### 信号X：[趋势名称]
- 判断依据：（列出支撑此判断的具体文章标题和URL）
- 信息来源标注：【AI推断】
- 对研究院的建议：（1句话）

文章列表（共{len(sel)}篇）：
{at}"""
    print(f"\n🤖 正在调用 Claude 生成研究简报（{len(sel)} 篇文章）...")
    client=anthropic.Anthropic(api_key=key)
    try:
        resp=client.messages.create(model="claude-sonnet-4-20250514",max_tokens=4000,messages=[{"role":"user","content":prompt}])
        sm=resp.content[0].text;print("✅ AI研究简报生成成功");return sm
    except anthropic.AuthenticationError:print("❌ AI汇总失败: API Key 无效");return None
    except anthropic.RateLimitError:print("❌ AI汇总失败: 请求频率超限");return None
    except Exception as e:print(f"❌ AI汇总失败: {e}");return None

if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser(description="GCC智库研究抓取系统 v2.1")
    parser.add_argument("--countries",nargs="+",default=None,help="只抓指定国家")
    parser.add_argument("--playwright",action="store_true",help="启用JS渲染")
    parser.add_argument("--ai",action="store_true",help="启用AI筛选、翻译、汇总")
    parser.add_argument("--api-key",default=None,help="Anthropic API Key")
    parser.add_argument("--output-dir",default="./output",help="输出目录")
    parser.add_argument("--debug",action="store_true",help="调试日志")
    args=parser.parse_args()
    if args.debug:logging.getLogger("gcc_scraper").setLevel(logging.DEBUG)
    if args.ai:
        ready,info=check_ai_ready(args.api_key)
        if not ready:
            print("\n"+"="*60+f"\n⚠️  --ai 已启用但AI不可用：\n{info}\n"+"="*60)
            if input("\n继续（不用AI）？[y/N] ").strip().lower()!="y":print("已退出。");exit(0)
            args.ai=False
    od=Path(args.output_dir);od.mkdir(parents=True,exist_ok=True)
    articles=run_scraper(use_playwright=args.playwright,enable_ai=args.ai,api_key=args.api_key,countries=args.countries)
    if articles:
        ts=datetime.now().strftime('%Y%m%d_%H%M')
        if args.ai:articles=batch_translate_titles(articles,args.api_key)
        md_path=export_markdown(articles,str(od/f"gcc_research_{ts}.md"))
        json_path=export_json(articles,str(od/f"gcc_research_{ts}.json"))
        sp=None
        if args.ai:
            sm=generate_ai_summary(articles,args.api_key)
            if sm:
                sp=od/f"gcc_summary_{ts}.md"
                with open(sp,"w",encoding="utf-8") as f:
                    f.write(f"# GCC研究动态AI简报\n\n> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')} | 分析文章: {len(articles)} 篇 | v2.1 — 成都创新金融研究院\n\n")
                    f.write("> ⚠️ 标注说明：【原文直述】= 文章中直接可见的事实 | 【AI推断】= 交叉分析推测 | 【待核实】= 信息不完整或可能过时\n\n")
                    f.write(sm)
        print(f"\n{'='*60}\n📂 输出文件:\n  📝 Markdown报告: {md_path}\n  💾 JSON数据:     {json_path}")
        if args.ai:print(f"  🤖 AI研究简报:   {sp}" if sp else "  🤖 AI研究简报:   ❌ 生成失败")
        print("="*60)
    else:print("\n⚠️ 未抓取到文章。\n  1. 检查网络\n  2. 添加 --playwright\n  3. 添加 --debug")
