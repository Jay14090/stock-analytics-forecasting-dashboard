"""Shared pytest fixtures.

No test in this suite touches the network. Market data is synthesised from a
seeded generator, which makes failures reproducible and keeps the suite usable
offline and inside CI.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Make the backend package importable when pytest is invoked from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app  # noqa: E402
from app.extensions import db as _db  # noqa: E402
from app.models import Portfolio, Transaction, Watchlist, WatchlistItem  # noqa: E402


def make_ohlcv(
    rows: int = 400,
    start_price: float = 100.0,
    seed: int = 7,
    trend: float = 0.0003,
    volatility: float = 0.015,
) -> pd.DataFrame:
    """Generate a deterministic OHLCV frame via geometric Brownian motion.

    Args:
        rows: Number of trading days.
        start_price: Opening level of the series.
        seed: RNG seed; the same seed always yields the same series.
        trend: Daily drift.
        volatility: Daily standard deviation of returns.
    """
    rng = np.random.default_rng(seed)
    returns = rng.normal(loc=trend, scale=volatility, size=rows)
    close = start_price * np.exp(np.cumsum(returns))

    # Intraday range scaled off the day's own move keeps high >= close >= low.
    spread = np.abs(rng.normal(0.008, 0.004, rows)) * close
    high = close + spread
    low = close - spread
    open_ = np.concatenate([[start_price], close[:-1]])
    volume = rng.integers(1_000_000, 9_000_000, rows).astype(float)

    index = pd.bdate_range(end=date.today(), periods=rows, name="date")
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum.reduce([high, open_, close]),
            "low": np.minimum.reduce([low, open_, close]),
            "close": close,
            "volume": volume,
        },
        index=index,
    )


@pytest.fixture(scope="session")
def ohlcv_factory():
    """The synthetic-series generator itself, for tests that need variants.

    Exposed as a fixture rather than imported directly: an unrelated ``tests``
    package on ``sys.path`` shadows ``tests.conftest``, and fixtures sidestep
    the import entirely.
    """
    return make_ohlcv


@pytest.fixture(scope="session")
def ohlcv() -> pd.DataFrame:
    """A 400-row synthetic price history."""
    return make_ohlcv()


@pytest.fixture(scope="session")
def short_ohlcv() -> pd.DataFrame:
    """A history too short for most indicators to warm up."""
    return make_ohlcv(rows=15)


@pytest.fixture
def app():
    """A fresh application on an in-memory database."""
    application = create_app("testing")
    with application.app_context():
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()


@pytest.fixture
def db(app):
    """The session-bound SQLAlchemy handle."""
    return _db


@pytest.fixture
def watchlist(db) -> Watchlist:
    """A watchlist holding two symbols."""
    record = Watchlist(name="Test List")
    record.items = [WatchlistItem(symbol="AAPL"), WatchlistItem(symbol="MSFT")]
    db.session.add(record)
    db.session.commit()
    return record


@pytest.fixture
def portfolio(db) -> Portfolio:
    """A portfolio with a buy, a partial sell and a second holding."""
    today = date.today()
    record = Portfolio(name="Test Portfolio", base_currency="USD", cash_balance=5_000.0)
    record.transactions = [
        Transaction(
            symbol="AAPL", kind="buy", quantity=10, price=100.0, fees=1.0,
            traded_on=today - timedelta(days=60),
        ),
        Transaction(
            symbol="AAPL", kind="sell", quantity=4, price=130.0, fees=1.0,
            traded_on=today - timedelta(days=10),
        ),
        Transaction(
            symbol="MSFT", kind="buy", quantity=5, price=200.0, fees=1.0,
            traded_on=today - timedelta(days=30),
        ),
    ]
    db.session.add(record)
    db.session.commit()
    return record
