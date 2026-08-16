"""Portfolio valuation and performance analytics.

Positions are folded from the transaction log using **average cost basis**,
which is the convention Indian and most European brokers report against. FIFO
lot tracking would change realised P&L; it is not implemented, and the choice
is stated in the API response so a reader is never guessing which one they are
looking at.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

import numpy as np
import pandas as pd

from ..models import Transaction
from .indicators import max_drawdown, sharpe_ratio
from .market_data import fetch_history, fetch_quote
from ..errors import NotFoundError, UpstreamError

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Position:
    """An open position folded from a symbol's transaction history."""

    symbol: str
    quantity: float = 0.0
    cost_basis: float = 0.0  # total cost of the open quantity, fees included
    realised_pnl: float = 0.0
    fees_paid: float = 0.0
    buy_count: int = 0
    sell_count: int = 0
    first_traded: str | None = None
    last_traded: str | None = None

    @property
    def average_cost(self) -> float:
        return self.cost_basis / self.quantity if self.quantity else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "quantity": round(self.quantity, 6),
            "averageCost": round(self.average_cost, 4),
            "costBasis": round(self.cost_basis, 2),
            "realisedPnl": round(self.realised_pnl, 2),
            "feesPaid": round(self.fees_paid, 2),
            "buyCount": self.buy_count,
            "sellCount": self.sell_count,
            "firstTraded": self.first_traded,
            "lastTraded": self.last_traded,
        }


def build_positions(transactions: Iterable[Transaction]) -> dict[str, Position]:
    """Fold transactions into per-symbol positions.

    Sells reduce the basis proportionally at the current average cost, so the
    remaining basis always reflects the remaining shares. Overselling is
    tolerated and clamped rather than raising: a user correcting a mistyped
    history should not hit a wall mid-edit.
    """
    positions: dict[str, Position] = {}

    for txn in sorted(transactions, key=lambda t: (t.traded_on, t.id or 0)):
        position = positions.setdefault(txn.symbol, Position(symbol=txn.symbol))
        traded_on = txn.traded_on.isoformat() if txn.traded_on else None

        if position.first_traded is None:
            position.first_traded = traded_on
        position.last_traded = traded_on
        position.fees_paid += txn.fees

        if txn.kind == "buy":
            position.quantity += txn.quantity
            position.cost_basis += txn.gross_value + txn.fees
            position.buy_count += 1
            continue

        # Sell
        sold = min(txn.quantity, position.quantity)
        if sold <= 0:
            logger.warning(
                "sell_without_position symbol=%s quantity=%s", txn.symbol, txn.quantity
            )
            position.sell_count += 1
            continue

        average_cost = position.average_cost
        proceeds = sold * txn.price - txn.fees
        position.realised_pnl += proceeds - sold * average_cost
        position.cost_basis -= sold * average_cost
        position.quantity -= sold
        position.sell_count += 1

        # Float error can leave a residue like 1e-13 shares.
        if abs(position.quantity) < 1e-9:
            position.quantity = 0.0
            position.cost_basis = 0.0

    return positions


def value_positions(positions: dict[str, Position]) -> list[dict[str, Any]]:
    """Attach live prices and unrealised P&L to open positions.

    A symbol whose quote cannot be fetched is still returned, marked stale, so
    one dead ticker never blanks the whole portfolio view.
    """
    valued: list[dict[str, Any]] = []

    for symbol, position in positions.items():
        if position.quantity <= 0:
            continue

        payload = position.to_dict()
        try:
            quote = fetch_quote(symbol)
            market_value = position.quantity * quote.price
            unrealised = market_value - position.cost_basis
            payload.update(
                {
                    "currentPrice": quote.price,
                    "marketValue": round(market_value, 2),
                    "unrealisedPnl": round(unrealised, 2),
                    "unrealisedPnlPercent": round(
                        unrealised / position.cost_basis * 100, 4
                    )
                    if position.cost_basis
                    else 0.0,
                    "dayChange": quote.change,
                    "dayChangePercent": quote.change_percent,
                    "dayPnl": round(position.quantity * quote.change, 2),
                    "name": quote.name,
                    "currency": quote.currency,
                    "stale": False,
                }
            )
        except (NotFoundError, UpstreamError) as exc:
            logger.warning("position_quote_failed symbol=%s reason=%s", symbol, exc.message)
            payload.update(
                {
                    "currentPrice": None,
                    "marketValue": None,
                    "unrealisedPnl": None,
                    "unrealisedPnlPercent": None,
                    "stale": True,
                    "staleReason": exc.message,
                }
            )

        valued.append(payload)

    return sorted(
        valued,
        key=lambda item: item.get("marketValue") or 0.0,
        reverse=True,
    )


def summarise(
    valued_positions: list[dict[str, Any]],
    positions: dict[str, Position],
    cash_balance: float = 0.0,
) -> dict[str, Any]:
    """Aggregate totals, allocation weights and concentration."""
    invested = sum(p["costBasis"] for p in valued_positions)
    market_value = sum(p["marketValue"] or 0.0 for p in valued_positions)
    day_pnl = sum(p.get("dayPnl") or 0.0 for p in valued_positions)
    realised = sum(p.realised_pnl for p in positions.values())
    fees = sum(p.fees_paid for p in positions.values())
    unrealised = market_value - invested

    for item in valued_positions:
        value = item.get("marketValue") or 0.0
        item["weight"] = round(value / market_value * 100, 4) if market_value else 0.0

    # Herfindahl index: 1.0 is a single-stock portfolio, near 0 is well spread.
    weights = np.array(
        [(p.get("marketValue") or 0.0) / market_value for p in valued_positions]
    ) if market_value else np.array([])
    concentration = float(np.sum(weights**2)) if weights.size else 0.0

    return {
        "positionCount": len(valued_positions),
        "invested": round(invested, 2),
        "marketValue": round(market_value, 2),
        "cashBalance": round(cash_balance, 2),
        "totalValue": round(market_value + cash_balance, 2),
        "unrealisedPnl": round(unrealised, 2),
        "unrealisedPnlPercent": round(unrealised / invested * 100, 4) if invested else 0.0,
        "realisedPnl": round(realised, 2),
        "totalPnl": round(unrealised + realised, 2),
        "feesPaid": round(fees, 2),
        "dayPnl": round(day_pnl, 2),
        "dayPnlPercent": round(day_pnl / market_value * 100, 4) if market_value else 0.0,
        "concentration": round(concentration, 4),
        "costBasisMethod": "average",
        "staleSymbols": [p["symbol"] for p in valued_positions if p.get("stale")],
    }


def build_equity_curve(
    transactions: Iterable[Transaction], period: str = "1y"
) -> dict[str, Any]:
    """Reconstruct daily portfolio value over ``period``.

    Shares held on each date come from the transaction log; prices come from
    each symbol's daily history. Symbols whose history cannot be fetched are
    excluded and named in the response rather than silently valued at zero.
    """
    transactions = sorted(transactions, key=lambda t: t.traded_on)
    if not transactions:
        return {"points": [], "metrics": {}, "excludedSymbols": []}

    symbols = sorted({t.symbol for t in transactions})
    histories: dict[str, pd.Series] = {}
    excluded: list[str] = []

    for symbol in symbols:
        try:
            histories[symbol] = fetch_history(symbol, period=period)["close"]
        except (NotFoundError, UpstreamError) as exc:
            logger.warning("equity_curve_symbol_skipped symbol=%s reason=%s", symbol, exc.message)
            excluded.append(symbol)

    if not histories:
        return {"points": [], "metrics": {}, "excludedSymbols": excluded}

    calendar = sorted(set().union(*(set(series.index) for series in histories.values())))
    if not calendar:
        return {"points": [], "metrics": {}, "excludedSymbols": excluded}

    # Cumulative share count per symbol on each date.
    deltas: dict[str, dict[pd.Timestamp, float]] = defaultdict(dict)
    for txn in transactions:
        if txn.symbol not in histories:
            continue
        stamp = pd.Timestamp(txn.traded_on)
        signed = txn.quantity if txn.kind == "buy" else -txn.quantity
        deltas[txn.symbol][stamp] = deltas[txn.symbol].get(stamp, 0.0) + signed

    values: list[float] = []
    for stamp in calendar:
        total = 0.0
        for symbol, series in histories.items():
            held = sum(qty for day, qty in deltas[symbol].items() if day <= stamp)
            if held <= 0:
                continue
            prices = series.loc[:stamp]
            if prices.empty:
                continue
            total += held * float(prices.iloc[-1])
        values.append(total)

    curve = pd.Series(values, index=pd.DatetimeIndex(calendar)).replace(0.0, np.nan).dropna()
    if curve.empty:
        return {"points": [], "metrics": {}, "excludedSymbols": excluded}

    start, end = float(curve.iloc[0]), float(curve.iloc[-1])
    return {
        "points": [
            {"date": str(stamp.date()), "value": round(float(value), 2)}
            for stamp, value in curve.items()
        ],
        "metrics": {
            "startValue": round(start, 2),
            "endValue": round(end, 2),
            "totalReturnPercent": round((end - start) / start * 100, 4) if start else 0.0,
            "maxDrawdownPercent": round(max_drawdown(curve) * 100, 4),
            "sharpeRatio": round(sharpe_ratio(curve), 4),
            "observations": int(len(curve)),
        },
        "excludedSymbols": excluded,
    }
