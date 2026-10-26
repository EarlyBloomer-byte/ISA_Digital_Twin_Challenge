"""Per-segment state estimator: extended Kalman filter over [damage D, load-response multiplier theta].

Predict step  : D += theta * u, where u is the model-predicted damage increment from
                measured traffic (ESAL x temperature x moisture / design capacity).
Update step   : probe-truck roughness (IRI) corrects D; because D drifts at a rate set by
                theta, the filter also learns each segment's own structural weakness.
"""
from __future__ import annotations

import math

import numpy as np

from . import pavement as pv

Q_THETA = 3.5e-7     # random-walk process noise on theta, per prediction
THETA_BOUNDS = (0.3, 4.0)


class PavementEKF:
    def __init__(self, d0=0.5, sd_d=0.25, theta0=1.0, sd_theta=0.4, r_iri=0.6 ** 2):
        self.x = np.array([d0, theta0], dtype=float)
        self.P = np.diag([sd_d ** 2, sd_theta ** 2])
        self.r = r_iri
        self.rejected = 0
        self.consec_rejects = 0
        self.updates = 0

    def predict(self, u: float):
        d, th = self.x
        self.x[0] = d + th * u
        F = np.array([[1.0, u], [0.0, 1.0]])
        Q = np.diag([(0.05 * th * u) ** 2 + 1e-12, Q_THETA])
        self.P = F @ self.P @ F.T + Q

    def update(self, z_iri: float) -> bool:
        d = max(float(self.x[0]), 0.05)
        h = float(pv.iri_from_damage(d))
        H = np.array([[float(pv.diri_dd(d)), 0.0]])
        S = float((H @ self.P @ H.T)[0, 0]) + self.r
        y = z_iri - h
        if abs(y) > 4.0 * math.sqrt(S):
            self.rejected += 1
            self.consec_rejects += 1
            if self.consec_rejects < 5:
                return False
            self.P[0, 0] += 0.05  # persistent disagreement: widen uncertainty and accept
            S += 0.05 * H[0, 0] ** 2
        self.consec_rejects = 0
        K = (self.P @ H.T) / S
        self.x = self.x + (K * y).ravel()
        self.x[0] = max(self.x[0], 0.0)
        self.x[1] = min(max(self.x[1], THETA_BOUNDS[0]), THETA_BOUNDS[1])
        IKH = np.eye(2) - K @ H
        self.P = IKH @ self.P @ IKH.T + K * self.r @ K.T  # Joseph form
        self.updates += 1
        return True

    def reset_after_maintenance(self, d_new: float, sd: float = 0.08):
        self.x[0] = d_new
        self.P[0, :] = 0.0
        self.P[:, 0] = 0.0
        self.P[0, 0] = sd ** 2
        self.consec_rejects = 0

    @property
    def d(self) -> float:
        return float(self.x[0])

    @property
    def theta(self) -> float:
        return float(self.x[1])

    @property
    def sd_d(self) -> float:
        return math.sqrt(max(self.P[0, 0], 0.0))

    @property
    def sd_theta(self) -> float:
        return math.sqrt(max(self.P[1, 1], 0.0))
