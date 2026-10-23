"""OMNISIGHT dashboard. Run:  streamlit run app.py

Reads the CSV files in data/ (run fetch_data.py once first). Works without internet,
except that the base map tiles need internet (an offline view is included).
"""
import os

import folium
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from streamlit_folium import st_folium

import dashboard_logic as dl
from fetch_data import CITIES
from indicators import fit_spi_params
from risk_engine import LEVELS, WEIGHTS, assess_city

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
HIST_PATH = os.path.join(DATA_DIR, "history_scores.csv")

COLORS = {"Low": "#2e8b57", "Moderate": "#e0a800", "High": "#e8590c", "Very high": "#a61e1e"}
EMOJI = {"Low": "🟢", "Moderate": "🟡", "High": "🟠", "Very high": "🔴"}

st.set_page_config(page_title="OMNISIGHT", layout="wide")


# ---------- cached data helpers ----------
@st.cache_data(show_spinner=False)
def load_all():
    return dl.load_cities(DATA_DIR)


@st.cache_data(show_spinner=False)
def load_history():
    return pd.read_csv(HIST_PATH) if os.path.exists(HIST_PATH) else None


data = load_all()
if not data:
    st.error("No data found in the 'data' folder. Run `python fetch_data.py` first, then reload this page.")
    st.stop()
cities = [c for c in CITIES if c in data]


@st.cache_data(show_spinner=False)
def params_for(city):
    return fit_spi_params(data[city].set_index("date")["rain_mm"])


@st.cache_data(show_spinner=False)
def assess(city, rain_factor=1.0, temp_add=0.0):
    return assess_city(data[city], rain_factor=rain_factor, temp_add=temp_add, params=params_for(city))


results = {c: assess(c) for c in cities}
table = dl.score_table(results, CITIES)
as_of = next(iter(results.values()))["as_of"]
hist = load_history()

# ---------- sidebar ----------
st.sidebar.title("OMNISIGHT")
st.sidebar.caption("Explainable water-stress risk indicator · Madhya Pradesh pilot")
city = st.sidebar.selectbox("City (for the detail tabs)", cities)
st.sidebar.warning("This is a risk indicator built from past weather data. It is not a forecast and not an "
                   "official warning. Weather data alone cannot establish actual water scarcity.")
with st.sidebar.expander("Score weights (design assumptions)"):
    st.write(pd.DataFrame({
        "Factor": [dl.FACTOR_LABELS[k] for k in WEIGHTS],
        "Weight": [f"{v:.0%}" for v in WEIGHTS.values()],
    }))
    st.caption("Level cut-offs: Low < 25, Moderate 25-50, High 50-75, Very high 75+. "
               "These are assumptions, not calibrated values.")
st.sidebar.caption("Weather data: Open-Meteo.com (CC BY 4.0). ERA5 reanalysis, a gridded estimate, "
                   "not a station measurement.")

st.title("OMNISIGHT")
st.caption(f"REAL DATA (reanalysis) · 1991 to {data[cities[0]]['date'].max().date()} · "
           f"scores are as of {as_of}, the last complete month")

tab_map, tab_city, tab_why, tab_what, tab_report, tab_val = st.tabs(
    ["Map & comparison", "City detail", "Why this score", "What-if", "Evidence report", "Validation"])

# ---------- 1. map and comparison ----------
with tab_map:
    st.subheader("Which cities show the strongest combination of risk indicators?")
    st.markdown("  ".join(f"{EMOJI[n]} **{n}**" for n in COLORS) +
                "  (Low < 25 · Moderate 25-50 · High 50-75 · Very high 75+)")
    m = folium.Map(location=[24.4, 77.9], zoom_start=6, tiles="OpenStreetMap")
    for _, row in table.iterrows():
        folium.CircleMarker(
            location=[row["Latitude"], row["Longitude"]], radius=16,
            color=COLORS[row["Level"]], fill=True, fill_color=COLORS[row["Level"]], fill_opacity=0.85,
            tooltip=folium.Tooltip(f"{row['City']}: {row['Score']} ({row['Level']})", permanent=True),
        ).add_to(m)
    st_folium(m, height=460, returned_objects=[])
    st.dataframe(table[["City", "Score", "Level", "SPI-3", "Heat (sd)", "Dry days"]], hide_index=True)
    with st.expander("Map tiles not loading? (offline view)"):
        offline = table.assign(Size=table["Score"] + 10)
        fig = px.scatter(offline, x="Longitude", y="Latitude", color="Level", text="City", size="Size",
                         size_max=30, color_discrete_map=COLORS)
        fig.update_traces(textposition="top center")
        st.plotly_chart(fig)

# ---------- 2. city detail ----------
with tab_city:
    res = results[city]
    st.subheader(f"{city}: what environmental changes are occurring?")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Risk score", f"{res['score']:.1f}", res["level"], delta_color="off")
    c2.metric("Rain (SPI-3)", f"{res['spi3']:.2f}", dl.spi_label(res["spi3"]), delta_color="off")
    c3.metric("Heat vs normal", f"{res['heat_z']:+.2f} sd", dl.heat_label(res["heat_z"]), delta_color="off")
    c4.metric("Longest dry spell", f"{res['dry_run_days']} days", "last 60 days", delta_color="off")

    mv = dl.monthly_vs_normal(data[city], as_of)
    fig = go.Figure()
    fig.add_bar(x=mv["month"], y=mv["actual_mm"], name="Actual rain (mm)")
    fig.add_scatter(x=mv["month"], y=mv["normal_mm"], name="1991-2020 average", mode="lines+markers")
    fig.update_layout(title="Monthly rainfall: last 12 complete months vs normal", yaxis_title="mm")
    st.plotly_chart(fig)

    spi = dl.recent_spi(data[city], params_for(city), as_of)
    fig = go.Figure(go.Scatter(x=spi.index, y=spi.values, mode="lines+markers", name="SPI-3"))
    for y, label in ((-1.0, "moderately dry"), (-1.5, "very dry"), (-2.0, "extremely dry")):
        fig.add_hline(y=y, line_dash="dot", annotation_text=label)
    fig.update_layout(title="3-month SPI since 2010 (months with enough rain history)", yaxis_title="SPI-3")
    st.plotly_chart(fig)

    if hist is not None:
        h = hist[hist["city"] == city]
        fig = px.bar(h, x="year", y="score", title="Risk score for each year, as of 30 September")
        for y in (25, 50, 75):
            fig.add_hline(y=y, line_dash="dot")
        st.plotly_chart(fig)
        st.caption("The 1991-2020 baseline is also the scoring period, so these are sanity checks against "
                   "documented dry years, not tests on unseen data.")

# ---------- 3. why this score ----------
with tab_why:
    res = results[city]
    pts = dl.contributions(res, WEIGHTS)
    st.subheader(f"{city}: what evidence and assumptions explain {res['score']:.1f}?")
    breakdown = pd.DataFrame({
        "Factor": [dl.FACTOR_LABELS[k] for k in pts],
        "Measured value": [f"SPI-3 = {res['spi3']:.2f} ({dl.spi_label(res['spi3'])})",
                           f"{res['heat_z']:+.2f} sd ({dl.heat_label(res['heat_z'])})",
                           f"{res['dry_run_days']} days"],
        "Factor share (0-1)": [round(res["parts"][k], 2) for k in pts],
        "Weight": [f"{WEIGHTS[k]:.0%}" for k in pts],
        "Points": [pts[k] for k in pts],
    })
    st.dataframe(breakdown, hide_index=True)
    fig = go.Figure(go.Bar(x=list(pts.values()), y=[dl.FACTOR_LABELS[k] for k in pts], orientation="h"))
    fig.update_layout(title=f"Points contributed to the {res['score']:.1f} score", xaxis_title="points (max 100 in total)")
    st.plotly_chart(fig)
    st.markdown("**Scoring logic**")
    st.code("rain  = clip(-SPI3 / 2, 0, 1)      # SPI -2 or lower  -> full marks\n"
            "heat  = clip(heat_sd / 2, 0, 1)    # 2 sd hotter      -> full marks\n"
            "dry   = clip(dry_days / 30, 0, 1)  # 30-day dry spell -> full marks\n"
            "score = 100 * (0.50*rain + 0.25*heat + 0.25*dry)", language="text")
    st.markdown("**Assumptions and limitations**")
    st.markdown("- Weights and level cut-offs are design assumptions, not calibrated values.\n"
                "- Data is ERA5 reanalysis (a model-based gridded estimate), not a local station measurement.\n"
                "- Version 1 uses rainfall and temperature only. Groundwater, reservoir and demand data are "
                "not included.\n"
                "- SPI-3 covers the last 3 months only, so an earlier deficit can be missed.")

# ---------- 4. what-if ----------
with tab_what:
    st.subheader(f"{city}: how does the estimated risk change under hypothetical conditions?")
    c1, c2 = st.columns(2)
    rain_pct = c1.slider("Rain in the last 3 months (% of actual)", 30, 150, 100, 5)
    temp_add = c2.slider("Extra heat in the last 30 days (°C)", 0.0, 5.0, 0.0, 0.5)
    base = results[city]
    scen = assess(city, rain_pct / 100, temp_add)
    if rain_pct != 100 or temp_add != 0:
        st.warning("SCENARIO: hypothetical values, not real data.")
    else:
        st.info("No change selected yet. Move a slider to explore a hypothetical scenario.")
    m1, m2, m3 = st.columns(3)
    m1.metric("Actual score", f"{base['score']:.1f}", base["level"], delta_color="off")
    m2.metric("Scenario score", f"{scen['score']:.1f}", scen["level"], delta_color="off")
    m3.metric("Change", f"{scen['score'] - base['score']:+.1f} points")
    pb, ps = dl.contributions(base, WEIGHTS), dl.contributions(scen, WEIGHTS)
    labels = [dl.FACTOR_LABELS[k] for k in pb]
    fig = go.Figure()
    fig.add_bar(x=labels, y=list(pb.values()), name="Actual")
    fig.add_bar(x=labels, y=list(ps.values()), name="Scenario (hypothetical)")
    fig.update_layout(barmode="group", yaxis_title="points")
    st.plotly_chart(fig)
    st.caption("The scenario multiplies the last 3 months of rain and adds the heat to the last 30 days of "
               "temperature, then recomputes the same score. It is an exploration of the model, not a forecast.")

# ---------- 5. evidence report ----------
with tab_report:
    res = results[city]
    top = dl.top_history(hist, city) if hist is not None else None
    text = dl.report_text(city, res, WEIGHTS, top)
    st.markdown(text)
    st.download_button("Download this report (Markdown)", text, file_name=f"omnisight_{city.lower()}_report.md")

# ---------- 6. validation (limited) ----------
with tab_val:
    st.subheader("How does the score compare with documented dry years?")
    if hist is None:
        st.info("Run `python history.py` first. It scores every year (as of 30 September) and saves the "
                "results this tab needs.")
    else:
        yearly = dl.yearly_average(hist)
        fig = px.bar(yearly, x="year", y="avg_score", color="Year type",
                     color_discrete_map={"Documented all-India deficient monsoon": "#e8590c",
                                         "Other years": "#7fa3ad"},
                     title="Average risk score of the five cities, each year as of 30 September")
        fig.update_layout(yaxis_title="average score (0-100)")
        st.plotly_chart(fig)
        st.dataframe(dl.validation_table(hist), hide_index=True)
        st.markdown("**Read this carefully**")
        st.markdown("- This is a sanity check, not a test on unseen data. 1991-2020 is both the baseline "
                    "and the scoring period.\n"
                    "- The highlighted years are all-India figures (ORF for 2002 and 2009, the IMD 2015 season "
                    "report for 2014 and 2015). They do not map exactly onto single cities.\n"
                    "- Some years rank high without a source we could check (for example 2000, 2001 and 2004).\n"
                    "- A district-level check for 2015 agreed for Gwalior, Jabalpur and Bhopal but not for "
                    "Indore and Ujjain, where IMD reports above-normal rain and our ERA5 data shows below-normal "
                    "rain. The sources disagree and we cannot tell which is right.")
