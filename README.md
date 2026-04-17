# GCC智库研究抓取系统 v2.1

> 成都创新金融研究院 — 姜亭汀 | 更新于 2026-04-17

自动抓取 21 个 GCC / 泛MENA 智库的最新研究文章，经四层漏斗筛选后输出 Markdown 报告、JSON 数据，并可选推送至飞书多维表格。

---

## 目录

1. [文件结构](#文件结构)
2. [环境准备](#环境准备)
3. [主抓取脚本：gcc_thinktank_scraper_v2.py](#主抓取脚本)
4. [评分阈值测试：scoring_test.py](#评分阈值测试)
5. [飞书同步：feishu_sync.py](#飞书同步)
6. [全文转PDF：fulltext_to_pdf.py](#全文转pdf)
7. [架构说明：四层漏斗 + 增量去重](#架构说明)
8. [定时任务配置](#定时任务配置)
9. [常见问题](#常见问题)

---

## 文件结构

```
GccScraper/
├── gcc_thinktank_scraper_v2.py   # 主抓取脚本（核心）
├── feishu_sync.py                # 将JSON结果推送到飞书多维表格
├── fulltext_to_pdf.py            # 全文抓取并输出PDF/HTML（AI训练数据）
├── scoring_test.py               # 关键词评分阈值对比测试工具
├── dedup.py                      # SQLite去重模块（供外部调用）
├── .gitignore                    # 忽略output/、*.db、.env等
├── output/                       # 主脚本输出目录（自动创建）
│   ├── gcc_research_YYYYMMDD_HHMM.md
│   ├── gcc_research_YYYYMMDD_HHMM.json
│   └── gcc_summary_YYYYMMDD_HHMM.md   # 仅 --ai 模式生成
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

**JS 渲染**（SPA 网站必须，如 EPC、Future Center）：

```bash
pip install playwright
playwright install chromium
```

**AI 功能**（翻译、筛选、研究简报）：

```bash
pip install anthropic
```

**全文PDF生成**（仅 fulltext_to_pdf.py 需要）：

```bash
pip install trafilatura reportlab
```

**飞书同步 + .env 支持**（仅 feishu_sync.py 需要）：

```bash
pip install python-dotenv
```

**一键安装全部依赖**：

```bash
pip install requests beautifulsoup4 feedparser playwright anthropic trafilatura reportlab python-dotenv
playwright install chromium
```

### 3. 配置 API Key

AI 功能需要 Anthropic API Key。**推荐用环境变量**，避免出现在 bash 历史记录中：

```bash
# macOS / Linux：加入 ~/.zshrc 或 ~/.bashrc
export ANTHROPIC_API_KEY="sk-ant-xxxxx..."

# 或者创建 .env 文件（已加入 .gitignore，不会被提交）
echo 'ANTHROPIC_API_KEY=sk-ant-xxxxx...' > .env
```

---

## 主抓取脚本

**文件：** `gcc_thinktank_scraper_v2.py`

### 功能

- 抓取 21 个智库的最新研究文章（HTML + RSS 双通道）
- 四层漏斗筛选（来源可信度 → 关键词评分 → 内容类型 → AI辅助）
- SQLite 增量去重（自动跳过上次已处理的文章）
- 可选：Claude Haiku 边界文章分类、标题批量翻译、Claude Sonnet 研究简报生成
- 输出 Markdown 报告 + JSON 数据

### 运行方式

**① 最简运行（无需任何配置）**

```bash
python gcc_thinktank_scraper_v2.py
```

仅用 requests 抓取，不调用 AI，结果写入 `./output/`。

---

**② 推荐：启用 Playwright + AI**

```bash
export ANTHROPIC_API_KEY="sk-ant-xxxxx..."
python gcc_thinktank_scraper_v2.py --playwright --ai
```

- `--playwright`：启用 Chromium 渲染 JS 页面，覆盖更多智库
- `--ai`：启用 Claude Haiku 边界文章分类 + 标题翻译 + Claude Sonnet 研究简报

---

**③ 只抓特定国家**

```bash
# 只抓 UAE 和沙特
python gcc_thinktank_scraper_v2.py --countries UAE "Saudi Arabia" --playwright --ai

# 只抓卡塔尔
python gcc_thinktank_scraper_v2.py --countries Qatar
```

`--countries` 支持多个值，用空格分隔，国家名需与 THINK_TANKS 配置中的 `country` 字段一致。

---

**④ 控制每站抓取量**

```bash
# 精读模式：每站最多 20 篇
python gcc_thinktank_scraper_v2.py --max-per-tank 20 --ai --playwright

# 全量模式：每站最多 100 篇
python gcc_thinktank_scraper_v2.py --max-per-tank 100
```

默认每站 50 篇，截取最新的。

---

**⑤ 调试模式**

```bash
# 显示每个候选条目（标题、URL、被过滤原因）
python gcc_thinktank_scraper_v2.py --countries UAE --playwright --debug
```

---

**⑥ 增量去重**

首次运行会自动创建 `gcc_dedup.db`，此后每次运行自动跳过已处理文章：

```bash
# 正常运行（默认启用去重）
python gcc_thinktank_scraper_v2.py --ai --playwright

# 禁用去重（每次全量处理）
python gcc_thinktank_scraper_v2.py --no-dedup

# 使用自定义数据库路径
python gcc_thinktank_scraper_v2.py --dedup-db /path/to/custom.db
```

### 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--countries` | 全部 | 只抓指定国家，可多个（空格分隔） |
| `--playwright` | 关闭 | 启用 Chromium JS 渲染 |
| `--ai` | 关闭 | 启用 AI 筛选 + 翻译 + 研究简报 |
| `--api-key` | 读环境变量 | Anthropic API Key（建议用环境变量代替） |
| `--output-dir` | `./output` | 输出目录 |
| `--max-per-tank` | 50 | 每个智库最多保留篇数 |
| `--no-dedup` | 关闭 | 禁用 SQLite 增量去重 |
| `--dedup-db` | `gcc_dedup.db` | 去重数据库路径 |
| `--debug` | 关闭 | 显示调试日志 |

### 输出文件

运行后在 `./output/` 目录下生成：

| 文件 | 内容 |
|------|------|
| `gcc_research_YYYYMMDD_HHMM.md` | Markdown 报告，按优先级（⭐/📄/📋）分组 |
| `gcc_research_YYYYMMDD_HHMM.json` | 完整数据，可导入飞书/Notion |
| `gcc_summary_YYYYMMDD_HHMM.md` | AI 研究简报（仅 `--ai` 模式） |

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
python scoring_test.py --json output/gcc_research_20260417_1000.json
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
# 创建 .env 文件（已加入 .gitignore，不会被提交）
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
python feishu_sync.py output/gcc_research_20260417_1000.json
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
| 发布日期 | 文本 | 文章发布日期 |
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
┌─────────────────────────────────┐
│  第一层：来源可信度              │
│  core_gcc 智库 → 直接通过（99分）│
│  pan_mena 智库 → 进入第二层      │
└──────────────┬──────────────────┘
               ▼
┌─────────────────────────────────┐
│  第二层：关键词评分              │
│  GCC / 海合会 = 3分             │
│  国家名（UAE/Saudi...）= 2分    │
│  Gulf / MENA / 中东 = 1分      │
│  标题命中 ×2                    │
│  总分 ≥ 3 → 通过                │
└──────────────┬──────────────────┘
               ▼
┌─────────────────────────────────┐
│  第三层：内容类型识别            │
│  排除：Register / Vacancy...    │
│  高价值：report / analysis → ⭐  │
│  中价值：blog / opinion → 📄    │
│  低价值：newsletter → 📋        │
└──────────────┬──────────────────┘
               ▼
┌─────────────────────────────────┐
│  第四层：AI 辅助（可选）         │
│  评分 2–4 的边界文章             │
│  → Claude Haiku 快速二分类      │
└──────────────┬──────────────────┘
               ▼
          最终文章列表
```

### 增量去重机制

每次运行在翻译/导出前自动过滤：

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

### 数据流

```
gcc_thinktank_scraper_v2.py
        │
        ├─ output/gcc_research_*.json  ──→  feishu_sync.py  ──→  飞书多维表格
        ├─ output/gcc_research_*.md    ──→  直接阅读 / 分发
        └─ output/gcc_summary_*.md     ──→  研究团队内部简报
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

**泛 MENA 智库（4个，需关键词评分 ≥ 3）**

| 国家 | 智库 |
|------|------|
| 🇱🇧 黎巴嫩 | Carnegie Middle East Center |
| 🇪🇬 埃及 | Al-Ahram Center |
| 🇹🇷 土耳其 | Al Sharq Forum |
| 🇫🇷 法国 | Arab Reform Initiative |

---

## 定时任务配置

### macOS / Linux（crontab）

```bash
# 编辑 crontab
crontab -e

# 每天早上 8 点运行全量抓取 + 飞书同步
0 8 * * * cd /path/to/GccScraper && \
    /usr/bin/python3 gcc_thinktank_scraper_v2.py --playwright --ai >> logs/scraper.log 2>&1 && \
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
      - run: pip install requests beautifulsoup4 feedparser playwright anthropic python-dotenv
      - run: playwright install chromium
      - run: python gcc_thinktank_scraper_v2.py --playwright --ai
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
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

| 功能 | 使用模型 | 估算成本 |
|------|---------|---------|
| 边界文章分类（20篇） | Claude Haiku | ~$0.001 |
| 标题批量翻译（100篇） | Claude Haiku | ~$0.005 |
| 研究简报生成（1次） | Claude Sonnet | ~$0.01 |

每日运行一次全量抓取 + AI 的总成本通常在 **$0.02 以内**。

### Q：当天运行后再次运行，显示"去重过滤了 N 篇，剩余 0 篇"？

这是正常的去重行为：当天已处理的文章 URL 都记录在 `gcc_dedup.db`，同一天再次运行会过滤掉全部已见文章。

**解决方案：**

```bash
# 方案1：直接删除数据库，下次运行重建（最彻底）
rm gcc_dedup.db
python gcc_thinktank_scraper_v2.py --ai

# 方案2：本次跳过去重，不影响数据库（推荐）
python gcc_thinktank_scraper_v2.py --no-dedup --ai

# 方案3：彻底关闭去重窗口（每次都全量处理）
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
