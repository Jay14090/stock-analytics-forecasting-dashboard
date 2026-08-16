"""Analysis endpoints: indicators, LSTM forecasts, signals and screening."""

from __future__ import annotations

import logging

from flask import Blueprint, current_app, jsonify, request

from ..errors import BadRequestError, NotFoundError, UpstreamError
from ..schemas import (
    ForecastQuerySchema,
    IndicatorQuerySchema,
    ScreenQuerySchema,
    SignalQuerySchema,
    TrainRequestSchema,
    frame_to_records,
)
from ..services import market_data
from ..services.forecasting import (
    forecast_symbol,
    get_registry,
    tensorflow_available,
    train_symbol,
)
from ..services.indicators import compute_indicators, max_drawdown, sharpe_ratio
from ..services.sentiment import aggregate_sentiment, score_headlines
from ..services.signals import generate_signal

logger = logging.getLogger(__name__)

bp = Blueprint("analysis", __name__, url_prefix="/api")

#: Screening runs a full indicator pass per symbol; keep the fan-out bounded.
MAX_SCREEN_SYMBOLS = 25


@bp.get("/indicators/<symbol>")
def indicators(symbol: str):
    """Full technical indicator panel aligned to the price history."""
    params = IndicatorQuerySchema().load(request.args)
    frame = market_data.fetch_history(
        symbol, period=params["period"], interval=params["interval"]
    )
    panel = compute_indicators(frame)

    requested = params.get("indicators")
    if requested:
        wanted = [name.strip() for name in requested.split(",") if name.strip()]
        unknown = [name for name in wanted if name not in panel.columns]
        if unknown:
            raise BadRequestError(
                f"Unknown indicator(s): {', '.join(unknown)}.",
                details={"available": sorted(panel.columns)},
            )
        panel = panel[wanted]

    close = frame["close"]
    return jsonify(
        {
            "symbol": market_data.normalise_symbol(symbol),
            "period": params["period"],
            "indicators": frame_to_records(panel),
            "available": sorted(panel.columns),
            "statistics": {
                "maxDrawdownPercent": round(max_drawdown(close) * 100, 4),
                "sharpeRatio": round(sharpe_ratio(close), 4),
                "totalReturnPercent": round(
                    (float(close.iloc[-1]) / float(close.iloc[0]) - 1) * 100, 4
                ),
            },
        }
    )


@bp.get("/forecast/<symbol>")
def forecast(symbol: str):
    """Multi-step LSTM forecast, training the model on demand."""
    params = ForecastQuerySchema().load(request.args)
    symbol = market_data.normalise_symbol(symbol)

    frame = market_data.fetch_history(symbol, period=params["period"])
    payload = forecast_symbol(
        symbol, frame, horizon=params["horizon"], retrain=params["retrain"]
    )
    return jsonify(payload)


@bp.post("/forecast/<symbol>/train")
def train(symbol: str):
    """Force a retrain and return the resulting metrics.

    Synchronous on purpose: a single-process deployment has nowhere to put a
    background job, and pretending a training run finished when it has not is
    worse than making the caller wait.
    """
    params = TrainRequestSchema().load(request.get_json(silent=True) or {})
    symbol = market_data.normalise_symbol(symbol)

    frame = market_data.fetch_history(symbol, period=params["period"])
    metadata = train_symbol(symbol, frame, force=params["force"])

    return jsonify(
        {
            "symbol": symbol,
            "trainedAt": metadata.trained_at,
            "metrics": metadata.metrics,
            "trainingRows": metadata.training_rows,
            "epochsRun": metadata.epochs_run,
            "history": metadata.history,
        }
    )


@bp.get("/models")
def list_models():
    """Every trained model currently on disk."""
    return jsonify(
        {
            "tensorflowAvailable": tensorflow_available(),
            "models": get_registry().list_models(),
        }
    )


@bp.delete("/models/<symbol>")
def delete_model(symbol: str):
    """Evict a trained model so the next forecast retrains from scratch."""
    symbol = market_data.normalise_symbol(symbol)
    if not get_registry().delete(symbol):
        raise NotFoundError(f"No trained model stored for {symbol}.")
    return jsonify({"symbol": symbol, "deleted": True})


def _sentiment_for(symbol: str) -> dict | None:
    """Best-effort sentiment; never fails the caller."""
    try:
        return aggregate_sentiment(score_headlines(market_data.fetch_news(symbol, limit=15)))
    except (NotFoundError, UpstreamError) as exc:
        logger.info("sentiment_skipped symbol=%s reason=%s", symbol, exc.message)
        return None


@bp.get("/signals/<symbol>")
def signal(symbol: str):
    """Buy/sell/hold recommendation with the full rule breakdown."""
    params = SignalQuerySchema().load(request.args)
    symbol = market_data.normalise_symbol(symbol)

    frame = market_data.fetch_history(symbol, period=params["period"])
    panel = compute_indicators(frame)

    sentiment = _sentiment_for(symbol) if params["include_sentiment"] else None

    forecast_payload = None
    if params["include_forecast"]:
        try:
            forecast_payload = forecast_symbol(symbol, frame)
        except Exception as exc:  # noqa: BLE001 - forecast is an optional input
            logger.warning("signal_forecast_skipped symbol=%s error=%s", symbol, exc)

    return jsonify(
        generate_signal(
            frame,
            symbol=symbol,
            forecast=forecast_payload,
            sentiment=sentiment,
            indicators=panel,
        )
    )


@bp.get("/signals")
def screen():
    """Run the signal engine across several symbols (``?symbols=AAPL,MSFT``)."""
    params = ScreenQuerySchema().load(request.args)
    symbols = [s.strip().upper() for s in params["symbols"].split(",") if s.strip()]

    if not symbols:
        raise BadRequestError("Provide at least one symbol.")
    if len(symbols) > MAX_SCREEN_SYMBOLS:
        raise BadRequestError(
            f"Screening is limited to {MAX_SCREEN_SYMBOLS} symbols per request.",
            details={"requested": len(symbols), "limit": MAX_SCREEN_SYMBOLS},
        )

    results: list[dict] = []
    failures: list[dict] = []

    for symbol in symbols:
        try:
            frame = market_data.fetch_history(symbol, period=params["period"])
            sentiment = _sentiment_for(symbol) if params["include_sentiment"] else None
            results.append(
                generate_signal(frame, symbol=symbol, sentiment=sentiment)
            )
        except Exception as exc:  # noqa: BLE001 - report, never abort the screen
            message = getattr(exc, "message", str(exc))
            logger.warning("screen_symbol_failed symbol=%s reason=%s", symbol, message)
            failures.append({"symbol": symbol, "reason": message})

    results.sort(key=lambda item: item["score"], reverse=True)
    return jsonify(
        {
            "results": results,
            "failures": failures,
            "evaluated": len(results),
            "period": params["period"],
        }
    )
