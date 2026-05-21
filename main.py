"""Entry point for the EEG Sonification Tool.

Usage:
    python main.py --mode music --preset ambient
    python main.py --mode music --preset melodic
    python main.py --mode study --config configs/study/faa_demo.yaml --subject S01
    python main.py --list-streams
"""

import sys
import os

# Allow running from the project root without installing as a package
sys.path.insert(0, os.path.dirname(__file__))

from src.ui.cli import build_parser, load_config, load_music_preset, print_streams


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.list_streams:
        print_streams()
        return

    if args.mode == "music":
        config = load_music_preset(args.preset)
        from src.modes.music_mode import MusicMode
        runner = MusicMode(config)
        runner.start()

    elif args.mode == "study":
        if not args.config:
            parser.error("--config is required for --mode study")
        config = load_config(args.config)
        from src.modes.study_mode import StudyMode
        runner = StudyMode(config, subject_id=args.subject)
        runner.start()


if __name__ == "__main__":
    main()
