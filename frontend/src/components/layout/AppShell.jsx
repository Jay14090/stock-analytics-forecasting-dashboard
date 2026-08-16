import { NavLink, Outlet } from 'react-router-dom';
import './layout.css';
import SymbolSearch from './SymbolSearch';
import { useTheme } from '../../hooks/useTheme';
import { useHealth } from '../../hooks/useMarketData';
import { Badge } from '../common';

const NAV_ITEMS = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/screener', label: 'Screener' },
  { to: '/watchlists', label: 'Watchlists' },
  { to: '/portfolio', label: 'Portfolio' },
  { to: '/models', label: 'Models' },
];

/**
 * Application frame: sidebar navigation, top bar with search, routed content.
 *
 * The backend status indicator is deliberate — the most common failure in
 * local development is a frontend running against a backend that is not, and
 * without this the symptom is an unexplained error on every panel.
 */
export default function AppShell() {
  const { theme, toggleTheme } = useTheme();
  const { data: health, isError } = useHealth();

  const status = (() => {
    if (isError) return { tone: 'down', label: 'API offline' };
    if (!health) return { tone: 'neutral', label: 'Checking…' };
    if (health.status !== 'ok') return { tone: 'warn', label: 'API degraded' };
    if (!health.checks?.forecasting?.ok) {
      return { tone: 'warn', label: 'Forecasting off' };
    }
    return { tone: 'up', label: 'API healthy' };
  })();

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true" />
          <div>
            <span className="brand-name">Stock Analytics</span>
            <span className="brand-sub">Forecasting dashboard</span>
          </div>
        </div>

        <nav aria-label="Main">
          <ul className="nav-list">
            {NAV_ITEMS.map((item) => (
              <li key={item.to}>
                <NavLink
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) => `nav-link ${isActive ? 'nav-link-active' : ''}`}
                >
                  {item.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>

        <div className="sidebar-footer">
          <Badge tone={status.tone} size="sm">
            <span className={`status-dot status-${status.tone}`} aria-hidden="true" />
            {status.label}
          </Badge>
          {health?.checks?.forecasting?.ok === false && (
            <p className="muted sidebar-note">
              TensorFlow is not installed, so forecasts are unavailable. Everything
              else works.
            </p>
          )}
        </div>
      </aside>

      <div className="main-column">
        <header className="topbar">
          <SymbolSearch />
          <button
            type="button"
            className="theme-toggle"
            onClick={toggleTheme}
            aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
            title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
          >
            {theme === 'dark' ? '☾' : '☀'}
          </button>
        </header>

        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
