"""
Bidirectional Email Interface — MVP
Configuration loader module.
"""

import json
import os
import logging

logger = logging.getLogger("app")

DEFAULT_CONFIG = {
    "endpoint_id": "endpoint-1",
    "email_address": "",
    "email_password": "",
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 587,
    "imap_host": "imap.gmail.com",
    "imap_port": 993,
    "peers": [],
    "polling_interval_seconds": 10,
    "ack_timeout_seconds": 60,
    "retry_count": 3,
    "retry_interval_seconds": 30,
    "protocol_version": "1.0",
    "email_max_lifetime_days": 30,
}


def load_config(config_path: str = "config.json") -> dict:
    """Load and validate configuration from a JSON file."""
    if not os.path.exists(config_path):
        logger.error("Configuration file not found: %s", config_path)
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_path, "r") as f:
        config = json.load(f)

    # Merge with defaults
    merged = {**DEFAULT_CONFIG, **config}

    # Validate required fields
    required = ["endpoint_id", "email_address", "email_password", "smtp_host", "imap_host"]
    missing = [k for k in required if not merged.get(k)]
    if missing:
        logger.error("Missing required config fields: %s", missing)
        raise ValueError(f"Missing required configuration fields: {missing}")

    if not merged.get("peers"):
        logger.warning("No peers configured — sending will not be possible until peers are added.")

    logger.info("Configuration loaded for endpoint '%s'", merged["endpoint_id"])
    return merged
