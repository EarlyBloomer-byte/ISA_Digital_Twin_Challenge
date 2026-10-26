import numpy as np

from routetwin import pavement as pv
from routetwin.estimator import PavementEKF


def test_ekf_recovers_damage_and_load_multiplier():
    rng = np.random.default_rng(0)
    e = PavementEKF()
    d_true, theta_true, u = 0.35, 1.5, 3e-5
    for k in range(1, 10001):
        d_true += theta_true * u
        e.predict(u)
        if k % 5 == 0:
            e.update(float(pv.iri_from_damage(d_true)) + 0.6 * rng.standard_normal())
    assert abs(e.d - d_true) < 0.04
    assert abs(e.theta - theta_true) < 0.3
    assert e.sd_d < 0.05


def test_ekf_uncertainty_shrinks_with_observations_and_grows_without():
    e = PavementEKF()
    s0 = e.sd_d
    for _ in range(50):
        e.update(5.0)
    assert e.sd_d < s0
    s1 = e.sd_d
    for _ in range(2000):
        e.predict(1e-4)
    assert e.sd_d > s1


def test_ekf_rejects_gross_outlier():
    e = PavementEKF(d0=0.5, sd_d=0.05)
    before = e.d
    assert e.update(25.0) is False
    assert e.d == before and e.rejected == 1


def test_reset_after_maintenance():
    e = PavementEKF(d0=0.9)
    e.reset_after_maintenance(0.05)
    assert abs(e.d - 0.05) < 1e-12 and e.sd_d < 0.1
