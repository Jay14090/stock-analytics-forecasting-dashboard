"""Portfolio ORM models.

A portfolio owns transactions; holdings are *derived* from them rather than
stored. Keeping a mutable quantity column next to an append-only transaction
log gives you two sources of truth that drift, and the drift always surfaces as
a wrong P&L number nobody can explain.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import Date, DateTime, Enum, Float, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db

TRANSACTION_KINDS = ("buy", "sell")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Portfolio(db.Model):
    """A named account holding a transaction history."""

    __tablename__ = "portfolios"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    base_currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)
    cash_balance: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )

    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="portfolio",
        cascade="all, delete-orphan",
        order_by="Transaction.traded_on",
        lazy="selectin",
    )

    def to_dict(self, include_transactions: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "baseCurrency": self.base_currency,
            "cashBalance": round(self.cash_balance, 2),
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "transactionCount": len(self.transactions),
        }
        if include_transactions:
            payload["transactions"] = [t.to_dict() for t in self.transactions]
        return payload

    def __repr__(self) -> str:
        return f"<Portfolio {self.name!r}>"


class Transaction(db.Model):
    """A single buy or sell.

    Fees are stored separately from price so cost basis and realised P&L can
    both be computed correctly: fees increase the basis on a buy and reduce
    proceeds on a sell.
    """

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(
        Enum(*TRANSACTION_KINDS, name="transaction_kind"), nullable=False
    )
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    fees: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    traded_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    note: Mapped[str | None] = mapped_column(String(280))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )

    portfolio: Mapped[Portfolio] = relationship(back_populates="transactions")

    @property
    def gross_value(self) -> float:
        """Quantity × price, before fees."""
        return self.quantity * self.price

    @property
    def cash_impact(self) -> float:
        """Signed effect on cash: a buy consumes it, a sell releases it."""
        if self.kind == "buy":
            return -(self.gross_value + self.fees)
        return self.gross_value - self.fees

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "portfolioId": self.portfolio_id,
            "symbol": self.symbol,
            "kind": self.kind,
            "quantity": self.quantity,
            "price": self.price,
            "fees": self.fees,
            "grossValue": round(self.gross_value, 2),
            "cashImpact": round(self.cash_impact, 2),
            "tradedOn": self.traded_on.isoformat() if self.traded_on else None,
            "note": self.note,
        }

    def __repr__(self) -> str:
        return f"<Transaction {self.kind} {self.quantity}×{self.symbol}@{self.price}>"
