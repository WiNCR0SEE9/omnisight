"""Does the single biggest rainfall day change the current result?

For each city: cap the largest daily rainfall at the second-largest value,
re-fit the baseline, and compare the latest SPI-3 and risk score.
Run:  python sensitivity.py
"""
import glob
import sys

import pandas as pd

from risk_engine import assess_city

folder = sys.argv[1] if len(sys.argv) > 1 else "data"
files = sorted(glob.glob(f"{folder}/*_daily.csv"))
if not files:
    sys.exit(f"No *_daily.csv files in '{folder}'.")

print(f"{'city':9} {'top day':11} {'mm':>6} -> {'cap':>6} | {'SPI3':>6} {'SPI3 capped':>11} | {'score':>5} {'capped':>6}")
for path in files:
    df = pd.read_csv(path, parse_dates=["date"])
    top = df.nlargest(2, "rain_mm")
    cap = top["rain_mm"].iloc[1]
    capped = df.copy()
    capped.loc[capped["rain_mm"] > cap, "rain_mm"] = cap
    a, b = assess_city(df), assess_city(capped)
    print(f"{df['city'].iloc[0]:9} {top['date'].iloc[0].date()} {top['rain_mm'].iloc[0]:6.1f} -> {cap:6.1f} | "
          f"{a['spi3']:6.2f} {b['spi3']:11.2f} | {a['score']:5.1f} {b['score']:6.1f}")
print("\nAs-of month:", a["as_of"])
