"""Prompt template loading and versioning.

Prompts are files, not string literals.  That makes them reviewable in a diff,
editable by someone who is not a programmer, and -- because each is hashed -- it
makes a prompt change visible in the audit log without the log ever storing the
prompt text.

When a run is later questioned, ``prompt_versions`` in its audit record says
exactly which template produced it.  If the hash does not match the file on disk
today, the prompt has changed since, and the record says so.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from adhikar.errors import ConfigurationError

PROMPT_DIR = Path(__file__).parent / "prompts"


@dataclass(frozen=True, slots=True)
class Prompt:
    """A template plus the hash that identifies this exact version of it."""

    name: str
    text: str
    sha256: str

    def render(self, **substitutions: str) -> str:
        """Fill ``{{PLACEHOLDER}}`` slots.

        Raises:
            ConfigurationError: a placeholder remained unfilled, which means the
                template and its caller have drifted apart. Sending a prompt with
                a literal ``{{QUESTION}}`` in it would silently degrade output.
        """
        rendered = self.text
        for key, value in substitutions.items():
            rendered = rendered.replace(f"{{{{{key}}}}}", value)

        # {{FENCE}} is filled later, by the transcript builder, and is the one
        # placeholder legitimately still present at this point.
        leftover = [
            name
            for name in _placeholders(rendered)
            # {{FENCE}} is substituted later, by the transcript builder.
            if name != "FENCE"
        ]
        if leftover:
            raise ConfigurationError(
                f"prompt '{self.name}' has unfilled placeholder(s): {sorted(leftover)}"
            )
        return rendered


def _placeholders(text: str) -> set[str]:
    import re

    return set(re.findall(r"\{\{([A-Z_]+)\}\}", text))


@lru_cache(maxsize=32)
def load(name: str, directory: Path | None = None) -> Prompt:
    """Load a prompt template by name (without the ``.md`` suffix).

    Raises:
        ConfigurationError: the template does not exist or is empty.
    """
    base = directory or PROMPT_DIR
    path = base / f"{name}.md"
    # Defence against a name reaching this from a request: resolve and confirm
    # the file really sits inside the prompt directory.
    resolved = path.resolve()
    if not resolved.is_relative_to(base.resolve()):
        raise ConfigurationError(f"prompt name {name!r} escapes the prompt directory")
    try:
        text = resolved.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise ConfigurationError(f"prompt template '{name}' not found at {path}") from exc
    if not text:
        raise ConfigurationError(f"prompt template '{name}' is empty")
    return Prompt(name=name, text=text, sha256=hashlib.sha256(text.encode("utf-8")).hexdigest())


def versions(*names: str) -> dict[str, str]:
    """Short hashes for the named prompts, for the audit record."""
    return {name: load(name).sha256[:16] for name in names}
