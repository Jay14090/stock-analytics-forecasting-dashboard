"""Watchlist ORM models."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Watchlist(db.Model):
    """A named collection of tickers."""

    __tablename__ = "watchlists"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )

    items: Mapped[list["WatchlistItem"]] = relationship(
        back_populates="watchlist",
        cascade="all, delete-orphan",
        order_by="WatchlistItem.created_at",
        lazy="selectin",
    )

    def to_dict(self, include_items: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "symbolCount": len(self.items),
        }
        if include_items:
            payload["items"] = [item.to_dict() for item in self.items]
        return payload

    def __repr__(self) -> str:
        return f"<Watchlist {self.name!r} items={len(self.items)}>"


class WatchlistItem(db.Model):
    """One ticker inside a watchlist."""

    __tablename__ = "watchlist_items"
    __table_args__ = (
        # The same ticker twice in one list is always a mistake; across lists
        # it is normal.
        UniqueConstraint("watchlist_id", "symbol", name="uq_watchlist_symbol"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    watchlist_id: Mapped[int] = mapped_column(
        ForeignKey("watchlists.id", ondelete="CASCADE"), nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    note: Mapped[str | None] = mapped_column(String(280))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )

    watchlist: Mapped[Watchlist] = relationship(back_populates="items")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "note": self.note,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<WatchlistItem {self.symbol!r}>"
