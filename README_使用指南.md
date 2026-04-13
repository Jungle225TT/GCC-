# GCC智库研究抓取系统 v2.0 — 使用指南

> 成都创新金融研究院 | 2026-04-13

## 快速开始

### 1. 安装依赖

```bash
pip install requests beautifulsoup4 playwright anthropic
playwright install chromium
```

### 2. 基础运行（仅 requests，无需其他配置）

```bash
python gcc_thinktank_scraper_v2.py
```

### 3. 推荐运行方式（Playwright + AI）

```bash
# 设置 API Key
export ANTHROPIC_API_KEY="sk-ant-xxx..."

# 全量抓取 + JS渲染 + AI筛选汇总
python gcc_thinktank_scraper_v2.py --playwright --ai

# 只抓 UAE 和沙特的智库
python gcc_thinktank_scraper_v2.py --countries UAE "Saudi Arabia" --playwright

# 调试模式（看到每个候选条目）
python gcc_thinktank_scraper_v2.py --countries UAE --playwright --debug
```

### 4. 输出文件

运行后在 `./output/` 目录下生成：

| 文件 | 用途 |
|------|------|
| `gcc_research_YYYYMMDD_HHMM.md` | Markdown 报告，按优先级分组，便于快速浏览 |
| `gcc_research_YYYYMMDD_HHMM.json` | JSON 数据，便于程序化处理或导入其他平台 |
| `gcc_summary_YYYYMMDD_HHMM.md` | AI 生成的中文研究简报（需 --ai 参数） |

---

## 四层漏斗筛选逻辑

```
原始文章
  │
  ▼
┌─────────────────────────────┐
│ 第一层：来源可信度            │
│ 核心GCC智库 → 直接通过        │
│ 泛MENA智库 → 需要关键词评分   │
└──────────────┬──────────────┘
               ▼
┌─────────────────────────────┐
│ 第二层：关键词评分            │
│ 强信号(GCC)=3分              │
│ 国家名=2分 | 弱信号=1分      │
│ 标题权重 ×2                  │
│ 总分≥3 → 通过                │
└──────────────┬──────────────┘
               ▼
┌─────────────────────────────┐
│ 第三层：内容类型识别          │
│ 排除: Register/Join/Vacancy  │
│ 高价值: report/analysis →⭐  │
│ 中价值: blog/opinion → 📄    │
│ 低价值: newsletter → 📋      │
└──────────────┬──────────────┘
               ▼
┌─────────────────────────────┐
│ 第四层：AI辅助（可选）        │
│ 边界模糊文章 → Claude Haiku  │
│ 快速分类，成本极低            │
└──────────────┬──────────────┘
               ▼
         最终结果
```

---

## 覆盖的智库列表（21个）

### 核心GCC智库（17个，默认相关）

| 国家 | 智库 |
|------|------|
| 🇸🇦 沙特 | KAPSARC, Rasanah, King Faisal Center |
| 🇦🇪 阿联酋 | EPC, ECSSR, GRC, Bhuth, Al Qasimi Foundation, Future Center |
| 🇶🇦 卡塔尔 | AJCS, Brookings Doha, Doha Institute |
| 🇰🇼 科威特 | API, KISR |
| 🇧🇭 巴林 | Derasat |
| 🇴🇲 阿曼 | Tawasul |

### 泛MENA智库（4个，需关键词评分）

| 国家 | 智库 |
|------|------|
| 🇱🇧 黎巴嫩 | Carnegie Middle East Center |
| 🇪🇬 埃及 | Al-Ahram Center |
| 🇹🇷 土耳其 | Al Sharq Forum |
| 🇫🇷 法国 | Arab Reform Initiative |

---

## 常见问题

### Q: 某个网站抓不到内容？
**A:** 大部分情况是因为JS动态渲染。加 `--playwright` 参数即可。如果还不行，用 `--debug` 看具体错误。

### Q: 如何添加新的智库？
**A:** 在 `THINK_TANKS` 列表中添加一个字典，按照现有格式填写。关键是要用浏览器 F12 找到正确的 CSS 选择器。

### Q: 如何调整筛选阈值？
**A:** 修改脚本顶部的常量：
- `RELEVANCE_THRESHOLD = 3` — 关键词评分阈值
- `SCORE_STRONG/COUNTRY/WEAK` — 各级关键词分值
- `TITLE_MULTIPLIER = 2` — 标题权重倍数

### Q: AI 功能花多少钱？
**A:** Claude Haiku 极便宜，20篇文章的分类大约 $0.001。AI汇总用 Sonnet 大约 $0.01/次。

### Q: 输出格式怎么选？
**A:** 
- **日常浏览** → Markdown 报告，用 VS Code / Typora 打开
- **团队协作** → JSON 导入飞书多维表格或 Notion 数据库
- **定期报告** → AI 生成的简报（`--ai`），可直接转发给团队

---

## 后续扩展建议

1. **定时任务**: 用 crontab 或 GitHub Actions 每日自动抓取
2. **飞书集成**: 用飞书 Open API 将 JSON 数据写入多维表格
3. **增量抓取**: 记录已抓取的 URL，避免重复
4. **RSS 订阅**: 部分智库提供 RSS，可作为补充数据源
5. **全文抓取**: 对高优先级文章，自动抓取全文用于深度分析
