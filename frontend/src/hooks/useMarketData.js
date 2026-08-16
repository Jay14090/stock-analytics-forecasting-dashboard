/**
 * Data-fetching hooks.
 *
 * All server state goes through TanStack Query so caching, deduplication and
 * refetching are declared once per resource rather than reimplemented in every
 * component with useEffect.
 *
 * Stale times are set per resource from how fast the underlying data actually
 * changes: quotes move constantly, daily candles change once a session, and a
 * trained model is valid for a day.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { analysis, portfolios, stocks, system, watchlists } from '../api/endpoints';

export const queryKeys = {
  quote: (symbol) => ['quote', symbol],
  quotes: (symbols) => ['quotes', [...symbols].sort().join(',')],
  history: (symbol, period, interval) => ['history', symbol, period, interval],
  indicators: (symbol, period) => ['indicators', symbol, period],
  forecast: (symbol, horizon, period) => ['forecast', symbol, horizon, period],
  signal: (symbol, options) => ['signal', symbol, options],
  screen: (symbols, period) => ['screen', [...symbols].sort().join(','), period],
  news: (symbol) => ['news', symbol],
  models: () => ['models'],
  watchlists: () => ['watchlists'],
  watchlist: (id) => ['watchlist', id],
  portfolios: () => ['portfolios'],
  portfolio: (id) => ['portfolio', id],
  performance: (id, period) => ['performance', id, period],
  health: () => ['health'],
};

const MINUTE = 60 * 1000;

/** Don't retry a request the user can only fix by changing their input. */
function retryUnlessClientError(failureCount, error) {
  if (error?.isClientError) return false;
  return failureCount < 2;
}

// --- Market data ---------------------------------------------------------

export function useQuote(symbol, options = {}) {
  return useQuery({
    queryKey: queryKeys.quote(symbol),
    queryFn: () => stocks.quote(symbol),
    enabled: Boolean(symbol),
    staleTime: MINUTE,
    refetchInterval: options.live ? MINUTE : false,
    retry: retryUnlessClientError,
    ...options,
  });
}

export function useQuotes(symbols = [], options = {}) {
  return useQuery({
    queryKey: queryKeys.quotes(symbols),
    queryFn: () => stocks.quotes(symbols),
    enabled: symbols.length > 0,
    staleTime: MINUTE,
    retry: retryUnlessClientError,
    ...options,
  });
}

export function useHistory(symbol, { period = '1y', interval = '1d' } = {}, options = {}) {
  return useQuery({
    queryKey: queryKeys.history(symbol, period, interval),
    queryFn: () => stocks.history(symbol, { period, interval }),
    enabled: Boolean(symbol),
    staleTime: 15 * MINUTE,
    retry: retryUnlessClientError,
    ...options,
  });
}

export function useIndicators(symbol, { period = '1y' } = {}, options = {}) {
  return useQuery({
    queryKey: queryKeys.indicators(symbol, period),
    queryFn: () => analysis.indicators(symbol, { period }),
    enabled: Boolean(symbol),
    staleTime: 15 * MINUTE,
    retry: retryUnlessClientError,
    ...options,
  });
}

export function useNews(symbol, options = {}) {
  return useQuery({
    queryKey: queryKeys.news(symbol),
    queryFn: () => stocks.news(symbol),
    enabled: Boolean(symbol),
    staleTime: 30 * MINUTE,
    retry: retryUnlessClientError,
    ...options,
  });
}

// --- Analysis ------------------------------------------------------------

/**
 * Forecast.
 *
 * Disabled by default: a cache miss trains a model synchronously, so this must
 * be an explicit user action rather than something that fires on page load.
 */
export function useForecast(symbol, { horizon = 5, period = '2y', enabled = false } = {}) {
  return useQuery({
    queryKey: queryKeys.forecast(symbol, horizon, period),
    queryFn: () => analysis.forecast(symbol, { horizon, period }),
    enabled: Boolean(symbol) && enabled,
    staleTime: 60 * MINUTE,
    gcTime: 4 * 60 * MINUTE,
    retry: false, // a failed 30s training run should not silently run twice
  });
}

export function useSignal(symbol, { period = '1y', includeForecast = false } = {}, options = {}) {
  return useQuery({
    queryKey: queryKeys.signal(symbol, { period, includeForecast }),
    queryFn: () => analysis.signal(symbol, { period, includeForecast }),
    enabled: Boolean(symbol),
    staleTime: 10 * MINUTE,
    retry: retryUnlessClientError,
    ...options,
  });
}

export function useScreen(symbols = [], { period = '6mo' } = {}, options = {}) {
  return useQuery({
    queryKey: queryKeys.screen(symbols, period),
    queryFn: () => analysis.screen(symbols, { period }),
    enabled: symbols.length > 0,
    staleTime: 10 * MINUTE,
    retry: false,
    ...options,
  });
}

export function useModels() {
  return useQuery({
    queryKey: queryKeys.models(),
    queryFn: analysis.models,
    staleTime: 5 * MINUTE,
  });
}

export function useTrainModel() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ symbol, period, force }) => analysis.train(symbol, { period, force }),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.models() });
      queryClient.invalidateQueries({ queryKey: ['forecast', variables.symbol] });
    },
  });
}

// --- Watchlists ----------------------------------------------------------

export function useWatchlists() {
  return useQuery({
    queryKey: queryKeys.watchlists(),
    queryFn: watchlists.list,
    staleTime: 5 * MINUTE,
  });
}

export function useWatchlist(id, options = {}) {
  return useQuery({
    queryKey: queryKeys.watchlist(id),
    queryFn: () => watchlists.get(id),
    enabled: Boolean(id),
    staleTime: MINUTE,
    ...options,
  });
}

export function useWatchlistMutations(watchlistId) {
  const queryClient = useQueryClient();

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.watchlists() });
    if (watchlistId) {
      queryClient.invalidateQueries({ queryKey: queryKeys.watchlist(watchlistId) });
    }
  };

  return {
    create: useMutation({ mutationFn: watchlists.create, onSuccess: invalidate }),
    remove: useMutation({ mutationFn: watchlists.remove, onSuccess: invalidate }),
    addItem: useMutation({
      mutationFn: ({ symbol, note }) => watchlists.addItem(watchlistId, symbol, note),
      onSuccess: invalidate,
    }),
    removeItem: useMutation({
      mutationFn: (itemId) => watchlists.removeItem(watchlistId, itemId),
      onSuccess: invalidate,
    }),
  };
}

// --- Portfolios ----------------------------------------------------------

export function usePortfolios() {
  return useQuery({
    queryKey: queryKeys.portfolios(),
    queryFn: portfolios.list,
    staleTime: 5 * MINUTE,
  });
}

export function usePortfolio(id, options = {}) {
  return useQuery({
    queryKey: queryKeys.portfolio(id),
    queryFn: () => portfolios.get(id),
    enabled: Boolean(id),
    staleTime: MINUTE,
    ...options,
  });
}

export function usePerformance(id, period = '1y', options = {}) {
  return useQuery({
    queryKey: queryKeys.performance(id, period),
    queryFn: () => portfolios.performance(id, period),
    enabled: Boolean(id),
    staleTime: 15 * MINUTE,
    ...options,
  });
}

export function usePortfolioMutations(portfolioId) {
  const queryClient = useQueryClient();

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.portfolios() });
    if (portfolioId) {
      queryClient.invalidateQueries({ queryKey: queryKeys.portfolio(portfolioId) });
      queryClient.invalidateQueries({ queryKey: ['performance', portfolioId] });
    }
  };

  return {
    create: useMutation({ mutationFn: portfolios.create, onSuccess: invalidate }),
    remove: useMutation({ mutationFn: portfolios.remove, onSuccess: invalidate }),
    addTransaction: useMutation({
      mutationFn: (payload) => portfolios.addTransaction(portfolioId, payload),
      onSuccess: invalidate,
    }),
    removeTransaction: useMutation({
      mutationFn: (transactionId) =>
        portfolios.removeTransaction(portfolioId, transactionId),
      onSuccess: invalidate,
    }),
  };
}

// --- System --------------------------------------------------------------

export function useHealth() {
  return useQuery({
    queryKey: queryKeys.health(),
    queryFn: system.health,
    staleTime: 30 * 1000,
    refetchInterval: 60 * 1000,
    retry: 1,
  });
}
