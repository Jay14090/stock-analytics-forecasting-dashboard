/**
 * HTTP client.
 *
 * The backend returns one error envelope for every failure:
 *
 *   { "error": { "code": "not_found", "message": "...", "details": {...} } }
 *
 * This module turns that into a typed `ApiError`, so UI code branches on
 * `error.code` and never parses a message string to decide what happened.
 */

const BASE_URL = import.meta.env.VITE_API_URL || '/api';

/** Error carrying the backend's code and details alongside the HTTP status. */
export class ApiError extends Error {
  constructor(message, { status, code, details } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status ?? 0;
    this.code = code ?? 'unknown_error';
    this.details = details ?? {};
  }

  /** True when retrying might plausibly succeed. */
  get isRetryable() {
    return this.status >= 500 || this.status === 0 || this.code === 'upstream_error';
  }

  /** True when the failure is the user's input, not the system's fault. */
  get isClientError() {
    return this.status >= 400 && this.status < 500;
  }
}

function buildUrl(path, params) {
  const url = `${BASE_URL}${path}`;
  if (!params) return url;

  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return;
    query.append(key, String(value));
  });

  const serialised = query.toString();
  return serialised ? `${url}?${serialised}` : url;
}

/**
 * Perform a request and unwrap the JSON body.
 *
 * @param {string} path        Path below /api, e.g. `/stocks/AAPL/quote`.
 * @param {object} [options]
 * @param {object} [options.params]  Query parameters; empty values are dropped.
 * @param {number} [options.timeout] Abort after this many ms. Forecast requests
 *   train a model synchronously and legitimately take a minute, so callers
 *   raise this rather than the default being set high for everything.
 */
export async function request(path, { params, timeout = 30000, ...init } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);

  let response;
  try {
    response = await fetch(buildUrl(path, params), {
      headers: {
        Accept: 'application/json',
        ...(init.body ? { 'Content-Type': 'application/json' } : {}),
        ...init.headers,
      },
      signal: controller.signal,
      ...init,
    });
  } catch (cause) {
    clearTimeout(timer);
    if (cause.name === 'AbortError') {
      throw new ApiError(`The request timed out after ${timeout / 1000}s.`, {
        code: 'timeout',
      });
    }
    throw new ApiError('Could not reach the server. Is the backend running?', {
      code: 'network_error',
    });
  }
  clearTimeout(timer);

  // 204 and friends carry no body.
  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;

  if (!response.ok) {
    const envelope = payload?.error ?? {};
    throw new ApiError(envelope.message || `Request failed (${response.status}).`, {
      status: response.status,
      code: envelope.code,
      details: envelope.details,
    });
  }

  return payload;
}

export const http = {
  get: (path, options) => request(path, { method: 'GET', ...options }),
  post: (path, body, options) =>
    request(path, { method: 'POST', body: JSON.stringify(body ?? {}), ...options }),
  delete: (path, options) => request(path, { method: 'DELETE', ...options }),
};
