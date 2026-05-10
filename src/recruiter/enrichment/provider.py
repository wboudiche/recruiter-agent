from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

# ---------- schemas ----------


class EnrichmentSignal(BaseModel):
    type: Literal["code", "answer", "post", "talk", "writing", "profile"]
    summary: str
    url: str | None = None
    timestamp: datetime | None = None


class EnrichmentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    profile_url: str
    confidence: float          # 0.0..1.0
    discovered: bool           # True if found via discovery, False if from candidate.links
    signals: list[EnrichmentSignal]
    summary: str               # one-paragraph overview, recruiter-facing


class EnrichmentBundle(BaseModel):
    fetched_at: datetime
    expires_at: datetime
    discovery_consent: bool
    results: list[EnrichmentResult]
    errors: list[dict]         # { source, error, transient }


class EnrichmentHint(BaseModel):
    """Input shape for a provider. Either an explicit URL (confidence 1.0)
    or a name+employer pair from discovery (confidence 0.5)."""
    url: str | None = None
    name: str | None = None
    employer: str | None = None
    confidence: float = 0.5
    source: str | None = None  # which provider this hint targets, if known

    def model_post_init(self, _ctx) -> None:
        if not self.url and not self.name:
            raise ValueError("EnrichmentHint requires url or name")


# ---------- protocol ----------


@runtime_checkable
class EnrichmentProvider(Protocol):
    name: ClassVar[str]
    domains: ClassVar[list[str]]

    async def enrich(self, hint: EnrichmentHint) -> EnrichmentResult | None: ...

    async def aclose(self) -> None: ...


# ---------- registry ----------


_REGISTRY: dict[str, type] = {}


def register(name: str):
    """Class decorator. Registers a provider class under `name`. Each provider
    module imports `register` and decorates its top-level provider class."""
    def deco(cls: type) -> type:
        _REGISTRY[name] = cls
        return cls
    return deco


def _instantiate(cls: type, settings: Any) -> EnrichmentProvider | None:
    """Build a provider instance from settings. Each provider class accepts
    optional kwargs (api_key, token, etc.) — the loader resolves them per
    provider name. Returns None when required config is missing."""
    from recruiter.crypto import settings_cipher

    cipher = settings_cipher()
    name = getattr(cls, "name", None)
    try:
        if name == "twitter":
            enc = getattr(settings, "enrichment_twitter_api_key_enc", None)
            if not enc:
                return None
            return cls(bearer_token=cipher.decrypt(enc))
        if name == "youtube":
            enc = getattr(settings, "enrichment_youtube_api_key_enc", None)
            if not enc:
                return None
            return cls(api_key=cipher.decrypt(enc))
        if name == "stackoverflow":
            enc = getattr(settings, "enrichment_stackexchange_key_enc", None)
            return cls(api_key=cipher.decrypt(enc) if enc else None)
        if name == "github":
            enc = getattr(settings, "github_token_enc", None)
            return cls(token=cipher.decrypt(enc) if enc else None)
        # Keyless providers: hackernews, reddit, mastodon, bluesky, devto, blog.
        return cls()
    except Exception:
        # A bad/corrupted ciphertext shouldn't take down the whole pipeline.
        return None


def resolve_all(settings: Any) -> list[EnrichmentProvider]:
    """Return one configured instance per registered provider, filtered by
    `settings.enrichment_sources` (dict of name → bool; missing → True)
    and by required-config presence."""
    toggles: dict[str, bool] = getattr(settings, "enrichment_sources", None) or {}
    out: list[EnrichmentProvider] = []
    for name, cls in _REGISTRY.items():
        if toggles.get(name, True) is False:
            continue
        inst = _instantiate(cls, settings)
        if inst is None:
            continue
        out.append(inst)
    return out


def resolve_for_domain(domain: str, settings: Any) -> EnrichmentProvider | None:
    """Return the single provider whose `domains` list matches the given
    URL host, or None if no provider claims it. Used by the pipeline when
    routing an explicit hint URL to its handler."""
    for prov in resolve_all(settings):
        for d in prov.domains:
            if domain == d or domain.endswith("." + d):
                return prov
    return None
