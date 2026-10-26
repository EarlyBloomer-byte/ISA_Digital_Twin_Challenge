"""International Roughness Index (golden-car) and ISO 8608 profile synthesis.

Used for verification: the twin's roughness observations are expressed in IRI,
and this module lets us check the IRI computation against synthetic road
profiles of known ISO 8608 roughness class.
"""
from __future__ import annotations

import numpy as np
from scipy import signal

# Golden-car parameters (normalised by sprung mass), Sayers (1986)
K1, K2, C, MU = 653.0, 63.3, 6.0, 0.15

ISO8608_GD0 = {  # geometric-mean PSD at n0 = 0.1 cycle/m, m^3
    "A": 16e-6, "B": 64e-6, "C": 256e-6, "D": 1024e-6, "E": 4096e-6,
}


def iri_from_profile(profile_m: np.ndarray, dx: float = 0.25, speed_kmh: float = 80.0,
                     skip_m: float = 50.0) -> float:
    """IRI in m/km from an elevation profile sampled every `dx` metres."""
    y = np.asarray(profile_m, dtype=float)
    y = y - y[0]
    v = speed_kmh / 3.6
    dt = dx / v
    A = np.array([[0, 1, 0, 0],
                  [-K2, -C, K2, C],
                  [0, 0, 0, 1],
                  [K2 / MU, C / MU, -(K1 + K2) / MU, -C / MU]])
    B = np.array([[0], [0], [0], [K1 / MU]])
    Cm = np.array([[0, 1, 0, -1]])
    D = np.zeros((1, 1))
    Ad, Bd, Cd, Dd, _ = signal.cont2discrete((A, B, Cm, D), dt, method="foh")
    _, out, _ = signal.dlsim((Ad, Bd, Cd, Dd, dt), y.reshape(-1, 1))
    k = int(skip_m / dx)
    stroke_rate = np.abs(out[k:, 0])
    return float(np.mean(stroke_rate) / v * 1000.0)


def iso8608_profile(cls: str, length_m: float = 1000.0, dx: float = 0.25, seed: int = 0) -> np.ndarray:
    """Synthesize a road profile for ISO 8608 class A..E (waviness w = 2)."""
    rng = np.random.default_rng(seed)
    gd0 = ISO8608_GD0[cls]
    n0 = 0.1
    n_samples = int(length_m / dx)
    dn = 1.0 / length_m
    n_k = np.arange(1, n_samples // 2) * dn
    amp = np.sqrt(2.0 * gd0 * (n_k / n0) ** -2.0 * dn)
    phase = rng.uniform(0, 2 * np.pi, size=n_k.size)
    x = np.arange(n_samples) * dx
    z = np.zeros(n_samples)
    for a, n, p in zip(amp, n_k, phase):
        z += a * np.cos(2 * np.pi * n * x + p)
    return z
