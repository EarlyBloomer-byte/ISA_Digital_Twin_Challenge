"""Weather providers that drive the simulated world.

InternalWeather - stochastic generator (simulation mode, fully reproducible).
SeriesWeather   - replays a recorded real hourly series (hybrid mode).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

# Illustrative fraction of wet hours per month for the Lagos region (Jan..Dec)
WET_HOUR_FRACTION = [0.02, 0.03, 0.06, 0.10, 0.14, 0.18, 0.14, 0.08, 0.16, 0.12, 0.05, 0.02]
MEAN_AIR_TEMP = [28.5, 29.5, 29.5, 29.0, 28.0, 26.5, 25.5, 25.5, 26.0, 27.0, 28.0, 28.0]
MEAN_RAIN_DURATION_TICKS = 12


def month_of_doy(doy: int) -> int:
    return min(11, int(((doy - 1) % 365) / 30.4375))


class InternalWeather:
    def __init__(self, rng: np.random.Generator, start_doy: int = 121, tick_s: int = 600):
        self.rng = rng
        self.start_doy = start_doy
        self.tick_s = tick_s
        self.raining = False
        self.intensity = 0.0
        self.force_rain_until = -1.0

    def force_rain(self, until_ts: float, intensity: float = 8.0):
        self.force_rain_until = until_ts
        self.raining, self.intensity = True, intensity

    def at(self, ts: float) -> tuple[float, float]:
        day = ts / 86400.0
        doy = self.start_doy + int(day)
        hour = (ts % 86400.0) / 3600.0
        m = month_of_doy(doy)
        if ts < self.force_rain_until:
            self.raining = True
        else:
            frac = WET_HOUR_FRACTION[m]
            p_end = 1.0 / MEAN_RAIN_DURATION_TICKS
            p_start = frac / (MEAN_RAIN_DURATION_TICKS * (1.0 - frac))
            if self.raining:
                if self.rng.random() < p_end:
                    self.raining = False
            elif self.rng.random() < p_start:
                self.raining = True
                self.intensity = float(self.rng.lognormal(math.log(3.0), 0.7))
        rain = self.intensity if self.raining else 0.0
        air = MEAN_AIR_TEMP[m] + 4.0 * math.sin(2 * math.pi * (hour - 9.0) / 24.0) - (1.5 if rain > 0 else 0.0)
        return rain, air


class SeriesWeather:
    """Replays hourly rain (mm/h) and air temperature (C) from a recorded JSON file.

    File format (written by scripts/record_weather.py):
      {"source": "...", "start_iso": "...", "hourly": {"precipitation": [...], "temperature_2m": [...]}}
    """
    def __init__(self, rain: list[float], temp: list[float], meta: dict | None = None):
        if len(rain) != len(temp) or not rain:
            raise ValueError("weather series must be non-empty and equal length")
        self.rain = [0.0 if v is None else float(v) for v in rain]
        self.temp = [28.0 if v is None else float(v) for v in temp]
        self.meta = meta or {}

    @classmethod
    def from_file(cls, path: str | Path) -> "SeriesWeather":
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(
                f"{p} not found. Hybrid mode replays recorded real weather: run "
                "`python scripts/record_weather.py` (needs internet) first.")
        raw = json.loads(p.read_text())
        h = raw["hourly"]
        return cls(h["precipitation"], h["temperature_2m"], {k: v for k, v in raw.items() if k != "hourly"})

    def force_rain(self, until_ts: float, intensity: float = 8.0):
        pass  # recorded series is not overridden

    def at(self, ts: float) -> tuple[float, float]:
        i = int(ts // 3600) % len(self.rain)  # loops if the sim outlasts the recording
        return self.rain[i], self.temp[i]
