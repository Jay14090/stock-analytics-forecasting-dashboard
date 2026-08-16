"""LSTM forecasting package.

Public surface:

* :func:`train_symbol` — train and persist a model for one ticker.
* :func:`forecast_symbol` — multi-step forecast, training on demand.
* :func:`tensorflow_available` — whether the optional stack is installed.
* :class:`ModelRegistry` — on-disk model store.
"""

from .model import tensorflow_available
from .registry import ModelMetadata, ModelRegistry
from .service import forecast_symbol, get_registry, train_symbol

__all__ = [
    "ModelMetadata",
    "ModelRegistry",
    "forecast_symbol",
    "get_registry",
    "tensorflow_available",
    "train_symbol",
]
