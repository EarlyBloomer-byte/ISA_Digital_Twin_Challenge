"""Pavement physics used by both the simulated world and the twin.

Models (all simplified, parameters are illustrative and must be calibrated):
  * Load equivalency: AASHTO fourth-power approximation per axle group.
  * Damage: linear (Miner-type) accumulation of equivalent standard axle loads
    (ESAL) against design capacity, modified by temperature and moisture.
  * Condition: condition index CI = 100 (1 - D^beta); roughness IRI(D).
"""
from __future__ import annotations

import numpy as np

G = 9.81
REF_SINGLE_KN = 80.0      # standard single axle (18 kip)
REF_TANDEM_KN = 148.0     # approx. tandem-axle reference
AXLE_SHARE = (0.10, 0.45, 0.45)  # steer / drive tandem / trailer tandem (6x4 + tandem trailer)
BETA = 1.3
IRI_NEW = 1.5      # m/km, new pavement
IRI_SPAN = 7.0     # m/km added at D = 1


def esal_per_truck_p(gvw_t, exponent: float):
    """Load equivalency with a chosen exponent (used to test model mismatch; the standard value is 4)."""
    w = np.asarray(gvw_t, dtype=float) * G
    return ((AXLE_SHARE[0] * w / REF_SINGLE_KN) ** exponent
            + (AXLE_SHARE[1] * w / REF_TANDEM_KN) ** exponent
            + (AXLE_SHARE[2] * w / REF_TANDEM_KN) ** exponent)


def esal_per_truck(gvw_t):
    """Equivalent standard axle loads per truck pass (fourth-power law)."""
    return esal_per_truck_p(gvw_t, 4.0)


def temp_factor(t_c):
    """Asphalt softens when hot: damage rate doubles per +15 C above 30 C (clipped)."""
    return np.clip(2.0 ** ((np.asarray(t_c, dtype=float) - 30.0) / 15.0), 0.5, 3.0)


def wet_factor(wetness):
    """Moisture weakens base/subgrade: up to 2x damage rate when saturated."""
    return 1.0 + np.clip(wetness, 0.0, 1.0)


def condition_index(d):
    d = np.clip(np.asarray(d, dtype=float), 0.0, 1.0)
    return 100.0 * (1.0 - d ** BETA)


def damage_from_ci(ci):
    return np.clip(1.0 - np.asarray(ci, dtype=float) / 100.0, 0.0, 1.0) ** (1.0 / BETA)


def iri_from_damage(d):
    d = np.clip(np.asarray(d, dtype=float), 0.0, 1.35)
    return IRI_NEW + IRI_SPAN * d ** BETA


def diri_dd(d):
    d = np.clip(np.asarray(d, dtype=float), 0.05, 1.35)
    return IRI_SPAN * BETA * d ** (BETA - 1.0)
