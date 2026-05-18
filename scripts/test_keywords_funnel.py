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
    _KW,
    STRONG_KEYWORDS,
    RELEVANCE_THRESHOLD,
    Article,
    THINK_TANKS,
    get_compliance_rule,
    normalize_date,
    _clean_article_title,
    _is_likely_article,
    extract_articles_from_page,
)

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
    title_lower = article.title.lower()
    text_demote = title_lower
    if _KW["demote_check_summary"]:
        text_demote += " " + (article.snippet or "").lower()
    hits = [w for w in _KW["demote_set"] if w in text_demote]
    hits += [w for w in _KW.get("title_only_demote_set", set()) if w in title_lower]
    if hits:
        ks += _KW["max_penalty"]
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
        "Derasat Center participates in the Joint Regional Initiative“Bridging Stability: EU-GCC Cooperation in an Era of Fragmentation”",
    ]
    failed = []
    for title in titles:
        if not is_hard_filtered(make_test_article(title)):
            failed.append(title)
    assert not failed, "以下 core_gcc 噪音样本未被硬过滤:\n" + "\n".join(f"  - {t}" for t in failed)
    print(f"  [OK] {len(titles)} 条 core_gcc 近期噪音样本被硬过滤")


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
    test_count_badge_category_title_filtered,
    test_pan_mena_deep_topic_strong_titles_promoted,
    test_arab_reform_title_date_cleanup,
    test_mei_link_scan_fallback_extracts_articles,
    test_western_source_urls_updated,
    test_compliance_rules_cover_all_think_tanks,
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
