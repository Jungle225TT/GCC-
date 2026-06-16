#!/usr/bin/env python3
"""Regenerate the AI summary from an exported gcc_research_*.json file."""

import argparse
import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gcc_thinktank_scraper_v2 import (
    Article,
    apply_keyword_demotion,
    apply_source_relevance_adjustments,
    compute_keyword_score,
    compute_topic_relevance_score,
    export_summary_pdf,
    generate_ai_summary,
)


def load_filtered_out(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            rows.append(
                {
                    "title": row.get("title", ""),
                    "url": row.get("url", ""),
                    "source": row.get("source", ""),
                    "filter_hit": row.get("filter_word", ""),
                }
            )
    return rows


def refresh_core_gcc_relevance_scores(articles: list[Article]) -> int:
    """Refresh saved core_gcc relevance scores using the current keyword rules."""
    changed = 0
    for article in articles:
        if article.source_tier != "core_gcc":
            continue
        before = article.topic_relevance_score
        actual_score_raw, actual_matches = compute_keyword_score(article.title, article.snippet or "")
        actual_score, demote_hits = apply_keyword_demotion(actual_score_raw, article.title, article.snippet or "")
        if demote_hits:
            actual_matches = actual_matches + [
                f"{hit}(降权,-2)" for hit in demote_hits
            ]
        article.keyword_score = 99.0
        article.matched_keywords = ["core_gcc_auto_pass"] + actual_matches
        article.topic_relevance_score = compute_topic_relevance_score(
            article.keyword_score,
            article.content_type,
            source_tier=article.source_tier,
            actual_keyword_score=actual_score,
        )
        apply_source_relevance_adjustments(article, {}, actual_score, actual_matches)
        if article.topic_relevance_score != before:
            changed += 1
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description="Regenerate GCC AI summary from JSON export")
    parser.add_argument("json_path", help="Path to gcc_research_*.json")
    parser.add_argument("--output-dir", default=None, help="Output directory; defaults to JSON parent")
    parser.add_argument("--summary-workers", type=int, default=1)
    parser.add_argument("--filtered-out", default=None, help="Optional filtered_out.csv path")
    parser.add_argument("--suffix", default="fixed", help="Filename suffix before extension")
    parser.add_argument(
        "--keep-json-scores",
        action="store_true",
        help="Use relevance scores already stored in JSON instead of refreshing core_gcc scores",
    )
    args = parser.parse_args()

    os.environ.setdefault("AI_FORCE_CURL", "1")
    os.environ.setdefault("AI_TIMEOUT_SECONDS", "240")
    os.environ.setdefault("AI_MAX_RETRIES", "0")
    os.environ.setdefault("AI_SUMMARY_BATCH_SIZE", "3")
    os.environ.setdefault("AI_SUMMARY_MAX_TOKENS", "5000")

    json_path = Path(args.json_path)
    output_dir = Path(args.output_dir) if args.output_dir else json_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    records = payload["articles"] if isinstance(payload, dict) else payload
    articles = [Article(**record) for record in records]
    changed_scores = 0
    if not args.keep_json_scores:
        changed_scores = refresh_core_gcc_relevance_scores(articles)

    filtered_path = Path(args.filtered_out) if args.filtered_out else output_dir / "filtered_out.csv"
    summary = generate_ai_summary(
        articles,
        summary_workers=args.summary_workers,
        filtered_out_records=load_filtered_out(filtered_path),
    )
    if not summary:
        raise SystemExit("AI summary generation returned empty text")

    ts = datetime.now().strftime("%Y%m%d_%H%M")
    suffix = f"_{args.suffix}" if args.suffix else ""
    md_path = output_dir / f"gcc_summary_{ts}{suffix}.md"
    pdf_path = output_dir / f"gcc_summary_{ts}{suffix}.pdf"
    md_path.write_text(summary, encoding="utf-8")
    export_summary_pdf(summary, str(pdf_path))

    markers = (
        summary.count("AI 解析失败")
        + summary.count("本批次 AI 解析失败")
        + summary.count("curl fallback failed")
        + summary.count("Connection error")
    )
    print(f"AI summary MD: {md_path}")
    print(f"AI summary PDF: {pdf_path}")
    print(f"refreshed_core_gcc_scores: {changed_scores}")
    print(f"failure_markers: {markers}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
