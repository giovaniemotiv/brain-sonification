"""Tests for processing/smoothing — no hardware or audio required."""

import pytest
from src.processing.smoothing import ExponentialSmoother, MultiChannelSmoother, smooth


def test_smoother_first_sample_returns_raw():
    s = ExponentialSmoother(alpha=0.3)
    assert s.update(5.0) == pytest.approx(5.0)


def test_smoother_converges_toward_target():
    s = ExponentialSmoother(alpha=0.5)
    val = 0.0
    for _ in range(20):
        val = s.update(1.0)
    assert val > 0.99


def test_smoother_alpha_validation():
    with pytest.raises(ValueError):
        ExponentialSmoother(alpha=0.0)
    with pytest.raises(ValueError):
        ExponentialSmoother(alpha=1.5)


def test_smoother_reset():
    s = ExponentialSmoother(alpha=0.3)
    s.update(10.0)
    s.reset()
    assert s.value is None
    assert s.update(5.0) == pytest.approx(5.0)


def test_multi_channel_smoother():
    ms = MultiChannelSmoother(alpha=0.5)
    data = {"alpha": 1.0, "beta": 2.0}
    result = ms.update(data)
    assert set(result.keys()) == {"alpha", "beta"}
    # First update returns raw value
    assert result["alpha"] == pytest.approx(1.0)
    assert result["beta"] == pytest.approx(2.0)
    # Second update smooths
    result2 = ms.update({"alpha": 0.0, "beta": 0.0})
    assert result2["alpha"] == pytest.approx(0.5)
    assert result2["beta"] == pytest.approx(1.0)


def test_stateless_smooth():
    assert smooth(1.0, None, alpha=0.3) == pytest.approx(1.0)
    assert smooth(1.0, 0.0, alpha=0.5) == pytest.approx(0.5)
