/**
 * API surface.
 *
 * One function per endpoint, grouped by resource. Components never build URLs
 * or query strings themselves, so a route change is a one-line edit here.
 */

import { http } from './client';

export const stocks = {
  search: (q, limit = 10) => http.get('/stocks/search', { params: { q, limit } }),

  quote: (symbol) => http.get(`/stocks/${encodeURIComponent(symbol)}/quote`),

  quotes: (symbols) =>
    http.get('/stocks/quotes', { params: { symbols: symbols.join(',') } }),

  history: (symbol, { period = '1y', interval = '1d' } = {}) =>
    http.get(`/stocks/${encodeURIComponent(symbol)}/history`, {
      params: { period, interval },
    }),

  news: (symbol, limit = 15) =>
    http.get(`/stocks/${encodeURIComponent(symbol)}/news`, { params: { limit } }),
};

export const analysis = {
  indicators: (symbol, { period = '1y', indicators } = {}) =>
    http.get(`/indicators/${encodeURIComponent(symbol)}`, {
      params: { period, indicators },
    }),

  /**
   * Forecast. Training happens synchronously on a cache miss and takes ~30s on
   * a few years of daily data, hence the raised timeout.
   */
  forecast: (symbol, { horizon = 5, period = '2y', retrain = false } = {}) =>
    http.get(`/forecast/${encodeURIComponent(symbol)}`, {
      params: { horizon, period, retrain },
      timeout: 180000,
    }),

  train: (symbol, body = {}) =>
    http.post(`/forecast/${encodeURIComponent(symbol)}/train`, body, {
      timeout: 300000,
    }),

  signal: (symbol, { period = '1y', includeForecast = false, includeSentiment = true } = {}) =>
    http.get(`/signals/${encodeURIComponent(symbol)}`, {
      params: { period, includeForecast, includeSentiment },
      timeout: includeForecast ? 180000 : 30000,
    }),

  screen: (symbols, { period = '6mo', includeSentiment = false } = {}) =>
    http.get('/signals', {
      params: { symbols: symbols.join(','), period, includeSentiment },
      timeout: 90000,
    }),

  models: () => http.get('/models'),

  deleteModel: (symbol) => http.delete(`/models/${encodeURIComponent(symbol)}`),
};

export const watchlists = {
  list: () => http.get('/watchlists'),
  create: (name) => http.post('/watchlists', { name }),
  get: (id, { quotes = true } = {}) =>
    http.get(`/watchlists/${id}`, { params: { quotes } }),
  remove: (id) => http.delete(`/watchlists/${id}`),
  addItem: (id, symbol, note) => http.post(`/watchlists/${id}/items`, { symbol, note }),
  removeItem: (id, itemId) => http.delete(`/watchlists/${id}/items/${itemId}`),
};

export const portfolios = {
  list: () => http.get('/portfolios'),
  create: (payload) => http.post('/portfolios', payload),
  get: (id) => http.get(`/portfolios/${id}`),
  remove: (id) => http.delete(`/portfolios/${id}`),
  performance: (id, period = '1y') =>
    http.get(`/portfolios/${id}/performance`, { params: { period }, timeout: 90000 }),
  transactions: (id) => http.get(`/portfolios/${id}/transactions`),
  addTransaction: (id, payload) => http.post(`/portfolios/${id}/transactions`, payload),
  removeTransaction: (id, transactionId) =>
    http.delete(`/portfolios/${id}/transactions/${transactionId}`),
};

export const system = {
  health: () => http.get('/health'),
  cache: () => http.get('/cache'),
  clearCache: (prefix) => http.delete('/cache', { params: { prefix } }),
};
