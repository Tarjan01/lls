"""Compatibility entrypoint for the Reverse Detective demo."""

from reverse_detective.app import main, run_game

__all__ = ["main", "run_game"]


if __name__ == "__main__":
    main()

