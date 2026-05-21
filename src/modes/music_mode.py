"""Music mode: preset-driven, fully automatic EEG → music mapping."""

import time
from typing import Dict, Any, Optional

from ..acquisition.lsl_inlet import discover_emotiv_streams, LSLInlet, lsl_available
from ..processing.smoothing import MultiChannelSmoother
from ..processing.normalizer import MinMaxNormalizer
from ..synthesis.engine import SynthEngine
from ..synthesis.musical import scale_to_freqs, eeg_to_note, progression_step, bpm_to_seconds


class MusicMode:
    """Runs the music pipeline: LSL → smooth → normalize → musical mapping → synth.

    All mapping is driven by the preset YAML. No manual controls — fully automatic.

    Config example (configs/music/ambient.yaml):
        mode: music
        preset: ambient
        voices: [drone, pad]
        key: C
        scale: pentatonic_minor
        mapping:
          alpha: atmosphere
          engagement: intensity
          stress: dissonance
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.preset = config.get("preset", "ambient")
        self.key = config.get("key", "C")
        self.scale = config.get("scale", "pentatonic_minor")
        self.mapping = config.get("mapping", {})
        voices = config.get("voices", ["drone", "pad"])

        audio_cfg = config.get("audio", {})
        self.engine = SynthEngine(
            sample_rate=audio_cfg.get("sample_rate", 44100),
            buffer_size=audio_cfg.get("buffer_size", 256),
            active_voices=voices,
        )

        self._smoother = MultiChannelSmoother(alpha=config.get("smoothing_alpha", 0.15))
        self._normalizer = MinMaxNormalizer()
        self._inlets: Dict[str, LSLInlet] = {}
        self._scale_freqs = scale_to_freqs(self.key, self.scale, octaves=3, base_octave=3)
        self._chord_step = 0
        self._last_chord_change = 0.0
        self._chord_interval = bpm_to_seconds(config.get("chord_bpm", 30))
        self._running = False

    def start(self) -> None:
        self.engine.start()
        self._connect_streams()
        self._running = True
        print(f"[Music] Started — preset={self.preset}, key={self.key}, scale={self.scale}")
        print(f"[Music] Active voices: {list(self.engine._voices.keys())}")
        self._run_loop()

    def _connect_streams(self) -> None:
        if not lsl_available():
            print("[Music] pylsl not available — audio-only mode")
            return
        print("[Music] Discovering Emotiv streams (5s timeout)...")
        found = discover_emotiv_streams(timeout=5.0)
        if not found:
            print("[Music] No Emotiv streams found — running in audio-only mode")
            return
        for category, info in found.items():
            inlet = LSLInlet(info)
            inlet.start()
            self._inlets[category] = inlet
            print(f"[Music] Connected: {inlet}")

    def _run_loop(self) -> None:
        try:
            while self._running:
                raw_data = self._collect_latest()
                if raw_data:
                    smoothed = self._smoother.update(raw_data)
                    normalized = self._normalizer.update(smoothed)
                    self._apply_musical_mapping(normalized)
                time.sleep(0.05)  # ~20 Hz update rate
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def _collect_latest(self) -> Dict[str, float]:
        data = {}
        for category, inlet in self._inlets.items():
            result = inlet.get_latest()
            if result:
                sample, _ = result
                if category == "bandpower":
                    data.update(self._parse_bandpower(sample, inlet))
                elif category == "performance":
                    data.update(self._parse_performance(sample, inlet))
        return data

    def _parse_bandpower(self, sample, inlet) -> Dict[str, float]:
        # Emotiv Band Power: channels are theta, alpha_low, alpha_high, beta_low, beta_high, gamma per electrode
        # Flatten to aggregate band values for music mode
        n = len(sample)
        chunk = max(1, n // 6)
        bands = ["theta", "alpha_low", "alpha_high", "beta_low", "beta_high", "gamma"]
        result = {}
        for i, band in enumerate(bands):
            vals = sample[i * chunk: (i + 1) * chunk]
            if vals:
                result[band] = sum(vals) / len(vals)
        # Combine alpha bands
        if "alpha_low" in result and "alpha_high" in result:
            result["alpha"] = (result["alpha_low"] + result["alpha_high"]) / 2.0
        return result

    def _parse_performance(self, sample, inlet) -> Dict[str, float]:
        # Emotiv Performance Metrics: engagement, excitement, stress, relaxation, interest, focus
        labels = ["engagement", "excitement", "stress", "relaxation", "interest", "focus"]
        return {labels[i]: sample[i] for i in range(min(len(labels), len(sample)))}

    def _apply_musical_mapping(self, data: Dict[str, float]) -> None:
        now = time.monotonic()

        # Advance chord progression at configured BPM
        if now - self._last_chord_change >= self._chord_interval:
            self._chord_step += 1
            self._last_chord_change = now

        for eeg_band, musical_concept in self.mapping.items():
            value = data.get(eeg_band)
            if value is None:
                continue

            if musical_concept == "atmosphere":
                # Alpha → drone cutoff + pad mod rate
                cutoff = 200.0 + value * 2000.0
                self.engine.set_param("drone.cutoff", cutoff)
                self.engine.set_param("pad.mod_rate", 0.05 + value * 0.5)

            elif musical_concept == "intensity":
                # Engagement → overall volume + voice blend
                self.engine.set_param("drone.mul", 0.1 + value * 0.3)
                self.engine.set_param("pad.mul", 0.05 + value * 0.25)

            elif musical_concept == "dissonance":
                # Stress → detuning + mod depth
                self.engine.set_param("drone.detune", 1.0 + value * 12.0)
                self.engine.set_param("pad.mod_depth", value * 0.6)

            elif musical_concept == "pitch":
                freq = eeg_to_note(value, self._scale_freqs)
                self.engine.set_param("pad.freq", freq)
                self.engine.set_param("drone.freq", freq / 2.0)

            elif musical_concept == "rhythm":
                bpm = 40 + value * 120
                self._chord_interval = bpm_to_seconds(bpm)

    def stop(self) -> None:
        self._running = False
        for inlet in self._inlets.values():
            inlet.stop()
        self.engine.stop()
        print("[Music] Stopped.")
