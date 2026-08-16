import { Badge, Button, Card, DataTable, EmptyState, ErrorState, Loading } from '../common';
import {
  formatNumber,
  formatPercent,
  formatRelativeTime,
  trendClass,
} from '../../utils/format';
import './analysis.css';

/**
 * LSTM forecast panel.
 *
 * Loading a forecast is an explicit action, not automatic: a cache miss trains
 * a model synchronously and takes about half a minute, which is not something
 * to trigger silently on page load.
 *
 * The validation metrics are shown next to the forecast on purpose. A forecast
 * without its measured skill invites more trust than it has earned, and on
 * daily returns the honest skill score is usually close to zero.
 */
export default function ForecastCard({ query, symbol, requested, onRequest }) {
  const { data, isLoading, isError, error, refetch } = query;

  if (!requested) {
    return (
      <Card title="LSTM forecast">
        <EmptyState
          icon="◈"
          title="Forecast not generated"
          description={`Runs a stacked LSTM over ${symbol}'s recent history to project the next five sessions. If no model is cached, one is trained first — that takes roughly 30 seconds.`}
          action={
            <Button variant="primary" onClick={onRequest}>
              Generate forecast
            </Button>
          }
        />
      </Card>
    );
  }

  if (isLoading) {
    return (
      <Card title="LSTM forecast">
        <Loading label="Training model and forecasting" height={220} />
        <p className="muted disclaimer">
          First run for a symbol trains from scratch. Subsequent forecasts reuse the
          cached model and return immediately.
        </p>
      </Card>
    );
  }

  if (isError) {
    return (
      <Card title="LSTM forecast">
        <ErrorState error={error} onRetry={refetch} compact />
      </Card>
    );
  }

  const { metrics, model } = data;
  const tone = trendClass(data.expectedChangePercent);

  // Directional accuracy is the metric that matters for a trading decision,
  // and 50% is a coin flip. Flag anything at or below that plainly.
  const beatsChance = metrics.directionalAccuracy > 0.5;
  const beatsBaseline = metrics.skillScore > 0;

  return (
    <Card
      title="LSTM forecast"
      subtitle={`${data.horizon} sessions ahead from ${data.lastDate}`}
      actions={
        <Badge tone={tone === 'muted' ? 'neutral' : tone} size="lg">
          {formatPercent(data.expectedChangePercent, { signed: true })}
        </Badge>
      }
    >
      <DataTable
        keyField="date"
        rows={data.forecast}
        columns={[
          { key: 'date', header: 'Date' },
          {
            key: 'predictedClose',
            header: 'Predicted',
            align: 'right',
            numeric: true,
            render: (row) => formatNumber(row.predictedClose),
          },
          {
            key: 'interval',
            header: '95% interval',
            align: 'right',
            numeric: true,
            render: (row) =>
              `${formatNumber(row.lowerBound)} – ${formatNumber(row.upperBound)}`,
          },
        ]}
      />

      <div className="metric-grid">
        <div className="metric">
          <span className="label">Directional accuracy</span>
          <span className={`numeric ${beatsChance ? 'up' : 'down'}`}>
            {formatPercent(metrics.directionalAccuracy * 100, { decimals: 1 })}
          </span>
          <span className="muted metric-note">
            {beatsChance ? 'better than a coin flip' : 'at or below chance'}
          </span>
        </div>

        <div className="metric">
          <span className="label">Skill vs baseline</span>
          <span className={`numeric ${beatsBaseline ? 'up' : 'down'}`}>
            {metrics.skillScore >= 0 ? '+' : ''}
            {metrics.skillScore.toFixed(4)}
          </span>
          <span className="muted metric-note">
            against predicting no change
          </span>
        </div>

        <div className="metric">
          <span className="label">Validation RMSE</span>
          <span className="numeric">{metrics.rmse.toFixed(5)}</span>
          <span className="muted metric-note">
            baseline {metrics.baselineRmse.toFixed(5)}
          </span>
        </div>

        <div className="metric">
          <span className="label">Trained</span>
          <span className="numeric">{formatRelativeTime(model.trainedAt)}</span>
          <span className="muted metric-note">
            {model.trainingRows} windows · {model.epochsRun} epochs
          </span>
        </div>
      </div>

      <details className="model-details">
        <summary>Model architecture</summary>
        <dl className="model-spec">
          <dt>Network</dt>
          <dd className="numeric">{model.architecture}</dd>
          <dt>Target</dt>
          <dd>{model.target}</dd>
          <dt>Sequence length</dt>
          <dd className="numeric">{model.sequenceLength} sessions</dd>
          <dt>Features</dt>
          <dd className="numeric">{model.features.join(', ')}</dd>
        </dl>
      </details>

      <p className="disclaimer muted">{data.disclaimer}</p>
    </Card>
  );
}
