# Drift ↔ Hyperliquid Arbitrage Bot

## Overview

Drift-Hyperliquid Arbitrage Bot executes price and funding rate arbitrage between Drift on Solana and Hyperliquid L2 perpetual markets. The bot monitors both venues, identifies profitable spreads and executes hedged positions simultaneously on each exchange. Strategies can run in simulation or live trading mode.

## Architecture Highlights

- **Modular Connectors** – Each exchange is abstracted by a `ConnectorBase` implementation providing asynchronous book data, funding rates and order management.
- **Execution Engine** – `ExecutionEngine` ensures atomic pair trades. Orders are placed on both venues and rolled back if either side fails, preventing directional exposure.
- **Strategy Layer** – Strategies implement logic for basis and funding arbitrage while leveraging shared execution and connectors.
- **Configuration Loader** – Typed configuration via Pydantic with environment variable fallbacks for sensitive keys.
- **Multi Strategy Runner** – Supports concurrent strategies driven by a single CLI entry point.
- **Comprehensive Tests** – Pytest suite covers connectors, strategies and execution logic ensuring safe upgrades.

## Strategy Details

### Basis Arbitrage

The basis strategy compares the spot-equivalent prices of perpetual contracts on Drift and Hyperliquid. It retrieves the best bid and ask levels from each venue and computes the average price required to fill the configured `amount`. This approximation allows the strategy to estimate potential slippage and to calculate the all-in entry cost. Taker fees for both legs are subtracted from the gross spread. If going long on one exchange and short on the other is projected to yield at least `min_profit_usd` after fees, and the worst slippage across both books stays below `max_slippage_bps`, the opportunity is returned. The long venue is whichever side delivers the higher net profit at that point in time.

### Funding Rate Arbitrage

Funding arbitrage evaluates the difference in expected funding payments between the two venues. The strategy fetches the most recent funding rates along with current order books. Using mid prices from both exchanges, it estimates the dollar value of the funding spread for the configured holding period (`hold_time_sec`). Taker fees for opening and closing both legs are deducted from this figure. If the resulting profit exceeds `min_profit_usd` and the estimated slippage from the order books is within `max_slippage_bps`, the strategy enters a market-neutral position: long on the exchange with the lower funding rate and short on the one with the higher rate.

Both strategies obtain order book snapshots and funding data through the connector classes. When an opportunity is identified, its parameters are passed to the `ExecutionEngine`, which handles atomic order placement on both exchanges, monitors fills, and enforces slippage and timeout constraints.

## Installation

1. Install Python 3.12+ and create a virtual environment.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy `config/main.example.yaml` to `config/main.yaml` and edit values. Secrets should be passed via environment variables as shown below.

## Running the Bot

Run strategies using the CLI:
```bash
python cli.py --strategy basis --mode live --config config/main.yaml
```
Options:
- `--strategy {basis,funding}` – select strategy or omit to run both.
- `--mode {live,dry-run}` or `--dry-run` – live trading or simulation.
- `--safe-mode` – force safe mode, preventing new trades.

### Environment Variables
Sensitive data is read from the environment if not set in the YAML:
- `DRIFT_PRIVATE_KEY`
- `HYPERLIQUID_API_KEY`
- `HYPERLIQUID_API_SECRET`
- `HYPERLIQUID_ACCOUNT_ADDRESS`

## Logging & Monitoring

The bot logs to console and optionally to file. Executed trades and opportunities are persisted in JSONL files:
- `storage/trades.jsonl`
- `storage/opportunities.jsonl`
- `storage/events.log`


## Execution Logic & Risk Management

**Execution process:**

Before placing trades, the bot fetches current positions on both exchanges to record the initial state.

Buy and sell (long/short legs) orders are submitted simultaneously using asynchronous calls, minimizing delay between legs (though true atomicity is impossible as exchanges operate independently).

After orders are submitted, the bot enters a fill-waiting phase (`_wait_fill`), polling each position at a set interval (typically every second) to check if the order has filled. Each leg has a strict timeout (e.g., 10 seconds).

If both orders are filled within the timeout, the trade is considered successful; the bot calculates realized slippage per leg and logs all execution parameters.

If either leg is not filled before timeout, the bot triggers a rollback: cancels any unfilled orders, logs the error, and switches to safe mode, where new trades are blocked until manual review.

**Risks managed and minimized in code:**

- **Execution delay:** all key actions (order placement, fill monitoring, cancellation) are fully asynchronous to minimize inter-leg delay. A strict timeout ensures that if any leg does not fill promptly, the trade is rolled back.
- **Slippage:** after execution, the bot calculates the difference between expected and realized price for each leg and compares it to the configured threshold (`max_slippage_bps`). Exceeding this threshold triggers a warning in the logs.
- **Partial/one-sided fill:** if only one order is filled, the bot cancels the remaining order and activates safe mode, preventing unhedged market exposure.
- **SDK/network/exchange failures:** all network and SDK errors are caught and logged; in any exception, the bot rolls back orders and activates safe mode.
- **Full execution logging:** all critical execution events and parameters are logged for future audit and troubleshooting.

**Additional potential risks:**

- **Blockchain or L2 settlement delays:** even if orders are submitted instantly, settlement on the blockchain or L2 may be delayed, increasing the risk of execution gaps.
- **Order book movement during execution:** prices can move sharply in milliseconds between opportunity detection and execution, resulting in reduced or negative arbitrage.
- **Exchange API failures or rate limits:** exchanges may impose rate limits, drop connections, or return unexpected errors at critical moments.
- **Position desyncs between SDK and exchange:** a position may fill on the exchange but not be reflected in SDK/API state immediately, leading to false execution assumptions.
- **Undocumented changes to exchange parameters:** changes in precision, lot size, or order requirements (without notice) may cause order rejection or incorrect amount calculation.

All these considerations mean that, despite robust risk management and rollback logic, all operations should be monitored and validated in real time, with manual oversight recommended for production use.

## Security Recommendations

- Never commit real API keys or private keys. The `.gitignore` excludes `config/main.yaml` and `.env` files.
- Use environment variables for secrets as supported by `ConfigLoader`.
- Restrict key permissions and consider using dedicated accounts for trading.

## Disclaimer

This project is provided under the MIT License for research and development. Running the bot with real funds without a professional audit is strongly discouraged. No warranty is given and you assume all risks when deploying this software.
