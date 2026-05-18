# pan_mena 12 个智库命中质量评估报告

评估日期：2026-05-13  
评估对象：`THINK_TANKS` 中 `tier == "pan_mena"` 的 12 个来源  
评估目标：观察泛 MENA 来源文章命中质量是否稳定，检查强相关占比是否落在 10%~30% 预期区间，并判断是否需要调整 `RELEVANCE_THRESHOLD` 或 `keywords.yaml`。

## 1. 评估口径

本次使用两套口径：

1. **生产口径**
   - `filter_undated=True`
   - `max_age_days=30`
   - `max_per_tank=20`
   - `dedup_db=None`
   - 不启用 AI API，仅评估脚本内 `topic_relevance_score`

2. **来源质量观察口径**
   - `filter_undated=False`
   - `max_age_days=0`
   - `max_per_tank=20`
   - `dedup_db=None`
   - 目的不是模拟日报产出，而是观察 pan_mena 来源通过漏斗后的真实候选池质量

强相关判定沿用当前项目约定：

- 强相关：`topic_relevance_score >= 4.0`
- 中等相关：`topic_relevance_score < 4.0`

## 2. 覆盖来源

本次确认 `pan_mena` 共 12 个来源：

| 来源 | region | 国家 |
|---|---|---|
| Carnegie Middle East Center | mena | Lebanon |
| Al-Ahram Center for Political and Strategic Studies | mena | Egypt |
| Al Sharq Forum | mena | Turkey |
| Arab Reform Initiative | mena | France |
| Middle East Institute (MEI) | western | USA |
| Center for Strategic and International Studies (CSIS) | western | USA |
| Atlantic Council — Middle East Programs | western | USA |
| Chatham House — Gulf States | western | UK |
| Oxford Institute for Energy Studies (OIES) | western | UK |
| Baker Institute for Public Policy (Rice University) | western | USA |
| Wilson Center — Middle East Program | western | USA |
| International Institute for Strategic Studies (IISS) | western | UK |

## 3. 生产口径结果

生产口径最终仅保留 1 篇文章：

| 指标 | 数值 |
|---|---:|
| 最终文章数 | 1 |
| 强相关文章数 | 1 |
| 强相关占比 | 100.0% |
| 来源 | Atlantic Council |
| 文章 | The new playbook for AI leadership: The case of the United Arab Emirates |

结论：生产口径样本太小，不能直接用 100% 强相关占比判断阈值过宽。实际问题是多数 pan_mena 来源在本轮抓取中要么无近期日期，要么被站点 403/404/RSS 问题阻断。

## 4. 来源质量观察口径结果

不做时效和无日期过滤后，候选池为 52 篇。

| 指标 | 数值 |
|---|---:|
| 候选文章数 | 52 |
| 强相关文章数 | 2 |
| 强相关占比 | 3.8% |
| 有日期文章数 | 10 |
| 有日期强相关文章数 | 1 |
| 有日期强相关占比 | 10.0% |
| 硬过滤文章数 | 1 |

评分分布：

| `topic_relevance_score` | 篇数 |
|---:|---:|
| 4.5 | 1 |
| 4.0 | 1 |
| 2.5 | 50 |

内容类型分布：

| `content_type` | 篇数 |
|---|---:|
| high | 2 |
| unknown | 50 |

来源分布：

| 来源 | 候选数 | 强相关 | 强相关占比 | 有日期数 |
|---|---:|---:|---:|---:|
| Carnegie Middle East Center | 20 | 0 | 0.0% | 0 |
| Arab Reform Initiative | 20 | 1 | 5.0% | 0 |
| Al Sharq Forum | 9 | 0 | 0.0% | 9 |
| Al-Ahram Center for Political and Strategic Studies | 2 | 0 | 0.0% | 0 |
| Atlantic Council — Middle East Programs | 1 | 1 | 100.0% | 1 |

## 5. 质量观察

### 5.1 强相关占比偏低的主因不是阈值

全量观察口径下强相关占比为 3.8%，低于 10%~30% 预期。但有日期样本的强相关占比为 10.0%，刚好落在预期下沿。

偏低的主要原因是评分机制而不是 `RELEVANCE_THRESHOLD`：

- `deep_topic` 来源当前直接使用 `keyword_score=5.0` 保底通过。
- 这会绕过标题真实关键词得分。
- 因此 Carnegie、Al Sharq、Arab Reform 中明显包含 `Hormuz`、`Gulf Cooperation Council`、`Arab Gulf`、`Regional Bloc` 等强信号的标题仍被压在 2.5 分。

典型例子：

- `What Does the Strait of Hormuz’s Closure Mean?`
- `Can the Gulf Cooperation Council Transcend Its Divisions?`
- `Europe and the Arab Gulf Must Come Together`
- `STEP and the Possibility of a New Regional Bloc in the Middle East`

这些标题不应因为来源为 `deep_topic` 而丢失标题强信号。

### 5.2 外置硬过滤词存在执行顺序问题

发现一篇应被硬过滤的文章漏入：

- `AL SHARQ STRATEGIC RESEARCH INTERNSHIP PROGRAM ANNOUNCEMENT`

`keywords.yaml` 已包含 `internship program` 和 `program announcement`，但代码先命中 `LOW_VALUE_PATTERNS` 中的 `announcement` 并返回 `low`，导致外置硬过滤词没有机会执行。

处理建议：硬过滤词应优先于 high/medium/low 内容类型判断。

### 5.3 Arab Reform Initiative 日期与标题抽取质量较差

Arab Reform 的多个候选标题混入作者、栏目、发布日期和标签，例如：

`Paused, Not Resolved:The Saudi-UAE Rivalry and the War in Sudan—...13 May 2026#Conflicts#Saudi Arabia...`

影响：

- 生产口径下这些文章被视为无日期，随后被 `filter_undated` 剔除。
- 标题展示质量下降。
- 日期本来存在于文本中，但没有被抽取到 `date` 字段。

处理建议：在 HTML 卡片日期选择器失败时，允许从标题文本兜底抽取日期；同时对标题中 `—`、`#tag`、`&nbsp` 等元数据做轻量清理。

### 5.4 部分 western 来源存在抓取可达性问题

本轮观察到：

- MEI、Chatham House、Baker、IISS 多个页面返回 403。
- OIES 的两个配置路径返回 404。
- Wilson Center 的 publications 路径返回 404。
- CSIS 主 program 页 403，`/analysis` 可抓但本轮无保留。

这些问题会影响 pan_mena 来源覆盖率，但不应通过降低阈值来补偿。

### 5.5 Carnegie metadata 验证受 403 影响

Carnegie 列表页可通过 Playwright 抓到候选，但文章详情页 metadata 验证请求返回 403。当前逻辑对验证失败采取保守保留，因此 Carnegie 候选池中会保留一部分偏泛中东/伊朗战争文章。

处理建议：本轮先不把 Carnegie 403 作为关键词或阈值问题处理；后续可考虑让 `verify_carnegie_metadata()` 复用 Playwright 或跳过 requests 详情页验证。

## 6. 优化建议

本次建议优先做三项低风险优化：

1. **修正硬过滤执行顺序**
   - 外置 `hard_filter_words` 应在 high/medium/low 内容类型判断之前执行。
   - 目的：确保 `internship program announcement` 等明确噪音被剔除。

2. **deep_topic 保底但不遮蔽真实关键词得分**
   - 当前：`deep_topic` 直接 `keyword_score=5.0`。
   - 建议：先计算真实关键词得分，再取 `max(5.0, actual_score)`。
   - 目的：让强信号标题自然进入强相关档，而不是统一停在 2.5。

3. **补充少量强信号词**
   - 建议补充到 `STRONG_KEYWORDS`：
     - `gulf states`
     - `arab gulf`
     - `iran-gulf`
     - `u.s.-gulf`
     - `us-gulf`
     - `regional bloc`
     - `axis of resistance`
     - `regional integration`
     - `energy security`
     - `hormuz crisis`
     - `hormuz disruption`
     - `chokepoint`
   - 这些词已在 `keywords.yaml` 的 `strong_signal_supplement` 中有对应依据或与既有绿色样本一致。

暂不建议：

- 不建议调整 `RELEVANCE_THRESHOLD=3`。本轮问题不是入口阈值过高或过低，而是强信号没有在 `deep_topic` 场景下进入评分。
- 不建议扩大硬过滤词。除 internship 漏网外，本轮没有发现大量需要硬删的新增噪音。
- 不建议把 pan_mena 整体改为 core_gcc 式自动高分。泛 MENA 来源确实包含不少偏泛中东、历史旧文和地区外议题，需要保持中等相关缓冲层。

## 7. 验证要求

优化后至少运行：

```bash
python3 scripts/test_keywords_funnel.py
```

并验证：

- `AL SHARQ STRATEGIC RESEARCH INTERNSHIP PROGRAM ANNOUNCEMENT` 返回 `excluded`。
- `deep_topic` 标题含 `Hormuz` / `Gulf Cooperation Council` / `regional bloc` 时，`keyword_score` 高于保底 5。
- pan_mena 有日期候选的强相关占比维持在 10%~30% 区间附近。

## 8. 已实施优化与复验结果

本次已实施以下优化：

1. **硬过滤优先执行**
   - 将外置 `hard_filter_words` 判断提前到 high/medium/low 内容类型判断之前。
   - 复验：`AL SHARQ STRATEGIC RESEARCH INTERNSHIP PROGRAM ANNOUNCEMENT` 返回 `('excluded', 'excluded')`。

2. **deep_topic 保底但不遮蔽真实关键词得分**
   - 原逻辑：`deep_topic` 直接使用 `keyword_score=5.0`。
   - 新逻辑：先计算真实关键词得分，再取 `max(5.0, actual_score)`。
   - 额外约束：只有 `deep_topic` 且命中 `STRONG_KEYWORDS` 的文章，才将 `topic_relevance_score` 保底抬到 4.0；单纯命中国家名不会被误抬高。

3. **补充强信号词**
   - 新增：`gulf states`、`arab gulf`、`iran-gulf`、`u.s.-gulf`、`us-gulf`、`regional bloc`、`axis of resistance`、`regional integration`、`energy security`、`hormuz crisis`、`hormuz disruption`、`chokepoint`。
   - 目的：覆盖 4-29 绿色样本与本轮 pan_mena 中明显强相关但此前停留在 2.5 分的标题。

4. **标题和日期轻量清理**
   - 增加 `_clean_article_title()`，清理卡片标题中混入的作者、栏目、日期、标签等元数据。
   - 增强 `normalize_date()`，支持 `Commentary13 May 2026`、`Book24 May 2022` 这类字母和日期粘连的格式。
   - 复验：Arab Reform 的 `Paused, Not Resolved...13 May 2026...` 可抽取为 `2026-05-13`，标题清理为 `Paused, Not Resolved:The Saudi-UAE Rivalry and the War in Sudan`。

复验结果：

| 口径 | 候选数 | 强相关 | 强相关占比 | 备注 |
|---|---:|---:|---:|---|
| 来源质量观察口径 | 53 | 14 | 26.4% | 落在 10%~30% 预期区间 |
| 来源质量观察口径（有日期） | 31 | 6 | 19.4% | 落在 10%~30% 预期区间 |
| 生产口径 | 3 | 1 | 33.3% | 样本仍小，主要用于确认日期修复后近期文章可进入输出 |

优化后强相关样例：

- `What Does the Strait of Hormuz’s Closure Mean?`
- `Can the Gulf Cooperation Council Transcend Its Divisions?`
- `STEP and the Possibility of a New Regional Bloc in the Middle East`
- `Iraq’s Fatal Dilemma: Axis of Resistance or Regional Integration?`
- `The Gulf States and Israel after the Abraham Accords`

最终判断：

- 暂不调整 `RELEVANCE_THRESHOLD=3`。
- 暂不继续扩大 `hard_filter_words`。
- 后续优先处理 Carnegie metadata 详情页 403 和若干 western 来源 403/404 的抓取可达性问题。

## 9. 2026-05-14 继续优化记录

本轮继续处理四类遗留项：

1. **合规规则补齐并接入运行时**
   - `compliance_rules.yaml` 已覆盖当前 29 个 `THINK_TANKS` 域名。
   - CSV 命中的 Brookings、Atlantic Council、IISS 默认 `allow_scrape=false`，运行时自动跳过；如需人工覆盖使用 `--include-high-risk`。
   - CSV 未覆盖的 core_gcc、MEI、CSIS、OIES、Baker 等来源先以 `manual_domain_inventory` 标记，保留后续 robots/ToS 人工复核入口。

2. **Carnegie metadata 403 处理**
   - `verify_carnegie_metadata()` 在 requests 失败时可复用当前 Playwright browser 抓详情页 HTML。
   - Playwright 等待策略从 `networkidle` 改为 `domcontentloaded`，避免长连接页面导致 20s 超时。

3. **western 来源 URL 与抓取策略**
   - MEI：当前有效页面为 `https://mei.edu/regions/gulf/`；本地 requests 仍 403，Playwright 不再超时但候选仍为 0，需后续专项处理站点渲染/反爬返回内容。
   - CSIS：新增 `/regions/middle-east/gulf`；requests 对 region/program 页仍 403，但 `/analysis` 可抓到候选。
   - Chatham：修正路径为 `/regions/middle-east-and-north-africa/gulf-states`，并标记 `use_playwright`；requests 仍 403。
   - OIES：旧 research 子路径疑似 404，改为 `/publications/` + `/research/` + RSS。
   - Baker：当前中心页为 `/center-for-energy-studies` 与 `/ces`；移除会跳转 403 的 `/research`。
   - Wilson：移除 404 的 `/program/middle-east-program/publications`，改用 `/collection/middle-east-program-research`、`/publication-series/MEP-policy-briefs`、`/collection/mena360`。
   - AGSIW：移除会 404 的 `/topic/economics-and-energy/`、`/topic/security-and-defense/`。

4. **新增回归测试**
   - `scripts/test_keywords_funnel.py` 新增 pan_mena 样本：公告硬过滤、deep_topic 强信号抬分、Arab Reform 标题/日期清理、MEI 普通链接结构兜底抽取、western 旧 URL 防回退、合规规则覆盖。
   - 最新结果：`14 通过 / 0 失败 / 14 总计`。

实抓复验：

```bash
python3 gcc_thinktank_scraper_v2.py \
  --dry-run-keywords --no-dedup \
  --countries USA --max-per-tank 1 \
  --days 0 --keep-undated \
  --output-dir /private/tmp/gcc_usa_check3
```

结果：AGSIW、CSIS、Baker、Wilson 有候选输出；Atlantic 按合规跳过；MEI 仍 0 候选。
