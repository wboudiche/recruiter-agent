# Importing concrete provider modules at package import time ensures their
# `@register(...)` decorators fire, populating the provider registry that
# `provider.resolve()` consults at runtime. Without these imports the registry
# starts empty and every LinkedIn/Web search reports "Search isn't configured."
from recruiter.sourcing import brave as _brave  # noqa: F401
from recruiter.sourcing import google_cse as _google_cse  # noqa: F401
