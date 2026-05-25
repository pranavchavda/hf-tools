#!/usr/bin/env python3
"""hf — unified CLI for the Kotak Neo trading platform (hf-* suite).

Usage::

    hf login  --totp [--mobile ...] [--ucc ...] [--consumer-key ...]
    hf login  --otp  [--mobile ...] [--password ...]          # see note below
    hf order  --exchange NSECM --product CNC --price 100 --type LIMIT \\
              --qty 10 --symbol RELIANCE-EQ --side BUY [--trigger 0] [--dry-run]
    hf cancel ORDER_ID [--is-verify]
    hf modify ORDER_ID [--price ...] [--qty ...] [--trigger ...] [--type ...] [--validity ...]
    hf positions [--exchange NSECM]
    hf portfolio
    hf tradebook
    hf orderbook [--pending-only]
    hf funds
    hf logout

Global flags (any subcommand):
    --json      emit raw JSON (machine parsing, e.g. Hermes)
    --pretty    force pretty key/value + table output (default when a TTY)

Conventions:
    * Default output is pretty; pass --json for machine parsing.
    * Errors are written to stderr as structured JSON.
    * Exit code 0 on success, 1 on error.

AUTH NOTE
---------
The installed ``neo_api_client`` SDK (v2.0.x) supports a **TOTP + MPIN** login
flow only. The classic SMS-OTP flow (``--otp``) is not available in this SDK
build; selecting it returns a structured error directing you to ``--totp``.
"""

import sys
import json
import argparse
import datetime

# Support running both as an installed package (`hf`) and as a loose script.
try:
    from hf_tools import config
except ImportError:  # pragma: no cover - direct script execution
    import config


# --------------------------------------------------------------------------
# Output helpers
# --------------------------------------------------------------------------

def emit_error(message, code="API_ERROR", as_json=True, exit_code=1):
    """Write a structured error to stderr and exit."""
    payload = {"success": False, "error": str(message), "code": code}
    if as_json:
        print(json.dumps(payload), file=sys.stderr)
    else:
        print("ERROR [%s]: %s" % (code, message), file=sys.stderr)
    sys.exit(exit_code)


def emit_success(data, as_json=True, pretty_fn=None):
    """Write a success payload to stdout."""
    if as_json:
        print(json.dumps({"success": True, "data": data}, default=str))
    else:
        if pretty_fn is not None:
            pretty_fn(data)
        else:
            print(json.dumps(data, indent=2, default=str))
    sys.exit(0)


def _print_kv(d, title=None):
    if title:
        print(title)
        print("-" * len(title))
    if not isinstance(d, dict):
        print(d)
        return
    width = max((len(str(k)) for k in d), default=0)
    for key, val in d.items():
        print("  %-*s : %s" % (width, key, val))


def _print_table(rows, columns):
    """Print a list of dicts as an aligned table.

    ``columns`` is a list of (key, header) tuples.
    """
    if not rows:
        print("(no records)")
        return
    headers = [h for _, h in columns]
    keys = [k for k, _ in columns]
    widths = [len(h) for h in headers]
    str_rows = []
    for row in rows:
        cells = []
        for i, key in enumerate(keys):
            cell = str(row.get(key, "") if isinstance(row, dict) else "")
            cells.append(cell)
            widths[i] = max(widths[i], len(cell))
        str_rows.append(cells)
    fmt = "  ".join("%-*s" for _ in headers)
    flat_header = []
    for w, h in zip(widths, headers):
        flat_header.extend([w, h])
    print(fmt % tuple(flat_header))
    print("  ".join("-" * w for w in widths))
    for cells in str_rows:
        flat = []
        for w, c in zip(widths, cells):
            flat.extend([w, c])
        print(fmt % tuple(flat))


# --------------------------------------------------------------------------
# Kotak REST API helpers (bypasses the SDK's broken URL resolution)
# --------------------------------------------------------------------------

import urllib.request as _urllib_request
import urllib.error as _urllib_error

def _rest_call(method, path, session, body=None, query_params=None):
    """Make a REST call to the Kotak Neo API for an authenticated session.
    
    Args:
        method: 'GET' or 'POST'
        path: URL path like '/quick/user/positions'
        session: session dict from config.get_client()
        body: optional dict for POST body
        query_params: optional dict for query string
    """
    base = session.get("base_url", "https://e22.kotaksecurities.com")
    url = f"{base}{path}"
    
    hs_id = session.get("serverId", "")
    if query_params:
        import urllib.parse
        url += "?" + urllib.parse.urlencode(query_params)
    elif hs_id:
        import urllib.parse
        url += "?sId=" + urllib.parse.quote(hs_id)
    
    headers = {
        "Sid": session.get("edit_sid", ""),
        "Auth": session.get("edit_token", ""),
        "accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    
    data = None
    if body:
        import urllib.parse
        data = urllib.parse.urlencode(body).encode("utf-8")
    
    req = _urllib_request.Request(url, data=data, headers=headers, method=method)
    try:
        with _urllib_request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except _urllib_error.HTTPError as e:
        err = e.read().decode("utf-8")
        try:
            return json.loads(err)
        except json.JSONDecodeError:
            return {"error": [{"message": err[:200]}]}
    except Exception as e:
        return {"error": [{"message": str(e)}]}

def _get_session(as_json=True):
    """Load session and validate, emitting error and exiting on failure."""
    try:
        return config.get_client()
    except config.HFError as exc:
        emit_error(exc.message, code=exc.code, as_json=as_json)

def _check_kotak(resp, as_json=True):
    """Check Kotak response for errors, raise HFError if found."""
    if isinstance(resp, dict):
        errs = resp.get("error") or resp.get("Error")
        if errs:
            if isinstance(errs, list):
                msg = "; ".join(e.get("message", str(e)) for e in errs)
            else:
                msg = str(errs)
            raise config.HFError(msg, code="API_ERROR")
        if resp.get("stat") == "Not_Ok" or resp.get("stCode") not in (None, 200):
            msg = resp.get("errMsg") or resp.get("emsg") or str(resp)
            raise config.HFError(msg, code="API_ERROR")
    return resp

def _extract_rows(resp):
    """Extract data rows from a Kotak response."""
    if isinstance(resp, dict):
        data = resp.get("data")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [data]
    if isinstance(resp, list):
        return resp
    return []


# --------------------------------------------------------------------------
# login
# --------------------------------------------------------------------------

def cmd_login(args):
    as_json = args.json
    env = config.load_env()

    if args.otp:
        emit_error(
            "The installed neo_api_client SDK (v2.0.x) does not support the SMS-OTP "
            "login flow. Use `hf login --totp` (TOTP authenticator + MPIN) instead.",
            code="INVALID_PARAMS",
            as_json=as_json,
        )

    # TOTP is the only real flow; treat it as the default when neither flag given.
    consumer_key = args.consumer_key or env.get("consumer_key")
    mobile = args.mobile or env.get("mobile_number")
    ucc = args.ucc or env.get("ucc")
    environment = args.environment or env.get("environment") or config.DEFAULT_ENVIRONMENT
    neo_fin_key = env.get("neo_fin_key")

    if not consumer_key:
        emit_error("Missing consumer key. Pass --consumer-key or set KOTAK_CONSUMER_KEY.",
                   code="INVALID_PARAMS", as_json=as_json)
    if not mobile:
        emit_error("Missing mobile number. Pass --mobile or set KOTAK_MOBILE.",
                   code="INVALID_PARAMS", as_json=as_json)
    if not ucc:
        emit_error("Missing UCC. Pass --ucc or set KOTAK_UCC (found under Profile in the app).",
                   code="INVALID_PARAMS", as_json=as_json)

    # TOTP code: from flag, auto-generate from key, or interactive prompt.
    totp_code = args.totp_code
    if not totp_code:
        totp_key = env.get("totp_key")
        if totp_key:
            try:
                import pyotp
                totp_code = pyotp.TOTP(totp_key).now()
            except ImportError:
                pass  # fall through to interactive
    if not totp_code and not as_json:
        totp_code = input("Enter 6-digit TOTP from your authenticator app: ").strip()
    if not totp_code:
        emit_error("Missing TOTP code. Pass --totp-code or set KOTAK_TOTP_KEY.",
                   code="INVALID_PARAMS", as_json=as_json)

    # MPIN: from flag, env, or prompt.
    mpin = args.mpin or env.get("mpin")
    if not mpin and not as_json:
        import getpass
        mpin = getpass.getpass("Enter MPIN: ").strip()
    if not mpin:
        emit_error("Missing MPIN. Pass --mpin or set KOTAK_MPIN.",
                   code="INVALID_PARAMS", as_json=as_json)

    # --- Login via direct Kotak REST API ---
    # The SDK's get_domain(session_init=True) returns a wrong base URL for PROD,
    # so we bypass the SDK for auth and use direct REST calls.
    
    login_url = "https://mis.kotaksecurities.com/login/1.0/tradeApiLogin"
    validate_url = "https://mis.kotaksecurities.com/login/1.0/tradeApiValidate"
    
    auth_headers = {
        "Authorization": consumer_key,
        "neo-fin-key": env.get("neo_fin_key") or "neotradeapi",
        "Content-Type": "application/json",
    }
    
    try:
        import urllib.request, urllib.error, json as _json
        
        def _rest_post(url, body):
            """Make a direct REST POST request without the SDK."""
            data = _json.dumps(body).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers=auth_headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    return _json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8")
                try:
                    return _json.loads(err_body)
                except _json.JSONDecodeError:
                    return {"error": [{"message": err_body}]}
        
        # Step 1: TOTP Login (with warm-up retry — first call to Kotak often 400s)
        totp_code = pyotp.TOTP(totp_key).now() if totp_key else totp_code
        login_body = {"mobileNumber": mobile, "ucc": ucc, "totp": totp_code}
        
        login_resp = _rest_post(login_url, login_body)
        # If first attempt fails with 400, retry with fresh TOTP once
        if login_resp.get("error") and any(
            e.get("code") == "400" for e in (login_resp.get("error") or [])
        ):
            import time as _time
            _time.sleep(0.5)
            totp_code = pyotp.TOTP(totp_key).now() if totp_key else pyotp.TOTP(totp_key).now()
            login_body["totp"] = totp_code
            login_resp = _rest_post(login_url, login_body)
        
        if not login_resp.get("data") or not login_resp["data"].get("token"):
            err_msg = login_resp.get("error", [{}])
            if isinstance(err_msg, list):
                err_msg = err_msg[0].get("message", str(login_resp))
            emit_error("Login failed: %s" % err_msg, code="API_ERROR", as_json=as_json)
        
        login_data = login_resp["data"]
        
        # Step 2: Validate with MPIN
        validate_body = {
            "token": login_data["token"],
            "sid": login_data["sid"],
            "rid": login_data["rid"],
            "mpin": mpin,
        }
        validate_resp = _rest_post(validate_url, validate_body)
        
        if not validate_resp.get("data") or not validate_resp["data"].get("token"):
            err_msg = validate_resp.get("error", [{}])
            if isinstance(err_msg, list):
                err_msg = err_msg[0].get("message", str(validate_resp))
            emit_error("2FA validation failed: %s" % err_msg, code="API_ERROR", as_json=as_json)
        
        validate_data = validate_resp["data"]
        
    except config.HFError:
        raise
    except Exception as exc:
        emit_error("Login failed: %s" % exc, code="NETWORK_ERROR", as_json=as_json)
    
    # Build session from the returned tokens
    session = {
        "consumer_key": consumer_key,
        "environment": environment,
        "ucc": ucc,
        "mobile_number": mobile,
        "edit_token": validate_data.get("token", login_data.get("token")),
        "edit_sid": validate_data.get("sid", login_data.get("sid")),
        "edit_rid": validate_data.get("rid", login_data.get("rid")),
        "serverId": validate_data.get("hsServerId", validate_data.get("serverId", "")),
        "dataCenter": login_data.get("dataCenter", "E22"),
        "neo_fin_key": env.get("neo_fin_key"),
        "base_url": "https://%s.kotaksecurities.com" % login_data.get("dataCenter", "e22").lower(),
        "logged_in_at": __import__("datetime").datetime.now().isoformat(),
        "token_type": "totp_validate",
        "greeting_name": login_data.get("greetingName", ""),
    }
    path = config.save_session(session)

    result = {
        "message": "Login successful.",
        "ucc": ucc,
        "environment": environment,
        "session_file": path,
        "logged_in_at": session["logged_in_at"],
    }
    emit_success(result, as_json=as_json, pretty_fn=lambda d: _print_kv(d, "Kotak Neo — Login"))


# --------------------------------------------------------------------------
# order
# --------------------------------------------------------------------------

def cmd_order(args):
    as_json = args.json

    order_type = args.type.upper()
    side = args.side.upper()

    # Validation
    if side not in ("BUY", "SELL"):
        emit_error("--side must be BUY or SELL", code="INVALID_PARAMS", as_json=as_json)
    if order_type not in ("LIMIT", "MARKET", "SL", "SL-M"):
        emit_error("--type must be one of LIMIT, MARKET, SL, SL-M", code="INVALID_PARAMS", as_json=as_json)
    if order_type in ("SL", "SL-M") and float(args.trigger or 0) <= 0:
        emit_error("%s orders require a positive --trigger price" % order_type,
                   code="INVALID_PARAMS", as_json=as_json)
    if args.qty <= 0:
        emit_error("--qty must be a positive integer", code="INVALID_PARAMS", as_json=as_json)

    price = "0" if order_type == "MARKET" else str(args.price)

    # Map exchange/order types to Kotak codes
    ex_map = {"NSECM": "nse_cm", "BSECM": "bse_cm", "NSEFO": "nse_fo", "BSEFO": "bse_fo", "NSECD": "cde_fo", "BSECD": "bcd", "MCXFO": "mcx_fo"}
    exch = ex_map.get(args.exchange.upper(), args.exchange)
    prod_map = {"CNC": "CNC", "MIS": "MIS", "NRML": "NRML"}
    prod = prod_map.get(args.product.upper(), args.product)
    ot_map = {"LIMIT": "L", "MARKET": "MKT", "SL": "SL", "SL-M": "SL-M"}
    ot = ot_map.get(order_type, order_type)
    val_map = {"DAY": "DAY", "IOC": "IOC"}
    val = val_map.get(args.validity.upper(), args.validity)

    body = {
        "am": args.amo.upper(),
        "dq": "0",
        "es": exch,
        "mp": "0",
        "pc": prod,
        "pf": "N",
        "pr": price,
        "pt": ot,
        "qt": str(args.qty),
        "rt": val,
        "tp": str(args.trigger or "0"),
        "ts": args.symbol,
        "tt": side,
        "os": "WEB",
    }
    if args.tag:
        body["ig"] = args.tag

    if args.dry_run:
        auth_ok = config.session_is_valid()
        result = {
            "dry_run": True,
            "would_place": body,
            "authenticated": auth_ok,
            "note": "No order was placed (--dry-run).",
        }
        emit_success(result, as_json=as_json,
                     pretty_fn=lambda d: _print_kv(d["would_place"], "DRY RUN — order NOT placed"))

    session = _get_session(as_json)
    resp = _rest_call("POST", "/quick/order/rule/ms/place", session, body=body)
    _check_kotak(resp, as_json)

    data = resp.get("data", resp) if isinstance(resp, dict) else resp
    emit_success(data, as_json=as_json,
                 pretty_fn=lambda d: _print_kv(d, "Order placed"))


# --------------------------------------------------------------------------
# cancel
# --------------------------------------------------------------------------

def cmd_cancel(args):
    as_json = args.json
    session = _get_session(as_json)
    body = {"on": args.order_id, "am": args.amo.upper()}
    
    if args.is_verify:
        # Fetch orderbook to verify order status
        ob = _rest_call("GET", "/quick/user/orders", session)
        if isinstance(ob, dict) and "data" in ob:
            for item in ob["data"]:
                if item.get("nOrdNo") == args.order_id:
                    st = item.get("ordSt", "").lower()
                    if st in ("rejected", "cancelled", "complete", "traded"):
                        reason = item.get("rejRsn", "")
                        emit_error("Order %s already %s%s" % (args.order_id, st, ": " + reason if reason else ""),
                                   code="API_ERROR", as_json=as_json)
    
    resp = _rest_call("POST", "/quick/order/cancel", session, body=body)
    _check_kotak(resp, as_json)
    
    data = resp.get("data", resp) if isinstance(resp, dict) else resp
    emit_success(data, as_json=as_json, pretty_fn=lambda d: _print_kv(d, "Order cancelled"))


# --------------------------------------------------------------------------
# modify
# --------------------------------------------------------------------------

def cmd_modify(args):
    as_json = args.json

    if args.price is None and args.qty is None and args.trigger is None:
        emit_error("Nothing to modify: pass at least one of --price, --qty, --trigger.",
                   code="INVALID_PARAMS", as_json=as_json)

    session = _get_session(as_json)
    body = {
        "on": args.order_id,
        "pr": str(args.price) if args.price is not None else "0",
        "qt": str(args.qty) if args.qty is not None else "0",
        "tp": str(args.trigger) if args.trigger is not None else "0",
        "pt": args.type.upper(),
        "rt": args.validity.upper(),
    }
    
    resp = _rest_call("POST", "/quick/order/vr/modify", session, body=body)
    _check_kotak(resp, as_json)

    data = resp.get("data", resp) if isinstance(resp, dict) else resp
    emit_success(data, as_json=as_json, pretty_fn=lambda d: _print_kv(d, "Order modified"))


# --------------------------------------------------------------------------
# positions
# --------------------------------------------------------------------------

def cmd_positions(args):
    as_json = args.json
    session = _get_session(as_json)
    resp = _rest_call("GET", "/quick/user/positions", session)
    _check_kotak(resp, as_json)

    rows = _extract_rows(resp)
    if args.exchange:
        rows = [r for r in rows if str(r.get("exSeg", r.get("es", ""))).upper() == args.exchange.upper()]

    def pretty(_):
        _print_table(rows, [
            ("trdSym", "SYMBOL"), ("exSeg", "EXCH"), ("prod", "PROD"),
            ("flBuyQty", "BUYQTY"), ("flSellQty", "SELLQTY"),
            ("buyAmt", "BUYAMT"), ("sellAmt", "SELLAMT"),
        ])
    emit_success(rows, as_json=as_json, pretty_fn=pretty)


# --------------------------------------------------------------------------
# portfolio (holdings)
# --------------------------------------------------------------------------

def cmd_portfolio(args):
    as_json = args.json
    session = _get_session(as_json)
    resp = _rest_call("GET", "/portfolio/v1/holdings", session)
    _check_kotak(resp, as_json)

    rows = _extract_rows(resp)

    def pretty(_):
        _print_table(rows, [
            ("displaySymbol", "SYMBOL"), ("quantity", "QTY"),
            ("averagePrice", "AVG"), ("closingPrice", "LTP"),
            ("mktValue", "MKTVAL"), ("holdingCost", "COST"),
        ])
    emit_success(rows, as_json=as_json, pretty_fn=pretty)


# --------------------------------------------------------------------------
# tradebook
# --------------------------------------------------------------------------

def cmd_tradebook(args):
    as_json = args.json
    session = _get_session(as_json)
    resp = _rest_call("GET", "/quick/user/trades", session)
    _check_kotak(resp, as_json)

    rows = _extract_rows(resp)

    def pretty(_):
        _print_table(rows, [
            ("trdSym", "SYMBOL"), ("exSeg", "EXCH"), ("trnsTp", "SIDE"),
            ("fldQty", "QTY"), ("avgPrc", "PRICE"), ("flDtTm", "TIME"),
            ("nOrdNo", "ORDERID"),
        ])
    emit_success(rows, as_json=as_json, pretty_fn=pretty)


# --------------------------------------------------------------------------
# orderbook
# --------------------------------------------------------------------------

_OPEN_STATES = {"open", "pending", "trigger pending", "modified", "validation pending", "open pending"}


def cmd_orderbook(args):
    as_json = args.json
    session = _get_session(as_json)
    resp = _rest_call("GET", "/quick/user/orders", session)
    _check_kotak(resp, as_json)

    rows = _extract_rows(resp)
    if args.pending_only:
        rows = [r for r in rows if r.get("ordSt", "").strip().lower() in _OPEN_STATES]

    def pretty(_):
        _print_table(rows, [
            ("nOrdNo", "ORDERID"), ("trdSym", "SYMBOL"), ("exSeg", "EXCH"),
            ("trnsTp", "SIDE"), ("ordSt", "STATUS"), ("fldQty", "FILLED"),
            ("avgPrc", "PRICE"),
        ])
    emit_success(rows, as_json=as_json, pretty_fn=pretty)

def cmd_funds(args):
    as_json = args.json
    session = _get_session(as_json)
    resp = _rest_call("GET", "/quick/user/limits", session)
    _check_kotak(resp, as_json)

    rows = _extract_rows(resp)

    def pretty(_):
        _print_table(rows, [
            ("stat", "STATUS"), ("usableMktVal", "MKT_VAL"),
            ("usedMargin", "MARGIN"), ("multiplier", "MULTIPLIER"),
            ("availableCash", "CASH"),
        ])
    emit_success(rows, as_json=as_json, pretty_fn=pretty)


# --------------------------------------------------------------------------
# logout
# --------------------------------------------------------------------------

def cmd_logout(args):
    as_json = args.json
    api_msg = None
    try:
        session = config.get_client()
        resp = _rest_call("GET", "/apim/login/2.0/logout", session)
        api_msg = resp
    except config.HFError:
        pass
    except Exception as exc:
        api_msg = "remote logout error: %s" % exc

    removed = config.clear_session()
    result = {
        "message": "Logged out." if removed else "No active local session to clear.",
        "local_session_cleared": removed,
        "remote": api_msg,
    }
    emit_success(result, as_json=as_json, pretty_fn=lambda d: _print_kv(d, "Logout"))


# --------------------------------------------------------------------------
# Argument parsing
# --------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog="hf",
        description="Kotak Neo trading CLI (hf-* suite).",
    )

    def add_common(sp):
        sp.add_argument("--json", action="store_true", help="emit raw JSON output")
        sp.add_argument("--pretty", action="store_true", help="force pretty output (default)")

    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # login
    p = sub.add_parser("login", help="authenticate and store a session")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--totp", action="store_true", help="TOTP authenticator + MPIN flow (default)")
    g.add_argument("--otp", action="store_true", help="(unsupported by installed SDK) SMS OTP flow")
    p.add_argument("--mobile", help="registered mobile number")
    p.add_argument("--password", help="account password (reserved; not used by TOTP flow)")
    p.add_argument("--ucc", help="Unique Client Code")
    p.add_argument("--totp-code", help="6-digit code from authenticator app")
    p.add_argument("--mpin", help="6-digit MPIN")
    p.add_argument("--consumer-key", help="Kotak consumer key")
    p.add_argument("--consumer-secret", help="Kotak consumer secret")
    p.add_argument("--environment", help="prod or uat (default from env or prod)")
    add_common(p)
    p.set_defaults(func=cmd_login)

    # order
    p = sub.add_parser("order", help="place an order")
    p.add_argument("--exchange", required=True, help="exchange segment, e.g. NSECM, NSEFO")
    p.add_argument("--product", required=True, help="CNC, MIS or NRML")
    p.add_argument("--price", default="0", help="limit price (ignored for MARKET)")
    p.add_argument("--type", required=True, help="LIMIT, MARKET, SL or SL-M")
    p.add_argument("--qty", required=True, type=int, help="quantity")
    p.add_argument("--symbol", required=True, help="trading symbol, e.g. RELIANCE-EQ")
    p.add_argument("--side", required=True, help="BUY or SELL")
    p.add_argument("--trigger", default="0", help="trigger price (required for SL/SL-M)")
    p.add_argument("--validity", default="DAY", help="DAY or IOC (default DAY)")
    p.add_argument("--amo", default="NO", help="after-market order YES/NO (default NO)")
    p.add_argument("--tag", help="optional order tag")
    p.add_argument("--dry-run", action="store_true", help="validate only; do not place")
    add_common(p)
    p.set_defaults(func=cmd_order)

    # cancel
    p = sub.add_parser("cancel", help="cancel an order by id")
    p.add_argument("order_id", help="order number to cancel")
    p.add_argument("--amo", default="NO", help="after-market YES/NO (default NO)")
    p.add_argument("--is-verify", action="store_true",
                   help="verify order state before cancelling")
    add_common(p)
    p.set_defaults(func=cmd_cancel)

    # modify
    p = sub.add_parser("modify", help="modify an existing order")
    p.add_argument("order_id", help="order number to modify")
    p.add_argument("--price", help="new limit price")
    p.add_argument("--qty", help="new quantity")
    p.add_argument("--trigger", help="new trigger price")
    p.add_argument("--type", default="LIMIT", help="order type (default LIMIT)")
    p.add_argument("--validity", default="DAY", help="validity (default DAY)")
    p.add_argument("--symbol", help="trading symbol (some segments require it)")
    p.add_argument("--exchange", help="exchange segment")
    p.add_argument("--product", help="product type")
    p.add_argument("--side", help="BUY or SELL")
    add_common(p)
    p.set_defaults(func=cmd_modify)

    # positions
    p = sub.add_parser("positions", help="show open positions")
    p.add_argument("--exchange", help="filter by exchange segment")
    add_common(p)
    p.set_defaults(func=cmd_positions)

    # portfolio
    p = sub.add_parser("portfolio", help="show holdings")
    add_common(p)
    p.set_defaults(func=cmd_portfolio)

    # tradebook
    p = sub.add_parser("tradebook", help="show executed trades")
    add_common(p)
    p.set_defaults(func=cmd_tradebook)

    # orderbook
    p = sub.add_parser("orderbook", help="show orders placed today")
    p.add_argument("--pending-only", action="store_true", help="only open/pending orders")
    add_common(p)
    p.set_defaults(func=cmd_orderbook)

    # funds
    p = sub.add_parser("funds", help="show available margins / limits")
    p.add_argument("--segment", default="ALL", help="segment filter (default ALL)")
    p.add_argument("--exchange", help="exchange filter (default ALL)")
    p.add_argument("--product", help="product filter (default ALL)")
    add_common(p)
    p.set_defaults(func=cmd_funds)

    # logout
    p = sub.add_parser("logout", help="end the session")
    add_common(p)
    p.set_defaults(func=cmd_logout)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 1

    # Resolve output mode: JSON only when explicitly requested.
    if not hasattr(args, "json"):
        args.json = False
    try:
        args.func(args)
    except SystemExit:
        raise
    except config.HFError as exc:
        emit_error(exc.message, code=exc.code, as_json=args.json)
    except KeyboardInterrupt:
        emit_error("Interrupted.", code="INVALID_PARAMS", as_json=args.json)
    except Exception as exc:  # last-resort guard
        emit_error("Unexpected error: %s" % exc, code="API_ERROR", as_json=args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
