from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol


@dataclass
class SearchResult:
    name: str
    url: str
    snippet: str
    source: Literal["linkedin", "github", "web"]


class SearchError(Exception):
    """Raised by providers when a search call fails. `transient` distinguishes
    rate-limit / network failures (retryable later) from config / auth
    failures (require Settings change)."""

    def __init__(self, message: str, *, transient: bool) -> None:
        super().__init__(message)
        self.transient = transient


class SearchProvider(Protocol):
    async def search(self, query: str, limit: int) -> list[SearchResult]: ...


# Module-level registry. Factories are called with a SettingsRow and return
# a configured SearchProvider instance.
_FACTORIES: dict[str, Callable[[Any], SearchProvider]] = {}


def register(
    name: str,
) -> Callable[[Callable[[Any], SearchProvider]], Callable[[Any], SearchProvider]]:
    def deco(factory: Callable[[Any], SearchProvider]) -> Callable[[Any], SearchProvider]:
        _FACTORIES[name] = factory
        return factory
    return deco


def resolve(settings: Any) -> SearchProvider | None:
    """Return a configured provider for the SettingsRow, or None if unset
    or registered factory missing."""
    name = getattr(settings, "search_provider", None)
    if not name:
        return None
    factory = _FACTORIES.get(name)
    if factory is None:
        return None
    return factory(settings)


def parse_linkedin_name(title: str | None) -> str | None:
    """Extract a person's name from a LinkedIn search-result title.

    LinkedIn titles look like 'Alice Doe - Senior Rust | LinkedIn'.
    Strip the '| LinkedIn' suffix and take the segment before the first
    ' - '. Returns None if the title is empty or whitespace-only.
    """
    if not title or not title.strip():
        return None
    cleaned = title.split(" | ")[0].strip()
    return cleaned.split(" - ")[0].strip() or None
