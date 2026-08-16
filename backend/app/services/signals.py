"""Buy/sell/hold signal generation.

A weighted rule engine rather than a classifier, for one reason: every signal
has to be explainable. A user looking at a SELL needs to see which rules fired
and how hard, and a rule engine gives that for free where a black-box model
would need a separate explanation layer.

Each rule returns a score in [-1, 1] (negative bearish, positive bullish) plus
a human-readable rationale. The composite is a weighted mean, so adding a rule
never silently rescales the others.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
import pandas as pd

from .indicators import compute_indicators

logger = logging.getLogger(__name__)

# Thresholds on the composite score. Wide neutral band on purpose: the honest
# default for a technical screen is "no opinion", and a system that always has
# a view is a system that is usually wrong.
STRONG_BUY_THRESHOLD = 0.45
BUY_THRESHOLD = 0.15
SELL_THRESHOLD = -0.15
STRONG_SELL_THRESHOLD = -0.45

#: Fraction of the total rule weight that must actually fire before the engine
#: will issue anything other than "hold". On a short history most indicators
#: are still warming up, and a directional call resting on one warmed-up rule
#: is noise wearing the costume of a recommendation.
MIN_COVERAGE_FOR_ACTION = 0.35


@dataclass(slots=True)
class RuleResult:
    """One rule's verdict."""

    name: str
    score: float
    weight: float
    rationale: str
    category: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "score": round(self.score, 4),
            "weight": self.weight,
            "contribution": round(self.score * self.weight, 4),
            "rationale": self.rationale,
            "category": self.category,
        }


def _latest(series: pd.Series) -> float | None:
    """Last non-null value, or None when the indicator has not warmed up."""
    cleaned = series.dropna()
    if cleaned.empty:
        return None
    value = float(cleaned.iloc[-1])
    return value if np.isfinite(value) else None


def _clamp(value: float) -> float:
    return float(np.clip(value, -1.0, 1.0))


# --- Rules ---------------------------------------------------------------
# Each takes (ohlcv, indicators) and returns a RuleResult or None when the
# inputs have not warmed up. Returning None keeps a cold indicator from being
# read as a neutral opinion.


def rule_trend_alignment(frame: pd.DataFrame, ind: pd.DataFrame) -> RuleResult | None:
    """Price against the 50- and 200-day averages, plus their crossover."""
    close = _latest(frame["close"])
    sma50 = _latest(ind["sma50"])
    sma200 = _latest(ind["sma200"])
    if close is None or sma50 is None:
        return None

    score = 0.0
    notes: list[str] = []

    if close > sma50:
        score += 0.4
        notes.append("price above the 50-day average")
    else:
        score -= 0.4
        notes.append("price below the 50-day average")

    if sma200 is not None:
        if close > sma200:
            score += 0.3
            notes.append("and above the 200-day")
        else:
            score -= 0.3
            notes.append("and below the 200-day")

        # Golden/death cross: the classic regime marker.
        if sma50 > sma200:
            score += 0.3
            notes.append("with the 50-day above the 200-day (golden cross)")
        else:
            score -= 0.3
            notes.append("with the 50-day below the 200-day (death cross)")

    return RuleResult(
        name="Trend alignment",
        score=_clamp(score),
        weight=0.25,
        rationale=", ".join(notes).capitalize() + ".",
        category="trend",
    )


def rule_momentum_rsi(frame: pd.DataFrame, ind: pd.DataFrame) -> RuleResult | None:
    """RSI, read as mean reversion at the extremes.

    Scored linearly from the 50 midpoint and inverted: a high RSI is a reason
    to be cautious, not a reason to buy.
    """
    value = _latest(ind["rsi14"])
    if value is None:
        return None

    score = _clamp((50 - value) / 30)

    if value >= 70:
        rationale = f"RSI at {value:.1f} is overbought; momentum is stretched."
    elif value <= 30:
        rationale = f"RSI at {value:.1f} is oversold; the selling may be exhausted."
    else:
        rationale = f"RSI at {value:.1f} sits in the neutral band."

    return RuleResult(
        name="RSI momentum",
        score=score,
        weight=0.15,
        rationale=rationale,
        category="momentum",
    )


def rule_macd_crossover(frame: pd.DataFrame, ind: pd.DataFrame) -> RuleResult | None:
    """MACD histogram sign and whether it is expanding."""
    histogram = ind["macdHistogram"].dropna()
    if len(histogram) < 2:
        return None

    current = float(histogram.iloc[-1])
    previous = float(histogram.iloc[-2])

    # Normalise by ATR, not by price. A fixed price-percentage scale saturates
    # on a volatile stock and barely registers on a quiet one; dividing by
    # recent true range asks the right question — how big is this histogram
    # relative to how much this particular stock normally moves?
    volatility = _latest(ind["atr14"])
    if volatility and volatility > 0:
        score = _clamp(current / volatility * 1.5)
    else:
        close = _latest(frame["close"]) or 1.0
        score = _clamp(current / close * 60)

    if current > 0 and current > previous:
        rationale = "MACD is above its signal line and the gap is widening."
    elif current > 0:
        rationale = "MACD is above its signal line but the gap is narrowing."
    elif current < 0 and current < previous:
        rationale = "MACD is below its signal line and falling further."
    else:
        rationale = "MACD is below its signal line but recovering."

    return RuleResult(
        name="MACD crossover",
        score=score,
        weight=0.15,
        rationale=rationale,
        category="momentum",
    )


def rule_bollinger_position(frame: pd.DataFrame, ind: pd.DataFrame) -> RuleResult | None:
    """Position within the Bollinger band, as mean reversion."""
    percent_b = _latest(ind["bbPercentB"])
    if percent_b is None:
        return None

    score = _clamp((0.5 - percent_b) * 2)

    if percent_b > 1:
        rationale = "Price has closed above the upper band — extended."
    elif percent_b < 0:
        rationale = "Price has closed below the lower band — extended to the downside."
    else:
        rationale = f"Price sits at {percent_b * 100:.0f}% of the band width."

    return RuleResult(
        name="Bollinger position",
        score=score,
        weight=0.10,
        rationale=rationale,
        category="volatility",
    )


def rule_volume_confirmation(frame: pd.DataFrame, ind: pd.DataFrame) -> RuleResult | None:
    """Does volume confirm the recent move?

    A move on heavy volume is more durable than the same move on thin volume;
    a move on unusually light volume is treated as weak evidence either way.
    """
    if len(frame) < 25:
        return None

    recent_volume = float(frame["volume"].tail(5).mean())
    baseline_volume = float(frame["volume"].tail(25).mean())
    if baseline_volume <= 0:
        return None

    ratio = recent_volume / baseline_volume
    price_change = float(frame["close"].iloc[-1] / frame["close"].iloc[-6] - 1) if len(frame) > 6 else 0.0

    direction = np.sign(price_change)

    # Only *above-average* volume confirms anything. Below-average volume is
    # the absence of evidence, so it scores zero rather than voting: a quiet
    # drift should not be read as conviction in either direction.
    confirmation = _clamp(max(0.0, ratio - 1.0) * 1.5)
    score = _clamp(direction * confirmation)

    if ratio > 1.2:
        rationale = (
            f"Volume is {ratio:.1f}× its 25-day average, confirming the "
            f"{'advance' if direction > 0 else 'decline'}."
        )
    elif ratio < 0.8:
        rationale = (
            f"Volume is only {ratio:.1f}× its average, so the recent move carries "
            "no confirmation either way."
        )
    else:
        rationale = "Volume is close to its recent average; no clear confirmation."

    return RuleResult(
        name="Volume confirmation",
        score=score,
        weight=0.10,
        rationale=rationale,
        category="volume",
    )


def rule_forecast(forecast: dict[str, Any] | None) -> RuleResult | None:
    """The LSTM's expected move, discounted by its measured skill.

    A model that barely beats a naive baseline should barely move the signal,
    so the raw expected change is scaled by directional accuracy above chance.
    """
    if not forecast:
        return None

    expected = forecast.get("expectedChangePercent")
    metrics = forecast.get("metrics", {})
    if expected is None:
        return None

    accuracy = float(metrics.get("directionalAccuracy", 0.5))
    # Map 50% (coin flip) → 0 credibility, 75%+ → full credibility.
    credibility = _clamp((accuracy - 0.5) / 0.25)
    if credibility <= 0:
        return RuleResult(
            name="LSTM forecast",
            score=0.0,
            weight=0.25,
            rationale=(
                f"The model's directional accuracy ({accuracy:.0%}) is at or below "
                "chance on held-out data, so its forecast is not being counted."
            ),
            category="forecast",
        )

    raw = _clamp(float(expected) / 5.0)  # a 5% expected move saturates the rule
    score = _clamp(raw * credibility)

    return RuleResult(
        name="LSTM forecast",
        score=score,
        weight=0.25,
        rationale=(
            f"The model projects {expected:+.2f}% over {forecast.get('horizon')} sessions "
            f"({accuracy:.0%} directional accuracy on held-out data)."
        ),
        category="forecast",
    )


def rule_sentiment(sentiment: dict[str, Any] | None) -> RuleResult | None:
    """Recent news tone, scaled by how much the headlines agree."""
    if not sentiment or not sentiment.get("articleCount"):
        return None

    score = float(sentiment.get("score", 0.0))
    confidence = float(sentiment.get("confidence", 0.0))
    label = sentiment.get("label", "neutral")

    return RuleResult(
        name="News sentiment",
        score=_clamp(score * (0.4 + 0.6 * confidence)),
        weight=0.15,
        rationale=(
            f"{sentiment['articleCount']} recent headlines read {label} "
            f"(agreement {confidence:.0%})."
        ),
        category="sentiment",
    )


#: Technical rules, applied to every symbol.
TECHNICAL_RULES: list[Callable[[pd.DataFrame, pd.DataFrame], RuleResult | None]] = [
    rule_trend_alignment,
    rule_momentum_rsi,
    rule_macd_crossover,
    rule_bollinger_position,
    rule_volume_confirmation,
]

#: Combined weight when every rule — technical, forecast and sentiment — fires.
#: Used to express how much of the available evidence a given signal rests on.
TECHNICAL_WEIGHT = 0.25 + 0.15 + 0.15 + 0.10 + 0.10
FORECAST_WEIGHT = 0.25
SENTIMENT_WEIGHT = 0.15
MAX_TOTAL_WEIGHT = TECHNICAL_WEIGHT + FORECAST_WEIGHT + SENTIMENT_WEIGHT


def _classify(score: float) -> str:
    if score >= STRONG_BUY_THRESHOLD:
        return "strong_buy"
    if score >= BUY_THRESHOLD:
        return "buy"
    if score <= STRONG_SELL_THRESHOLD:
        return "strong_sell"
    if score <= SELL_THRESHOLD:
        return "sell"
    return "hold"


def generate_signal(
    frame: pd.DataFrame,
    *,
    symbol: str,
    forecast: dict[str, Any] | None = None,
    sentiment: dict[str, Any] | None = None,
    indicators: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Evaluate every rule and combine them into one recommendation.

    Args:
        frame: OHLCV history.
        symbol: Ticker, for the response payload.
        forecast: Optional payload from the forecasting service.
        sentiment: Optional aggregate from the sentiment service.
        indicators: Precomputed indicator panel, recomputed if omitted.

    Returns:
        The action, the composite score, and every rule that contributed.
    """
    panel = compute_indicators(frame) if indicators is None else indicators

    results: list[RuleResult] = []
    for rule in TECHNICAL_RULES:
        try:
            outcome = rule(frame, panel)
        except Exception:  # noqa: BLE001 - one broken rule must not kill the signal
            logger.exception("signal_rule_failed rule=%s symbol=%s", rule.__name__, symbol)
            continue
        if outcome is not None:
            results.append(outcome)

    for optional in (rule_forecast(forecast), rule_sentiment(sentiment)):
        if optional is not None:
            results.append(optional)

    if not results:
        return {
            "symbol": symbol,
            "action": "hold",
            "score": 0.0,
            "confidence": 0.0,
            "rules": [],
            "summary": "Not enough history to evaluate any rule.",
        }

    total_weight = sum(rule.weight for rule in results)
    composite = sum(rule.score * rule.weight for rule in results) / total_weight

    # Confidence blends conviction with coverage: a decisive score from two
    # rules is weaker evidence than the same score from seven.
    coverage = min(1.0, total_weight / MAX_TOTAL_WEIGHT)
    confidence = round(min(1.0, abs(composite) * 1.4) * coverage, 4)

    bullish = [r for r in results if r.score > 0.1]
    bearish = [r for r in results if r.score < -0.1]
    summary = (
        f"{len(bullish)} bullish and {len(bearish)} bearish rules fired out of "
        f"{len(results)} evaluated."
    )

    if coverage < MIN_COVERAGE_FOR_ACTION:
        action = "hold"
        summary = (
            f"Only {coverage:.0%} of the rule set has enough history to evaluate; "
            "holding until more indicators warm up."
        )
    else:
        action = _classify(composite)

    return {
        "symbol": symbol,
        "action": action,
        "score": round(float(composite), 4),
        "confidence": confidence,
        "coverage": round(coverage, 4),
        "rules": [rule.to_dict() for rule in results],
        "summary": summary,
        "asOf": str(frame.index[-1].date()),
        "disclaimer": "Generated from public data for research. Not investment advice.",
    }
