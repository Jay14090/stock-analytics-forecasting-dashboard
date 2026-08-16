"""Technical indicators.

Implemented directly on pandas rather than pulled from TA-Lib: the formulas
are short, the dependency is a C extension that complicates deployment, and
having them here means the smoothing conventions are explicit and testable.

Convention throughout: every function takes an OHLCV frame indexed by date
(as produced by :mod:`app.services.market_data`) and returns a Series or frame
aligned to that same index, with ``NaN`` for the warm-up window rather than a
silently truncated series.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# Wilder's smoothing (used by RSI/ATR/ADX) is an EMA with alpha = 1/period,
# which is *not* the same as pandas' span-based EMA. Keeping it in one helper
# avoids the classic off-by-a-smoothing-factor bug.
def _wilder_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    """Simple moving average."""
    return series.rolling(window=period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential moving average (span convention)."""
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index, Wilder's original smoothing.

    Returns values in [0, 100]. A flat series has no losses, which would divide
    by zero; that case is pinned to 100 (maximum strength) by convention.
    """
    delta = close.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)

    avg_gain = _wilder_ema(gains, period)
    avg_loss = _wilder_ema(losses, period)

    rs = avg_gain / avg_loss.replace(0, np.nan)
    result = 100 - (100 / (1 + rs))
    return result.where(avg_loss != 0, 100.0).where(avg_gain.notna())


@dataclass(slots=True)
class MACDResult:
    macd: pd.Series
    signal: pd.Series
    histogram: pd.Series


def macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> MACDResult:
    """Moving Average Convergence Divergence."""
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return MACDResult(
        macd=macd_line,
        signal=signal_line,
        histogram=macd_line - signal_line,
    )


@dataclass(slots=True)
class BollingerResult:
    upper: pd.Series
    middle: pd.Series
    lower: pd.Series
    bandwidth: pd.Series
    percent_b: pd.Series


def bollinger_bands(
    close: pd.Series, period: int = 20, std_devs: float = 2.0
) -> BollingerResult:
    """Bollinger Bands plus bandwidth and %B.

    Population standard deviation (``ddof=0``) matches Bollinger's definition;
    pandas defaults to the sample deviation, so it is set explicitly.
    """
    middle = sma(close, period)
    deviation = close.rolling(window=period, min_periods=period).std(ddof=0)
    upper = middle + std_devs * deviation
    lower = middle - std_devs * deviation
    span = (upper - lower).replace(0, np.nan)
    return BollingerResult(
        upper=upper,
        middle=middle,
        lower=lower,
        bandwidth=span / middle,
        percent_b=(close - lower) / span,
    )


def true_range(frame: pd.DataFrame) -> pd.Series:
    """Wilder's True Range."""
    previous_close = frame["close"].shift(1)
    ranges = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1)


def atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range — the volatility input to position sizing."""
    return _wilder_ema(true_range(frame), period)


def obv(frame: pd.DataFrame) -> pd.Series:
    """On-Balance Volume: cumulative volume signed by the daily move."""
    direction = np.sign(frame["close"].diff()).fillna(0.0)
    return (direction * frame["volume"]).cumsum()


@dataclass(slots=True)
class StochasticResult:
    k: pd.Series
    d: pd.Series


def stochastic(
    frame: pd.DataFrame, period: int = 14, smooth_k: int = 3, smooth_d: int = 3
) -> StochasticResult:
    """Stochastic oscillator (slow %K and %D)."""
    lowest = frame["low"].rolling(window=period, min_periods=period).min()
    highest = frame["high"].rolling(window=period, min_periods=period).max()
    span = (highest - lowest).replace(0, np.nan)

    raw_k = 100 * (frame["close"] - lowest) / span
    k = raw_k.rolling(window=smooth_k, min_periods=smooth_k).mean()
    d = k.rolling(window=smooth_d, min_periods=smooth_d).mean()
    return StochasticResult(k=k, d=d)


def vwap(frame: pd.DataFrame, period: int = 20) -> pd.Series:
    """Rolling volume-weighted average price over ``period`` sessions."""
    typical = (frame["high"] + frame["low"] + frame["close"]) / 3
    weighted = (typical * frame["volume"]).rolling(period, min_periods=period).sum()
    volume = frame["volume"].rolling(period, min_periods=period).sum().replace(0, np.nan)
    return weighted / volume


def daily_returns(close: pd.Series) -> pd.Series:
    """Simple daily percentage returns."""
    return close.pct_change()


def annualised_volatility(close: pd.Series, window: int = 21) -> pd.Series:
    """Rolling realised volatility, annualised over 252 trading days."""
    return daily_returns(close).rolling(window, min_periods=window).std() * np.sqrt(252)


def max_drawdown(close: pd.Series) -> float:
    """Worst peak-to-trough decline in the series, as a negative fraction."""
    if close.empty:
        return 0.0
    running_peak = close.cummax()
    drawdown = (close - running_peak) / running_peak
    return float(drawdown.min())


def sharpe_ratio(close: pd.Series, risk_free_rate: float = 0.0) -> float:
    """Annualised Sharpe ratio from daily closes.

    ``risk_free_rate`` is an annual figure and is de-annualised before use.
    """
    returns = daily_returns(close).dropna()
    if len(returns) < 2:
        return 0.0
    excess = returns - risk_free_rate / 252
    deviation = excess.std(ddof=1)
    if deviation == 0 or np.isnan(deviation):
        return 0.0
    return float(excess.mean() / deviation * np.sqrt(252))


#: Indicator sets the API exposes, with the warm-up each one needs.
INDICATOR_WARMUP = {
    "sma20": 20, "sma50": 50, "sma200": 200,
    "ema12": 12, "ema26": 26,
    "rsi14": 15, "macd": 35, "bbands": 20,
    "atr14": 15, "obv": 2, "stochastic": 20, "vwap20": 20,
}


def compute_indicators(frame: pd.DataFrame) -> pd.DataFrame:
    """Compute the full indicator panel for an OHLCV frame.

    Returns a frame on the same index; columns are ``NaN`` wherever the
    indicator has not warmed up yet, which the API converts to ``null`` so the
    chart draws a gap instead of a misleading flat line.
    """
    close = frame["close"]
    macd_result = macd(close)
    bands = bollinger_bands(close)
    stoch = stochastic(frame)

    return pd.DataFrame(
        {
            "sma20": sma(close, 20),
            "sma50": sma(close, 50),
            "sma200": sma(close, 200),
            "ema12": ema(close, 12),
            "ema26": ema(close, 26),
            "rsi14": rsi(close),
            "macd": macd_result.macd,
            "macdSignal": macd_result.signal,
            "macdHistogram": macd_result.histogram,
            "bbUpper": bands.upper,
            "bbMiddle": bands.middle,
            "bbLower": bands.lower,
            "bbPercentB": bands.percent_b,
            "bbBandwidth": bands.bandwidth,
            "atr14": atr(frame),
            "obv": obv(frame),
            "stochK": stoch.k,
            "stochD": stoch.d,
            "vwap20": vwap(frame),
            "volatility21": annualised_volatility(close),
        },
        index=frame.index,
    )
