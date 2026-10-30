from typing import Literal

from app.config import settings

ModelRole = Literal["general", "coding"]


def resolve_model(role: ModelRole) -> str:
    if role == "general":
        return settings.primary_model
    if role == "coding":
        return settings.coding_model
    raise ValueError(f"Unsupported model role: {role}")
