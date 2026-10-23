"""Does it matter if the rain indicator covers 3 months (Jul-Sep) or the full 4-month monsoon (Jun-Sep)?

For every city and year (as of 30 September) this compares:
  SPI-3 = rain of Jul-Aug-Sep        (what the app uses)
  SPI-4 = rain of Jun-Jul-Aug-Sep    (the official IMD monsoon season)
It prints how similarly the two rank the years and which years they disagree on.

Run:  python compare_windows.py
"""
import glob
import os
import sys

import pandas as pd

from indicators import fit_spi_params, spi_from_value

folder = sys.argv[1] if len(sys.argv) > 1 else "data"
files = sorted(glob.glob(os.path.join(folder, "*_daily.csv")))
if not files:
    sys.exit(f"No *_daily.csv files in '{folder}'.")

all_rows = []
for path in files:
    df = pd.read_csv(path, parse_dates=["date"])
    city = df["city"].iloc[0]
    rain = df.set_index("date")["rain_mm"]
    p3, p4 = fit_spi_params(rain, window=3), fit_spi_params(rain, window=4)
    for year in range(rain.index.min().year, rain.index.max().year + 1):
        end = pd.Timestamp(year, 9, 30)
        if end > rain.index.max():
            continue
        spi3 = spi_from_value(rain[pd.Timestamp(year, 7, 1):end].sum(), 9, p3)
        spi4 = spi_from_value(rain[pd.Timestamp(year, 6, 1):end].sum(), 9, p4)
        all_rows.append({"city": city, "year": year, "spi3": round(spi3, 2), "spi4": round(spi4, 2)})
res = pd.DataFrame(all_rows)
res["diff"] = (res["spi4"] - res["spi3"]).round(2)

print("Rank agreement between SPI-3 and SPI-4 across years (Spearman, 1.0 = identical ranking):")
corr = res.groupby("city").apply(lambda g: g["spi3"].corr(g["spi4"], method="spearman"), include_groups=False)
print(corr.round(2).to_string())

print("\nYears where the two disagree by 0.75 SPI or more (biggest first):")
big = res[res["diff"].abs() >= 0.75].sort_values("diff", key=abs, ascending=False)
print(big.head(15).to_string(index=False) if len(big) else "none")

print("\n5 driest years by SPI-3 vs by SPI-4 (all cities averaged):")
avg = res.groupby("year")[["spi3", "spi4"]].mean().round(2)
print("SPI-3:", list(avg["spi3"].nsmallest(5).index))
print("SPI-4:", list(avg["spi4"].nsmallest(5).index))
print("\nRule of thumb: if every city is about 0.9 or higher and the driest years are mostly the same, "
      "SPI-3 is fine. Keep it and describe the difference in the limitations.")
