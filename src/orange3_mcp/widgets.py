"""Widget catalog: known Orange3 widgets and their qualified names / channels."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources


@dataclass(frozen=True)
class WidgetSpec:
    id: str
    name: str
    category: str
    qualified_name: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "qualified_name": self.qualified_name,
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
        }


def _catalog_path() -> str:
    override = os.environ.get("ORANGE3_MCP_WIDGET_CATALOG")
    if override:
        return override
    return str(resources.files("orange3_mcp").joinpath("widgets_catalog.json"))


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, WidgetSpec]:
    path = _catalog_path()
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    catalog: dict[str, WidgetSpec] = {}
    for entry in raw["widgets"]:
        spec = WidgetSpec(
            id=entry["id"],
            name=entry["name"],
            category=entry["category"],
            qualified_name=entry["qualified_name"],
            inputs=tuple(entry.get("inputs", [])),
            outputs=tuple(entry.get("outputs", [])),
        )
        catalog[spec.id] = spec
        # allow lookup by qualified_name too, for widgets referenced that way
        catalog[spec.qualified_name] = spec
    return catalog


def find_widget(identifier: str) -> WidgetSpec | None:
    """Look up a widget by catalog id, qualified name, or (case-insensitive) display name."""
    catalog = load_catalog()
    if identifier in catalog:
        return catalog[identifier]
    lowered = identifier.strip().lower()
    for spec in catalog.values():
        if spec.name.lower() == lowered:
            return spec
    return None


def list_widgets(category: str | None = None) -> list[WidgetSpec]:
    catalog = load_catalog()
    seen: set[str] = set()
    results: list[WidgetSpec] = []
    for spec in catalog.values():
        if spec.id in seen:
            continue
        seen.add(spec.id)
        if category and spec.category.lower() != category.lower():
            continue
        results.append(spec)
    results.sort(key=lambda s: (s.category, s.name))
    return results
