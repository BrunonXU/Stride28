"""
Stride28 Eval — 一键评测入口

用法:
    # 跑全部（搜索 + RAG）
    python -m eval.run_eval

    # 只跑搜索
    python -m eval.run_eval --search-only

    # 只跑 RAG
    python -m eval.run_eval --rag-only

    # 跳过 rewrite delta（省时间）
    python -m eval.run_eval --skip-rewrite-delta

报告输出到 eval/reports/ 目录。
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 加载 .env（后端由 main.py 加载，eval 独立运行需要自己加载）
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("eval")


async def main():
    parser = argparse.ArgumentParser(description="Stride28 Eval")
    parser.add_argument("--search-only", action="store_true")
    parser.add_argument("--rag-only", action="store_true")
    parser.add_argument("--skip-rewrite-delta", action="store_true")
    args = parser.parse_args()

    from eval.runners.report_generator import save_json, save_markdown

    search_report = None
    rag_report = None

    # ---- Search Eval ----
    if not args.rag_only:
        logger.info("=" * 60)
        logger.info("Starting Search Eval...")
        logger.info("=" * 60)
        try:
            from eval.runners.search_eval import run_search_eval
            search_report = await run_search_eval(
                skip_rewrite_delta=args.skip_rewrite_delta,
            )
            json_path = save_json(search_report, "search_eval")
            logger.info(f"Search eval JSON saved: {json_path}")
        except Exception as e:
            logger.error(f"Search eval failed: {e}", exc_info=True)

    # ---- RAG Eval ----
    if not args.search_only:
        logger.info("=" * 60)
        logger.info("Starting RAG Eval...")
        logger.info("=" * 60)
        try:
            from eval.runners.rag_eval import run_rag_eval
            rag_report = run_rag_eval()
            json_path = save_json(rag_report, "rag_eval")
            logger.info(f"RAG eval JSON saved: {json_path}")
        except Exception as e:
            logger.error(f"RAG eval failed: {e}", exc_info=True)

    # ---- Markdown Report ----
    if search_report or rag_report:
        md_path = save_markdown(search_report, rag_report)
        logger.info(f"Markdown report saved: {md_path}")
        logger.info("=" * 60)
        logger.info("Eval complete!")
        logger.info("=" * 60)
    else:
        logger.warning("No eval results to report.")


if __name__ == "__main__":
    asyncio.run(main())
