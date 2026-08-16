import { useEffect, useState } from 'react';
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
import {
  useWatchlist,
  useWatchlistMutations,
  useWatchlists,
} from '../hooks/useMarketData';
import { formatCompact, formatCurrency, formatPercent } from '../utils/format';
import './pages.css';

export default function WatchlistPage() {
  const navigate = useNavigate();
  const lists = useWatchlists();
  const [selectedId, setSelectedId] = useState(null);
  const [newListName, setNewListName] = useState('');
  const [newSymbol, setNewSymbol] = useState('');

  // Select the first list once they load, and recover if the selected one is
  // deleted from another tab.
  useEffect(() => {
    const available = lists.data?.watchlists ?? [];
    if (!available.length) {
      setSelectedId(null);
      return;
    }
    if (!available.some((list) => list.id === selectedId)) {
      setSelectedId(available[0].id);
    }
  }, [lists.data, selectedId]);

  const detail = useWatchlist(selectedId);
  const mutations = useWatchlistMutations(selectedId);

  async function createList(event) {
    event.preventDefault();
    const name = newListName.trim();
    if (!name) return;
    await mutations.create.mutateAsync(name);
    setNewListName('');
  }

  async function addSymbol(event) {
    event.preventDefault();
    const symbol = newSymbol.trim().toUpperCase();
    if (!symbol || !selectedId) return;
    await mutations.addItem.mutateAsync({ symbol });
    setNewSymbol('');
  }

  const items = detail.data?.items ?? [];

  return (
    <div className="stack">
      <header>
        <h1>Watchlists</h1>
        <p className="secondary">
          Group tickers and track them together. Quotes refresh each time the list
          is opened.
        </p>
      </header>

      {lists.isError && <ErrorState error={lists.error} onRetry={lists.refetch} />}

      <div className="split-layout">
        <Card title="Lists" padded={false}>
          {lists.isLoading ? (
            <Loading height={160} />
          ) : (
            <ul className="selector-list">
              {(lists.data?.watchlists ?? []).map((list) => (
                <li key={list.id}>
                  <button
                    type="button"
                    className={`selector ${list.id === selectedId ? 'selector-active' : ''}`}
                    onClick={() => setSelectedId(list.id)}
                  >
                    <span>{list.name}</span>
                    <span className="muted numeric">{list.symbolCount}</span>
                  </button>
                </li>
              ))}
              {!lists.data?.watchlists?.length && (
                <li className="selector-empty muted">No lists yet.</li>
              )}
            </ul>
          )}

          <form className="inline-form" onSubmit={createList}>
            <input
              className="text-input"
              value={newListName}
              onChange={(event) => setNewListName(event.target.value)}
              placeholder="New list name"
              aria-label="New watchlist name"
            />
            <Button type="submit" variant="primary" size="sm" loading={mutations.create.isPending}>
              Add
            </Button>
          </form>

          {mutations.create.isError && (
            <div className="form-error">
              <ErrorState error={mutations.create.error} compact />
            </div>
          )}
        </Card>

        <Card
          title={detail.data?.name ?? 'Symbols'}
          subtitle={selectedId ? `${items.length} symbols` : undefined}
          padded={false}
          actions={
            selectedId && (
              <Button
                variant="danger"
                size="sm"
                onClick={() => mutations.remove.mutate(selectedId)}
                loading={mutations.remove.isPending}
              >
                Delete list
              </Button>
            )
          }
        >
          {!selectedId ? (
            <EmptyState
              icon="◇"
              title="No list selected"
              description="Create a watchlist on the left to start tracking symbols."
            />
          ) : detail.isLoading ? (
            <Loading label="Loading quotes" height={200} />
          ) : (
            <>
              <form className="inline-form" onSubmit={addSymbol}>
                <input
                  className="text-input"
                  value={newSymbol}
                  onChange={(event) => setNewSymbol(event.target.value)}
                  placeholder="Add symbol, e.g. NVDA"
                  aria-label="Symbol to add"
                />
                <Button
                  type="submit"
                  variant="primary"
                  size="sm"
                  loading={mutations.addItem.isPending}
                >
                  Add
                </Button>
              </form>

              {mutations.addItem.isError && (
                <div className="form-error">
                  <ErrorState error={mutations.addItem.error} compact />
                </div>
              )}

              <DataTable
                rows={items}
                onRowClick={(row) => navigate(`/stock/${row.symbol}`)}
                emptyMessage="No symbols in this list yet."
                columns={[
                  {
                    key: 'symbol',
                    header: 'Symbol',
                    render: (row) => <span className="numeric strong">{row.symbol}</span>,
                  },
                  {
                    key: 'name',
                    header: 'Name',
                    render: (row) => (
                      <span className="truncate">{row.quote?.name ?? '—'}</span>
                    ),
                  },
                  {
                    key: 'price',
                    header: 'Price',
                    align: 'right',
                    numeric: true,
                    render: (row) =>
                      row.quote
                        ? formatCurrency(row.quote.price, row.quote.currency)
                        : '—',
                  },
                  {
                    key: 'change',
                    header: '%',
                    align: 'right',
                    numeric: true,
                    render: (row) =>
                      row.quote ? (
                        <Badge tone={row.quote.changePercent >= 0 ? 'up' : 'down'} size="sm">
                          {formatPercent(row.quote.changePercent, { signed: true })}
                        </Badge>
                      ) : (
                        <span className="muted">unavailable</span>
                      ),
                  },
                  {
                    key: 'volume',
                    header: 'Volume',
                    align: 'right',
                    numeric: true,
                    render: (row) => formatCompact(row.quote?.volume),
                  },
                  {
                    key: 'actions',
                    header: '',
                    align: 'right',
                    render: (row) => (
                      <Button
                        size="sm"
                        variant="danger"
                        onClick={(event) => {
                          event.stopPropagation();
                          mutations.removeItem.mutate(row.id);
                        }}
                        aria-label={`Remove ${row.symbol}`}
                      >
                        Remove
                      </Button>
                    ),
                  },
                ]}
              />
            </>
          )}
        </Card>
      </div>
    </div>
  );
}
