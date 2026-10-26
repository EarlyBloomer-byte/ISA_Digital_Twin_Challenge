"""Record real hourly weather for the corridor midpoint (used by hybrid mode).

Source: Open-Meteo forecast API with `past_days` (no API key). Needs internet.
NOTE: not exercised against the live service in the development sandbox. Check the file it writes.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

OUT = Path(__file__).resolve().parent.parent / "data" / "field" / "weather_lagos_ibadan.json"
LAT, LON = 7.0, 3.67  # corridor midpoint (approximate)


def main(days: int = 60):
    r = httpx.get("https://api.open-meteo.com/v1/forecast", timeout=60, params={
        "latitude": LAT, "longitude": LON, "hourly": "temperature_2m,precipitation",
        "past_days": min(days, 92), "forecast_days": 1, "timezone": "UTC"})
    r.raise_for_status()
    h = r.json()["hourly"]
    OUT.write_text(json.dumps({
        "source": "Open-Meteo forecast API (past_days, model-based reanalysis/forecast blend)",
        "retrieved_utc": datetime.now(timezone.utc).isoformat(), "latitude": LAT, "longitude": LON,
        "start_iso": h["time"][0],
        "hourly": {"precipitation": h["precipitation"], "temperature_2m": h["temperature_2m"]},
    }))
    print(f"wrote {OUT} ({len(h['time'])} hourly values from {h['time'][0]})")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 60)
