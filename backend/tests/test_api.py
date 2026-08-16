"""HTTP layer: routing, validation, error envelope and persistence.

Market-data calls are patched, so these tests exercise the API contract rather
than Yahoo Finance's availability.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

import pytest

from app.errors import NotFoundError, UpstreamError
from app.services.market_data import Quote


@pytest.fixture
def fake_quote():
    return Quote(
        symbol="AAPL",
        name="Apple Inc.",
        price=200.0,
        previous_close=190.0,
        change=10.0,
        change_percent=5.2631,
        currency="USD",
        exchange="NasdaqGS",
        market_cap=3_000_000_000_000,
        volume=50_000_000,
        day_high=201.0,
        day_low=195.0,
    )


class TestSystemEndpoints:
    def test_root_describes_the_service(self, client):
        payload = client.get("/").get_json()
        assert payload["name"]
        assert payload["health"] == "/api/health"

    def test_health_reports_ok(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.get_json()["status"] == "ok"

    def test_health_reports_forecasting_availability(self, client):
        checks = client.get("/api/health").get_json()["checks"]
        assert "forecasting" in checks
        assert isinstance(checks["forecasting"]["ok"], bool)

    def test_routes_index_is_populated(self, client):
        payload = client.get("/api/routes").get_json()
        assert payload["count"] > 20

    def test_response_time_header_is_set(self, client):
        assert "X-Response-Time-Ms" in client.get("/api/health").headers

    def test_unknown_route_returns_the_error_envelope(self, client):
        response = client.get("/api/does-not-exist")
        assert response.status_code == 404
        assert "error" in response.get_json()


class TestStockEndpoints:
    def test_quote_returns_camel_case_payload(self, client, fake_quote):
        with patch("app.api.stocks.market_data.fetch_quote", return_value=fake_quote):
            payload = client.get("/api/stocks/AAPL/quote").get_json()
        assert payload["symbol"] == "AAPL"
        assert payload["changePercent"] == pytest.approx(5.2631)

    def test_history_serialises_candles(self, client, ohlcv):
        with patch("app.api.stocks.market_data.fetch_history", return_value=ohlcv):
            payload = client.get("/api/stocks/AAPL/history?period=1y").get_json()
        assert payload["count"] == len(ohlcv)
        candle = payload["candles"][0]
        assert set(candle) >= {"date", "open", "high", "low", "close", "volume"}

    def test_history_rejects_an_unsupported_period(self, client):
        response = client.get("/api/stocks/AAPL/history?period=42y")
        assert response.status_code == 400
        assert response.get_json()["error"]["code"] == "bad_request"

    def test_unknown_symbol_returns_404_envelope(self, client):
        with patch(
            "app.api.stocks.market_data.fetch_quote",
            side_effect=NotFoundError("Unknown ticker 'NOPE'."),
        ):
            response = client.get("/api/stocks/NOPE/quote")
        assert response.status_code == 404
        assert response.get_json()["error"]["code"] == "not_found"

    def test_provider_outage_surfaces_as_502(self, client):
        with patch(
            "app.api.stocks.market_data.fetch_quote",
            side_effect=UpstreamError("Yahoo Finance is unavailable."),
        ):
            response = client.get("/api/stocks/AAPL/quote")
        assert response.status_code == 502
        assert response.get_json()["error"]["code"] == "upstream_error"

    def test_bulk_quotes_reports_missing_symbols(self, client, fake_quote):
        with patch(
            "app.api.stocks.market_data.fetch_quotes",
            return_value=[fake_quote.to_dict()],
        ):
            payload = client.get("/api/stocks/quotes?symbols=AAPL,GHOST").get_json()
        assert payload["returned"] == 1
        assert payload["missing"] == ["GHOST"]

    def test_bulk_quotes_requires_symbols(self, client):
        assert client.get("/api/stocks/quotes").status_code == 400

    def test_bulk_quotes_enforces_a_limit(self, client):
        symbols = ",".join(f"SYM{i}" for i in range(60))
        response = client.get(f"/api/stocks/quotes?symbols={symbols}")
        assert response.status_code == 400
        assert response.get_json()["error"]["details"]["limit"] == 40

    def test_search_requires_two_characters(self, client):
        assert client.get("/api/stocks/search?q=a").status_code == 400

    def test_news_attaches_sentiment(self, client):
        articles = [
            {
                "id": "1",
                "title": "Apple beats estimates as revenue surges",
                "summary": "",
                "publisher": "Wire",
                "url": "https://example.com",
                "publishedAt": "2026-08-16T10:00:00+00:00",
            }
        ]
        with patch("app.api.stocks.market_data.fetch_news", return_value=articles):
            payload = client.get("/api/stocks/AAPL/news").get_json()
        assert payload["sentiment"]["label"] == "positive"
        assert payload["articles"][0]["score"] > 0


class TestAnalysisEndpoints:
    def test_indicators_include_warmup_nulls(self, client, ohlcv):
        with patch("app.api.analysis.market_data.fetch_history", return_value=ohlcv):
            payload = client.get("/api/indicators/AAPL").get_json()
        first = payload["indicators"][0]
        # SMA-200 cannot exist on day one; it must be null, not 0.
        assert first["sma200"] is None
        assert "statistics" in payload

    def test_indicator_subset_selection(self, client, ohlcv):
        with patch("app.api.analysis.market_data.fetch_history", return_value=ohlcv):
            payload = client.get("/api/indicators/AAPL?indicators=rsi14,sma20").get_json()
        assert set(payload["indicators"][0]) == {"date", "rsi14", "sma20"}

    def test_unknown_indicator_is_rejected_with_options(self, client, ohlcv):
        with patch("app.api.analysis.market_data.fetch_history", return_value=ohlcv):
            response = client.get("/api/indicators/AAPL?indicators=nonsense")
        assert response.status_code == 400
        assert "available" in response.get_json()["error"]["details"]

    def test_signal_returns_rules(self, client, ohlcv):
        with patch("app.api.analysis.market_data.fetch_history", return_value=ohlcv), patch(
            "app.api.analysis._sentiment_for", return_value=None
        ):
            payload = client.get("/api/signals/AAPL").get_json()
        assert payload["action"] in {"strong_buy", "buy", "hold", "sell", "strong_sell"}
        assert payload["rules"]

    def test_screen_ranks_by_score_and_reports_failures(self, client, ohlcv):
        def history(symbol, **_):
            if symbol == "BAD":
                raise NotFoundError("Unknown ticker 'BAD'.")
            return ohlcv

        with patch("app.api.analysis.market_data.fetch_history", side_effect=history):
            payload = client.get("/api/signals?symbols=AAPL,MSFT,BAD").get_json()

        assert payload["evaluated"] == 2
        assert payload["failures"][0]["symbol"] == "BAD"
        scores = [item["score"] for item in payload["results"]]
        assert scores == sorted(scores, reverse=True)

    def test_screen_enforces_a_limit(self, client):
        symbols = ",".join(f"S{i}" for i in range(30))
        assert client.get(f"/api/signals?symbols={symbols}").status_code == 400

    def test_models_endpoint_reports_availability(self, client):
        payload = client.get("/api/models").get_json()
        assert "tensorflowAvailable" in payload
        assert isinstance(payload["models"], list)

    def test_deleting_an_unknown_model_is_404(self, client):
        assert client.delete("/api/models/NOSUCH").status_code == 404


class TestWatchlistEndpoints:
    def test_create_and_list(self, client):
        created = client.post("/api/watchlists", json={"name": "Tech"})
        assert created.status_code == 201

        payload = client.get("/api/watchlists").get_json()
        assert [w["name"] for w in payload["watchlists"]] == ["Tech"]

    def test_duplicate_name_conflicts(self, client):
        client.post("/api/watchlists", json={"name": "Tech"})
        response = client.post("/api/watchlists", json={"name": "Tech"})
        assert response.status_code == 409
        assert response.get_json()["error"]["code"] == "conflict"

    def test_missing_name_is_rejected(self, client):
        response = client.post("/api/watchlists", json={})
        assert response.status_code == 400
        assert "name" in response.get_json()["error"]["details"]["fields"]

    def test_add_item_validates_the_symbol_upstream(self, client, watchlist, fake_quote):
        with patch("app.api.watchlists.market_data.fetch_quote", return_value=fake_quote):
            response = client.post(
                f"/api/watchlists/{watchlist.id}/items", json={"symbol": "aapl"}
            )
        # AAPL is already in the fixture list, so this must conflict, not duplicate.
        assert response.status_code == 409

    def test_add_new_item_succeeds(self, client, watchlist, fake_quote):
        fake_quote.symbol = "NVDA"
        with patch("app.api.watchlists.market_data.fetch_quote", return_value=fake_quote):
            response = client.post(
                f"/api/watchlists/{watchlist.id}/items", json={"symbol": "NVDA"}
            )
        assert response.status_code == 201
        assert response.get_json()["symbol"] == "NVDA"

    def test_get_with_quotes_disabled_skips_upstream(self, client, watchlist):
        payload = client.get(f"/api/watchlists/{watchlist.id}?quotes=false").get_json()
        assert payload["symbolCount"] == 2
        assert "quote" not in payload["items"][0]

    def test_delete_removes_the_list(self, client, watchlist):
        assert client.delete(f"/api/watchlists/{watchlist.id}").status_code == 200
        assert client.get(f"/api/watchlists/{watchlist.id}").status_code == 404

    def test_unknown_watchlist_is_404(self, client):
        assert client.get("/api/watchlists/9999").status_code == 404


class TestPortfolioEndpoints:
    def test_create_and_list(self, client):
        response = client.post(
            "/api/portfolios", json={"name": "Main", "cashBalance": 1000}
        )
        assert response.status_code == 201
        assert response.get_json()["cashBalance"] == 1000

    def test_valuation_folds_transactions(self, client, portfolio, fake_quote):
        with patch(
            "app.services.portfolio_analytics.fetch_quote", return_value=fake_quote
        ):
            payload = client.get(f"/api/portfolios/{portfolio.id}").get_json()

        symbols = {p["symbol"] for p in payload["positions"]}
        assert symbols == {"AAPL", "MSFT"}

        aapl = next(p for p in payload["positions"] if p["symbol"] == "AAPL")
        assert aapl["quantity"] == pytest.approx(6.0)  # 10 bought, 4 sold
        assert payload["summary"]["costBasisMethod"] == "average"

    def test_stale_quote_does_not_break_the_view(self, client, portfolio):
        with patch(
            "app.services.portfolio_analytics.fetch_quote",
            side_effect=UpstreamError("provider down"),
        ):
            payload = client.get(f"/api/portfolios/{portfolio.id}").get_json()

        assert all(position["stale"] for position in payload["positions"])
        assert set(payload["summary"]["staleSymbols"]) == {"AAPL", "MSFT"}

    def test_add_transaction_updates_cash(self, client):
        created = client.post("/api/portfolios", json={"name": "Cash", "cashBalance": 10_000})
        portfolio_id = created.get_json()["id"]

        response = client.post(
            f"/api/portfolios/{portfolio_id}/transactions",
            json={"symbol": "AAPL", "kind": "buy", "quantity": 10, "price": 100, "fees": 5},
        )
        assert response.status_code == 201

        payload = client.get(f"/api/portfolios/{portfolio_id}").get_json()
        assert payload["cashBalance"] == pytest.approx(10_000 - 1005)

    def test_deleting_a_transaction_reverses_the_cash_impact(self, client):
        created = client.post("/api/portfolios", json={"name": "Undo", "cashBalance": 5_000})
        portfolio_id = created.get_json()["id"]

        added = client.post(
            f"/api/portfolios/{portfolio_id}/transactions",
            json={"symbol": "AAPL", "kind": "buy", "quantity": 5, "price": 100},
        ).get_json()

        client.delete(f"/api/portfolios/{portfolio_id}/transactions/{added['id']}")
        payload = client.get(f"/api/portfolios/{portfolio_id}").get_json()
        assert payload["cashBalance"] == pytest.approx(5_000)

    def test_future_trade_date_is_rejected(self, client, portfolio):
        response = client.post(
            f"/api/portfolios/{portfolio.id}/transactions",
            json={
                "symbol": "AAPL", "kind": "buy", "quantity": 1, "price": 100,
                "tradedOn": (date.today() + timedelta(days=5)).isoformat(),
            },
        )
        assert response.status_code == 400

    def test_invalid_transaction_kind_is_rejected(self, client, portfolio):
        response = client.post(
            f"/api/portfolios/{portfolio.id}/transactions",
            json={"symbol": "AAPL", "kind": "short", "quantity": 1, "price": 100},
        )
        assert response.status_code == 400

    def test_negative_quantity_is_rejected(self, client, portfolio):
        response = client.post(
            f"/api/portfolios/{portfolio.id}/transactions",
            json={"symbol": "AAPL", "kind": "buy", "quantity": -5, "price": 100},
        )
        assert response.status_code == 400


class TestCacheEndpoints:
    def test_stats_are_reported(self, client):
        payload = client.get("/api/cache").get_json()
        assert {"entries", "hits", "misses", "hitRate"} & set(payload) or "hit_rate" in payload

    def test_cache_can_be_cleared(self, client):
        assert client.delete("/api/cache").status_code == 200
