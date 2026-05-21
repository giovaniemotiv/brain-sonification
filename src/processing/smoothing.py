"""Exponential smoothing for EEG signal streams."""

from typing import Dict, Optional, Union


class ExponentialSmoother:
    """Single-value exponential moving average.

    value_t = alpha * raw + (1 - alpha) * value_{t-1}
    Lower alpha = smoother but more lag. Typical: 0.2-0.4 for bandpower.
    """

    def __init__(self, alpha: float = 0.3, initial: Optional[float] = None):
        if not (0.0 < alpha <= 1.0):
            raise ValueError(f"alpha must be in (0, 1], got {alpha}")
        self.alpha = alpha
        self._value: Optional[float] = initial

    def update(self, raw: float) -> float:
        if self._value is None:
            self._value = raw
        else:
            self._value = self.alpha * raw + (1.0 - self.alpha) * self._value
        return self._value

    @property
    def value(self) -> Optional[float]:
        return self._value

    def reset(self) -> None:
        self._value = None


class MultiChannelSmoother:
    """Applies ExponentialSmoother to each key in a dict independently."""

    def __init__(self, alpha: float = 0.3):
        self.alpha = alpha
        self._smoothers: Dict[str, ExponentialSmoother] = {}

    def update(self, data: Dict[str, float]) -> Dict[str, float]:
        result = {}
        for key, value in data.items():
            if key not in self._smoothers:
                self._smoothers[key] = ExponentialSmoother(self.alpha)
            result[key] = self._smoothers[key].update(value)
        return result

    def reset(self) -> None:
        for s in self._smoothers.values():
            s.reset()


def smooth(value: float, prev: Optional[float], alpha: float = 0.3) -> float:
    """Stateless functional smoother. Returns new smoothed value."""
    if prev is None:
        return value
    return alpha * value + (1.0 - alpha) * prev
