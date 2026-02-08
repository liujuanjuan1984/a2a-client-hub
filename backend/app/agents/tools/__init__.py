"""Tools package initializer.

Concrete tool classes live under the submodules within this package. We avoid
re-exporting them here so that dynamic discovery (see ``app.agents.registry``)
only encounters each tool once when iterating over submodules.
"""

from app.agents.tools.base import AbstractTool

__all__ = ["AbstractTool"]
