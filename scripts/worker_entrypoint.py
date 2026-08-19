"""PyInstaller console entrypoint for the packaged M1 worker."""

from __future__ import annotations

from ai_edit_machine.worker import main


if __name__ == "__main__":
    raise SystemExit(main())
