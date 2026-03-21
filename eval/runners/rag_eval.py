"""
RAG Eval Runner — 检索质量自动评测

创建临时 ChromaDB collection，灌入 seed materials，
评测 Hit@K、Reranker Lift、LLM-as-Judge context relevance。
测完删除 collection，不污染正式数据。
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent


def _load_cases() -> list[dict]:
    path = ROOT / "eval" / "test_cases" / "rag_cases.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _check_hit(
    retrieved: list,
    expected_titles: list[str],
) -> bool:
    """检查 expected_titles 中是否有任意一个出现在 retrieved 结果中。

    匹配规则：retrieved 的 metadata.title 包含 expected_title（子串匹配）。
    """
    for rt in retrieved:
        meta = rt.metadata if hasattr(rt, "metadata") else {}
        ret_title = meta.get("title", "")
        for exp in expected_titles:
            if exp in ret_title or ret_title in exp:
                return True
    return False


def run_rag_eval() -> dict:
    """执行完整 RAG 评测。

    Returns:
        完整评测报告 dict
    """
    cases = _load_cases()

    from src.rag import RAGEngine
    from eval.judges.llm_judge import LLMJudge

    judge = LLMJudge()

    all_query_results = []
    hit_at_3_list = []
    hit_at_5_list = []
    reranker_lift_list = []
    latencies = []

    for case in cases:
        cid = case["id"]
        domain = case["domain"]
        seeds = case["seed_materials"]
        queries = case["queries"]

        # ---- 创建临时 collection ----
        collection_name = f"eval_{cid}_{uuid.uuid4().hex[:8]}"
        engine = RAGEngine(collection_name=collection_name)
        logger.info(f"[RAG Eval] {cid}: 创建临时 collection {collection_name}")

        try:
            # ---- 灌入 seed materials ----
            for i, mat in enumerate(seeds):
                engine.add_document(
                    content=mat["content"],
                    metadata={
                        "title": mat["title"],
                        "material_id": f"eval_{cid}_{i}",
                        "source_tier": mat["metadata"].get("source_tier", ""),
                        "platform": mat["metadata"].get("platform", ""),
                    },
                    doc_id=f"eval_{cid}_{i}",
                )
            logger.info(f"[RAG Eval] {cid}: 灌入 {len(seeds)} 条 seed materials")

            # ---- 逐条 query 评测 ----
            for q in queries:
                query = q["query"]
                expected = q["expected_hit_titles"]

                # 1. Rerank=True 检索
                t0 = time.perf_counter()
                results_rerank = engine.retrieve(
                    query=query, k=5, rerank=True, retrieve_k=15,
                )
                ms_rerank = round((time.perf_counter() - t0) * 1000, 1)

                # 2. Rerank=False 检索（embedding-only）
                t1 = time.perf_counter()
                results_emb = engine.retrieve(
                    query=query, k=5, rerank=False,
                )
                ms_emb = round((time.perf_counter() - t1) * 1000, 1)

                # 3. Hit@K 计算
                hit3_rerank = _check_hit(results_rerank[:3], expected)
                hit5_rerank = _check_hit(results_rerank[:5], expected)
                hit3_emb = _check_hit(results_emb[:3], expected)
                hit5_emb = _check_hit(results_emb[:5], expected)

                hit_at_3_list.append(hit3_rerank)
                hit_at_5_list.append(hit5_rerank)

                # Reranker lift = rerank hit - emb hit
                lift_3 = int(hit3_rerank) - int(hit3_emb)
                lift_5 = int(hit5_rerank) - int(hit5_emb)
                reranker_lift_list.append({"lift_at_3": lift_3, "lift_at_5": lift_5})

                # 4. LLM-as-Judge context relevance（rerank 结果）
                passages = [r.content[:300] for r in results_rerank[:3]]
                judge_data = judge.score_rag_context(query=query, retrieved_passages=passages)

                latencies.append(ms_rerank)

                qr = {
                    "case_id": cid,
                    "query": query,
                    "expected_titles": expected,
                    "hit_at_3_rerank": hit3_rerank,
                    "hit_at_5_rerank": hit5_rerank,
                    "hit_at_3_emb": hit3_emb,
                    "hit_at_5_emb": hit5_emb,
                    "reranker_lift_at_3": lift_3,
                    "reranker_lift_at_5": lift_5,
                    "judge_score": judge_data["score"],
                    "judge_reason": judge_data["reason"],
                    "latency_rerank_ms": ms_rerank,
                    "latency_emb_ms": ms_emb,
                    "retrieved_titles_rerank": [
                        (r.metadata or {}).get("title", "?")
                        for r in results_rerank[:5]
                    ],
                    "retrieved_titles_emb": [
                        (r.metadata or {}).get("title", "?")
                        for r in results_emb[:5]
                    ],
                }
                all_query_results.append(qr)
                logger.info(
                    f"[RAG Eval] {cid}/{query[:30]}: "
                    f"hit@3={hit3_rerank} hit@5={hit5_rerank} "
                    f"judge={judge_data['score']} lift@3={lift_3}"
                )

        finally:
            # ---- 清理临时 collection ----
            try:
                engine.delete_collection()
                logger.info(f"[RAG Eval] {cid}: 已删除临时 collection")
            except Exception as e:
                logger.warning(f"[RAG Eval] 清理 collection 失败: {e}")

    # ---- 汇总 ----
    total_queries = len(all_query_results)
    valid_judges = [q["judge_score"] for q in all_query_results if q["judge_score"] > 0]
    sorted_lat = sorted(latencies)

    summary = {
        "total_queries": total_queries,
        "hit_at_3": round(sum(hit_at_3_list) / total_queries, 3) if total_queries else 0,
        "hit_at_5": round(sum(hit_at_5_list) / total_queries, 3) if total_queries else 0,
        "avg_judge_score": round(sum(valid_judges) / len(valid_judges), 2) if valid_judges else 0,
        "avg_reranker_lift_at_3": round(
            sum(r["lift_at_3"] for r in reranker_lift_list) / len(reranker_lift_list), 3
        ) if reranker_lift_list else 0,
        "avg_reranker_lift_at_5": round(
            sum(r["lift_at_5"] for r in reranker_lift_list) / len(reranker_lift_list), 3
        ) if reranker_lift_list else 0,
        "latency_p50_ms": sorted_lat[len(sorted_lat) // 2] if sorted_lat else 0,
        "latency_p95_ms": sorted_lat[int(len(sorted_lat) * 0.95)] if sorted_lat else 0,
    }

    return {
        "eval_type": "rag",
        "summary": summary,
        "queries": all_query_results,
    }
