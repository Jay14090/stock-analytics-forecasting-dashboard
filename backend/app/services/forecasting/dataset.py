"""Feature engineering and windowing for the LSTM.

The two decisions that matter for correctness live here:

1. **The split is chronological, never shuffled.** Randomly splitting a price
   series lets the model validate on days it effectively saw during training.
2. **Scalers are fitted on the training window only.** Fitting on the whole
   series leaks the validation range's min/max backwards into training and
   produces validation scores the model cannot reproduce live.

Both are easy to get wrong and neither shows up as an error — only as a model
that looks excellent offline and useless in production.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..indicators import atr, ema, macd, rsi, sma

logger = logging.getLogger(__name__)

#: Model inputs. Price levels are deliberately excluded except for the target
#: column: a network trained on raw levels learns the price range of its
#: training window and degrades as soon as the stock leaves it. Returns and
#: bounded oscillators generalise across regimes.
FEATURE_COLUMNS = [
    "log_return",
    "log_return_5d",
    "volume_ratio",
    "high_low_range",
    "close_to_sma20",
    "close_to_sma50",
    "rsi14_scaled",
    "macd_normalised",
    "atr_normalised",
]

TARGET_COLUMN = "log_return"


class MinMaxScaler:
    """Feature scaler with an explicit fit/transform split.

    scikit-learn has one, but this keeps the training path dependency-free and
    makes the persisted parameters trivial to serialise alongside the model.
    """

    def __init__(self, feature_range: tuple[float, float] = (0.0, 1.0)) -> None:
        self.minimum: np.ndarray | None = None
        self.scale: np.ndarray | None = None
        self.feature_range = feature_range

    def fit(self, values: np.ndarray) -> "MinMaxScaler":
        low, high = self.feature_range
        self.minimum = np.nanmin(values, axis=0)
        span = np.nanmax(values, axis=0) - self.minimum
        # A constant column has zero span; map it to the range floor instead
        # of dividing by zero.
        span[span == 0] = 1.0
        self.scale = (high - low) / span
        return self

    def transform(self, values: np.ndarray) -> np.ndarray:
        if self.minimum is None or self.scale is None:
            raise RuntimeError("Scaler must be fitted before transform().")
        low, _ = self.feature_range
        return (values - self.minimum) * self.scale + low

    def fit_transform(self, values: np.ndarray) -> np.ndarray:
        return self.fit(values).transform(values)

    def inverse_transform(self, values: np.ndarray) -> np.ndarray:
        if self.minimum is None or self.scale is None:
            raise RuntimeError("Scaler must be fitted before inverse_transform().")
        low, _ = self.feature_range
        return (values - low) / self.scale + self.minimum

    def to_dict(self) -> dict[str, list[float]]:
        return {
            "minimum": np.asarray(self.minimum).tolist(),
            "scale": np.asarray(self.scale).tolist(),
            "featureRange": list(self.feature_range),
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "MinMaxScaler":
        scaler = cls(tuple(payload.get("featureRange", (0.0, 1.0))))  # type: ignore[arg-type]
        scaler.minimum = np.asarray(payload["minimum"], dtype=np.float64)
        scaler.scale = np.asarray(payload["scale"], dtype=np.float64)
        return scaler


@dataclass(slots=True)
class WindowedDataset:
    """Supervised windows plus everything needed to invert the transform."""

    x_train: np.ndarray
    y_train: np.ndarray
    x_validation: np.ndarray
    y_validation: np.ndarray
    feature_scaler: MinMaxScaler
    target_scaler: MinMaxScaler
    feature_frame: pd.DataFrame
    split_index: int

    @property
    def n_features(self) -> int:
        return self.x_train.shape[2]


def build_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Derive the model's feature matrix from an OHLCV frame.

    Every feature is either a return, a ratio or a bounded oscillator, so the
    representation of a ₹50 stock and a ₹5,000 stock is comparable.
    """
    close = frame["close"]
    features = pd.DataFrame(index=frame.index)

    # Log returns are additive across time, which makes the recursive
    # multi-step reconstruction downstream exact rather than approximate.
    features["log_return"] = np.log(close / close.shift(1))
    features["log_return_5d"] = np.log(close / close.shift(5))

    rolling_volume = frame["volume"].rolling(20, min_periods=20).mean()
    features["volume_ratio"] = frame["volume"] / rolling_volume.replace(0, np.nan)

    features["high_low_range"] = (frame["high"] - frame["low"]) / close

    features["close_to_sma20"] = close / sma(close, 20) - 1
    features["close_to_sma50"] = close / sma(close, 50) - 1

    # RSI is already bounded; centre it on zero to match the other features.
    features["rsi14_scaled"] = (rsi(close) - 50) / 50

    macd_result = macd(close)
    features["macd_normalised"] = (macd_result.macd - macd_result.signal) / close

    features["atr_normalised"] = atr(frame) / close

    features = features.replace([np.inf, -np.inf], np.nan)
    return features


def prepare_dataset(
    frame: pd.DataFrame,
    sequence_length: int,
    validation_split: float = 0.15,
) -> WindowedDataset:
    """Turn an OHLCV frame into scaled, windowed train/validation tensors.

    Args:
        frame: OHLCV history, oldest first.
        sequence_length: Trailing observations per sample.
        validation_split: Fraction of windows held out from the end.

    Raises:
        ValueError: if there is not enough clean history to build both splits.
    """
    features = build_features(frame).dropna()
    if len(features) <= sequence_length + 10:
        raise ValueError(
            f"Need more than {sequence_length + 10} clean rows to build windows; "
            f"got {len(features)}."
        )

    values = features[FEATURE_COLUMNS].to_numpy(dtype=np.float64)
    targets = features[[TARGET_COLUMN]].to_numpy(dtype=np.float64)

    # Split on *windows*, and reserve the boundary so no training window
    # overlaps a validation target.
    total_windows = len(values) - sequence_length
    validation_windows = max(1, int(total_windows * validation_split))
    split_index = total_windows - validation_windows

    if split_index < 10:
        raise ValueError(
            "Not enough history for a meaningful train/validation split "
            f"({split_index} training windows)."
        )

    # Fit scalers on the training rows only — see the module docstring.
    train_row_end = split_index + sequence_length
    feature_scaler = MinMaxScaler().fit(values[:train_row_end])
    target_scaler = MinMaxScaler().fit(targets[:train_row_end])

    scaled_features = feature_scaler.transform(values)
    scaled_targets = target_scaler.transform(targets)

    x_all = np.stack(
        [scaled_features[i : i + sequence_length] for i in range(total_windows)]
    )
    y_all = scaled_targets[sequence_length:].reshape(-1)

    logger.debug(
        "dataset_built windows=%d train=%d validation=%d features=%d",
        total_windows, split_index, validation_windows, len(FEATURE_COLUMNS),
    )

    return WindowedDataset(
        x_train=x_all[:split_index],
        y_train=y_all[:split_index],
        x_validation=x_all[split_index:],
        y_validation=y_all[split_index:],
        feature_scaler=feature_scaler,
        target_scaler=target_scaler,
        feature_frame=features,
        split_index=split_index,
    )


def latest_window(
    features: pd.DataFrame, scaler: MinMaxScaler, sequence_length: int
) -> np.ndarray:
    """Build the single most recent input window for inference."""
    values = features[FEATURE_COLUMNS].to_numpy(dtype=np.float64)
    if len(values) < sequence_length:
        raise ValueError(
            f"Need {sequence_length} rows for a prediction window; got {len(values)}."
        )
    window = scaler.transform(values[-sequence_length:])
    return window.reshape(1, sequence_length, len(FEATURE_COLUMNS))
