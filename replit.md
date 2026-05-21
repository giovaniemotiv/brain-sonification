# Brain Sonification

A Python CLI tool that converts Emotiv EEG data into real-time audio. Two modes: **music** (immersive presets) and **study** (research-grade, configurable).

## Project type

CLI tool (no web frontend). Requires:
- Emotiv Pro + Emotiv Launcher with LSL output (for live data)
- Local audio output device

Because it needs real hardware (EEG headset + audio), it cannot run interactively inside the Replit container. The Replit setup verifies the codebase is healthy by running the unit test suite.

## Replit setup

- Language: Python 3.12
- Dependencies installed from `requirements.txt` via the package manager
- Workflow `Start application` runs the hardware-free unit tests (`tests/test_mapper.py` and `tests/test_smoothing.py`) as a sanity check — 32 tests pass

## Running locally (with hardware)

```bash
python main.py --mode music --preset ambient
python main.py --mode study --config configs/study/default.yaml --subject S01
python main.py --list-streams
```

See `README.md` for full usage and config documentation.

## Project layout

```
src/
  acquisition/    LSL stream discovery + thread-safe inlets
  processing/     Smoothing, baseline calibration, parameter mapping
  synthesis/      sounddevice audio engine, voices, musical helpers
  modes/          music_mode.py and study_mode.py run loops
  logging_/       Session recording (JSONL / HDF5 + YAML snapshot)
  ui/             CLI argument parser
configs/          music/ and study/ YAML presets
tests/            pytest suite (mapper, smoothing, acquisition)
```

## User preferences

(none recorded yet)
