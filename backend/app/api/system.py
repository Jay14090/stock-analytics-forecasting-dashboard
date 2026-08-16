"""Operational endpoints: health, cache inspection and the route index."""

from __future__ import annotations

import platform
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, request

from ..extensions import db
from ..services.cache import market_cache
from ..services.forecasting import tensorflow_available

bp = Blueprint("system", __name__, url_prefix="/api")


@bp.get("/health")
def health():
    """Liveness and dependency check.

    Returns 503 when the database is unreachable so a load balancer can act on
    it. TensorFlow being absent is reported but is *not* unhealthy — the rest
    of the dashboard works without it.
    """
    database_ok = True
    database_error = None
    try:
        db.session.execute(db.text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - report any driver failure verbatim
        database_ok = False
        database_error = str(exc)

    payload = {
        "status": "ok" if database_ok else "degraded",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": {
            "database": {"ok": database_ok, "error": database_error},
            "forecasting": {
                "ok": tensorflow_available(),
                "detail": "TensorFlow present" if tensorflow_available()
                else "TensorFlow not installed; forecasting endpoints return 503",
            },
        },
        "runtime": {
            "python": platform.python_version(),
            "environment": current_app.config.get("ENV_NAME", "development"),
        },
    }
    return jsonify(payload), (200 if database_ok else 503)


@bp.get("/cache")
def cache_stats():
    """Hit rate and occupancy of the market-data cache."""
    return jsonify(market_cache.stats())


@bp.delete("/cache")
def clear_cache():
    """Drop cached market data (optionally by ``?prefix=history:AAPL``)."""
    prefix = request.args.get("prefix", "")
    removed = market_cache.invalidate(prefix)
    return jsonify({"cleared": removed, "prefix": prefix or "*"})


@bp.get("/routes")
def routes():
    """Machine-readable index of the API surface."""
    listing = []
    for rule in sorted(current_app.url_map.iter_rules(), key=lambda r: str(r)):
        if not str(rule).startswith("/api"):
            continue
        methods = sorted(rule.methods - {"HEAD", "OPTIONS"})
        listing.append(
            {
                "rule": str(rule),
                "methods": methods,
                "endpoint": rule.endpoint,
                "summary": (current_app.view_functions[rule.endpoint].__doc__ or "")
                .strip()
                .split("\n")[0],
            }
        )
    return jsonify({"routes": listing, "count": len(listing)})
