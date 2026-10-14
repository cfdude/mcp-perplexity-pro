"""Build ``AskOptions`` the way a tool does: the routing mode resolves the call first."""

from mcp_perplexity_pro.agent import AskOptions
from mcp_perplexity_pro.routing import resolve
from mcp_perplexity_pro.settings import Settings

STANDARD = Settings(api_key="test-dummy-api-key", routing="standard", model="perplexity/sonar")


def ask_options(depth=None, model=None, settings=STANDARD, **rest) -> AskOptions:
    return AskOptions(route=resolve(settings, depth=depth, model=model), **rest)
