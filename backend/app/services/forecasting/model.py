"""LSTM architecture and metrics.

TensorFlow is imported lazily. It is a heavy optional dependency, and the rest
of the dashboard — charts, indicators, portfolio, signals — must keep working
on a deployment that never installs it. :func:`require_tensorflow` is the one
place that decides whether the forecasting feature is available.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

_tensorflow: Any | None = None
_import_error: str | None = None

#: Fixed seed so a retrain of the same symbol on the same data is reproducible.
RANDOM_SEED = 42


def tensorflow_available() -> bool:
    """True when the deep-learning stack can be imported."""
    try:
        require_tensorflow()
    except RuntimeError:
        return False
    return True


def require_tensorflow():
    """Import TensorFlow once and cache the module.

    Raises:
        RuntimeError: with the original import failure, so the API can return
            a 503 that explains itself instead of a generic 500.
    """
    global _tensorflow, _import_error

    if _tensorflow is not None:
        return _tensorflow
    if _import_error is not None:
        raise RuntimeError(_import_error)

    # Silence the C++ INFO/WARNING banner before the first import.
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
    try:
        import tensorflow as tf  # noqa: PLC0415 - deliberately deferred
    except Exception as exc:  # noqa: BLE001 - surface any import failure
        _import_error = (
            f"TensorFlow could not be imported ({exc}). Install the optional "
            "forecasting dependencies with: pip install 'tensorflow-cpu>=2.20'."
        )
        logger.warning("tensorflow_unavailable error=%s", exc)
        raise RuntimeError(_import_error) from exc

    tf.get_logger().setLevel("ERROR")
    tf.keras.utils.set_random_seed(RANDOM_SEED)
    _tensorflow = tf
    logger.info("tensorflow_loaded version=%s", tf.__version__)
    return tf


def build_model(sequence_length: int, n_features: int, learning_rate: float = 1e-3):
    """Construct the stacked LSTM.

    Two recurrent layers with dropout between them: one layer underfits the
    multi-scale structure of daily returns, three overfits a few thousand
    windows without a matching gain in validation loss. Huber loss rather than
    MSE because return series are heavy-tailed and a single gap day should not
    dominate the gradient.
    """
    tf = require_tensorflow()
    layers = tf.keras.layers

    model = tf.keras.Sequential(
        [
            tf.keras.Input(shape=(sequence_length, n_features), name="window"),
            layers.LSTM(64, return_sequences=True, name="lstm_1"),
            layers.Dropout(0.2, name="dropout_1"),
            layers.LSTM(32, return_sequences=False, name="lstm_2"),
            layers.Dropout(0.2, name="dropout_2"),
            layers.Dense(16, activation="relu", name="dense_1"),
            layers.Dense(1, name="prediction"),
        ],
        name="lstm_return_forecaster",
    )

    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=learning_rate),
        loss=tf.keras.losses.Huber(delta=1.0),
        metrics=["mae"],
    )
    return model


def training_callbacks(patience: int = 8):
    """Early stopping plus LR decay, both watching validation loss."""
    tf = require_tensorflow()
    return [
        tf.keras.callbacks.EarlyStopping(
            monitor="val_loss",
            patience=patience,
            restore_best_weights=True,
            verbose=0,
        ),
        tf.keras.callbacks.ReduceLROnPlateau(
            monitor="val_loss",
            factor=0.5,
            patience=max(2, patience // 2),
            min_lr=1e-5,
            verbose=0,
        ),
    ]


# --- Metrics -------------------------------------------------------------


def rmse(actual: np.ndarray, predicted: np.ndarray) -> float:
    return float(np.sqrt(np.mean((actual - predicted) ** 2)))


def mae(actual: np.ndarray, predicted: np.ndarray) -> float:
    return float(np.mean(np.abs(actual - predicted)))


def mape(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Mean absolute percentage error, ignoring near-zero denominators."""
    mask = np.abs(actual) > 1e-9
    if not mask.any():
        return 0.0
    return float(np.mean(np.abs((actual[mask] - predicted[mask]) / actual[mask])) * 100)


def directional_accuracy(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Share of days where the predicted sign matched the realised sign.

    For a trading signal this matters more than RMSE: a forecast can have a
    small error and still be on the wrong side of zero every single day.
    """
    if actual.size == 0:
        return 0.0
    return float(np.mean(np.sign(actual) == np.sign(predicted)))


def evaluate_forecast(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    """Full metric set, including the naive baseline the model must beat.

    The baseline is persistence — "tomorrow's return equals today's". Reporting
    a model's RMSE without it is meaningless, because on daily returns a
    zero-forecast is already a strong competitor.
    """
    actual = np.asarray(actual, dtype=np.float64).reshape(-1)
    predicted = np.asarray(predicted, dtype=np.float64).reshape(-1)

    baseline = np.zeros_like(actual)  # predict "no change"
    model_rmse = rmse(actual, predicted)
    baseline_rmse = rmse(actual, baseline)

    return {
        "rmse": round(model_rmse, 8),
        "mae": round(mae(actual, predicted), 8),
        "mape": round(mape(actual, predicted), 4),
        "directionalAccuracy": round(directional_accuracy(actual, predicted), 4),
        "baselineRmse": round(baseline_rmse, 8),
        "skillScore": round(
            1 - model_rmse / baseline_rmse if baseline_rmse > 0 else 0.0, 4
        ),
        "samples": int(actual.size),
    }
