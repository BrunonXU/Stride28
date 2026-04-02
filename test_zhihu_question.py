"""独立测试：知乎问题页 DOM 提取"""
import asyncio, logging, sys, os
sys.path.insert(0, os.path.dirname(__file__))
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(message)s", stream=sys.stderr)

async def main():
    from playwright.async_api import async_playwright
    from pathlib import Path

    ROOT = Path(__file__).parent
    DATA = ROOT / "browser_data" / "zhihu"
    STEALTH = ROOT / "stealth.min.js"

    pw = await (async_playwright()).start()
    ctx = await pw.chromium.launch_persistent_context(
        user_data_dir=str(DATA),
        headless=False,  # 先用可见模式看看页面到底长什么样
        viewport={"width": 1920, "height": 1080},
    )
    if STEALTH.exists():
        await ctx.add_init_script(path=str(STEALTH))

    page = await ctx.new_page()
    url = "https://www.zhihu.com/question/1936375725931361485"
    print(f"导航到: {url}")
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(5000)

    # 截图看看页面状态
    await page.screenshot(path="zhihu_question_debug.png", full_page=False)
    print("截图已保存: zhihu_question_debug.png")

    # 尝试提取
    title = await page.evaluate("() => document.querySelector('.QuestionHeader-title')?.innerText || 'NO TITLE'")
    answer_count = await page.evaluate("() => document.querySelectorAll('.AnswerItem, .List-item, .AnswerCard').length")
    print(f"标题: {title}")
    print(f"回答元素数: {answer_count}")

    # 打印页面 URL（看是否被重定向到登录页）
    print(f"当前 URL: {page.url}")

    await page.wait_for_timeout(30000)  # 保持 30 秒让你看
    await ctx.close()
    await pw.stop()

asyncio.run(main())
