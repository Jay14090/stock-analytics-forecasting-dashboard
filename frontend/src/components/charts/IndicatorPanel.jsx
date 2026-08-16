import { useMemo } from 'react';
import PlotlyChart from './PlotlyChart';
import { usePlotlyTheme } from './usePlotlyTheme';

/**
 * Oscillator panels (RSI, MACD, Stochastic).
 *
 * Each oscillator gets its own chart rather than sharing an axis: RSI lives in
 * 0–100 and MACD is centred on zero at price scale, so overlaying them makes
 * one of the two unreadable.
 */

/** RSI with its conventional 30/70 bands shaded. */
export function RsiChart({ rows = [], height = 180 }) {
  const theme = usePlotlyTheme();

  const { data, layout } = useMemo(() => {
    const dates = rows.map((r) => r.date);
    return {
      data: [
        {
          type: 'scatter',
          mode: 'lines',
          name: 'RSI (14)',
          x: dates,
          y: rows.map((r) => r.rsi14),
          line: { color: theme.colors.series[1], width: 1.6 },
          connectgaps: false,
        },
      ],
      layout: {
        yaxis: { range: [0, 100], tickvals: [0, 30, 50, 70, 100], title: { text: 'RSI' } },
        showlegend: false,
        shapes: [
          {
            type: 'rect', xref: 'paper', x0: 0, x1: 1, yref: 'y', y0: 70, y1: 100,
            fillcolor: theme.colors.down, opacity: 0.08, line: { width: 0 },
          },
          {
            type: 'rect', xref: 'paper', x0: 0, x1: 1, yref: 'y', y0: 0, y1: 30,
            fillcolor: theme.colors.up, opacity: 0.08, line: { width: 0 },
          },
          {
            type: 'line', xref: 'paper', x0: 0, x1: 1, yref: 'y', y0: 50, y1: 50,
            line: { color: theme.colors.muted, width: 1, dash: 'dot' },
          },
        ],
        margin: { l: 48, r: 24, t: 8, b: 28 },
      },
    };
  }, [rows, theme]);

  return <PlotlyChart data={data} layout={layout} height={height} ariaLabel="Relative Strength Index" />;
}

/** MACD line, signal line and a signed histogram. */
export function MacdChart({ rows = [], height = 200 }) {
  const theme = usePlotlyTheme();

  const { data, layout } = useMemo(() => {
    const dates = rows.map((r) => r.date);
    const histogram = rows.map((r) => r.macdHistogram);

    return {
      data: [
        {
          type: 'bar',
          name: 'Histogram',
          x: dates,
          y: histogram,
          marker: {
            color: histogram.map((value) =>
              value >= 0 ? theme.colors.up : theme.colors.down,
            ),
            opacity: 0.5,
          },
        },
        {
          type: 'scatter',
          mode: 'lines',
          name: 'MACD',
          x: dates,
          y: rows.map((r) => r.macd),
          line: { color: theme.colors.accent, width: 1.6 },
          connectgaps: false,
        },
        {
          type: 'scatter',
          mode: 'lines',
          name: 'Signal',
          x: dates,
          y: rows.map((r) => r.macdSignal),
          line: { color: theme.colors.warn, width: 1.4, dash: 'dash' },
          connectgaps: false,
        },
      ],
      layout: {
        yaxis: { title: { text: 'MACD' }, zeroline: true },
        margin: { l: 48, r: 24, t: 8, b: 28 },
        barmode: 'relative',
      },
    };
  }, [rows, theme]);

  return <PlotlyChart data={data} layout={layout} height={height} ariaLabel="MACD" />;
}

/** Portfolio or index equity curve as a filled area. */
export function EquityCurveChart({ points = [], height = 300, label = 'Portfolio value' }) {
  const theme = usePlotlyTheme();

  const { data, layout } = useMemo(() => {
    const values = points.map((p) => p.value);
    // Colour the curve by its overall direction so a losing period is obvious
    // before reading a single number.
    const gaining = values.length > 1 && values[values.length - 1] >= values[0];
    const colour = gaining ? theme.colors.up : theme.colors.down;

    return {
      data: [
        {
          type: 'scatter',
          mode: 'lines',
          name: label,
          x: points.map((p) => p.date),
          y: values,
          line: { color: colour, width: 2 },
          fill: 'tozeroy',
          fillcolor: gaining ? 'rgba(38,169,108,0.12)' : 'rgba(226,85,92,0.12)',
        },
      ],
      layout: {
        yaxis: { title: { text: 'Value' }, tickformat: ',.0f' },
        showlegend: false,
        margin: { l: 64, r: 24, t: 12, b: 32 },
      },
    };
  }, [points, label, theme]);

  return <PlotlyChart data={data} layout={layout} height={height} ariaLabel={label} />;
}

/** Allocation donut. */
export function AllocationChart({ positions = [], height = 300 }) {
  const theme = usePlotlyTheme();

  const { data, layout } = useMemo(
    () => ({
      data: [
        {
          type: 'pie',
          hole: 0.62,
          labels: positions.map((p) => p.symbol),
          values: positions.map((p) => p.marketValue ?? 0),
          marker: {
            colors: positions.map(
              (_, index) => theme.colors.series[index % theme.colors.series.length],
            ),
            line: { color: 'transparent', width: 0 },
          },
          textinfo: 'label+percent',
          textposition: 'outside',
          // Keep every label rendered even when slices get thin; Plotly hides
          // outside labels that collide unless it is told not to.
          automargin: true,
          hovertemplate: '%{label}: %{value:,.0f} (%{percent})<extra></extra>',
          sort: true,
        },
      ],
      layout: {
        showlegend: false,
        // Outside labels need room on all four sides or they clip at the
        // plot edge — the top and bottom slices are the ones that suffer.
        margin: { l: 60, r: 60, t: 40, b: 40 },
        hovermode: 'closest',
      },
    }),
    [positions, theme],
  );

  return <PlotlyChart data={data} layout={layout} height={height} ariaLabel="Portfolio allocation" />;
}
