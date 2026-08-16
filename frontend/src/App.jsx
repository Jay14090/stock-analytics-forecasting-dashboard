import { Component, Suspense, lazy } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import AppShell from './components/layout/AppShell';
import { ErrorState, Loading } from './components/common';

// Route-level code splitting. The chart pages pull in Plotly, which is by far
// the largest dependency; splitting keeps it out of the initial bundle.
const DashboardPage = lazy(() => import('./pages/DashboardPage'));
const StockDetailPage = lazy(() => import('./pages/StockDetailPage'));
const ScreenerPage = lazy(() => import('./pages/ScreenerPage'));
const WatchlistPage = lazy(() => import('./pages/WatchlistPage'));
const PortfolioPage = lazy(() => import('./pages/PortfolioPage'));
const ModelsPage = lazy(() => import('./pages/ModelsPage'));

/**
 * Catches render-time errors so one broken panel does not blank the app.
 * Class component because React exposes no hook equivalent.
 */
class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error('Unhandled render error:', error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: 'var(--space-6)' }}>
          <ErrorState
            error={this.state.error}
            onRetry={() => this.setState({ error: null })}
          />
        </div>
      );
    }
    return this.props.children;
  }
}

export default function App() {
  return (
    <ErrorBoundary>
      <Routes>
        <Route path="/" element={<AppShell />}>
          <Route
            index
            element={
              <Suspense fallback={<Loading label="Loading dashboard" height={320} />}>
                <DashboardPage />
              </Suspense>
            }
          />
          <Route
            path="stock/:symbol"
            element={
              <Suspense fallback={<Loading label="Loading chart" height={420} />}>
                <StockDetailPage />
              </Suspense>
            }
          />
          <Route
            path="screener"
            element={
              <Suspense fallback={<Loading label="Loading screener" />}>
                <ScreenerPage />
              </Suspense>
            }
          />
          <Route
            path="watchlists"
            element={
              <Suspense fallback={<Loading label="Loading watchlists" />}>
                <WatchlistPage />
              </Suspense>
            }
          />
          <Route
            path="portfolio"
            element={
              <Suspense fallback={<Loading label="Loading portfolio" />}>
                <PortfolioPage />
              </Suspense>
            }
          />
          <Route
            path="models"
            element={
              <Suspense fallback={<Loading label="Loading models" />}>
                <ModelsPage />
              </Suspense>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </ErrorBoundary>
  );
}
