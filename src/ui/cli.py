"""CLI argument parsing and status utilities."""

import argparse
import sys
from typing import Dict, Any

try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="brain-sonification",
        description="EEG → Audio: convert Emotiv brainwave data into sound",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --mode music --preset ambient
  python main.py --mode music --preset melodic
  python main.py --mode music --preset rhythmic
  python main.py --mode study --config configs/study/faa_demo.yaml --subject S01
  python main.py --mode study --config configs/study/default.yaml
""",
    )
    parser.add_argument(
        "--mode",
        choices=["music", "study"],
        required=True,
        help="Run mode: 'music' (automatic preset) or 'study' (research pipeline)",
    )
    parser.add_argument(
        "--preset",
        choices=["ambient", "melodic", "rhythmic"],
        default="ambient",
        help="Music preset to use (only for --mode music)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to YAML config file (required for --mode study)",
    )
    parser.add_argument(
        "--subject",
        type=str,
        default="",
        help="Subject ID for session logging (study mode)",
    )
    parser.add_argument(
        "--list-streams",
        action="store_true",
        help="Discover and print available LSL streams, then exit",
    )
    return parser


def load_config(path: str) -> Dict[str, Any]:
    if not _YAML_AVAILABLE:
        print("ERROR: pyyaml is not installed. Run: pip install pyyaml")
        sys.exit(1)
    try:
        with open(path, "r") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        print(f"ERROR: Config file not found: {path}")
        sys.exit(1)


def load_music_preset(preset_name: str) -> Dict[str, Any]:
    path = f"configs/music/{preset_name}.yaml"
    return load_config(path)


def print_streams() -> None:
    """Discover and print all available LSL streams."""
    from ..acquisition.lsl_inlet import discover_streams, lsl_available
    if not lsl_available():
        print("pylsl is not installed. Run: pip install pylsl")
        return
    print("Searching for LSL streams (5 second timeout)...")
    streams = discover_streams(timeout=5.0)
    if not streams:
        print("No LSL streams found.")
        return
    print(f"Found {len(streams)} stream(s):")
    for info in streams:
        print(f"  [{info.type()}] {info.name()} — {info.channel_count()} ch @ {info.nominal_srate()} Hz")
