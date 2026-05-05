"""Persona inspection (read-only — editing happens in YAML on disk)."""
from __future__ import annotations

from fastapi import APIRouter

from src.api.schemas import PersonaOut, PersonasResponse
from src.tools.persona import list_all_personas, load_active_persona

router = APIRouter(prefix="/api/personas", tags=["personas"])


@router.get("", response_model=PersonasResponse)
def list_personas() -> PersonasResponse:
    active, personas = list_all_personas()
    return PersonasResponse(
        active=active,
        personas=[
            PersonaOut(name=p.name, description=p.description, instructions=p.instructions)
            for p in personas.values()
        ],
    )


@router.get("/active", response_model=PersonaOut)
def active_persona() -> PersonaOut:
    p = load_active_persona()
    return PersonaOut(name=p.name, description=p.description, instructions=p.instructions)
