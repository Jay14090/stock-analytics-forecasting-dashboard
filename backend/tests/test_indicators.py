"""Indicator correctness.

These check mathematical properties and known-value cases rather than just
"the function returns something", because an indicator that is subtly wrong
still returns a plausible-looking series.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.services import indicators as ind


class TestMovingAverages:
    def test_sma_matches_manual_mean(self):
        series = pd.Series([1.0, 2, 3, 4, 5, 6])
        result = ind.sma(series, 3)
        assert result.iloc[2] == pytest.approx(2.0)
        assert result.iloc[5] == pytest.approx(5.0)

    def test_sma_warmup_is_nan(self):
        result = ind.sma(pd.Series(range(10), dtype=float), 5)
        assert result.iloc[:4].isna().all()
        assert result.iloc[4:].notna().all()

    def test_ema_reacts_faster_than_sma(self, ohlcv):
        """On a rising series the EMA should sit above the SMA."""
        rising = pd.Series(np.linspace(100, 200, 100))
        assert ind.ema(rising, 20).iloc[-1] > ind.sma(rising, 20).iloc[-1]


class TestRSI:
    def test_bounded_between_zero_and_hundred(self, ohlcv):
        values = ind.rsi(ohlcv["close"]).dropna()
        assert values.between(0, 100).all()

    def test_monotonic_rise_is_maximal(self):
        """A series that only ever rises has no losses, so RSI pins at 100."""
        rising = pd.Series(np.arange(1, 60, dtype=float))
        assert ind.rsi(rising).dropna().iloc[-1] == pytest.approx(100.0)

    def test_monotonic_fall_is_minimal(self):
        falling = pd.Series(np.arange(60, 1, -1, dtype=float))
        assert ind.rsi(falling).dropna().iloc[-1] == pytest.approx(0.0, abs=1e-6)


class TestMACD:
    def test_histogram_is_macd_minus_signal(self, ohlcv):
        result = ind.macd(ohlcv["close"])
        difference = (result.macd - result.signal).dropna()
        pd.testing.assert_series_equal(
            result.histogram.dropna(), difference, check_names=False
        )

    def test_uses_configured_spans(self, ohlcv):
        fast = ind.macd(ohlcv["close"], fast=5, slow=10, signal=3)
        slow = ind.macd(ohlcv["close"], fast=12, slow=26, signal=9)
        # A shorter configuration warms up sooner.
        assert fast.macd.notna().sum() > slow.macd.notna().sum()


class TestBollingerBands:
    def test_band_ordering(self, ohlcv):
        bands = ind.bollinger_bands(ohlcv["close"])
        valid = bands.upper.notna()
        assert (bands.upper[valid] >= bands.middle[valid]).all()
        assert (bands.middle[valid] >= bands.lower[valid]).all()

    def test_percent_b_within_band_is_zero_to_one(self, ohlcv):
        bands = ind.bollinger_bands(ohlcv["close"])
        close = ohlcv["close"]
        inside = (close >= bands.lower) & (close <= bands.upper) & bands.percent_b.notna()
        assert bands.percent_b[inside].between(0, 1).all()

    def test_constant_series_has_zero_width(self):
        flat = pd.Series([50.0] * 40)
        bands = ind.bollinger_bands(flat)
        assert bands.upper.dropna().eq(50.0).all()


class TestVolatilityAndVolume:
    def test_atr_is_non_negative(self, ohlcv):
        assert (ind.atr(ohlcv).dropna() >= 0).all()

    def test_true_range_covers_gaps(self):
        """A gap down makes |low - previous close| the widest of the three."""
        frame = pd.DataFrame(
            {"high": [10.0, 6.0], "low": [9.0, 5.0], "close": [10.0, 5.5], "volume": [1, 1]}
        )
        assert ind.true_range(frame).iloc[1] == pytest.approx(5.0)

    def test_obv_accumulates_by_direction(self):
        frame = pd.DataFrame(
            {
                "close": [10.0, 11.0, 10.5, 12.0],
                "volume": [100.0, 200.0, 150.0, 300.0],
                "high": [10, 11, 11, 12.0],
                "low": [10, 11, 10, 12.0],
            }
        )
        result = ind.obv(frame)
        # +200 on the up day, -150 on the down day, +300 on the next up day.
        assert result.iloc[-1] == pytest.approx(350.0)


class TestRiskMetrics:
    def test_max_drawdown_is_negative_or_zero(self, ohlcv):
        assert ind.max_drawdown(ohlcv["close"]) <= 0

    def test_max_drawdown_known_case(self):
        series = pd.Series([100.0, 120.0, 60.0, 90.0])
        assert ind.max_drawdown(series) == pytest.approx(-0.5)

    def test_monotonic_series_has_no_drawdown(self):
        assert ind.max_drawdown(pd.Series([1.0, 2, 3, 4])) == pytest.approx(0.0)

    def test_sharpe_of_constant_series_is_zero(self):
        assert ind.sharpe_ratio(pd.Series([100.0] * 50)) == 0.0

    def test_sharpe_is_finite(self, ohlcv):
        assert np.isfinite(ind.sharpe_ratio(ohlcv["close"]))


class TestIndicatorPanel:
    def test_panel_preserves_index(self, ohlcv):
        panel = ind.compute_indicators(ohlcv)
        assert len(panel) == len(ohlcv)
        assert panel.index.equals(ohlcv.index)

    def test_panel_has_every_advertised_column(self, ohlcv):
        panel = ind.compute_indicators(ohlcv)
        for column in ("sma20", "rsi14", "macd", "bbUpper", "atr14", "obv", "stochK"):
            assert column in panel.columns

    def test_short_history_warms_up_to_nan_not_error(self, short_ohlcv):
        """A 15-row history cannot warm up SMA-200 — that must be NaN, not a crash."""
        panel = ind.compute_indicators(short_ohlcv)
        assert panel["sma200"].isna().all()
        assert len(panel) == len(short_ohlcv)
