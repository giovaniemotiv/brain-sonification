"""Scale/chord helpers for music mode. No pyo dependency."""

import math
from typing import List

# Semitone intervals from root for each scale
SCALES = {
    "major":             [0, 2, 4, 5, 7, 9, 11],
    "minor":             [0, 2, 3, 5, 7, 8, 10],
    "pentatonic_major":  [0, 2, 4, 7, 9],
    "pentatonic_minor":  [0, 3, 5, 7, 10],
    "dorian":            [0, 2, 3, 5, 7, 9, 10],
    "phrygian":          [0, 1, 3, 5, 7, 8, 10],
    "lydian":            [0, 2, 4, 6, 7, 9, 11],
    "mixolydian":        [0, 2, 4, 5, 7, 9, 10],
    "whole_tone":        [0, 2, 4, 6, 8, 10],
    "chromatic":         list(range(12)),
}

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

CHORD_PROGRESSIONS = {
    "ambient":  [0, 4, 5, 3],   # I - V - VI - IV (relative to scale degrees)
    "tension":  [0, 2, 4, 6],
    "resolve":  [6, 4, 2, 0],
    "loop":     [0, 3, 4, 3],
}


def note_to_semitone(note_name: str) -> int:
    """Convert note name like 'C', 'A#' to semitone offset 0-11."""
    note_name = note_name.strip().upper()
    if note_name not in NOTE_NAMES:
        raise ValueError(f"Unknown note: {note_name!r}")
    return NOTE_NAMES.index(note_name)


def scale_to_freqs(root: str, scale_name: str, octaves: int = 3, base_octave: int = 3) -> List[float]:
    """Return a list of frequencies for the given scale across multiple octaves.

    Args:
        root: Root note name, e.g. 'C', 'A#'
        scale_name: Key from SCALES dict
        octaves: How many octaves to span
        base_octave: Starting octave (MIDI octave numbering, middle C = octave 4)
    """
    if scale_name not in SCALES:
        raise ValueError(f"Unknown scale: {scale_name!r}. Available: {list(SCALES)}")
    root_semitone = note_to_semitone(root)
    intervals = SCALES[scale_name]
    midi_base = (base_octave + 1) * 12 + root_semitone
    freqs = []
    for octave in range(octaves):
        for interval in intervals:
            midi = midi_base + octave * 12 + interval
            freq = 440.0 * (2.0 ** ((midi - 69) / 12.0))
            freqs.append(round(freq, 3))
    return freqs


def eeg_to_note(value: float, scale_freqs: List[float]) -> float:
    """Map a normalized 0-1 EEG value to a frequency from the scale.

    Uses quantized mapping so output always lands on a valid scale degree.
    """
    value = max(0.0, min(1.0, value))
    idx = int(value * (len(scale_freqs) - 1))
    return scale_freqs[idx]


def eeg_to_note_smooth(value: float, scale_freqs: List[float]) -> float:
    """Map 0-1 to frequency with linear interpolation between scale degrees.

    Produces microtonal glides — good for ambient, less suitable for melodic.
    """
    value = max(0.0, min(1.0, value))
    pos = value * (len(scale_freqs) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(scale_freqs) - 1)
    frac = pos - lo
    return scale_freqs[lo] + frac * (scale_freqs[hi] - scale_freqs[lo])


def progression_step(step: int, scale_freqs: List[float], progression_name: str = "ambient") -> float:
    """Return the root frequency for a chord at a given step in a named progression."""
    prog = CHORD_PROGRESSIONS.get(progression_name, CHORD_PROGRESSIONS["ambient"])
    degree = prog[step % len(prog)]
    idx = degree % len(scale_freqs)
    return scale_freqs[idx]


def bpm_to_seconds(bpm: float) -> float:
    return 60.0 / max(bpm, 1.0)


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * max(0.0, min(1.0, t))
