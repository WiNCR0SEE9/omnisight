"""Features and target for the OMNISIGHT 2.0 machine-learning model.

QUESTION THE MODEL ANSWERS
    At the end of a month (April to September), will NEXT month be a "dry" month?
    "Dry" = next month's rainfall is in the lowest third (tercile) of that calendar month's rainfall
    in the training years 1991-2015, for that city.

WHY THIS TARGET
    * Labels come straight from the same weather data, so nothing is invented.
    * It is a real forecasting question: features use only the past, the label is in the future.
    * It does NOT claim to predict groundwater, crop yield or an official drought.

HOW LEAKAGE IS PREVENTED
    * Everything that defines "normal" (monthly mean/std, daily temperature mean/std, the dry
      thresholds) is computed from TRAINING YEARS ONLY (<= TRAIN_END_YEAR).
    * Every feature at an origin date uses data up to that date and nothing later.
      test_ml.py checks this by changing the future and confirming the features do not move.
    * Train/test split is by time: origins up to 2015 train, 2016 onwards test.
"""
import numpy as np
import pandas as pd

import dashboard_logic as dl

TRAIN_END_YEAR = 2015
ORIGIN_MONTHS = (4, 5, 6, 7, 8, 9)  # forecast made at the end of these months, for the next month
DRY_QUANTILE = 1 / 3
FEATURES = ["rain_1m_z", "rain_3m_z", "rain_6m_z", "tmax_30d_z", "dry_run_60", "month_sin", "month_cos"]

FEATURE_MEANING = {
    "rain_1m_z": "Last month's rain vs normal (std devs)",
    "rain_3m_z": "Last 3 months' rain vs normal (std devs)",
    "rain_6m_z": "Last 6 months' rain vs normal (std devs)",
    "tmax_30d_z": "Last 30 days' max temperature vs normal (std devs)",
    "dry_run_60": "Longest dry spell in last 60 days (days)",
    "month_sin": "Time of year (sin)",
    "month_cos": "Time of year (cos)",
}


def _monthly_totals(rain):
    """Monthly rain totals; months with missing days become NaN."""
    g = rain.resample("MS").agg(["sum", "count"])
    out = g["sum"].astype(float)
    out[g["count"] < g.index.days_in_month] = np.nan
    return out


def _z_by_calendar_month(series, train_end_year):
    """z-score of each value against the mean/std of the same calendar month in TRAINING years."""
    train = series[series.index.year <= train_end_year]
    mean = train.groupby(train.index.month).mean()
    std = train.groupby(train.index.month).std().replace(0, np.nan)
    m = series.index.month
    return (series - mean.reindex(m).values) / std.reindex(m).values


def _tmax_z(tmax, train_end_year, window=30):
    """30-day mean max temperature vs the same day of year in TRAINING years (in std devs)."""
    roll = tmax.rolling(window).mean()
    train = roll[(roll.index.year <= train_end_year)].dropna()
    g = train.groupby(train.index.dayofyear)
    mean, std = g.mean(), g.std().replace(0, np.nan)
    doy = roll.index.dayofyear
    return (roll - mean.reindex(doy).values) / std.reindex(doy).values


def _longest_dry_run(window_values, threshold_mm=1.0):
    best = cur = 0
    for v in window_values:
        cur = cur + 1 if v < threshold_mm else 0
        best = max(best, cur)
    return best


def build_city_frame(df, city, train_end_year=TRAIN_END_YEAR):
    """One row per forecast origin (end of April..September). The target is NaN if next month is incomplete."""
    rain = df.set_index("date")["rain_mm"].astype(float)
    tmax = df.set_index("date")["tmax_c"].astype(float)

    monthly = _monthly_totals(rain)
    acc3 = monthly.rolling(3).sum()
    acc6 = monthly.rolling(6).sum()
    z1 = _z_by_calendar_month(monthly, train_end_year)
    z3 = _z_by_calendar_month(acc3, train_end_year)
    z6 = _z_by_calendar_month(acc6, train_end_year)
    tz = _tmax_z(tmax, train_end_year)

    train_monthly = monthly[monthly.index.year <= train_end_year]
    dry_thr = train_monthly.groupby(train_monthly.index.month).quantile(DRY_QUANTILE)

    rows = []
    for start in monthly.index:
        if start.month not in ORIGIN_MONTHS:
            continue
        origin = start + pd.offsets.MonthEnd(0)
        if origin > rain.index.max() or np.isnan(monthly[start]):
            continue
        nxt = start + pd.offsets.MonthBegin(1)
        rain_next = monthly.get(nxt, np.nan)
        win = rain.loc[:origin].iloc[-60:]
        ang = 2 * np.pi * start.month / 12
        rows.append({
            "city": city, "origin": origin, "year": origin.year, "month": origin.month,
            "rain_1m_z": z1[start], "rain_3m_z": z3[start], "rain_6m_z": z6[start],
            "tmax_30d_z": tz.get(origin, np.nan),
            "dry_run_60": _longest_dry_run(win.values),
            "month_sin": np.sin(ang), "month_cos": np.cos(ang),
            "rain_now_mm": monthly[start], "rain_next_mm": rain_next,
            "persist_dry": float(monthly[start] < dry_thr[start.month]),
            "y": (float(rain_next < dry_thr[nxt.month]) if not np.isnan(rain_next) else np.nan),
        })
    out = pd.DataFrame(rows)
    out["split"] = np.where(out["year"] <= train_end_year, "train", "test")
    return out


def build_dataset(data_dir, train_end_year=TRAIN_END_YEAR):
    """All cities together. Rows with a missing feature or an unknown target are dropped."""
    data = dl.load_cities(data_dir)
    frames = [build_city_frame(df, city, train_end_year) for city, df in data.items()]
    ds = pd.concat(frames, ignore_index=True)
    ds = ds.dropna(subset=FEATURES + ["y"]).reset_index(drop=True)
    ds["y"] = ds["y"].astype(int)
    return ds
