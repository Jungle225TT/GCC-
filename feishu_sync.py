#!/usr/bin/env python3
"""
GCC智库抓取系统 — 飞书多维表格对接模块
自动将 JSON 抓取结果推送到飞书多维表格，支持增量更新（URL去重）

依赖: pip install requests

使用前准备（一次性）：
  1. 登录 https://open.feishu.cn → 创建企业自建应用
  2. 获取 App ID 和 App Secret
  3. 应用权限中开启：bitable:app（多维表格全部权限）
  4. 发布应用版本
  5. 在飞书中创建一个多维表格，将应用机器人添加为协作者
  6. 从表格URL中获取 app_token（sh开头）和 table_id
  7. 填入下方配置或设置环境变量

使用：
  # 首次运行（自动创建字段 + 导入数据）
  python feishu_sync.py output/gcc_research_20260414_1035.json

  # 与抓取脚本联动
  python gcc_thinktank_scraper_v2.py --ai --playwright && python feishu_sync.py output/gcc_research_*.json

  # 设为定时任务后全自动运行
  python feishu_sync.py output/gcc_research_*.json --auto
"""

import json
import time
import sys
import os
import glob
import requests
from pathlib import Path
from datetime import datetime

# ============================================================
# 配置（优先读环境变量，也可直接填写）
# ============================================================
FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID", "")          # 飞书应用 App ID
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "")   # 飞书应用 App Secret
FEISHU_APP_TOKEN = os.environ.get("FEISHU_APP_TOKEN", "")     # 多维表格 app_token（URL中sh开头的部分）
FEISHU_TABLE_ID = os.environ.get("FEISHU_TABLE_ID", "")       # 数据表 table_id

BASE_URL = "https://open.feishu.cn/open-apis"


# ============================================================
# 飞书 API 封装
# ============================================================

def get_tenant_token():
    """获取 tenant_access_token"""
    url = f"{BASE_URL}/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={
        "app_id": FEISHU_APP_ID,
        "app_secret": FEISHU_APP_SECRET,
    })
    data = resp.json()
    if data.get("code") != 0:
        print(f"❌ 获取token失败: {data.get('msg')}")
        print(f"   请检查 FEISHU_APP_ID 和 FEISHU_APP_SECRET 是否正确")
        return None
    token = data["tenant_access_token"]
    print(f"✅ 获取飞书token成功（有效期2小时）")
    return token


def _headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }


def list_fields(token):
    """列出多维表格的所有字段"""
    url = f"{BASE_URL}/bitable/v1/apps/{FEISHU_APP_TOKEN}/tables/{FEISHU_TABLE_ID}/fields"
    resp = requests.get(url, headers=_headers(token))
    data = resp.json()
    if data.get("code") != 0:
        print(f"❌ 获取字段列表失败: {data.get('msg')}")
        return []
    return data.get("data", {}).get("items", [])


def create_field(token, field_name, field_type, property_dict=None):
    """创建字段
    field_type: 1=文本, 2=数字, 3=单选, 5=日期, 15=超链接
    """
    url = f"{BASE_URL}/bitable/v1/apps/{FEISHU_APP_TOKEN}/tables/{FEISHU_TABLE_ID}/fields"
    body = {"field_name": field_name, "type": field_type}
    if property_dict:
        body["property"] = property_dict
    resp = requests.post(url, headers=_headers(token), json=body)
    data = resp.json()
    if data.get("code") == 0:
        print(f"  ✅ 创建字段: {field_name}")
    else:
        print(f"  ⚠️  字段 {field_name}: {data.get('msg')}")


def ensure_fields(token):
    """确保多维表格有所需的字段"""
    existing = list_fields(token)
    existing_names = {f["field_name"] for f in existing}

    # 需要的字段定义：(名称, 类型, 属性)
    # 1=文本, 2=数字, 3=单选, 5=日期, 15=超链接
    required_fields = [
        ("发布日期", 1, None),              # 文本（日期格式不统一，用文本更灵活）
        ("平台", 1, None),                  # 文本
        ("标题", 1, None),                  # 文本
        ("中文标题", 1, None),              # 文本
        ("链接", 15, None),                 # 超链接
        ("优先级", 3, {"options": [         # 单选
            {"name": "⭐ 优先阅读"},
            {"name": "📄 常规"},
            {"name": "📋 简讯"},
        ]}),
        ("内容类型", 3, {"options": [       # 单选
            {"name": "high"},
            {"name": "medium"},
            {"name": "low"},
            {"name": "unknown"},
        ]}),
        ("数据来源", 3, {"options": [       # 单选
            {"name": "RSS"},
            {"name": "HTML"},
        ]}),
        ("国家", 1, None),                  # 文本
        ("摘要", 1, None),                  # 文本
        ("抓取时间", 1, None),              # 文本
    ]

    print(f"\n📋 检查字段（已有 {len(existing_names)} 个）...")
    created = 0
    for name, ftype, prop in required_fields:
        if name not in existing_names:
            create_field(token, name, ftype, prop)
            created += 1

    if created == 0:
        print(f"  所有字段已存在，无需创建")
    else:
        print(f"  新建了 {created} 个字段")


def list_existing_urls(token):
    """获取表格中已有的所有文章URL，用于去重"""
    urls = set()
    page_token = ""
    page_size = 500

    while True:
        url = f"{BASE_URL}/bitable/v1/apps/{FEISHU_APP_TOKEN}/tables/{FEISHU_TABLE_ID}/records"
        params = {
            "page_size": page_size,
            "field_names": '["链接"]',  # 只取链接字段，减少数据量
        }
        if page_token:
            params["page_token"] = page_token

        resp = requests.get(url, headers=_headers(token), params=params)
        data = resp.json()

        if data.get("code") != 0:
            print(f"  ⚠️  读取已有记录失败: {data.get('msg')}")
            break

        items = data.get("data", {}).get("items", [])
        for item in items:
            fields = item.get("fields", {})
            link_field = fields.get("链接")
            if isinstance(link_field, dict):
                urls.add(link_field.get("link", ""))
            elif isinstance(link_field, str):
                urls.add(link_field)

        has_more = data.get("data", {}).get("has_more", False)
        if not has_more:
            break
        page_token = data.get("data", {}).get("page_token", "")

    return urls


def batch_create_records(token, records, batch_size=100):
    """批量新增记录"""
    url = f"{BASE_URL}/bitable/v1/apps/{FEISHU_APP_TOKEN}/tables/{FEISHU_TABLE_ID}/records/batch_create"
    total = len(records)
    success = 0
    fail = 0

    for i in range(0, total, batch_size):
        batch = records[i:i + batch_size]
        body = {"records": [{"fields": r} for r in batch]}

        resp = requests.post(url, headers=_headers(token), json=body)
        data = resp.json()

        if data.get("code") == 0:
            success += len(batch)
            print(f"  ✅ 已写入 {success}/{total} 条", end="\r")
        else:
            fail += len(batch)
            print(f"\n  ❌ 批次写入失败: {data.get('msg')}")

        # 避免触发限频（飞书限制: 100次/分钟）
        if i + batch_size < total:
            time.sleep(1)

    print(f"\n  写入完成: {success} 成功, {fail} 失败")
    return success


# ============================================================
# JSON → 飞书记录转换
# ============================================================

def article_to_record(article, scraped_at=""):
    """将一篇文章转为飞书多维表格记录"""
    priority_map = {
        "priority_read": "⭐ 优先阅读",
        "normal": "📄 常规",
        "low": "📋 简讯",
    }

    return {
        "发布日期": article.get("date") or "-",
        "平台": article.get("source", ""),
        "标题": article.get("title", ""),
        "中文标题": article.get("title_cn") or "-",
        "链接": {
            "text": article.get("title", "")[:50],
            "link": article.get("url", ""),
        },
        "优先级": priority_map.get(article.get("priority", "normal"), "📄 常规"),
        "内容类型": article.get("content_type", "unknown"),
        "数据来源": "RSS" if article.get("fetch_method") == "rss" else "HTML",
        "国家": article.get("source_country", ""),
        "摘要": (article.get("snippet") or "")[:500],
        "抓取时间": scraped_at,
    }


# ============================================================
# 主流程
# ============================================================

def sync_to_feishu(json_path, auto_mode=False):
    """将 JSON 文件同步到飞书多维表格"""

    # 检查配置
    missing = []
    if not FEISHU_APP_ID: missing.append("FEISHU_APP_ID")
    if not FEISHU_APP_SECRET: missing.append("FEISHU_APP_SECRET")
    if not FEISHU_APP_TOKEN: missing.append("FEISHU_APP_TOKEN")
    if not FEISHU_TABLE_ID: missing.append("FEISHU_TABLE_ID")

    if missing:
        print("❌ 缺少飞书配置:")
        for m in missing:
            print(f"   export {m}=\"你的值\"")
        print(f"\n📖 配置指南见脚本顶部注释")
        return False

    # 读取 JSON
    print(f"\n📂 读取: {json_path}")
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    articles = data.get("articles", [])
    scraped_at = data.get("metadata", {}).get("scraped_at", "")[:16]
    print(f"  共 {len(articles)} 篇文章, 抓取时间: {scraped_at}")

    if not articles:
        print("⚠️  无文章，跳过")
        return True

    # 获取 token
    token = get_tenant_token()
    if not token:
        return False

    # 确保字段
    ensure_fields(token)

    # 增量去重
    print(f"\n🔍 检查已有记录（增量去重）...")
    existing_urls = list_existing_urls(token)
    print(f"  表格中已有 {len(existing_urls)} 条记录")

    new_articles = [a for a in articles if a.get("url", "") not in existing_urls]
    skipped = len(articles) - len(new_articles)
    print(f"  新增: {len(new_articles)} 篇 | 已存在跳过: {skipped} 篇")

    if not new_articles:
        print("\n✅ 无新文章需要同步")
        return True

    # 转换并写入
    print(f"\n📤 开始写入飞书多维表格...")
    records = [article_to_record(a, scraped_at) for a in new_articles]
    success = batch_create_records(token, records)

    print(f"\n{'='*60}")
    print(f"✅ 飞书同步完成")
    print(f"  新增: {success} 条")
    print(f"  跳过: {skipped} 条（已存在）")
    print(f"  表格地址: https://你的企业.feishu.cn/base/{FEISHU_APP_TOKEN}")
    print(f"{'='*60}")
    return True


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="GCC智库 → 飞书多维表格同步")
    parser.add_argument("json_files", nargs="*", help="JSON文件路径（支持通配符）")
    parser.add_argument("--auto", action="store_true", help="自动模式（无交互）")
    args = parser.parse_args()

    # 展开通配符
    files = []
    for pattern in (args.json_files or []):
        files.extend(glob.glob(pattern))

    # 自动查找最新的
    if not files:
        output_dir = Path("./output")
        if output_dir.exists():
            files = sorted(output_dir.glob("gcc_research_*.json"), reverse=True)
            if files:
                files = [str(files[0])]
                print(f"🔍 自动找到最新: {files[0]}")

    if not files:
        print("❌ 未找到JSON文件")
        print("   用法: python feishu_sync.py output/gcc_research_*.json")
        sys.exit(1)

    # 同步每个文件
    for f in sorted(set(str(x) for x in files)):
        if not Path(f).exists():
            print(f"⚠️  文件不存在: {f}")
            continue
        sync_to_feishu(f, args.auto)
