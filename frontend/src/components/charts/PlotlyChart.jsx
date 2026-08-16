import { useEffect, useRef } from 'react';
import Plotly from 'plotly.js-finance-dist-min';
import { usePlotlyTheme } from './usePlotlyTheme';

/**
 * Thin React binding for Plotly.
 *
 * Written directly against the Plotly API rather than pulling in
 * `react-plotly.js`, whose peer dependencies lag current React and which adds
 * a layer that has to be worked around for resize and cleanup anyway.
 *
 * Behaviour worth knowing:
 * - `react()` is used for updates, which diffs against the existing graph
 *   instead of tearing it down, so zoom and pan survive a data refresh.
 * - A ResizeObserver keeps the plot sized to its container; Plotly's own
 *   `responsive` config only tracks the window, which misses sidebar toggles
 *   and grid reflows.
 * - The graph is purged on unmount. Skipping this leaks a WebGL context per
 *   mount, and browsers cap those at around sixteen.
 */
export default function PlotlyChart({
  data,
  layout = {},
  config = {},
  height = 420,
  onHover,
  onUnhover,
  className = '',
  ariaLabel,
}) {
  const containerRef = useRef(null);
  const initialised = useRef(false);
  const theme = usePlotlyTheme();

  useEffect(() => {
    const node = containerRef.current;
    if (!node) return undefined;

    // Axis keys must be *absent* when unused, not present-and-undefined:
    // Plotly enumerates every key matching /^[xy]axis/ and dereferences it, so
    // a `yaxis2: undefined` throws inside its layout cleaner.
    const mergedLayout = {
      ...theme.layout,
      ...layout,
      height,
      xaxis: { ...theme.layout.xaxis, ...layout.xaxis },
      yaxis: { ...theme.layout.yaxis, ...layout.yaxis },
      ...(layout.yaxis2
        ? { yaxis2: { ...theme.layout.yaxis, ...layout.yaxis2 } }
        : {}),
      legend: { ...theme.layout.legend, ...layout.legend },
      margin: { ...theme.layout.margin, ...layout.margin },
    };

    // The spread of `layout` above can still carry an explicit undefined from
    // a caller; drop those before handing the object to Plotly.
    Object.keys(mergedLayout).forEach((key) => {
      if (mergedLayout[key] === undefined) delete mergedLayout[key];
    });

    const mergedConfig = {
      displayModeBar: true,
      displaylogo: false,
      responsive: false, // handled by the ResizeObserver below
      modeBarButtonsToRemove: ['lasso2d', 'select2d', 'toggleSpikelines'],
      ...config,
    };

    if (!initialised.current) {
      Plotly.newPlot(node, data, mergedLayout, mergedConfig);
      initialised.current = true;
    } else {
      Plotly.react(node, data, mergedLayout, mergedConfig);
    }

    return undefined;
  }, [data, layout, config, height, theme]);

  // Keep the plot matched to its container.
  useEffect(() => {
    const node = containerRef.current;
    if (!node || typeof ResizeObserver === 'undefined') return undefined;

    let frame = 0;
    const observer = new ResizeObserver(() => {
      // Coalesce bursts of resize events into one relayout per frame.
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        if (containerRef.current) Plotly.Plots.resize(containerRef.current);
      });
    });

    observer.observe(node);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, []);

  // Hover handlers are attached separately so changing them does not force a
  // full replot.
  useEffect(() => {
    const node = containerRef.current;
    if (!node || !initialised.current) return undefined;

    if (onHover) node.on('plotly_hover', onHover);
    if (onUnhover) node.on('plotly_unhover', onUnhover);

    return () => {
      if (onHover) node.removeAllListeners?.('plotly_hover');
      if (onUnhover) node.removeAllListeners?.('plotly_unhover');
    };
  }, [onHover, onUnhover]);

  // Release the graph (and its WebGL context) on unmount.
  useEffect(() => {
    const node = containerRef.current;
    return () => {
      if (node) Plotly.purge(node);
    };
  }, []);

  return (
    <div
      ref={containerRef}
      className={className}
      role="img"
      aria-label={ariaLabel}
      style={{ width: '100%', height }}
    />
  );
}
