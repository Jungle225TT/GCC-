#!/usr/bin/env python3
"""
v2.4.1 关键词漏斗回归测试
基于马老师 4-29 标注样本英文原标题（43篇：绿16 / 黄17 / 红4）

运行方式：
  cd /path/to/GccScraper
  python scripts/test_keywords_funnel.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gcc_thinktank_scraper_v2 import (
    compute_keyword_score,
    classify_content_type,
    compute_topic_relevance_score,
    apply_source_relevance_adjustments,
    apply_keyword_demotion,
    _KW,
    STRONG_KEYWORDS,
    RELEVANCE_THRESHOLD,
    Article,
    THINK_TANKS,
    get_compliance_rule,
    high_risk_sources_records,
    filtered_out_notice,
    normalize_date,
    _clean_article_title,
    _classify_candidate,
    _dedupe_articles_by_title,
    _is_likely_article,
    extract_articles_from_page,
    _detect_blocking_reason,
    _classify_fetch_exception,
)
import requests

# ─────────────────────────────────────────────────────────────────────────────
# 测试数据集（英文原标题）
# ─────────────────────────────────────────────────────────────────────────────

RED_TITLES = [
    "Two Leading Global Universities Add the Doha Historical Dictionary to Their Digital Libraries",
    "Dr. Shaikh Mohamed Bin Hamad Al Khalifa",
    "Maritime Security in the Gulf of Guinea: The Shift from Piracy to Proxy Conflicts",
    "Fourth episode of the sound of thoughts podcast",
    # v1.2 升级：从降权词升级为硬过滤词（core_gcc tier 降权 -2 无效，须走第三层剔除）
    "IRAN IN A WEEK March April 16-22, 2026",
    "IRAN IN A WEEK April 9-15, 2026",
    "Rasanah's Monthly Iran Case File: February-March 2026",
    "IRAN IN A WEEK March April 2-8, 2026",
]

YELLOW_DEMOTE_TITLES = [
    "The Washington–Vatican Rift: Causes and Implications",
    'Book Review: "The 2019 Legislative and Presidential Elections in Tunisia"',
    "How Did the IRGC Seize Power in Iran?",
    "After Orbán: A Political Turning Point",
    "Digital Activism within the Coptic Community in North America",
    "US-European Disagreements Over the War in Iran and NATO's Future",
    "Western Sahara in Transition: Geopolitics, Diplomacy, and Uncertain Future",
]

GREEN_TITLES = [
    "What swap, Gulf?",
    "Iranian Policies on Arabian Gulf and Regional Security from the 1979 Revolution to the 2026 War",
    "'A long time coming': How to understand the UAE's decision to leave OPEC",
    "Why is the UAE leaving OPEC?",
    "The Hollow Promise of Arab Solidarity",
    "The Gulf's Iran Problem Isn't Solved",
    "Can Qatar Still Mediate After Becoming a Target?",
    "The Hormuz Disruption and Rethinking Energy Security",
    "Iran's Missile and Drone Programs and Security in the Arabian Gulf",
    "The Non-Financial Benefits of Bahrain's Demands for Compensation",
    'Combating Iran\'s "Mutually Assured Destruction" Doctrine: Lessons from History',
    "Eroding Trust and the Future of Iran–Gulf Engagement",
    "Shock, Adaptation and Resilience: The Global Economic Fallout of the 2026 Hormuz Crisis",
    "Leverage at the Chokepoint: Wartime Power, Peacetime Limits",
    "Bahrain's Cabinet Announces a Timely Economic Support Package",
    "STEP and the Possibility of a New Regional Bloc in the Middle East",
    "Iraq's Fatal Dilemma: Axis of Resistance or Regional Integration?",
]

# ─────────────────────────────────────────────────────────────────────────────
# 辅助函数
# ─────────────────────────────────────────────────────────────────────────────

def make_test_article(title, snippet=""):
    """构造一个最小 Article（不是 core_gcc，模拟 pan_mena 来源）。"""
    return Article(
        title=title,
        url=f"https://example.com/{title[:30].replace(' ', '-').lower()}",
        source="Test Source",
        source_country="Test",
        source_tier="pan_mena",
        snippet=snippet,
    )


def score_with_demote(article):
    """
    方案 C2：第二层评分 + 降权词扣分。
    复现 scrape_think_tank 中的注入逻辑，供测试直接调用。
    同步支持 title_only_demote_set（v1.3：NATO 等词仅检查标题）。
    """
    ks, mk = compute_keyword_score(article.title, article.snippet or "")
    ks, hits = apply_keyword_demotion(ks, article.title, article.snippet or "")
    if hits:
        if not hasattr(article, "_funnel_debug"):
            article._funnel_debug = {}
        article._funnel_debug["demote_hits"] = hits
        article._funnel_debug["demote_penalty"] = _KW["max_penalty"]
    return ks


def is_hard_filtered(article):
    """调用第三层：classify_content_type 返回 excluded 则为 True。"""
    ct, _ = classify_content_type(article.title, article.url)
    return ct == "excluded"


# ─────────────────────────────────────────────────────────────────────────────
# 测试函数
# ─────────────────────────────────────────────────────────────────────────────

def test_keywords_yaml_loaded():
    """keywords.yaml 必须成功加载，filter_set 和 demote_set 不为空。"""
    assert len(_KW["filter_set"]) > 0, "filter_set 为空，keywords.yaml 可能未加载"
    assert len(_KW["demote_set"]) > 0, "demote_set 为空，keywords.yaml 可能未加载"
    print(f"  [OK] keywords.yaml 加载成功：filter={len(_KW['filter_set'])} 词，demote={len(_KW['demote_set'])} 词")


def test_strong_keywords_contain_rescue_words():
    """三个关键救回词必须存在于 STRONG_KEYWORDS。"""
    required = ["mutually assured destruction", "arabian gulf", "regional security"]
    sk_lower = [kw.lower() for kw in STRONG_KEYWORDS]
    for w in required:
        assert w in sk_lower, f"STRONG_KEYWORDS 缺少关键救回词: {w}"
    print(f"  [OK] 三个关键救回词均在 STRONG_KEYWORDS 中")


def test_red_titles_filtered():
    """4 篇红色样本全部应被第三层硬过滤剔除。"""
    failed = []
    for title in RED_TITLES:
        art = make_test_article(title)
        if not is_hard_filtered(art):
            failed.append(title)
    assert not failed, f"以下红色样本未被硬过滤:\n" + "\n".join(f"  - {t}" for t in failed)
    print(f"  [OK] {len(RED_TITLES)}/{len(RED_TITLES)} 篇红色样本全部被硬过滤")


def test_green_not_filtered():
    """16 篇绿色样本全部不应被硬过滤。"""
    failed = []
    for title in GREEN_TITLES:
        art = make_test_article(title)
        if is_hard_filtered(art):
            failed.append(title)
    assert not failed, f"以下绿色样本被误过滤:\n" + "\n".join(f"  - {t}" for t in failed)
    print(f"  [OK] {len(GREEN_TITLES)}/{len(GREEN_TITLES)} 篇绿色样本零误杀")


def test_yellow_demoted():
    """黄色降权词样本应命中降权，_funnel_debug['demote_penalty'] == -2。"""
    failed = []
    for title in YELLOW_DEMOTE_TITLES:
        art = make_test_article(title)
        score_with_demote(art)
        debug = getattr(art, "_funnel_debug", {})
        if debug.get("demote_penalty") != -2:
            failed.append(title)
    assert not failed, f"以下黄色样本未被降权:\n" + "\n".join(f"  - {t}" for t in failed)
    print(f"  [OK] {len(YELLOW_DEMOTE_TITLES)}/{len(YELLOW_DEMOTE_TITLES)} 篇黄色样本全部降权 -2")


def test_mad_doctrine_rescued():
    """
    ⭐ 关键回归：#25 含「Lessons from History」（降权词），
    但标题同时含「Mutually Assured Destruction」（强信号词），
    最终评分应 >= 3（通过阈值，进入推荐档）。
    """
    title = 'Combating Iran\'s "Mutually Assured Destruction" Doctrine: Lessons from History'
    art = make_test_article(title)
    score = score_with_demote(art)
    debug = getattr(art, "_funnel_debug", {})
    # 验证确实命中了降权词
    assert debug.get("demote_penalty") == -2, f"未触发降权，debug={debug}"
    # 验证被强信号词救回（总分仍高于阈值）
    assert score >= RELEVANCE_THRESHOLD, (
        f"被降权后未能被救回，score={score} < threshold={RELEVANCE_THRESHOLD}\n"
        f"  debug={debug}\n"
        f"  请确认 'mutually assured destruction' 在 STRONG_KEYWORDS 中"
    )
    print(f"  [OK] ⭐ MAD Doctrine 救回：score={score:.1f}（降权 -2 后仍 >= {RELEVANCE_THRESHOLD}）")


def test_1979_revolution_rescued():
    """
    ⭐ 关键回归：#6 含「1979 Revolution」（降权词），
    但标题含「Arabian Gulf」和「Regional Security」（强信号词），
    最终评分应 >= 3。
    """
    title = "Iranian Policies on Arabian Gulf and Regional Security from the 1979 Revolution to the 2026 War"
    art = make_test_article(title)
    score = score_with_demote(art)
    debug = getattr(art, "_funnel_debug", {})
    assert debug.get("demote_penalty") == -2, f"未触发降权，debug={debug}"
    assert score >= RELEVANCE_THRESHOLD, (
        f"被降权后未能被救回，score={score} < threshold={RELEVANCE_THRESHOLD}\n"
        f"  debug={debug}\n"
        f"  请确认 'arabian gulf'/'regional security' 在 STRONG_KEYWORDS 中"
    )
    print(f"  [OK] ⭐ 1979 Revolution 救回：score={score:.1f}（降权 -2 后仍 >= {RELEVANCE_THRESHOLD}）")


def test_green_demoted_still_rescued():
    """被降权的绿色样本，最终分应仍 >= RELEVANCE_THRESHOLD（强信号词救回有效）。
    注意：部分绿色样本在 pan_mena 通用来源下本身关键词得分低（真实系统靠 source tier 通过），
    此测试只验证「被降权」的绿色文章能被救回，不验证未降权的低分文章。"""
    failed = []
    rescued = []
    for title in GREEN_TITLES:
        art = make_test_article(title)
        if is_hard_filtered(art):
            continue
        score = score_with_demote(art)
        debug = getattr(art, "_funnel_debug", {})
        if debug.get("demote_penalty") == -2:
            if score < RELEVANCE_THRESHOLD:
                failed.append(f"{title[:70]}  (score={score:.1f}, hits={debug.get('demote_hits')})")
            else:
                rescued.append(title)
    assert not failed, "以下被降权的绿色样本未被强信号词救回:\n" + "\n".join(f"  - {t}" for t in failed)
    print(f"  [OK] 被降权的绿色样本均被强信号词救回（{len(rescued)} 篇，阈值={RELEVANCE_THRESHOLD}）")


def test_pan_mena_event_announcement_hard_filtered():
    """本轮 pan_mena 漏网样本：活动/实习公告必须先于 low 判断被硬过滤。"""
    title = "AL SHARQ STRATEGIC RESEARCH INTERNSHIP PROGRAM ANNOUNCEMENT"
    art = make_test_article(title, "Apply for the Al Sharq Strategic Research internship program.")
    ct, priority = classify_content_type(art.title, art.url)
    assert (ct, priority) == ("excluded", "excluded"), f"公告未被硬过滤: {(ct, priority)}"
    print("  [OK] pan_mena 实习公告样本被硬过滤")


def test_career_center_policy_study_not_hard_filtered():
    """career 裸词不能误杀 UAE 就业/教育政策研究，只过滤招聘和活动语境。"""
    title = "Employment Pathways or Empty Promises? Student Perceptions of University and Career Center Support in Facilitating Employment in the UAE"
    art = make_test_article(title)
    ct, priority = classify_content_type(art.title, art.url)
    assert (ct, priority) != ("excluded", "excluded"), f"career center 政策研究被误过滤: {(ct, priority)}"
    assert _is_likely_article(title, art.url), "career center 政策研究不应被文章有效性规则剔除"

    workshop = make_test_article("KAPSARC holds Career Paths Workshop in Washington DC")
    assert is_hard_filtered(workshop), "career paths workshop 应被过滤"
    print("  [OK] career center 政策研究保留，career workshop 过滤")


def test_core_gcc_recent_noise_hard_filtered():
    """core_gcc 自动 99 分下，近期发现的公告/偏题样本必须走硬过滤。"""
    titles = [
        "Rasanah’s Iran Case File for April 2026 Is Now Available",
        "How Did the IRGC Seize Power in Iran?",
        "The Washington–Vatican Rift: Causes and Implications",
        "AJCS to Participate in Decolonizing Knowledge Forum in Istanbul",
        "Book Signings Held for Four New AJCS Titles",
        "Derasat Center participates in the Joint Regional Initiative“Bridging Stability: EU-GCC Cooperation in an Era of Fragmentation”",
        "Derasat Center CEO discusses knowledge partnership and research cooperation with U.S. Ambassador",
    ]
    failed = []
    for title in titles:
        if not is_hard_filtered(make_test_article(title)):
            failed.append(title)
    assert not failed, "以下 core_gcc 噪音样本未被硬过滤:\n" + "\n".join(f"  - {t}" for t in failed)
    print(f"  [OK] {len(titles)} 条 core_gcc 近期噪音样本被硬过滤")


def test_core_gcc_auto_pass_does_not_force_strong_relevance():
    """core_gcc 自动通过只负责保留文章，强相关仍需真实议题信号。"""
    broad_title = "Syria Escapes Iran War, Can It Benefit From It?"
    broad_score, _ = compute_keyword_score(broad_title, "")
    broad_relevance = compute_topic_relevance_score(
        99.0, "high", source_tier="core_gcc", actual_keyword_score=broad_score,
    )
    assert broad_relevance < 4.0, f"泛中东题目不应自动进强相关: {broad_relevance}"

    focused_title = "Gulf States Adjust to a New Normal"
    focused_score, _ = compute_keyword_score(focused_title, "")
    focused_relevance = compute_topic_relevance_score(
        99.0, "high", source_tier="core_gcc", actual_keyword_score=focused_score,
    )
    assert focused_relevance >= 4.0, f"含 Gulf States 强信号的题目应保持强相关: {focused_relevance}"
    print("  [OK] core_gcc 自动通过不再把泛议题直接推入强相关")


def test_vehicle_technology_case_study_demoted_to_medium():
    """车辆技术/可持续性基准类能源技术文章应保留，但只进入中等相关。"""
    title = "Towards a Normalized Sustainability Benchmarking Framework for Vehicle Technologies: A Saudi Case Study"
    actual_score, actual_matches = compute_keyword_score(title, "")
    demoted_score, demote_hits = apply_keyword_demotion(actual_score, title, "")
    article = make_test_article(title)
    article.source_tier = "core_gcc"
    article.keyword_score = 99.0
    article.content_type = "high"
    article.topic_relevance_score = compute_topic_relevance_score(
        99.0,
        "high",
        source_tier="core_gcc",
        actual_keyword_score=demoted_score,
    )
    apply_source_relevance_adjustments(article, {}, demoted_score, actual_matches)

    assert demote_hits, "车辆技术/可持续性基准样本未命中降权词"
    assert article.topic_relevance_score < 4.0, (
        f"车辆技术案例研究不应进入强相关: score={article.topic_relevance_score}, "
        f"actual={actual_score}, demoted={demoted_score}, hits={demote_hits}"
    )
    assert article.topic_relevance_score == 3.5, f"预期下沉为中等相关 3.5 分: {article.topic_relevance_score}"
    print("  [OK] 车辆技术/可持续性基准案例研究下沉至中等相关")


def test_core_gcc_title_strong_signal_promoted_even_when_content_type_unknown():
    """core_gcc 标题强信号应进强相关，不能因 URL 未标明 analysis/report 被压低。"""
    cases = [
        "Brent and WTI Dynamics During the Hormuz Crisis: Positioning and the Expanding Role of Options",
        "Drone Warfare and Arabian Gulf Security: The Strategic Value of Cooperation with Ukraine",
        "A New Era In GCC-UK Economic and Trade Relations",
    ]
    failed = []
    for title in cases:
        actual_score, actual_matches = compute_keyword_score(title, "")
        article = make_test_article(title)
        article.source_tier = "core_gcc"
        article.keyword_score = 99.0
        article.content_type = "unknown"
        article.topic_relevance_score = compute_topic_relevance_score(
            99.0,
            "unknown",
            source_tier="core_gcc",
            actual_keyword_score=actual_score,
        )
        apply_source_relevance_adjustments(article, {}, actual_score, actual_matches)
        if article.topic_relevance_score < 4.0:
            failed.append(f"{title} (score={article.topic_relevance_score}, matches={actual_matches})")
    assert not failed, "以下 core_gcc 强信号标题未进入强相关:\n" + "\n".join(f"  - {x}" for x in failed)
    print("  [OK] core_gcc 标题强信号即使内容类型 unknown 也进入强相关")


def test_count_badge_category_title_filtered():
    """分类/标签页计数标题如 Economic Security(2085) 不应进入文章池。"""
    title = "Economic Security(2085)"
    url = "https://www.csis.org/topics/economic-security"
    assert classify_content_type(title, url) == ("excluded", "excluded"), "计数标题未被第三层过滤"
    assert not _is_likely_article(title, url), "计数标题未被文章有效性规则过滤"
    print("  [OK] 计数型分类页标题被过滤")


def test_pan_mena_deep_topic_strong_titles_promoted():
    """deep_topic 保底不应遮蔽标题强信号，Hormuz/GCC/regional bloc 应进入强相关。"""
    titles = [
        "What Does the Strait of Hormuz’s Closure Mean?",
        "Can the Gulf Cooperation Council Transcend Its Divisions?",
        "STEP and the Possibility of a New Regional Bloc in the Middle East",
        "Iraq’s Fatal Dilemma: Axis of Resistance or Regional Integration?",
    ]
    failed = []
    for title in titles:
        score, matched = compute_keyword_score(title, "")
        final_score = max(5.0, score)
        relevance = compute_topic_relevance_score(final_score, "unknown")
        if any("(标题,+" in m for m in matched):
            relevance = max(relevance, 4.0)
        if final_score <= 5.0 or relevance < 4.0:
            failed.append(f"{title} (keyword={final_score}, relevance={relevance}, matched={matched})")
    assert not failed, "以下 deep_topic 强信号样本未进入强相关:\n" + "\n".join(f"  - {x}" for x in failed)
    print(f"  [OK] {len(titles)} 篇 pan_mena deep_topic 强信号样本进入强相关")


def test_deep_topic_auto_pass_does_not_force_strong_relevance():
    """deep_topic 保底只负责收录，标题无真实GCC信号时不应强推。"""
    tank = {"deep_topic": True}
    title = "Lebanon and Israel Talks: Empowering Diplomacy Over Open-Ended Conflict"
    actual_score, actual_matches = compute_keyword_score(title, "")
    article = make_test_article(title)
    article.keyword_score = 5.0
    article.content_type = "high"
    article.topic_relevance_score = compute_topic_relevance_score(5.0, "high")
    apply_source_relevance_adjustments(article, tank, actual_score, actual_matches)
    assert article.topic_relevance_score < 4.0, f"deep_topic 泛议题不应进强相关: {article.topic_relevance_score}"
    print("  [OK] deep_topic 保底不再把泛议题直接推入强相关")


def test_arab_reform_title_date_cleanup():
    """Arab Reform 卡片标题中混入日期/标签时，应抽取日期并清理展示标题。"""
    raw = "Paused, Not Resolved:The Saudi-UAE Rivalry and the War in Sudan—Commentary13 May 2026#Conflicts#Saudi Arabia#United Arab Emirates"
    assert normalize_date(raw) == "2026-05-13", f"日期抽取失败: {normalize_date(raw)}"
    cleaned = _clean_article_title(raw)
    expected = "Paused, Not Resolved:The Saudi-UAE Rivalry and the War in Sudan"
    assert cleaned == expected, f"标题清理失败: {cleaned!r}"

    raw_author = "Paused, Not Resolved:The Saudi-UAE Rivalry and the War in Sudan—&nbspLeena BadriBawader /"
    cleaned_author = _clean_article_title(raw_author)
    assert cleaned_author == expected, f"作者尾巴清理失败: {cleaned_author!r}"
    print("  [OK] Arab Reform 粘连标题可抽取日期并清理元数据")


def test_mei_link_scan_fallback_extracts_articles():
    """MEI 页面会把文章标题放在普通链接中，非 article/card 容器；全页链接扫描应补足。"""
    html = """
    <html><body>
      <nav><a href="/about">About</a></nav>
      <a href="/publications/what-does-uaes-departure-mean-opec">What Does the UAE’s Departure Mean for OPEC+?</a>
      <p>The UAE’s departure represents an undeniable strategic setback for OPEC+.</p>
      <div>May 8, 2026</div>
    </body></html>
    """
    selectors = {"article": "article, .card", "title": "h2 a, h3 a", "snippet": "p", "date": "time"}
    articles = extract_articles_from_page(html, "https://mei.edu", "https://mei.edu/regions/gulf/", selectors, "Middle East Institute (MEI)")
    assert len(articles) == 1, f"MEI fallback 未抽到文章: {articles}"
    assert articles[0]["title"] == "What Does the UAE’s Departure Mean for OPEC+?"
    assert articles[0]["date"] == "2026-05-08"
    print("  [OK] MEI 普通链接结构可由全页扫描抽取为文章")


def test_rss_candidate_uses_url_exclusion_rules():
    """RSS 条目也应复用 URL 导航/媒介过滤，避免 podcast 链接漏入文章池。"""
    title = "The IEA’s Fatih Birol on ‘the greatest energy security threat in history’"
    url = "https://www.atlanticcouncil.org/commentary/podcast/the-ieas-fatih-birol-on-the-greatest-energy-security-threat-in-history/"
    ct, priority, filter_hit = _classify_candidate(title, url)
    assert (ct, priority) == ("excluded", "excluded"), f"RSS podcast URL 未被过滤: {(ct, priority, filter_hit)}"
    assert filter_hit == "exclude_pattern"

    article_title = "What Gulf states need in a US-Iran deal"
    article_url = "https://www.atlanticcouncil.org/dispatches/what-gulf-states-need-in-a-us-iran-deal/"
    ct, priority, filter_hit = _classify_candidate(article_title, article_url)
    assert ct != "excluded", f"正常 RSS 文章不应被 URL 规则误杀: {(ct, priority, filter_hit)}"
    print("  [OK] RSS 候选条目已复用 URL 过滤规则且未误杀正常文章")


def test_atlantic_expert_media_mentions_hard_filtered():
    """Atlantic RSS 中专家媒体露出标题不应因 Hormuz 等强信号进入强相关。"""
    noise_titles = [
        "Braw in Future on the risk to seafarers in the Strait of Hormuz",
        "Braw in Sky News on Iran seizing ship in Strait of Hormuz",
        "Braw in Future Center on maritime tolls and global shipping",
        "Kroenig interviewed on NPR on Abraham Accords and Iran",
        "Charai for The National Interest: Iran’s Terror Regime Has Shown Its True Face",
    ]
    failed = []
    for title in noise_titles:
        ct, priority, filter_hit = _classify_candidate(
            title,
            f"https://www.atlanticcouncil.org/commentary/{title[:32].replace(' ', '-').lower()}/",
        )
        if (ct, priority) != ("excluded", "excluded"):
            failed.append(f"{title} -> {(ct, priority, filter_hit)}")
    assert not failed, "以下专家媒体露出标题未被硬过滤:\n" + "\n".join(f"  - {x}" for x in failed)

    issue_brief = "The new playbook for AI leadership: The case of the United Arab Emirates"
    ct, priority, filter_hit = _classify_candidate(
        issue_brief,
        "https://www.atlanticcouncil.org/in-depth-research-reports/issue-brief/the-new-playbook-for-ai-leadership-the-case-of-the-united-arab-emirates/",
    )
    assert ct != "excluded", f"Atlantic 正常 issue brief 不应被误杀: {(ct, priority, filter_hit)}"
    print("  [OK] Atlantic 专家媒体露出被过滤，正常 issue brief 保留")


def test_chatham_north_sea_oil_news_hard_filtered():
    """Chatham Gulf States 栏目混入的英国北海油新闻不应进入 GCC 简报。"""
    title = "UK should not invest in new North Sea oil as it is ‘a price taker, not a price maker’ – Dr Fatih Birol, IEA chief"
    url = "https://www.chathamhouse.org/2026/05/uk-should-not-invest-new-north-sea-oil-it-price-taker-not-price-maker-dr-fatih-birol-iea"
    ct, priority, filter_hit = _classify_candidate(title, url)
    assert (ct, priority) == ("excluded", "excluded"), f"Chatham 北海油新闻未被硬过滤: {(ct, priority, filter_hit)}"

    gulf_energy = "What Gulf states need in a changing oil market"
    ct, priority, filter_hit = _classify_candidate(
        gulf_energy,
        "https://www.chathamhouse.org/2026/05/what-gulf-states-need-changing-oil-market",
    )
    assert ct != "excluded", f"正常 Gulf energy 题目不应被误杀: {(ct, priority, filter_hit)}"
    print("  [OK] Chatham 北海油新闻被过滤，正常 Gulf energy 题目保留")


def test_same_source_duplicate_titles_keep_latest():
    """同一来源同标题不同 URL 时，保留排序后第一篇，通常就是最新版本。"""
    latest = Article(
        title="Derasat Center CEO discusses knowledge partnership and research cooperation with U.S. Ambassador",
        url="https://www.derasat.org.bh/en/derasat-center-ceo-discusses-knowledge-partnership-and-research-cooperation-with-u-s-ambassador-2/",
        source="Bahrain Center for Strategic, International and Energy Studies (Derasat)",
        source_country="Bahrain",
        source_tier="core_gcc",
        date="2026-05-21",
    )
    older = Article(
        title="Derasat Center CEO discusses knowledge partnership and research cooperation with U.S. Ambassador",
        url="https://www.derasat.org.bh/en/derasat-center-ceo-discusses-knowledge-partnership-and-research-cooperation-with-u-s-ambassador/",
        source="Bahrain Center for Strategic, International and Energy Studies (Derasat)",
        source_country="Bahrain",
        source_tier="core_gcc",
        date="2026-05-20",
    )
    other = Article(
        title="A New Era In GCC-UK Economic and Trade Relations",
        url="https://www.derasat.org.bh/en/a-new-era-in-gcc-uk-economic-and-trade-relations/",
        source="Bahrain Center for Strategic, International and Energy Studies (Derasat)",
        source_country="Bahrain",
        source_tier="core_gcc",
        date="2026-05-24",
    )
    deduped, removed = _dedupe_articles_by_title([latest, older, other])
    assert removed == 1
    assert [a.url for a in deduped] == [latest.url, other.url]
    print("  [OK] 同源重复标题去重保留最新版本")


def test_western_source_urls_updated():
    """本轮 403/404 排查沉淀：已知失效/旧路径不应继续作为主配置。"""
    by_name = {t["name"]: t for t in THINK_TANKS}
    assert "/topic/economics-and-energy/" not in by_name["Arab Gulf States Institute in Washington (AGSIW)"]["pages"]
    assert "/topic/security-and-defense/" not in by_name["Arab Gulf States Institute in Washington (AGSIW)"]["pages"]
    assert by_name["Middle East Institute (MEI)"]["base_url"] == "https://mei.edu"
    assert "/regions/gulf/" in by_name["Middle East Institute (MEI)"]["pages"]
    assert by_name["Middle East Institute (MEI)"].get("use_playwright") is True
    assert "/regions/middle-east/gulf" in by_name["Center for Strategic and International Studies (CSIS)"]["pages"]
    assert "/analysis" not in by_name["Center for Strategic and International Studies (CSIS)"]["pages"]
    assert "/regions/middle-east-and-north-africa/gulf-states" in by_name["Chatham House — Gulf States"]["pages"]
    assert "/regions/middle-east-north-africa/gulf-states" not in by_name["Chatham House — Gulf States"]["pages"]
    assert by_name["Chatham House — Gulf States"].get("use_playwright") is True
    assert "/center-for-energy-studies" in by_name["Baker Institute for Public Policy (Rice University)"]["pages"]
    assert "/centers/center-for-energy-studies/" not in by_name["Baker Institute for Public Policy (Rice University)"]["pages"]
    assert "/research" not in by_name["Baker Institute for Public Policy (Rice University)"]["pages"]
    assert "/collection/middle-east-program-research" in by_name["Wilson Center — Middle East Program"]["pages"]
    assert "/program/middle-east-program/publications" not in by_name["Wilson Center — Middle East Program"]["pages"]
    print("  [OK] western 来源 URL 配置已替换本轮发现的失效旧路径")


def test_blocked_sources_manual_and_rss_discovery_config():
    """默认跳过来源的人工/RSS发现层配置应与合规结论一致。"""
    by_name = {t["name"]: t for t in THINK_TANKS}

    brookings = by_name["Brookings Doha Center"]
    assert brookings.get("manual_monitor") is True
    assert brookings.get("rss_feeds") == [], "Brookings 旧 comments feed 不应继续配置为抓取源"
    assert "/regions/middle-east-north-africa/" in brookings["pages"]
    assert "/centers/center-for-middle-east-policy/" in brookings["pages"]

    atlantic = by_name["Atlantic Council — Middle East Programs"]
    assert atlantic.get("rss_discovery_only") is True
    assert atlantic.get("rss_metadata_only") is True
    assert atlantic.get("rss_feeds") == ["https://www.atlanticcouncil.org/region/middle-east/feed/"]
    assert "https://www.atlanticcouncil.org/feed/" not in atlantic.get("rss_feeds", [])
    atlantic_rule = get_compliance_rule(atlantic["base_url"])
    assert atlantic_rule.get("allow_scrape") is False
    assert atlantic_rule.get("rss_discovery_allowed") is True
    assert atlantic_rule.get("fulltext_scraping_allowed") is False

    iiss = by_name["International Institute for Strategic Studies (IISS)"]
    assert iiss.get("manual_monitor") is True
    assert iiss.get("rss_feeds") == [], "IISS 主站 RSS 403，不应配置为抓取源"
    assert "https://www.tandfonline.com/action/showAxaArticles?journalCode=tsur20" not in iiss["pages"]
    assert "https://milbalplus.iiss.org/" not in iiss["pages"]
    assert "https://www.tandfonline.com/action/showAxaArticles?journalCode=tsur20" in iiss.get("manual_pages", [])
    assert "https://milbalplus.iiss.org/" in iiss.get("manual_pages", [])
    print("  [OK] 默认跳过来源已按人工关注/RSS发现/订阅数据库分层配置")


def test_compliance_rules_cover_all_think_tanks():
    """29 个当前智库源都应命中 compliance_rules.yaml 的域名级规则。"""
    missing = []
    blocked = []
    for tank in THINK_TANKS:
        rule = get_compliance_rule(tank["base_url"])
        if rule.get("analysis_source") == "默认策略":
            missing.append(tank["name"])
        if rule.get("allow_scrape") is False:
            blocked.append(tank["name"])
    assert not missing, "以下来源未命中域名级合规规则:\n" + "\n".join(f"  - {x}" for x in missing)
    assert {"Brookings Doha Center", "Atlantic Council — Middle East Programs", "International Institute for Strategic Studies (IISS)"}.issubset(set(blocked)), (
        f"高风险默认禁用来源不完整: {blocked}"
    )
    print(f"  [OK] compliance_rules.yaml 覆盖 {len(THINK_TANKS)} 个当前智库源；默认禁用 {len(blocked)} 个高风险来源")


def test_high_risk_sources_records_for_dry_run_export():
    """dry-run 附带的 blocked_sources.csv 应覆盖默认跳过来源。"""
    rows = high_risk_sources_records()
    names = {row["source"] for row in rows}
    expected = {"Brookings Doha Center", "Atlantic Council — Middle East Programs", "International Institute for Strategic Studies (IISS)"}
    assert expected.issubset(names), f"默认跳过来源表不完整: {names}"
    for row in rows:
        links = row.get("manual_links") or []
        assert links and links[0]["label"] == "官网", f"缺少人工浏览官网入口: {row}"
        assert all(link.get("url", "").startswith("https://") for link in links), f"人工浏览入口必须是 HTTPS: {links}"
        assert row.get("metadata_allowed_path"), f"缺少合规替代发现路径: {row}"
        assert row.get("fulltext_allowed_path"), f"缺少合规全文路径: {row}"
    assert high_risk_sources_records(include_high_risk=True) == [], "--include-high-risk 时不应列为未抓取"
    print(f"  [OK] blocked_sources.csv 数据源覆盖 {len(rows)} 个默认跳过来源")


def test_tos_report_blocked_domains_have_alternative_paths():
    """docs/GCC_不可爬取网站及替代访问路径报告.md 中的禁止/需审批域名应落入合规规则。"""
    report_urls = {
        "https://www.cambridge.org/core/journals/international-organization": "International Organization",
        "https://www.tandfonline.com/journals/rrip20": "Taylor & Francis",
        "https://direct.mit.edu/isec": "MIT Press",
        "https://www.aeaweb.org/journals/aer": "AEA",
        "https://onlinelibrary.wiley.com/journal/10970266": "Wiley",
        "https://www.jstor.org/journal/admisciequar": "JSTOR",
        "https://www.piie.com/": "PIIE",
        "https://www.journals.uchicago.edu/journals/jpe": "UChicago Press",
        "https://www.atlanticcouncil.org/programs/geoeconomics-center/": "Atlantic Council",
        "https://www.brookings.edu/artificial-intelligence/": "Brookings",
    }
    failed = []
    for url, label in report_urls.items():
        rule = get_compliance_rule(url)
        if rule.get("allow_scrape") is not False:
            failed.append(f"{label}: allow_scrape={rule.get('allow_scrape')}")
            continue
        if rule.get("fulltext_scraping_allowed") is not False:
            failed.append(f"{label}: fulltext_scraping_allowed={rule.get('fulltext_scraping_allowed')}")
        if not rule.get("metadata_allowed_path"):
            failed.append(f"{label}: 缺 metadata_allowed_path")
        if not rule.get("fulltext_allowed_path"):
            failed.append(f"{label}: 缺 fulltext_allowed_path")
        if not rule.get("requires_permission"):
            failed.append(f"{label}: requires_permission 未标记")
    assert not failed, "ToS 报告域名规则不完整:\n" + "\n".join(f"  - {x}" for x in failed)

    all_blocked = high_risk_sources_records(active_only=False)
    all_sources = {row["source"] for row in all_blocked}
    assert "International Organization (Cambridge)" in all_sources, "全量合规台账缺 Cambridge"
    assert "JPE (Journal of Political Economy / UChicago Press)" in all_sources, "全量合规台账缺 JPE"
    active_sources = {row["source"] for row in high_risk_sources_records()}
    assert "International Organization (Cambridge)" not in active_sources, "默认运行清单不应混入非当前 THINK_TANKS 来源"
    print(f"  [OK] ToS 报告禁止/需审批域名已落入合规规则（全量 {len(all_blocked)} 条，默认仅当前源）")


def test_filtered_out_notice_for_ai_summary():
    """filtered_out.csv 对应记录应能进入 AI 简报末尾复核清单。"""
    rows = [
        {
            "title": "OIES Podcast – China after the Iran crisis: change or continuity?",
            "url": "https://www.oxfordenergy.org/publications/china-after-the-iran-crisis-change-or-continuity/",
            "source": "Oxford Institute for Energy Studies (OIES)",
            "filter_hit": "podcast",
        }
    ]
    notice = filtered_out_notice(rows, section_no=4)
    assert "## 四、关键词硬过滤复核清单" in notice
    assert "OIES Podcast" in notice
    assert "podcast" in notice
    assert "[查看](https://www.oxfordenergy.org/publications/china-after-the-iran-crisis-change-or-continuity/)" in notice
    print("  [OK] filtered_out.csv 可写入 AI 简报复核清单")


def test_fetch_blocking_diagnostics_classify_challenges():
    """阻断诊断只用于记录原因，不改变合规边界或尝试绕过核验。"""
    assert _detect_blocking_reason("<title>Just a moment...</title><script>cf-chl</script>") == "cloudflare_challenge"
    assert _detect_blocking_reason("<div class='cf-turnstile'></div>") == "turnstile_challenge"
    assert _detect_blocking_reason("<div class='g-recaptcha'></div>") == "captcha_challenge"
    assert _detect_blocking_reason("<html><body>Normal policy brief</body></html>") is None
    assert _classify_fetch_exception(requests.exceptions.ConnectTimeout("connect timeout")) == "timeout"
    assert _classify_fetch_exception(requests.exceptions.HTTPError("403 Client Error: Forbidden")) == "http_403"
    print("  [OK] 抓取阻断诊断可识别 Cloudflare/Turnstile/CAPTCHA/timeout")


# ─────────────────────────────────────────────────────────────────────────────
# 主运行入口
# ─────────────────────────────────────────────────────────────────────────────

TESTS = [
    test_keywords_yaml_loaded,
    test_strong_keywords_contain_rescue_words,
    test_red_titles_filtered,
    test_green_not_filtered,
    test_yellow_demoted,
    test_mad_doctrine_rescued,
    test_1979_revolution_rescued,
    test_green_demoted_still_rescued,
    test_pan_mena_event_announcement_hard_filtered,
    test_career_center_policy_study_not_hard_filtered,
    test_core_gcc_recent_noise_hard_filtered,
    test_core_gcc_auto_pass_does_not_force_strong_relevance,
    test_vehicle_technology_case_study_demoted_to_medium,
    test_core_gcc_title_strong_signal_promoted_even_when_content_type_unknown,
    test_count_badge_category_title_filtered,
    test_pan_mena_deep_topic_strong_titles_promoted,
    test_deep_topic_auto_pass_does_not_force_strong_relevance,
    test_arab_reform_title_date_cleanup,
    test_mei_link_scan_fallback_extracts_articles,
    test_rss_candidate_uses_url_exclusion_rules,
    test_atlantic_expert_media_mentions_hard_filtered,
    test_chatham_north_sea_oil_news_hard_filtered,
    test_same_source_duplicate_titles_keep_latest,
    test_western_source_urls_updated,
    test_blocked_sources_manual_and_rss_discovery_config,
    test_compliance_rules_cover_all_think_tanks,
    test_high_risk_sources_records_for_dry_run_export,
    test_tos_report_blocked_domains_have_alternative_paths,
    test_filtered_out_notice_for_ai_summary,
    test_fetch_blocking_diagnostics_classify_challenges,
]

if __name__ == "__main__":
    print("=" * 60)
    print("v2.4.1 关键词漏斗回归测试")
    print("=" * 60)
    passed = failed_tests = 0
    for test_fn in TESTS:
        print(f"\n{test_fn.__name__}")
        try:
            test_fn()
            passed += 1
        except AssertionError as e:
            print(f"  [FAIL] {e}")
            failed_tests += 1
        except Exception as e:
            print(f"  [ERROR] {type(e).__name__}: {e}")
            failed_tests += 1
    print("\n" + "=" * 60)
    print(f"结果：{passed} 通过 / {failed_tests} 失败 / {len(TESTS)} 总计")
    if failed_tests:
        print("⚠️  有测试失败，请检查上方错误信息")
        sys.exit(1)
    else:
        print("全部通过")
    print("=" * 60)
