"""Compare our ERA5 monsoon rain for 2015 with the IMD district figures quoted by SANDRP.

IMD numbers (mm, 1 June to 30 Sept 2015, actual and normal) are copied by hand from the table in
https://sandrp.in/2015/10/28/imd-mp-govt-provide-shockingly-different-district-rainfall-figures-will-they-explain-please/
Check them against the article before you quote them. IMD's "normal" is IMD's own long-period
average, not our 1991-2020 average, so compare the PERCENT of normal, not the raw millimetres.

Run:  python check_2015.py
"""
import glob
import os
import sys

import pandas as pd

# city: (IMD actual mm, IMD normal mm) for 1 Jun - 30 Sep 2015
IMD_2015 = {
    "Indore": (1193.2, 839.7),
    "Bhopal": (998.4, 998.6),
    "Gwalior": (645.4, 790.6),
    "Jabalpur": (822.2, 1090.3),
    "Ujjain": (1405.2, 833.7),
}
YEAR = 2015
BASE = (1991, 2020)

folder = sys.argv[1] if len(sys.argv) > 1 else "data"
rows = []
for path in sorted(glob.glob(os.path.join(folder, "*_daily.csv"))):
    df = pd.read_csv(path, parse_dates=["date"])
    city = df["city"].iloc[0]
    rain = df.set_index("date")["rain_mm"]
    season = rain[rain.index.month.isin([6, 7, 8, 9])]
    totals = season.groupby(season.index.year).sum()
    era_year = totals[YEAR]
    era_norm = totals[(totals.index >= BASE[0]) & (totals.index <= BASE[1])].mean()
    row = {"city": city, "ERA5 Jun-Sep": round(era_year), "ERA5 1991-2020 avg": round(era_norm),
           "ERA5 % of avg": round(100 * era_year / era_norm)}
    if city in IMD_2015:
        act, norm = IMD_2015[city]
        row.update({"IMD actual": act, "IMD normal": norm, "IMD % of normal": round(100 * act / norm)})
    rows.append(row)

out = pd.DataFrame(rows)
print(f"Monsoon (Jun-Sep) {YEAR}: ERA5 (our data) vs IMD district figures\n")
print(out.to_string(index=False))
print("\nHow to read it: the two '% of normal' columns should point the same way "
      "(both below 100 = dry, both above 100 = wet). Exact numbers will differ because ERA5 is a gridded "
      "model estimate and IMD uses district stations and its own normal.")
