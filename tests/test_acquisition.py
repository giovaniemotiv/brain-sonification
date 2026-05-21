"""Tests for LSL acquisition layer using a synthetic outlet (no Emotiv hardware needed)."""

import time
import threading
import pytest

pylsl = pytest.importorskip("pylsl", reason="pylsl not installed")

from src.acquisition.lsl_inlet import LSLInlet, discover_streams, lsl_available


STREAM_NAME = "TestStream_brain_sonification"
STREAM_TYPE = "EEG"
CHANNEL_COUNT = 4
SAMPLE_RATE = 100.0


@pytest.fixture(scope="module")
def fake_outlet():
    """Create a synthetic LSL outlet that pushes samples continuously."""
    info = pylsl.StreamInfo(STREAM_NAME, STREAM_TYPE, CHANNEL_COUNT, SAMPLE_RATE, "float32", "uid_test_123")
    outlet = pylsl.StreamOutlet(info)
    stop_event = threading.Event()

    def push_loop():
        sample = [0.1, 0.2, 0.3, 0.4]
        while not stop_event.is_set():
            outlet.push_sample(sample)
            time.sleep(1.0 / SAMPLE_RATE)

    thread = threading.Thread(target=push_loop, daemon=True)
    thread.start()
    time.sleep(0.5)  # let the outlet register
    yield outlet
    stop_event.set()


def test_lsl_available():
    assert lsl_available() is True


def test_discover_streams(fake_outlet):
    streams = discover_streams(timeout=3.0)
    names = [s.name() for s in streams]
    assert STREAM_NAME in names, f"Expected {STREAM_NAME!r} in {names}"


def test_inlet_connects_and_pulls(fake_outlet):
    streams = discover_streams(timeout=3.0)
    target = next((s for s in streams if s.name() == STREAM_NAME), None)
    assert target is not None, "Test stream not found"

    inlet = LSLInlet(target)
    assert inlet.channel_count == CHANNEL_COUNT
    assert inlet.sample_rate == SAMPLE_RATE

    inlet.start()
    time.sleep(0.2)
    result = inlet.get_sample(timeout=1.0)
    inlet.stop()

    assert result is not None, "No sample received within timeout"
    sample, timestamp = result
    assert len(sample) == CHANNEL_COUNT
    assert isinstance(timestamp, float)


def test_inlet_get_latest_drains_queue(fake_outlet):
    streams = discover_streams(timeout=3.0)
    target = next((s for s in streams if s.name() == STREAM_NAME), None)
    inlet = LSLInlet(target)
    inlet.start()
    time.sleep(0.3)  # accumulate some samples
    latest = inlet.get_latest()
    inlet.stop()

    assert latest is not None
    # Queue should be drained after get_latest
    assert inlet.get_latest() is None
