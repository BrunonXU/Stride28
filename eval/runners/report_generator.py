"""
Report Generator — 评测报告生成（JSON + Markdown）

输出到 eval/reports/ 目录，文件名带时间戳。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
REPORTS_DIR = ROOT / "eval" / "reports"


def _ensure_dir():
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def save_json(data: dict, prefix: str) -> str:
    """保存 JSON 报告，返回文件路径。"""
    _ensure_dir()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = REPORTS_DIR / f"{prefix}_{ts}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return str(path)


def generate_markdown(search_report: dict | None, rag_report: dict | None) -> str:
    """生成 Markdown 格式的评测报告。"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# Stride28 Eval Report",
        f"",
        f"> Generated: {ts}",
        f"",
    ]

    # ---- Search Eval ----
    if search_report:
        s = search_report.get("summary", {})
        lines.extend([
            "## Search Eval",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Total Cases | {s.get('total_cases', 0)} |",
            f"| Avg LLM-Judge Score | {s.get('avg_judge_score', 0)}/5.0 |",
            f"| Avg Rewrite Delta | {_fmt_delta(s.get('avg_rewrite_delta'))} |",
            f"| Avg Keyword Hit Rate | {_pct(s.get('avg_keyword_hit', 0))} |",
            f"| Search Success Rate | {_pct(s.get('search_success_rate', 0))} |",
            f"| Latency P50 | {_fmt_ms(s.get('latency_p50_ms', 0))} |",
            f"| Latency P95 | {_fmt_ms(s.get('latency_p95_ms', 0))} |",
            f"| Total Errors | {s.get('total_errors', 0)} |",
            "",
        ])

        # 逐 case 详情
        lines.append("### Per-Case Details")
        lines.append("")
        for c in search_report.get("cases", []):
            lines.append(
                f"**{c['id']}** `{c['query']}` "
                f"({c['category']}) — "
                f"Judge: {c['avg_judge_score']}/5 | "
                f"KW Hit: {_pct(c['keyword_hit_rate'])} | "
                f"Rewrite Delta: {_fmt_delta(c.get('rewrite_delta'))} | "
                f"Search: {_fmt_ms(c.get('search_ms', 0))} | "
                f"Results: {c['result_count']}"
            )
            # tier distribution
            tier = c.get("tier_distribution", {})
            if tier:
                tier_str = ", ".join(f"{k}={v}" for k, v in tier.items())
                lines.append(f"  Tiers: {tier_str}")

            # top 5 details
            for d in c.get("top5_details", []):
                lines.append(
                    f"  - [{d['judge_score']}/5] "
                    f"{d['title']} "
                    f"({d['platform']}/{d['source_tier']}) "
                    f"— {d['judge_reason']}"
                )
            lines.append("")

    # ---- RAG Eval ----
    if rag_report:
        r = rag_report.get("summary", {})
        lines.extend([
            "## RAG Eval",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Total Queries | {r.get('total_queries', 0)} |",
            f"| Hit@3 | {_pct(r.get('hit_at_3', 0))} |",
            f"| Hit@5 | {_pct(r.get('hit_at_5', 0))} |",
            f"| Avg LLM-Judge Score | {r.get('avg_judge_score', 0)}/5.0 |",
        ])
        lines.extend([
            f"| Avg Reranker Lift@3 | {_fmt_lift(r.get('avg_reranker_lift_at_3', 0))} |",
            f"| Avg Reranker Lift@5 | {_fmt_lift(r.get('avg_reranker_lift_at_5', 0))} |",
            f"| Retrieval Latency P50 | {_fmt_ms(r.get('latency_p50_ms', 0))} |",
            f"| Retrieval Latency P95 | {_fmt_ms(r.get('latency_p95_ms', 0))} |",
            "",
        ])

        # 逐 query 详情
        lines.append("### Per-Query Details")
        lines.append("")
        for q in rag_report.get("queries", []):
            lines.append(
                f"**{q['case_id']}** `{q['query']}` — "
                f"Hit@3: {'Y' if q['hit_at_3_rerank'] else 'N'} | "
                f"Hit@5: {'Y' if q['hit_at_5_rerank'] else 'N'} | "
                f"Judge: {q['judge_score']}/5 | "
                f"Lift@3: {q['reranker_lift_at_3']:+d} | "
                f"Latency: {_fmt_ms(q['latency_rerank_ms'])}"
            )
            lines.append(f"  Expected: {q['expected_titles']}")
            lines.append(f"  Rerank top5: {q['retrieved_titles_rerank']}")
            lines.append(f"  Emb-only top5: {q['retrieved_titles_emb']}")
            lines.append(f"  Judge reason: {q['judge_reason']}")
            lines.append("")

    # ---- 面试话术建议 ----
    lines.extend([
        "## Interview Talking Points",
        "",
    ])
    if search_report:
        s = search_report.get("summary", {})
        lines.append(
            f"- Search: LLM-Judge avg {s.get('avg_judge_score', 0)}/5.0, "
            f"keyword hit {_pct(s.get('avg_keyword_hit', 0))}, "
            f"P50 search latency {_fmt_ms(s.get('latency_p50_ms', 0))}, "
            f"success rate {_pct(s.get('search_success_rate', 0))}"
        )
        if s.get("avg_rewrite_delta") is not None:
            lines.append(
                f"- Query Rewrite: avg relevance lift {_fmt_delta(s['avg_rewrite_delta'])}"
            )
    if rag_report:
        r = rag_report.get("summary", {})
        lines.append(
            f"- RAG: Hit@3 {_pct(r.get('hit_at_3', 0))}, "
            f"Hit@5 {_pct(r.get('hit_at_5', 0))}, "
            f"Judge avg {r.get('avg_judge_score', 0)}/5.0"
        )
        if r.get("avg_reranker_lift_at_3", 0) != 0:
            lines.append(
                f"- Reranker: avg lift@3 {_fmt_lift(r['avg_reranker_lift_at_3'])}, "
                f"lift@5 {_fmt_lift(r['avg_reranker_lift_at_5'])}"
            )
    lines.append("")

    return "\n".join(lines)


def save_markdown(search_report: dict | None, rag_report: dict | None) -> str:
    """生成并保存 Markdown 报告，返回文件路径。"""
    _ensure_dir()
    md = generate_markdown(search_report, rag_report)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = REPORTS_DIR / f"eval_report_{ts}.md"
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)
    return str(path)


# ---- 格式化工具函数 ----

def _pct(v: float) -> str:
    return f"{v * 100:.1f}%"

def _fmt_ms(v: float) -> str:
    if v >= 1000:
        return f"{v / 1000:.1f}s"
    return f"{v:.0f}ms"

def _fmt_delta(v) -> str:
    if v is None:
        return "N/A"
    return f"{v:+.2f}"

def _fmt_lift(v: float) -> str:
    return f"{v:+.3f}"
