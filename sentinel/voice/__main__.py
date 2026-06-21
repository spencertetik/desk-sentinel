"""Entry point for the Desk Sentinel voice agent.

Usage:
    python -m sentinel.voice [--config PATH]
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
log = logging.getLogger("desk_sentinel.voice")


def main() -> None:
    parser = argparse.ArgumentParser(description="Desk Sentinel Voice Agent")
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config.yaml (default: config.yaml in cwd)",
    )
    args = parser.parse_args()

    # Load config
    from sentinel.config import load_config
    cfg_path = Path(args.config)
    if not cfg_path.exists():
        log.error("Config file not found: %s", cfg_path)
        sys.exit(1)

    cfg = load_config(cfg_path)
    voice_cfg = cfg.voice

    # Open the store read-only (WAL mode allows concurrent readers)
    from sentinel.store import Store
    db_path = Path(cfg.db_path)
    if not db_path.exists():
        log.warning("DB not found at %s — stats will be empty", db_path)

    store = Store(db_path)

    # Build and run the agent
    from sentinel.voice.agent import VoiceAgent
    agent = VoiceAgent(store=store, config=voice_cfg)

    try:
        agent.run()
    finally:
        store.close()


if __name__ == "__main__":
    main()
