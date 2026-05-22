# GCC 项目不可直接爬取网站及替代访问路径报告

生成日期：2026-05-21  
依据文件：
- `/Users/jungle/Desktop/期刊信源_ToS合规检查报告.docx`
- `/Users/jungle/Desktop/ToS_合规判断_前30.csv`

## 一、结论摘要

基于已完成 ToS 合规判断的前 30 个网站，其中 9 个网站被判定为“明确禁止网络爬虫/自动化抓取”，另有 1 个网站虽然未明文禁止 robots，但要求自动化软件或批量下载事先获批。

我的判断是：这些网站不应纳入常规全文爬虫任务，也不应通过模拟浏览器、绕过反爬、批量下载或规避付费墙等方式获取正文。更稳妥的路径是将其拆成两层处理：

| 层级 | 建议做法 | 可获取内容 |
|---|---|---|
| 发现层 | 使用 Crossref、OpenAlex、Unpaywall、RePEc、官方 newsletter/RSS、邮件提醒等合规渠道 | 标题、作者、日期、DOI、摘要、链接、OA 状态 |
| 正文层 | 仅在开放获取、机构订阅授权、出版社 TDM API、JSTOR dataset、书面许可等路径下获取 | 合法授权范围内的正文、XML、PDF 或数据集 |

不建议使用的路径包括：绕过付费墙、抓缓存/镜像、模拟登录、规避反爬、使用盗版全文源、以技术可行为理由批量抓取官网正文。

## 二、明确禁止爬虫的网站

| 序号 | 网站 | 网站链接 | ToS 链接 | 合规判定 |
|---:|---|---|---|---|
| 1 | International Organization (Cambridge) | [访问](https://www.cambridge.org/core/journals/international-organization) | [ToS](https://www.cambridge.org/legal/website-terms-of-use) | 明确禁止爬虫 |
| 2 | RIPE (Taylor & Francis / Informa) | [访问](https://www.tandfonline.com/journals/rrip20) | [ToS](https://www.tandfonline.com/terms-and-conditions) | 明确禁止爬虫 |
| 3 | International Security (MIT Press) | [访问](https://direct.mit.edu/isec) | [ToS](https://mitpress.mit.edu/terms-use/) | 明确禁止自动化访问 |
| 4 | AER (American Economic Association) | [访问](https://www.aeaweb.org/journals/aer) | [ToS](https://www.aeaweb.org/terms-of-service/site) | 明确禁止自动化收集 |
| 5 | SMJ (Strategic Management Journal / Wiley) | [访问](https://onlinelibrary.wiley.com/journal/10970266) | [ToS](https://onlinelibrary.wiley.com/terms-and-conditions) | 明确禁止 scraper / crawler / robot |
| 6 | ASQ (via JSTOR) | [访问](https://www.jstor.org/journal/admisciequar) | [ToS](https://about.jstor.org/terms/) | 明确禁止自动下载、抓取、抽取 |
| 7 | Brookings AI Initiative | [访问](https://www.brookings.edu/artificial-intelligence/) | [ToS](https://www.brookings.edu/terms-of-use/) | 明确禁止 spiders / robots 收集邮箱；站点内容商业使用受限 |
| 8 | PIIE (Peterson Institute for International Economics) | [访问](https://www.piie.com/) | [ToS](https://www.piie.com/terms-use) | 明确禁止 page scrape / robot / spider |
| 9 | Atlantic Council GeoEconomics Center | [访问](https://www.atlanticcouncil.org/programs/geoeconomics-center/) | [ToS](https://www.atlanticcouncil.org/terms-of-use/) | 明确禁止自动化系统访问，公开搜索引擎索引除外 |

## 三、需事先审批的网站

| 序号 | 网站 | 网站链接 | ToS 链接 | 合规判定 |
|---:|---|---|---|---|
| 1 | JPE (Journal of Political Economy / UChicago Press) | [访问](https://www.journals.uchicago.edu/journals/jpe) | [ToS](https://www.journals.uchicago.edu/t-and-c) | 未明禁 robots，但自动化软件或批量下载须事先获批 |

## 四、替代访问路径判断

| 网站 | 是否有替代路径 | 建议替代路径 | 适合获取的内容 |
|---|---:|---|---|
| Cambridge / International Organization | 有 | Cambridge 允许在有合法访问权限的前提下进行非商业 TDM；如需大量下载或 XML 格式，应联系 `openresearch@cambridge.org`；也可用 Crossref、OpenAlex、Unpaywall 查 DOI、元数据和 OA 版本 | 元数据、OA 正文、经授权正文或 XML |
| Taylor & Francis / RIPE | 有 | 订阅机构可在非商业基础上做 TDM；商业 TDM 需另行报价或授权；建议先联系 Taylor & Francis TDM 支持 | 授权 TDM 正文、元数据、OA 版本 |
| MIT Press / International Security | 有但受限 | 使用 MIT Press Direct 上明确开放访问的内容、机构订阅、手动访问；不要自动化访问官网；可通过 Crossref、OpenAlex、Unpaywall 查询 OA 版本 | OA 正文、订阅正文、元数据 |
| AEA / AER | 有但偏发现层 | AEA 官方邮件提醒可跟踪新文章；RePEc/IDEAS 可获取 AER 目录和元数据；正文需依赖机构订阅、开放版本或作者工作论文版本 | 目录、元数据、部分作者版本 |
| Wiley / SMJ | 有 | Wiley TDM 通常通过 Crossref TDM/API token 与 Wiley TDM 协议实现；也可使用机构订阅、OA 或 self-archived 版本 | 授权 TDM 正文、OA 正文、元数据 |
| JSTOR / ASQ | 有，且较明确 | JSTOR Text Analysis Support 可下载书目元数据，并申请 full-text dataset；但不得用于训练或增强 AI 模型，也不得创建替代 JSTOR 的产品或数据库 | 研究/教学用数据集、元数据 |
| Brookings | 有但不建议程序化抓正文 | 官网人工访问；订阅 Brookings Brief/newsletters；若需批量或商业化使用，应申请书面授权 | 人工阅读、链接和标题提醒 |
| PIIE | 有但需谨慎 | 官网允许个人用途打印/下载；PIIE Insider newsletter 可做更新提醒；部分专家页有 RSS；分发、商业使用或程序化访问需单独许可 | 人工阅读、newsletter/RSS 发现 |
| Atlantic Council | 有但不建议程序化抓正文 | 使用 newsletters、官网人工访问、ACTV、Podcast、社媒更新；批量获取正文建议先申请许可 | 人工阅读、邮件/社媒/播客提醒 |
| JPE / UChicago Press | 有但需审批 | 学术 TDM 可行，但若使用自动化软件或批量下载正文，须先向 Press 申请批准；RePEc/IDEAS 可做目录和元数据发现 | 元数据、经批准的 TDM 正文 |

## 五、建议落地策略

### 1. 在信源台账中增加合规字段

建议对上述网站统一标注：

| 字段 | 建议值 |
|---|---|
| `crawler_allowed` | `false` |
| `fulltext_scraping_allowed` | `false` |
| `metadata_allowed_path` | `Crossref/OpenAlex/Unpaywall/RePEc/newsletter/RSS` |
| `fulltext_allowed_path` | `OA / subscribed access / TDM API / dataset request / written permission` |
| `requires_permission` | 对 JPE、商业 TDM、批量下载、正文复用等场景标记为 `true` |

### 2. 在采集系统中拆分“发现”和“全文”

对这些站点不建议直接进入全文抓取队列。更稳妥的流程如下：

1. 用合规发现源获取文章清单：标题、作者、日期、DOI、URL、来源。
2. 用 Unpaywall 或 OpenAlex 判断是否存在 OA 版本。
3. 对有 OA 版本的文章，优先访问 OA 链接，而不是抓原站受限页面。
4. 对无 OA 版本但有订阅或 TDM 权限的文章，通过授权 API、出版社提供的数据集或机构订阅流程获取。
5. 对仍无法合规获取的文章，只保留元数据和链接，不抓正文。

### 3. 报告生成时的处理建议

| 场景 | 建议处理 |
|---|---|
| 仅需知道新文章 | 使用元数据、RSS、邮件提醒、目录页、Crossref/OpenAlex |
| 需要摘要 | 优先使用公开摘要；若无公开摘要，仅保留标题和链接 |
| 需要正文分析 | 只处理 OA、授权 TDM、JSTOR dataset 或机构订阅许可范围内的正文 |
| 需要 AI 训练 | 不使用这些站点正文，除非许可条款明示允许 |
| 需要商业用途 | 逐站申请商业授权，不按默认可用处理 |

## 六、参考来源

- [Cambridge Core Text and Data Mining Policy](https://www.cambridge.org/core/services/open-research-policies/text-and-data-mining)
- [Taylor & Francis Text and Data Mining Policy](https://taylorandfrancis.com/our-policies/textanddatamining/)
- [JSTOR Text Analysis Support](https://support.jstor.org/hc/en-us/articles/32479181127575-JSTOR-Text-Analysis-Support-Getting-Started)
- [Crossref REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/)
- [OpenAlex Works API](https://developers.openalex.org/api-reference/works)
- [AEA Email Notifications](https://www.aeaweb.org/notify/)
- [PIIE Terms of Use](https://www.piie.com/terms-use)
- [Atlantic Council Newsletters / Get Involved](https://www.atlanticcouncil.org/get-involved/)

## 七、总判断

上述网站应被视为“不可直接爬取官网正文”的高风险源。它们仍可作为研究发现源或参考源使用，但正文获取必须走明确授权路径。对于 GCC 项目的自动化采集流程，建议将这些站点默认排除在常规爬虫之外，仅保留合规发现、人工阅读、OA 版本识别和授权 TDM 四类路径。
