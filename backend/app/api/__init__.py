"""API blueprints.

One blueprint per resource area, all mounted under ``/api``.
"""

from flask import Flask

from . import analysis, portfolios, stocks, system, watchlists

BLUEPRINTS = (
    system.bp,
    stocks.bp,
    analysis.bp,
    watchlists.bp,
    portfolios.bp,
)


def register_blueprints(app: Flask) -> None:
    """Attach every API blueprint to ``app``."""
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)


__all__ = ["BLUEPRINTS", "register_blueprints"]
