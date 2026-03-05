"""Template registry."""

from __future__ import annotations

from neocore.exceptions import TemplateNotFoundError
from neocore.templates.engine import PostingTemplate


class TemplateRegistry:
    """In-memory registry for posting templates."""

    def __init__(self) -> None:
        self._templates: dict[str, PostingTemplate] = {}

    def register(self, template: PostingTemplate) -> None:
        if template.name in self._templates:
            raise ValueError(f"template already registered: {template.name}")
        self._templates[template.name] = template

    def get(self, name: str) -> PostingTemplate:
        template = self._templates.get(name)
        if template is None:
            raise TemplateNotFoundError(template_name=name)
        return template

    def names(self) -> list[str]:
        return sorted(self._templates)


def _build_default_registry() -> TemplateRegistry:
    from neocore.templates.builtins import BUILTIN_TEMPLATES

    registry = TemplateRegistry()
    for template in BUILTIN_TEMPLATES:
        registry.register(template)
    return registry


DEFAULT_REGISTRY = _build_default_registry()

__all__ = ["DEFAULT_REGISTRY", "TemplateRegistry"]
