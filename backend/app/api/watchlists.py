"""Watchlist CRUD, with optional live quotes attached."""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..errors import ConflictError, NotFoundError
from ..extensions import db
from ..models import Watchlist, WatchlistItem
from ..schemas import WatchlistCreateSchema, WatchlistItemCreateSchema
from ..services import market_data

logger = logging.getLogger(__name__)

bp = Blueprint("watchlists", __name__, url_prefix="/api/watchlists")


def _get_or_404(watchlist_id: int) -> Watchlist:
    watchlist = db.session.get(Watchlist, watchlist_id)
    if watchlist is None:
        raise NotFoundError(f"Watchlist {watchlist_id} does not exist.")
    return watchlist


@bp.get("")
def list_watchlists():
    """All watchlists, without quotes (cheap enough for a nav sidebar)."""
    watchlists = db.session.scalars(select(Watchlist).order_by(Watchlist.name)).all()
    return jsonify({"watchlists": [w.to_dict() for w in watchlists]})


@bp.post("")
def create_watchlist():
    """Create a watchlist."""
    payload = WatchlistCreateSchema().load(request.get_json(silent=True) or {})
    watchlist = Watchlist(name=payload["name"].strip())

    db.session.add(watchlist)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ConflictError(f"A watchlist named '{payload['name']}' already exists.")

    return jsonify(watchlist.to_dict()), 201


@bp.get("/<int:watchlist_id>")
def get_watchlist(watchlist_id: int):
    """One watchlist, with a live quote per symbol.

    ``?quotes=false`` skips the upstream calls when only the membership list is
    needed.
    """
    watchlist = _get_or_404(watchlist_id)
    payload = watchlist.to_dict()

    if request.args.get("quotes", "true").lower() != "false" and watchlist.items:
        quotes = {
            quote["symbol"]: quote
            for quote in market_data.fetch_quotes(item.symbol for item in watchlist.items)
        }
        for item in payload["items"]:
            item["quote"] = quotes.get(item["symbol"])

    return jsonify(payload)


@bp.delete("/<int:watchlist_id>")
def delete_watchlist(watchlist_id: int):
    """Delete a watchlist and its members."""
    watchlist = _get_or_404(watchlist_id)
    db.session.delete(watchlist)
    db.session.commit()
    return jsonify({"id": watchlist_id, "deleted": True})


@bp.post("/<int:watchlist_id>/items")
def add_item(watchlist_id: int):
    """Add a symbol. The ticker is validated upstream before it is stored."""
    watchlist = _get_or_404(watchlist_id)
    payload = WatchlistItemCreateSchema().load(request.get_json(silent=True) or {})

    # Resolve against the provider so the list cannot fill with typos.
    symbol = market_data.fetch_quote(payload["symbol"]).symbol

    item = WatchlistItem(
        watchlist_id=watchlist.id, symbol=symbol, note=payload.get("note")
    )
    db.session.add(item)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ConflictError(f"{symbol} is already in '{watchlist.name}'.")

    return jsonify(item.to_dict()), 201


@bp.delete("/<int:watchlist_id>/items/<int:item_id>")
def remove_item(watchlist_id: int, item_id: int):
    """Remove a symbol from a watchlist."""
    _get_or_404(watchlist_id)
    item = db.session.get(WatchlistItem, item_id)
    if item is None or item.watchlist_id != watchlist_id:
        raise NotFoundError(f"Item {item_id} is not in watchlist {watchlist_id}.")

    db.session.delete(item)
    db.session.commit()
    return jsonify({"id": item_id, "deleted": True})
