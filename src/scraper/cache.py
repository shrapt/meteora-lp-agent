"""Cache scraped data locally as JSON files."""

from __future__ import annotations

import json
import time
from pathlib import Path

from src.common.config import CACHE_DIR
from src.common.logger import get_logger

log = get_logger(__name__)


def _cache_path(category: str, key: str) -> Path:
    d = CACHE_DIR / category
    d.mkdir(parents=True, exist_ok=True)
    safe_key = key.replace("/", "_").replace("\\", "_")
    return d / f"{safe_key}.json"


def cache_get(category: str, key: str, max_age_hours: float = 4.0) -> dict | None:
    """Load from cache if fresh enough."""
    path = _cache_path(category, key)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        cached_at = data.get("_cached_at", 0)
        age_hours = (time.time() - cached_at) / 3600
        if age_hours > max_age_hours:
            return None
        return data
    except Exception as e:
        log.warning("Cache read error for %s/%s: %s", category, key, e)
        return None


def cache_set(category: str, key: str, data: dict) -> None:
    """Write data to cache with timestamp."""
    data["_cached_at"] = time.time()
    path = _cache_path(category, key)
    path.write_text(json.dumps(data, indent=2, default=str))


def cache_list(category: str) -> list[str]:
    """List all cached keys in a category."""
    d = CACHE_DIR / category
    if not d.exists():
        return []
    return [p.stem for p in d.glob("*.json")]
