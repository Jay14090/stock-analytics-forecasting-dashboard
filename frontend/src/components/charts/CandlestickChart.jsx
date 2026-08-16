import { useMemo } from 'react';
import PlotlyChart from './PlotlyChart';
import { usePlotlyTheme } from './usePlotlyTheme';

/**
 * OHLC candlesticks with optional overlays and a volume sub-panel.
 *
 * Volume shares the x-axis on a second y-axis pinned to the bottom fifth of
 * the plot. Two stacked plots would double the axis labels and let the two
 * charts drift out of sync when the user pans.
 */
export default function CandlestickChart({
  candles = [],
  overlays = [],
  forecast = null,
  showVolume = true,
  height = 480,
  symbol = '',
}) {
  const theme = usePlotlyTheme();

  const { data, layout } = useMemo(() => {
    const dates = candles.map((c) => c.date);

    const traces = [
      {
        type: 'candlestick',
        name: symbol || 'Price',
        x: dates,
        open: candles.map((c) => c.open),
        high: candles.map((c) => c.high),
        low: candles.map((c) => c.low),
        close: candles.map((c) => c.close),
        increasing: {
          line: { color: theme.colors.up, width: 1 },
          fillcolor: theme.colors.up,
        },
        decreasing: {
          line: { color: theme.colors.down, width: 1 },
          fillcolor: theme.colors.down,
        },
        yaxis: 'y',
        hoverlabel: { namelength: -1 },
      },
    ];

    overlays.forEach((overlay, index) => {
      traces.push({
        type: 'scatter',
        mode: 'lines',
        name: overlay.name,
        x: overlay.x ?? dates,
        y: overlay.y,
        line: {
          color: overlay.color ?? theme.colors.series[index % theme.colors.series.length],
          width: overlay.width ?? 1.5,
          dash: overlay.dash,
        },
        // Gaps where an indicator has not warmed up must stay gaps.
        connectgaps: false,
        yaxis: 'y',
        opacity: overlay.opacity ?? 1,
      });
    });

    if (forecast?.length) {
      const lastCandle = candles[candles.length - 1];

      // Anchor the forecast to the final actual close so the line connects
      // instead of floating away from the history.
      const anchorDate = lastCandle?.date;
      const anchorClose = lastCandle?.close;

      const forecastX = [anchorDate, ...forecast.map((p) => p.date)];
      const upper = [anchorClose, ...forecast.map((p) => p.upperBound)];
      const lower = [anchorClose, ...forecast.map((p) => p.lowerBound)];

      traces.push(
        {
          type: 'scatter',
          mode: 'lines',
          name: '95% interval',
          x: forecastX,
          y: upper,
          line: { width: 0 },
          hoverinfo: 'skip',
          showlegend: false,
          yaxis: 'y',
        },
        {
          type: 'scatter',
          mode: 'lines',
          name: '95% interval',
          x: forecastX,
          y: lower,
          line: { width: 0 },
          fill: 'tonexty',
          fillcolor: 'rgba(61, 157, 246, 0.16)',
          hoverinfo: 'skip',
          yaxis: 'y',
        },
        {
          type: 'scatter',
          mode: 'lines+markers',
          name: 'LSTM forecast',
          x: forecastX,
          y: [anchorClose, ...forecast.map((p) => p.predictedClose)],
          line: { color: theme.colors.accent, width: 2, dash: 'dot' },
          marker: { size: 5, color: theme.colors.accent },
          yaxis: 'y',
        },
      );
    }

    if (showVolume) {
      traces.push({
        type: 'bar',
        name: 'Volume',
        x: dates,
        y: candles.map((c) => c.volume),
        marker: {
          color: candles.map((c) =>
            c.close >= c.open ? theme.colors.up : theme.colors.down,
          ),
          opacity: 0.45,
        },
        yaxis: 'y2',
        hovertemplate: '%{y:.3s}<extra>Volume</extra>',
      });
    }

    return {
      data: traces,
      layout: {
        xaxis: {
          rangeslider: { visible: false },
          type: 'date',
        },
        yaxis: {
          title: { text: 'Price' },
          domain: showVolume ? [0.24, 1] : [0, 1],
          tickformat: ',.2f',
        },
        ...(showVolume
          ? {
              yaxis2: {
                title: { text: 'Vol' },
                domain: [0, 0.18],
                tickformat: '.2s',
                showgrid: false,
              },
            }
          : {}),
        showlegend: true,
      },
    };
  }, [candles, overlays, forecast, showVolume, symbol, theme]);

  return (
    <PlotlyChart
      data={data}
      layout={layout}
      height={height}
      ariaLabel={`Candlestick chart for ${symbol || 'the selected symbol'}`}
    />
  );
}
