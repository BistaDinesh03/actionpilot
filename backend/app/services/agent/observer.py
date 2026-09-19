from __future__ import annotations

from typing import Any

from playwright.sync_api import Page

from .state import Observation


def observe_page(page: Page, limit: int = 4000) -> Observation:
    visible_text = page.locator("body").inner_text(timeout=5_000)[:limit]
    links = page.locator("a")
    buttons = page.locator("button")
    forms = page.locator("input, textarea, select")
    return Observation(kind="browser", summary=f"{page.title()} at {page.url}", data={"url": page.url, "title": page.title(), "visible_text": visible_text, "links": [{"text": links.nth(i).inner_text()[:160], "url": links.nth(i).get_attribute("href")} for i in range(min(links.count(), 30))], "buttons": [buttons.nth(i).inner_text()[:160] for i in range(min(buttons.count(), 30))], "forms": [{"tag": forms.nth(i).evaluate("element => element.tagName"), "placeholder": forms.nth(i).get_attribute("placeholder")} for i in range(min(forms.count(), 30))]})


def observe_result(status: str, output: dict[str, Any]) -> Observation:
    return Observation(kind="tool_result", summary=status, data=output)
