"""Beat times and RR intervals of one decoded session.

The decoder's `rrt` rows hold, per beat, the RR to the next beat (empty at a break). Each RR is
placed at the end of its interval: t_end = beat time + RR.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
import pandas as pd

from netribeat.hex_decoder.reader import item

F = npt.NDArray[np.float64]


def rr_intervals(df: pd.DataFrame, t0_ms: int) -> tuple[F, F]:
    """(t_end in seconds from the session start, RR in ms) for every beat with a known RR."""
    beats = item(df, "rrt").dropna(subset=["value"])
    rr = beats["value"].to_numpy(dtype=float)
    t_s = np.array([(t.value // 1_000_000 - t0_ms) / 1000 for t in beats["timestamp"]])
    return np.round(t_s, 3) + rr / 1000, rr
