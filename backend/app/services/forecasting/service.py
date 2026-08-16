"""Training and inference orchestration for the LSTM forecaster.

The model predicts the **next day's log return**, not the price. Two reasons:

* A network trained on raw prices memorises the level of its training window
  and fails as soon as the stock trades outside it.
* Log returns are additive, so a multi-step path reconstructs exactly by
  cumulative summation rather than by compounding rounding error.

Multi-step forecasts are produced recursively: predict one step, synthesise the
bar that return implies, recompute the features, predict again. Recursive
forecasting compounds its own error, so the intervals widen with the horizon
and the API reports the horizon explicitly.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
from flask import current_app

from ...errors import InsufficientDataError, ModelUnavailableError
from .dataset import (
    FEATURE_COLUMNS,
    MinMaxScaler,
    build_features,
    latest_window,
    prepare_dataset,
)
from .model import build_model, evaluate_forecast, require_tensorflow, training_callbacks
from .registry import ModelMetadata, ModelRegistry

logger = logging.getLogger(__name__)

#: Training is CPU-bound and memory-hungry; one symbol at a time per process
#: keeps a burst of requests from thrashing the machine.
_training_lock = threading.Lock()

#: 95% interval under a normal approximation of the residuals.
_Z_SCORE_95 = 1.96


@dataclass(slots=True)
class ForecastPoint:
    date: str
    predicted_close: float
    lower_bound: float
    upper_bound: float
    predicted_return: float
    step: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "predictedClose": round(self.predicted_close, 4),
            "lowerBound": round(self.lower_bound, 4),
            "upperBound": round(self.upper_bound, 4),
            "predictedReturn": round(self.predicted_return, 6),
            "step": self.step,
        }


def get_registry() -> ModelRegistry:
    """Registry rooted at the configured model directory."""
    return ModelRegistry(current_app.config["MODEL_DIR"])


def _future_trading_days(last_date: pd.Timestamp, steps: int) -> list[pd.Timestamp]:
    """Next ``steps`` weekdays after ``last_date``.

    Weekday-only, deliberately: exchange holiday calendars differ per market
    and a wrong calendar is worse than an honest approximation. The labels are
    display dates for a forecast, not settlement dates.
    """
    days: list[pd.Timestamp] = []
    cursor = last_date
    while len(days) < steps:
        cursor = cursor + pd.Timedelta(days=1)
        if cursor.weekday() < 5:
            days.append(cursor)
    return days


def _synthesise_bar(
    frame: pd.DataFrame, predicted_return: float
) -> dict[str, float]:
    """Build the OHLCV bar implied by a predicted return.

    Only the close is predicted. High, low and volume are filled from recent
    behaviour so the indicator features can be recomputed for the next step;
    they are scaffolding for the recursion, never presented as forecasts.
    """
    last_close = float(frame["close"].iloc[-1])
    next_close = last_close * float(np.exp(predicted_return))

    recent = frame.tail(20)
    typical_range = float(((recent["high"] - recent["low"]) / recent["close"]).mean())
    if not np.isfinite(typical_range) or typical_range <= 0:
        typical_range = 0.02

    half_range = next_close * typical_range / 2
    return {
        "open": last_close,
        "high": max(last_close, next_close) + half_range,
        "low": min(last_close, next_close) - half_range,
        "close": next_close,
        "volume": float(recent["volume"].mean()),
    }


def _predict_scaled(model, window: np.ndarray, target_scaler: MinMaxScaler) -> float:
    """Run one forward pass and invert the target scaling."""
    scaled = model.predict(window, verbose=0)
    return float(target_scaler.inverse_transform(scaled.reshape(-1, 1))[0, 0])


def train_symbol(symbol: str, frame: pd.DataFrame, *, force: bool = False) -> ModelMetadata:
    """Train and persist a model for ``symbol``.

    Args:
        symbol: Ticker the model belongs to.
        frame: OHLCV history, oldest first.
        force: Retrain even if a fresh model already exists.

    Raises:
        ModelUnavailableError: TensorFlow is not installed.
        InsufficientDataError: not enough history to train honestly.
    """
    config = current_app.config
    registry = get_registry()
    last_date = str(frame.index[-1].date())

    if not force:
        existing = registry.load_metadata(symbol)
        if existing and not existing.is_stale(config["MODEL_MAX_AGE_HOURS"], last_date):
            logger.debug("model_reused symbol=%s trained_at=%s", symbol, existing.trained_at)
            return existing

    if len(frame) < config["MIN_TRAINING_ROWS"]:
        raise InsufficientDataError(
            f"Training needs at least {config['MIN_TRAINING_ROWS']} sessions of "
            f"history; {symbol} has {len(frame)}.",
            details={"required": config["MIN_TRAINING_ROWS"], "available": len(frame)},
        )

    try:
        tf = require_tensorflow()
    except RuntimeError as exc:
        raise ModelUnavailableError(str(exc)) from exc

    try:
        dataset = prepare_dataset(
            frame,
            sequence_length=config["SEQUENCE_LENGTH"],
            validation_split=config["VALIDATION_SPLIT"],
        )
    except ValueError as exc:
        raise InsufficientDataError(str(exc)) from exc

    # Serialise training: two concurrent Keras fits on one CPU are slower than
    # running them back to back, and memory spikes cause hard failures.
    with _training_lock:
        started = time.perf_counter()
        model = build_model(
            sequence_length=config["SEQUENCE_LENGTH"], n_features=dataset.n_features
        )
        history = model.fit(
            dataset.x_train,
            dataset.y_train,
            validation_data=(dataset.x_validation, dataset.y_validation),
            epochs=config["TRAIN_EPOCHS"],
            batch_size=config["TRAIN_BATCH_SIZE"],
            callbacks=training_callbacks(),
            shuffle=False,  # windows are ordered; shuffling leaks structure
            verbose=0,
        )
        elapsed = time.perf_counter() - started

    # Score in return space, not scaled space, so the numbers mean something.
    predictions_scaled = model.predict(dataset.x_validation, verbose=0).reshape(-1, 1)
    predicted_returns = dataset.target_scaler.inverse_transform(predictions_scaled).reshape(-1)
    actual_returns = dataset.target_scaler.inverse_transform(
        dataset.y_validation.reshape(-1, 1)
    ).reshape(-1)

    metrics = evaluate_forecast(actual_returns, predicted_returns)
    metrics["residualStd"] = round(float(np.std(actual_returns - predicted_returns)), 8)
    metrics["trainingSeconds"] = round(elapsed, 2)

    metadata = ModelMetadata(
        symbol=symbol,
        trained_at=datetime.now(timezone.utc).isoformat(),
        sequence_length=config["SEQUENCE_LENGTH"],
        horizon=config["FORECAST_HORIZON"],
        features=list(FEATURE_COLUMNS),
        metrics=metrics,
        training_rows=int(len(dataset.x_train)),
        epochs_run=int(len(history.history.get("loss", []))),
        feature_scaler=dataset.feature_scaler.to_dict(),
        target_scaler=dataset.target_scaler.to_dict(),
        last_close=float(frame["close"].iloc[-1]),
        last_date=last_date,
        history={
            "loss": [round(float(v), 6) for v in history.history.get("loss", [])],
            "valLoss": [round(float(v), 6) for v in history.history.get("val_loss", [])],
        },
    )

    registry.save(symbol, model, metadata)
    logger.info(
        "model_trained symbol=%s epochs=%d seconds=%.1f skill=%.3f",
        symbol, metadata.epochs_run, elapsed, metrics["skillScore"],
    )
    return metadata


def forecast_symbol(
    symbol: str,
    frame: pd.DataFrame,
    horizon: int | None = None,
    *,
    retrain: bool = False,
) -> dict[str, Any]:
    """Produce a multi-step forecast, training first if needed.

    Returns a payload with the forecast path, the model's validation metrics
    and provenance describing when it was trained.
    """
    config = current_app.config
    horizon = int(horizon or config["FORECAST_HORIZON"])
    horizon = max(1, min(horizon, 30))

    metadata = train_symbol(symbol, frame, force=retrain)

    registry = get_registry()
    model = registry.load_model(symbol)
    if model is None:
        # Artefact missing or unreadable — rebuild once rather than fail.
        logger.warning("model_missing_retraining symbol=%s", symbol)
        metadata = train_symbol(symbol, frame, force=True)
        model = registry.load_model(symbol)
        if model is None:
            raise ModelUnavailableError(
                f"Could not load or rebuild a model for {symbol}."
            )

    feature_scaler, target_scaler = metadata.scalers()
    sequence_length = metadata.sequence_length

    working = frame.copy()
    features = build_features(working).dropna()
    if len(features) < sequence_length:
        raise InsufficientDataError(
            f"Need {sequence_length} clean sessions to forecast; got {len(features)}.",
            details={"required": sequence_length, "available": len(features)},
        )

    residual_std = float(metadata.metrics.get("residualStd", 0.0)) or float(
        np.std(features["log_return"].tail(60))
    )

    last_close = float(working["close"].iloc[-1])
    dates = _future_trading_days(working.index[-1], horizon)

    points: list[ForecastPoint] = []
    cumulative_return = 0.0

    for step in range(1, horizon + 1):
        window = latest_window(features, feature_scaler, sequence_length)
        predicted_return = _predict_scaled(model, window, target_scaler)

        # Guard against a pathological output moving the path 50% in a day.
        predicted_return = float(np.clip(predicted_return, -0.25, 0.25))
        cumulative_return += predicted_return

        predicted_close = last_close * float(np.exp(cumulative_return))

        # Errors accumulate like a random walk, so the band grows with sqrt(h).
        interval = _Z_SCORE_95 * residual_std * np.sqrt(step)
        lower = last_close * float(np.exp(cumulative_return - interval))
        upper = last_close * float(np.exp(cumulative_return + interval))

        points.append(
            ForecastPoint(
                date=str(dates[step - 1].date()),
                predicted_close=predicted_close,
                lower_bound=lower,
                upper_bound=upper,
                predicted_return=predicted_return,
                step=step,
            )
        )

        if step < horizon:
            synthetic = _synthesise_bar(working, predicted_return)
            working.loc[dates[step - 1]] = synthetic
            features = build_features(working).dropna()

    final_close = points[-1].predicted_close
    total_change = (final_close - last_close) / last_close * 100

    return {
        "symbol": symbol,
        "horizon": horizon,
        "lastClose": round(last_close, 4),
        "lastDate": metadata.last_date,
        "forecast": [point.to_dict() for point in points],
        "expectedChangePercent": round(total_change, 4),
        "metrics": metadata.metrics,
        "model": {
            "trainedAt": metadata.trained_at,
            "sequenceLength": metadata.sequence_length,
            "trainingRows": metadata.training_rows,
            "epochsRun": metadata.epochs_run,
            "features": metadata.features,
            "architecture": "LSTM(64) → Dropout → LSTM(32) → Dropout → Dense(16) → Dense(1)",
            "target": "next-day log return",
        },
        "disclaimer": (
            "Forecasts are recursive and compound their own error; the interval "
            "widens with the horizon. Research output, not investment advice."
        ),
    }
