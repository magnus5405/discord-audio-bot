"""Main orchestrator - Discord client and TUI launcher."""

import asyncio
import logging
import os
from typing import Optional

from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Main entry point for the Discord audio bot."""
    # Load environment variables from .env
    load_dotenv()
    
    # TODO: Initialize Discord client
    # TODO: Start Textual TUI in separate terminal
    # TODO: Run session orchestration loop
    
    logger.info("Discord Audio Bot initialized")
    logger.info("Phase 1: Voice connectivity setup")


if __name__ == "__main__":
    main()
