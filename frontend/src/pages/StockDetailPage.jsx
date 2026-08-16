import { useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import CandlestickChart from '../components/charts/CandlestickChart';
import { MacdChart, RsiChart } from '../components/charts/IndicatorPanel';
import SignalCard from '../components/analysis/SignalCard';
import ForecastCard from '../components/analysis/ForecastCard';
import NewsFeed from '../components/analysis/NewsFeed';
import {
  Badge,
  Card,
  ErrorState,
  Loading,
  SegmentedControl,
  StatTile,
} from '../components/common';
import {
  useForecast,
  useHistory,
  useIndicators,
  useNews,
  useQuote,
  useSignal,
} from '../hooks/useMarketData';
import {
  formatCompact,
  formatCurrency,
  formatNumber,
  formatPercent,
  trendClass,
} from '../utils/format';
import './pages.css';

const PERIODS = ['3mo', '6mo', '1y', '2y', '5y'];

const OVERLAY_OPTIONS = [
  { key: 'sma20', name: 'SMA 20' },
  { key: 'sma50', name: 'SMA 50' },
  { key: 'sma200', name: 'SMA 200' },
  { key: 'bbUpper', name: 'BB upper', dash: 'dot' },
  { key: 'bbLower', name: 'BB lower', dash: 'dot' },
];

export default function StockDetailPage() {
  const { symbol } = useParams();
  const [period, setPeriod] = useState('1y');
  const [activeOverlays, setActiveOverlays] = useState(['sma50', 'sma200']);
  const [forecastRequested, setForecastRequested] = useState(false);

  const quote = useQuote(symbol, { live: true });
  const history = useHistory(symbol, { period });
  const indicators = useIndicators(symbol, { period });
  const signal = useSignal(symbol, { period });
  const news = useNews(symbol);
  const forecast = useForecast(symbol, { horizon: 5, enabled: forecastRequested });

  // Indicator rows are keyed by date; index them so overlays align to candles
  // even if the two endpoints return slightly different ranges.
  const overlays = useMemo(() => {
    const rows = indicators.data?.indicators;
    if (!rows) return [];

    return OVERLAY_OPTIONS.filter((option) => activeOverlays.includes(option.key)).map(
      (option) => ({
        name: option.name,
        x: rows.map((row) => row.date),
        y: rows.map((row) => row[option.key]),
        dash: option.dash,
        width: option.dash ? 1 : 1.5,
        opacity: option.dash ? 0.7 : 1,
      }),
    );
  }, [indicators.data, activeOverlays]);

  function toggleOverlay(key) {
    setActiveOverlays((current) =>
      current.includes(key) ? current.filter((item) => item !== key) : [...current, key],
    );
  }

  if (quote.isError) {
    return <ErrorState error={quote.error} onRetry={quote.refetch} />;
  }

  const data = quote.data;
  const changeTone = trendClass(data?.change);

  return (
    <div className="stack">
      {/* --- Header ---------------------------------------------------- */}
      <header className="detail-header">
        <div className="detail-identity">
          <div className="row">
            <h1 className="numeric">{symbol?.toUpperCase()}</h1>
            {data?.exchange && <Badge tone="neutral">{data.exchange}</Badge>}
          </div>
          <p className="secondary">{quote.isLoading ? 'Loading…' : data?.name}</p>
          {(data?.sector || data?.industry) && (
            <p className="muted detail-sector">
              {[data.sector, data.industry].filter(Boolean).join(' · ')}
            </p>
          )}
        </div>

        {data && (
          <div className="detail-price">
            <span className="numeric detail-last">
              {formatCurrency(data.price, data.currency)}
            </span>
            <span className={`numeric detail-change ${changeTone}`}>
              {formatCurrency(data.change, data.currency)} (
              {formatPercent(data.changePercent, { signed: true })})
            </span>
          </div>
        )}
      </header>

      {/* --- Key statistics -------------------------------------------- */}
      {data && (
        <div className="grid-auto">
          <StatTile
            label="Day range"
            value={`${formatNumber(data.dayLow)} – ${formatNumber(data.dayHigh)}`}
          />
          <StatTile
            label="52-week range"
            value={
              data.fiftyTwoWeekLow
                ? `${formatNumber(data.fiftyTwoWeekLow)} – ${formatNumber(data.fiftyTwoWeekHigh)}`
                : '—'
            }
          />
          <StatTile label="Volume" value={formatCompact(data.volume)} />
          <StatTile label="Market cap" value={formatCompact(data.marketCap)} />
          {indicators.data?.statistics && (
            <>
              <StatTile
                label={`Return (${period})`}
                value={formatPercent(indicators.data.statistics.totalReturnPercent, {
                  signed: true,
                })}
                tone={trendClass(indicators.data.statistics.totalReturnPercent)}
              />
              <StatTile
                label="Max drawdown"
                value={formatPercent(indicators.data.statistics.maxDrawdownPercent)}
                tone="down"
                hint="Worst peak-to-trough decline in this window"
              />
            </>
          )}
        </div>
      )}

      {/* --- Price chart ------------------------------------------------ */}
      <Card
        title="Price"
        subtitle={
          forecast.data
            ? 'Candles with indicator overlays and the LSTM forecast path'
            : 'Candles with indicator overlays'
        }
        padded={false}
        actions={
          <SegmentedControl
            options={PERIODS}
            value={period}
            onChange={setPeriod}
            ariaLabel="Chart period"
          />
        }
      >
        <div className="chart-toolbar">
          {OVERLAY_OPTIONS.map((option) => (
            <button
              key={option.key}
              type="button"
              className={`chip ${activeOverlays.includes(option.key) ? 'chip-active' : ''}`}
              onClick={() => toggleOverlay(option.key)}
              aria-pressed={activeOverlays.includes(option.key)}
            >
              {option.name}
            </button>
          ))}
        </div>

        {history.isLoading && <Loading label="Loading price history" height={420} />}
        {history.isError && (
          <div style={{ padding: 'var(--space-5)' }}>
            <ErrorState error={history.error} onRetry={history.refetch} />
          </div>
        )}
        {history.data && (
          <CandlestickChart
            symbol={symbol}
            candles={history.data.candles}
            overlays={overlays}
            forecast={forecast.data?.forecast}
            height={460}
          />
        )}
      </Card>

      {/* --- Oscillators ------------------------------------------------ */}
      <div className="two-column">
        <Card title="RSI (14)" subtitle="Shaded above 70 and below 30" padded={false}>
          {indicators.isLoading ? (
            <Loading height={180} />
          ) : (
            <RsiChart rows={indicators.data?.indicators ?? []} />
          )}
        </Card>

        <Card title="MACD (12, 26, 9)" subtitle="Line, signal and histogram" padded={false}>
          {indicators.isLoading ? (
            <Loading height={200} />
          ) : (
            <MacdChart rows={indicators.data?.indicators ?? []} />
          )}
        </Card>
      </div>

      {/* --- Signal, forecast, news ------------------------------------- */}
      <div className="two-column">
        <SignalCard query={signal} />
        <ForecastCard
          query={forecast}
          symbol={symbol}
          requested={forecastRequested}
          onRequest={() => setForecastRequested(true)}
        />
      </div>

      <NewsFeed query={news} />
    </div>
  );
}
