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
  SegmentedControl,
} from '../components/common';
import { useScreen } from '../hooks/useMarketData';
import { describeAction, formatPercent } from '../utils/format';
import './pages.css';

const DEFAULT_SYMBOLS = 'AAPL, MSFT, NVDA, GOOGL, AMZN, META, TSLA, AMD';
const PERIODS = ['3mo', '6mo', '1y'];

/**
 * Run the signal engine across a list of tickers and rank the results.
 *
 * The symbol list is submitted explicitly rather than screening as the user
 * types: each symbol costs a history fetch plus a full indicator pass.
 */
export default function ScreenerPage() {
  const navigate = useNavigate();
  const [input, setInput] = useState(DEFAULT_SYMBOLS);
  const [submitted, setSubmitted] = useState([]);
  const [period, setPeriod] = useState('6mo');

  const screen = useScreen(submitted, { period });

  function run(event) {
    event.preventDefault();
    const symbols = input
      .split(',')
      .map((value) => value.trim().toUpperCase())
      .filter(Boolean);
    setSubmitted(symbols);
  }

  return (
    <div className="stack">
      <header>
        <h1>Screener</h1>
        <p className="secondary">
          Scores each symbol against the full rule set — trend, RSI, MACD,
          Bollinger position and volume confirmation — and ranks them.
        </p>
      </header>

      <Card>
        <form className="screener-form" onSubmit={run}>
          <div className="field">
            <label htmlFor="screener-symbols" className="label">
              Symbols (comma separated, max 25)
            </label>
            <input
              id="screener-symbols"
              className="text-input"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="AAPL, MSFT, RELIANCE.NS"
            />
          </div>

          <div className="field">
            <span className="label">Period</span>
            <SegmentedControl
              options={PERIODS}
              value={period}
              onChange={setPeriod}
              ariaLabel="Screening period"
            />
          </div>

          <Button type="submit" variant="primary" loading={screen.isFetching}>
            Run screen
          </Button>
        </form>
      </Card>

      {screen.isError && <ErrorState error={screen.error} onRetry={screen.refetch} />}

      {screen.isFetching && <Loading label={`Screening ${submitted.length} symbols`} height={200} />}

      {!submitted.length && !screen.isFetching && (
        <EmptyState
          icon="◎"
          title="Nothing screened yet"
          description="Enter symbols above and run the screen to rank them by composite signal score."
        />
      )}

      {screen.data && !screen.isFetching && (
        <>
          <Card
            title="Results"
            subtitle={`${screen.data.evaluated} symbols scored over ${screen.data.period}`}
            padded={false}
          >
            <DataTable
              keyField="symbol"
              rows={screen.data.results}
              onRowClick={(row) => navigate(`/stock/${row.symbol}`)}
              emptyMessage="No symbols could be scored."
              columns={[
                {
                  key: 'symbol',
                  header: 'Symbol',
                  render: (row) => <span className="numeric strong">{row.symbol}</span>,
                },
                {
                  key: 'action',
                  header: 'Signal',
                  render: (row) => {
                    const action = describeAction(row.action);
                    return <Badge tone={action.tone}>{action.label}</Badge>;
                  },
                },
                {
                  key: 'score',
                  header: 'Score',
                  align: 'right',
                  numeric: true,
                  render: (row) => (
                    <span className={row.score >= 0 ? 'up' : 'down'}>
                      {row.score >= 0 ? '+' : ''}
                      {row.score.toFixed(3)}
                    </span>
                  ),
                },
                {
                  key: 'confidence',
                  header: 'Confidence',
                  align: 'right',
                  numeric: true,
                  render: (row) => formatPercent(row.confidence * 100, { decimals: 0 }),
                },
                {
                  key: 'summary',
                  header: 'Rules fired',
                  render: (row) => <span className="muted truncate">{row.summary}</span>,
                },
              ]}
            />
          </Card>

          {screen.data.failures?.length > 0 && (
            <Card title="Could not be screened" padded={false}>
              <DataTable
                keyField="symbol"
                rows={screen.data.failures}
                columns={[
                  {
                    key: 'symbol',
                    header: 'Symbol',
                    render: (row) => <span className="numeric">{row.symbol}</span>,
                  },
                  { key: 'reason', header: 'Reason' },
                ]}
              />
            </Card>
          )}
        </>
      )}
    </div>
  );
}
