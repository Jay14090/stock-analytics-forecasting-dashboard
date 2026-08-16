"""Request validation schemas and serialisation helpers.

Validation happens at the edge so services can assume clean inputs, and so a
malformed request returns a 400 naming the offending field instead of a 500
from somewhere deep in pandas.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from marshmallow import (
    EXCLUDE,
    Schema,
    ValidationError,
    fields,
    validate,
    validates_schema,
)

from .models import TRANSACTION_KINDS

PERIODS = ["1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "max"]
INTERVALS = ["1d", "1wk", "1mo"]


# --- Serialisation -------------------------------------------------------


def json_safe(value: Any) -> Any:
    """Convert numpy/pandas scalars to JSON-serialisable Python values.

    ``NaN`` and ``inf`` become ``None``: JSON has no representation for them,
    and ``NaN`` is exactly what an indicator emits during its warm-up window,
    so it must survive to the client as ``null`` and draw a gap in the chart.
    """
    if value is None:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return None if (math.isnan(number) or math.isinf(number)) else round(number, 6)
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (pd.Timestamp, date)):
        return str(getattr(value, "date", lambda: value)())
    if isinstance(value, np.ndarray):
        return [json_safe(item) for item in value.tolist()]
    return value


def frame_to_records(frame: pd.DataFrame, date_key: str = "date") -> list[dict[str, Any]]:
    """Serialise a date-indexed frame to a list of JSON-safe records."""
    records: list[dict[str, Any]] = []
    for stamp, row in frame.iterrows():
        record: dict[str, Any] = {date_key: json_safe(stamp)}
        for column, value in row.items():
            record[str(column)] = json_safe(value)
        records.append(record)
    return records


def series_to_records(series: pd.Series, value_key: str = "value") -> list[dict[str, Any]]:
    """Serialise a date-indexed series, dropping the warm-up NaNs."""
    return [
        {"date": json_safe(stamp), value_key: json_safe(value)}
        for stamp, value in series.items()
        if pd.notna(value)
    ]


# --- Query schemas -------------------------------------------------------
#
# Query strings routinely carry parameters we do not model (cache busters, UTM
# tags, a stray `&_=1697...` from a client library). marshmallow 4 raises on
# unknown keys by default, which would turn those into spurious 400s, so query
# schemas drop what they do not recognise. Body schemas keep the strict default
# so a misspelled field in a POST is reported rather than silently ignored.


class QuerySchema(Schema):
    """Base for anything loaded from ``request.args``."""

    class Meta:
        unknown = EXCLUDE


class HistoryQuerySchema(QuerySchema):
    period = fields.Str(load_default="1y", validate=validate.OneOf(PERIODS))
    interval = fields.Str(load_default="1d", validate=validate.OneOf(INTERVALS))


class IndicatorQuerySchema(HistoryQuerySchema):
    #: Comma-separated indicator keys; omitted means the full panel.
    indicators = fields.Str(load_default=None, allow_none=True)


class ForecastQuerySchema(QuerySchema):
    horizon = fields.Int(load_default=5, validate=validate.Range(min=1, max=30))
    period = fields.Str(load_default="2y", validate=validate.OneOf(PERIODS))
    retrain = fields.Bool(load_default=False)


class SearchQuerySchema(QuerySchema):
    q = fields.Str(required=True, validate=validate.Length(min=2, max=60))
    limit = fields.Int(load_default=10, validate=validate.Range(min=1, max=25))


class SignalQuerySchema(QuerySchema):
    period = fields.Str(load_default="1y", validate=validate.OneOf(PERIODS))
    include_forecast = fields.Bool(load_default=False, data_key="includeForecast")
    include_sentiment = fields.Bool(load_default=True, data_key="includeSentiment")


class ScreenQuerySchema(QuerySchema):
    symbols = fields.Str(required=True, validate=validate.Length(min=1, max=600))
    period = fields.Str(load_default="6mo", validate=validate.OneOf(PERIODS))
    include_sentiment = fields.Bool(load_default=False, data_key="includeSentiment")


class NewsQuerySchema(QuerySchema):
    limit = fields.Int(load_default=15, validate=validate.Range(min=1, max=50))


# --- Body schemas --------------------------------------------------------


class WatchlistCreateSchema(Schema):
    name = fields.Str(required=True, validate=validate.Length(min=1, max=80))


class WatchlistItemCreateSchema(Schema):
    symbol = fields.Str(required=True, validate=validate.Length(min=1, max=20))
    note = fields.Str(load_default=None, allow_none=True, validate=validate.Length(max=280))


class PortfolioCreateSchema(Schema):
    name = fields.Str(required=True, validate=validate.Length(min=1, max=80))
    baseCurrency = fields.Str(load_default="USD", validate=validate.Length(min=2, max=8))
    cashBalance = fields.Float(load_default=0.0, validate=validate.Range(min=0))


class TransactionCreateSchema(Schema):
    symbol = fields.Str(required=True, validate=validate.Length(min=1, max=20))
    kind = fields.Str(required=True, validate=validate.OneOf(TRANSACTION_KINDS))
    quantity = fields.Float(required=True, validate=validate.Range(min=1e-6))
    price = fields.Float(required=True, validate=validate.Range(min=0))
    fees = fields.Float(load_default=0.0, validate=validate.Range(min=0))
    tradedOn = fields.Date(load_default=None, allow_none=True)
    note = fields.Str(load_default=None, allow_none=True, validate=validate.Length(max=280))

    @validates_schema
    def _not_in_the_future(self, data: dict[str, Any], **_: Any) -> None:
        traded = data.get("tradedOn")
        if traded and traded > date.today():
            raise ValidationError(
                "Trade date cannot be in the future.", field_name="tradedOn"
            )


class TrainRequestSchema(QuerySchema):
    period = fields.Str(load_default="5y", validate=validate.OneOf(PERIODS))
    force = fields.Bool(load_default=False)
