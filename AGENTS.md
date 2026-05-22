# GccScraper — Codex 指引

本文件为 Codex 在此项目中工作时的常驻上下文。详细架构记忆见 MEMORY.md。

---

## 项目概览

- **全名**：GCC智库研究抓取系统 v2.4.1
- **主入口**：`gcc_thinktank_scraper_v2.py`（核心逻辑在此）
- **智库信源配置**：`think_tanks.yaml`（29 个智库的 URL、RSS、栏目页和选择器）
- **关键词配置**：`keywords.yaml`（根目录，与主文件同级）
- **智库数量**：29 个（core_gcc 17 + pan_mena 12）

---

## 关键约定

### 相关性分层（两档，勿改回三档）
输出 Markdown 只有**两档**，不是三档：
- **强相关**（`topic_relevance_score >= 4.0`）：区块置顶，标题前加 `⭐`
- **中等相关**（`topic_relevance_score < 4.0`）：紧随其后

**Markdown 报告**实现位置：
- `_relevance_tier(score)` → `gcc_thinktank_scraper_v2.py:318`
- `_table_rows()` 中的 `⭐` 标记 → `:989`
- `export_markdown()` 默认分组 → `:1031`

**AI 简报**（`generate_ai_summary`）同样遵循两档：
- 文章排序：强相关全部在前，中等相关在后（tier 内各自按日期降序）
- 目录分两节：`⭐ 推荐阅读（强相关）` / `📄 中等相关`，header 显示各档篇数
- 章节标题后处理：`### [N]` → `### [⭐ N]`（强相关文章，索引 1 至 n_strong）
- PDF 渲染：STSong-Light 不支持 emoji，`_colored_symbols()` 在 `export_summary_pdf` 内将符号替换为带色圆点：
  - `⭐` → 红色 `●`（`#C0392B`，强相关）
  - `📄` → 蓝色 `●`（`#2980B9`，中等相关）
  - `_safe()` 和 `_with_links()` 均调用此函数，覆盖所有文本路径

### core_gcc 过滤规则
- `core_gcc` 智库自动赋分 99，`demote_words` 降权（-2）对其无效（97 >> 阈值 3）
- 要过滤 core_gcc 来源的噪音，**必须用 `hard_filter_words`**，不能用 `demote_words`
- `hard_filter_words` 在第三层 `classify_content_type` 中生效，对所有 tier 均有效

### keywords.yaml 三类词表
| 词表 | 触发层 | 检查范围 |
|------|--------|---------|
| `hard_filter_words` | 第三层，直接丢弃 | 标题 + URL |
| `demote_words` | 第二层，score -2 | 标题 + 摘要 |
| `title_only_demote_words` | 第二层，score -2 | **仅标题** |

### 去重机制
- **跨智库 in-memory 去重**：`run_scraper` 在 AI 筛选前按 URL 去重，防止同一文章被多个来源重复收录，`--no-dedup` 时同样生效
- **SQLite 增量去重**：`data/gcc_dedup.db`，过滤近 N 天已处理文章（本地无此目录，须加 `--no-dedup`）

### 本地运行注意
- 本地无 `data/` 目录，必须加 `--no-dedup`
- dry-run 输出目录建议用 `--output-dir` 指定，避免写入 `./output`

---

## 禁止事项

- 不要将相关性分层改回三档（优先/推荐/备查已废弃）
- 不要在 `demote_words` 里放需要对 core_gcc 生效的过滤词
- 不要在本地运行时省略 `--no-dedup`（会因缺少 data/ 报错）
- 不要修改 Notebook 里的导出逻辑（Notebook 只调主脚本子进程，无独立导出代码）

---

## 常用命令

```bash
# 本地 dry-run（关键词调参）
python3 gcc_thinktank_scraper_v2.py \
  --dry-run-keywords --no-dedup \
  --output-dir "/Users/jungle/Desktop/gcc_dryrun_output" \
  --max-per-tank 20

# 关键词回归测试
python3 scripts/test_keywords_funnel.py
```
