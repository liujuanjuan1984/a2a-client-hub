"""Router registry for API route modules."""

from typing import Final

# Keep router registration centralized here to avoid hard-coded duplication in
# app.main and make startup registration changes reviewable in one place.
ROUTER_MODULES: Final[tuple[str, ...]] = (
    "app.features.auth.router",
    "app.features.personal_agents.router",
    "app.features.hub_agents.router",
    "app.features.hub_agents.admin_router",
    "app.api.routers.admin_proxy_allowlist",
    "app.features.schedules.router",
    "app.features.extension_capabilities.personal_router",
    "app.features.extension_capabilities.hub_router",
    "app.features.opencode_sessions.router",
    "app.features.sessions.router",
    "app.features.invitations.router",
    "app.features.shortcuts.router",
)
