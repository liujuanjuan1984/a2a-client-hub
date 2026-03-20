"""Router registry for API route modules."""

from typing import Final

# Keep router registration centralized here to avoid hard-coded duplication in
# app.main and make startup registration changes reviewable in one place.
ROUTER_MODULES: Final[tuple[str, ...]] = (
    "app.features.auth.router",
    "app.api.routers.a2a_agents",
    "app.api.routers.hub_a2a_agents",
    "app.api.routers.admin_a2a_agents",
    "app.api.routers.admin_proxy_allowlist",
    "app.api.routers.a2a_schedules",
    "app.api.routers.a2a_extension_capabilities",
    "app.api.routers.hub_a2a_extension_capabilities",
    "app.api.routers.opencode_session_directory",
    "app.api.routers.me_sessions",
    "app.features.invitations.router",
    "app.features.shortcuts.router",
)
