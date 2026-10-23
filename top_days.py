import glob
import pandas as pd

for path in sorted(glob.glob("data/*_daily.csv")):
    df = pd.read_csv(path, parse_dates=["date"])
    print("\n", df["city"].iloc[0])
    print(df.nlargest(5, "rain_mm")[["date", "rain_mm"]].to_string(index=False))