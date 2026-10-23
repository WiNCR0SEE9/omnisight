"""Day 1-2 sanity check for the downloaded CSV files in data/.

Run:  python check_data.py
Prints, for each city: rows, date range, missing values, average yearly rain,
and a baseline SPI check (mean should be near 0, std near 1 for monsoon months).
Pass a different folder as the first argument if needed.
"""
import glob
import os
import sys

import pandas as pd

from indicators import BASE_END, BASE_START, fit_spi_params, spi_series

folder = sys.argv[1] if len(sys.argv) > 1 else "data"
files = sorted(glob.glob(os.path.join(folder, "*_daily.csv")))
if not files:
    sys.exit(f"No *_daily.csv files found in '{folder}'. Run fetch_data.py first.")

for path in files:
    df = pd.read_csv(path, parse_dates=["date"])
    city = df["city"].iloc[0]
    n_missing_rain = int(df["rain_mm"].isna().sum())
    n_missing_temp = int(df["tmax_c"].isna().sum())
    print(f"\n=== {city} ({os.path.basename(path)}) ===")
    print(f"rows: {len(df)} | {df['date'].min().date()} to {df['date'].max().date()}")
    print(f"missing rain: {n_missing_rain} | missing tmax: {n_missing_temp}")
    print(f"duplicate dates: {int(df['date'].duplicated().sum())}")
    print(f"max rain in a day: {df['rain_mm'].max():.1f} mm | max tmax: {df['tmax_c'].max():.1f} C")

    yearly = df.groupby(df["date"].dt.year)["rain_mm"].sum()
    full = yearly[yearly.index.isin(range(BASE_START, BASE_END + 1))]
    print(f"avg yearly rain {BASE_START}-{BASE_END}: {full.mean():.0f} mm")

    if n_missing_rain or n_missing_temp:
        print("WARNING: missing values found. Fix or document them before scoring.")
        continue
    rs = df.set_index("date")["rain_mm"]
    spi = spi_series(rs, fit_spi_params(rs))
    base = spi[(spi.index.year >= BASE_START) & (spi.index.year <= BASE_END)
               & spi.index.month.isin([8, 9])]
    print(f"baseline SPI-3 (Aug/Sep): mean {base.mean():.2f}, std {base.std():.2f} "
          "(expect about 0 and 1)")
