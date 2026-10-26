import numpy as np
import pandas as pd
from scipy import stats
BASE_START, BASE_END = 1991, 2020  # baseline ("normal") period

def last_complete_month_end(index):
    last = index.max()
    if last == last + pd.offsets.MonthEnd(0):
        return last
    return last.replace(day=1) - pd.Timedelta(days=1)

def monthly_accumulated(rain_daily, window=3):
    """Monthly rainfall totals (complete months only), summed over a rolling window of months."""
    m = rain_daily.resample("MS").agg(["sum", "count"])
    m = m[m["count"] == m.index.days_in_month]["sum"]
    return m.rolling(window).sum()

def fit_spi_params(rain_daily, window=3):
    """Fit a gamma distribution for each calendar month on the 1991-2020 baseline."""
    acc = monthly_accumulated(rain_daily, window).dropna()
    base = acc[(acc.index.year >= BASE_START) & (acc.index.year <= BASE_END)]
    params = {}
    for month in range(1, 13):
        vals = base[base.index.month == month]
        nonzero = vals[vals > 0.01]
        if len(nonzero) < 10:
            continue  # dry-season months: too few non-zero values to fit
        p0 = 1 - len(nonzero) / len(vals)
        a, _, scale = stats.gamma.fit(nonzero, floc=0)
        params[month] = (a, scale, p0)
    return params

def spi_from_value(acc_mm, month, params):
    """Turn an accumulated rainfall total (mm) for a calendar month into an SPI value."""
    if month not in params:
        raise ValueError(f"No SPI fit for month {month} (too dry / too little data)")
    a, scale, p0 = params[month]
    if acc_mm <= 0.01:
        cdf = p0
    else:
        cdf = p0 + (1 - p0) * stats.gamma.cdf(acc_mm, a, scale=scale)
    cdf = min(max(cdf, 0.001), 0.999)
    return float(stats.norm.ppf(cdf))

def spi_series(rain_daily, params, window=3):
    acc = monthly_accumulated(rain_daily, window).dropna()
    acc = acc[[ts.month in params for ts in acc.index]]
    vals = [spi_from_value(v, ts.month, params) for ts, v in acc.items()]
    return pd.Series(vals, index=acc.index, name="spi3")

def heat_z(tmax_daily, window=30):
    """How unusual is the last-30-day mean maximum temperature vs the same days in 1991-2020?"""
    roll = tmax_daily.rolling(window).mean().dropna()
    base = roll[(roll.index.year >= BASE_START) & (roll.index.year <= BASE_END)]
    g = base.groupby(base.index.dayofyear)
    mean, std = g.mean(), g.std()
    doy = roll.index.dayofyear
    return (roll - mean.reindex(doy).values) / std.reindex(doy).values

def longest_dry_run(rain_daily, days=60, threshold_mm=1.0):
    """Longest streak of consecutive days with less than 1 mm rain in the last 60 days."""
    best = cur = 0
    for is_dry in (rain_daily.iloc[-days:] < threshold_mm):
        cur = cur + 1 if is_dry else 0
        best = max(best, cur)
    return best