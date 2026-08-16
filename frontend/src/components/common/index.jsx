/**
 * Shared UI primitives.
 *
 * Small and unstyled-by-default on purpose: every page composes these, so
 * behaviour (loading, empty, error) stays consistent without each page
 * inventing its own version.
 */

import './common.css';
import { ApiError } from '../../api/client';

/** Panel container with an optional header and actions. */
export function Card({ title, subtitle, actions, children, className = '', padded = true }) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="card-header">
          <div>
            {title && <h3 className="card-title">{title}</h3>}
            {subtitle && <p className="card-subtitle">{subtitle}</p>}
          </div>
          {actions && <div className="card-actions">{actions}</div>}
        </header>
      )}
      <div className={padded ? 'card-body' : 'card-body card-body-flush'}>{children}</div>
    </section>
  );
}

/** Headline figure with a label and optional delta. */
export function StatTile({ label, value, delta, deltaLabel, tone = 'neutral', hint }) {
  return (
    <div className="stat-tile">
      <span className="label">{label}</span>
      <span className={`stat-value numeric ${tone}`}>{value}</span>
      {(delta || deltaLabel) && (
        <span className="stat-delta">
          {delta && <span className={`numeric ${tone}`}>{delta}</span>}
          {deltaLabel && <span className="muted">{deltaLabel}</span>}
        </span>
      )}
      {hint && <span className="stat-hint muted">{hint}</span>}
    </div>
  );
}

/** Status pill. `tone` maps to the semantic colour set. */
export function Badge({ children, tone = 'neutral', size = 'md' }) {
  return <span className={`badge badge-${tone} badge-${size}`}>{children}</span>;
}

/** Button. `variant` covers primary / ghost / danger. */
export function Button({
  children,
  variant = 'ghost',
  size = 'md',
  loading = false,
  disabled,
  ...props
}) {
  return (
    <button
      className={`btn btn-${variant} btn-${size}`}
      disabled={disabled || loading}
      {...props}
    >
      {loading && <span className="btn-spinner" aria-hidden="true" />}
      {children}
    </button>
  );
}

/** Indeterminate loading state, sized to the region it replaces. */
export function Loading({ label = 'Loading', height = 120 }) {
  return (
    <div className="loading" style={{ minHeight: height }} role="status">
      <span className="spinner" aria-hidden="true" />
      <span className="muted">{label}…</span>
    </div>
  );
}

/** Skeleton block for content whose shape is known before its data arrives. */
export function Skeleton({ height = 16, width = '100%', radius = 4 }) {
  return (
    <span
      className="skeleton"
      style={{ height, width, borderRadius: radius }}
      aria-hidden="true"
    />
  );
}

/**
 * Error state.
 *
 * Reads the `ApiError` code to say something specific and actionable rather
 * than printing a raw exception at the user.
 */
export function ErrorState({ error, onRetry, compact = false }) {
  const isApi = error instanceof ApiError;

  const guidance = (() => {
    if (!isApi) return 'Something went wrong rendering this view.';
    switch (error.code) {
      case 'network_error':
        return 'The API is not reachable. Start the backend with `flask --app wsgi run` and try again.';
      case 'timeout':
        return 'The request took too long. Training a new model can take a minute — retry, or train it from the model panel first.';
      case 'upstream_error':
        return 'Yahoo Finance did not respond. This is usually transient; retrying in a moment normally works.';
      case 'not_found':
        return 'That symbol could not be found. Check the ticker — non-US listings need a suffix, like RELIANCE.NS.';
      case 'insufficient_data':
        return 'There is not enough price history for this calculation. Try a longer period.';
      case 'model_unavailable':
        return 'Forecasting needs TensorFlow, which is not installed on the server. Everything else still works.';
      default:
        return error.message;
    }
  })();

  return (
    <div className={`error-state ${compact ? 'error-state-compact' : ''}`} role="alert">
      <div className="error-mark" aria-hidden="true">!</div>
      <div className="stack" style={{ gap: 'var(--space-2)' }}>
        <strong>{isApi ? error.message : 'Unexpected error'}</strong>
        <p className="muted">{guidance}</p>
        {onRetry && (
          <div>
            <Button variant="primary" size="sm" onClick={onRetry}>
              Try again
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

/** Empty state with an optional call to action. */
export function EmptyState({ title, description, action, icon = '○' }) {
  return (
    <div className="empty-state">
      <span className="empty-icon" aria-hidden="true">{icon}</span>
      <strong>{title}</strong>
      {description && <p className="muted">{description}</p>}
      {action}
    </div>
  );
}

/**
 * Data table.
 *
 * Columns declare their own alignment and renderer, which keeps numeric
 * right-alignment and tabular figures consistent everywhere.
 */
export function DataTable({ columns, rows, keyField = 'id', onRowClick, emptyMessage = 'No rows.' }) {
  if (!rows?.length) {
    return <p className="muted table-empty">{emptyMessage}</p>;
  }

  return (
    <div className="scroll-x">
      <table className="data-table">
        <thead>
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                style={{ textAlign: column.align ?? 'left', width: column.width }}
                scope="col"
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row[keyField] ?? row.symbol}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              className={onRowClick ? 'clickable' : undefined}
            >
              {columns.map((column) => (
                <td
                  key={column.key}
                  style={{ textAlign: column.align ?? 'left' }}
                  className={column.numeric ? 'numeric' : undefined}
                >
                  {column.render ? column.render(row) : row[column.key]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Segmented control for small mutually-exclusive choices (period pickers). */
export function SegmentedControl({ options, value, onChange, ariaLabel }) {
  return (
    <div className="segmented" role="group" aria-label={ariaLabel}>
      {options.map((option) => {
        const optionValue = option.value ?? option;
        const label = option.label ?? option;
        const active = optionValue === value;
        return (
          <button
            key={optionValue}
            type="button"
            className={`segment ${active ? 'segment-active' : ''}`}
            aria-pressed={active}
            onClick={() => onChange(optionValue)}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}
