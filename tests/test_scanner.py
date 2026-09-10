import asyncio
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from src import mexc_futures_scraper as scanner


CONTRACT = dict(symbol="ABC_USDT", quoteCoin="USDT", settleCoin="USDT", futureType=1,
                state=0, contractSize="0.1")
TICKER = dict(symbol="ABC_USDT", lastPrice="2", amount24="1000000", holdVol="500000",
              riseFallRate="0.6", fundingRate="0.0001")


def test_thresholds_and_contract_units():
    coins, evaluated = scanner.select_gainers([TICKER], [CONTRACT])
    assert evaluated == {"ABC_USDT"}
    assert coins[0]["oi"] == Decimal("100000")
    assert coins[0]["ratio"] == Decimal("0.10")
    assert coins[0]["gain"] == 60
    assert coins[0]["funding"] == Decimal("0.01")


@pytest.mark.parametrize("changes", [dict(riseFallRate="0.5999"), dict(amount24="999999"),
                                    dict(holdVol="499999"), dict(amount24="0")])
def test_below_thresholds(changes):
    assert scanner.select_gainers([TICKER | changes], [CONTRACT]) == ([], {"ABC_USDT"})


@pytest.mark.parametrize("changes", [dict(futureType=2), dict(state=3), dict(settleCoin="BTC"),
                                    dict(quoteCoin="BTC")])
def test_only_active_usdt_perpetuals(changes):
    assert scanner.select_gainers([TICKER], [CONTRACT | changes])[0] == []


@pytest.mark.parametrize("value", [None, "NaN", "Infinity", "bad", "-1"])
def test_invalid_data_does_not_rearm(value):
    assert scanner.select_gainers([TICKER | dict(lastPrice=value)], [CONTRACT]) == ([], set())


def test_sort_and_optional_upper_ratio(monkeypatch):
    high = TICKER | dict(symbol="XYZ_USDT", riseFallRate="1.2", holdVol="10000000")
    contracts = [CONTRACT, CONTRACT | dict(symbol="XYZ_USDT")]
    assert [c["symbol"] for c in scanner.select_gainers([TICKER, high], contracts)[0]] == [
        "XYZ_USDT", "ABC_USDT"]
    monkeypatch.setattr(scanner, "MAX_OI_TURNOVER_RATIO", Decimal("1.5"))
    assert len(scanner.select_gainers([TICKER, high], contracts)[0]) == 1


def test_persistent_delivery_retry_and_reentry(tmp_path, monkeypatch):
    monkeypatch.setattr(scanner, "DB_PATH", str(tmp_path / "scanner.db"))
    scanner.init_db()
    with scanner.get_db() as conn:
        conn.executemany("INSERT INTO telegram_users VALUES (?, ?, ?)",
                         [("1", "one", "today"), ("2", "two", "today")])
    app = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock(side_effect=[None, RuntimeError()])))
    coins, evaluated = scanner.select_gainers([TICKER], [CONTRACT])
    asyncio.run(scanner.deliver_alerts(app, coins, evaluated))
    scanner.init_db()  # Restart must preserve successful deliveries and subscribers.
    app.bot.send_message = AsyncMock()
    asyncio.run(scanner.deliver_alerts(app, coins, evaluated))
    assert app.bot.send_message.call_count == 1
    assert app.bot.send_message.call_args.kwargs["chat_id"] == "2"
    asyncio.run(scanner.deliver_alerts(app, [], set()))  # Missing data must not rearm.
    asyncio.run(scanner.deliver_alerts(app, coins, evaluated))
    assert app.bot.send_message.call_count == 1
    asyncio.run(scanner.deliver_alerts(app, [], evaluated))
    asyncio.run(scanner.deliver_alerts(app, coins, evaluated))
    assert app.bot.send_message.call_count == 3


@pytest.mark.parametrize("payload", [{"success": False, "code": 1},
                                    {"success": True, "code": 0, "data": []},
                                    {"success": True, "code": 0, "data": {}},
                                    {"success": True, "code": 0, "data": [None]}])
def test_bad_snapshot_rejected(monkeypatch, payload):
    monkeypatch.setattr(scanner.requests, "get", lambda *a, **kw: SimpleNamespace(
        raise_for_status=lambda: None, json=lambda: payload))
    with pytest.raises(ValueError):
        scanner.fetch_market_data("ticker")


def test_scan_failure_does_not_deliver(monkeypatch):
    def fail():
        raise ValueError("API failure")
    monkeypatch.setattr(scanner, "scrape", fail)
    delivery = AsyncMock()
    monkeypatch.setattr(scanner, "deliver_alerts", delivery)
    asyncio.run(scanner.scrape_loop(SimpleNamespace(application=None)))
    delivery.assert_not_called()
