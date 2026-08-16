import { useMemo } from 'react';
import { useTheme } from '../../hooks/useTheme';

/**
 * Resolve the current CSS design tokens into a Plotly layout.
 *
 * Plotly cannot read CSS custom properties, so the values are pulled off the
 * computed root style at render time. Reading them (rather than duplicating a
 * palette here) keeps charts and interface in lockstep: retuning `tokens.css`
 * retunes the charts too.
 */
export function usePlotlyTheme() {
  const { theme } = useTheme();

  return useMemo(() => {
    const styles = getComputedStyle(document.documentElement);
    const token = (name, fallback) =>
      styles.getPropertyValue(name).trim() || fallback;

    const text = token('--text-secondary', '#9aa8c4');
    const muted = token('--text-muted', '#6b7a99');
    const grid = token('--grid', 'rgba(148,163,184,0.12)');
    const surface = token('--bg-surface', '#121826');
    const border = token('--border', '#253049');

    const axis = {
      gridcolor: grid,
      zerolinecolor: grid,
      linecolor: border,
      tickfont: { color: muted, size: 11, family: token('--font-mono', 'monospace') },
      titlefont: { color: text, size: 12 },
      automargin: true,
    };

    return {
      theme,
      colors: {
        up: token('--up', '#26a96c'),
        down: token('--down', '#e2555c'),
        accent: token('--accent', '#3d9df6'),
        warn: token('--warn', '#d9a441'),
        neutral: token('--neutral', '#7d8aa8'),
        series: [
          token('--series-1', '#3d9df6'),
          token('--series-2', '#b98cf0'),
          token('--series-3', '#f0b64c'),
          token('--series-4', '#4fd1c5'),
          token('--series-5', '#ef7ea8'),
        ],
        text,
        muted,
      },
      layout: {
        paper_bgcolor: 'transparent',
        plot_bgcolor: 'transparent',
        font: {
          family: token('--font-sans', 'system-ui'),
          color: text,
          size: 12,
        },
        margin: { l: 56, r: 24, t: 16, b: 40 },
        hovermode: 'x unified',
        hoverlabel: {
          bgcolor: surface,
          bordercolor: border,
          font: { color: token('--text-primary', '#e8edf7'), size: 12 },
        },
        legend: {
          orientation: 'h',
          y: 1.06,
          x: 0,
          font: { size: 11, color: muted },
          bgcolor: 'transparent',
        },
        xaxis: { ...axis, showspikes: true, spikecolor: muted, spikethickness: 1, spikemode: 'across' },
        yaxis: axis,
        dragmode: 'pan',
      },
    };
  }, [theme]);
}
