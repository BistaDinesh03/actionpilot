from __future__ import annotations

from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright


class BrowserSession:
    def __init__(self, runtime_dir: Path, headless: bool = True) -> None:
        self.runtime_dir = runtime_dir
        self.headless = headless
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None

    def start(self) -> Page:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=self.headless)
        self.context = self.browser.new_context(
            record_video_dir=str(self.runtime_dir / "video"),
            record_video_size={"width": 1280, "height": 720},
        )
        self.page = self.context.new_page()
        return self.page

    def screenshot(self, name: str) -> str | None:
        if not self.page:
            return None
        path = self.runtime_dir / name
        self.page.screenshot(path=str(path), full_page=False)
        return str(path)

    def close(self) -> None:
        for resource in (self.context, self.browser, self.playwright):
            try:
                if resource:
                    resource.close() if resource is not self.playwright else resource.stop()
            except Exception:
                pass
        self.page = None
        self.context = None
        self.browser = None
        self.playwright = None
