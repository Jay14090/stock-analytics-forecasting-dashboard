import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Badge,
  Button,
  Card,
  DataTable,
  EmptyState,
  ErrorState,
  Loading,
} from '../components/common';
import { useModels, useTrainModel } from '../hooks/useMarketData';
import { analysis } from '../api/endpoints';
import { formatNumber, formatPercent, formatRelativeTime } from '../utils/format';
import './pages.css';

/**
 * Trained model registry.
 *
 * Training from here rather than from the chart lets a user warm a model up
 * before they need the forecast, which is the difference between a 30-second
 * wait and an instant one.
 */
export default function ModelsPage() {
  const navigate = useNavigate();
  const models = useModels();
  const train = useTrainModel();
  const [symbol, setSymbol] = useState('');

  async function submit(event) {
    event.preventDefault();
    const ticker = symbol.trim().toUpperCase();
    if (!ticker) return;
    await train.mutateAsync({ symbol: ticker, period: '5y', force: true });
    setSymbol('');
  }

  async function evict(ticker) {
    await analysis.deleteModel(ticker);
    models.refetch();
  }

  const available = models.data?.tensorflowAvailable;

  return (
    <div className="stack">
      <header>
        <h1>Forecasting models</h1>
        <p className="secondary">
          One LSTM per symbol, trained on demand and cached on disk. Models are
          retrained automatically once they are a day old or new sessions have closed.
        </p>
      </header>

      {available === false && (
        <Card>
          <ErrorState
            error={{
              message: 'TensorFlow is not installed on the server.',
              code: 'model_unavailable',
              isClientError: false,
            }}
            compact
          />
        </Card>
      )}

      <Card title="Train a model">
        <form className="inline-form" onSubmit={submit}>
          <input
            className="text-input"
            value={symbol}
            onChange={(event) => setSymbol(event.target.value)}
            placeholder="Symbol, e.g. AAPL"
            aria-label="Symbol to train"
            disabled={!available}
          />
          <Button
            type="submit"
            variant="primary"
            loading={train.isPending}
            disabled={!available}
          >
            Train
          </Button>
        </form>

        <p className="muted disclaimer">
          Training runs synchronously over five years of daily data and takes roughly
          30 seconds. The request holds open until it finishes.
        </p>

        {train.isError && (
          <div className="form-error">
            <ErrorState error={train.error} compact />
          </div>
        )}

        {train.isSuccess && (
          <div className="train-result">
            <Badge tone="up">Trained {train.data.symbol}</Badge>
            <span className="muted">
              {train.data.epochsRun} epochs over {train.data.trainingRows} windows ·
              directional accuracy{' '}
              {formatPercent(train.data.metrics.directionalAccuracy * 100, { decimals: 1 })}
            </span>
          </div>
        )}
      </Card>

      <Card title="Stored models" padded={false}>
        {models.isLoading ? (
          <Loading height={160} />
        ) : models.data?.models?.length ? (
          <DataTable
            keyField="symbol"
            rows={models.data.models}
            columns={[
              {
                key: 'symbol',
                header: 'Symbol',
                render: (row) => (
                  <button
                    type="button"
                    className="link-button numeric strong"
                    onClick={() => navigate(`/stock/${row.symbol}`)}
                  >
                    {row.symbol}
                  </button>
                ),
              },
              {
                key: 'trainedAt',
                header: 'Trained',
                render: (row) => formatRelativeTime(row.trainedAt),
              },
              {
                key: 'directional',
                header: 'Directional acc.',
                align: 'right',
                numeric: true,
                render: (row) => (
                  <span className={row.metrics.directionalAccuracy > 0.5 ? 'up' : 'down'}>
                    {formatPercent(row.metrics.directionalAccuracy * 100, { decimals: 1 })}
                  </span>
                ),
              },
              {
                key: 'skill',
                header: 'Skill vs baseline',
                align: 'right',
                numeric: true,
                render: (row) => (
                  <span className={row.metrics.skillScore > 0 ? 'up' : 'down'}>
                    {row.metrics.skillScore >= 0 ? '+' : ''}
                    {formatNumber(row.metrics.skillScore, 4)}
                  </span>
                ),
              },
              {
                key: 'rmse',
                header: 'RMSE',
                align: 'right',
                numeric: true,
                render: (row) => formatNumber(row.metrics.rmse, 5),
              },
              {
                key: 'epochs',
                header: 'Epochs',
                align: 'right',
                numeric: true,
                render: (row) => row.epochsRun,
              },
              {
                key: 'rows',
                header: 'Windows',
                align: 'right',
                numeric: true,
                render: (row) => formatNumber(row.trainingRows, 0),
              },
              {
                key: 'actions',
                header: '',
                align: 'right',
                render: (row) => (
                  <Button size="sm" variant="danger" onClick={() => evict(row.symbol)}>
                    Evict
                  </Button>
                ),
              },
            ]}
          />
        ) : (
          <EmptyState
            icon="◈"
            title="No models trained yet"
            description="Train one above, or generate a forecast from any stock page — the first forecast trains and caches the model."
          />
        )}
      </Card>
    </div>
  );
}
