"""Launcher for the Nexora node-agent FastAPI app."""

from __future__ import annotations

from .api import app, main  # noqa: F401


if __name__ == "__main__":
    main()
