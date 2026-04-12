"""Console entry for PyInstaller TUI-only builds (invokes ``--tui``)."""

from __future__ import annotations

from src.main import main
from src.runtime_opus import load_discord_opus_if_frozen

load_discord_opus_if_frozen()


if __name__ == "__main__":
    raise SystemExit(main(["--tui"]))
