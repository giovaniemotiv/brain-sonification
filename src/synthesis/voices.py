"""Synthesis voices — numpy/scipy DSP, no external audio library required."""

import numpy as np
from scipy.signal import lfilter

_TWO_PI = 2.0 * np.pi


# ---------------------------------------------------------------------------
# DSP helpers
# ---------------------------------------------------------------------------

def _lpf_coeffs(cutoff_hz: float, sr: int):
    """First-order lowpass IIR coefficients (b, a) for scipy.lfilter."""
    fc = min(max(float(cutoff_hz), 5.0), sr * 0.49)
    k = np.exp(-_TWO_PI * fc / sr)
    return np.array([1.0 - k]), np.array([1.0, -k])


def _bpf_coeffs(center_hz: float, q: float, sr: int):
    """Second-order bandpass IIR (b, a) via bilinear transform."""
    fc = min(max(float(center_hz), 20.0), sr * 0.49)
    w0 = _TWO_PI * fc / sr
    alpha = np.sin(w0) / (2.0 * max(q, 0.1))
    b0 = alpha
    b1 = 0.0
    b2 = -alpha
    a0 = 1.0 + alpha
    a1 = -2.0 * np.cos(w0)
    a2 = 1.0 - alpha
    return (np.array([b0 / a0, b1 / a0, b2 / a0]),
            np.array([1.0, a1 / a0, a2 / a0]))


def _saw_block(phase: float, freq: float, n: int, sr: int):
    """Generate n sawtooth samples via phase accumulator. Returns (samples, new_phase)."""
    phases = (phase + (freq / sr) * np.arange(n, dtype=np.float64)) % 1.0
    new_phase = float((phases[-1] + freq / sr) % 1.0)
    return (2.0 * phases - 1.0).astype(np.float32), new_phase


def _sine_block(phase: float, freq: float, n: int, sr: int):
    """Generate n sine samples. Returns (samples, new_phase)."""
    phases = (phase + (freq / sr) * np.arange(n, dtype=np.float64)) % 1.0
    new_phase = float((phases[-1] + freq / sr) % 1.0)
    return np.sin(_TWO_PI * phases).astype(np.float32), new_phase


def _pan_stereo(mono: np.ndarray, pan: float) -> np.ndarray:
    """Constant-power pan. pan in [-1, 1]. Returns (n, 2) float32 array."""
    angle = (float(pan) + 1.0) * np.pi / 4.0
    l_gain = float(np.cos(angle))
    r_gain = float(np.sin(angle))
    return np.column_stack([mono * l_gain, mono * r_gain]).astype(np.float32)


class _Smooth:
    """Per-block exponential parameter smoother. Thread-safe via GIL."""
    __slots__ = ("target", "current", "_k")

    def __init__(self, value: float, smooth_ms: float = 50.0, sr: int = 44100):
        self.target = float(value)
        self.current = float(value)
        self._k = smooth_ms * sr / 1000.0  # time constant in samples

    def set(self, value: float) -> None:
        self.target = float(value)

    def advance(self, n_frames: int) -> float:
        if self._k > 0:
            alpha = 1.0 - np.exp(-n_frames / self._k)
            self.current += (self.target - self.current) * alpha
        else:
            self.current = self.target
        return self.current


# ---------------------------------------------------------------------------
# Voices
# ---------------------------------------------------------------------------

class DroneVoice:
    """Three detuned sawtooth oscillators through a first-order lowpass.

    Params: freq, detune, cutoff, pan, mul
    """

    def __init__(self, sr: int = 44100, buf: int = 256):
        self._sr, self._n = sr, buf
        self._freq   = _Smooth(80.0,   500.0, sr)
        self._detune = _Smooth(4.0,    200.0, sr)
        self._cutoff = _Smooth(800.0,  300.0, sr)
        self._pan    = _Smooth(0.0,    100.0, sr)
        self._mul    = _Smooth(0.3,    200.0, sr)

        self._phases = [0.0, 0.0, 0.0]
        self._zi = np.zeros(1, dtype=np.float64)
        self._last_cutoff = -1.0
        self._b, self._a = _lpf_coeffs(800.0, sr)
        self._out = np.zeros((buf, 2), dtype=np.float32)

    def set(self, param: str, value: float) -> bool:
        p = {"freq": self._freq, "detune": self._detune, "cutoff": self._cutoff,
             "pan": self._pan, "mul": self._mul}
        if param in p:
            p[param].set(value)
            return True
        return False

    def generate(self) -> np.ndarray:
        n, sr = self._n, self._sr
        freq   = self._freq.advance(n)
        detune = self._detune.advance(n)
        cutoff = self._cutoff.advance(n)
        pan    = self._pan.advance(n)
        mul    = self._mul.advance(n)

        d = detune / 1000.0
        freqs = [freq, freq * (1.0 + d), freq * (1.0 - d * 0.7)]

        mix = np.zeros(n, dtype=np.float64)
        for i, f in enumerate(freqs):
            saw, self._phases[i] = _saw_block(self._phases[i], f, n, sr)
            mix += saw
        mix /= len(freqs)

        if abs(cutoff - self._last_cutoff) > 0.5:
            self._b, self._a = _lpf_coeffs(cutoff, sr)
            self._last_cutoff = cutoff

        filtered, self._zi = lfilter(self._b, self._a, mix, zi=self._zi)
        mono = (filtered * mul).astype(np.float32)
        self._out[:] = _pan_stereo(mono, pan)
        return self._out


class PadVoice:
    """Additive synthesis: 5 sine harmonics with LFO amplitude modulation.

    Params: freq, mod_rate, mod_depth, pan, mul
    """

    def __init__(self, sr: int = 44100, buf: int = 256):
        self._sr, self._n = sr, buf
        self._freq      = _Smooth(220.0, 1000.0, sr)
        self._mod_rate  = _Smooth(0.2,   200.0,  sr)
        self._mod_depth = _Smooth(0.3,   200.0,  sr)
        self._pan       = _Smooth(0.0,   200.0,  sr)
        self._mul       = _Smooth(0.25,  500.0,  sr)

        # Harmonic oscillator phases (up to 5 harmonics)
        self._phases = [0.0] * 5
        self._lfo_phase = 0.0
        self._out = np.zeros((buf, 2), dtype=np.float32)

    def set(self, param: str, value: float) -> bool:
        p = {"freq": self._freq, "mod_rate": self._mod_rate,
             "mod_depth": self._mod_depth, "pan": self._pan, "mul": self._mul}
        if param in p:
            p[param].set(value)
            return True
        return False

    def generate(self) -> np.ndarray:
        n, sr = self._n, self._sr
        freq      = self._freq.advance(n)
        mod_rate  = self._mod_rate.advance(n)
        mod_depth = self._mod_depth.advance(n)
        pan       = self._pan.advance(n)
        mul       = self._mul.advance(n)

        # LFO (tremolo)
        lfo, self._lfo_phase = _sine_block(self._lfo_phase, mod_rate, n, sr)
        envelope = 1.0 - mod_depth + lfo * mod_depth

        # Additive harmonics with 1/harmonic amplitude
        mix = np.zeros(n, dtype=np.float32)
        for i in range(5):
            h = i + 1
            h_freq = freq * h
            if h_freq >= sr * 0.49:
                break
            sine, self._phases[i] = _sine_block(self._phases[i], h_freq, n, sr)
            mix += sine / h

        mix *= envelope * mul * 0.4
        self._out[:] = _pan_stereo(mix, pan)
        return self._out


class PercVoice:
    """White noise through a resonant bandpass filter with exponential decay.

    Call trigger() to fire a hit.
    Params: center_freq, resonance, decay, pan, mul
    """

    def __init__(self, sr: int = 44100, buf: int = 256):
        self._sr, self._n = sr, buf
        self._center_freq = _Smooth(400.0, 20.0,  sr)
        self._resonance   = _Smooth(4.0,   20.0,  sr)
        self._decay       = _Smooth(0.3,   100.0, sr)
        self._pan         = _Smooth(0.0,   100.0, sr)
        self._mul         = _Smooth(0.0,   100.0, sr)

        self._env = 0.0          # current envelope value (0-1)
        self._triggered = False  # flag set by trigger(), read in generate()
        self._zi = np.zeros(2, dtype=np.float64)
        self._last_center = -1.0
        self._last_q = -1.0
        self._b, self._a = _bpf_coeffs(400.0, 4.0, sr)
        self._out = np.zeros((buf, 2), dtype=np.float32)

    def trigger(self, mul: float = 0.6) -> None:
        self._mul.set(mul)
        self._triggered = True

    def set(self, param: str, value: float) -> bool:
        p = {"center_freq": self._center_freq, "resonance": self._resonance,
             "decay": self._decay, "pan": self._pan, "mul": self._mul}
        if param in p:
            p[param].set(value)
            return True
        return False

    def generate(self) -> np.ndarray:
        n, sr = self._n, self._sr
        center = self._center_freq.advance(n)
        q      = self._resonance.advance(n)
        decay  = self._decay.advance(n)
        pan    = self._pan.advance(n)
        mul    = self._mul.advance(n)

        if self._triggered:
            self._env = 1.0
            self._triggered = False

        if self._env < 1e-6:
            self._out[:] = 0.0
            return self._out

        # Recompute filter if params changed
        if abs(center - self._last_center) > 0.5 or abs(q - self._last_q) > 0.01:
            self._b, self._a = _bpf_coeffs(center, q, sr)
            self._last_center = center
            self._last_q = q

        noise = np.random.randn(n).astype(np.float32) * 0.5
        filtered, self._zi = lfilter(self._b, self._a, noise, zi=self._zi)

        decay_coeff = float(np.exp(-1.0 / max(decay * sr, 1.0)))
        env_buf = self._env * (decay_coeff ** np.arange(n))
        self._env *= decay_coeff ** n

        mono = (filtered * env_buf * mul).astype(np.float32)
        self._out[:] = _pan_stereo(mono, pan)
        return self._out


class SparkleVoice:
    """FM synthesis: carrier modulated by a sine at carrier_freq * mod_ratio.

    Params: carrier_freq, mod_ratio, mod_index, pan, mul
    """

    def __init__(self, sr: int = 44100, buf: int = 256):
        self._sr, self._n = sr, buf
        self._carrier_freq = _Smooth(880.0, 50.0,  sr)
        self._mod_ratio    = _Smooth(2.0,   100.0, sr)
        self._mod_index    = _Smooth(5.0,   100.0, sr)
        self._pan          = _Smooth(0.0,   50.0,  sr)
        self._mul          = _Smooth(0.15,  100.0, sr)

        self._carrier_phase  = 0.0
        self._mod_phase      = 0.0
        self._env = 0.0
        self._triggered = False
        self._out = np.zeros((buf, 2), dtype=np.float32)

    def hit(self, freq: float = 880.0, mul: float = 0.3) -> None:
        self._carrier_freq.set(freq)
        self._mul.set(mul)
        self._triggered = True

    def trigger(self, **kwargs) -> None:
        self.hit(**kwargs)

    def set(self, param: str, value: float) -> bool:
        p = {"carrier_freq": self._carrier_freq, "mod_ratio": self._mod_ratio,
             "mod_index": self._mod_index, "pan": self._pan, "mul": self._mul}
        if param in p:
            p[param].set(value)
            return True
        return False

    def generate(self) -> np.ndarray:
        n, sr = self._n, self._sr
        carrier_freq = self._carrier_freq.advance(n)
        mod_ratio    = self._mod_ratio.advance(n)
        mod_index    = self._mod_index.advance(n)
        pan          = self._pan.advance(n)
        mul          = self._mul.advance(n)

        if self._triggered:
            self._env = 1.0
            self._triggered = False

        if self._env < 1e-6:
            self._out[:] = 0.0
            return self._out

        mod_freq = carrier_freq * mod_ratio
        modulator, self._mod_phase = _sine_block(self._mod_phase, mod_freq, n, sr)

        # FM: carrier phase is perturbed by modulator
        t = np.arange(n, dtype=np.float64) / sr
        carrier_phases = (self._carrier_phase + carrier_freq * t +
                          mod_index * modulator / (mod_freq or 1.0)) % 1.0
        self._carrier_phase = float((carrier_phases[-1] + carrier_freq / sr) % 1.0)
        fm = np.sin(_TWO_PI * carrier_phases).astype(np.float32)

        decay_coeff = float(np.exp(-1.0 / max(0.2 * sr, 1.0)))
        env_buf = self._env * (decay_coeff ** np.arange(n))
        self._env *= decay_coeff ** n

        mono = (fm * env_buf * mul).astype(np.float32)
        self._out[:] = _pan_stereo(mono, pan)
        return self._out
