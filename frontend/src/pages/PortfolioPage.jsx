import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AllocationChart, EquityCurveChart } from '../components/charts/IndicatorPanel';
import {
  Badge,
  Button,
  Card,
  DataTable,
  EmptyState,
  ErrorState,
  Loading,
  SegmentedControl,
  StatTile,
} from '../components/common';
import {
  usePerformance,
  usePortfolio,
  usePortfolioMutations,
  usePortfolios,
} from '../hooks/useMarketData';
import {
  formatCurrency,
  formatDate,
  formatNumber,
  formatPercent,
  formatSigned,
  trendClass,
} from '../utils/format';
import './pages.css';

const PERIODS = ['3mo', '6mo', '1y', '2y'];

const EMPTY_TRADE = {
  symbol: '',
  kind: 'buy',
  quantity: '',
  price: '',
  fees: '',
  tradedOn: '',
};

export default function PortfolioPage() {
  const navigate = useNavigate();
  const portfolios = usePortfolios();
  const [selectedId, setSelectedId] = useState(null);
  const [period, setPeriod] = useState('1y');
  const [trade, setTrade] = useState(EMPTY_TRADE);
  const [newName, setNewName] = useState('');

  useEffect(() => {
    const available = portfolios.data?.portfolios ?? [];
    if (!available.length) {
      setSelectedId(null);
      return;
    }
    if (!available.some((item) => item.id === selectedId)) {
      setSelectedId(available[0].id);
    }
  }, [portfolios.data, selectedId]);

  const detail = usePortfolio(selectedId);
  const performance = usePerformance(selectedId, period, { enabled: Boolean(selectedId) });
  const mutations = usePortfolioMutations(selectedId);

  async function createPortfolio(event) {
    event.preventDefault();
    const name = newName.trim();
    if (!name) return;
    await mutations.create.mutateAsync({ name, cashBalance: 0 });
    setNewName('');
  }

  async function submitTrade(event) {
    event.preventDefault();
    if (!selectedId) return;

    await mutations.addTransaction.mutateAsync({
      symbol: trade.symbol.trim().toUpperCase(),
      kind: trade.kind,
      quantity: Number(trade.quantity),
      price: Number(trade.price),
      fees: trade.fees ? Number(trade.fees) : 0,
      ...(trade.tradedOn ? { tradedOn: trade.tradedOn } : {}),
    });
    setTrade(EMPTY_TRADE);
  }

  const summary = detail.data?.summary;
  const positions = detail.data?.positions ?? [];

  return (
    <div className="stack">
      <header className="spread">
        <div>
          <h1>Portfolio</h1>
          <p className="secondary">
            Positions are derived from the trade log using average cost basis.
          </p>
        </div>
        <div className="row">
          {(portfolios.data?.portfolios ?? []).map((item) => (
            <button
              key={item.id}
              type="button"
              className={`chip ${item.id === selectedId ? 'chip-active' : ''}`}
              onClick={() => setSelectedId(item.id)}
            >
              {item.name}
            </button>
          ))}
        </div>
      </header>

      {portfolios.isError && (
        <ErrorState error={portfolios.error} onRetry={portfolios.refetch} />
      )}

      {!portfolios.isLoading && !portfolios.data?.portfolios?.length && (
        <Card>
          <EmptyState
            icon="◫"
            title="No portfolios yet"
            description="Create one to start tracking holdings, cost basis and realised P&L."
            action={
              <form className="inline-form" onSubmit={createPortfolio}>
                <input
                  className="text-input"
                  value={newName}
                  onChange={(event) => setNewName(event.target.value)}
                  placeholder="Portfolio name"
                  aria-label="Portfolio name"
                />
                <Button type="submit" variant="primary" loading={mutations.create.isPending}>
                  Create
                </Button>
              </form>
            }
          />
        </Card>
      )}

      {detail.isLoading && <Loading label="Valuing positions" height={200} />}

      {summary && (
        <>
          <div className="grid-auto">
            <StatTile
              label="Total value"
              value={formatCurrency(summary.totalValue, detail.data.baseCurrency)}
              hint={`${formatCurrency(summary.cashBalance, detail.data.baseCurrency)} cash`}
            />
            <StatTile
              label="Unrealised P&L"
              value={formatSigned(summary.unrealisedPnl)}
              delta={formatPercent(summary.unrealisedPnlPercent, { signed: true })}
              tone={trendClass(summary.unrealisedPnl)}
            />
            <StatTile
              label="Realised P&L"
              value={formatSigned(summary.realisedPnl)}
              tone={trendClass(summary.realisedPnl)}
              hint={`${formatCurrency(summary.feesPaid)} in fees`}
            />
            <StatTile
              label="Today"
              value={formatSigned(summary.dayPnl)}
              delta={formatPercent(summary.dayPnlPercent, { signed: true })}
              tone={trendClass(summary.dayPnl)}
            />
            <StatTile
              label="Concentration"
              value={formatNumber(summary.concentration, 2)}
              hint="1.00 is a single holding; lower is more diversified"
            />
          </div>

          {summary.staleSymbols?.length > 0 && (
            <Card>
              <p className="muted">
                Live prices are unavailable for{' '}
                <strong>{summary.staleSymbols.join(', ')}</strong>. Those positions are
                excluded from the valuation above.
              </p>
            </Card>
          )}

          <div className="two-column">
            <Card
              title="Performance"
              subtitle="Daily value reconstructed from the trade log"
              padded={false}
              actions={
                <SegmentedControl
                  options={PERIODS}
                  value={period}
                  onChange={setPeriod}
                  ariaLabel="Performance period"
                />
              }
            >
              {performance.isLoading ? (
                <Loading height={300} />
              ) : performance.data?.points?.length ? (
                <>
                  <EquityCurveChart points={performance.data.points} />
                  <div className="metric-strip">
                    <span>
                      Return{' '}
                      <strong className={trendClass(performance.data.metrics.totalReturnPercent)}>
                        {formatPercent(performance.data.metrics.totalReturnPercent, {
                          signed: true,
                        })}
                      </strong>
                    </span>
                    <span>
                      Max drawdown{' '}
                      <strong className="down">
                        {formatPercent(performance.data.metrics.maxDrawdownPercent)}
                      </strong>
                    </span>
                    <span>
                      Sharpe{' '}
                      <strong className="numeric">
                        {formatNumber(performance.data.metrics.sharpeRatio, 2)}
                      </strong>
                    </span>
                  </div>
                </>
              ) : (
                <EmptyState
                  icon="◠"
                  title="No history to plot"
                  description="Add trades with dates in the past to build an equity curve."
                />
              )}
            </Card>

            <Card title="Allocation" subtitle="By current market value" padded={false}>
              {positions.length ? (
                <AllocationChart positions={positions} />
              ) : (
                <EmptyState icon="○" title="No open positions" />
              )}
            </Card>
          </div>

          <Card title="Positions" padded={false}>
            <DataTable
              keyField="symbol"
              rows={positions}
              onRowClick={(row) => navigate(`/stock/${row.symbol}`)}
              emptyMessage="No open positions."
              columns={[
                {
                  key: 'symbol',
                  header: 'Symbol',
                  render: (row) => <span className="numeric strong">{row.symbol}</span>,
                },
                {
                  key: 'quantity',
                  header: 'Qty',
                  align: 'right',
                  numeric: true,
                  render: (row) => formatNumber(row.quantity, 2),
                },
                {
                  key: 'averageCost',
                  header: 'Avg cost',
                  align: 'right',
                  numeric: true,
                  render: (row) => formatNumber(row.averageCost),
                },
                {
                  key: 'currentPrice',
                  header: 'Price',
                  align: 'right',
                  numeric: true,
                  render: (row) =>
                    row.stale ? <span className="muted">stale</span> : formatNumber(row.currentPrice),
                },
                {
                  key: 'marketValue',
                  header: 'Value',
                  align: 'right',
                  numeric: true,
                  render: (row) => (row.marketValue ? formatNumber(row.marketValue) : '—'),
                },
                {
                  key: 'unrealisedPnl',
                  header: 'Unrealised',
                  align: 'right',
                  numeric: true,
                  render: (row) =>
                    row.unrealisedPnl === null ? (
                      '—'
                    ) : (
                      <span className={trendClass(row.unrealisedPnl)}>
                        {formatSigned(row.unrealisedPnl)}
                      </span>
                    ),
                },
                {
                  key: 'unrealisedPnlPercent',
                  header: '%',
                  align: 'right',
                  numeric: true,
                  render: (row) =>
                    row.unrealisedPnlPercent === null ? (
                      '—'
                    ) : (
                      <Badge tone={row.unrealisedPnlPercent >= 0 ? 'up' : 'down'} size="sm">
                        {formatPercent(row.unrealisedPnlPercent, { signed: true })}
                      </Badge>
                    ),
                },
                {
                  key: 'weight',
                  header: 'Weight',
                  align: 'right',
                  numeric: true,
                  render: (row) => formatPercent(row.weight, { decimals: 1 }),
                },
              ]}
            />
          </Card>

          <div className="two-column">
            <Card title="Record a trade">
              <form className="trade-form" onSubmit={submitTrade}>
                <div className="field">
                  <label className="label" htmlFor="trade-symbol">Symbol</label>
                  <input
                    id="trade-symbol"
                    className="text-input"
                    required
                    value={trade.symbol}
                    onChange={(event) => setTrade({ ...trade, symbol: event.target.value })}
                    placeholder="AAPL"
                  />
                </div>

                <div className="field">
                  <label className="label" htmlFor="trade-kind">Side</label>
                  <select
                    id="trade-kind"
                    className="text-input"
                    value={trade.kind}
                    onChange={(event) => setTrade({ ...trade, kind: event.target.value })}
                  >
                    <option value="buy">Buy</option>
                    <option value="sell">Sell</option>
                  </select>
                </div>

                <div className="field">
                  <label className="label" htmlFor="trade-qty">Quantity</label>
                  <input
                    id="trade-qty"
                    className="text-input"
                    type="number"
                    step="any"
                    min="0"
                    required
                    value={trade.quantity}
                    onChange={(event) => setTrade({ ...trade, quantity: event.target.value })}
                  />
                </div>

                <div className="field">
                  <label className="label" htmlFor="trade-price">Price</label>
                  <input
                    id="trade-price"
                    className="text-input"
                    type="number"
                    step="any"
                    min="0"
                    required
                    value={trade.price}
                    onChange={(event) => setTrade({ ...trade, price: event.target.value })}
                  />
                </div>

                <div className="field">
                  <label className="label" htmlFor="trade-fees">Fees</label>
                  <input
                    id="trade-fees"
                    className="text-input"
                    type="number"
                    step="any"
                    min="0"
                    value={trade.fees}
                    onChange={(event) => setTrade({ ...trade, fees: event.target.value })}
                    placeholder="0"
                  />
                </div>

                <div className="field">
                  <label className="label" htmlFor="trade-date">Date</label>
                  <input
                    id="trade-date"
                    className="text-input"
                    type="date"
                    value={trade.tradedOn}
                    max={new Date().toISOString().slice(0, 10)}
                    onChange={(event) => setTrade({ ...trade, tradedOn: event.target.value })}
                  />
                </div>

                <Button
                  type="submit"
                  variant="primary"
                  loading={mutations.addTransaction.isPending}
                >
                  Record trade
                </Button>
              </form>

              {mutations.addTransaction.isError && (
                <div className="form-error">
                  <ErrorState error={mutations.addTransaction.error} compact />
                </div>
              )}
            </Card>

            <Card title="Trade history" padded={false}>
              <DataTable
                rows={detail.data?.transactions ?? []}
                emptyMessage="No trades recorded."
                columns={[
                  {
                    key: 'tradedOn',
                    header: 'Date',
                    render: (row) => formatDate(row.tradedOn),
                  },
                  {
                    key: 'symbol',
                    header: 'Symbol',
                    render: (row) => <span className="numeric">{row.symbol}</span>,
                  },
                  {
                    key: 'kind',
                    header: 'Side',
                    render: (row) => (
                      <Badge tone={row.kind === 'buy' ? 'up' : 'down'} size="sm">
                        {row.kind}
                      </Badge>
                    ),
                  },
                  {
                    key: 'quantity',
                    header: 'Qty',
                    align: 'right',
                    numeric: true,
                    render: (row) => formatNumber(row.quantity, 2),
                  },
                  {
                    key: 'price',
                    header: 'Price',
                    align: 'right',
                    numeric: true,
                    render: (row) => formatNumber(row.price),
                  },
                  {
                    key: 'actions',
                    header: '',
                    align: 'right',
                    render: (row) => (
                      <Button
                        size="sm"
                        variant="danger"
                        onClick={() => mutations.removeTransaction.mutate(row.id)}
                        aria-label={`Delete trade ${row.id}`}
                      >
                        Delete
                      </Button>
                    ),
                  },
                ]}
              />
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
