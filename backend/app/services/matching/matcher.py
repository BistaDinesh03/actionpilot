from __future__ import annotations

import re
from typing import Any

STOP_WORDS = {"run", "my", "the", "a", "an", "workflow", "skill", "task", "please", "do", "for", "with", "using", "search"}
ASSIGNMENT = re.compile(r"\b([a-zA-Z_]\w*)\s*=\s*(?:\"([^\"]+)\"|'([^']+)'|(.+?))(?=\s+and\s+|\s*$)", re.IGNORECASE)
FOR_VALUE = re.compile(r"\bfor\s+(?:a|an|the)\s+(.+?)(?:\s+workflow|\s+skill|\s*$)", re.IGNORECASE)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w=.'-]", " ", text.lower())).strip()


def words(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", normalize(text)) if word not in STOP_WORDS and len(word) > 1}


def extract_variables(command: str, skill: dict[str, Any]) -> dict[str, str]:
    variables: dict[str, str] = {}
    for match in ASSIGNMENT.finditer(command):
        variables[match.group(1).lower()] = next(value for value in match.groups()[1:] if value is not None).strip()
    if "product" not in variables:
        value_match = FOR_VALUE.search(command)
        if value_match and any("{product}" in str(step.get("value", "")) or step.get("type") == "type" for step in skill.get("steps", [])):
            variables["product"] = value_match.group(1).strip(" .,'\"")
    return variables


def apply_variables(step: dict[str, Any], variables: dict[str, str]) -> dict[str, Any]:
    result = dict(step)
    if isinstance(result.get("value"), str):
        for key, value in variables.items():
            result["value"] = result["value"].replace("{" + key + "}", value).replace("{{" + key + "}}", value)
        if result.get("type") == "type" and "product" in variables:
            result["value"] = variables["product"]
        if result.get("type") == "select" and any(key in variables for key in ("color", "size")):
            result["value"] = variables.get("color", variables.get("size", result["value"]))
    return result


def skill_text(skill: dict[str, Any]) -> dict[str, set[str]]:
    step_text = " ".join(f"{step.get('label', '')} {step.get('value', '')} {step.get('url', '')}" for step in skill.get("steps", []))
    return {"name": words(skill.get("name", "")), "description": words(skill.get("description", "")), "domains": words(" ".join(skill.get("domains", []))), "steps": words(step_text)}


def match_command(command: str, skills: list[dict[str, Any]]) -> dict[str, Any]:
    normalized = normalize(command)
    command_words = words(normalized)
    ranked: list[tuple[float, dict[str, Any]]] = []
    for skill in skills:
        fields = skill_text(skill)
        score = len(command_words & fields["name"]) * 0.55
        score += len(command_words & fields["description"]) * 0.2
        score += len(command_words & fields["domains"]) * 0.15
        score += len(command_words & fields["steps"]) * 0.1
        if normalize(skill.get("name", "")) in normalized:
            score += 0.75
        ranked.append((score, skill))
    ranked.sort(key=lambda item: item[0], reverse=True)
    if not ranked or ranked[0][0] < 0.35:
        return {"intent": "clarify", "matched": False, "confidence": 0.0, "variables": {}, "message": "I could not find a matching skill."}
    top_score, top_skill = ranked[0]
    second_score = ranked[1][0] if len(ranked) > 1 else 0.0
    confidence = min(0.99, round(0.45 + top_score / 2.5, 2))
    if len(ranked) > 1 and top_score - second_score < 0.2:
        return {"intent": "clarify", "matched": False, "confidence": confidence, "variables": {}, "message": "Which skill should I run?", "candidates": [item[1] for item in ranked[:3]]}
    variables = extract_variables(command, top_skill)
    plan = [apply_variables(step, variables) for step in top_skill.get("steps", [])]
    requires_confirmation = any(step.get("risk_level") == "high" for step in plan)
    return {"intent": "run_skill", "matched": True, "skill_id": top_skill["id"], "skill": top_skill, "confidence": confidence, "variables": variables, "plan": plan, "requires_confirmation": requires_confirmation}
