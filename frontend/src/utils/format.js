/**
 * Display formatting.
 *
 * Centralised because inconsistent number formatting is the fastest way to
 * make a financial UI feel untrustworthy — the same value must not appear as
 * "1,234.5" in one panel and "1234.50" in the next.
 */

const CURRENCY_SYMBOLS = {
  USD: '$',
  INR: '₹',
  EUR: '€',
  GBP: '£',
  JPY: '¥',
};

/** Currency amount, with the symbol when the code is one we recognise. */
export function formatCurrency(value, currency = 'USD', { decimals = 2 } = {}) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';

  const symbol = CURRENCY_SYMBOLS[currency];
  const formatted = Number(value).toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });

  return symbol ? `${symbol}${formatted}` : `${formatted} ${currency}`;
}

/** Plain number with thousands separators. */
export function formatNumber(value, decimals = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return Number(value).toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

/** Percentage, always signed when `signed` is set (price moves read better). */
export function formatPercent(value, { decimals = 2, signed = false } = {}) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  const sign = signed && value > 0 ? '+' : '';
  return `${sign}${Number(value).toFixed(decimals)}%`;
}

/** Compact magnitude for market caps and volumes: 1.2T, 45.3B, 890M. */
export function formatCompact(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';

  const abs = Math.abs(value);
  const tiers = [
    [1e12, 'T'],
    [1e9, 'B'],
    [1e6, 'M'],
    [1e3, 'K'],
  ];

  for (const [threshold, suffix] of tiers) {
    if (abs >= threshold) {
      return `${(value / threshold).toFixed(abs >= threshold * 10 ? 1 : 2)}${suffix}`;
    }
  }
  return String(Math.round(value));
}

/** Signed value with an explicit + so gains and losses are scannable. */
export function formatSigned(value, decimals = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  const sign = value > 0 ? '+' : '';
  return `${sign}${formatNumber(value, decimals)}`;
}

/** Short date: "16 Aug 2026". */
export function formatDate(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  });
}

/** Relative age: "3h ago", "2d ago". Used on news and model timestamps. */
export function formatRelativeTime(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);

  const seconds = Math.round((Date.now() - date.getTime()) / 1000);
  if (seconds < 60) return 'just now';

  const units = [
    [60, 'm', 60],
    [3600, 'h', 24],
    [86400, 'd', 30],
    [2592000, 'mo', 12],
  ];

  for (const [divisor, suffix, ceiling] of units) {
    const amount = Math.floor(seconds / divisor);
    if (amount < ceiling) return `${amount}${suffix} ago`;
  }
  return formatDate(value);
}

/** Direction class for colouring a value. */
export function trendClass(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return 'muted';
  if (value > 0) return 'up';
  if (value < 0) return 'down';
  return 'muted';
}

/** Turn a signal action into display text and a semantic tone. */
export function describeAction(action) {
  const map = {
    strong_buy: { label: 'Strong buy', tone: 'up' },
    buy: { label: 'Buy', tone: 'up' },
    hold: { label: 'Hold', tone: 'neutral' },
    sell: { label: 'Sell', tone: 'down' },
    strong_sell: { label: 'Strong sell', tone: 'down' },
  };
  return map[action] ?? { label: action ?? 'Unknown', tone: 'neutral' };
}
