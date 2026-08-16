"""Yahoo Finance access layer.

Everything that talks to the network lives here. The rest of the application
consumes normalised pandas frames and plain dictionaries and never imports
``yfinance`` directly, which keeps the provider swappable and makes the
services testable without a socket.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

import pandas as pd
import yfinance as yf
from flask import current_app

from ..errors import InsufficientDataError, NotFoundError, UpstreamError
from .cache import market_cache

logger = logging.getLogger(__name__)

#: Yahoo tickers: letters, digits and a small set of separators (BRK-B, ^NSEI,
#: RELIANCE.NS, BTC-USD). Anything else is rejected before it reaches the wire.
_SYMBOL_RE = re.compile(r"^[A-Za-z0-9.\-^=]{1,20}$")

_VALID_RANGES = {
    "1mo": 30, "3mo": 90, "6mo": 180, "1y": 365,
    "2y": 730, "5y": 1825, "10y": 3650, "max": 0,
}

_VALID_INTERVALS = {"1d", "1wk", "1mo"}

_OHLCV = ["open", "high", "low", "close", "volume"]


class RetryPolicy:
    """Bounded exponential backoff for transient upstream failures."""

    def __init__(self, attempts: int = 3, base_delay: float = 0.4) -> None:
        self.attempts = attempts
        self.base_delay = base_delay

    def run(self, operation, *, description: str):
        last_error: Exception | None = None
        for attempt in range(1, self.attempts + 1):
            try:
                return operation()
            except Exception as exc:  # noqa: BLE001 - provider raises bare Exception
                last_error = exc
                if attempt == self.attempts:
                    break
                delay = self.base_delay * (2 ** (attempt - 1))
                logger.warning(
                    "upstream_retry op=%s attempt=%d/%d delay=%.2fs error=%s",
                    description, attempt, self.attempts, delay, exc,
                )
                time.sleep(delay)
        raise UpstreamError(
            f"Failed to fetch {description} after {self.attempts} attempts.",
            details={"reason": str(last_error)},
        )


@dataclass(slots=True)
class Quote:
    """A point-in-time snapshot of a symbol."""

    symbol: str
    name: str
    price: float
    previous_close: float
    change: float
    change_percent: float
    currency: str
    exchange: str
    market_cap: float | None = None
    volume: int | None = None
    day_high: float | None = None
    day_low: float | None = None
    fifty_two_week_high: float | None = None
    fifty_two_week_low: float | None = None
    sector: str | None = None
    industry: str | None = None
    as_of: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "price": self.price,
            "previousClose": self.previous_close,
            "change": self.change,
            "changePercent": self.change_percent,
            "currency": self.currency,
            "exchange": self.exchange,
            "marketCap": self.market_cap,
            "volume": self.volume,
            "dayHigh": self.day_high,
            "dayLow": self.day_low,
            "fiftyTwoWeekHigh": self.fifty_two_week_high,
            "fiftyTwoWeekLow": self.fifty_two_week_low,
            "sector": self.sector,
            "industry": self.industry,
            "asOf": self.as_of,
        }


def normalise_symbol(symbol: str) -> str:
    """Validate and canonicalise a ticker.

    Raises:
        NotFoundError: if the string cannot be a ticker at all. Rejecting here
            avoids handing arbitrary user input to the provider.
    """
    if not symbol:
        raise NotFoundError("A ticker symbol is required.")
    cleaned = symbol.strip().upper()
    if not _SYMBOL_RE.match(cleaned):
        raise NotFoundError(
            f"'{symbol}' is not a valid ticker symbol.",
            details={"symbol": symbol},
        )
    return cleaned


def _as_float(value: Any) -> float | None:
    """Coerce provider values to float, tolerating None/NaN/strings."""
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result:  # NaN
        return None
    return result


def _flatten_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """yfinance returns a MultiIndex when several tickers are requested."""
    if isinstance(frame.columns, pd.MultiIndex):
        frame = frame.copy()
        frame.columns = [str(col[0]) for col in frame.columns]
    return frame


def _normalise_history(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Return a tz-naive, lower-cased, gap-free OHLCV frame indexed by date."""
    if frame is None or frame.empty:
        raise NotFoundError(
            f"No price history available for '{symbol}'.",
            details={"symbol": symbol},
        )

    frame = _flatten_columns(frame).copy()
    frame.columns = [str(col).strip().lower().replace(" ", "_") for col in frame.columns]

    missing = [col for col in _OHLCV if col not in frame.columns]
    if missing:
        raise UpstreamError(
            f"Price history for '{symbol}' is missing columns: {', '.join(missing)}.",
            details={"symbol": symbol, "missing": missing},
        )

    frame = frame[_OHLCV]

    if isinstance(frame.index, pd.DatetimeIndex) and frame.index.tz is not None:
        frame.index = frame.index.tz_localize(None)
    frame.index = pd.to_datetime(frame.index).normalize()
    frame.index.name = "date"

    # A row without a close is unusable; a zero-volume day is legitimate
    # (holidays, thin small caps) and is kept.
    frame = frame[~frame.index.duplicated(keep="last")]
    frame = frame.dropna(subset=["close"]).sort_index()

    if frame.empty:
        raise NotFoundError(
            f"No usable price history for '{symbol}'.", details={"symbol": symbol}
        )
    return frame


def fetch_history(
    symbol: str,
    period: str = "2y",
    interval: str = "1d",
    *,
    use_cache: bool = True,
) -> pd.DataFrame:
    """Fetch normalised OHLCV history for one symbol.

    Args:
        symbol: Ticker, validated before use.
        period: One of ``_VALID_RANGES``.
        interval: One of ``_VALID_INTERVALS``.
        use_cache: Set False to force a live read.

    Returns:
        DataFrame indexed by date with open/high/low/close/volume columns.
    """
    symbol = normalise_symbol(symbol)
    if period not in _VALID_RANGES:
        raise NotFoundError(
            f"Unsupported period '{period}'.",
            details={"supported": sorted(_VALID_RANGES)},
        )
    if interval not in _VALID_INTERVALS:
        raise NotFoundError(
            f"Unsupported interval '{interval}'.",
            details={"supported": sorted(_VALID_INTERVALS)},
        )

    cache_key = f"history:{symbol}:{period}:{interval}"
    ttl = current_app.config["HISTORY_CACHE_TTL"] if use_cache else 0

    def _load() -> pd.DataFrame:
        retry = RetryPolicy()
        raw = retry.run(
            lambda: yf.Ticker(symbol).history(
                period=period, interval=interval, auto_adjust=True, timeout=
                current_app.config["MARKET_DATA_TIMEOUT"],
            ),
            description=f"history for {symbol}",
        )
        return _normalise_history(raw, symbol)

    if ttl <= 0:
        return _load()
    return market_cache.get_or_set(cache_key, ttl, _load)


def fetch_quote(symbol: str) -> Quote:
    """Fetch a current snapshot, falling back to daily bars for the price.

    ``Ticker.info`` is the richest source but is also the flakiest endpoint
    Yahoo exposes, so the last two closes are used to derive price and change
    whenever ``info`` is thin or unavailable.
    """
    symbol = normalise_symbol(symbol)
    cache_key = f"quote:{symbol}"
    ttl = current_app.config["QUOTE_CACHE_TTL"]

    def _load() -> Quote:
        retry = RetryPolicy()
        ticker = yf.Ticker(symbol)

        info: dict[str, Any] = {}
        try:
            info = retry.run(lambda: ticker.info or {}, description=f"info for {symbol}")
        except UpstreamError:
            logger.warning("quote_info_unavailable symbol=%s falling_back=history", symbol)

        history = fetch_history(symbol, period="1mo", interval="1d")
        closes = history["close"]
        last_close = float(closes.iloc[-1])
        prior_close = float(closes.iloc[-2]) if len(closes) > 1 else last_close

        price = _as_float(info.get("currentMarketPrice")) or _as_float(
            info.get("regularMarketPrice")
        ) or last_close
        previous_close = (
            _as_float(info.get("regularMarketPreviousClose")) or prior_close
        )
        change = price - previous_close
        change_percent = (change / previous_close * 100) if previous_close else 0.0

        name = (
            info.get("longName")
            or info.get("shortName")
            or info.get("displayName")
            or symbol
        )
        if not info and history.empty:
            raise NotFoundError(f"Unknown ticker '{symbol}'.", details={"symbol": symbol})

        return Quote(
            symbol=symbol,
            name=str(name),
            price=round(price, 4),
            previous_close=round(previous_close, 4),
            change=round(change, 4),
            change_percent=round(change_percent, 4),
            currency=str(info.get("currency") or "USD"),
            exchange=str(info.get("fullExchangeName") or info.get("exchange") or "—"),
            market_cap=_as_float(info.get("marketCap")),
            volume=int(history["volume"].iloc[-1]) if len(history) else None,
            day_high=_as_float(info.get("dayHigh")) or float(history["high"].iloc[-1]),
            day_low=_as_float(info.get("dayLow")) or float(history["low"].iloc[-1]),
            fifty_two_week_high=_as_float(info.get("fiftyTwoWeekHigh")),
            fifty_two_week_low=_as_float(info.get("fiftyTwoWeekLow")),
            sector=info.get("sector"),
            industry=info.get("industry"),
        )

    if ttl <= 0:
        return _load()
    return market_cache.get_or_set(cache_key, ttl, _load)


def fetch_quotes(symbols: Iterable[str]) -> list[dict[str, Any]]:
    """Fetch several quotes, skipping the ones that fail.

    A watchlist with one delisted ticker should still render, so per-symbol
    failures are logged and dropped rather than failing the whole request.
    """
    results: list[dict[str, Any]] = []
    for raw_symbol in symbols:
        try:
            results.append(fetch_quote(raw_symbol).to_dict())
        except (NotFoundError, UpstreamError) as exc:
            logger.warning("quote_skipped symbol=%s reason=%s", raw_symbol, exc.message)
    return results


def search_symbols(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Look up tickers by company name or partial symbol."""
    query = (query or "").strip()
    if len(query) < 2:
        raise NotFoundError("Search needs at least two characters.")

    cache_key = f"search:{query.lower()}:{limit}"

    def _load() -> list[dict[str, Any]]:
        retry = RetryPolicy(attempts=2)
        try:
            raw = retry.run(
                lambda: yf.Search(query, max_results=limit).quotes,
                description=f"search for {query!r}",
            )
        except UpstreamError:
            return []

        matches: list[dict[str, Any]] = []
        for item in raw or []:
            symbol = item.get("symbol")
            if not symbol:
                continue
            matches.append(
                {
                    "symbol": symbol,
                    "name": item.get("longname") or item.get("shortname") or symbol,
                    "exchange": item.get("exchDisp") or item.get("exchange") or "—",
                    "type": item.get("quoteType") or "EQUITY",
                }
            )
        return matches[:limit]

    return market_cache.get_or_set(cache_key, current_app.config["NEWS_CACHE_TTL"], _load)


def fetch_news(symbol: str, limit: int = 20) -> list[dict[str, Any]]:
    """Fetch recent headlines for a symbol.

    News is decoration on a chart, never the reason a request fails, so an
    upstream error here degrades to an empty list.
    """
    symbol = normalise_symbol(symbol)
    cache_key = f"news:{symbol}:{limit}"

    def _load() -> list[dict[str, Any]]:
        try:
            retry = RetryPolicy(attempts=2)
            raw = retry.run(lambda: yf.Ticker(symbol).news or [], description=f"news for {symbol}")
        except UpstreamError:
            logger.warning("news_unavailable symbol=%s", symbol)
            return []

        articles: list[dict[str, Any]] = []
        for item in raw[:limit]:
            # yfinance moved news under a "content" envelope; support both.
            content = item.get("content") if isinstance(item.get("content"), dict) else item
            title = content.get("title") or item.get("title")
            if not title:
                continue

            published = (
                content.get("pubDate")
                or content.get("displayTime")
                or item.get("providerPublishTime")
            )
            if isinstance(published, (int, float)):
                published = datetime.fromtimestamp(published, tz=timezone.utc).isoformat()

            provider = content.get("provider")
            publisher = (
                provider.get("displayName")
                if isinstance(provider, dict)
                else item.get("publisher")
            )

            link = content.get("canonicalUrl") or {}
            url = link.get("url") if isinstance(link, dict) else None

            articles.append(
                {
                    "id": str(item.get("id") or content.get("id") or title)[:120],
                    "title": str(title),
                    "summary": str(content.get("summary") or content.get("description") or ""),
                    "publisher": str(publisher or "Unknown"),
                    "url": url or item.get("link"),
                    "publishedAt": published,
                }
            )
        return articles

    return market_cache.get_or_set(cache_key, current_app.config["NEWS_CACHE_TTL"], _load)


def require_min_rows(frame: pd.DataFrame, minimum: int, *, operation: str) -> None:
    """Guard an analysis that needs a minimum series length."""
    if len(frame) < minimum:
        raise InsufficientDataError(
            f"{operation} needs at least {minimum} rows of history; got {len(frame)}.",
            details={"required": minimum, "available": len(frame)},
        )
