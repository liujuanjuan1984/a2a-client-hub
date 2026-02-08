"""Cardbox configuration helpers.

This module centralises the setup required to use the embedded Cardbox
context engine inside the Compass backend. We call ``setup_cardbox`` during
application start-up so all subsequent imports can rely on a configured
Cardbox environment.
"""

from card_box_core.config import configure

from app.core.config import Settings


def setup_cardbox(settings: Settings) -> None:
    """Initialise Cardbox with Compass configuration values.

    Parameters
    ----------
    settings:
        The application settings object populated from environment variables.

    This helper ensures that Cardbox uses the DuckDB path declared in our
    settings and respects the desired history level / logging verbosity. The
    function is idempotent: invoking it multiple times will just reapply the
    same configuration.
    """

    configure(
        {
            "DUCKDB_STORAGE_ADAPTER": {"path": settings.card_box_duckdb_path},
            "DEFAULT_HISTORY_LEVEL": settings.card_box_history_level,
            "VERBOSE_LOGS": settings.card_box_verbose_logs,
        }
    )
