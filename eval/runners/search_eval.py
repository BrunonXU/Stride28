"""
Search Eval Runner — 搜索质量自动评测

直接调用 SearchOrchestrator（不走 HTTP），采集：
- LLM-as-Judge relevance（主指标）
- Query rewrite delta（主指标）
- Keyword hit rate（辅助）
- Reject keyword rate（辅助）
- Source tier distribution
- Latency（各阶段耗时）
- 错误与降级信息
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 项目根目录
ROOT = Path(__file__).resolve().parent.parent.parent


def _load_cases() -> list[dict]:
    """加载搜索 test cases。"""
    path = ROOT / "eval" / "test_cases" / "search_cases.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _create_orchestrator(llm_provider=None):
    """创建 SearchOrchestrator 实例。"""
    from src.specialists.search_orchestrator import SearchOrchestrator
    return SearchOrchestrator(llm_provider=llm_provider)


def _create_llm():
    """创建 LLM provider。"""
    from src.providers.factory import ProviderFactory
    try:
        return ProviderFactory.create_llm()
    except Exception as e:
        logger.warning(f"LLM 创建失败: {e}")
        return None


async def _run_single_search(
    orchestrator,
    query: str,
    platforms: list[str],
    plan_id: str | None = None,
    learner_context=None,
) -> dict:
    """执行单次搜索，收集结果和各阶段耗时。

    Returns:
        {
            "results": [SearchResult.to_dict(), ...],
            "total_ms": float,
            "stage_events": [{"stage": ..., "ts": ...}, ...],
            "errors": [str, ...],
        }
    """
    results = []
    stage_events = []
    errors = []
    t0 = time.perf_counter()

    async for event in orchestrator.search_all_platforms_stream(
        query=query,
        platforms=platforms,
        learner_context=learner_context,
        plan_id=plan_id,
    ):
        stage = event.get("stage", "")
        ts = round((time.perf_counter() - t0) * 1000, 1)
        stage_events.append({"stage": stage, "ts_ms": ts, **event})

        if stage == "done":
            results = event.get("results", [])
        elif stage == "error":
            errors.append(event.get("message", "unknown"))

    total_ms = round((time.perf_counter() - t0) * 1000, 1)
    return {
        "results": results,
        "total_ms": total_ms,
        "stage_events": stage_events,
        "errors": errors,
    }


def _compute_keyword_hit(results: list[dict], keywords: list[str], top_n: int = 5) -> float:
    """计算 top_n 结果中 title_keywords 的命中率。"""
    if not keywords or not results:
        return 0.0
    top = results[:top_n]
    hits = 0
    for kw in keywords:
        kw_lower = kw.lower()
        for r in top:
            title = (r.get("title", "") or "").lower()
            desc = (r.get("description", "") or "").lower()
            if kw_lower in title or kw_lower in desc:
                hits += 1
                break
    return round(hits / len(keywords), 3)


def _compute_reject_rate(results: list[dict], reject_keywords: list[str], top_n: int = 5) -> float:
    """计算 top_n 结果中 reject_keywords 的出现率（越低越好）。"""
    if not reject_keywords or not results:
        return 0.0
    top = results[:top_n]
    rejects = 0
    for r in top:
        title = (r.get("title", "") or "").lower()
        desc = (r.get("description", "") or "").lower()
        for kw in reject_keywords:
            if kw.lower() in title or kw.lower() in desc:
                rejects += 1
                break
    return round(rejects / len(top), 3)


def _compute_tier_distribution(results: list[dict]) -> dict[str, int]:
    """统计 source_tier 分布。"""
    dist: dict[str, int] = {}
    for r in results:
        tier = r.get("source_tier", "") or "unknown"
        dist[tier] = dist.get(tier, 0) + 1
    return dist


async def run_search_eval(skip_rewrite_delta: bool = False) -> dict:
    """执行完整搜索评测。

    Args:
        skip_rewrite_delta: 跳过 rewrite delta 对比（省时间，默认 False）

    Returns:
        完整评测报告 dict
    """
    cases = _load_cases()
    llm = _create_llm()

    from eval.judges.llm_judge import LLMJudge
    judge = LLMJudge(llm_provider=llm)

    all_case_results = []
    all_latencies = []
    all_errors = []

    for case in cases:
        cid = case["id"]
        query = case["query"]
        platforms = case["platforms"]
        signals = case.get("expected_signals", {})
        plan_ctx = case.get("plan_context", {})

        logger.info(f"[Search Eval] Running {cid}: {query}")

        # ---- 构建 learner_context ----
        learner_context = None
        if plan_ctx:
            from src.specialists.quality_assessor import LearnerContext
            learner_context = LearnerContext(
                goal=plan_ctx.get("goal", ""),
                level=plan_ctx.get("level", ""),
                query=query,
            )

        # ---- 执行搜索（rewrite=on，默认行为）----
        orchestrator = _create_orchestrator(llm_provider=llm)
        try:
            search_data = await _run_single_search(
                orchestrator, query, platforms,
                learner_context=learner_context,
            )
        finally:
            await orchestrator.close()

        results = search_data["results"]
        total_ms = search_data["total_ms"]
        errors = search_data["errors"]

        # ---- LLM-as-Judge（top 5）----
        judge_scores = []
        for r in results[:5]:
            score_data = judge.score_search_result(
                query=query,
                title=r.get("title", ""),
                description=r.get("description", ""),
                content_summary=r.get("content_summary", ""),
                learning_goal=plan_ctx.get("goal", ""),
                learning_level=plan_ctx.get("level", ""),
            )
            judge_scores.append({
                "title": r.get("title", "")[:60],
                "platform": r.get("platform", ""),
                "source_tier": r.get("source_tier", ""),
                "quality_score": r.get("quality_score", 0),
                "judge_score": score_data["score"],
                "judge_reason": score_data["reason"],
            })

        avg_judge = (
            round(sum(s["judge_score"] for s in judge_scores) / len(judge_scores), 2)
            if judge_scores else 0
        )

        # ---- 辅助指标 ----
        kw_hit = _compute_keyword_hit(results, signals.get("title_keywords", []))
        reject_rate = _compute_reject_rate(results, signals.get("reject_keywords", []))
        tier_dist = _compute_tier_distribution(results)

        # ---- Rewrite Delta（可选）----
        rewrite_delta = None
        if not skip_rewrite_delta and llm:
            # 用一个无 LLM 的 orchestrator 跑一次（rewrite 会因为 _llm=None 而跳过）
            orch_no_rewrite = _create_orchestrator(llm_provider=None)
            try:
                no_rw_data = await _run_single_search(
                    orch_no_rewrite, query, platforms,
                    learner_context=learner_context,
                )
            finally:
                await orch_no_rewrite.close()

            no_rw_scores = []
            for r in no_rw_data["results"][:5]:
                sd = judge.score_search_result(
                    query=query,
                    title=r.get("title", ""),
                    description=r.get("description", ""),
                    content_summary=r.get("content_summary", ""),
                    learning_goal=plan_ctx.get("goal", ""),
                    learning_level=plan_ctx.get("level", ""),
                )
                no_rw_scores.append(sd["score"])

            avg_no_rw = (
                round(sum(no_rw_scores) / len(no_rw_scores), 2)
                if no_rw_scores else 0
            )
            rewrite_delta = round(avg_judge - avg_no_rw, 2)

        case_result = {
            "id": cid,
            "query": query,
            "category": case.get("category", ""),
            "result_count": len(results),
            "avg_judge_score": avg_judge,
            "keyword_hit_rate": kw_hit,
            "reject_rate": reject_rate,
            "tier_distribution": tier_dist,
            "rewrite_delta": rewrite_delta,
            "total_ms": total_ms,
            "errors": errors,
            "top5_details": judge_scores,
        }
        all_case_results.append(case_result)
        all_latencies.append(total_ms)
        all_errors.extend(errors)

    # ---- 汇总 ----
    valid_judges = [c["avg_judge_score"] for c in all_case_results if c["avg_judge_score"] > 0]
    valid_deltas = [c["rewrite_delta"] for c in all_case_results if c["rewrite_delta"] is not None]
    sorted_lat = sorted(all_latencies)

    summary = {
        "total_cases": len(cases),
        "avg_judge_score": round(sum(valid_judges) / len(valid_judges), 2) if valid_judges else 0,
        "avg_rewrite_delta": round(sum(valid_deltas) / len(valid_deltas), 2) if valid_deltas else None,
        "avg_keyword_hit": round(
            sum(c["keyword_hit_rate"] for c in all_case_results) / len(all_case_results), 3
        ) if all_case_results else 0,
        "latency_p50_ms": sorted_lat[len(sorted_lat) // 2] if sorted_lat else 0,
        "latency_p95_ms": sorted_lat[int(len(sorted_lat) * 0.95)] if sorted_lat else 0,
        "total_errors": len(all_errors),
        "search_success_rate": round(
            sum(1 for c in all_case_results if c["result_count"] > 0) / len(all_case_results), 3
        ) if all_case_results else 0,
    }

    return {
        "eval_type": "search",
        "summary": summary,
        "cases": all_case_results,
    }
