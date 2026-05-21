"""Baseline calibration and per-channel normalization."""

import time
from typing import Dict, List, Optional
import numpy as np


class BaselineCalibrator:
    """Collects samples during a calibration window, then normalizes relative to that baseline.

    Usage:
        cal = BaselineCalibrator(duration_seconds=60)
        # During calibration window:
        while cal.is_collecting:
            cal.add_sample({"AF3.alpha": 0.45, "AF4.alpha": 0.51, ...})
        cal.finish()
        # During session:
        normalized = cal.normalize({"AF3.alpha": 0.60, ...})
    """

    def __init__(self, duration_seconds: float = 60.0):
        self.duration = duration_seconds
        self._start_time: Optional[float] = None
        self._buffer: Dict[str, List[float]] = {}
        self._mean: Dict[str, float] = {}
        self._std: Dict[str, float] = {}
        self._finished = False

    def start(self) -> None:
        self._start_time = time.monotonic()
        self._buffer.clear()
        self._finished = False

    @property
    def is_collecting(self) -> bool:
        if self._start_time is None or self._finished:
            return False
        return (time.monotonic() - self._start_time) < self.duration

    @property
    def elapsed(self) -> float:
        if self._start_time is None:
            return 0.0
        return time.monotonic() - self._start_time

    @property
    def progress(self) -> float:
        return min(1.0, self.elapsed / self.duration)

    def add_sample(self, data: Dict[str, float]) -> None:
        for key, value in data.items():
            self._buffer.setdefault(key, []).append(float(value))

    def finish(self) -> None:
        for key, values in self._buffer.items():
            arr = np.array(values)
            self._mean[key] = float(arr.mean())
            std = float(arr.std())
            self._std[key] = std if std > 1e-9 else 1.0
        self._finished = True

    def normalize(self, data: Dict[str, float]) -> Dict[str, float]:
        """Return z-score normalized values relative to baseline.

        Falls back to raw value if key was not seen during calibration.
        """
        result = {}
        for key, value in data.items():
            if key in self._mean:
                result[key] = (value - self._mean[key]) / self._std[key]
            else:
                result[key] = value
        return result

    def normalize_to_range(
        self, data: Dict[str, float], out_min: float = 0.0, out_max: float = 1.0
    ) -> Dict[str, float]:
        """Normalize and clip to [out_min, out_max] using ±3 std as the natural range."""
        z = self.normalize(data)
        result = {}
        for key, zval in z.items():
            t = (zval + 3.0) / 6.0  # map [-3, +3] std → [0, 1]
            t = max(0.0, min(1.0, t))
            result[key] = out_min + t * (out_max - out_min)
        return result

    @property
    def baseline_stats(self) -> Dict[str, Dict[str, float]]:
        return {k: {"mean": self._mean[k], "std": self._std[k]} for k in self._mean}


class MinMaxNormalizer:
    """Simple running min-max normalizer with optional decay for adaptive range."""

    def __init__(self, decay: float = 0.9999):
        self._min: Dict[str, float] = {}
        self._max: Dict[str, float] = {}
        self.decay = decay

    def update(self, data: Dict[str, float]) -> Dict[str, float]:
        result = {}
        for key, value in data.items():
            if key not in self._min:
                self._min[key] = value
                self._max[key] = value
            else:
                self._min[key] = min(self._min[key] * self.decay, value)
                self._max[key] = max(self._max[key] * self.decay, value)
            rng = self._max[key] - self._min[key]
            if rng < 1e-9:
                result[key] = 0.5
            else:
                result[key] = (value - self._min[key]) / rng
        return result
