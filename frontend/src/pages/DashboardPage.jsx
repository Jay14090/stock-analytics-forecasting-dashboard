import { useMemo } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Badge, Card, DataTable, ErrorState, Loading, StatTile } from '../components/common';
import { usePortfolios, useQuotes, useWatchlists } from '../hooks/useMarketData';
import {
  formatCompact,
  formatCurrency,
  formatPercent,
  trendClass,
} from '../utils/format';
import './pages.css';

/** Index proxies and megacaps — a reasonable default market view. */
const MARKET_OVERVIEW = ['SPY', 'QQQ', 'DIA', 'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN'];

export default function DashboardPage() {
  const navigate = useNavigate();
  const quotes = useQuotes(MARKET_OVERVIEW);
  const watchlists = useWatchlists();
  const portfolios = usePortfolios();

  const { advancers, decliners, leader, laggard } = useMemo(() => {
    const rows = quotes.data?.quotes ?? [];
    const sorted = [...rows].sort((a, b) => b.changePercent - a.changePercent);
    return {
      advancers: rows.filter((row) => row.changePercent > 0).length,
      decliners: rows.filter((row) => row.changePercent < 0).length,
      leader: sorted[0],
      laggard: sorted[sorted.length - 1],
    };
  }, [quotes.data]);

  return (
    <div className="stack">
      <header>
        <h1>Market overview</h1>
        <p className="secondary">
          Live quotes for major indices and megacap technology. Search any ticker
          above, or press <kbd>/</kbd>.
        </p>
      </header>

      {quotes.isError && <ErrorState error={quotes.error} onRetry={quotes.refetch} />}

      {quotes.data && (
        <div className="grid-auto">
          <StatTile
            label="Advancing"
            value={advancers}
            tone="up"
            hint={`of ${quotes.data.returned} tracked`}
          />
          <StatTile label="Declining" value={decliners} tone="down" />
          {leader && (
            <StatTile
              label="Best performer"
              value={leader.symbol}
              delta={formatPercent(leader.changePercent, { signed: true })}
              tone="up"
            />
          )}
          {laggard && (
            <StatTile
              label="Worst performer"
              value={laggard.symbol}
              delta={formatPercent(laggard.changePercent, { signed: true })}
              tone="down"
            />
          )}
        </div>
      )}

      <Card
        title="Quotes"
        subtitle="Click any row to open the full chart"
        padded={false}
      >
        {quotes.isLoading ? (
          <Loading label="Loading quotes" height={260} />
        ) : (
          <DataTable
            keyField="symbol"
            rows={quotes.data?.quotes ?? []}
            onRowClick={(row) => navigate(`/stock/${row.symbol}`)}
            emptyMessage="No quotes returned."
            columns={[
              {
                key: 'symbol',
                header: 'Symbol',
                render: (row) => <span className="numeric strong">{row.symbol}</span>,
              },
              {
                key: 'name',
                header: 'Name',
                render: (row) => <span className="truncate">{row.name}</span>,
              },
              {
                key: 'price',
                header: 'Price',
                align: 'right',
                numeric: true,
                render: (row) => formatCurrency(row.price, row.currency),
              },
              {
                key: 'change',
                header: 'Change',
                align: 'right',
                numeric: true,
                render: (row) => (
                  <span className={trendClass(row.change)}>
                    {formatCurrency(row.change, row.currency)}
                  </span>
                ),
              },
              {
                key: 'changePercent',
                header: '%',
                align: 'right',
                numeric: true,
                render: (row) => (
                  <Badge tone={row.changePercent >= 0 ? 'up' : 'down'} size="sm">
                    {formatPercent(row.changePercent, { signed: true })}
                  </Badge>
                ),
              },
              {
                key: 'volume',
                header: 'Volume',
                align: 'right',
                numeric: true,
                render: (row) => formatCompact(row.volume),
              },
              {
                key: 'marketCap',
                header: 'Mkt cap',
                align: 'right',
                numeric: true,
                render: (row) => formatCompact(row.marketCap),
              },
            ]}
          />
        )}
      </Card>

      <div className="two-column">
        <Card
          title="Watchlists"
          actions={<Link to="/watchlists">Manage</Link>}
          padded={false}
        >
          {watchlists.isLoading ? (
            <Loading height={140} />
          ) : (
            <DataTable
              rows={watchlists.data?.watchlists ?? []}
              emptyMessage="No watchlists yet. Create one from the Watchlists page."
              columns={[
                { key: 'name', header: 'Name' },
                {
                  key: 'symbolCount',
                  header: 'Symbols',
                  align: 'right',
                  numeric: true,
                },
              ]}
            />
          )}
        </Card>

        <Card
          title="Portfolios"
          actions={<Link to="/portfolio">Manage</Link>}
          padded={false}
        >
          {portfolios.isLoading ? (
            <Loading height={140} />
          ) : (
            <DataTable
              rows={portfolios.data?.portfolios ?? []}
              emptyMessage="No portfolios yet. Create one from the Portfolio page."
              columns={[
                { key: 'name', header: 'Name' },
                {
                  key: 'transactionCount',
                  header: 'Trades',
                  align: 'right',
                  numeric: true,
                },
                {
                  key: 'cashBalance',
                  header: 'Cash',
                  align: 'right',
                  numeric: true,
                  render: (row) => formatCurrency(row.cashBalance, row.baseCurrency),
                },
              ]}
            />
          )}
        </Card>
      </div>
    </div>
  );
}
