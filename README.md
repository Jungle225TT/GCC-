# GCC智库研究抓取系统 v2.3

> 成都创新金融研究院 — 姜亭汀 | 更新于 2026-04-22

自动抓取 21 个 GCC / 泛MENA 智库的最新研究文章，经四层漏斗筛选后输出 Markdown 报告、JSON 数据、AI 研究简报 PDF，并可选推送至飞书多维表格。

---

## 目录

1. [文件结构](#文件结构)
2. [环境准备](#环境准备)
3. [主抓取脚本：gcc_thinktank_scraper_v2.py](#主抓取脚本)
4. [过滤规则配置：filter_rules.yaml](#过滤规则配置)
5. [评分阈值测试：scoring_test.py](#评分阈值测试)
6. [飞书同步：feishu_sync.py](#飞书同步)
7. [全文转PDF：fulltext_to_pdf.py](#全文转pdf)
8. [架构说明：四层漏斗 + 增量去重](#架构说明)
9. [定时任务配置](#定时任务配置)
10. [常见问题](#常见问题)

---

## 文件结构

```
GccScraper/
├── gcc_thinktank_scraper_v2.py   # 主抓取脚本（核心）
├── filter_rules.yaml             # 过滤规则配置（标题黑名单 + URL正则，可直接编辑）
├── ai_client.py                  # AI接口抽象层（DeepSeek / Anthropic 切换）
├── feishu_sync.py                # 将JSON结果推送到飞书多维表格
├── fulltext_to_pdf.py            # 全文抓取并输出PDF/HTML（AI训练数据）
├── scoring_test.py               # 关键词评分阈值对比测试工具
├── dedup.py                      # SQLite去重模块（供外部调用）
├── .gitignore                    # 忽略output/、*.db、.env等
├── output/                       # 主脚本输出目录（自动创建）
│   ├── gcc_research_YYYYMMDD_HHMM.md
│   ├── gcc_research_YYYYMMDD_HHMM.json
│   ├── gcc_summary_YYYYMMDD_HHMM.md    # 仅 --ai 模式生成
│   └── gcc_summary_YYYYMMDD_HHMM.pdf   # 仅 --ai 模式生成
└── output_fulltext/              # 全文PDF输出目录（自动创建）
```

---

## 环境准备

### 1. Python 版本

需要 Python **3.10+**（使用了 `str | None` 类型注解）。

```bash
python --version   # 确认 >= 3.10
```

### 2. 安装依赖

**基础依赖**（所有脚本都需要）：

```bash
pip install requests beautifulsoup4
```

**RSS 支持**（推荐，提升抓取成功率）：

```bash
pip install feedparser
```

**JS 渲染**（SPA 网站必须，如 Carnegie MEC、EPC、Future Center）：

```bash
pip install playwright
playwright install chromium
```

**AI 功能**（翻译、筛选、研究简报）：

```bash
# 默认使用 DeepSeek（推荐，性价比更高）
pip install openai

# 或使用 Anthropic Claude
pip install anthropic
```

**AI 研究简报 PDF 生成**（`--ai` 模式输出 PDF 需要）：

```bash
pip install reportlab
```

**全文PDF生成**（仅 fulltext_to_pdf.py 需要）：

```bash
pip install trafilatura reportlab
```

**外置过滤规则**（`filter_rules.yaml` 需要）：

```bash
pip install pyyaml
```

**飞书同步 + .env 支持**（仅 feishu_sync.py 需要）：

```bash
pip install python-dotenv
```

**一键安装全部依赖**：

```bash
pip install requests beautifulsoup4 feedparser playwright openai reportlab trafilatura pyyaml python-dotenv
playwright install chromium
```

### 3. 配置 API Key

AI 功能通过 `ai_client.py` 管理，默认使用 **DeepSeek**，可通过环境变量切换为 Anthropic Claude。

**默认：DeepSeek（推荐）**

```bash
# macOS / Linux：加入 ~/.zshrc 或 ~/.bashrc
export DEEPSEEK_API_KEY="sk-xxxxx"

# 或者创建 .env 文件（已加入 .gitignore，不会被提交）
echo 'DEEPSEEK_API_KEY=sk-xxxxx' > .env
```

**可选：切换为 Anthropic Claude**

```bash
export AI_PROVIDER=anthropic
export ANTHROPIC_API_KEY="sk-ant-xxxxx"
```

| 环境变量 | 说明 |
|---------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API Key（默认 provider） |
| `AI_PROVIDER` | 设为 `anthropic` 可切换至 Claude；省略则用 DeepSeek |
| `ANTHROPIC_API_KEY` | 仅 `AI_PROVIDER=anthropic` 时需要 |

---

## 主抓取脚本

**文件：** `gcc_thinktank_scraper_v2.py`

### 功能

- 抓取 21 个智库的最新研究文章（HTML + RSS 双通道）
- 深层专题页直接抓取（Carnegie GCC 专题、Al Sharq 国家标签、Arab Reform 国家标签）
- 四层漏斗筛选（来源可信度 → 关键词评分 → 内容类型 → AI辅助）
- 日期标准化：统一输出 `YYYY-MM-DD` 格式，自动过滤无日期文章（机构介绍页兜底）
- 时效过滤：只收录近 N 天的文章，默认 30 天
- SQLite 增量去重（自动跳过上次已处理的文章）
- 可选：AI 边界文章分类、标题批量翻译、AI 研究简报（输出 MD + PDF）；默认用 DeepSeek，可切换至 Anthropic Claude

### 运行方式

**① 最简运行（无需任何配置）**

```bash
python gcc_thinktank_scraper_v2.py
```

仅用 requests 抓取，不调用 AI，默认收录近 30 天文章，结果写入 `./output/`。

---

**② 推荐：启用 Playwright + AI**

```bash
export DEEPSEEK_API_KEY="sk-xxxxx"
python gcc_thinktank_scraper_v2.py --playwright --ai
```

- `--playwright`：启用 Chromium 渲染 JS 页面（Carnegie MEC 等 SPA 站点必须）
- `--ai`：启用 AI 边界文章分类 + 标题翻译 + 研究简报（输出 MD + PDF）

---

**③ 控制时效：只收最近 N 天**

```bash
# 只收近 3 天（日报场景）
python gcc_thinktank_scraper_v2.py --ai --playwright --days 3

# 只收近 10 天（周报场景）
python gcc_thinktank_scraper_v2.py --ai --playwright --days 10

# 近 30 天（默认值，月报场景）
python gcc_thinktank_scraper_v2.py --ai --playwright

# 不限时效（全量历史）
python gcc_thinktank_scraper_v2.py --ai --days 0
```

---

**④ 只抓特定国家**

```bash
# 只抓 UAE 和沙特
python gcc_thinktank_scraper_v2.py --countries UAE "Saudi Arabia" --playwright --ai

# 只抓卡塔尔
python gcc_thinktank_scraper_v2.py --countries Qatar
```

`--countries` 支持多个值，用空格分隔，国家名需与 `THINK_TANKS` 配置中的 `country` 字段一致。

---

**⑤ 控制每站抓取量**

```bash
# 精读模式：每站最多 20 篇
python gcc_thinktank_scraper_v2.py --max-per-tank 20 --ai --playwright

# 全量模式：每站最多 100 篇
python gcc_thinktank_scraper_v2.py --max-per-tank 100
```

默认每站 50 篇，截取最新的。

---

**⑥ 增量去重**

首次运行会自动创建 `gcc_dedup.db`，此后每次运行自动跳过已处理文章：

```bash
# 正常运行（默认启用去重，1 天窗口）
python gcc_thinktank_scraper_v2.py --ai --playwright

# 扩大去重窗口至 7 天（防止一周内重复推送）
python gcc_thinktank_scraper_v2.py --dedup-days 7

# 禁用去重（每次全量处理）
python gcc_thinktank_scraper_v2.py --no-dedup

# 使用自定义数据库路径
python gcc_thinktank_scraper_v2.py --dedup-db /path/to/custom.db
```

---

**⑦ 调试模式**

```bash
# 显示每个候选条目（标题、URL、被过滤原因）
python gcc_thinktank_scraper_v2.py --countries UAE --playwright --debug

# 保留无日期文章（查看被无日期过滤器拦截的内容）
python gcc_thinktank_scraper_v2.py --keep-undated --debug
```

---

### 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--days` | `30` | 只收录近 N 天内发布的文章；常用值：`3`（日报）、`10`（周报）、`30`（月报）；`0` = 不限时效 |
| `--countries` | 全部 | 只抓指定国家，可多个（空格分隔） |
| `--playwright` | 关闭 | 启用 Chromium JS 渲染（Carnegie MEC 等 SPA 站点必须） |
| `--ai` | 关闭 | 启用 AI 筛选 + 翻译 + 研究简报（输出 MD + PDF） |
| `--api-key` | 读环境变量 | AI API Key（DeepSeek 或 Anthropic，建议用环境变量代替） |
| `--output-dir` | `./output` | 输出目录 |
| `--max-per-tank` | `50` | 每个智库最多保留篇数 |
| `--no-dedup` | 关闭 | 禁用 SQLite 增量去重 |
| `--dedup-db` | `gcc_dedup.db` | 去重数据库路径 |
| `--dedup-days` | `1` | 去重时间窗口（天）；`0` = 关闭去重效果 |
| `--keep-undated` | 关闭 | 保留无发布日期的文章（默认过滤，用于调试） |
| `--debug` | 关闭 | 显示调试日志 |

### 输出文件

运行后在 `./output/` 目录下生成：

| 文件 | 内容 |
|------|------|
| `gcc_research_YYYYMMDD_HHMM.md` | Markdown 报告，按优先级（⭐/📄/📋）分组 |
| `gcc_research_YYYYMMDD_HHMM.json` | 完整数据，可导入飞书/Notion |
| `gcc_summary_YYYYMMDD_HHMM.md` | AI 结构化研究简报，含目录+逐篇解析+趋势信号（仅 `--ai`） |
| `gcc_summary_YYYYMMDD_HHMM.pdf` | 同上，排版后的 PDF 版本，可直接分发（仅 `--ai`，需 `reportlab`） |

---

## 过滤规则配置

**文件：** `filter_rules.yaml`

### 作用

控制 `_is_likely_article()` 函数的判定逻辑，决定哪些链接被认定为"导航/介绍页"而丢弃。包含两个规则集：

| 规则集 | 匹配方式 | 用途 |
|--------|---------|------|
| `nav_exact` | 标题精确匹配（大小写不敏感） | 过滤导航词、机构全称、栏目名等 |
| `nav_url_patterns` | URL 正则匹配（Python `re.search`） | 过滤分类页、成员页、活动页、部门页等 |

### 加载机制

脚本启动时自动读取同目录下的 `filter_rules.yaml`（需安装 `pyyaml`）：

- **文件存在且 pyyaml 已装**：加载 YAML，启动日志输出规则数量
- **文件不存在**：静默使用代码内置默认值（与 YAML 内容保持同步）
- **pyyaml 未安装**：打印警告，使用内置默认值

```
📋 过滤规则已加载：130 条精确匹配，35 条 URL 模式
```

### 编辑方法

直接打开 `filter_rules.yaml`，在对应列表下追加或删除条目，保存后下次运行即生效，**无需改动 Python 代码**。

**添加标题黑名单（nav_exact）：**

```yaml
nav_exact:
  - publications          # 已有条目
  - my new nav term       # 新增：直接追加
```

**添加 URL 正则黑名单（nav_url_patterns）：**

```yaml
nav_url_patterns:
  - '/category/'          # 已有条目
  - '/my-section/'        # 新增：普通路径片段
  - '/archive/\d{4}/'     # 新增：含正则（年份归档页）
```

> **注意**：`nav_url_patterns` 的每一项是 Python 正则表达式，匹配前 URL 已转为小写。含特殊字符（如 `[`, `?`, `\`）的模式建议用单引号括起来。

### 常见场景

**某智库的栏目页反复误入结果**，在 `nav_exact` 末尾加一行该栏目的英文标题（全小写）即可。

**某智库的 URL 路径规律性地对应介绍页**（如 `/insight/category/`），在 `nav_url_patterns` 末尾加对应正则即可。

---

## 评分阈值测试

**文件：** `scoring_test.py`

### 功能

在 38 篇人工标注的测试集上对比阈值 1–6 的精度/召回，帮助调整 `RELEVANCE_THRESHOLD`。

### 运行方式

**① 使用内置测试集**

```bash
python scoring_test.py
```

输出各阈值的保留/排除统计，并自动分析 `output/` 目录下最新的 JSON 文件。

---

**② 指定实际抓取数据**

```bash
python scoring_test.py --json output/gcc_research_20260422_1000.json
```

额外显示各智库实际文章数分布，以及泛MENA文章的具体评分。

### 输出示例

```
阈值 │相关保留  │相关漏抓  │误留不相关  │正确排除  │边界保留  │准确率  │ 评价
 ≥1 │  15/15  │   0/15  │    3/13   │  10/13  │  10/10  │  89.3% │ ✅良好
 ≥2 │  15/15  │   0/15  │    2/13   │  11/13  │   9/10  │  92.9% │ ✅良好
 ≥3 │  15/15  │   0/15  │    0/13   │  13/13  │   7/10  │ 100.0% │ ⭐最优 ◀当前
 ≥4 │  13/15  │   2/15  │    0/13   │  13/13  │   5/10  │  92.9% │ ✅良好
```

### 调整阈值

测试完毕后，在 `gcc_thinktank_scraper_v2.py` 顶部修改：

```python
RELEVANCE_THRESHOLD = 3   # 当前推荐值，调整这里
SCORE_STRONG = 3          # GCC / 海合会
SCORE_COUNTRY = 2         # 国家名（Saudi Arabia, UAE...）
SCORE_WEAK = 1            # Gulf / Middle East / MENA
TITLE_MULTIPLIER = 2      # 标题命中得分翻倍
```

---

## 飞书同步

**文件：** `feishu_sync.py`

### 功能

将主脚本生成的 JSON 文件批量写入飞书多维表格，支持增量同步（URL去重，不重复写入）。

### 一次性配置（飞书端）

1. 登录 [open.feishu.cn](https://open.feishu.cn) → 创建企业自建应用
2. 获取 **App ID** 和 **App Secret**
3. 应用权限中开启：`bitable:app`（多维表格全部权限）
4. 发布应用版本
5. 在飞书中创建多维表格，将应用机器人添加为**协作者**（编辑权限）
6. 从表格 URL 中复制 `app_token`（`sh` 开头）和 `table_id`

### 配置 API 凭证

**方式一：.env 文件（推荐）**

```bash
cat > .env << 'EOF'
FEISHU_APP_ID=cli_xxxxx
FEISHU_APP_SECRET=xxxxx
FEISHU_APP_TOKEN=shxxxxx
FEISHU_TABLE_ID=tblxxxxx
EOF
```

**方式二：环境变量**

```bash
export FEISHU_APP_ID="cli_xxxxx"
export FEISHU_APP_SECRET="xxxxx"
export FEISHU_APP_TOKEN="shxxxxx"
export FEISHU_TABLE_ID="tblxxxxx"
```

### 运行方式

**① 同步指定 JSON 文件**

```bash
python feishu_sync.py output/gcc_research_20260422_1000.json
```

**② 通配符同步多个文件**

```bash
python feishu_sync.py output/gcc_research_*.json
```

**③ 自动查找最新文件**

```bash
python feishu_sync.py
# 自动查找 output/ 目录下最新的 gcc_research_*.json
```

**④ 与主脚本联动（推荐）**

```bash
python gcc_thinktank_scraper_v2.py --ai --playwright && python feishu_sync.py
```

### 首次运行会自动创建以下字段

| 字段名 | 类型 | 说明 |
|--------|------|------|
| 发布日期 | 文本 | 文章发布日期（YYYY-MM-DD 格式） |
| 平台 | 文本 | 智库名称 |
| 标题 | 文本 | 英文原标题 |
| 中文标题 | 文本 | Claude 翻译（需 --ai） |
| 链接 | 超链接 | 原文 URL |
| 优先级 | 单选 | ⭐优先阅读 / 📄常规 / 📋简讯 |
| 内容类型 | 单选 | high / medium / low / unknown |
| 数据来源 | 单选 | RSS / HTML |
| 国家 | 文本 | 智库所在国家 |
| 摘要 | 文本 | 文章摘要 |
| 抓取时间 | 文本 | 本次抓取时间戳 |

### 注意事项

- 飞书 API 限频：100 次/分钟，脚本已自动加 1s 间隔
- 若读取历史记录失败（网络超时/限频），脚本**会中止写入**而非全量重复写入
- 表格中已有的 URL 自动跳过，不会重复写入

---

## 全文转PDF

**文件：** `fulltext_to_pdf.py`

### 功能

逐篇抓取指定智库文章的**完整正文**，合并输出为一个 PDF + HTML 文件，用于 AI 训练数据采集。

### 可用站点

```bash
python fulltext_to_pdf.py --list
```

```
可用站点:

  kapsarc            King Abdullah Petroleum Studies and Research Centre (KAPSARC)  [Saudi Arabia]
  ajcs               Al Jazeera Centre for Studies (AJCS)  [Qatar]
  carnegie           Carnegie Middle East Center  [Lebanon]
  rasanah            International Institute for Iranian Studies (Rasanah IIIS)  [Saudi Arabia]
  brookings-doha     Brookings Doha Center  [Qatar]
  derasat            Bahrain Center for Strategic, International and Energy Studies (Derasat)  [Bahrain]
```

### 运行方式

**① 默认（抓 KAPSARC，最多 20 篇）**

```bash
python fulltext_to_pdf.py
```

**② 指定站点**

```bash
python fulltext_to_pdf.py --site ajcs
python fulltext_to_pdf.py --site carnegie
python fulltext_to_pdf.py --site brookings-doha
```

**③ 控制篇数**

```bash
# 抓 50 篇
python fulltext_to_pdf.py --site kapsarc --max 50

# 最多 10 篇，快速验证
python fulltext_to_pdf.py --site rasanah --max 10
```

**④ 启用 JS 渲染（SPA 网站）**

```bash
python fulltext_to_pdf.py --site ajcs --playwright
```

**⑤ 调试模式**

```bash
python fulltext_to_pdf.py --site kapsarc --debug
```

### 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--site` | `kapsarc` | 目标站点（见 `--list`） |
| `--max` | 20 | 最多抓取篇数 |
| `--playwright` | 关闭 | 启用 JS 渲染 |
| `--output-dir` | `./output_fulltext` | 输出目录 |
| `--list` | — | 列出所有可用站点后退出 |
| `--debug` | 关闭 | 显示详细日志 |

### 输出文件

在 `./output_fulltext/` 下生成：

| 文件 | 说明 |
|------|------|
| `kapsarc_YYYYMMDD_HHMM.pdf` | 封面 + 目录 + 正文的 PDF |
| `kapsarc_YYYYMMDD_HHMM.html` | 同内容的静态 HTML（可直接在浏览器阅读） |

若未安装 `reportlab`，自动降级输出 `.txt` 文件。

---

## 架构说明

### 四层漏斗筛选

```
原始文章（HTML / RSS）
        │
        ▼
┌─────────────────────────────────────┐
│  第一层：来源可信度                  │
│  core_gcc 智库 → 直接通过（99分）   │
│  deep_topic 专题页 → 自动通过（5分）│  ← v2.3 新增
│  pan_mena 智库 → 进入第二层         │
└──────────────┬──────────────────────┘
               ▼
┌─────────────────────────────────────┐
│  第二层：关键词评分                  │
│  GCC / 海合会 = 3分                │
│  国家名（UAE/Saudi...）= 2分       │
│  Gulf / MENA / 中东 = 1分         │
│  标题命中 ×2                       │
│  总分 ≥ 3 → 通过                   │
└──────────────┬──────────────────────┘
               ▼
┌─────────────────────────────────────┐
│  第三层：内容类型识别                │
│  排除：Register / Vacancy / 招聘... │
│  高价值：report / analysis → ⭐     │
│  中价值：blog / opinion → 📄       │
│  低价值：newsletter → 📋           │
└──────────────┬──────────────────────┘
               ▼
┌─────────────────────────────────────┐
│  第四层：AI 辅助（可选）             │
│  评分 2–4 的边界文章                │
│  → Claude Haiku 快速二分类          │
└──────────────┬──────────────────────┘
               ▼
┌─────────────────────────────────────┐
│  后处理过滤                          │
│  无日期文章 → 过滤（机构页兜底）     │  ← v2.3 新增
│  超出时效窗口 → 过滤（--days 控制）  │  ← v2.3 新增
└──────────────┬──────────────────────┘
               ▼
          最终文章列表（按发布日期降序）
```

### deep_topic 深层专题页机制

对 Carnegie MEC、Al Sharq Forum、Arab Reform Initiative 三个泛MENA站点，v2.3 改为直接抓取各智库自己整理好的 GCC 国别专题页和标签页（如 `/regions/saudi-arabia`、`/tag/gcc/`），跳过首页随机内容。从这些专题页抓到的文章默认通过来源可信度关卡（得 5 分），不再走关键词评分，大幅提升召回率。

### 增量去重机制

```
抓取结果
   │
   ▼  load_seen_urls("gcc_dedup.db")
过滤已见 URL
   │
   ▼  翻译 + 导出
   │
   ▼  save_new_urls(articles, "gcc_dedup.db")
写入新 URL
```

- 去重数据库默认存放在脚本同目录下的 `gcc_dedup.db`
- 可用 `--no-dedup` 跳过（全量重处理）
- 飞书同步有**独立的飞书层去重**，两层去重互不干扰

### 日期标准化

所有来源的日期统一为 `YYYY-MM-DD` 格式（或 `YYYY-MM` / `YYYY`）：

| 原始格式 | 标准化后 |
|---------|---------|
| `April 22, 2026` / `22 Apr 2026` | `2026-04-22` |
| `2024-03-15T10:30:00Z` | `2024-03-15` |
| `March 2025` | `2025-03` |
| `15/03/2024` | `2024-03-15` |
| 无法解析 | `None`（触发无日期过滤） |

### 数据流

```
gcc_thinktank_scraper_v2.py
        │
        ├─ output/gcc_research_*.json  ──→  feishu_sync.py  ──→  飞书多维表格
        ├─ output/gcc_research_*.md    ──→  直接阅读 / 分发
        ├─ output/gcc_summary_*.md     ──→  研究团队内部简报
        └─ output/gcc_summary_*.pdf    ──→  可直接分发的 PDF 简报
```

### 覆盖的智库（21 个）

**核心 GCC 智库（17个，直接通过筛选）**

| 国家 | 智库 |
|------|------|
| 🇸🇦 沙特 | KAPSARC, Rasanah IIIS, King Faisal Center |
| 🇦🇪 阿联酋 | EPC, ECSSR, GRC, Bhuth, Al Qasimi Foundation, Future Center |
| 🇶🇦 卡塔尔 | AJCS, Brookings Doha, Doha Institute |
| 🇰🇼 科威特 | API, KISR |
| 🇧🇭 巴林 | Derasat |
| 🇴🇲 阿曼 | Tawasul |
| 🇺🇸 美国 | AGSIW（Arab Gulf States Institute in Washington）|

**泛 MENA 智库（4个，GCC 专题页直接通过 / 首页需关键词评分 ≥ 3）**

| 国家 | 智库 | 抓取方式 |
|------|------|---------|
| 🇱🇧 黎巴嫩 | Carnegie Middle East Center | deep_topic 专题页（需 Playwright） |
| 🇪🇬 埃及 | Al-Ahram Center | 首页 + 关键词评分 |
| 🇹🇷 土耳其 | Al Sharq Forum | deep_topic 国别标签页 |
| 🇫🇷 法国 | Arab Reform Initiative | deep_topic 国别标签页 |

---

## 定时任务配置

### macOS / Linux（crontab）

```bash
# 编辑 crontab
crontab -e

# 每天早上 8 点运行全量抓取（近30天）+ 飞书同步
0 8 * * * cd /path/to/GccScraper && \
    /usr/bin/python3 gcc_thinktank_scraper_v2.py --playwright --ai --days 30 >> logs/scraper.log 2>&1 && \
    /usr/bin/python3 feishu_sync.py >> logs/feishu.log 2>&1
```

### Windows（任务计划程序）

使用 `setup.bat` 或 `test_run.bat` 进行手动测试，正式定时任务建议在 Linux 服务器上运行。

### GitHub Actions（推荐云端运行）

创建 `.github/workflows/scrape.yml`：

```yaml
name: GCC Scraper

on:
  schedule:
    - cron: '0 0 * * *'   # 每天 UTC 00:00（北京时间 08:00）
  workflow_dispatch:        # 支持手动触发

jobs:
  scrape:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install requests beautifulsoup4 feedparser playwright openai reportlab python-dotenv
      - run: playwright install chromium
      - run: python gcc_thinktank_scraper_v2.py --playwright --ai --days 30
        env:
          DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}
      - run: python feishu_sync.py
        env:
          FEISHU_APP_ID: ${{ secrets.FEISHU_APP_ID }}
          FEISHU_APP_SECRET: ${{ secrets.FEISHU_APP_SECRET }}
          FEISHU_APP_TOKEN: ${{ secrets.FEISHU_APP_TOKEN }}
          FEISHU_TABLE_ID: ${{ secrets.FEISHU_TABLE_ID }}
      - uses: actions/upload-artifact@v4
        with:
          name: gcc-reports
          path: output/
```

---

## 常见问题

### Q：某个网站抓不到内容，结果为 0 篇？

先加 `--debug` 查看详细日志：

```bash
python gcc_thinktank_scraper_v2.py --countries UAE --debug
```

- 如果看到 `requests 失败`，通常是 JS 渲染问题 → 加 `--playwright`
- 如果看到大量 `❌ 排除` 或 `⏭️ 评分不足`，说明筛选过严 → 考虑降低阈值或检查选择器

### Q：结果都是 0 篇，显示"时效过滤"移除了很多？

默认只收录近 30 天的文章。如需收录更早的内容：

```bash
# 扩大至近 90 天
python gcc_thinktank_scraper_v2.py --days 90

# 不限时效
python gcc_thinktank_scraper_v2.py --days 0
```

### Q：结果包含机构介绍页或无日期文章？

v2.3 默认开启无日期过滤（机构介绍页通常没有发布日期）。如需调试查看被过滤的内容：

```bash
python gcc_thinktank_scraper_v2.py --keep-undated --debug
```

如果某个机构介绍页反复出现，将其标题（全小写）加入 `filter_rules.yaml` 的 `nav_exact` 列表，或将其 URL 路径规律加入 `nav_url_patterns`，下次运行即生效。详见[过滤规则配置](#过滤规则配置)章节。

### Q：修改过滤规则后不生效？

检查以下几点：

1. 确认已安装 `pyyaml`：`pip install pyyaml`
2. 确认 `filter_rules.yaml` 与 `gcc_thinktank_scraper_v2.py` 在同一目录
3. 启动时日志应出现 `📋 过滤规则已加载：...` 字样；若出现 `使用内置默认规则` 说明 YAML 未被读取
4. YAML 格式错误（如缩进不一致）会导致加载失败，检查报错信息后修正

### Q：如何添加新智库？

在 `THINK_TANKS` 列表中新增一项，用浏览器 F12 找到文章卡片的 CSS 选择器：

```python
{
    "name": "智库全名",
    "country": "Saudi Arabia",          # 需与 --countries 参数保持一致
    "tier": "core_gcc",                  # core_gcc 或 pan_mena
    "base_url": "https://example.com",
    "pages": ["/publications/"],
    "rss_feeds": ["https://example.com/feed/"],  # 有RSS优先用RSS
    # 以下两个字段仅用于泛MENA站点的深层专题页（可选）：
    # "deep_topic": True,               # 从专题页抓取，跳过关键词评分
    # "use_playwright": True,           # SPA 站点需要 JS 渲染
    "selectors": {
        "article": "article, .card",     # 文章卡片容器
        "title": "h2 a, h3 a",           # 标题链接
        "snippet": "p, .excerpt",        # 摘要
        "date": "time, .date",           # 日期
    },
},
```

然后用单站测试验证：

```bash
python gcc_thinktank_scraper_v2.py --countries "新国家名" --debug --playwright
```

### Q：如何调整关键词评分阈值？

先用 `scoring_test.py` 验证效果，再修改主文件：

```bash
# 先测试不同阈值的效果
python scoring_test.py

# 确认后修改 gcc_thinktank_scraper_v2.py 顶部的常量
RELEVANCE_THRESHOLD = 3   # 改为你想要的值
```

### Q：AI 功能费用？

默认使用 DeepSeek，费用极低：

| 功能 | 使用模型（DeepSeek） | 估算成本 |
|------|---------|---------|
| 边界文章分类（20篇） | deepseek-chat | ~$0.0002 |
| 标题批量翻译（100篇） | deepseek-chat | ~$0.001 |
| 研究简报生成（1次） | deepseek-chat | ~$0.003 |

每日运行一次全量抓取 + AI 的总成本通常在 **$0.005 以内**。

如切换为 Anthropic Claude（`AI_PROVIDER=anthropic`），成本约为 DeepSeek 的 5–10 倍。

### Q：当天运行后再次运行，显示"去重过滤了 N 篇，剩余 0 篇"？

这是正常的去重行为：当天已处理的文章 URL 都记录在 `gcc_dedup.db`，同一天再次运行会过滤掉全部已见文章。

**解决方案：**

```bash
# 方案1：直接删除数据库，下次运行重建（最彻底）
rm gcc_dedup.db
python gcc_thinktank_scraper_v2.py --ai

# 方案2：本次跳过去重，不影响数据库（推荐）
python gcc_thinktank_scraper_v2.py --no-dedup --ai

# 方案3：关闭去重窗口（每次都全量处理）
python gcc_thinktank_scraper_v2.py --dedup-days 0 --ai
```

> **注意**：去重的目的是防止同一篇文章被多次推送到飞书。如果只是想重新生成 AI 简报，用方案2即可；如果要完全重置，用方案1。

### Q：去重数据库损坏或想重置？

```bash
# 删除数据库，下次运行会重建
rm gcc_dedup.db

# 或者用 --no-dedup 临时跳过，不删除数据库
python gcc_thinktank_scraper_v2.py --no-dedup
```

### Q：飞书同步提示"读取历史记录失败"？

这是网络超时或飞书 API 限频导致的。脚本会**中止本次写入**而非重复写入所有数据。

解决方案：

1. 等待 1–2 分钟后重试
2. 检查 `FEISHU_APP_TOKEN` 和 `FEISHU_TABLE_ID` 是否正确
3. 确认应用机器人已被添加为表格协作者

### Q：全文 PDF 的正文提取质量不好？

```bash
# 确认 trafilatura 已安装（质量最高的正文提取库）
pip install trafilatura

# 对 SPA 网站加 --playwright
python fulltext_to_pdf.py --site ajcs --playwright
```

若某篇文章正文仍为空，说明该网站需要登录或有反爬，目前无解。

### Q：PDF 打不开或损坏？

v2.3 已修复 URL 中 `&` 字符导致的 XML 格式错误（会使 reportlab 写出损坏文件）。如仍遇到问题：

1. 确认 `reportlab` 版本 ≥ 3.6：`pip install --upgrade reportlab`
2. 检查运行日志，若有 `⚠️ PDF 首次生成失败，降级重试` 提示，降级模式下链接不可点击但 PDF 可正常打开
3. 删除损坏的 PDF 文件后重新运行
