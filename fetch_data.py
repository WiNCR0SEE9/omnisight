import os
import sys
import time
from datetime import date, timedelta

import pandas as pd
import requests

# Approximate city-centre coordinates (latitude, longitude). Double-check them on a map.
CITIES = {
    "Indore": (22.72, 75.86),
    "Bhopal": (23.26, 77.41),
    "Gwalior": (26.22, 78.18),
    "Jabalpur": (23.18, 79.99),
    "Ujjain": (23.18, 75.78),
}
URL = "https://archive-api.open-meteo.com/v1/archive"
MAX_TRIES = 5
PAUSE_BETWEEN_CITIES_S = 10


def fetch_city(name, lat, lon, start="1991-01-01", end=None):
    if end is None:
        end = (date.today() - timedelta(days=7)).isoformat()  # latest days may not be available yet
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start,
        "end_date": end,
        "daily": "temperature_2m_max,precipitation_sum",
        "timezone": "auto",
    }
    for attempt in range(1, MAX_TRIES + 1):
        r = requests.get(URL, params=params, timeout=60)
        if r.status_code == 429:  # too many requests: wait and try again
            try:
                wait = int(r.headers.get("Retry-After", ""))
            except ValueError:
                wait = 60 * attempt
            print(f"  {name}: rate limited (429). Waiting {wait}s, attempt {attempt}/{MAX_TRIES}...")
            time.sleep(wait)
            continue
        r.raise_for_status()
        d = r.json()["daily"]
        df = pd.DataFrame({
            "date": pd.to_datetime(d["time"]),
            "tmax_c": d["temperature_2m_max"],
            "rain_mm": d["precipitation_sum"],
        })
        df.insert(0, "city", name)
        return df
    raise RuntimeError(f"{name}: still rate limited after {MAX_TRIES} tries. Wait a few minutes and run again.")


if __name__ == "__main__":
    force = "--force" in sys.argv
    os.makedirs("data", exist_ok=True)
    first_download = True
    for name, (lat, lon) in CITIES.items():
        path = f"data/{name.lower()}_daily.csv"
        if os.path.exists(path) and not force:
            print(f"{name}: {path} already exists, skipping (use --force to download again)")
            continue
        if not first_download:
            time.sleep(PAUSE_BETWEEN_CITIES_S)
        first_download = False
        df = fetch_city(name, lat, lon)
        df.to_csv(path, index=False)
        print(name, len(df), "rows, missing values:", int(df.isna().sum().sum()))