import numpy as np
import pytest

from routetwin import pavement as pv
from routetwin.iri import iri_from_profile, iso8608_profile


def test_fourth_power_law():
    # Every axle group scales with load^4, so +10% GVW => +46.41% ESAL exactly
    ratio = pv.esal_per_truck(44.0) / pv.esal_per_truck(40.0)
    assert ratio == pytest.approx(1.1 ** 4, rel=1e-9)


def test_overloading_is_disproportionately_damaging():
    assert pv.esal_per_truck(55.0) > 3.0 * pv.esal_per_truck(40.0)


def test_condition_and_iri_are_monotone():
    d = np.linspace(0, 1.2, 50)
    assert np.all(np.diff(pv.condition_index(d)) <= 1e-12)
    assert np.all(np.diff(pv.iri_from_damage(d)) >= 0)
    assert pv.condition_index(0.0) == 100.0


def test_damage_ci_roundtrip():
    for ci in (90.0, 60.0, 45.0, 10.0):
        assert pv.condition_index(pv.damage_from_ci(ci)) == pytest.approx(ci, abs=1e-9)


def test_temperature_and_moisture_raise_damage_rate():
    assert pv.temp_factor(45.0) > pv.temp_factor(30.0) > pv.temp_factor(20.0)
    assert pv.wet_factor(1.0) == 2.0 and pv.wet_factor(0.0) == 1.0


def test_iri_flat_profile_is_zero():
    assert iri_from_profile(np.zeros(4000)) == pytest.approx(0.0, abs=1e-9)


def test_iri_is_linear_in_amplitude():
    p = iso8608_profile("B", seed=3)
    assert iri_from_profile(2.0 * p) == pytest.approx(2.0 * iri_from_profile(p), rel=1e-6)


def test_iri_orders_iso8608_classes():
    vals = [np.mean([iri_from_profile(iso8608_profile(c, seed=s)) for s in range(3)]) for c in "ABCD"]
    assert vals == sorted(vals)
    assert vals[3] / vals[0] > 6  # class D has 64x the PSD of A => about 8x the roughness amplitude
