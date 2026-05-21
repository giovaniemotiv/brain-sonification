# Brain Sonification

Convert Emotiv EEG data into audio — real-time. Two modes: **music** (immersive, automatic) and **study** (research-grade, fully configurable).

## Requirements

- Python 3.10+
- Emotiv Pro + Emotiv Launcher with LSL output enabled (for live data)
- Audio output device

## Install

```bash
cd D:\src\brain-sonification
pip install -r requirements.txt
```

> **pyo on Windows:** if the pip install fails for pyo, download the prebuilt wheel from http://ajaxsoundstudio.com/software/pyo/

## Quick start

### Music mode

```bash
# Atmospheric drone/pad driven by alpha waves
python main.py --mode music --preset ambient

# Tonal melodies driven by brain state
python main.py --mode music --preset melodic

# Generative electronic — engagement and stress drive rhythm
python main.py --mode music --preset rhythmic
```

Press `Ctrl+C` to stop.

### Study mode

```bash
# Default — simple one-band-per-voice mapping, 30s calibration
python main.py --mode study --config configs/study/default.yaml --subject S01

# Frontal Alpha Asymmetry demo
python main.py --mode study --config configs/study/faa_demo.yaml --subject S01

# Spectral mapping — hear the raw EEG frequency bands
python main.py --mode study --config configs/study/spectral.yaml
```

### Discover available LSL streams

```bash
python main.py --list-streams
```

## Emotiv setup

1. Open Emotiv Launcher and start a session with your headset
2. In Emotiv Pro settings, enable **LSL output** for:
   - `EmotivDataStream-EEG`
   - `EmotivDataStream-Band Power`
   - `EmotivDataStream-Performance Metrics`
3. Run `python main.py --list-streams` to verify streams appear

## Run tests (no hardware needed)

```bash
python -m pytest tests/ -v
```

The acquisition test requires `pylsl` and creates a synthetic LSL stream locally. The mapper and smoother tests need no audio or hardware.

## Project structure

```
src/
  acquisition/    LSL stream discovery + thread-safe inlets
  processing/     Smoothing, baseline calibration, parameter mapping
  synthesis/      pyo audio engine, voice definitions, musical helpers
  modes/          music_mode.py and study_mode.py run loops
  logging_/       Session recording (JSONL or HDF5 + YAML config snapshot)
  ui/             CLI argument parser

configs/
  music/          ambient.yaml, melodic.yaml, rhythmic.yaml
  study/          default.yaml, faa_demo.yaml, spectral.yaml

sessions/         Auto-created per run (timestamped folders)
```

## Creating a custom study config

Copy `configs/study/default.yaml` and edit the `mapping` section. Each rule is:

```yaml
mapping:
  bandpower:
    source_key:
      target: voice.parameter    # e.g. drone.cutoff, pad.freq, sparkle.mul
      range: [min, max]          # output range for this parameter
      curve: linear              # linear | exponential | logarithmic | scurve
      invert: false              # flip the mapping direction
  events:
    my_event:
      source: source_key
      threshold: 1.5             # z-score std devs above baseline
      direction: above           # "above" or "below"
      trigger: sparkle           # voice name to trigger
      cooldown: 2.0              # seconds before re-firing
```

Available voices and their parameters:

| Voice   | Parameters                                        |
|---------|---------------------------------------------------|
| drone   | freq, detune, cutoff, resonance, pan, mul         |
| pad     | freq, mod_rate, mod_depth, pan, mul               |
| perc    | center_freq, resonance, decay, pan, mul           |
| sparkle | carrier_freq, mod_ratio, mod_index, pan, mul      |

## Session data

Each study session saves to `sessions/YYYY-MM-DD_HHMMSS_SubjectID/`:

- `metadata.json` — subject ID, start time, mode
- `config.yaml` — exact config used (for reproducibility)
- `raw_data.jsonl` — raw EEG values per tick
- `normalized.jsonl` — baseline-normalized values per tick
