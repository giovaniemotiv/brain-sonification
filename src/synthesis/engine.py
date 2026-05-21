"""Audio engine: sounddevice OutputStream + unified set_param() interface."""

import numpy as np
from typing import Optional, Dict, List, Any

try:
    import sounddevice as sd
    _SD_AVAILABLE = True
except ImportError:
    _SD_AVAILABLE = False

from .voices import DroneVoice, PadVoice, PercVoice, SparkleVoice


class SynthEngine:
    """Manages a sounddevice output stream and routes set_param() to voices.

    Usage:
        engine = SynthEngine()
        engine.start()
        engine.set_param("drone.freq", 80.0)
        engine.set_param("pad.mul", 0.25)
        engine.trigger("perc")
        engine.stop()

    Runs in silent mode if sounddevice is not installed (for testing).
    """

    VOICE_CLASSES = {
        "drone":   DroneVoice,
        "pad":     PadVoice,
        "perc":    PercVoice,
        "sparkle": SparkleVoice,
    }

    def __init__(
        self,
        sample_rate: int = 44100,
        buffer_size: int = 256,
        active_voices: Optional[List[str]] = None,
    ):
        self._sr = sample_rate
        self._buf = buffer_size
        self._active_voice_names = active_voices or list(self.VOICE_CLASSES)
        self._voices: Dict[str, Any] = {}
        self._stream = None
        self._running = False
        self._mix = np.zeros((buffer_size, 2), dtype=np.float32)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._build_voices()

        if not _SD_AVAILABLE:
            print("[SynthEngine] sounddevice not available — silent mode")
            self._running = True
            return

        self._stream = sd.OutputStream(
            samplerate=self._sr,
            blocksize=self._buf,
            channels=2,
            dtype="float32",
            callback=self._callback,
            latency="low",
        )
        self._stream.start()
        self._running = True
        print(f"[SynthEngine] Started — sr={self._sr}, buf={self._buf}, "
              f"voices={list(self._voices)}")

    def stop(self) -> None:
        self._running = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------

    def set_param(self, path: str, value: float) -> bool:
        """Set a voice parameter. Format: 'voice_name.param_name'."""
        parts = path.split(".", 1)
        if len(parts) != 2:
            return False
        voice_name, param = parts
        voice = self._voices.get(voice_name)
        if voice is None:
            return False
        return voice.set(param, float(value))

    def trigger(self, voice_name: str, **kwargs) -> None:
        """Fire a one-shot event on a voice (perc hit, sparkle burst)."""
        voice = self._voices.get(voice_name)
        if voice is None:
            return
        if hasattr(voice, "trigger"):
            voice.trigger(**kwargs)
        elif hasattr(voice, "hit"):
            voice.hit(**kwargs)

    def get_voice(self, name: str) -> Optional[Any]:
        return self._voices.get(name)

    @property
    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_voices(self) -> None:
        for name in self._active_voice_names:
            cls = self.VOICE_CLASSES.get(name)
            if cls:
                self._voices[name] = cls(sr=self._sr, buf=self._buf)

    def _callback(self, outdata: np.ndarray, frames: int,
                  time_info: Any, status: Any) -> None:
        self._mix[:] = 0.0
        for voice in self._voices.values():
            self._mix += voice.generate()
        # Soft clip
        np.tanh(self._mix, out=self._mix)
        outdata[:] = self._mix

    def __repr__(self) -> str:
        voices = ", ".join(self._voices) or "none"
        return (f"SynthEngine(sr={self._sr}, buf={self._buf}, "
                f"voices=[{voices}], running={self._running})")
