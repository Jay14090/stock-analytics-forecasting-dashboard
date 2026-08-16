"""On-disk model registry.

Training an LSTM per symbol takes tens of seconds, which is far too slow to do
inside a request. Models are therefore trained once, persisted with their
scalers and metrics, and reused until they go stale.

Layout, one directory per symbol::

    instance/models/AAPL/
        model.keras       # architecture + weights
        metadata.json     # scalers, metrics, training provenance

Scalers live in the metadata rather than a pickle: pickles of a class defined
in this package break the moment the class moves, and the parameters are six
floats per feature.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .dataset import MinMaxScaler

logger = logging.getLogger(__name__)

_SAFE_NAME_RE = re.compile(r"[^A-Z0-9._-]")

METADATA_FILENAME = "metadata.json"
MODEL_FILENAME = "model.keras"

#: Bump when a change makes previously-saved artefacts unusable (new features,
#: different target). Stale-version models are retrained instead of loaded.
ARTEFACT_VERSION = 2


@dataclass(slots=True)
class ModelMetadata:
    """Everything needed to reuse a trained model, and to judge whether to."""

    symbol: str
    trained_at: str
    sequence_length: int
    horizon: int
    features: list[str]
    metrics: dict[str, float]
    training_rows: int
    epochs_run: int
    feature_scaler: dict[str, Any]
    target_scaler: dict[str, Any]
    last_close: float
    last_date: str
    artefact_version: int = ARTEFACT_VERSION
    history: dict[str, list[float]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ModelMetadata":
        known = {f for f in cls.__slots__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in payload.items() if k in known})

    @property
    def trained_datetime(self) -> datetime:
        stamp = datetime.fromisoformat(self.trained_at)
        return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)

    def is_stale(self, max_age_hours: int, last_date: str | None = None) -> bool:
        """Stale if the artefact is old, superseded, or predates newer bars."""
        if self.artefact_version != ARTEFACT_VERSION:
            return True
        if datetime.now(timezone.utc) - self.trained_datetime > timedelta(
            hours=max_age_hours
        ):
            return True
        # New trading sessions have closed since training.
        return bool(last_date and last_date > self.last_date)

    def scalers(self) -> tuple[MinMaxScaler, MinMaxScaler]:
        return (
            MinMaxScaler.from_dict(self.feature_scaler),
            MinMaxScaler.from_dict(self.target_scaler),
        )


class ModelRegistry:
    """Filesystem-backed store of trained models."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _safe_dir(self, symbol: str) -> Path:
        """Map a ticker to a directory name that cannot escape the root.

        Symbols reach this from user input; ``^NSEI`` and ``BRK-B`` are valid
        tickers and ``..`` must never be one.
        """
        cleaned = _SAFE_NAME_RE.sub("_", symbol.strip().upper())
        if not cleaned or cleaned.strip("._") == "":
            raise ValueError(f"Cannot derive a model path for symbol {symbol!r}.")
        return self.root / cleaned

    def paths(self, symbol: str) -> tuple[Path, Path]:
        directory = self._safe_dir(symbol)
        return directory / MODEL_FILENAME, directory / METADATA_FILENAME

    def exists(self, symbol: str) -> bool:
        model_path, metadata_path = self.paths(symbol)
        return model_path.exists() and metadata_path.exists()

    def load_metadata(self, symbol: str) -> ModelMetadata | None:
        _, metadata_path = self.paths(symbol)
        if not metadata_path.exists():
            return None
        try:
            with metadata_path.open("r", encoding="utf-8") as handle:
                return ModelMetadata.from_dict(json.load(handle))
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            logger.warning("metadata_unreadable symbol=%s error=%s", symbol, exc)
            return None

    def load_model(self, symbol: str):
        """Load the Keras model, or None if it is missing or unreadable."""
        from .model import require_tensorflow

        model_path, _ = self.paths(symbol)
        if not model_path.exists():
            return None
        try:
            tf = require_tensorflow()
            return tf.keras.models.load_model(model_path, compile=False)
        except Exception as exc:  # noqa: BLE001 - a corrupt artefact must not 500
            logger.warning("model_load_failed symbol=%s error=%s", symbol, exc)
            return None

    def save(self, symbol: str, model, metadata: ModelMetadata) -> None:
        """Persist a model and its metadata atomically.

        Written to a temporary directory and moved into place, so a crash
        mid-save cannot leave a half-written model that later loads as valid.
        """
        target = self._safe_dir(symbol)
        target.parent.mkdir(parents=True, exist_ok=True)

        staging = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=target.parent))
        try:
            model.save(staging / MODEL_FILENAME)
            with (staging / METADATA_FILENAME).open("w", encoding="utf-8") as handle:
                json.dump(metadata.to_dict(), handle, indent=2, default=str)

            if target.exists():
                shutil.rmtree(target)
            staging.replace(target)
            logger.info(
                "model_saved symbol=%s rows=%d directional_accuracy=%.3f",
                symbol,
                metadata.training_rows,
                metadata.metrics.get("directionalAccuracy", 0.0),
            )
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def delete(self, symbol: str) -> bool:
        directory = self._safe_dir(symbol)
        if not directory.exists():
            return False
        shutil.rmtree(directory, ignore_errors=True)
        return True

    def list_models(self) -> list[dict[str, Any]]:
        """Summarise every stored model, newest first."""
        if not self.root.exists():
            return []

        summaries: list[dict[str, Any]] = []
        for directory in sorted(self.root.iterdir()):
            if not directory.is_dir() or directory.name.startswith("."):
                continue
            metadata = self.load_metadata(directory.name)
            if metadata is None:
                continue
            summaries.append(
                {
                    "symbol": metadata.symbol,
                    "trainedAt": metadata.trained_at,
                    "sequenceLength": metadata.sequence_length,
                    "horizon": metadata.horizon,
                    "trainingRows": metadata.training_rows,
                    "epochsRun": metadata.epochs_run,
                    "metrics": metadata.metrics,
                    "artefactVersion": metadata.artefact_version,
                }
            )
        return sorted(summaries, key=lambda item: item["trainedAt"], reverse=True)
