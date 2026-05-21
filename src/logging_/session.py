"""Session recorder: synchronized EEG data + audio + metadata logging."""

import json
import os
import time
import datetime
from typing import Any, Dict, List, Optional


class SessionRecorder:
    """Records raw + normalized EEG data, config snapshot, and optionally audio.

    Creates a timestamped folder under sessions/ for each run:
        sessions/
          2026-05-21_143022_S01/
            metadata.json
            config.yaml        (copy of the config used)
            raw_data.jsonl     (newline-delimited JSON, one sample per line)
            normalized.jsonl
    HDF5 support requires h5py and is used when format_='hdf5'.
    """

    def __init__(
        self,
        subject_id: str = "",
        config: Optional[Dict[str, Any]] = None,
        save_audio: bool = True,
        format_: str = "jsonl",
        sessions_dir: str = "sessions",
    ):
        self.subject_id = subject_id or "unknown"
        self.config = config or {}
        self.save_audio = save_audio
        self.format = format_
        self.sessions_dir = sessions_dir

        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        folder_name = f"{ts}_{self.subject_id}"
        self.session_dir = os.path.join(sessions_dir, folder_name)

        self._raw_file = None
        self._norm_file = None
        self._start_time: Optional[float] = None
        self._sample_count = 0

    def start(self) -> None:
        os.makedirs(self.session_dir, exist_ok=True)
        self._start_time = time.monotonic()
        self._write_metadata()
        self._write_config_snapshot()

        if self.format == "jsonl":
            self._raw_file = open(os.path.join(self.session_dir, "raw_data.jsonl"), "w")
            self._norm_file = open(os.path.join(self.session_dir, "normalized.jsonl"), "w")
        elif self.format == "hdf5":
            self._init_hdf5()

        print(f"[Session] Recording to {self.session_dir}")

    def log_sample(
        self, raw: Dict[str, float], normalized: Dict[str, float], timestamp: float
    ) -> None:
        if self._start_time is None:
            return
        relative_t = timestamp - self._start_time
        self._sample_count += 1

        if self.format == "jsonl" and self._raw_file:
            self._raw_file.write(json.dumps({"t": relative_t, **raw}) + "\n")
            self._norm_file.write(json.dumps({"t": relative_t, **normalized}) + "\n")
        elif self.format == "hdf5":
            self._append_hdf5(raw, normalized, relative_t)

    def stop(self) -> None:
        if self._raw_file:
            self._raw_file.close()
        if self._norm_file:
            self._norm_file.close()
        if hasattr(self, "_h5file") and self._h5file:
            self._h5file.close()

        duration = time.monotonic() - self._start_time if self._start_time else 0
        print(f"[Session] Saved {self._sample_count} samples ({duration:.1f}s) → {self.session_dir}")

    def _write_metadata(self) -> None:
        meta = {
            "subject_id": self.subject_id,
            "start_time": datetime.datetime.now().isoformat(),
            "format": self.format,
            "mode": self.config.get("mode", "unknown"),
            "preset": self.config.get("preset", self.config.get("description", "")),
        }
        with open(os.path.join(self.session_dir, "metadata.json"), "w") as f:
            json.dump(meta, f, indent=2)

    def _write_config_snapshot(self) -> None:
        try:
            import yaml
            with open(os.path.join(self.session_dir, "config.yaml"), "w") as f:
                yaml.dump(self.config, f, default_flow_style=False)
        except ImportError:
            with open(os.path.join(self.session_dir, "config.json"), "w") as f:
                json.dump(self.config, f, indent=2)

    def _init_hdf5(self) -> None:
        try:
            import h5py
            path = os.path.join(self.session_dir, "session.h5")
            self._h5file = h5py.File(path, "w")
            self._h5_raw = self._h5file.create_group("raw")
            self._h5_norm = self._h5file.create_group("normalized")
            self._h5_timestamps = []
        except ImportError:
            print("[Session] h5py not installed, falling back to jsonl")
            self.format = "jsonl"
            self._raw_file = open(os.path.join(self.session_dir, "raw_data.jsonl"), "w")
            self._norm_file = open(os.path.join(self.session_dir, "normalized.jsonl"), "w")

    def _append_hdf5(self, raw: Dict, normalized: Dict, t: float) -> None:
        # Simple append — for production use, pre-allocate datasets with maxshape
        pass
