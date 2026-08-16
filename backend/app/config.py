"""Application configuration.

Configuration is environment-driven with sane defaults for local development.
Select an environment with the ``APP_ENV`` variable (``development``,
``testing`` or ``production``); anything else falls back to development.
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
INSTANCE_DIR = BASE_DIR / "instance"


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


class BaseConfig:
    """Settings shared by every environment."""

    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    JSON_SORT_KEYS = False

    # --- Database -------------------------------------------------------
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{(INSTANCE_DIR / 'app.db').as_posix()}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    # --- CORS -----------------------------------------------------------
    CORS_ORIGINS = [
        origin.strip()
        for origin in os.environ.get(
            "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
        ).split(",")
        if origin.strip()
    ]

    # --- Market data ----------------------------------------------------
    #: Seconds an intraday/price payload stays warm in the cache.
    QUOTE_CACHE_TTL = _env_int("QUOTE_CACHE_TTL", 60)
    #: Seconds a daily OHLC history payload stays warm in the cache.
    HISTORY_CACHE_TTL = _env_int("HISTORY_CACHE_TTL", 15 * 60)
    #: Seconds a news payload stays warm in the cache.
    NEWS_CACHE_TTL = _env_int("NEWS_CACHE_TTL", 30 * 60)
    #: Upper bound on entries held in the in-process cache.
    CACHE_MAX_ENTRIES = _env_int("CACHE_MAX_ENTRIES", 512)
    #: Network timeout, in seconds, for any upstream market-data call.
    MARKET_DATA_TIMEOUT = _env_int("MARKET_DATA_TIMEOUT", 20)

    # --- Forecasting ----------------------------------------------------
    MODEL_DIR = Path(os.environ.get("MODEL_DIR", INSTANCE_DIR / "models"))
    #: Trailing observations fed to the LSTM for a single prediction.
    SEQUENCE_LENGTH = _env_int("SEQUENCE_LENGTH", 60)
    #: Trading days predicted ahead of the last observation.
    FORECAST_HORIZON = _env_int("FORECAST_HORIZON", 5)
    TRAIN_EPOCHS = _env_int("TRAIN_EPOCHS", 40)
    TRAIN_BATCH_SIZE = _env_int("TRAIN_BATCH_SIZE", 32)
    #: Fraction of the series held out, chronologically, for validation.
    VALIDATION_SPLIT = float(os.environ.get("VALIDATION_SPLIT", "0.15"))
    #: Minimum usable rows before training is even attempted.
    MIN_TRAINING_ROWS = _env_int("MIN_TRAINING_ROWS", 250)
    #: Age past which a cached model is considered stale and retrained.
    MODEL_MAX_AGE_HOURS = _env_int("MODEL_MAX_AGE_HOURS", 24)

    # --- Logging --------------------------------------------------------
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
    LOG_JSON = _env_bool("LOG_JSON", False)


class DevelopmentConfig(BaseConfig):
    DEBUG = True


class TestingConfig(BaseConfig):
    TESTING = True
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    # Keep tests fast and deterministic: no cache reuse, tiny training runs.
    QUOTE_CACHE_TTL = 0
    HISTORY_CACHE_TTL = 0
    NEWS_CACHE_TTL = 0
    TRAIN_EPOCHS = 1
    SEQUENCE_LENGTH = 10
    MIN_TRAINING_ROWS = 30
    LOG_LEVEL = "CRITICAL"


class ProductionConfig(BaseConfig):
    DEBUG = False

    def __init__(self) -> None:
        if self.SECRET_KEY == "dev-secret-change-me":
            raise RuntimeError(
                "SECRET_KEY must be set to a non-default value in production"
            )


_CONFIGS: dict[str, type[BaseConfig]] = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}


def get_config(name: str | None = None) -> type[BaseConfig]:
    """Return the config class for ``name`` (or ``APP_ENV``)."""
    key = (name or os.environ.get("APP_ENV", "development")).strip().lower()
    return _CONFIGS.get(key, DevelopmentConfig)
