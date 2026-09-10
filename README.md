# MEXC futures gainer alerts

Scans public MEXC market data every 60 seconds and sends Telegram alerts for active
USDT perpetual futures matching all of these defaults:

- 24h gain ≥ 80%.
- 24h turnover ≥ 1,000,000 USDT.
- Open-interest notional / 24h turnover ≥ 10%.

Open-interest notional is `holdVol × contractSize × lastPrice`, in USDT.
Alerts are ordered by gain and include turnover, OI, OI/turnover, funding rate,
last price, and a futures link. No MEXC API key is needed.

## Run

```sh
python -m pip install -r requirements.txt
export TG_BOT_TOKEN='your-telegram-bot-token'
bash run_app.sh
```

The process reads environment variables; it does not automatically load `.env`.
Send `/start` to the bot to subscribe; `/health` checks bot responsiveness.
Existing subscribers in `data/mexc_futures.db` are retained. Announcement scraping
is replaced by market scanning; old announcement records are left intact.

| Environment variable | Default | Meaning |
| --- | --- | --- |
| `TG_BOT_TOKEN` | required | Telegram bot token |
| `SCRAPE_INTERVAL` | `60` | Seconds between scans |
| `MIN_GAIN_PERCENT` | `80` | Minimum 24h percentage gain |
| `MIN_TURNOVER_USDT` | `1000000` | Minimum 24h turnover |
| `MIN_OI_TURNOVER_RATIO` | `0.10` | Minimum OI/turnover ratio (10%) |
| `MAX_OI_TURNOVER_RATIO` | unset | Optional upper ratio, e.g. `1.50` for 150% |
| `DB_PATH` | `data/mexc_futures.db` in repo | SQLite database location |

The first scan alerts on currently qualifying contracts. Each subscriber receives
one alert per qualifying period, including across restarts. A successfully evaluated
contract that stops qualifying is rearmed and can alert again on re-entry. Missing
or malformed data and failed scans do not reset alerts. Failed Telegram deliveries
retry on subsequent scans while the contract qualifies. A crash after Telegram
accepts a message but before SQLite records it can cause a duplicate on restart.

Persist `/app/data` when using Docker to retain subscribers and alert state:

```sh
docker build -t mexc-gainers .
docker run --env-file .env -v "$(pwd)/data:/app/data" mexc-gainers
```

## Checks

```sh
uv sync
uv run pytest
uv run ruff check src tests
```

Market fields: [MEXC ticker documentation](https://www.mexc.com/api-docs/futures/market-endpoints/get-ticker-contract-market-data)
and [contract metadata](https://www.mexc.com/api-docs/futures/market-endpoints/get-contract-info).

## GitHub deployment

Pull requests and pushes to `main` run the locked Python test suite, lint and shell
checks, and a Docker build. Successful pushes to `main` deploy automatically;
`workflow_dispatch` also supports a manual deployment from `main`. Workflow-only
and startup-script changes are included. Deployments are serialized.

The repository needs these existing Actions secrets: `DEPLOY_HOST`, `DEPLOY_USER`,
`DEPLOY_PASSWORD`, and `TG_BOT_TOKEN`. The SSH user needs Docker access and a Git
checkout at `~/market-scraper` with access to the origin repository.

Deployment builds an archive of the triggering commit before stopping the old
container. It preserves `~/market-scraper/data`, replaces only
`mexc-market-scraper-container`, and enables automatic restart. The Git working
files on the server are not used as the image source. A failed startup restores
the previous container; a failed build leaves it running.

Docker health requires a successful market scan within the last three scan
intervals (at least 180 seconds). Deployment waits up to 180 seconds for initial
health. This checks market access and scan completion, not delivery to every
subscriber. Failed individual Telegram deliveries are retried as described above.
