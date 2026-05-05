"""Persona YAML loader — re-read on every call so non-developers can edit
config/personas.yaml live without restarting the agent.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict

import yaml

from src import settings

logger = logging.getLogger(__name__)


@dataclass
class Persona:
    name: str
    description: str
    instructions: str


# Last-known-good cache so a broken edit doesn't take the agent down.
_LAST_GOOD: Dict[str, Persona] | None = None
_LAST_ACTIVE: str | None = None


def _parse(raw: dict) -> tuple[str, Dict[str, Persona]]:
    active = raw.get("active")
    personas_raw = raw.get("personas") or {}
    if not active or active not in personas_raw:
        raise ValueError(f"persona config invalid: active='{active}' not found")
    personas: Dict[str, Persona] = {}
    for name, body in personas_raw.items():
        personas[name] = Persona(
            name=name,
            description=str(body.get("description", "")),
            instructions=str(body.get("instructions", "")).strip(),
        )
    return active, personas


def load_active_persona() -> Persona:
    global _LAST_GOOD, _LAST_ACTIVE
    try:
        with open(settings.PERSONA_CONFIG_PATH, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        active, personas = _parse(raw)
        _LAST_GOOD = personas
        _LAST_ACTIVE = active
        return personas[active]
    except Exception as e:  # noqa: BLE001
        logger.error("Failed to load persona config (%s) — using last-good", e)
        if _LAST_GOOD and _LAST_ACTIVE and _LAST_ACTIVE in _LAST_GOOD:
            return _LAST_GOOD[_LAST_ACTIVE]
        # Bootstrap default if there's no last-good and the file is broken.
        return Persona(
            name="default",
            description="Fallback persona",
            instructions="Write a concise, accurate report based on the data.",
        )


def list_all_personas() -> tuple[str, Dict[str, Persona]]:
    """Return (active_name, all_personas). Falls back to last-known-good."""
    global _LAST_GOOD, _LAST_ACTIVE
    try:
        with open(settings.PERSONA_CONFIG_PATH, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        active, personas = _parse(raw)
        _LAST_GOOD = personas
        _LAST_ACTIVE = active
        return active, personas
    except Exception as e:  # noqa: BLE001
        logger.error("Failed to load persona config (%s) — using last-good", e)
        if _LAST_GOOD and _LAST_ACTIVE:
            return _LAST_ACTIVE, _LAST_GOOD
        fallback = Persona(
            name="default",
            description="Fallback persona",
            instructions="Write a concise, accurate report based on the data.",
        )
        return "default", {"default": fallback}
