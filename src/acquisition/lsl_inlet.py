"""LSL stream discovery and thread-safe sample acquisition."""

import threading
import queue
import time
from typing import Optional

try:
    import pylsl
    _LSL_AVAILABLE = True
except ImportError:
    _LSL_AVAILABLE = False

# Known Emotiv stream name prefixes
EMOTIV_STREAM_NAMES = {
    "eeg": "EmotivDataStream-EEG",
    "bandpower": "EmotivDataStream-Band Power",
    "performance": "EmotivDataStream-Performance Metrics",
}


def lsl_available() -> bool:
    return _LSL_AVAILABLE


def discover_streams(stream_type: Optional[str] = None, timeout: float = 5.0) -> list:
    """Return a list of available LSL StreamInfo objects.

    Args:
        stream_type: Filter by LSL type string (e.g. "EEG"). None returns all.
        timeout: Seconds to wait for stream discovery.
    """
    if not _LSL_AVAILABLE:
        return []
    if stream_type:
        return pylsl.resolve_stream("type", stream_type, timeout=timeout)
    return pylsl.resolve_streams(wait_time=timeout)


def discover_emotiv_streams(timeout: float = 5.0) -> dict:
    """Discover Emotiv streams by name. Returns {category: StreamInfo} for found streams."""
    if not _LSL_AVAILABLE:
        return {}
    found = {}
    all_streams = pylsl.resolve_streams(wait_time=timeout)
    for info in all_streams:
        for category, name in EMOTIV_STREAM_NAMES.items():
            if info.name() == name:
                found[category] = info
                break
    return found


class LSLInlet:
    """Thread-safe wrapper around a single LSL inlet.

    Runs a background thread that continuously pulls samples into a Queue.
    Call start() before reading and stop() when done.
    """

    def __init__(self, stream_info, max_queue_size: int = 1000):
        if not _LSL_AVAILABLE:
            raise RuntimeError("pylsl is not installed")
        self._info = stream_info
        self._inlet = pylsl.StreamInlet(stream_info, recover=True)
        self._queue: queue.Queue = queue.Queue(maxsize=max_queue_size)
        self._thread: Optional[threading.Thread] = None
        self._running = False

    @property
    def name(self) -> str:
        return self._info.name()

    @property
    def channel_count(self) -> int:
        return self._info.channel_count()

    @property
    def sample_rate(self) -> float:
        return self._info.nominal_srate()

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._pull_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)

    def _pull_loop(self) -> None:
        while self._running:
            try:
                sample, timestamp = self._inlet.pull_sample(timeout=0.1)
                if sample is not None:
                    if self._queue.full():
                        try:
                            self._queue.get_nowait()
                        except queue.Empty:
                            pass
                    self._queue.put_nowait((sample, timestamp))
            except Exception:
                time.sleep(0.01)

    def get_sample(self, timeout: float = 0.1) -> Optional[tuple]:
        """Return (sample_list, timestamp) or None if no data within timeout."""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def get_latest(self) -> Optional[tuple]:
        """Drain the queue and return only the most recent sample."""
        latest = None
        while True:
            try:
                latest = self._queue.get_nowait()
            except queue.Empty:
                break
        return latest

    def __repr__(self) -> str:
        return f"LSLInlet(name={self.name!r}, channels={self.channel_count}, rate={self.sample_rate} Hz)"
