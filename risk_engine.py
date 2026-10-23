import numpy as np
import pandas as pd

from indicators import (fit_spi_params, spi_from_value, heat_z,
                        longest_dry_run, last_complete_month_end)

# These weights and level cut-offs are DESIGN ASSUMPTIONS (not scientific constants).
# Show them on screen and let the user change them.
WEIGHTS = {"rain": 0.50, "heat": 0.25, "dry": 0.25}
LEVELS = [(25, "Low"), (50, "Moderate"), (75, "High"), (101, "Very high")]


def level_for(score):
    for limit, name in LEVELS:
        if score < limit:
            return name


def combine(spi3, hz, dry, weights=WEIGHTS):
    """Turn the three indicators into factor shares, a 0-100 score and a level."""
    parts = {
        "rain": float(np.clip(-spi3 / 2, 0, 1)),   # SPI -2 or lower -> full marks
        "heat": float(np.clip(hz / 2, 0, 1)),      # 2 standard deviations hotter -> full marks
        "dry": float(np.clip(dry / 30, 0, 1)),     # 30-day dry spell -> full marks
    }
    score = 100 * sum(weights[k] * parts[k] for k in parts)
    return {"parts": parts, "score": round(score, 1), "level": level_for(score)}


def assess_city(df, rain_factor=1.0, temp_add=0.0, params=None, weights=WEIGHTS):
    """df has columns: date, tmax_c, rain_mm (daily).
    rain_factor / temp_add are what-if changes applied to the latest 3 months of rain
    and the latest 30 days of temperature. Defaults = real data, no scenario."""
    rain = df.set_index("date")["rain_mm"]
    tmax = df.set_index("date")["tmax_c"]
    end = last_complete_month_end(rain.index)
    rain, tmax = rain[:end], tmax[:end]
    params = params or fit_spi_params(rain)

    start3 = end.replace(day=1) - pd.DateOffset(months=2)   # first day of the 3-month window
    start30 = end - pd.Timedelta(days=29)
    r, t = rain.copy(), tmax.copy()
    r[start3:] = r[start3:] * rain_factor
    t[start30:] = t[start30:] + temp_add

    spi3 = spi_from_value(r[start3:end].sum(), end.month, params)
    hz = float(heat_z(t).loc[end])
    dry = longest_dry_run(r)

    out = combine(spi3, hz, dry, weights)
    out.update({"as_of": end.date(), "spi3": spi3, "heat_z": hz, "dry_run_days": dry})
    return out