"""Risk score for every year, as of 30 September (end of the monsoon season).

Uses the SAME baseline (1991-2020) and the SAME formula for every year, so the years can be
compared with each other. Output: data/history_scores.csv plus a printed summary.

Run:  python history.py

Note: 1991-2020 is also the baseline period, so scores for those years show how
each year compares with the 1991-2020 normal. They are not a test on unseen data.
"""
import glob
import os
import sys

import pandas as pd

from indicators import fit_spi_params, heat_z, longest_dry_run, spi_from_value
from risk_engine import WEIGHTS, combine

END_MONTH, END_DAY = 9, 30


def history_for_city(df, weights=WEIGHTS):
    city = df["city"].iloc[0]
    rain = df.set_index("date")["rain_mm"]
    tmax = df.set_index("date")["tmax_c"]
    params = fit_spi_params(rain)       # baseline fit once, on 1991-2020
    hz_all = heat_z(tmax)               # baseline taken from the full series, not a cut-off slice
    rows = []
    for year in range(rain.index.min().year, rain.index.max().year + 1):
        end = pd.Timestamp(year, END_MONTH, END_DAY)
        if end > rain.index.max():
            continue
        acc = rain[pd.Timestamp(year, 7, 1):end].sum()      # Jul-Aug-Sep total
        spi3 = spi_from_value(acc, END_MONTH, params)
        hz = float(hz_all.loc[end])
        dry = longest_dry_run(rain[:end])
        res = combine(spi3, hz, dry, weights)
        rows.append({"city": city, "year": year, "jas_rain_mm": round(acc, 1),
                     "spi3": round(spi3, 2), "heat_z": round(hz, 2), "dry_run_days": dry,
                     "score": res["score"], "level": res["level"]})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    folder = sys.argv[1] if len(sys.argv) > 1 else "data"
    files = sorted(glob.glob(os.path.join(folder, "*_daily.csv")))
    if not files:
        sys.exit(f"No *_daily.csv files in '{folder}'.")
    hist = pd.concat([history_for_city(pd.read_csv(p, parse_dates=["date"])) for p in files],
                     ignore_index=True)
    out = os.path.join(folder, "history_scores.csv")
    hist.to_csv(out, index=False)
    print(f"saved {out} ({len(hist)} rows)\n")

    for city, g in hist.groupby("city"):
        print(f"=== {city}: 5 highest-risk years (as of 30 Sep) ===")
        print(g.nlargest(5, "score")[["year", "jas_rain_mm", "spi3", "heat_z", "dry_run_days", "score", "level"]]
              .to_string(index=False), "\n")

    avg = hist.groupby("year")["score"].mean().round(1).sort_values(ascending=False)
    print("=== Years ranked by average score across all cities (top 8) ===")
    print(avg.head(8).to_string())
    print("\nScore range:", hist["score"].min(), "to", hist["score"].max())
    print("Levels:", hist["level"].value_counts().to_dict())
