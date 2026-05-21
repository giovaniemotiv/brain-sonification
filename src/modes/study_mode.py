"""Study mode: calibration, full modular pipeline, synchronized logging."""

import time
from typing import Dict, Any, List, Optional

from ..acquisition.lsl_inlet import discover_emotiv_streams, LSLInlet, lsl_available
from ..processing.smoothing import MultiChannelSmoother
from ..processing.normalizer import BaselineCalibrator
from ..processing.mapper import MappingEngine
from ..synthesis.engine import SynthEngine
from ..logging_.session import SessionRecorder


class StudyMode:
    """Full research pipeline with calibration, configurable mapping, and session logging.

    Config example (configs/study/faa_demo.yaml):
        mode: study
        calibration_seconds: 60
        streams: [bandpower, performance]
        smoothing_alpha: 0.25
        mapping:
          bandpower:
            AF3.alpha: {target: drone.pan, range: [-1, 1], curve: linear}
          events:
            alpha_spike: {source: alpha, threshold: 1.5, trigger: sparkle, cooldown: 2.0}
        logging:
          enabled: true
          format: hdf5
          save_audio: true
    """

    def __init__(self, config: Dict[str, Any], subject_id: str = ""):
        self.config = config
        self.subject_id = subject_id

        audio_cfg = config.get("audio", {})
        voices = config.get("voices", ["drone", "pad", "perc", "sparkle"])
        self.engine = SynthEngine(
            sample_rate=audio_cfg.get("sample_rate", 44100),
            buffer_size=audio_cfg.get("buffer_size", 256),
            active_voices=voices,
        )

        cal_secs = config.get("calibration_seconds", 60.0)
        self._calibrator = BaselineCalibrator(duration_seconds=cal_secs)
        self._smoother = MultiChannelSmoother(alpha=config.get("smoothing_alpha", 0.25))
        self._mapper = MappingEngine.from_config(config.get("mapping", {}))

        log_cfg = config.get("logging", {})
        self._recorder: Optional[SessionRecorder] = None
        if log_cfg.get("enabled", True):
            self._recorder = SessionRecorder(
                subject_id=subject_id,
                config=config,
                save_audio=log_cfg.get("save_audio", True),
                format_=log_cfg.get("format", "hdf5"),
            )

        self._inlets: Dict[str, LSLInlet] = {}
        self._wanted_streams: List[str] = config.get("streams", ["bandpower", "performance"])
        self._running = False
        self._tick_rate = config.get("tick_rate_hz", 20)

    def start(self) -> None:
        self.engine.start()
        self._connect_streams()

        if self._recorder:
            self._recorder.start()

        self._run_calibration()
        self._running = True
        print("[Study] Calibration complete. Starting session...")
        self._run_loop()

    def _connect_streams(self) -> None:
        if not lsl_available():
            print("[Study] pylsl not available — audio-only mode")
            return
        print("[Study] Discovering Emotiv streams (5s timeout)...")
        found = discover_emotiv_streams(timeout=5.0)
        for category, info in found.items():
            if category in self._wanted_streams:
                inlet = LSLInlet(info)
                inlet.start()
                self._inlets[category] = inlet
                print(f"[Study] Connected: {inlet}")
        if not found:
            print("[Study] No Emotiv streams found — audio-only mode")

    def _run_calibration(self) -> None:
        if not self._inlets:
            return
        dur = self._calibrator.duration
        print(f"[Study] Calibration: please relax for {dur:.0f} seconds...")
        self._calibrator.start()
        while self._calibrator.is_collecting:
            data = self._collect_latest_raw()
            if data:
                self._calibrator.add_sample(data)
            progress = self._calibrator.progress * 100
            print(f"\r[Study] Calibrating... {progress:.0f}%", end="", flush=True)
            time.sleep(0.1)
        self._calibrator.finish()
        print(f"\n[Study] Baseline captured: {len(self._calibrator.baseline_stats)} channels")
        for ch, stats in list(self._calibrator.baseline_stats.items())[:5]:
            print(f"  {ch}: mean={stats['mean']:.4f}, std={stats['std']:.4f}")

    def _run_loop(self) -> None:
        interval = 1.0 / self._tick_rate
        try:
            while self._running:
                t0 = time.monotonic()
                raw = self._collect_latest_raw()
                if raw:
                    smoothed = self._smoother.update(raw)
                    normalized = self._calibrator.normalize_to_range(smoothed)

                    calls = self._mapper.process(normalized, now=t0)
                    for path, value in calls:
                        self.engine.set_param(path, value)

                    for trigger in self._mapper.get_pending_triggers():
                        self.engine.trigger(trigger)

                    if self._recorder:
                        self._recorder.log_sample(raw, normalized, t0)

                    self._print_status(normalized)

                elapsed = time.monotonic() - t0
                wait = interval - elapsed
                if wait > 0:
                    time.sleep(wait)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def _collect_latest_raw(self) -> Dict[str, float]:
        data = {}
        for category, inlet in self._inlets.items():
            result = inlet.get_latest()
            if result:
                sample, timestamp = result
                # Flatten sample with category prefix
                for i, v in enumerate(sample):
                    data[f"{category}[{i}]"] = v
        return data

    def _print_status(self, normalized: Dict[str, float]) -> None:
        if not normalized:
            return
        items = list(normalized.items())[:4]
        parts = "  ".join(f"{k}={v:.2f}" for k, v in items)
        print(f"\r[Study] {parts}", end="", flush=True)

    def stop(self) -> None:
        self._running = False
        for inlet in self._inlets.values():
            inlet.stop()
        if self._recorder:
            self._recorder.stop()
        self.engine.stop()
        print("\n[Study] Session ended.")
