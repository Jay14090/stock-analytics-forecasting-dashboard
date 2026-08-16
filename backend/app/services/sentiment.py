"""News sentiment scoring.

A lexicon scorer tuned for financial headlines rather than a general-purpose
model. The reasoning: headlines are short, domain-specific and full of terms a
general model reads backwards ("shares plunge on beat"), and shipping a
transformer for a decorative panel would dominate both the image size and the
request latency. The lexicon is transparent and each score is explainable,
which matters more here than a couple of points of accuracy.

Scores are in [-1, 1]; the polarity bands are deliberately wide because a
headline scorer should abstain more often than it commits.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

logger = logging.getLogger(__name__)

# --- Lexicon -------------------------------------------------------------
# Weights are hand-set on a -3..3 scale, then normalised at scoring time.
# Terms were chosen from the vocabulary that actually recurs in equity
# headlines rather than from a general sentiment corpus.

_POSITIVE: dict[str, float] = {
    "beat": 2.2, "beats": 2.2, "tops": 2.0, "surge": 2.6, "surges": 2.6,
    "soar": 2.8, "soars": 2.8, "rally": 2.2, "rallies": 2.2, "jump": 2.0,
    "jumps": 2.0, "climb": 1.6, "climbs": 1.6, "gain": 1.5, "gains": 1.5,
    "rise": 1.4, "rises": 1.4, "upgrade": 2.4, "upgrades": 2.4,
    "upgraded": 2.4, "outperform": 2.2, "outperforms": 2.2, "record": 1.8,
    "profit": 1.6, "profits": 1.6, "growth": 1.5, "strong": 1.7,
    "stronger": 1.8, "robust": 1.7, "bullish": 2.5, "buy": 1.6,
    "overweight": 1.8, "raises": 1.7, "raised": 1.7, "boost": 1.8,
    "boosts": 1.8, "expands": 1.3, "expansion": 1.3, "breakthrough": 2.3,
    "approval": 1.9, "approved": 1.9, "wins": 1.9, "win": 1.9, "won": 1.7,
    "partnership": 1.2, "dividend": 1.1, "buyback": 1.6, "acquisition": 0.9,
    "milestone": 1.4, "momentum": 1.3, "optimistic": 1.8, "upside": 1.7,
    "rebound": 1.8, "recovery": 1.5, "accelerate": 1.5, "accelerates": 1.5,
    "exceeds": 2.1, "exceeded": 2.1, "highest": 1.6, "surpass": 2.0,
    "surpasses": 2.0, "innovation": 1.1, "efficient": 1.0, "upbeat": 1.9,
}

_NEGATIVE: dict[str, float] = {
    "miss": -2.2, "misses": -2.2, "missed": -2.2, "plunge": -2.8,
    "plunges": -2.8, "crash": -3.0, "crashes": -3.0, "slump": -2.4,
    "slumps": -2.4, "tumble": -2.5, "tumbles": -2.5, "fall": -1.6,
    "falls": -1.6, "drop": -1.7, "drops": -1.7, "decline": -1.6,
    "declines": -1.6, "downgrade": -2.4, "downgrades": -2.4,
    "downgraded": -2.4, "underperform": -2.2, "weak": -1.8, "weaker": -1.9,
    "bearish": -2.5, "sell": -1.6, "underweight": -1.8, "loss": -2.0,
    "losses": -2.0, "cuts": -1.8, "cut": -1.7, "slashes": -2.3,
    "slashed": -2.3, "warns": -2.2, "warning": -2.1, "concern": -1.5,
    "concerns": -1.5, "risk": -1.2, "risks": -1.2, "lawsuit": -2.1,
    "probe": -2.0, "investigation": -2.1, "fraud": -3.0, "recall": -2.2,
    "layoffs": -2.3, "layoff": -2.3, "bankruptcy": -3.0, "default": -2.7,
    "delay": -1.6, "delays": -1.6, "delayed": -1.6, "halt": -1.9,
    "halted": -1.9, "sinks": -2.4, "sink": -2.4, "slide": -1.9,
    "slides": -1.9, "pressure": -1.3, "headwind": -1.7, "headwinds": -1.7,
    "shortfall": -2.1, "disappointing": -2.3, "disappoints": -2.3,
    "lowest": -1.6, "struggles": -2.0, "struggling": -2.0, "selloff": -2.4,
    "volatile": -1.2, "uncertainty": -1.5, "scrutiny": -1.6, "penalty": -2.0,
    "fine": -1.5, "resigns": -1.7, "resignation": -1.7, "downturn": -2.2,
}

#: Multiply the score of the following term.
_INTENSIFIERS: dict[str, float] = {
    "very": 1.4, "extremely": 1.6, "sharply": 1.5, "significantly": 1.4,
    "massive": 1.6, "massively": 1.6, "hugely": 1.5, "record": 1.3,
    "slightly": 0.6, "marginally": 0.5, "somewhat": 0.7, "modestly": 0.7,
}

#: Flip the polarity of a term appearing shortly after.
_NEGATORS = frozenset(
    {"not", "no", "never", "without", "fails", "fail", "failed", "unable",
     "isn't", "wasn't", "won't", "doesn't", "didn't", "cannot", "despite"}
)

#: How many tokens a negator reaches forward.
_NEGATION_WINDOW = 3

_TOKEN_RE = re.compile(r"[a-z']+")

POSITIVE_THRESHOLD = 0.12
NEGATIVE_THRESHOLD = -0.12


@dataclass(slots=True)
class HeadlineSentiment:
    """The score for a single article, with the terms that produced it."""

    title: str
    score: float
    label: str
    matched_terms: list[str] = field(default_factory=list)
    url: str | None = None
    publisher: str | None = None
    published_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "score": self.score,
            "label": self.label,
            "matchedTerms": self.matched_terms,
            "url": self.url,
            "publisher": self.publisher,
            "publishedAt": self.published_at,
        }


def _label_for(score: float) -> str:
    if score >= POSITIVE_THRESHOLD:
        return "positive"
    if score <= NEGATIVE_THRESHOLD:
        return "negative"
    return "neutral"


def score_text(text: str) -> tuple[float, list[str]]:
    """Score one piece of text.

    Returns:
        ``(score, matched_terms)`` where score is in [-1, 1]. The raw sum is
        squashed with ``tanh`` so a headline stuffed with charged words cannot
        dominate an average, while a single strong term still registers.
    """
    if not text:
        return 0.0, []

    tokens = _TOKEN_RE.findall(text.lower())
    if not tokens:
        return 0.0, []

    total = 0.0
    matched: list[str] = []

    for index, token in enumerate(tokens):
        weight = _POSITIVE.get(token) or _NEGATIVE.get(token)
        if weight is None:
            continue

        # An intensifier scales the term. Both neighbours are checked because
        # headline grammar puts the adverb on either side: "sharply lower" but
        # also "shares fall sharply". Only the stronger of the two applies, so
        # "very sharply" does not multiply twice.
        modifiers = [_INTENSIFIERS.get(tokens[index - 1], 1.0)] if index > 0 else []
        if index + 1 < len(tokens):
            modifiers.append(_INTENSIFIERS.get(tokens[index + 1], 1.0))
        if modifiers:
            # Pick the neighbour furthest from 1.0 — an amplifier or a damper.
            weight *= max(modifiers, key=lambda factor: abs(factor - 1.0))

        # A negator within the preceding window flips and dampens it:
        # "not strong" is bearish, but weaker than an outright "weak".
        window = tokens[max(0, index - _NEGATION_WINDOW) : index]
        if any(word in _NEGATORS for word in window):
            weight *= -0.75

        total += weight
        matched.append(token)

    if not matched:
        return 0.0, []

    return round(math.tanh(total / 4.0), 4), matched


def score_headlines(articles: Iterable[dict[str, Any]]) -> list[HeadlineSentiment]:
    """Score a batch of articles from :func:`market_data.fetch_news`.

    The title carries most of the signal; the summary is included at reduced
    weight because it is often boilerplate.
    """
    scored: list[HeadlineSentiment] = []
    for article in articles:
        title = (article.get("title") or "").strip()
        if not title:
            continue

        title_score, title_terms = score_text(title)
        summary_score, summary_terms = score_text(article.get("summary") or "")
        combined = round(math.tanh(title_score + 0.35 * summary_score), 4)

        scored.append(
            HeadlineSentiment(
                title=title,
                score=combined,
                label=_label_for(combined),
                matched_terms=sorted(set(title_terms + summary_terms))[:8],
                url=article.get("url"),
                publisher=article.get("publisher"),
                published_at=article.get("publishedAt"),
            )
        )
    return scored


def _recency_weight(published_at: str | None, half_life_hours: float = 48.0) -> float:
    """Exponential decay by article age, floored so old news still counts."""
    if not published_at:
        return 0.5
    try:
        stamp = datetime.fromisoformat(str(published_at).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return 0.5
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)

    age_hours = (datetime.now(timezone.utc) - stamp).total_seconds() / 3600
    if age_hours < 0:
        return 1.0
    return max(0.15, 0.5 ** (age_hours / half_life_hours))


def aggregate_sentiment(scored: list[HeadlineSentiment]) -> dict[str, Any]:
    """Roll headline scores into one recency-weighted view.

    ``confidence`` reflects both volume and agreement: a single charged
    headline should not read as a strong signal, and neither should twenty
    headlines that cancel each other out.
    """
    if not scored:
        return {
            "score": 0.0,
            "label": "neutral",
            "confidence": 0.0,
            "articleCount": 0,
            "distribution": {"positive": 0, "neutral": 0, "negative": 0},
        }

    weights = [_recency_weight(item.published_at) for item in scored]
    total_weight = sum(weights) or 1.0
    weighted = sum(item.score * w for item, w in zip(scored, weights)) / total_weight

    distribution = {"positive": 0, "neutral": 0, "negative": 0}
    for item in scored:
        distribution[item.label] += 1

    decisive = distribution["positive"] + distribution["negative"]
    agreement = (
        abs(distribution["positive"] - distribution["negative"]) / decisive
        if decisive
        else 0.0
    )
    volume_factor = min(1.0, len(scored) / 8.0)

    return {
        "score": round(weighted, 4),
        "label": _label_for(weighted),
        "confidence": round(agreement * volume_factor, 4),
        "articleCount": len(scored),
        "distribution": distribution,
    }
