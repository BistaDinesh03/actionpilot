from __future__ import annotations

from typing import Any

from playwright.sync_api import Locator, Page


class LocatorResolutionError(RuntimeError):
    pass


def _usable(locator: Locator, wait_ms: int = 0) -> Locator | None:
    """Return the first visible match among all matches for this locator.

    Playwright locators often match multiple elements (e.g. a hidden mobile
    search input plus a visible header search input). We must not reject the
    whole strategy just because .first is hidden.

    When wait_ms > 0, poll for up to wait_ms milliseconds for any match to
    become visible before giving up. This handles dynamically rendered
    elements (SPAs, React/Vue/Angular apps) that appear shortly after
    navigation instead of being present in the initial HTML.
    """
    import time
    deadline = time.monotonic() + (wait_ms / 1000.0) if wait_ms > 0 else 0.0
    poll_interval = 0.1
    while True:
        try:
            count = locator.count()
            if count > 0:
                for index in range(count):
                    candidate = locator.nth(index)
                    try:
                        if candidate.is_visible():
                            return candidate
                    except Exception:
                        continue
        except Exception:
            pass
        if wait_ms <= 0 or time.monotonic() >= deadline:
            return None
        time.sleep(poll_interval)


def _try_strategies(context_obj, target: dict, wait_ms: int) -> tuple[Locator, str] | None:
    """Run the locator strategy chain against a Page or Frame.

    Returns (locator, strategy) on the first visible match, or None.
    """
    role = target.get("role")
    name = target.get("name")
    if role and name:
        locator = _usable(context_obj.get_by_role(role, name=name, exact=True), wait_ms)
        if locator:
            return locator, "role"
    label = target.get("label")
    if label:
        locator = _usable(context_obj.get_by_label(label, exact=True), wait_ms)
        if locator:
            return locator, "label"
    placeholder = target.get("placeholder")
    if placeholder:
        locator = _usable(context_obj.get_by_placeholder(placeholder, exact=True), wait_ms)
        if locator:
            return locator, "placeholder"
    text = target.get("text")
    if text:
        locator = _usable(context_obj.get_by_text(text, exact=True), wait_ms)
        if locator:
            return locator, "text"
    test_id = target.get("test_id")
    if test_id:
        locator = _usable(context_obj.get_by_test_id(test_id), wait_ms)
        if locator:
            return locator, "test_id"
    css = target.get("css")
    if css:
        locator = _usable(context_obj.locator(css), wait_ms)
        if locator:
            return locator, "css"
    xpath = target.get("xpath")
    if xpath:
        locator = _usable(context_obj.locator(f"xpath={xpath}"), wait_ms)
        if locator:
            return locator, "xpath"
    return None


def resolve_locator(page: Page, target: dict[str, Any], timeout_ms: int = 10_000) -> tuple[Locator, str]:
    """Resolve a recorded target to a live Playwright locator.

    Waits up to timeout_ms milliseconds for the element to appear and become
    visible. Distributes the budget across locator strategies: the first
    strategy gets a short probe, and if nothing shows up we keep trying until
    the overall timeout expires. This makes replay robust on SPAs and pages
    that render asynchronously.
    """
    import time
    page.set_default_timeout(timeout_ms)

    deadline = time.monotonic() + (timeout_ms / 1000.0)

    def remaining_ms() -> int:
        return max(0, int((deadline - time.monotonic()) * 1000))

    def try_top_then_frames() -> tuple[Locator, str] | None:
        # 1. Try the top frame first. Most targets live here.
        hit = _try_strategies(page, target, 0)
        if hit:
            return hit
        # 2. Fall back to every child frame. Same strategy chain, same target.
        #    This handles forms embedded in iframes (Stripe, Typeform, recaptcha,
        #    YouTube embeds, comment widgets).
        try:
            frames = page.frames
        except Exception:
            frames = []
        for frame in frames:
            if frame == page.main_frame:
                continue
            try:
                hit = _try_strategies(frame, target, 0)
            except Exception:
                continue
            if hit:
                return hit
        return None

    # First pass: instant. If any strategy already matches (top or frame), use it.
    hit = try_top_then_frames()
    if hit:
        return hit

    # Retry loop: give the page time to render, then re-run top + frames.
    poll_interval_ms = 100
    while remaining_ms() > 0:
        sleep_ms = min(poll_interval_ms, remaining_ms())
        time.sleep(sleep_ms / 1000.0)
        hit = try_top_then_frames()
        if hit:
            return hit

    raise LocatorResolutionError("Could not find a visible element using the recorded target")
