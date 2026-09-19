from __future__ import annotations

import json
import os
from typing import Any

import httpx

from .provider import StructuredIntent


class OpenAICompatibleProvider:
    def __init__(self, api_key: str | None = None, base_url: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key or os.getenv("AI_API_KEY", "")
        self.base_url = (base_url or os.getenv("AI_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        self.model = model or os.getenv("AI_MODEL", "")

    def _request(self, system: str, user: str) -> dict[str, Any]:
        if not self.api_key or not self.model:
            raise RuntimeError("AI provider is not configured")
        response = httpx.post(f"{self.base_url}/chat/completions", headers={"Authorization": f"Bearer {self.api_key}"}, json={"model": self.model, "temperature": 0, "response_format": {"type": "json_object"}, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}, timeout=20)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return json.loads(content)

    def understand_command(self, command: str, skills: list[dict[str, Any]]) -> StructuredIntent:
        result = self._request("Return JSON only. Never return code or commands. Choose a skill_id from the supplied list.", json.dumps({"command": command, "skills": [{"id": skill["id"], "name": skill["name"], "description": skill.get("description", "")} for skill in skills]}))
        return StructuredIntent.model_validate(result)

    def extract_variables(self, command: str, skill: dict[str, Any]) -> dict[str, str]:
        result = self._request("Return JSON only as {\"variables\": {\"name\": \"value\"}}. Never return code or secrets.", json.dumps({"command": command, "skill": skill}))
        return {str(key): str(value) for key, value in result.get("variables", {}).items()}
