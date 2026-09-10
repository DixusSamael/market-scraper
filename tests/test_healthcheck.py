import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

from src import healthcheck
from src import mexc_futures_scraper as scanner


def test_health_requires_recent_scan(tmp_path, monkeypatch):
    marker = tmp_path / "health"
    monkeypatch.setattr(healthcheck, "HEALTH_PATH", marker)
    monkeypatch.setattr(healthcheck.time, "time", lambda: 1000)
    assert not healthcheck.is_healthy()
    marker.touch()
    os.utime(marker, (950, 950))
    assert healthcheck.is_healthy()
    os.utime(marker, (700, 700))
    assert not healthcheck.is_healthy()


def test_completed_scan_updates_health(tmp_path, monkeypatch):
    marker = tmp_path / "health"
    monkeypatch.setattr(scanner, "HEALTH_PATH", marker)
    monkeypatch.setattr(scanner, "scrape", lambda: ([], set()))
    monkeypatch.setattr(scanner, "deliver_alerts", AsyncMock())
    asyncio.run(scanner.scrape_loop(SimpleNamespace(application=None)))
    assert marker.exists()
