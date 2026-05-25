# Kotak Neo CLI Tools (hf-* suite)

Python CLI tools for interacting with Kotak Neo trading platform via the official `neo_api_client` SDK.

## Architecture

Each tool is a standalone script in `hf-tools/`. All share a common session manager in `config.py`.

```
~/kotak-cli/
├── hf-tools/
│   ├── __init__.py
│   ├── config.py          # Shared session manager
│   ├── hf_login.py        # Login + OTP/TOTP 2FA
│   ├── hf_order.py        # Place orders (LIMIT/MARKET/SL)
│   ├── hf_cancel.py       # Cancel orders by ID
│   ├── hf_modify.py       # Modify existing orders
│   ├── hf_positions.py    # Open positions
│   ├── hf_portfolio.py    # Holdings + P&L
│   ├── hf_tradebook.py    # Executed trades
│   ├── hf_orderbook.py    # Pending/completed orders
│   ├── hf_funds.py        # Available margins/limits
│   └── hf_logout.py       # End session
├── env.template           # Config template
├── requirements.txt
├── setup.py               # pip install entry_points
└── CLAUDE.md
```

## Convention (matches NS nf-* style)

Every tool:
- **Defaults to JSON output** (`--json`) for machine parsing. Print pretty if `--pretty` flag or no flag at all.
- **Returns exit code 0** on success, **1** on error (with error message in JSON).
- **Reads session** from `~/.kotak-cli/session.json` managed by `config.py`.
- **Auto-refreshes** expired session (if tokens stale, re-login).
- Uses the venv at `~/.kotak-cli/.venv/`.
- SDK is installed: `pip install "git+https://github.com/Kotak-Neo/Kotak-neo-api-v2.git@v2.0.1#egg=neo_api_client"`

## SDK Reference

The `neo_api_client.NeoAPI` class provides these key methods after login:

```python
from neo_api_client import NeoAPI

# --- Auth ---
client = NeoAPI(consumer_key="xxx", consumer_secret="yyy", environment='prod')
client.login(mobilenumber="99...", password="...")    # Sends OTP via SMS
client.session_2fa("OTP")                               # Verify OTP
# OR:
client.totp_login(mobilenumber="99...", password="...")

# --- Trading ---
client.place_order(
    exchange_segment="NSECM",     # NSECM, BSECM, NSEFO, BSEFO, NSECD, BSECD
    product="CNC",                # CNC, MIS, NRML
    price="100.50",               # Price or 0 for MARKET
    order_type="LIMIT",           # LIMIT, MARKET, SL, SL-M
    quantity="10",                # Quantity in integer
    validity="DAY",               # DAY, IOC
    trading_symbol="RELIANCE-EQ",
    transaction_type="BUY",       # BUY or SELL
    amo="NO",                     # YES for after-market
    trigger_price="0",            # Required for SL orders
)
# Returns: {"success": True, "data": {"nOrdNo": "..."}}

client.cancel_order(order_id="...")
client.modify_order(order_id="...", price="105.00", quantity="15", trigger_price="0")

# --- Reporting ---
client.order_report()             # All orders today
client.trade_report()             # Executed trades
client.order_history(order_id)    # History for one order
client.positions()                # Open positions
client.holdings()                 # Portfolio holdings
client.limits()                   # Available margins/limits

# --- Market Data ---
client.search_scrip(exchange_segment="nse_fo", symbol="BANKNIFTY", ...)
client.quotes(exchange_segment="NSECM", symbol="RELIANCE-EQ")  # or scrip_token

# --- WebSocket ---
client.subscribe_to_orderfeed()

# --- Misc ---
client.logout()
```

### Exchange Segments (settings.py)
- NSECM = NSE Cash Market (equities)
- BSECM = BSE Cash Market
- NSEFO = NSE F&O (futures & options)
- BSEFO = BSE F&O
- NSECD = NSE CDS (currency derivatives)
- BSECD = BSE CDS
- NSECOMM = NSE Commodities

### Product Types
- CNC = Cash & Carry (delivery)
- MIS = Margin Intraday Square-off
- NRML = Normal (F&O, futures)

### Order Types
- LIMIT = Limit price
- MARKET = Market price
- SL = Stop Loss limit
- SL-M = Stop Loss market

### Transaction Types
- BUY
- SELL

### Validity
- DAY = Day order
- IOC = Immediate or Cancel
- GTC = Good Till Cancelled (may not be supported)

## Session Management (config.py)

`~/kotak-cli/session.json` stores:
```json
{
  "consumer_key": "...",
  "consumer_secret": "...",
  "mobile_number": "",
  "environment": "prod",
  "edit_token": "...",
  "edit_sid": "...",
  "serverId": "...",
  "logged_in_at": "ISO timestamp",
  "token_type": "session_2fa"
}
```

The config module:
- `load_session()` -> dict or None
- `save_session(data)` -> writes to ~/.kotak-cli/session.json
- `get_client() -> NeoAPI` — loads session, creates client, returns authenticated client
- `clear_session()` — removes session file (for re-login)

## Testing

Since we can't test live without real credentials, each tool should have a `--dry-run` flag:
- Authenticate but don't place trade
- Validate all params
- Print what WOULD happen

## Error Handling

All tools catch exceptions and output structured JSON errors:
```json
{"success": false, "error": "Human readable message", "code": "ERROR_CODE"}
```

Common error codes:
- `AUTH_REQUIRED` — need to login first
- `AUTH_EXPIRED` — session expired
- `INVALID_PARAMS` — bad input
- `API_ERROR` — Kotak API returned error
- `NETWORK_ERROR` — connection issue
