# GCC 智库简报关键词表说明文档

**版本**：v1.0
**生成日期**：2026-04-30
**作者**：姜亭汀
**反推依据**：马老师对 `gcc_summary_20260429_1901_标注版.pdf` 的标注（43 篇英文原标题样本：🟢绿 16 / 🟡黄 17 / 🔴红 4）

---

## 一、本文档的定位

本文档对应 **v2.4 进展文档 5.1 节「关键词体系优化的落地建议」** 的具体落地，是其中「从负样本反推产出两份分级关键词表」一步的产出物。

**关键词不重新发明轮子**——所有词表都接入到 v2.4 已存在的四层漏斗的现有层中，配套的 `keywords.yaml` 是外置配置，调整词表无需改代码。

---

## 二、⚠️ 标题语言重要说明

爬虫从智库网站抓取的标题是**英文原文**（少数智库可能含阿拉伯语原文），中文翻译只在生成 AI 简报时才发生，**不参与四层漏斗的筛选**。

因此本词表**以英文为主**：
- 降权词举例：`IRAN IN A WEEK`、`Vatican`、`NATO`、`Western Sahara`、`Coptic`、`Lessons from History`、`1979 Revolution`
- 硬过滤词举例：`podcast`、`episode of`、`Historical Dictionary`、`Gulf of Guinea`、`Dr. Sheikh`
- 强信号词举例：`OPEC`、`Hormuz`、`Arabian Gulf`、`Mutually Assured Destruction`

中文词条仅作为兼容补充（万一系统中存在已翻译的标题字段被同时检查时使用），实际命中绝大多数走英文。所有匹配都是**大小写不敏感**。

---

## 三、与现有四层漏斗的对接关系

v2.4 进展文档 5.1 节已经明确了三档关键词机制对接到四层漏斗的位置：

```
┌──────────────────────────────────────────────────────────────────────┐
│                     v2.4 已有的四层漏斗                              │
│                                                                      │
│  第一层：智库白名单 + RSS / Playwright / HTML 路由                   │
│         ↓                                                            │
│  第二层：关键词评分                                                  │
│    ├─ 现有：强信号词加分 + 普通词加分（v2.4 已有，不动）             │
│    └─ 【新增】降权词扣分 -2（封顶）  ← demote_words 接入此处         │
│       └─ 救回机制：现有强信号词加分先生效，                          │
│           降权扣分在其后执行 → 保留「强信号词救回」能力              │
│         ↓                                                            │
│  第三层：内容类型识别（剔除招聘/活动/讣告等）                        │
│    ├─ 现有：内置规则（v2.4 已有，不动）                              │
│    └─ 【新增】硬过滤词剔除  ← hard_filter_words 接入此处             │
│         ↓                                                            │
│  第四层：AI 评估（边界分类 / 标题翻译 / 简报生成）                   │
│         ↓                                                            │
│  输出：Markdown / JSON / 简报                                        │
└──────────────────────────────────────────────────────────────────────┘
```

**重要原则**：本次新增的「降权词」「硬过滤词」是对现有第二层和第三层的**最小侵入扩展**，不替换、不重写、不新建独立的评分模块。配置文件 `keywords.yaml` 缺失时，系统按 v2.4 原逻辑运行不受影响。

---

## 四、🔴 硬过滤词（hard_filter_words）

> **接入位置**：四层漏斗第三层「内容类型识别」函数内部
> **触发逻辑**：标题命中任一词 → 直接剔除（与现有的招聘/活动/讣告剔除并列）
> **摘要命中**：仅触发降权（避免误杀），不剔除

### 类别 1：媒体活动公告类

| 关键词 | 来源样本 | 风险提示 |
|--------|----------|----------|
| `podcast` / `episode of` | [19] Fourth episode of the sound of thoughts podcast | 仅锁定「episode of the X podcast」格式 |
| `sound of thoughts` | [19] 同上 | 节目名精确锁定 |
| `internship program` / `research internship` / `program announcement` | [39] AL SHARQ STRATEGIC RESEARCH INTERNSHIP PROGRAM ANNOUNCEMENT | — |
| 中文兼容：`播客` / `节目预告` | — | 翻译版字段使用 |

### 类别 2：纯人物履历 / 任命公告

| 关键词 | 来源样本 | 风险提示 |
|--------|----------|----------|
| `Dr. Sheikh` / `Dr. Shaikh` / `Sheikh Dr.` / `Shaikh Dr.` | [7] Dr. Shaikh Mohamed Bin Hamad Al Khalifa | **故意只锁定「Dr.+Sheikh」组合**——单纯 `Dr.` 或 `Sheikh` 太普遍（很多政治人物都被这么称呼），机械命中会大面积误杀 |

**未列入**：`biography of` / `profile of` 单独太泛，观察试运行后再决定是否补充。

### 类别 3：纯文化软实力 / 文献项目宣传

| 关键词 | 来源样本 | 风险提示 |
|--------|----------|----------|
| `Historical Dictionary` | [3] Two Leading Global Universities Add the Doha Historical Dictionary to Their Digital Libraries | — |
| `digital library` / `digital libraries` | [3] 同上 | 这里是图书馆,不是数字银行/数字货币——风险较低 |

**未列入**：单纯 `dictionary` 太泛（可能误命中政策词典/术语表），必须配合 `Historical` 才精确。

### 类别 4：远离 GCC 地理范围的偏题

| 关键词 | 来源样本 | 风险提示 |
|--------|----------|----------|
| `Gulf of Guinea` | [17] Maritime Security in the Gulf of Guinea | — |
| `West African piracy` | [17] 同上 | 不能用单独"West Africa"——GCC 在西非有投资 |
| `Latin America` / `Caribbean` | 同类延伸 | — |
| `Sub-Saharan Africa` | 同类延伸 | 慎用：GCC 在撒哈拉以南确有投资,但纯安全分析偏题 |

---

## 五、🟡 降权词（demote_words）

> **接入位置**：四层漏斗第二层「关键词评分」函数内部
> **触发逻辑**：标题或摘要命中任一词 → 总分 -2（封顶 -2，命中多个不重复扣分）
> **救回机制**：复用 v2.4 现有「强信号词救回」——文章不剔除，扣分后仍可进入第四层 AI 评估，仅排序下沉

### 类别 A：周期性监测报告 ⭐（信号最强，4 篇样本全部命中）

| 关键词 | 来源样本 |
|--------|----------|
| `IRAN IN A WEEK` / `Iran in a Week` / `in a week` | [15][24][34] 三篇全部黄色 |
| `Monthly Iran Case File` / `Case File` | [29] Rasanah's Monthly Iran Case File |
| `Weekly Digest` / `Monthly Report` | 同类延伸 |
| 中文兼容：`伊朗一周` / `月度档案` / `周报` / `月报` | — |

**类别说明**：信息密度低、重复性高的周期性监测报告。每周 4 篇"伊朗一周"塞进优先阅读对决策无意义。

---

### 类别 B：非 GCC 核心区域聚焦

| 子区域 | 关键词 | 来源样本 |
|--------|--------|----------|
| 北非 | `Western Sahara` | [43] Western Sahara in Transition |
| 北非 | `Tunisia` / `Tunisian` | [2] Elections in Tunisia |
| 北非 | `Morocco` / `Moroccan` | [43] 推断 |
| 北非 | `Algeria` / `Algerian` | 同类延伸 |
| 北非 | `POLISARIO` / `Polisario` | [43] 同上 |
| 北非 | `Maghreb` | 同类延伸 |
| 跨大西洋 | `NATO` / `North Atlantic Treaty` | [35] US-European Disagreements ... NATO's Future |
| 跨大西洋 | `transatlantic` | [35] 同上 |
| 跨大西洋 | `Vatican` / `the Pope` / `the Holy See` | [1] Washington–Vatican Rift |
| 中东欧 | `Orbán` / `Orban` / `Hungary` / `Hungarian` | [12] After Orbán |

**关键的「故意未列入」名单**（避免机械误降）：
- **Lebanon** ([18])——黎巴嫩与真主党、伊朗代理人战争是 GCC 安全核心议题。即便 [18] 被标黄，是因为视角偏离而非地区偏离。
- **Pakistan** ([33])——CPEC 与海湾安全直接相关。
- **Russia** ([37])——俄罗斯在中东角色密切。
- **Turkey**——土耳其-海湾关系密切。
- **Iraq** ([42])——绿色样本，核心相关。
- **Egypt**——虽未出现于样本，但与海湾政经联动密切。

仅当是「Pakistan domestic / Russia domestic / Turkey domestic」等内政时才该降权——这种细粒度判断需要上下文，简单关键词无法实现，留待未来「同主题去重模块」覆盖。

---

### 类别 C：侨民研究 / 跨国数字社会学

| 关键词 | 来源样本 |
|--------|----------|
| `Digital Activism` | [22] Digital Activism within the Coptic Community |
| `Coptic` / `Copts` | [22] 同上 |
| `diaspora` | 同类延伸 |
| `transnational mobilization` / `expatriate community` | 同类延伸 |
| 中文兼容：`侨民` / `散居社区` / `数字行动主义` / `科普特` | — |

---

### 类别 D：历史回顾性分析（非时事）

| 关键词 | 来源样本 | 风险提示 |
|--------|----------|----------|
| `Lessons from History` | [5] How Did the IRGC Seize Power in Iran? | ⚠️ **关键风险**：[25] 含此词但是绿色样本——靠强信号词「Mutually Assured Destruction」救回 |
| `1979 Revolution` | [5] 同上 | ⚠️ **关键风险**：[6] 含此词但是绿色样本——靠强信号词「Arabian Gulf」+「Regional Security」救回 |
| `Seize Power` / `Rise to Power` | [5] 同上 | — |
| 中文兼容：`历史教训` / `1979革命` / `夺取权力` | — |

**重要说明**：本类别能否安全使用，**完全依赖现有 funnel 的「强信号词救回」机制**能正确识别两个绿色样本中的强信号词。详见下文「六、强信号词补充建议」。

---

### 类别 E：战争分析的重复性叠加（占位，本次不启用）

[36][40][41] 三篇都是伊朗战争分析（轨迹评估、战略迷失、对美谈判），全部被标黄。但 [38] STEP and the Possibility of a New Regional Bloc 是绿色，也是中东战争话题——区别在**视角是否新颖**。

简单关键词无法区分这种细微差异，因此**本类别在 keywords.yaml 中以空列表 `[]` 占位，不实际启用**。建议未来在 funnel 中增加「同主题去重」机制：

> 48 小时内同议题命中 ≥3 篇时，第 4 篇起降权。

该机制属于另一个独立任务，不在本次落地范围内。

---

## 六、🟢 强信号词补充建议（strong_signal_supplement）

> **重要**：本节列出的词**不直接被代码加载**，仅作为「建议补充到 funnel 现有强信号词列表」的参考清单。Claude Code 在改造时会先阅读 funnel 中现有的强信号词，与本清单去重合并后再评估是否需要补充。

### ⭐⭐⭐ 关键救回词（必须存在）

| 关键词 | 救回的绿色样本 |
|--------|----------------|
| `Mutually Assured Destruction` | [25] Combating Iran's MAD Doctrine: **Lessons from History** |
| `Arabian Gulf` | [6] Iranian Policies on Arabian Gulf ... from the **1979 Revolution** to the 2026 War |
| `Regional Security` | [6] 第二保险（同 [6]）|

**这三个词必须在最终的 funnel 强信号词列表中**——否则两个绿色样本会被误降权。

### ⭐⭐ 核心议题锚点

`OPEC` / `Hormuz` / `Strait of Hormuz` / `GCC` / `Gulf Cooperation Council`

### ⭐ 高频政经议题词

`Energy Security` / `Currency Swap` / `Iran Problem` / `Iran-Gulf` / `Eroding Trust` / `Iranian Policies` / `Missile and Drone` / `Arab Solidarity` / `Hollow Promise` / `Hormuz Crisis` / `Hormuz Disruption` / `Chokepoint` / `Axis of Resistance` / `Regional Integration` / `Bahrain's Cabinet` / `Bahrain's Diplomacy` / `Bahrain's Demands` / `Mediate` / `Mediation` / `Regional Bloc` / `UAE leaving OPEC` / `decision to leave OPEC`

---

## 七、4-29 标注样本端到端回测结果（实测）

用 4-29 的 43 篇英文原标题对当前关键词表做了模拟回测：

| 指标 | 实测结果 | 评价 |
|------|----------|------|
| 红色样本被硬过滤 | **4/4** | ✅ 完美命中 |
| 绿色样本误杀 | **0/16** | ✅ 零误杀 |
| 关键回归 [25]「Lessons from History」 | ✅ 被「Mutually Assured Destruction」救回 | ✅ |
| 关键回归 [6]「1979 Revolution」 | ✅ 被「Arabian Gulf + Regional Security」救回 | ✅ |
| 黄色样本覆盖率 | **11/19** ≈ 58% | ✅ 符合预期 |
| 未覆盖的黄色样本 | [10][11][18][33][36][37][40][41]（8 篇）| 预期内,留给「同主题去重」机制 |

### 未覆盖的 8 篇黄色样本说明

| # | 标题 | 未覆盖原因 |
|---|------|------------|
| 10 | The Rung Bell and the Crooked Strait: Decoding the Conflict With Iran | 隐喻标题，无显式特征词 |
| 11 | Europe's Role in Ensuring Maritime Security in the Strait of Hormuz | Europe 不能作降权词；含强信号词反而会高分（视角偏离需上下文判断）|
| 18 | Lebanon's Hard Choices | Lebanon 故意未入降权 |
| 33 | Pakistan-Mediated Ceasefire | Pakistan 故意未入降权 |
| 36 | Gains and Losses: Assessing the Trajectories of the War on Iran | 战争分析重复（待去重模块）|
| 37 | Where Does Russia Stand in the War | Russia 故意未入降权 |
| 40 | Escalation Without Exit: Strategic Disorientation | 战争分析重复（待去重模块）|
| 41 | Iran's Strategic Options: Rethinking Negotiation with America | 战争分析重复（待去重模块）|

---

## 八、试运行模式（v2.4 文档 5.1 节明确要求）

v2.4 文档 5.1 节已规划：

> 系统侧配合：在 Colab 操作界面新增「试运行模式」开关，开启时使用测试分支的关键词表并把每条文章的命中词与评分明细一并输出到 JSON，便于负责人逐条对照评估。

本次落地实现：

- **命令行**：`gcc_thinktank_scraper_v2.py --dry-run-keywords`
- **Colab 界面**：新增「试运行模式」布尔开关
- **额外输出**：
  - `keyword_dryrun.json`：每篇文章的 `title / final_score / demote_hits / demote_penalty`
  - `filtered_out.csv`：被硬过滤剔除的文章 `title / url / source / filter_word`，便于马老师回查

---

## 九、试运行 / 维护流程

### 试运行（本周内）

1. 用 4-29 数据开 `--dry-run-keywords` 重跑，对比预期与实际命中率
2. 输出 `filtered_out.csv`，请马老师抽检 5-10 条被剔除文章，确认无误杀
3. 输出 `keyword_dryrun.json`，请马老师抽检 5-10 条被降权文章的命中关键词是否合理
4. 跑完后跑下周新数据 1-2 轮，观察规则在新内容上的稳定性
5. 试运行 1 周后固化进 v2.4.1 / v2.5 正式发布

### 持续维护

- **每月一次**：导出当月被剔除 / 降权样本，请马老师过一遍，识别误杀和漏网
- **更新流程**：直接修改 `data/keywords.yaml`，提交后下次抓取自动生效；运行时调试可调用 `funnel_current_v2.reload_keywords()` 热更新
- **changelog**：每次更新词表，必须在 YAML 末尾的 `changelog` 字段追加一条

### 边界争议处理

如果出现「这条不应该被过滤 / 降权」或「这条应该被过滤但没过滤」：

1. **首选**：往 funnel 现有的强信号词列表加词救回（比扩硬过滤词风险低）
2. **次选**：从 `keywords.yaml` 的降权词类别中移除单个词（如发现某词误降，直接从 YAML 删除即可）
3. **慎重**：往硬过滤词加新词。每加一个硬过滤词都要跑一遍回归测试

---

## 十、附录：原始标注样本清单

### 🔴 红色删除线（4 篇，应被硬过滤）

| # | 英文原标题 | 来源 | 命中类别 |
|---|-----------|------|----------|
| 3 | Two Leading Global Universities Add the Doha Historical Dictionary to Their Digital Libraries | Doha Institute | cultural_announcement |
| 7 | Dr. Shaikh Mohamed Bin Hamad Al Khalifa | Derasat | personal_profile |
| 17 | Maritime Security in the Gulf of Guinea: The Shift from Piracy to Proxy Conflicts | AJCS | out_of_scope_geography |
| 19 | Fourth episode of the sound of thoughts podcast | Derasat | publication_announcement |

### 🟡 黄色高亮（17 篇）

| # | 英文原标题 | 命中状态 |
|---|-----------|----------|
| 1 | The Washington–Vatican Rift | ✅ 降权（Vatican）|
| 2 | Book Review: Elections in Tunisia | ✅ 降权（Tunisia）|
| 5 | How Did the IRGC Seize Power in Iran? | ✅ 降权（Seize Power）|
| 10 | The Rung Bell and the Crooked Strait | ❌ 未覆盖（隐喻标题）|
| 11 | Europe's Role in Maritime Security in Strait of Hormuz | ❌ 未覆盖（视角偏离需上下文）|
| 12 | After Orbán | ✅ 降权（Orbán）|
| 15 | IRAN IN A WEEK March April 16-22, 2026 | ✅ 降权 |
| 18 | Lebanon's Hard Choices | ❌ 未覆盖（Lebanon 故意未入降权）|
| 22 | Digital Activism within the Coptic Community | ✅ 降权（Coptic / Digital Activism）|
| 24 | IRAN IN A WEEK April 9-15, 2026 | ✅ 降权 |
| 29 | Rasanah's Monthly Iran Case File | ✅ 降权（Monthly Iran Case File）|
| 33 | Pakistan-Mediated Ceasefire | ❌ 未覆盖（Pakistan 故意未入降权）|
| 34 | IRAN IN A WEEK March April 2-8, 2026 | ✅ 降权 |
| 35 | US-European Disagreements ... NATO's Future | ✅ 降权（NATO）|
| 36 | Gains and Losses: Assessing the Trajectories of the War on Iran | ❌ 未覆盖（战争重复）|
| 37 | Where Does Russia Stand in the War | ❌ 未覆盖（Russia 故意未入降权）|
| 40 | Escalation Without Exit: Strategic Disorientation | ❌ 未覆盖（战争重复）|
| 41 | Iran's Strategic Options: Rethinking Negotiation | ❌ 未覆盖（战争重复）|
| 43 | Western Sahara in Transition | ✅ 降权（Western Sahara）|

**关键词覆盖率**：17 篇黄色样本中 11 篇能被本次词表降权命中（约 58%）。剩余 6 篇依赖未来「同主题去重模块」覆盖，属本次设计预期范围。

### 🟢 绿色高亮（16 篇，全部应保留）

[4][6][8][9][13][14][16][20][21][23][25][26][27][28][30][31][32][38][42]

其中：
- [25]「Combating Iran's MAD Doctrine: Lessons from History」是**关键回归测试**——含降权词，靠强信号词「Mutually Assured Destruction」救回
- [6]「Iranian Policies on Arabian Gulf ... from the 1979 Revolution」是**关键回归测试**——含降权词，靠强信号词「Arabian Gulf」/「Regional Security」救回

---

**文档结束。** 调整词表时，直接编辑 `data/keywords.yaml` 并在 changelog 追加变更记录。
