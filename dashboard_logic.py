"""Dashboard logic with NO Streamlit/plotly/folium imports, so it can be tested on its own."""
import glob
import os

import pandas as pd

from indicators import BASE_END, BASE_START, spi_series

FACTOR_LABELS = {
    "rain": "Rain deficit (SPI-3)",
    "heat": "Heat anomaly (last 30 days)",
    "dry": "Dry spell (last 60 days)",
}

LEVEL_TEXT = {
    "Low": "The indicators are close to, or better than, the 1991-2020 normal.",
    "Moderate": "Some indicators are worse than the 1991-2020 normal.",
    "High": "Several indicators are clearly worse than the 1991-2020 normal.",
    "Very high": "Most indicators are strongly worse than the 1991-2020 normal.",
}


def load_cities(data_dir):
    """Return {city name: DataFrame(date, tmax_c, rain_mm)} from data/*_daily.csv."""
    out = {}
    for path in sorted(glob.glob(os.path.join(data_dir, "*_daily.csv"))):
        df = pd.read_csv(path, parse_dates=["date"]).sort_values("date").reset_index(drop=True)
        out[df["city"].iloc[0]] = df
    return out


def spi_label(x):
    if x >= 2.0:
        return "extremely wet"
    if x >= 1.5:
        return "very wet"
    if x >= 1.0:
        return "moderately wet"
    if x > -1.0:
        return "near normal"
    if x > -1.5:
        return "moderately dry"
    if x > -2.0:
        return "very dry"
    return "extremely dry"


def heat_label(z):
    if z >= 2.0:
        return "far hotter than normal"
    if z >= 1.0:
        return "hotter than normal"
    if z > -1.0:
        return "near normal"
    return "cooler than normal"


def contributions(res, weights):
    """Points (out of 100) that each factor adds to the score."""
    return {k: round(100 * weights[k] * res["parts"][k], 1) for k in res["parts"]}


def score_table(results, coords):
    """results: {city: assess_city output}. Returns a DataFrame sorted by score (highest first)."""
    rows = []
    for city, r in results.items():
        lat, lon = coords[city]
        rows.append({
            "City": city, "Score": r["score"], "Level": r["level"],
            "SPI-3": round(r["spi3"], 2), "Heat (sd)": round(r["heat_z"], 2),
            "Dry days": r["dry_run_days"], "Latitude": lat, "Longitude": lon,
        })
    return pd.DataFrame(rows).sort_values("Score", ascending=False).reset_index(drop=True)


def monthly_vs_normal(df, as_of, n=12):
    """Last n complete months of rain vs the 1991-2020 average for the same calendar month."""
    rain = df.set_index("date")["rain_mm"]
    monthly = rain.resample("MS").sum()
    monthly = monthly[monthly.index <= pd.Timestamp(as_of)]
    base = monthly[(monthly.index.year >= BASE_START) & (monthly.index.year <= BASE_END)]
    normal = base.groupby(base.index.month).mean()
    last = monthly.iloc[-n:]
    return pd.DataFrame({
        "month": last.index.strftime("%b %Y"),
        "actual_mm": last.values.round(1),
        "normal_mm": [round(float(normal[m]), 1) for m in last.index.month],
    })


def recent_spi(df, params, as_of, from_year=2010):
    rain = df.set_index("date")["rain_mm"][:pd.Timestamp(as_of)]
    s = spi_series(rain, params)
    return s[s.index.year >= from_year]


def recent_days(df, n=45):
    """The newest n days in the saved data."""
    return df.tail(n).reset_index(drop=True)


def summarize_update(results):
    """One plain sentence about what update_all() did."""
    errs = [r for r in results if r["status"] == "error"]
    if results and len(errs) == len(results):
        return ("Could not reach Open-Meteo (are you offline?). The saved data is unchanged. "
                "First error: " + errs[0]["error"])
    added = sum(r.get("added", 0) for r in results)
    last = max(r["last_date"] for r in results if "last_date" in r)
    msg = f"Added {added} new day(s) across the cities. The data now runs through {last}."
    if errs:
        msg += f" Failed for: {', '.join(r['city'] for r in errs)}."
    return msg


def top_history(hist, city, n=5):
    g = hist[hist["city"] == city].nlargest(n, "score")
    return g[["year", "jas_rain_mm", "spi3", "heat_z", "dry_run_days", "score", "level"]].reset_index(drop=True)


# All-India deficient monsoons, from sources we could read:
#   2002 and 2009: ORF article (19% and 22% below the long-period average)
#   2014 and 2015: IMD "Southwest Monsoon 2015" report (88% and 86% of the long-period average)
# These are national figures. They do not map exactly onto single cities.
DEFICIENT_YEARS = {
    2002: "19% below LPA",
    2009: "22% below LPA",
    2014: "88% of LPA",
    2015: "86% of LPA",
}


def yearly_average(hist):
    """Average score across cities for every year, with its rank (1 = highest risk)."""
    g = hist.groupby("year")["score"].mean().round(1).reset_index(name="avg_score")
    g["rank"] = g["avg_score"].rank(ascending=False, method="min").astype(int)
    g["Year type"] = g["year"].map(lambda y: "Documented all-India deficient monsoon"
                                   if y in DEFICIENT_YEARS else "Other years")
    return g


def validation_table(hist):
    y = yearly_average(hist).set_index("year")
    n = len(y)
    rows = []
    for year, note in DEFICIENT_YEARS.items():
        if year in y.index:
            r = int(y.loc[year, "rank"])
            rows.append({"Year": year, "All-India monsoon": note,
                         "Our average score": y.loc[year, "avg_score"],
                         "Our rank": f"{r} of {n}", "In our top 6?": "Yes" if r <= 6 else "No"})
    return pd.DataFrame(rows)


def _md_table(df):
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(str(row[c]) for c in cols) + " |")
    return "\n".join(lines)


def report_text(city, res, weights, top_years=None):
    pts = contributions(res, weights)
    lines = [
        f"# OMNISIGHT evidence report: {city}", "",
        f"**Data as of:** {res['as_of']} (last complete month). "
        f"**Risk score:** {res['score']:.1f} / 100 ({res['level']}).", "",
        "## Key indicators",
        f"- **Rain:** 3-month SPI = {res['spi3']:.2f} ({spi_label(res['spi3'])} compared with 1991-2020).",
        f"- **Heat:** the last-30-day mean maximum temperature is {res['heat_z']:+.2f} standard deviations "
        f"from the 1991-2020 normal for the same days ({heat_label(res['heat_z'])}).",
        f"- **Dry spell:** the longest run of days with under 1 mm of rain in the last 60 days is "
        f"{res['dry_run_days']} days.", "",
        "## How the score was built",
        f"- Rain deficit adds {pts['rain']} points (weight {weights['rain']:.0%}).",
        f"- Heat anomaly adds {pts['heat']} points (weight {weights['heat']:.0%}).",
        f"- Dry spell adds {pts['dry']} points (weight {weights['dry']:.0%}).",
        "- The weights and the level cut-offs (25 / 50 / 75) are design assumptions, "
        "not scientifically calibrated values.", "",
        "## What this means", LEVEL_TEXT[res["level"]], "",
        "## What this does not mean",
        "- It is not a forecast and not an official warning.",
        "- Weather data alone cannot establish actual water scarcity.", "",
        "## Missing information",
        "- Groundwater levels", "- Reservoir and lake storage", "- Soil moisture",
        "- Water demand and supply infrastructure", "- Local rain-gauge records", "",
        "## Suggested checks",
        "- Compare with local rain-gauge or IMD district rainfall for the same months.",
        "- Look at reservoir or lake level bulletins for the area.",
        "- Check local groundwater reports.",
        "- Check the weather forecast before drawing conclusions.", "",
        "## Data and method",
        "- Daily maximum temperature and rainfall from the Open-Meteo Historical Weather API "
        "(ERA5 reanalysis, a gridded model estimate, not a station measurement). "
        "Weather data by Open-Meteo.com, CC BY 4.0.",
        f"- Baseline period {BASE_START}-{BASE_END}. Rain is measured with the 3-month "
        "Standardized Precipitation Index (SPI).",
    ]
    if top_years is not None and len(top_years):
        pretty = top_years.rename(columns={
            "year": "Year", "jas_rain_mm": "Jul-Sep rain (mm)", "spi3": "SPI-3", "heat_z": "Heat (std dev)",
            "dry_run_days": "Longest dry spell (days)", "score": "Score", "level": "Level"})
        lines += ["", "## Highest-risk years since 1991 (same method, as of 30 September)",
                  _md_table(pretty), "",
                  "These years use the same 1991-2020 baseline that defines normal, so this is a sanity "
                  "check against documented dry years, not a test on unseen data."]
    return "\n".join(lines)
