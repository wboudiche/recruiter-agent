# Provider module imports get appended here as each @register-decorated
# class lands. Empty until T5 adds the first provider (Hacker News).
from recruiter.enrichment import bluesky as _bluesky  # noqa: F401
from recruiter.enrichment import hackernews as _hackernews  # noqa: F401
from recruiter.enrichment import mastodon as _mastodon  # noqa: F401
from recruiter.enrichment import reddit as _reddit  # noqa: F401
