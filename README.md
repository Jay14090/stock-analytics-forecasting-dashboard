# Stock Analytics & Forecasting Dashboard

Technical analysis, LSTM price forecasting, news sentiment and portfolio tracking
for equities, built on Yahoo Finance data.

**Stack:** React 18 · Vite · Plotly · Flask 3 · TensorFlow 2 · SQLAlchemy · pandas

---

## What it does

- **Charting** — OHLC candlesticks with volume, moving-average and Bollinger
  overlays, and RSI/MACD oscillator panels. Indicator warm-up periods render as
  gaps rather than misleading flat lines.
- **Technical indicators** — SMA, EMA, RSI, MACD, Bollinger Bands, ATR, OBV,
  Stochastic, VWAP, rolling volatility, max drawdown and Sharpe, implemented
  directly on pandas.
- **LSTM forecasting** — a stacked LSTM per symbol predicting next-day log
  returns, extended recursively to a multi-day path with widening confidence
  intervals. Models are trained on demand, cached on disk, and retrained when
  stale.
- **News sentiment** — a finance-tuned lexicon scorer with negation and
  intensifier handling, aggregated with recency weighting. Every score shows the
  terms that produced it.
- **Signals** — a weighted rule engine combining trend, momentum, volatility,
  volume, the forecast and sentiment into a buy/sell/hold call, with each rule's
  contribution and rationale exposed.
- **Screener** — runs the rule engine across a list of tickers and ranks them.
- **Watchlists & portfolio** — grouped tickers with live quotes; positions folded
  from an append-only trade log with average cost basis, realised/unrealised P&L,
  allocation weights, equity curve, drawdown and Sharpe.

---

## Quick start

Two terminals, from the repository root.

**Backend** (Python 3.11+):

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # optional; defaults work as-is

flask --app wsgi run --debug --port 5000
```

**Frontend** (Node 18+):

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api` to Flask, so there is no CORS
setup in development.

Optional — load a demo watchlist and portfolio:

```bash
cd backend && flask --app wsgi seed
```

Optional — pre-train a model so the first forecast is instant:

```bash
flask --app wsgi train AAPL MSFT --period 5y
```

---

## Architecture

```
backend/
  app/
    __init__.py          Application factory, request hooks, CLI commands
    config.py            Environment-driven config (dev / testing / production)
    errors.py            Error taxonomy and the single JSON error envelope
    extensions.py        SQLAlchemy + CORS singletons
    schemas.py           Marshmallow request validation, JSON serialisation
    api/                 Blueprints: stocks, analysis, watchlists, portfolios, system
    models/              ORM: watchlists, portfolios, transactions
    services/
      market_data.py     Yahoo Finance access, retries, normalisation
      cache.py           Thread-safe TTL + LRU cache
      indicators.py      Technical indicators
      sentiment.py       Lexicon sentiment scorer
      signals.py         Weighted rule engine
      portfolio_analytics.py   Position folding, valuation, equity curve
      forecasting/
        dataset.py       Feature engineering, scaling, windowing
        model.py         Keras architecture, metrics
        registry.py      Atomic on-disk model store
        service.py       Training and recursive multi-step inference
  tests/                 137 tests, no network access
frontend/
  src/
    api/                 HTTP client (typed errors) + endpoint definitions
    hooks/               TanStack Query data hooks, theme context
    components/
      charts/            Plotly binding and chart components
      common/            Card, StatTile, Badge, DataTable, error/empty states
      analysis/          Signal, forecast and news panels
      layout/            App shell, sidebar, symbol search
    pages/               Dashboard, Stock detail, Screener, Watchlists, Portfolio, Models
    utils/               Display formatting
```

### Design decisions worth calling out

**The model predicts returns, not prices.** A network trained on raw price levels
memorises the range of its training window and degrades as soon as the stock
trades outside it. Log returns are stationary and additive, so a multi-step path
reconstructs by summation rather than compounding rounding error.

**Scalers are fitted on the training split only.** Fitting on the whole series
leaks the validation range's min/max backwards into training. It produces
better-looking offline metrics that cannot be reproduced live. `tests/
test_forecasting.py` asserts this explicitly, because it is invisible at runtime.

**The split is chronological, never shuffled.** Random splits on a time series
let the model validate on days it effectively saw during training.

**Every forecast reports its skill against a naive baseline.** RMSE alone on
daily returns is close to meaningless — predicting "no change" is already a
strong competitor. The API returns `baselineRmse` and a `skillScore`, and the
signal engine discounts the forecast rule by measured directional accuracy, so a
model at chance accuracy contributes nothing.

**Signals are a rule engine, not a classifier.** Every recommendation has to be
explainable. Each rule returns a score, a weight and a sentence of rationale, and
the UI renders all of them. A black-box classifier would need a separate
explanation layer to say the same thing less honestly.

**The engine abstains when it cannot see.** Below a minimum rule coverage the
action is forced to `hold` — on a short history most indicators are still warming
up, and a directional call resting on one warmed-up rule is noise in the costume
of a recommendation.

**Positions are derived, never stored.** Holding a mutable quantity column beside
an append-only transaction log gives you two sources of truth that drift, and the
drift always surfaces as a P&L number nobody can explain.

**Market data is cached aggressively.** Yahoo Finance rate-limits hard. Quotes
are cached for 60s, daily history for 15 minutes, news for 30 minutes, through a
thread-safe TTL+LRU cache. Swapping in Redis means reimplementing `get`/`set`.

---

## Honest notes on model performance

Trained on five years of daily AAPL data (975 windows, 35 epochs, early
stopping):

| Metric                | Value    |
| --------------------- | -------- |
| Directional accuracy  | 54.4%    |
| Validation RMSE       | 0.016709 |
| Baseline RMSE         | 0.016734 |
| Skill vs baseline     | +0.0015  |

That is a *marginal* edge over predicting no change, and it is the expected
result. Daily equity returns are close to unpredictable from price history
alone; anything claiming 90%+ accuracy on this task is almost always measuring
price level rather than return, or leaking future data through its scaler.

The dashboard surfaces these numbers next to every forecast rather than hiding
them, and the signal engine weights the forecast by them. It is a demonstration
of a correctly-built forecasting pipeline, not a trading edge.

---

## API

`GET /api/routes` returns the full machine-readable index. Highlights:

| Method   | Route                                     | Purpose                              |
| -------- | ----------------------------------------- | ------------------------------------ |
| `GET`    | `/api/health`                             | Liveness + dependency status         |
| `GET`    | `/api/stocks/search?q=`                   | Ticker search                        |
| `GET`    | `/api/stocks/<symbol>/quote`              | Current snapshot                     |
| `GET`    | `/api/stocks/quotes?symbols=A,B`          | Bulk quotes (partial failures dropped)|
| `GET`    | `/api/stocks/<symbol>/history?period=1y`  | OHLCV candles                        |
| `GET`    | `/api/stocks/<symbol>/news`               | Headlines with sentiment             |
| `GET`    | `/api/indicators/<symbol>`                | Full indicator panel                 |
| `GET`    | `/api/forecast/<symbol>?horizon=5`        | LSTM forecast (trains on cache miss) |
| `POST`   | `/api/forecast/<symbol>/train`            | Force a retrain                      |
| `GET`    | `/api/signals/<symbol>`                   | Signal with rule breakdown           |
| `GET`    | `/api/signals?symbols=A,B`                | Screen and rank                      |
| `GET`    | `/api/models`                             | Trained model registry               |
| `GET`    | `/api/watchlists`, `/api/portfolios`      | CRUD roots                           |

Every error shares one envelope:

```json
{ "error": { "code": "not_found", "message": "…", "details": {} } }
```

Codes: `bad_request`, `not_found`, `conflict`, `upstream_error`,
`insufficient_data`, `model_unavailable`, `internal_error`.

---

## Testing

```bash
cd backend
pip install -r requirements-dev.txt
pytest                    # 137 tests
pytest --cov=app          # with coverage
```

No test touches the network — market data is synthesised from a seeded generator,
so the suite is deterministic and runs offline. Coverage includes indicator
correctness against hand-computed values, the two time-series leakage properties
described above, position-folding arithmetic checked against manually worked
examples, a real end-to-end LSTM training run, and the full HTTP surface with the
provider mocked.

---

## Configuration

All optional; see `backend/.env.example` for the full list with defaults.

| Variable                            | Default | Notes                                 |
| ----------------------------------- | ------- | ------------------------------------- |
| `APP_ENV`                           | `development` | `development`/`testing`/`production` |
| `SECRET_KEY`                        | dev value | **Required** in production          |
| `DATABASE_URL`                      | SQLite  | Any SQLAlchemy URL                    |
| `QUOTE_CACHE_TTL` / `HISTORY_CACHE_TTL` | 60 / 900 | Seconds                        |
| `SEQUENCE_LENGTH` / `FORECAST_HORIZON`  | 60 / 5   | LSTM window and horizon        |
| `TRAIN_EPOCHS`                      | 40      | Early stopping usually halts sooner   |
| `MODEL_MAX_AGE_HOURS`               | 24      | Retrain threshold                     |

TensorFlow is an **optional** dependency. Without it the API starts normally,
`/api/health` reports forecasting as unavailable, the forecast endpoints return
`503 model_unavailable`, and every other feature works.

---

## Production notes

```bash
# Backend
APP_ENV=production SECRET_KEY=… gunicorn --workers 2 --threads 4 --timeout 180 wsgi:app

# Frontend
npm run build      # emits frontend/dist/
```

Use few workers with threads rather than many processes: training holds the GIL
for tens of seconds and the market-data cache is per-process. The `--timeout 180`
matters because training runs synchronously inside the request.

---

## Limitations

- Yahoo Finance is an unofficial, rate-limited source with no uptime guarantee.
- Forecasts are recursive, so error compounds with the horizon; intervals widen
  accordingly and horizons beyond ~10 sessions are not meaningful.
- Synthetic OHLC bars generated during recursive forecasting fill high/low/volume
  from recent averages — scaffolding for the next step's features, never
  presented as forecasts themselves.
- Cost basis is average-cost only; FIFO lot tracking is not implemented.
- Forecast trading days are weekday-based and ignore exchange holiday calendars.
- Single-user: there is no authentication or per-user data isolation.

---

## Licence & disclaimer

Educational project. Everything here is generated from public data for research
purposes and is **not investment advice**.
