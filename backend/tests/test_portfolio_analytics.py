"""Position folding and portfolio valuation.

The arithmetic here is what a user checks against their broker statement, so
the expected values are worked out by hand in the assertions rather than
generated from the code under test.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.models import Transaction
from app.services.portfolio_analytics import build_positions, summarise


def txn(symbol, kind, quantity, price, fees=0.0, days_ago=0, txn_id=None):
    return Transaction(
        id=txn_id,
        symbol=symbol,
        kind=kind,
        quantity=quantity,
        price=price,
        fees=fees,
        traded_on=date.today() - timedelta(days=days_ago),
    )


class TestBuildPositions:
    def test_single_buy_sets_basis_including_fees(self):
        positions = build_positions([txn("AAPL", "buy", 10, 100.0, fees=5.0, days_ago=10)])
        position = positions["AAPL"]
        assert position.quantity == 10
        assert position.cost_basis == pytest.approx(1005.0)
        assert position.average_cost == pytest.approx(100.5)

    def test_average_cost_across_two_buys(self):
        positions = build_positions(
            [
                txn("AAPL", "buy", 10, 100.0, days_ago=20, txn_id=1),
                txn("AAPL", "buy", 10, 200.0, days_ago=10, txn_id=2),
            ]
        )
        assert positions["AAPL"].average_cost == pytest.approx(150.0)

    def test_partial_sell_realises_profit_and_reduces_basis(self):
        """Buy 10 @ 100, sell 4 @ 130: realised = 4 × 30 = 120, 6 shares left."""
        positions = build_positions(
            [
                txn("AAPL", "buy", 10, 100.0, days_ago=20, txn_id=1),
                txn("AAPL", "sell", 4, 130.0, days_ago=5, txn_id=2),
            ]
        )
        position = positions["AAPL"]
        assert position.quantity == pytest.approx(6.0)
        assert position.realised_pnl == pytest.approx(120.0)
        assert position.cost_basis == pytest.approx(600.0)

    def test_sell_fees_reduce_realised_profit(self):
        positions = build_positions(
            [
                txn("AAPL", "buy", 10, 100.0, days_ago=20, txn_id=1),
                txn("AAPL", "sell", 4, 130.0, fees=10.0, days_ago=5, txn_id=2),
            ]
        )
        assert positions["AAPL"].realised_pnl == pytest.approx(110.0)

    def test_full_exit_zeroes_the_position(self):
        positions = build_positions(
            [
                txn("AAPL", "buy", 10, 100.0, days_ago=20, txn_id=1),
                txn("AAPL", "sell", 10, 120.0, days_ago=5, txn_id=2),
            ]
        )
        position = positions["AAPL"]
        assert position.quantity == 0
        assert position.cost_basis == 0
        assert position.realised_pnl == pytest.approx(200.0)

    def test_realised_loss_is_negative(self):
        positions = build_positions(
            [
                txn("AAPL", "buy", 10, 100.0, days_ago=20, txn_id=1),
                txn("AAPL", "sell", 10, 80.0, days_ago=5, txn_id=2),
            ]
        )
        assert positions["AAPL"].realised_pnl == pytest.approx(-200.0)

    def test_overselling_is_clamped_not_fatal(self):
        """A typo'd oversell must not crash or invent negative shares."""
        positions = build_positions(
            [
                txn("AAPL", "buy", 5, 100.0, days_ago=20, txn_id=1),
                txn("AAPL", "sell", 50, 120.0, days_ago=5, txn_id=2),
            ]
        )
        assert positions["AAPL"].quantity == 0

    def test_sell_without_any_position_is_ignored(self):
        positions = build_positions([txn("AAPL", "sell", 5, 100.0, days_ago=1)])
        assert positions["AAPL"].quantity == 0
        assert positions["AAPL"].realised_pnl == 0

    def test_transactions_are_folded_in_date_order(self):
        """Out-of-order input must not change the outcome."""
        ordered = build_positions(
            [
                txn("AAPL", "buy", 10, 100.0, days_ago=30, txn_id=1),
                txn("AAPL", "sell", 5, 150.0, days_ago=10, txn_id=2),
            ]
        )
        shuffled = build_positions(
            [
                txn("AAPL", "sell", 5, 150.0, days_ago=10, txn_id=2),
                txn("AAPL", "buy", 10, 100.0, days_ago=30, txn_id=1),
            ]
        )
        assert ordered["AAPL"].realised_pnl == pytest.approx(shuffled["AAPL"].realised_pnl)

    def test_symbols_are_tracked_separately(self):
        positions = build_positions(
            [
                txn("AAPL", "buy", 10, 100.0, days_ago=20, txn_id=1),
                txn("MSFT", "buy", 5, 200.0, days_ago=15, txn_id=2),
            ]
        )
        assert set(positions) == {"AAPL", "MSFT"}
        assert positions["MSFT"].cost_basis == pytest.approx(1000.0)


class TestSummarise:
    def _valued(self):
        return [
            {"symbol": "AAPL", "costBasis": 1000.0, "marketValue": 1300.0, "dayPnl": 20.0},
            {"symbol": "MSFT", "costBasis": 1000.0, "marketValue": 700.0, "dayPnl": -10.0},
        ]

    def test_totals_and_percentages(self):
        summary = summarise(self._valued(), {}, cash_balance=500.0)
        assert summary["invested"] == pytest.approx(2000.0)
        assert summary["marketValue"] == pytest.approx(2000.0)
        assert summary["totalValue"] == pytest.approx(2500.0)
        assert summary["unrealisedPnl"] == pytest.approx(0.0)
        assert summary["dayPnl"] == pytest.approx(10.0)

    def test_weights_are_assigned_and_sum_to_100(self):
        valued = self._valued()
        summarise(valued, {}, cash_balance=0.0)
        assert valued[0]["weight"] == pytest.approx(65.0)
        assert sum(item["weight"] for item in valued) == pytest.approx(100.0)

    def test_concentration_is_one_for_a_single_holding(self):
        summary = summarise(
            [{"symbol": "AAPL", "costBasis": 100.0, "marketValue": 100.0, "dayPnl": 0.0}],
            {},
        )
        assert summary["concentration"] == pytest.approx(1.0)

    def test_empty_portfolio_does_not_divide_by_zero(self):
        summary = summarise([], {}, cash_balance=0.0)
        assert summary["positionCount"] == 0
        assert summary["unrealisedPnlPercent"] == 0.0
        assert summary["totalValue"] == 0.0

    def test_stale_positions_are_named(self):
        summary = summarise(
            [
                {
                    "symbol": "DEAD", "costBasis": 100.0, "marketValue": None,
                    "dayPnl": None, "stale": True,
                }
            ],
            {},
        )
        assert summary["staleSymbols"] == ["DEAD"]

    def test_cost_basis_method_is_declared(self):
        assert summarise([], {})["costBasisMethod"] == "average"
