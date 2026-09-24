from __future__ import annotations

from typing import Any

from playwright.sync_api import Page

from .state import Observation

# Bounded capture: never record unlimited DOM or page content.
MAX_VISIBLE_TEXT = 4000
MAX_LINKS = 30
MAX_BUTTONS = 30
MAX_FORMS = 30
MAX_ELEMENTS = 30
MAX_FIELD = 160

# One bounded evaluate per interactive element. Input values are never read
# (except submit/button/reset labels) so observations cannot capture typed data.
_ELEMENT_SCRIPT = """
e => ({
  tag: (e.tagName || '').toLowerCase(),
  role: e.getAttribute('role'),
  id: e.id || null,
  type: e.getAttribute('type'),
  placeholder: e.getAttribute('placeholder'),
  aria: e.getAttribute('aria-label'),
  text: ((e.innerText || '') + '').trim(),
  value: (['submit', 'button', 'reset'].indexOf((e.getAttribute('type') || '').toLowerCase()) >= 0 ? (e.value || '') : ''),
  label: ((e.labels && e.labels[0]) ? e.labels[0].innerText : '').trim(),
  visible: !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length),
})
"""

_IMPLICIT_ROLE = {"button": "button", "a": "link", "select": "combobox", "textarea": "textbox"}


def _bounded_elements(page: Page) -> tuple[list[dict[str, Any]], int]:
    """Interactive elements useful for deterministic decisions, hard-bounded."""
    interactive = page.locator("a, button, input, select, textarea, [role=button], [role=link], [role=textbox]")
    total = interactive.count()
    elements: list[dict[str, Any]] = []
    for index in range(min(total, MAX_ELEMENTS)):
        try:
            raw = interactive.nth(index).evaluate(_ELEMENT_SCRIPT)
        except Exception:
            continue
        tag = str(raw.get("tag") or "")
        name = str(raw.get("aria") or raw.get("text") or raw.get("label") or raw.get("placeholder") or raw.get("value") or "").strip()
        elements.append({
            "tag": tag[:32],
            "role": raw.get("role") or _IMPLICIT_ROLE.get(tag),
            "id": raw.get("id") or None,
            "type": raw.get("type") or None,
            "placeholder": raw.get("placeholder") or None,
            "name": name[:MAX_FIELD],
            "label": str(raw.get("label") or "").strip()[:MAX_FIELD],
            "visible": bool(raw.get("visible")),
        })
    return elements, total


def observe_page(page: Page, limit: int = MAX_VISIBLE_TEXT) -> Observation:
    """Bounded, deterministic, read-only snapshot of the live page."""
    visible_text = page.locator("body").inner_text(timeout=5_000)[:limit]
    links = page.locator("a")
    buttons = page.locator("button")
    forms = page.locator("input, textarea, select")
    elements, elements_total = _bounded_elements(page)
    return Observation(kind="browser", summary=f"{page.title()} at {page.url}", data={
        "url": page.url,
        "title": page.title(),
        "visible_text": visible_text,
        "links": [{"text": links.nth(i).inner_text()[:MAX_FIELD], "url": links.nth(i).get_attribute("href")} for i in range(min(links.count(), MAX_LINKS))],
        "buttons": [buttons.nth(i).inner_text()[:MAX_FIELD] for i in range(min(buttons.count(), MAX_BUTTONS))],
        "forms": [{"tag": forms.nth(i).evaluate("element => element.tagName"), "placeholder": forms.nth(i).get_attribute("placeholder")} for i in range(min(forms.count(), MAX_FORMS))],
        "elements": elements,
        "elements_total": elements_total,
        "elements_truncated": elements_total > MAX_ELEMENTS,
    })


def observe_result(status: str, output: dict[str, Any]) -> Observation:
    return Observation(kind="tool_result", summary=status, data=output)
