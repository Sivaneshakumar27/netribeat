"""Detrending and resampling of the RR series (Kubios-compatible)."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
from scipy import sparse
from scipy.interpolate import CubicSpline
from scipy.sparse.linalg import spsolve

F = npt.NDArray[np.float64]


def smoothness_priors(z: F, lam: float) -> F:
    """Tarvainen et al. 2002: trend = (I + λ² D₂ᵀD₂)⁻¹ z, D₂ the second-difference matrix."""
    n = z.size
    if n < 3:
        return np.full(n, float(np.mean(z)))
    d2 = sparse.diags([1.0, -2.0, 1.0], [0, 1, 2], shape=(n - 2, n))
    a = sparse.identity(n, format="csc") + lam**2 * (d2.T @ d2)
    return np.asarray(spsolve(a.tocsc(), z), dtype=np.float64)


def resample(t: F, rr: F, fs: float) -> tuple[F, F]:
    """Cubic-spline interpolation of the RR series onto an even grid (Kubios: 4 Hz)."""
    grid = np.arange(t[0], t[-1], 1.0 / fs)
    return grid, CubicSpline(t, rr)(grid)
