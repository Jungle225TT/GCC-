#!/usr/bin/env python3
"""
GCC智库抓取系统 — 评分阈值对比测试
在同一批测试数据上对比不同阈值（1-6分）的保留/排除效果

用法：
  python scoring_test.py                          # 用内置测试集
  python scoring_test.py --json output/xxx.json   # 用实际抓取数据
"""
import re, json
from pathlib import Path

STRONG_KEYWORDS=["gcc","gulf cooperation council"]
COUNTRY_KEYWORDS=["saudi arabia","saudi","ksa","uae","united arab emirates","emirates","qatar","qatari","kuwait","kuwaiti","bahrain","bahraini","oman","omani","riyadh","jeddah","dubai","abu dhabi","doha","muscat","manama"]
WEAK_KEYWORDS=["gulf","middle east","mena","arabian peninsula"]

def compute_score(title,snippet=""):
    tl,sl=title.lower(),(snippet or"").lower()
    total,matched=0.0,[]
    for kws,bs in[(STRONG_KEYWORDS,3),(COUNTRY_KEYWORDS,2),(WEAK_KEYWORDS,1)]:
        for kw in kws:
            kl=kw.lower()
            if kl in tl:s=bs*2;total+=s;matched.append(f"{kw}(标题+{s})")
            elif kl in sl:total+=bs;matched.append(f"{kw}(正文+{bs})")
    return total,matched

# 测试集：15篇相关 + 13篇不相关 + 10篇边界
TEST_ARTICLES=[
    {"title":"GCC Summit 2026: Key Outcomes","snippet":"","exp":True},
    {"title":"Saudi Arabia's Vision 2030: Progress","snippet":"","exp":True},
    {"title":"UAE Digital Economy Strategy","snippet":"","exp":True},
    {"title":"Qatar's LNG Export Strategy","snippet":"","exp":True},
    {"title":"Bahrain Economic Diversification","snippet":"","exp":True},
    {"title":"Kuwait Political Reform Debate","snippet":"","exp":True},
    {"title":"Oman Fiscal Policy Under Low Oil Prices","snippet":"","exp":True},
    {"title":"The Riyadh Summit Impact on Arab Unity","snippet":"","exp":True},
    {"title":"Dubai Real Estate Market 2026","snippet":"","exp":True},
    {"title":"Doha Forum: Regional Security","snippet":"","exp":True},
    {"title":"Gulf Cooperation Council Trade Integration","snippet":"","exp":True},
    {"title":"Iran Nuclear Deal","snippet":"Implications for Saudi Arabia and UAE","exp":True},
    {"title":"Oil Market Volatility","snippet":"Impact on GCC fiscal policies","exp":True},
    {"title":"Water Scarcity","snippet":"Oman and Bahrain desalination projects","exp":True},
    {"title":"US Military Presence","snippet":"Bases in Qatar, Bahrain, Kuwait","exp":True},
    {"title":"Egypt Constitutional Reform","snippet":"","exp":False},
    {"title":"Turkey Inflation Crisis","snippet":"","exp":False},
    {"title":"Lebanon Banking Collapse","snippet":"","exp":False},
    {"title":"Morocco Renewable Energy","snippet":"","exp":False},
    {"title":"Libya Peace Process Stalls","snippet":"","exp":False},
    {"title":"Tunisia Democratic Backsliding","snippet":"","exp":False},
    {"title":"Iraq Oil Production Targets","snippet":"","exp":False},
    {"title":"Jordan Water Crisis","snippet":"","exp":False},
    {"title":"Climate Change in North Africa","snippet":"","exp":False},
    {"title":"Gulf of Mexico Oil Spill","snippet":"","exp":False},
    {"title":"European Energy Security","snippet":"","exp":False},
    {"title":"China Belt and Road Central Asia","snippet":"","exp":False},
    {"title":"Nuclear Energy in Europe","snippet":"","exp":False},
    {"title":"Middle East Security Architecture","snippet":"","exp":"边界"},
    {"title":"MENA Economic Outlook 2026","snippet":"","exp":"边界"},
    {"title":"Gulf Energy Transition","snippet":"","exp":"边界"},
    {"title":"Iran Regional Influence","snippet":"Relations with Gulf states","exp":"边界"},
    {"title":"Oil Price Forecast","snippet":"OPEC+ production decisions","exp":"边界"},
    {"title":"Islamic Finance Trends","snippet":"Growth in Gulf region","exp":"边界"},
    {"title":"Middle East Startups","snippet":"Dubai and Riyadh as tech hubs","exp":"边界"},
    {"title":"US Middle East Policy","snippet":"Arms sales to Gulf allies","exp":"边界"},
    {"title":"Arab Youth Survey","snippet":"Saudi Arabia, UAE, Egypt","exp":"边界"},
    {"title":"Palestine Normalization","snippet":"Abraham Accords signatories","exp":"边界"},
]

def run_comparison():
    scored=[]
    for a in TEST_ARTICLES:
        sc,mt=compute_score(a["title"],a.get("snippet",""))
        scored.append({**a,"score":sc,"matched":mt})

    rel=[a for a in scored if a["exp"] is True]
    unr=[a for a in scored if a["exp"] is False]
    bor=[a for a in scored if a["exp"]=="边界"]

    print("="*85)
    print("📊 GCC智库评分阈值对比测试")
    print(f"   测试集: {len(rel)} 篇相关 | {len(unr)} 篇不相关 | {len(bor)} 篇边界")
    print("="*85)
    print()
    print(f"{'阈值':>4} │{'相关保留':>9} │{'相关漏抓':>9} │{'误留不相关':>11} │{'正确排除':>9} │{'边界保留':>9} │{'准确率':>7} │ 评价")
    print("─"*95)

    for th in [1,2,3,4,5,6]:
        rk=sum(1 for a in rel if a["score"]>=th)
        rm=len(rel)-rk
        uk=sum(1 for a in unr if a["score"]>=th)
        ue=len(unr)-uk
        bk=sum(1 for a in bor if a["score"]>=th)
        tot=len(rel)+len(unr)
        acc=(rk+ue)/tot*100
        pre=rk/(rk+uk) if(rk+uk)>0 else 0
        rec=rk/len(rel) if rel else 0
        f1=2*pre*rec/(pre+rec) if(pre+rec)>0 else 0

        if acc>=95 and rm<=1: rating="⭐最优"
        elif acc>=90: rating="✅良好"
        elif acc>=80: rating="⚠️一般"
        else: rating="❌差"
        cur=" ◀当前" if th==3 else ""
        print(f"  ≥{th} │ {rk:>5}/{len(rel)} │ {rm:>5}/{len(rel)} │  {uk:>5}/{len(unr)}  │ {ue:>5}/{len(unr)} │ {bk:>5}/{len(bor)} │ {acc:>5.1f}% │ {rating}{cur}")

    print("─"*95)

    # 详细评分
    print(f"\n{'='*85}")
    print("📋 逐篇评分详情")
    print(f"{'='*85}")
    for label,arts in[("✅ 相关",rel),("❌ 不相关",unr),("⚠️ 边界",bor)]:
        print(f"\n── {label} ({len(arts)}篇) ──")
        for a in sorted(arts,key=lambda x:-x["score"]):
            t3="✅" if a["score"]>=3 else "❌"
            ms=", ".join(a["matched"][:3]) if a["matched"] else "无匹配"
            print(f"  {t3} [{a['score']:>4.0f}分] {a['title'][:50]:<51} {ms}")

    # 结论
    r3=sum(1 for a in rel if a["score"]>=3)
    u3=sum(1 for a in unr if a["score"]<3)
    b3=sum(1 for a in bor if a["score"]>=3)
    print(f"""
{'='*85}
📝 结论
{'='*85}
  阈值≥3（当前）: 相关{r3}/{len(rel)}保留, 不相关{u3}/{len(unr)}排除, 边界{b3}/{len(bor)}保留

  ≥2 → 多保留边界文章，但Gulf of Mexico等会误入（不推荐）
  ≥3 → 平衡精度与召回，Gulf/Middle East/MENA单独出现不够分（推荐）
  ≥4 → 更严格，正文仅提到一个国名的文章会被排除（适合精读场景）
  ≥5 → 过严，需标题和正文同时命中才够分（不推荐日常使用）
""")

def analyze_json(path):
    with open(path,encoding="utf-8") as f: data=json.load(f)
    arts=data.get("articles",[])
    core=[a for a in arts if a.get("source_tier")=="core_gcc"]
    pan=[a for a in arts if a.get("source_tier")=="pan_mena"]
    print(f"\n{'='*85}")
    print(f"📊 实际数据分析: {path}")
    print(f"  核心GCC: {len(core)}篇（auto-pass,不受阈值影响）")
    print(f"  泛MENA: {len(pan)}篇（受阈值影响）")
    if pan:
        print(f"\n  泛MENA已保留文章:")
        for a in pan:
            print(f"    [{a.get('keyword_score',0):.0f}分] {a['title'][:70]}")
    from collections import Counter
    print(f"\n  各智库文章数:")
    for src,cnt in Counter(a["source"] for a in arts).most_common():
        print(f"    {cnt:>5}篇  {src}")

if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser(description="评分阈值对比测试")
    p.add_argument("--json",default=None,help="实际JSON数据")
    a=p.parse_args()
    run_comparison()
    if a.json: analyze_json(a.json)
    else:
        js=sorted(Path("./output").glob("gcc_research_*.json"),reverse=True) if Path("./output").exists() else []
        if js: print(f"\n🔍 自动找到: {js[0]}"); analyze_json(str(js[0]))
