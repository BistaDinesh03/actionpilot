from __future__ import annotations

from typing import Any

from playwright.sync_api import Locator, Page


class LocatorResolutionError(RuntimeError):
    pass


def _usable(locator: Locator) -> Locator | None:
    """Return the first visible match among all matches for this locator.

    Playwright locators often match multiple elements (e.g. a hidden mobile
    search input plus a visible header search input). We must not reject the
    whole strategy just because .first is hidden.
    """
    try:
        count = locator.count()
        if count == 0:
            return None
        for index in range(count):
            candidate = locator.nth(index)
            try:
                if candidate.is_visible():
                    return candidate
            except Exception:
                continue
        return None
    except Exception:
        return None


def resolve_locator(page: Page, target: dict[str, Any], timeout_ms: int = 10_000) -> tuple[Locator, str]:
    page.set_default_timeout(timeout_ms)
    role = target.get("role")
    name = target.get("name")
    if role and name:
        locator = _usable(page.get_by_role(role, name=name, exact=True))
        if locator:
            return locator, "role"
    label = target.get("label")
    if label:
        locator = _usable(page.get_by_label(label, exact=True))
        if locator:
            return locator, "label"
    placeholder = target.get("placeholder")
    if placeholder:
        locator = _usable(page.get_by_placeholder(placeholder, exact=True))
        if locator:
            return locator, "placeholder"
    text = target.get("text")
    if text:
        locator = _usable(page.get_by_text(text, exact=True))
        if locator:
            return locator, "text"
    test_id = target.get("test_id")
    if test_id:
        locator = _usable(page.get_by_test_id(test_id))
        if locator:
            return locator, "test_id"
    css = target.get("css")
    if css:
        locator = _usable(page.locator(css))
        if locator:
            return locator, "css"
    xpath = target.get("xpath")
    if xpath:
        locator = _usable(page.locator(f"xpath={xpath}"))
        if locator:
            return locator, "xpath"
    raise LocatorResolutionError("Could not find a visible element using the recorded target")
