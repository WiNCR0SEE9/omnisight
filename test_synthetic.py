"""Sanity tests on SYNTHETIC data (no internet needed)."""
import numpy as np
import pandas as pd
from unittest import mock

from indicators import fit_spi_params, spi_series, heat_z, longest_dry_run, BASE_START, BASE_END
from risk_engine import assess_city
import fetch_data

rng = np.random.default_rng(0)
dates = pd.date_range("1991-01-01", "2026-10-10", freq="D")
doy = dates.dayofyear.values
monsoon = (dates.month >= 6) & (dates.month <= 9)
rain = np.where(rng.random(len(dates)) < np.where(monsoon, 0.55, 0.03),
                rng.gamma(1.5, 12, len(dates)), 0.0)
tmax = 30 + 8 * np.sin((doy - 90) / 365 * 2 * np.pi) + rng.normal(0, 1.2, len(dates))
df = pd.DataFrame({"date": dates, "tmax_c": tmax, "rain_mm": rain})

# 1) baseline SPI should look roughly standard normal in monsoon months
rs = df.set_index("date")["rain_mm"]
params = fit_spi_params(rs)
spi = spi_series(rs, params)
base = spi[(spi.index.year >= BASE_START) & (spi.index.year <= BASE_END) & spi.index.month.isin([8, 9])]
print("baseline SPI-3 (Aug/Sep) mean %.2f std %.2f" % (base.mean(), base.std()))
assert abs(base.mean()) < 0.25 and 0.8 < base.std() < 1.2

# 2) normal run
res = assess_city(df, params=params)
print("as_of", res["as_of"], "score", res["score"], res["level"], {k: round(v, 2) for k, v in res["parts"].items()})
assert str(res["as_of"]) == "2026-09-30"          # partial October must be ignored
assert 0 <= res["score"] <= 100

# 3) what-if: less rain + hotter -> higher score
dry_hot = assess_city(df, rain_factor=0.5, temp_add=2.0, params=params)
wet_cool = assess_city(df, rain_factor=1.5, temp_add=0.0, params=params)
print("dry+hot", dry_hot["score"], "| normal", res["score"], "| wetter", wet_cool["score"])
assert dry_hot["score"] > res["score"] >= wet_cool["score"]
assert dry_hot["spi3"] < res["spi3"] < wet_cool["spi3"]

# 4) a drought year inserted in the middle should show strongly negative SPI
df2 = df.copy()
mask = (df2["date"] >= "2009-06-01") & (df2["date"] <= "2009-09-30")
df2.loc[mask, "rain_mm"] *= 0.3
s2 = spi_series(df2.set_index("date")["rain_mm"], params)
print("SPI-3 Sep 2009 with 70%% less rain: %.2f" % s2["2009-09-01"])
assert s2["2009-09-01"] < -1.5

# 5) dry run helper
assert longest_dry_run(pd.Series([5, 0, 0, 0, 3, 0, 0] * 10), days=60) == 3

# 6) fetch_data parsing with a mocked API response
fake = {"daily": {"time": ["2024-06-01", "2024-06-02"],
                  "temperature_2m_max": [38.1, 36.4], "precipitation_sum": [0.0, 12.5]}}
with mock.patch("fetch_data.requests.get") as g:
    g.return_value.json.return_value = fake
    g.return_value.raise_for_status.return_value = None
    out = fetch_data.fetch_city("Indore", 22.72, 75.86, end="2024-06-02")
print(out)
assert list(out.columns) == ["city", "date", "tmax_c", "rain_mm"] and len(out) == 2
print("ALL TESTS PASSED")
