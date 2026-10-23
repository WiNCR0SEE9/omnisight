# OMNISIGHT

Explainable climate-related water-stress risk indicator for selected Madhya Pradesh cities.
Built for STEAM Innovation League 2.0, Regional Round, 29 Oct 2026. SDGs: 6, 11, 13.

> OMNISIGHT is a decision-support prototype. It is **not** a prediction and **not** an
> official warning. Weather data alone cannot establish actual water scarcity.

## How to run (Windows)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt

python test_synthetic.py     # code sanity check, no internet needed
python fetch_data.py         # downloads 1991-today for 5 cities into data/ (needs internet, run once)
python check_data.py         # checks rows, missing values, baseline SPI
python history.py            # scores every year as of 30 Sep -> data/history_scores.csv (Validation tab)
streamlit run app.py         # opens the dashboard in your browser
```

If PowerShell blocks activation, use Command Prompt: `.venv\Scripts\activate.bat`.

## Files

```
fetch_data.py       downloads daily weather from Open-Meteo, saves data/<city>_daily.csv
check_data.py       sanity checks on the downloaded CSV files
indicators.py       SPI-3 (rain), heat anomaly, dry-spell length
risk_engine.py      combines indicators into a 0-100 score; supports what-if inputs
history.py          score for every year as of 30 Sep -> data/history_scores.csv
sensitivity.py      checks whether the single biggest rain day changes the result
dashboard_logic.py  tables, chart data and report text (no Streamlit, testable on its own)
app.py              Streamlit dashboard: map, city detail, why this score, what-if, evidence report
test_synthetic.py   tests on synthetic data (code correctness only, not real accuracy)
data/               downloaded CSV files (real reanalysis data) and history_scores.csv
```

## Data

- Source: Open-Meteo Historical Weather API (ERA5-based reanalysis, gridded estimate, not a ground station).
- Variables: daily maximum temperature and daily precipitation sum, 1991 to latest available.
- Attribution: weather data by [Open-Meteo.com](https://open-meteo.com/) (CC BY 4.0).
- The app reads the saved CSV files, so it works without internet.

## Method

1. **Rain deficit:** SPI-3 (3-month Standardized Precipitation Index) against a 1991-2020 baseline.
2. **Heat:** last-30-day mean maximum temperature vs the same days in 1991-2020 (in standard deviations).
3. **Dry spell:** longest run of days with under 1 mm rain in the last 60 days.
4. **Score:** 100 x (0.50 x rain + 0.25 x heat + 0.25 x dry), levels at 25 / 50 / 75.

Weights and level cut-offs are **design assumptions**, not scientifically calibrated values.

## Validation

**Status: limited validation. This is a sanity check, not a test on unseen data.**

We scored every year (1991-2025, plus 2026 so far) as of 30 September with `history.py`.

- Four monsoons are documented as deficient across India: 2002 (19% below the long-period average, LPA),
  2009 (22% below), 2014 (88% of LPA) and 2015 (86% of LPA).
  Sources: ORF (2002, 2009); IMD "Southwest Monsoon 2015" report (2014, 2015).
- Ranked by the average score of our five cities, 2002 is 3rd, 2015 is 5th and 2009 is 6th of 36 years.
  2014 is outside the top 8.
- Years 2000, 2001 and 2004 also rank high. We could not verify them against a source.
- District check for 2015 against IMD figures quoted by SANDRP (`check_2015.py`): ERA5 Jun-Sep as % of the
  1991-2020 average vs IMD actual as % of IMD normal: Gwalior 53 vs 82, Jabalpur 81 vs 75, Bhopal 111 vs 100
  (same direction); Indore 75 vs 142 and Ujjain 84 vs 169 (opposite direction). The same article reports large gaps
  between IMD and the MP Agriculture Department, so we cannot tell which source is right.
- Sensitivity to outliers (`sensitivity.py`): capping each city's largest daily rainfall changed SPI-3 by at most
  0.03 and the score by at most 0.1.
- Window choice (`compare_windows.py`): SPI-3 (Jul-Sep) and SPI-4 (Jun-Sep) rank the years alike
  (Spearman 0.88 to 0.96 by city), so we kept the simpler SPI-3.

All-India figures do not map exactly onto single cities, and 1991-2020 is both the baseline and the scoring
period. We make no accuracy claim.

## Limitations

- Reanalysis data is a model-based gridded estimate, not a measurement at a local station.
- Version 1 uses only rainfall and temperature. Groundwater, reservoir and demand data are not included.
- Weights (50/25/25) and level cut-offs (25/50/75) are design assumptions, not calibrated values.
- SPI-3 covers the last three months, so an earlier deficit (for example in June) can be missed.
- ERA5 contains a few very large daily values (for example Indore on 26 June 1997). We tested the effect on the
  current result and found it negligible, but we could not verify the event against a source.
- Validation is limited (see above).
- What-if results are hypothetical scenarios, not forecasts.
- OMNISIGHT is not a forecast and not an official warning.

## Tested with

Python on Windows with streamlit 1.66.0, pandas 3.0.6, numpy 2.5.4, scipy 1.18.1, plotly 7.1.0,
folium 0.20.0, streamlit-folium 0.27.4 and requests 2.34.2. The saved CSV files in `data/` let the dashboard run
without internet (only the map background needs it; an offline view is included).

## Team

Mr. Sameer Mansuri 

Miss Jamila Panbiharwala
Mr. Zaki Ajmeri
Mr. Sparsh Parmar 
