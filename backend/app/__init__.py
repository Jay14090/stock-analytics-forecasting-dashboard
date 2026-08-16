"""Application factory.

Constructing the app in a function (rather than at import time) is what lets
the test suite build a fresh, isolated instance per fixture and lets the CLI
and WSGI entry points share one code path.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from flask import Flask, g, jsonify, request

from .api import register_blueprints
from .config import INSTANCE_DIR, BaseConfig, get_config
from .errors import register_error_handlers
from .extensions import cors, db
from .logging_config import configure_logging

logger = logging.getLogger(__name__)

__version__ = "1.0.0"


def create_app(config_name: str | None = None, **overrides: Any) -> Flask:
    """Build and configure the Flask application.

    Args:
        config_name: ``development`` | ``testing`` | ``production``.
        **overrides: Config values applied last, used by tests.
    """
    app = Flask(__name__, instance_relative_config=False)

    config_class = get_config(config_name)
    app.config.from_object(config_class)
    app.config["ENV_NAME"] = config_name or "development"
    app.config.update(overrides)

    configure_logging(app.config["LOG_LEVEL"], app.config["LOG_JSON"])

    _ensure_directories(app)
    _init_extensions(app)
    register_blueprints(app)
    register_error_handlers(app)
    _register_request_hooks(app)
    _register_cli(app)
    _register_root(app)

    with app.app_context():
        db.create_all()

    logger.info(
        "app_ready environment=%s database=%s",
        app.config["ENV_NAME"],
        app.config["SQLALCHEMY_DATABASE_URI"].split("///")[-1],
    )
    return app


def _ensure_directories(app: Flask) -> None:
    """Create the instance and model directories before anything writes."""
    INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    model_dir = app.config["MODEL_DIR"]
    model_dir.mkdir(parents=True, exist_ok=True)


def _init_extensions(app: Flask) -> None:
    db.init_app(app)
    cors.init_app(
        app,
        resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}},
        supports_credentials=False,
    )


def _register_request_hooks(app: Flask) -> None:
    """Time every request and log the slow ones."""

    @app.before_request
    def _start_timer() -> None:
        g.request_started = time.perf_counter()

    @app.after_request
    def _log_request(response):
        started = getattr(g, "request_started", None)
        if started is None or not request.path.startswith("/api"):
            return response

        duration_ms = (time.perf_counter() - started) * 1000
        response.headers["X-Response-Time-Ms"] = f"{duration_ms:.1f}"

        # Only surface requests worth looking at: anything slow, or any failure.
        if duration_ms > 1500 or response.status_code >= 400:
            logger.info(
                "request method=%s path=%s status=%d duration_ms=%.1f",
                request.method, request.path, response.status_code, duration_ms,
            )
        return response


def _register_root(app: Flask) -> None:
    """A root document so hitting the host directly is not a 404."""

    @app.get("/")
    def index():
        return jsonify(
            {
                "name": "Stock Analytics & Forecasting API",
                "version": __version__,
                "documentation": "/api/routes",
                "health": "/api/health",
            }
        )


def _register_cli(app: Flask) -> None:
    """Register ``flask`` CLI commands."""
    import click

    @app.cli.command("init-db")
    def init_db() -> None:
        """Create all database tables."""
        db.create_all()
        click.echo("Database tables created.")

    @app.cli.command("seed")
    def seed() -> None:
        """Insert a starter watchlist and portfolio for local development."""
        from .models import Portfolio, Transaction, Watchlist, WatchlistItem
        from datetime import date, timedelta

        if db.session.query(Watchlist).count():
            click.echo("Database already seeded; nothing to do.")
            return

        watchlist = Watchlist(name="Megacap Tech")
        watchlist.items = [
            WatchlistItem(symbol=symbol)
            for symbol in ("AAPL", "MSFT", "NVDA", "GOOGL", "AMZN")
        ]

        portfolio = Portfolio(name="Demo Portfolio", base_currency="USD", cash_balance=10_000)
        today = date.today()
        portfolio.transactions = [
            Transaction(
                symbol="AAPL", kind="buy", quantity=10, price=185.50, fees=1.2,
                traded_on=today - timedelta(days=120),
            ),
            Transaction(
                symbol="MSFT", kind="buy", quantity=5, price=402.10, fees=1.2,
                traded_on=today - timedelta(days=90),
            ),
            Transaction(
                symbol="NVDA", kind="buy", quantity=8, price=118.75, fees=1.2,
                traded_on=today - timedelta(days=45),
            ),
            Transaction(
                symbol="AAPL", kind="sell", quantity=4, price=212.30, fees=1.2,
                traded_on=today - timedelta(days=20),
            ),
        ]

        db.session.add_all([watchlist, portfolio])
        db.session.commit()
        click.echo("Seeded 1 watchlist (5 symbols) and 1 portfolio (4 transactions).")

    @app.cli.command("train")
    @click.argument("symbols", nargs=-1, required=True)
    @click.option("--period", default="5y", help="History window used for training.")
    @click.option("--force", is_flag=True, help="Retrain even if a fresh model exists.")
    def train_models(symbols: tuple[str, ...], period: str, force: bool) -> None:
        """Train forecasting models for one or more SYMBOLS."""
        from .services.market_data import fetch_history
        from .services.forecasting import train_symbol

        for symbol in symbols:
            symbol = symbol.upper()
            click.echo(f"Training {symbol} ...")
            try:
                frame = fetch_history(symbol, period=period)
                metadata = train_symbol(symbol, frame, force=force)
            except Exception as exc:  # noqa: BLE001 - CLI reports and continues
                click.echo(f"  failed: {exc}", err=True)
                continue

            metrics = metadata.metrics
            click.echo(
                f"  done in {metrics.get('trainingSeconds', 0):.1f}s | "
                f"directional accuracy {metrics.get('directionalAccuracy', 0):.1%} | "
                f"skill vs baseline {metrics.get('skillScore', 0):+.3f}"
            )
