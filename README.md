# GCC智库研究抓取系统 v2.4.1

> 成都创新金融研究院 — 姜亭汀 | 更新于 2026-05-11

自动抓取 29 个 GCC / 泛MENA / 域外英美智库的最新研究文章，经四层漏斗筛选后输出 Markdown 报告、JSON 数据、AI 研究简报 PDF，并可选推送至飞书多维表格。

---

## 目录

1. [文件结构](#文件结构)
2. [环境准备](#环境准备)
3. [主抓取脚本：gcc_thinktank_scraper_v2.py](#主抓取脚本)
4. [关键词配置：keywords.yaml](#关键词配置)
5. [过滤规则配置：filter_rules.yaml](#过滤规则配置)
6. [评分阈值测试：scoring_test.py](#评分阈值测试)
7. [飞书同步：feishu_sync.py](#飞书同步)
8. [全文转PDF：fulltext_to_pdf.py](#全文转pdf)
9. [架构说明：四层漏斗 + 增量去重](#架构说明)
10. [Google Drive + Colab 协同](#google-drive--colab-协同)
11. [定时任务配置](#定时任务配置)
12. [常见问题](#常见问题)

> **深度阅读**：如需了解各技术决策背后的原因（为什么选 DeepSeek、为什么是四层漏斗、两档分级如何演变等），请阅读 [docs/PROJECT_GUIDE.md](docs/PROJECT_GUIDE.md)。

---

## 文件结构

```
GccScraper/
├── README.md                          # 项目主文档
├── requirements.txt                   # Python 依赖清单（pip install -r requirements.txt）
├── .gitignore
│
├── # ─── 核心源码（根目录直接运行）──────────────────────────────
├── gcc_thinktank_scraper_v2.py        # 主抓取脚本
├── keywords.yaml                      # 关键词配置（硬过滤 / 降权 / 仅标题降权）
├── ai_client.py                       # AI 接口抽象层（DeepSeek / Anthropic）
├── feishu_sync.py                     # 飞书多维表格同步
├── fulltext_to_pdf.py                 # 全文抓取并输出 PDF/HTML
├── scoring_test.py                    # 关键词评分阈值测试
├── dedup.py                           # SQLite 去重模块
├── filter_rules.yaml                  # 导航链接过滤规则配置（直接编辑，无需改代码）
│
├── notebooks/                         # Google Colab 协同工作
│   └── GCC_Scraper_Colab.ipynb        # 一键运行笔记本（挂载 Drive → 安装 → 运行）
│
├── docs/                              # 项目文档与进展汇报
│   ├── GCC智库抓取系统_项目进展汇报.docx
│   ├── GCC智库抓取系统进展v2.3.docx
│   ├── 技术变更记录_20260415.docx
│   ├── 筛选思路改进.docx
│   └── 飞书对接指南.md
│
├── assets/                            # 截图等静态资源
│   ├── 爬取测试.png
│   ├── 阈值测试.png
│   ├── 阈值测试2.png
│   └── 飞书表格.png
│
├── scripts/                           # 辅助脚本
│   ├── test_keywords_funnel.py        # 关键词漏斗回归测试（红/黄/绿测试集）
│   ├── setup.bat
│   └── test_run.bat
│
├── output/                            # 主脚本输出（gitignored，自动创建）
│   ├── gcc_research_YYYYMMDD_HHMM.md
│   ├── gcc_research_YYYYMMDD_HHMM.json
│   ├── gcc_summary_YYYYMMDD_HHMM.md  # 仅 --ai 模式
│   └── gcc_summary_YYYYMMDD_HHMM.pdf # 仅 --ai 模式
├── output_fulltext/                   # 全文 PDF 输出（gitignored，自动创建）
└── data/                              # 本地数据库（gitignored，自动创建）
    └── gcc_dedup.db                   # SQLite 增量去重数据库
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

### 4. 配置 AI 简报邮件发送（可选）

如需在每次 `--ai` 生成 PDF 后自动发送邮件，在 `.env` 或运行环境中配置 SMTP。脚本只会把 `gcc_summary_*.pdf` 作为附件发送，Markdown、JSON、CSV 等其他输出文件不会进入邮件。

```bash
AI_BRIEF_EMAIL_TO=recipient@example.com
AI_BRIEF_EMAIL_FROM=sender@example.com
AI_BRIEF_EMAIL_FROM_NAME=GCC AI简报
AI_BRIEF_SMTP_HOST=smtp.example.com
AI_BRIEF_SMTP_PORT=587
AI_BRIEF_SMTP_USER=sender@example.com
AI_BRIEF_SMTP_PASSWORD=your_smtp_password_or_app_password
AI_BRIEF_SMTP_STARTTLS=true
```

邮件主题默认为 `AI简报 YYYY-MM-DD`，正文会用约 250 字说明简报的阅读和引用方法。多个收件人可用逗号或分号分隔；如使用 465 端口，可设置 `AI_BRIEF_SMTP_USE_SSL=true`。

---

## 主抓取脚本

**文件：** `gcc_thinktank_scraper_v2.py`

### 功能

- 抓取 29 个智库的最新研究文章（HTML + RSS 双通道）
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

`--countries` 支持多个值，用空格分隔，国家名需与 `think_tanks.yaml` 中的 `country` 字段一致。

---

**⑤ 按维度分类抓取**

```bash
# 只抓 GCC 本地智库
python gcc_thinktank_scraper_v2.py --regions gcc --ai --playwright

# 只抓域外英美视角
python gcc_thinktank_scraper_v2.py --regions western --ai --days 10

# 只抓能源议题相关智库（KAPSARC / KISR / Derasat / OIES / Baker / CSIS …）
python gcc_thinktank_scraper_v2.py --topics energy --ai --playwright

# 只抓独立智库的安全议题
python gcc_thinktank_scraper_v2.py --org-types independent --topics security --ai

# 按区域分组输出 Markdown（不同于默认的两档分组）
python gcc_thinktank_scraper_v2.py --ai --group-by region

# 按议题分组输出
python gcc_thinktank_scraper_v2.py --ai --group-by topic
```

---

**⑥ 控制每站抓取量**

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
# 当前日常近 7 天 AI 简报（本地复盘，跳过 SQLite 去重）
python gcc_thinktank_scraper_v2.py --ai --days 7 --no-dedup

# 正常运行（默认启用去重，1 天窗口）
python gcc_thinktank_scraper_v2.py --ai --playwright

# 扩大去重窗口至 7 天（防止一周内重复推送）
python gcc_thinktank_scraper_v2.py --dedup-days 7

# 生产化运行前先补建 data/，再启用 SQLite 增量去重
mkdir -p data
python gcc_thinktank_scraper_v2.py --ai --days 7 --dedup-db data/gcc_dedup.db --dedup-days 14

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
| `--countries` | 全部 | 按国家过滤，可多个，如 `--countries Qatar UAE` |
| `--regions` | 全部 | 按区域过滤：`gcc` / `mena` / `western`，可多个 |
| `--org-types` | 全部 | 按机构性质过滤：`official` / `university` / `independent`，可多个 |
| `--topics` | 全部 | 按议题标签过滤（至少含其一的智库才被纳入）：`energy` / `security` / `economy` / `politics` / `society` / `technology` |
| `--group-by` | 无（按相关性两档） | Markdown 输出分组方式：`region` / `org_type` / `topic`；默认按强相关/中等相关两档分组 |
| `--playwright` | 关闭 | 启用 Chromium JS 渲染（Carnegie MEC 等 SPA 站点必须） |
| `--ai` | 关闭 | 启用 AI 筛选 + 翻译 + 研究简报（输出 MD + PDF） |
| `--api-key` | 读环境变量 | AI API Key（DeepSeek 或 Anthropic，建议用环境变量代替） |
| `--output-dir` | `./output` | 输出目录 |
| `--email-summary-to` | `AI_BRIEF_EMAIL_TO` | AI简报PDF收件邮箱；可用逗号/分号分隔多个 |
| `--no-email-summary` | 关闭 | 即使已配置收件邮箱，也跳过AI简报PDF邮件发送 |
| `--max-per-tank` | `50` | 每个智库最多保留篇数 |
| `--no-dedup` | 关闭 | 禁用 SQLite 增量去重 |
| `--dedup-db` | `data/gcc_dedup.db` | 去重数据库路径 |
| `--dedup-days` | `1` | 去重时间窗口（天）；`0` = 关闭去重效果 |
| `--keep-undated` | 关闭 | 保留无发布日期的文章（默认过滤，用于调试） |
| `--dry-run-keywords` | 关闭 | 试运行模式：输出关键词命中明细（`keyword_dryrun.json`）和被硬过滤条目（`filtered_out.csv`），便于调参 |
| `--debug` | 关闭 | 显示调试日志 |

### 输出文件

运行后在 `./output/` 目录下生成：

| 文件 | 内容 |
|------|------|
| `gcc_research_YYYYMMDD_HHMM.md` | Markdown 报告，按相关性两档分组（⭐ 强相关置顶 / 📄 中等相关） |
| `gcc_research_YYYYMMDD_HHMM.json` | 完整数据，可导入飞书/Notion |
| `gcc_summary_YYYYMMDD_HHMM.md` | AI 结构化研究简报：目录按两档分节（⭐ 推荐阅读 / 📄 中等相关）+ 逐篇解析（强相关章节标题加 ⭐）+ 趋势信号（仅 `--ai`） |
| `gcc_summary_YYYYMMDD_HHMM.pdf` | 同上，排版后的 PDF 版本，可直接分发（仅 `--ai`，需 `reportlab`） |

如已配置 `AI_BRIEF_EMAIL_TO` 和 SMTP 环境变量，`gcc_summary_*.pdf` 生成成功后会自动发送；邮件附件只包含该 PDF。

---

## 关键词配置

**文件：** `keywords.yaml`

### 作用

控制漏斗第二层（关键词评分）和第三层（硬过滤）的行为，**无需改动 Python 代码**，直接编辑此文件后重新运行即生效。

### 三类词表

| 词表 | 触发层 | 效果 |
|------|--------|------|
| `hard_filter_words` | 第三层 | 命中则直接丢弃（对所有 tier 含 core_gcc 均生效） |
| `demote_words` | 第二层 | 命中则评分 -2，检查标题 + 摘要 |
| `title_only_demote_words` | 第二层 | 命中则评分 -2，**仅检查标题**（适合摘要中常被引用的词，如 NATO） |

### 当前硬过滤分类（v1.3）

| 分类 | 代表词 | 说明 |
|------|--------|------|
| `publication_announcement` | podcast、episode of | 播客/节目公告 |
| `event_announcement` | roundtable discussion、organizes a lecture | 活动公告 |
| `periodic_monitoring` | IRAN IN A WEEK、Monthly Iran Case File | 定期监控简报 |
| `personal_profile` | Dr. Sheikh、Dr. Shaikh | 人物简介页 |
| `cultural_announcement` | Historical Dictionary、digital libraries | 文化/资源公告 |
| `out_of_scope_geography` | Gulf of Guinea、Latin America | 非目标地区 |

### 试运行调参

```bash
# 本地试运行（输出命中明细，不调用 AI，不写去重库）
python gcc_thinktank_scraper_v2.py \
  --dry-run-keywords --no-dedup \
  --output-dir "./output_test" --max-per-tank 20
# 产出：output_test/keyword_dryrun.json（通过文章 + 降权明细）
#       output_test/filtered_out.csv（被硬过滤文章）
```

运行时热重载词表（无需重启）：

```python
# 在 Python 交互环境 / Colab 中调用
from gcc_thinktank_scraper_v2 import reload_keywords
reload_keywords()
```

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
│  deep_topic 专题页 → 自动通过（5分）│
│  pan_mena 智库 → 进入第二层         │
└──────────────┬──────────────────────┘
               ▼
┌─────────────────────────────────────┐
│  第二层：关键词评分（keywords.yaml） │
│  STRONG（gcc/海合会/hormuz...）= 3分│
│  COUNTRY（UAE/Saudi...）= 2分      │
│  WEAK（Gulf/MENA...）= 1分         │
│  标题命中 ×2；降权词命中 -2        │
│  total ≥ 3 → 通过                  │
└──────────────┬──────────────────────┘
               ▼
┌─────────────────────────────────────┐
│  第三层：内容类型 + 硬过滤           │
│  （keywords.yaml hard_filter_words）│
│  排除：podcast/event/人物介绍/非核心│  ← 对所有 tier 生效
│  高价值：report/analysis → 相关性↑  │
│  低价值：newsletter → 相关性↓       │
└──────────────┬──────────────────────┘
               ▼
┌─────────────────────────────────────┐
│  第四层：AI 辅助（可选）             │
│  评分 2–4 的边界文章                │
│  → DeepSeek / Claude 快速二分类     │
└──────────────┬──────────────────────┘
               ▼
┌─────────────────────────────────────┐
│  后处理过滤                          │
│  无日期文章 → 过滤（机构页兜底）     │
│  超出时效窗口 → 过滤（--days 控制）  │
└──────────────┬──────────────────────┘
               ▼
     最终文章列表（按发布日期降序）
     输出 Markdown：
       ⭐ 推荐阅读（强相关，评分 ≥ 4.0）← 置顶，标题加⭐
       📄 中等相关（评分 < 4.0）
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
        ├─ output/gcc_summary_*.md     ──→  研究团队内部简报（含两档目录与 ⭐ 标记）
        └─ output/gcc_summary_*.pdf    ──→  可直接分发的 PDF 简报（同上）
```

### 覆盖的智库（29 个）

共 **29 个**智库，按三个维度分类管理。

**维度一：地区（region）**

| 区域 | 数量 | 代表机构 |
|------|------|---------|
| `gcc` GCC核心 | 16个 | KAPSARC、EPC、AJCS、Derasat … |
| `mena` 泛MENA | 4个 | Carnegie MEC、Al-Ahram、Al Sharq Forum、Arab Reform |
| `western` 域外英美 | 9个 | AGSIW、MEI、CSIS、Atlantic Council、Chatham House、OIES、Baker Institute、Wilson Center、IISS |

**维度二：机构性质（org_type）**

| 类型 | 说明 | 代表机构 |
|------|------|---------|
| `official` 官方/政府 | 政府资助或官方背景 | KAPSARC、EPC、AJCS、API … |
| `university` 大学研究 | 依托高校的研究中心 | Brookings Doha、Doha Institute、OIES、Baker Institute |
| `independent` 独立智库 | 独立运营的研究机构 | GRC、Carnegie MEC、AGSIW、MEI、CSIS、Chatham House … |

**维度三：议题（topics）**

| 标签 | 覆盖智库示例 |
|------|------------|
| `energy` ⚡ | KAPSARC、KISR、Derasat、OIES、Baker Institute、CSIS |
| `security` 🛡️ | Rasanah、ECSSR、EPC、Carnegie MEC、IISS、Atlantic Council |
| `economy` 💰 | EPC、GRC、API、Brookings Doha、Wilson Center、CSIS |
| `politics` 🏛 | King Faisal、EPC、AJCS、Carnegie MEC、MEI、Chatham House |
| `society` 👥 | Al Qasimi Foundation、Doha Institute、Al Sharq Forum、Arab Reform |
| `technology` 💻 | KISR |

**GCC 核心智库（tier=core_gcc，16个，直接通过评分）**

| 国家 | 智库 | 性质 | 议题 |
|------|------|------|------|
| 🇸🇦 沙特 | KAPSARC | official | energy, economy |
| 🇸🇦 沙特 | Rasanah IIIS | independent | security, politics |
| 🇸🇦 沙特 | King Faisal Center | official | politics, society, security |
| 🇦🇪 阿联酋 | EPC | official | politics, economy, security |
| 🇦🇪 阿联酋 | ECSSR | official | security, politics |
| 🇦🇪 阿联酋 | GRC | independent | politics, economy, security |
| 🇦🇪 阿联酋 | Bhuth | official | politics, economy |
| 🇦🇪 阿联酋 | Al Qasimi Foundation | official | society, economy |
| 🇦🇪 阿联酋 | Future Center | official | politics, security, economy |
| 🇶🇦 卡塔尔 | AJCS | official | politics, security, society |
| 🇶🇦 卡塔尔 | Brookings Doha | university | politics, economy, security |
| 🇶🇦 卡塔尔 | Doha Institute | university | politics, society, security |
| 🇰🇼 科威特 | API | official | economy |
| 🇰🇼 科威特 | KISR | official | energy, technology, economy |
| 🇧🇭 巴林 | Derasat | official | security, energy, economy |
| 🇴🇲 阿曼 | Tawasul | independent | politics, economy |

**泛 MENA 智库（tier=pan_mena，4个，GCC 专题页直接通过 / 首页需关键词评分 ≥ 3）**

| 国家 | 智库 | 抓取方式 | 性质 | 议题 |
|------|------|---------|------|------|
| 🇱🇧 黎巴嫩 | Carnegie MEC | deep_topic + Playwright | independent | politics, security |
| 🇪🇬 埃及 | Al-Ahram Center | 首页 + 关键词评分 | official | politics, security |
| 🇹🇷 土耳其 | Al Sharq Forum | deep_topic 国别标签页 | independent | politics, society |
| 🇫🇷 法国 | Arab Reform Initiative | deep_topic 国别标签页 | independent | politics, society |

**域外英美智库（tier=pan_mena，9个，GCC/MENA 专题页或关键词评分）**

| 国家 | 智库 | 性质 | 议题 |
|------|------|------|------|
| 🇺🇸 美国 | AGSIW | independent | politics, economy, security |
| 🇺🇸 美国 | MEI | independent | politics, security, economy |
| 🇺🇸 美国 | CSIS | independent | energy, security, economy |
| 🇺🇸 美国 | Atlantic Council | independent | security, politics, economy |
| 🇺🇸 美国 | Baker Institute | university | energy, economy |
| 🇺🇸 美国 | Wilson Center | official | politics, economy |
| 🇬🇧 英国 | Chatham House | independent | politics, security, economy |
| 🇬🇧 英国 | OIES | university | energy |
| 🇬🇧 英国 | IISS | independent | security, politics |

---

## Google Drive + Colab 协同

项目已内置 `notebooks/GCC_Scraper_Colab.ipynb`，团队成员无需本地配置 Python 环境，通过浏览器即可运行完整抓取流程。

### 首次上传（项目负责人操作一次）

1. 将整个 `GccScraper/` 文件夹上传至 Google Drive（建议放在 `我的云端硬盘` 根目录）
2. 用 Google Drive 打开 `notebooks/GCC_Scraper_Colab.ipynb`，选择 **用 Google Colab 打开**

### 团队成员使用流程

```
打开 Colab 笔记本
    │
    ▼  Step 1：挂载 Google Drive（授权一次）
    │
    ▼  Step 2：安装依赖（首次约 2–3 分钟）
    │
    ▼  Step 3：配置 API Key（推荐存入 Colab Secrets，左侧 🔑 图标）
    │
    ▼  Step 4：选择模式运行（日报/周报/月报/单国调试）
    │
    ▼  Step 5：在笔记本内预览 Markdown 简报 / 从 Drive 下载 PDF
```

### API Key 安全配置（Colab Secrets）

不要将 Key 直接写入笔记本代码（防止共享后泄露）。使用 Colab Secrets：

1. Colab 左侧栏点击 **🔑 Secrets**
2. 添加名称 `DEEPSEEK_API_KEY`，值填你的 Key，开启"笔记本访问权限"
3. 笔记本 Step 3 会自动读取，无需手动粘贴

| Secret 名称 | 用途 |
|------------|------|
| `DEEPSEEK_API_KEY` | DeepSeek AI（默认） |
| `ANTHROPIC_API_KEY` | Anthropic Claude（可选） |
| `FEISHU_APP_ID` | 飞书同步（可选） |
| `FEISHU_APP_SECRET` | 飞书同步（可选） |
| `FEISHU_APP_TOKEN` | 飞书同步（可选） |
| `FEISHU_TABLE_ID` | 飞书同步（可选） |
| `AI_BRIEF_EMAIL_TO` | AI简报PDF收件邮箱（可选） |
| `AI_BRIEF_EMAIL_FROM` | 发件邮箱（可选） |
| `AI_BRIEF_SMTP_HOST` | SMTP服务器地址（可选） |
| `AI_BRIEF_SMTP_PORT` | SMTP端口，常用 `587` 或 `465`（可选） |
| `AI_BRIEF_SMTP_USER` | SMTP登录账号（可选） |
| `AI_BRIEF_SMTP_PASSWORD` | SMTP密码或应用专用密码（可选） |

### 输出文件位置

运行完成后，结果文件自动保存在 Google Drive 的 `GccScraper/output/` 中，团队成员均可直接访问。

---

## 定时任务配置

### macOS / Linux（crontab）

```bash
# 编辑 crontab
crontab -e

# 每周一早上 8 点运行近 7 天 AI 简报 + 飞书同步
0 8 * * 1 cd /path/to/GccScraper && \
    /usr/bin/python3 gcc_thinktank_scraper_v2.py --ai --days 7 --no-dedup --dry-run-keywords >> logs/scraper.log 2>&1 && \
    /usr/bin/python3 feishu_sync.py >> logs/feishu.log 2>&1
```

### Windows（任务计划程序）

使用 `setup.bat` 或 `test_run.bat` 进行手动测试，正式定时任务建议在 Linux 服务器上运行。

### GitHub Actions（推荐云端运行）

仓库已提供 `.github/workflows/gcc_weekly_brief.yml`，默认在北京时间每周一 08:00 自动运行。核心配置如下：

```yaml
name: GCC Weekly AI Brief

on:
  schedule:
    - cron: "0 0 * * 1"   # UTC 周一 00:00 = 北京时间周一 08:00
  workflow_dispatch:

jobs:
  scrape:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: python -m pip install -r requirements.txt
      - run: python -m playwright install --with-deps chromium
      - run: python gcc_thinktank_scraper_v2.py --ai --days 7 --no-dedup --dry-run-keywords --output-dir output
        env:
          DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}
          AI_BRIEF_EMAIL_TO: ${{ secrets.AI_BRIEF_EMAIL_TO }}
          AI_BRIEF_EMAIL_FROM: ${{ secrets.AI_BRIEF_EMAIL_FROM }}
          AI_BRIEF_SMTP_HOST: ${{ secrets.AI_BRIEF_SMTP_HOST }}
          AI_BRIEF_SMTP_PORT: ${{ secrets.AI_BRIEF_SMTP_PORT }}
          AI_BRIEF_SMTP_USER: ${{ secrets.AI_BRIEF_SMTP_USER }}
          AI_BRIEF_SMTP_PASSWORD: ${{ secrets.AI_BRIEF_SMTP_PASSWORD }}
      - run: python feishu_sync.py --auto
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

完整运行手册见 [docs/定时自动运行与简报发布方案.md](docs/定时自动运行与简报发布方案.md)。

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

在 `think_tanks.yaml` 中新增一项，用浏览器 F12 找到文章卡片的 CSS 选择器。合规规则仍需同步写入 `compliance_rules.yaml`：

```yaml
- name: 智库全名
  country: Saudi Arabia              # 需与 --countries 参数保持一致
  tier: core_gcc                     # core_gcc 或 pan_mena
  region: gcc                        # gcc / mena / western
  org_type: official                 # official / university / independent
  topics:
  - energy
  - economy
  base_url: https://example.com
  pages:
  - /publications/
  rss_feeds:
  - https://example.com/feed/        # 有 RSS 优先用 RSS
  deep_topic: true                   # 可选：专题页默认通过来源层
  use_playwright: true               # 可选：SPA 站点需要 JS 渲染
  selectors:
    article: article, .card          # 文章卡片容器
    title: h2 a, h3 a                # 标题链接
    link: a[href]
    snippet: p, .excerpt             # 摘要
    date: time, .date                # 日期
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
