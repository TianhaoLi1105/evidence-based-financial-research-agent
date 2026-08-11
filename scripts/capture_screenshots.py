#!/usr/bin/env python3
"""
功能截图脚本（可选，用于 GitHub README）
==========================================
自动启动 Streamlit 并截取 4 张页面图到 docs/screenshots/：
  - single.png   单股分析（默认页）
  - compare.png  多股对比
  - chat.png     AI 对话抽屉
  - report.png   深度研报（若 AI 有历史消息）

用法：
  pip install playwright && playwright install chromium
  python scripts/capture_screenshots.py [--url http://localhost:8501]
"""
import argparse
import os
import signal
import subprocess
import sys
import time
import urllib.request

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "docs", "screenshots")
PORT = 8502


def wait_ready(url, timeout=90):
    """等待 Streamlit 就绪"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(1.5)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=None, help="已运行的 Streamlit 地址（不传则自动启动）")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("需要 playwright：pip install playwright && playwright install chromium")

    os.makedirs(OUT_DIR, exist_ok=True)
    proc = None
    if not args.url:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        proc = subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", "app.py",
             "--server.headless", "true", "--server.port", str(PORT),
             "--browser.gatherUsageStats", "false"],
            cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(4)
    base = args.url or f"http://localhost:{PORT}"
    if not wait_ready(base):
        if proc:
            proc.terminate()
        sys.exit("Streamlit 未在预期时间内就绪，请手动启动后加 --url 重试")

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 900},
                                    device_scale_factor=1.5)
            page.goto(base, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(3000)
            page.screenshot(path=os.path.join(OUT_DIR, "single.png"),
                            full_page=False)
            print("✓ docs/screenshots/single.png")

            # 多股对比：点击按钮
            for label in ("多股对比", "Compare"):
                try:
                    page.get_by_role("button", name=label).first.click(timeout=5000)
                    break
                except Exception:
                    continue
            page.wait_for_timeout(2500)
            page.screenshot(path=os.path.join(OUT_DIR, "compare.png"),
                            full_page=False)
            print("✓ docs/screenshots/compare.png")

            # AI 抽屉：点击右下角悬浮球
            try:
                page.locator("iframe[title*='ai_panel']").click(timeout=8000)
                page.wait_for_timeout(2500)
                page.screenshot(path=os.path.join(OUT_DIR, "chat.png"),
                                full_page=False)
                print("✓ docs/screenshots/chat.png")
                page.wait_for_timeout(1500)
                page.screenshot(path=os.path.join(OUT_DIR, "report.png"),
                                full_page=False)
                print("✓ docs/screenshots/report.png")
            except Exception as e:
                print(f"⚠ AI 抽屉截图失败（可手动打开后重试）：{e}")

            browser.close()
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
    print("完成。图片输出到 docs/screenshots/，提交时请勿删除 .gitkeep。")


if __name__ == "__main__":
    main()
