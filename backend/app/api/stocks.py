"""Market data endpoints: quotes, OHLC history, search and news."""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from ..errors import BadRequestError
from ..schemas import (
    HistoryQuerySchema,
    NewsQuerySchema,
    SearchQuerySchema,
    frame_to_records,
)
from ..services import market_data
from ..services.sentiment import aggregate_sentiment, score_headlines

logger = logging.getLogger(__name__)

bp = Blueprint("stocks", __name__, url_prefix="/api/stocks")

#: Guard on the bulk quote endpoint — one request should not fan out into a
#: hundred upstream calls.
MAX_BULK_SYMBOLS = 40


@bp.get("/search")
def search():
    """Search tickers by name or symbol."""
    params = SearchQuerySchema().load(request.args)
    results = market_data.search_symbols(params["q"], params["limit"])
    return jsonify({"query": params["q"], "results": results, "count": len(results)})


@bp.get("/<symbol>/quote")
def quote(symbol: str):
    """Current snapshot for one symbol."""
    return jsonify(market_data.fetch_quote(symbol).to_dict())


@bp.get("/quotes")
def bulk_quotes():
    """Snapshots for several symbols at once (``?symbols=AAPL,MSFT``).

    Individual failures are dropped rather than failing the batch, so the
    response may be shorter than the request.
    """
    raw = request.args.get("symbols", "")
    symbols = [s.strip() for s in raw.split(",") if s.strip()]

    if not symbols:
        raise BadRequestError("Provide at least one symbol via ?symbols=AAPL,MSFT.")
    if len(symbols) > MAX_BULK_SYMBOLS:
        raise BadRequestError(
            f"Too many symbols; the limit is {MAX_BULK_SYMBOLS} per request.",
            details={"requested": len(symbols), "limit": MAX_BULK_SYMBOLS},
        )

    quotes = market_data.fetch_quotes(symbols)
    return jsonify(
        {
            "quotes": quotes,
            "requested": len(symbols),
            "returned": len(quotes),
            "missing": sorted(
                {s.upper() for s in symbols} - {q["symbol"] for q in quotes}
            ),
        }
    )


@bp.get("/<symbol>/history")
def history(symbol: str):
    """OHLCV candles for charting."""
    params = HistoryQuerySchema().load(request.args)
    frame = market_data.fetch_history(
        symbol, period=params["period"], interval=params["interval"]
    )

    return jsonify(
        {
            "symbol": market_data.normalise_symbol(symbol),
            "period": params["period"],
            "interval": params["interval"],
            "candles": frame_to_records(frame),
            "count": len(frame),
            "start": str(frame.index[0].date()),
            "end": str(frame.index[-1].date()),
        }
    )


@bp.get("/<symbol>/news")
def news(symbol: str):
    """Recent headlines with per-article sentiment attached."""
    params = NewsQuerySchema().load(request.args)
    articles = market_data.fetch_news(symbol, limit=params["limit"])
    scored = score_headlines(articles)

    return jsonify(
        {
            "symbol": market_data.normalise_symbol(symbol),
            "articles": [item.to_dict() for item in scored],
            "sentiment": aggregate_sentiment(scored),
        }
    )
