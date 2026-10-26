# OMNISIGHT

Explainable water-stress and rainfall-risk indicator for five Madhya Pradesh cities (Indore, Bhopal, Gwalior,
Jabalpur, Ujjain). Built for STEAM Innovation League 2.0, Regional Round, 29 Oct 2026. SDGs 6, 11 and 13.

> OMNISIGHT is a decision-support prototype. It is **not** an official warning. The risk score describes the last
> three months; it is not a forecast. Weather data alone cannot establish actual water scarcity.

## What it does

1. **Risk score (0 to 100)** for each city: how unusual the last 3 months of rain, the last 30 days of heat and the
   longest dry spell are, compared with the 1991-2020 normal. Every score shows the points each indicator added.
2. **Next-month model (machine learning):** a trained model estimates whether next month's rain will fall in the
   driest third of years for that month. It is evaluated on years it never saw, and the result is shown openly.
3. **Unusual months:** every month since 1991 is compared with its own seasonal normal by two detectors
   (a statistical test and an Isolation Forest). Each flag lists the evidence behind it.
4. **Scenario lab:** change the recent rain and temperature and watch the score respond. Scenarios are labelled as
   hypothetical and kept apart from observed data and model output.
5. **Evidence report:** a downloadable Markdown report per city.
6. **Update data:** a button (and `update_data.py`) that adds the newest days from Open-Meteo.

## Main app and backup

| | Command | Use |
|---|---|---|
| **Main: website** | `python server.py` then open http://127.0.0.1:8000 | Demo and judging. All features above. |
| Backup: first dashboard | `streamlit run app.py` | Older version (risk score, what-if, report, validation, map). No ML model or anomalies. |

## How to run (Windows)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt

python fetch_data.py       # downloads 1991-today for 5 cities into data/ (needs internet, run once)
python check_data.py       # checks rows, missing values, baseline SPI
python history.py          # scores every year as of 30 Sep -> data/history_scores.csv (validation section)
python ml_train.py         # trains and compares the models, saves models/ (about 1 minute)
python server.py           # starts the website at http://127.0.0.1:8000
```

If PowerShell blocks activation, use Command Prompt: `.venv\Scripts\activate.bat`.
The saved `data/` and `models/` folders are enough to run the website without internet.

**Tests (no internet needed, synthetic data):**
```powershell
python test_synthetic.py   # indicators and risk engine
python test_ml.py          # no look-ahead leakage in the ML features
python test_anomaly.py     # anomaly detector finds planted anomalies
python test_server.py      # every endpoint, input validation and errors
```

## Files

```
server.py            website + JSON API (python standard library only)
web/                 index.html, style.css, app.js: the website (no external libraries)
fetch_data.py        one-time download from Open-Meteo into data/<city>_daily.csv
update_data.py       adds the newest days to the saved files (used by the Update data button)
indicators.py        SPI-3 (rain), heat anomaly, dry-spell length
risk_engine.py       combines indicators into the 0-100 score; supports scenario inputs
ml_features.py       features and target for the model; normals from training years only
ml_baselines.py      simple baselines the model must beat
ml_train.py          trains Logistic regression, Random forest, Gradient boosting; cross-validation; saves model
ml_predict.py        loads the saved model; prediction, per-prediction explanation, data checks
ml_anomaly.py        unusual-month detection (statistical test + Isolation Forest)
dashboard_logic.py   tables and report text shared by the website and the Streamlit app
history.py           risk score for every year as of 30 September
check_data.py, check_2015.py, compare_windows.py, sensitivity.py   data and method checks
app.py               first Streamlit dashboard (backup)
data/                downloaded CSV files and history_scores.csv
models/              omnisight_model.joblib and model_card.json
```

## Data

- Source: Open-Meteo Historical Weather API (ERA5 reanalysis, a gridded model estimate, not a station measurement).
- Variables: daily maximum temperature and daily precipitation sum, 1991 to latest available.
- Attribution: weather data by [Open-Meteo.com](https://open-meteo.com/) (CC BY 4.0). Free for non-commercial use.
- The app reads the saved CSV files. "Update data" fetches only the newest days; if there is no internet, the saved
  data stays unchanged and a message says so.
- City coordinates are approximate points, not district boundaries.

## Risk score method

1. **Rain deficit:** SPI-3 (3-month Standardized Precipitation Index) against a 1991-2020 baseline.
2. **Heat:** last-30-day mean maximum temperature vs the same days in 1991-2020 (in standard deviations).
3. **Dry spell:** longest run of days with under 1 mm of rain in the last 60 days.
4. **Score:** 100 x (0.50 x rain + 0.25 x heat + 0.25 x dry), levels at 25 / 50 / 75.

The weights and level cut-offs are **design assumptions**, not scientifically calibrated values.

## Next-month model

- **Question:** at the end of April to September, will next month's rain be in the lowest third of that calendar
  month in 1991-2015 (for that city)? Labels come from the same weather data; nothing is invented.
- **Features** (past data only): rain of the last 1, 3 and 6 months and temperature of the last 30 days, each as a
  z-score against the training-year normal; longest dry spell in 60 days; time of year.
- **Split:** train on origins up to 2015, test on 2016 onwards. Normals and thresholds use training years only.
  `test_ml.py` changes the future and checks that the features do not move.
- **Model choice:** settings chosen by walk-forward cross-validation inside the training years; the model used in
  the app is picked by that cross-validation, not by the test score.
- **Result on the test years** (`python ml_train.py`, our run on the saved data): ROC-AUC 0.576 (95% interval
  0.41 to 0.74) for logistic regression, 0.582 (0.45 to 0.71) for random forest and 0.599 (0.49 to 0.71) for gradient
  boosting. An AUC of 0.5 means guessing, so **the skill is modest and not proven**. Intervals resample whole years,
  because the cities in one year share a monsoon.
- **Baselines** (balanced accuracy, 0.5 = guessing): persistence 0.44, the SPI rule 0.47, logistic regression 0.61.
- The test years were wetter than the training years (18% of months "dry" against 31%), which affects precision.
- Permutation importance on the test years ranked the 30-day temperature anomaly first and the 3-month rain
  anomaly second. This is correlation, not proof of cause.
- The model output is a **model score**, not a calibrated probability.

## Unusual months

For every city and month since 1991 we compute four seasonal z-scores (rain, temperature, longest dry spell, number
of rainy days) against 1991-2020. Two detectors run side by side: any |z| of 2 or more, and an Isolation Forest
trained on 1991-2020 that flags the most unusual 5%. A flag means "unusual for this city", not a drought
declaration. Months with a normal of under 25 mm of rain are not scored for rain. A month dominated by one very
large daily value (for example Indore, 26 June 1997) is marked as weak evidence.

## Scenario lab

The scenario multiplies the last 3 months of rain and adds a temperature change to the last 30 days, then
recomputes the risk score (and feeds the same what-if to the model). It is simple arithmetic, not a physical model
of any district. Groundwater, reservoir and water-demand scenarios are not included.

## Validation of the risk score

**Status: limited validation. This is a sanity check, not a test on unseen data.**

- Four monsoons are documented as deficient across India: 2002 (19% below the long-period average, LPA),
  2009 (22% below), 2014 (88% of LPA) and 2015 (86% of LPA). Sources: ORF (2002, 2009); IMD "Southwest Monsoon 2015"
  report (2014, 2015).
- Ranked by the average score of our five cities, 2002 is 3rd, 2015 is 5th and 2009 is 6th of 36 years. 2014 is
  outside the top 8.
- Years 2000, 2001 and 2004 also rank high. We could not verify them against a source.
- District check for 2015 against IMD figures quoted by SANDRP (`check_2015.py`): same direction for Gwalior,
  Jabalpur and Bhopal; opposite direction for Indore and Ujjain. The same article reports large gaps between IMD and
  the MP Agriculture Department, so we cannot tell which source is right.
- Outlier test (`sensitivity.py`): capping each city's largest daily rainfall changed SPI-3 by at most 0.03.
- Window choice (`compare_windows.py`): SPI-3 and SPI-4 rank the years alike (Spearman 0.88 to 0.96).

All-India figures do not map exactly onto single cities, and 1991-2020 is both the baseline and the scoring period.
We make no accuracy claim.

## API

All endpoints return JSON. Errors look like `{"error": "..."}`.

| Endpoint | Returns |
|---|---|
| `GET /api/health` | data dates, model info |
| `GET /api/overview` | every city: risk score and next-month view |
| `GET /api/city/<name>/risk` | risk score and indicators; optional `?rain_factor=0.7&temp_add=2` |
| `GET /api/city/<name>/prediction` | model prediction with explanation; same optional scenario inputs |
| `GET /api/city/<name>/history` | monthly rain vs normal, newest 45 days |
| `GET /api/city/<name>/anomalies` | unusual months with triggers and evidence |
| `GET /api/city/<name>/compare` | baseline vs scenario side by side |
| `GET /api/city/<name>/sensitivity` | risk score on a rain x temperature grid |
| `GET /api/city/<name>/report` | evidence report as Markdown |
| `GET /api/validation` | known-dry-year check and the model's test results |
| `GET /api/model` | model card |
| `POST /api/update` | fetch the newest days from Open-Meteo |

Inputs are validated: `rain_factor` must be 0 to 3 and `temp_add` -5 to 10, otherwise the API answers 400.

## Limitations

- Reanalysis data is a model-based gridded estimate, not a measurement at a local station.
- Only rainfall and temperature are used. Groundwater, reservoir, soil moisture and demand data are not included.
- Weights (50/25/25) and level cut-offs (25/50/75) are design assumptions.
- SPI-3 covers the last three months, so an earlier deficit (for example in June) can be missed.
- Next-month prediction has modest, unproven skill (see above) and only works for forecasts made in April to September.
- ERA5 contains a few very large daily values (for example Indore, 26 June 1997); we could not verify them.
- The risk score cannot be computed when the latest complete month is a dry-season month (December to March),
  because the SPI cannot be fitted there; the app says so instead of showing a number.
- Validation is limited (see above). Only five cities.
- No satellite (NDVI) data, no action-ranking engine, no water-demand scenarios. These are future work.
- OMNISIGHT is not a forecast of drought and not an official warning.

## Tested with

Python 3.13 on Windows with streamlit 1.66.0, pandas 3.0.6, numpy 2.5.4, scipy 1.18.1, scikit-learn 1.9.1,
plotly 7.1.0, folium 0.20.0, streamlit-folium 0.27.4 and requests 2.34.2. The website needs only the standard
library plus pandas, numpy, scipy and scikit-learn on the server; the browser side uses no external library.
The font loads from Google Fonts when online and falls back to system fonts offline.

## Team

Jamila Panbiharwala, Zaki Ajmeri, Sparsh Parmar. Kakka International School, Nalkheda.
(Add roles if you want.)
