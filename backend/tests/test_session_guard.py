"""Browser session ids become runtime directories; keep them strictly inert.

Defense in depth for the audit finding "latent runtime_root / session_id
filesystem join": today the planner always generates uuid4-hex ids, but the
tools must refuse anything that could escape the runtime directory even if a
future plan source ever passed untrusted parameters.
"""

import uuid

import pytest

from app.services.agent.browser_tool import SESSION_ID_PATTERN, BrowserTool
from app.services.agent.playground_tool import PlaygroundTool


def test_planner_session_ids_satisfy_the_guard():
    # Real planner ids (uuid4 hex) must keep working unchanged.
    assert SESSION_ID_PATTERN.fullmatch(uuid.uuid4().hex)


def test_browser_tool_rejects_unsafe_session_ids(tmp_path):
    tool = BrowserTool(runtime_dir=tmp_path)
    for bad in ("../escape", "..", "a/b", "", "a" * 65):
        with pytest.raises(RuntimeError, match="invalid browser session id"):
            tool._start_session({"session_id": bad, "url": "http://127.0.0.1:4173/account.html"})


def test_playground_tool_rejects_unsafe_session_ids(tmp_path):
    tool = PlaygroundTool(runtime_dir=tmp_path)
    for bad in ("../escape", "..", "a/b"):
        with pytest.raises(RuntimeError, match="invalid playground session id"):
            tool._start_session(bad)
