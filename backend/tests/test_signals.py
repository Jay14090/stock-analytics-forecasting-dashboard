"""Signal rule engine."""

from __future__ import annotations

import pytest

from app.services.indicators import compute_indicators
from app.services.signals import generate_signal


@pytest.fixture(scope="module")
def uptrend(ohlcv_factory):
    """A strong, steady advance."""
    return ohlcv_factory(rows=400, trend=0.0025, volatility=0.008, seed=11)


@pytest.fixture(scope="module")
def downtrend(ohlcv_factory):
    return ohlcv_factory(rows=400, trend=-0.0025, volatility=0.008, seed=13)


class TestSignalShape:
    def test_returns_expected_keys(self, ohlcv):
        result = generate_signal(ohlcv, symbol="TEST")
        for key in ("symbol", "action", "score", "confidence", "rules", "summary"):
            assert key in result

    def test_action_is_from_the_known_set(self, ohlcv):
        action = generate_signal(ohlcv, symbol="TEST")["action"]
        assert action in {"strong_buy", "buy", "hold", "sell", "strong_sell"}

    def test_score_is_bounded(self, ohlcv):
        assert -1.0 <= generate_signal(ohlcv, symbol="TEST")["score"] <= 1.0

    def test_rule_contributions_are_reported(self, ohlcv):
        rules = generate_signal(ohlcv, symbol="TEST")["rules"]
        assert rules
        for rule in rules:
            assert rule["rationale"]
            # Both fields are rounded for the wire, so compare at that precision.
            assert rule["contribution"] == pytest.approx(
                rule["score"] * rule["weight"], abs=1e-4
            )


class TestDirectionality:
    def test_uptrend_scores_above_downtrend(self, uptrend, downtrend):
        """The engine must at minimum rank a rally above a slide."""
        up = generate_signal(uptrend, symbol="UP")["score"]
        down = generate_signal(downtrend, symbol="DOWN")["score"]
        assert up > down

    def test_uptrend_is_not_bearish(self, uptrend):
        assert generate_signal(uptrend, symbol="UP")["action"] not in {"sell", "strong_sell"}

    def test_downtrend_is_not_bullish(self, downtrend):
        assert generate_signal(downtrend, symbol="DOWN")["action"] not in {"buy", "strong_buy"}


class TestRuleCalibration:
    """Guards against the two ways these rules were previously miscalibrated."""

    def test_volume_rule_stays_neutral_on_thin_volume(self, ohlcv_factory):
        """Below-average volume is absent evidence, not bearish evidence.

        The earlier version scaled by |ratio - 1|, so a quiet drift produced a
        confident directional vote — exactly backwards.
        """
        from app.services.signals import rule_volume_confirmation

        frame = ohlcv_factory(rows=120, seed=21).copy()
        # Recent sessions at a fraction of the earlier baseline.
        frame.iloc[-5:, frame.columns.get_loc('volume')] = 200_000
        frame.iloc[-30:-5, frame.columns.get_loc('volume')] = 5_000_000

        result = rule_volume_confirmation(frame, compute_indicators(frame))
        assert result is not None
        assert result.score == pytest.approx(0.0)
        assert 'no confirmation' in result.rationale

    def test_volume_rule_confirms_on_heavy_volume(self, ohlcv_factory):
        from app.services.signals import rule_volume_confirmation

        frame = ohlcv_factory(rows=120, trend=0.01, volatility=0.005, seed=22).copy()
        frame.iloc[-30:-5, frame.columns.get_loc('volume')] = 1_000_000
        frame.iloc[-5:, frame.columns.get_loc('volume')] = 4_000_000

        result = rule_volume_confirmation(frame, compute_indicators(frame))
        assert result.score > 0.5  # rising price on heavy volume

    def test_macd_rule_is_volatility_normalised(self, ohlcv_factory):
        """A typical MACD reading must not saturate the rule.

        Normalising by price alone pinned ordinary readings at ±1.00, which
        made the rule a constant rather than a measurement.
        """
        from app.services.signals import rule_macd_crossover

        frame = ohlcv_factory(rows=300, trend=0.0008, volatility=0.012, seed=23)
        result = rule_macd_crossover(frame, compute_indicators(frame))
        assert result is not None
        assert abs(result.score) < 1.0

    def test_macd_scores_scale_with_price_independently(self, ohlcv_factory):
        """The same shape at ₹100 and ₹10,000 must score the same."""
        from app.services.signals import rule_macd_crossover

        cheap = ohlcv_factory(rows=300, start_price=100.0, seed=24)
        expensive = ohlcv_factory(rows=300, start_price=10_000.0, seed=24)

        a = rule_macd_crossover(cheap, compute_indicators(cheap))
        b = rule_macd_crossover(expensive, compute_indicators(expensive))
        assert a.score == pytest.approx(b.score, abs=1e-6)


class TestDegradedInputs:
    def test_short_history_yields_hold_without_crashing(self, short_ohlcv):
        """Too little history to warm the rules up must abstain, not guess."""
        result = generate_signal(short_ohlcv, symbol="TINY")
        assert result["action"] == "hold"
        assert result["coverage"] < 0.35
        assert "warm up" in result["summary"]

    def test_precomputed_indicators_are_reused(self, ohlcv):
        panel = compute_indicators(ohlcv)
        a = generate_signal(ohlcv, symbol="TEST", indicators=panel)
        b = generate_signal(ohlcv, symbol="TEST")
        assert a["score"] == pytest.approx(b["score"])


class TestOptionalInputs:
    def test_credible_forecast_shifts_the_score(self, ohlcv):
        base = generate_signal(ohlcv, symbol="TEST")["score"]
        bullish = generate_signal(
            ohlcv,
            symbol="TEST",
            forecast={
                "expectedChangePercent": 8.0,
                "horizon": 5,
                "metrics": {"directionalAccuracy": 0.72},
            },
        )["score"]
        assert bullish > base

    def test_coin_flip_forecast_is_discounted(self, ohlcv):
        """A model at chance accuracy must not move the recommendation."""
        result = generate_signal(
            ohlcv,
            symbol="TEST",
            forecast={
                "expectedChangePercent": 25.0,
                "horizon": 5,
                "metrics": {"directionalAccuracy": 0.50},
            },
        )
        forecast_rule = next(r for r in result["rules"] if r["name"] == "LSTM forecast")
        assert forecast_rule["score"] == 0.0
        assert "not being counted" in forecast_rule["rationale"]

    def test_sentiment_is_included_when_supplied(self, ohlcv):
        result = generate_signal(
            ohlcv,
            symbol="TEST",
            sentiment={
                "score": -0.6, "label": "negative", "confidence": 0.8, "articleCount": 12
            },
        )
        assert any(rule["name"] == "News sentiment" for rule in result["rules"])

    def test_empty_sentiment_adds_no_rule(self, ohlcv):
        result = generate_signal(
            ohlcv, symbol="TEST", sentiment={"articleCount": 0, "score": 0.0}
        )
        assert not any(rule["name"] == "News sentiment" for rule in result["rules"])

    def test_more_evidence_raises_confidence(self, ohlcv):
        bare = generate_signal(ohlcv, symbol="TEST")
        enriched = generate_signal(
            ohlcv,
            symbol="TEST",
            forecast={
                "expectedChangePercent": 3.0, "horizon": 5,
                "metrics": {"directionalAccuracy": 0.70},
            },
            sentiment={
                "score": 0.5, "label": "positive", "confidence": 0.9, "articleCount": 10
            },
        )
        assert enriched["confidence"] >= bare["confidence"]
