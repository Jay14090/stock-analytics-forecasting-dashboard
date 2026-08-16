"""Portfolio endpoints: accounts, transactions, valuation and performance."""

from __future__ import annotations

import logging
from datetime import date

from flask import Blueprint, jsonify, request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..errors import ConflictError, NotFoundError
from ..extensions import db
from ..models import Portfolio, Transaction
from ..schemas import PortfolioCreateSchema, TransactionCreateSchema
from ..services import market_data
from ..services.portfolio_analytics import (
    build_equity_curve,
    build_positions,
    summarise,
    value_positions,
)

logger = logging.getLogger(__name__)

bp = Blueprint("portfolios", __name__, url_prefix="/api/portfolios")


def _get_or_404(portfolio_id: int) -> Portfolio:
    portfolio = db.session.get(Portfolio, portfolio_id)
    if portfolio is None:
        raise NotFoundError(f"Portfolio {portfolio_id} does not exist.")
    return portfolio


@bp.get("")
def list_portfolios():
    """All portfolios, summary only."""
    portfolios = db.session.scalars(select(Portfolio).order_by(Portfolio.name)).all()
    return jsonify({"portfolios": [p.to_dict() for p in portfolios]})


@bp.post("")
def create_portfolio():
    """Create a portfolio."""
    payload = PortfolioCreateSchema().load(request.get_json(silent=True) or {})
    portfolio = Portfolio(
        name=payload["name"].strip(),
        base_currency=payload["baseCurrency"].upper(),
        cash_balance=payload["cashBalance"],
    )

    db.session.add(portfolio)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ConflictError(f"A portfolio named '{payload['name']}' already exists.")

    return jsonify(portfolio.to_dict()), 201


@bp.delete("/<int:portfolio_id>")
def delete_portfolio(portfolio_id: int):
    """Delete a portfolio and its transaction history."""
    portfolio = _get_or_404(portfolio_id)
    db.session.delete(portfolio)
    db.session.commit()
    return jsonify({"id": portfolio_id, "deleted": True})


@bp.get("/<int:portfolio_id>")
def get_portfolio(portfolio_id: int):
    """Portfolio with live valuation, positions and allocation weights."""
    portfolio = _get_or_404(portfolio_id)

    positions = build_positions(portfolio.transactions)
    valued = value_positions(positions)
    summary = summarise(valued, positions, portfolio.cash_balance)

    # Transactions are included so the detail view renders the book, the
    # positions and the history from a single round trip.
    return jsonify(
        {
            **portfolio.to_dict(include_transactions=True),
            "summary": summary,
            "positions": valued,
            "closedPositions": [
                position.to_dict()
                for position in positions.values()
                if position.quantity <= 0
            ],
        }
    )


@bp.get("/<int:portfolio_id>/performance")
def performance(portfolio_id: int):
    """Daily equity curve with drawdown and Sharpe."""
    portfolio = _get_or_404(portfolio_id)
    period = request.args.get("period", "1y")
    curve = build_equity_curve(portfolio.transactions, period=period)
    return jsonify({"portfolioId": portfolio_id, "period": period, **curve})


@bp.get("/<int:portfolio_id>/transactions")
def list_transactions(portfolio_id: int):
    """Transaction history, newest first."""
    _get_or_404(portfolio_id)
    transactions = db.session.scalars(
        select(Transaction)
        .where(Transaction.portfolio_id == portfolio_id)
        .order_by(Transaction.traded_on.desc(), Transaction.id.desc())
    ).all()
    return jsonify({"transactions": [t.to_dict() for t in transactions]})


@bp.post("/<int:portfolio_id>/transactions")
def add_transaction(portfolio_id: int):
    """Record a buy or sell and apply its cash impact."""
    portfolio = _get_or_404(portfolio_id)
    payload = TransactionCreateSchema().load(request.get_json(silent=True) or {})

    # Validate the ticker upstream so the book cannot fill with typos.
    symbol = market_data.normalise_symbol(payload["symbol"])

    transaction = Transaction(
        portfolio_id=portfolio.id,
        symbol=symbol,
        kind=payload["kind"],
        quantity=payload["quantity"],
        price=payload["price"],
        fees=payload["fees"],
        traded_on=payload.get("tradedOn") or date.today(),
        note=payload.get("note"),
    )

    db.session.add(transaction)
    portfolio.cash_balance += transaction.cash_impact
    db.session.commit()

    return jsonify(transaction.to_dict()), 201


@bp.delete("/<int:portfolio_id>/transactions/<int:transaction_id>")
def delete_transaction(portfolio_id: int, transaction_id: int):
    """Remove a transaction and reverse its cash impact."""
    portfolio = _get_or_404(portfolio_id)
    transaction = db.session.get(Transaction, transaction_id)
    if transaction is None or transaction.portfolio_id != portfolio_id:
        raise NotFoundError(
            f"Transaction {transaction_id} is not in portfolio {portfolio_id}."
        )

    portfolio.cash_balance -= transaction.cash_impact
    db.session.delete(transaction)
    db.session.commit()
    return jsonify({"id": transaction_id, "deleted": True})
