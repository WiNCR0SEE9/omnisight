"""Add the newest days to the saved CSV files, so the data is not frozen.

Run:  python update_data.py        (needs internet)
The 'Update data' button in the dashboard calls the same code.

How it works, per city:
  1. read the saved CSV and find its last date
  2. ask Open-Meteo only for the days from 10 days before that date up to 7 days ago
     (the newest few days are not available yet; the last days before that can still be revised,
     which is why we re-download a 10-day overlap)
  3. merge: newer values replace older ones for the same date, days we already had are kept
  4. save the CSV again
If there is no internet the saved data stays exactly as it was.
"""
import os
import time
from datetime import date, timedelta

import pandas as pd

from fetch_data import CITIES, fetch_city

OVERLAP_DAYS = 10
LAG_DAYS = 7  # newest days are not available yet


def update_city_file(name, lat, lon, path, today=None, fetcher=fetch_city):
    today = today or date.today()
    end = pd.Timestamp(today - timedelta(days=LAG_DAYS))

    if not os.path.exists(path):  # nothing saved yet: full download
        df = fetcher(name, lat, lon)
        df = df.dropna(subset=["tmax_c", "rain_mm"])
        df.to_csv(path, index=False)
        return {"city": name, "status": "downloaded", "added": len(df),
                "last_date": str(df["date"].max().date())}

    old = pd.read_csv(path, parse_dates=["date"])
    last = old["date"].max()
    if last >= end:
        return {"city": name, "status": "up to date", "added": 0, "last_date": str(last.date())}

    start = last - pd.Timedelta(days=OVERLAP_DAYS - 1)
    new = fetcher(name, lat, lon, start=str(start.date()), end=str(end.date()))
    ok = new.dropna(subset=["tmax_c", "rain_mm"])  # skip days whose values are not available yet
    if ok.empty:
        return {"city": name, "status": "no newer data yet", "added": 0, "last_date": str(last.date())}

    merged = (pd.concat([old, ok]).drop_duplicates("date", keep="last")
              .sort_values("date").reset_index(drop=True))
    merged.to_csv(path, index=False)
    return {"city": name, "status": "updated", "added": len(merged) - len(old),
            "last_date": str(merged["date"].max().date())}


def update_all(data_dir="data", cities=CITIES, today=None, fetcher=fetch_city, pause=2.0):
    os.makedirs(data_dir, exist_ok=True)
    results = []
    for i, (name, (lat, lon)) in enumerate(cities.items()):
        if i:
            time.sleep(pause)
        path = os.path.join(data_dir, f"{name.lower()}_daily.csv")
        try:
            results.append(update_city_file(name, lat, lon, path, today=today, fetcher=fetcher))
        except Exception as e:  # offline, rate limit, bad response...
            results.append({"city": name, "status": "error", "error": str(e)[:120]})
    return results


if __name__ == "__main__":
    for r in update_all("data"):
        print(r)
