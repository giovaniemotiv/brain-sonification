"""Tests for processing/mapper and synthesis/musical — no audio required."""

import pytest
from src.processing.mapper import ParamMapping, MappingEngine, CURVES
from src.synthesis.musical import (
    scale_to_freqs, eeg_to_note, eeg_to_note_smooth,
    progression_step, note_to_semitone, SCALES
)


# --- ParamMapping ---

def test_param_mapping_linear():
    m = ParamMapping("alpha", "drone.cutoff", range_min=200.0, range_max=2000.0, curve="linear")
    assert m.apply(0.0) == pytest.approx(200.0)
    assert m.apply(1.0) == pytest.approx(2000.0)
    assert m.apply(0.5) == pytest.approx(1100.0)


def test_param_mapping_clamps_input():
    m = ParamMapping("x", "y", 0.0, 1.0)
    assert m.apply(-0.5) == pytest.approx(0.0)
    assert m.apply(1.5) == pytest.approx(1.0)


def test_param_mapping_invert():
    m = ParamMapping("x", "y", 0.0, 1.0, invert=True)
    assert m.apply(1.0) == pytest.approx(0.0)
    assert m.apply(0.0) == pytest.approx(1.0)


def test_param_mapping_exponential():
    m = ParamMapping("x", "y", 0.0, 1.0, curve="exponential")
    assert m.apply(0.5) == pytest.approx(0.25)  # 0.5 ** 2


@pytest.mark.parametrize("curve_name", list(CURVES.keys()))
def test_all_curves_produce_valid_range(curve_name):
    m = ParamMapping("x", "y", 0.0, 100.0, curve=curve_name)
    for t in [0.0, 0.25, 0.5, 0.75, 1.0]:
        val = m.apply(t)
        assert 0.0 <= val <= 100.0, f"curve={curve_name}, t={t}, val={val}"


# --- MappingEngine ---

def test_mapping_engine_from_config():
    config = {
        "bandpower": {
            "alpha": {"target": "drone.cutoff", "range": [200, 2000], "curve": "linear"}
        }
    }
    engine = MappingEngine.from_config(config)
    assert len(engine.param_mappings) == 1
    assert engine.param_mappings[0].source_key == "alpha"
    assert engine.param_mappings[0].target_param == "drone.cutoff"


def test_mapping_engine_process():
    config = {
        "perf": {
            "engagement": {"target": "drone.mul", "range": [0.0, 0.5], "curve": "linear"}
        }
    }
    engine = MappingEngine.from_config(config)
    results = engine.process({"engagement": 1.0}, now=0.0)
    assert len(results) == 1
    path, value = results[0]
    assert path == "drone.mul"
    assert value == pytest.approx(0.5)


def test_mapping_engine_ignores_missing_keys():
    config = {"s": {"missing_key": {"target": "x.y", "range": [0, 1]}}}
    engine = MappingEngine.from_config(config)
    results = engine.process({"other_key": 0.5}, now=0.0)
    assert results == []


# --- Musical helpers ---

def test_note_to_semitone():
    assert note_to_semitone("C") == 0
    assert note_to_semitone("A") == 9
    assert note_to_semitone("A#") == 10


def test_scale_to_freqs_length():
    freqs = scale_to_freqs("C", "pentatonic_minor", octaves=2)
    assert len(freqs) == 5 * 2  # 5 notes per octave × 2 octaves


def test_scale_to_freqs_ascending():
    freqs = scale_to_freqs("C", "major", octaves=1)
    assert freqs == sorted(freqs), "Frequencies should be in ascending order"


def test_eeg_to_note_boundaries():
    freqs = scale_to_freqs("A", "pentatonic_minor")
    assert eeg_to_note(0.0, freqs) == freqs[0]
    assert eeg_to_note(1.0, freqs) == freqs[-1]


def test_eeg_to_note_smooth_between_degrees():
    freqs = [100.0, 200.0, 300.0]
    val = eeg_to_note_smooth(0.5, freqs)
    assert 100.0 < val < 300.0


@pytest.mark.parametrize("scale_name", list(SCALES.keys()))
def test_all_scales_produce_freqs(scale_name):
    freqs = scale_to_freqs("C", scale_name, octaves=1)
    assert len(freqs) == len(SCALES[scale_name])
    assert all(f > 0 for f in freqs)
