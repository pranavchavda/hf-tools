# hf-tools — Kotak Neo Trading CLI Suite

A suite of CLI tools for interacting with the **Kotak Neo** trading platform. Uses the official `neo_api_client` SDK but bypasses its broken URL resolution for direct REST API calls.

## Installation

```bash
git clone https://github.com/pranavchavda/hf-tools.git
cd hf-tools
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Setup

Create `~/.kotak-cli/.env` with your credentials:

```
KOTAK_CONSUMER_KEY=your-consumer-key
KOTAK_MOBILE=99XXXXXXXX
KOTAK_UCC=your-ucc
KOTAK_MPIN=your-mpin
KOTAK_TOTP_KEY=your-totp-secret
KOTAK_ENVIRONMENT=prod
```

## Usage

```bash
# Login (auto-generates TOTP from key)
hf login

# Check positions
hf positions
hf positions --json

# View portfolio
hf portfolio

# Order book
hf orderbook
hf orderbook --pending-only

# Trade history
hf tradebook

# Available funds
hf funds

# Place an order (use --dry-run to validate first)
hf order --exchange NSECM --product CNC --price 100 --type LIMIT \
         --qty 10 --symbol RELIANCE-EQ --side BUY --dry-run

# Cancel order
hf cancel ORDER_ID

# Modify order
hf modify ORDER_ID --price 105 --qty 15
```

All commands support `--json` for machine parsing and `--pretty` for human-readable tables.

## Commands

| Command | Description |
|---------|-------------|
| `login` | TOTP + MPIN authentication (auto TOTP from key) |
| `order` | Place LIMIT/MARKET/SL/SL-M orders |
| `cancel` | Cancel an order by ID |
| `modify` | Modify price/qty/trigger on an existing order |
| `positions` | View open positions |
| `portfolio` | View holdings |
| `tradebook` | View executed trades |
| `orderbook` | View all orders (use `--pending-only`) |
| `funds` | View available margins and limits |
| `logout` | End session |

## Notes

- **Login quirk**: The first login call to Kotak often returns 400; the tool auto-retries once with a fresh TOTP.
- Uses direct REST calls, bypassing the SDK's broken `get_domain(session_init=True)` URL resolution.
- Session tokens persist in `~/.kotak-cli/session.json` for the trading day.
