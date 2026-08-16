"""News sentiment scoring."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services import sentiment as sent


def _article(title: str, hours_ago: float = 1.0, summary: str = "") -> dict:
    stamp = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return {
        "title": title,
        "summary": summary,
        "publishedAt": stamp.isoformat(),
        "publisher": "Test Wire",
        "url": "https://example.com/a",
    }


class TestScoreText:
    def test_positive_headline_scores_positive(self):
        score, terms = sent.score_text("Company beats earnings estimates, shares surge")
        assert score > 0.2
        assert "beats" in terms

    def test_negative_headline_scores_negative(self):
        score, terms = sent.score_text("Shares plunge after profit warning and downgrade")
        assert score < -0.2
        assert "plunge" in terms

    def test_neutral_headline_scores_zero(self):
        score, terms = sent.score_text("Company schedules annual meeting for Tuesday")
        assert score == 0.0
        assert terms == []

    def test_score_is_bounded(self):
        piled_on = "surge soar rally beat jump boost record gains upgrade breakthrough"
        score, _ = sent.score_text(piled_on)
        assert -1.0 <= score <= 1.0

    def test_empty_input_is_neutral(self):
        assert sent.score_text("") == (0.0, [])

    def test_negation_flips_polarity(self):
        positive, _ = sent.score_text("Results were strong")
        negated, _ = sent.score_text("Results were not strong")
        assert positive > 0 > negated

    def test_intensifier_amplifies(self):
        plain, _ = sent.score_text("Shares fall")
        intense, _ = sent.score_text("Shares fall sharply")
        assert intense < plain

    def test_dampener_reduces_magnitude(self):
        plain, _ = sent.score_text("Shares decline")
        slight, _ = sent.score_text("Shares decline slightly")
        assert abs(slight) < abs(plain)


class TestScoreHeadlines:
    def test_labels_match_scores(self):
        scored = sent.score_headlines(
            [
                _article("Profit beats forecasts as growth accelerates"),
                _article("Regulator opens fraud investigation into the company"),
                _article("Board schedules routine meeting"),
            ]
        )
        labels = {item.label for item in scored}
        assert labels == {"positive", "negative", "neutral"}

    def test_articles_without_titles_are_dropped(self):
        assert sent.score_headlines([{"title": "", "summary": "x"}]) == []


class TestAggregate:
    def test_empty_input_is_neutral_with_no_confidence(self):
        result = sent.aggregate_sentiment([])
        assert result["label"] == "neutral"
        assert result["confidence"] == 0.0
        assert result["articleCount"] == 0

    def test_unanimous_headlines_beat_mixed_ones_on_confidence(self):
        unanimous = sent.aggregate_sentiment(
            sent.score_headlines([_article("Shares surge on upgrade")] * 8)
        )
        mixed = sent.aggregate_sentiment(
            sent.score_headlines(
                [_article("Shares surge on upgrade"), _article("Shares plunge on fraud probe")] * 4
            )
        )
        assert unanimous["confidence"] > mixed["confidence"]

    def test_recent_news_outweighs_stale_news(self):
        """A fresh negative headline should pull harder than an old positive one."""
        result = sent.aggregate_sentiment(
            sent.score_headlines(
                [
                    _article("Shares soar on record profit", hours_ago=500),
                    _article("Shares plunge on fraud probe", hours_ago=1),
                ]
            )
        )
        assert result["score"] < 0

    def test_distribution_counts_sum_to_article_count(self):
        scored = sent.score_headlines(
            [
                _article("Profit beats forecasts"),
                _article("Shares plunge on downgrade"),
                _article("Company confirms meeting date"),
            ]
        )
        result = sent.aggregate_sentiment(scored)
        assert sum(result["distribution"].values()) == result["articleCount"] == 3

    def test_score_stays_bounded(self):
        scored = sent.score_headlines([_article("Shares soar on record profit beat")] * 30)
        assert -1.0 <= sent.aggregate_sentiment(scored)["score"] <= 1.0
