"""Shared session manager for the Kotak Neo hf-* CLI suite.

Handles credential loading (.env), session persistence to ~/.kotak-cli/session.json,
and reconstruction of an authenticated ``neo_api_client.NeoAPI`` instance.

NOTE ON SDK FLOW
----------------
The installed ``neo_api_client`` (v2.0.x) authenticates with a **TOTP + MPIN**
flow (``totp_login`` -> ``totp_validate``). There is no ``login`` /
``session_2fa`` / ``generateOTP`` as described in older docs. After a successful
``totp_validate`` the SDK stores everything needed to make authenticated calls on
``client.configuration``:

    edit_token, edit_sid, edit_rid, serverId, base_url, data_center

We persist those values so subsequent commands can rebuild a working client
without re-authenticating.
"""

import os
import json
import datetime

# --- Paths ---------------------------------------------------------------

SESSION_DIR = os.path.expanduser("~/.kotak-cli")
SESSION_FILE = os.path.join(SESSION_DIR, "session.json")
ENV_FILE = os.path.join(SESSION_DIR, ".env")

DEFAULT_ENVIRONMENT = "prod"


class HFError(Exception):
    """Structured error carrying a machine-readable code."""

    def __init__(self, message, code="API_ERROR"):
        super().__init__(message)
        self.message = message
        self.code = code


# --- Filesystem helpers --------------------------------------------------

def _ensure_dir():
    os.makedirs(SESSION_DIR, exist_ok=True)


# --- Credentials / dotenv ------------------------------------------------

def load_env():
    """Load credentials from ~/.kotak-cli/.env (and process env) into a dict.

    Recognised keys (env var -> returned key):
        KOTAK_CONSUMER_KEY     -> consumer_key
        KOTAK_CONSUMER_SECRET  -> consumer_secret
        KOTAK_MOBILE / KOTAK_MOBILE_NUMBER -> mobile_number
        KOTAK_PASSWORD         -> password
        KOTAK_UCC              -> ucc
        KOTAK_MPIN             -> mpin
        KOTAK_ENVIRONMENT      -> environment
        KOTAK_NEO_FIN_KEY      -> neo_fin_key
    """
    # Load the .env file into os.environ if present (does not override real env).
    try:
        from dotenv import load_dotenv
        if os.path.exists(ENV_FILE):
            load_dotenv(ENV_FILE, override=False)
    except ImportError:
        # python-dotenv missing; fall back to manual parse so we still work.
        if os.path.exists(ENV_FILE):
            with open(ENV_FILE) as fh:
                for raw in fh:
                    line = raw.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))

    return {
        "consumer_key": os.environ.get("KOTAK_CONSUMER_KEY"),
        "consumer_secret": os.environ.get("KOTAK_CONSUMER_SECRET"),
        "mobile_number": os.environ.get("KOTAK_MOBILE") or os.environ.get("KOTAK_MOBILE_NUMBER"),
        "password": os.environ.get("KOTAK_PASSWORD"),
        "ucc": os.environ.get("KOTAK_UCC"),
        "mpin": os.environ.get("KOTAK_MPIN"),
        "environment": os.environ.get("KOTAK_ENVIRONMENT", DEFAULT_ENVIRONMENT),
        "neo_fin_key": os.environ.get("KOTAK_NEO_FIN_KEY"),
        "totp_key": os.environ.get("KOTAK_TOTP_KEY"),
    }


# --- Session persistence -------------------------------------------------

def load_session():
    """Return the saved session dict, or None if no session file exists."""
    if not os.path.exists(SESSION_FILE):
        return None
    try:
        with open(SESSION_FILE) as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None


def save_session(data):
    """Persist session ``data`` (dict) to disk with restrictive permissions."""
    _ensure_dir()
    with open(SESSION_FILE, "w") as fh:
        json.dump(data, fh, indent=2)
    try:
        os.chmod(SESSION_FILE, 0o600)
    except OSError:
        pass
    return SESSION_FILE


def clear_session():
    """Remove the saved session file. Returns True if a file was removed."""
    if os.path.exists(SESSION_FILE):
        os.remove(SESSION_FILE)
        return True
    return False


def session_is_valid(session=None):
    """Heuristic: a session is usable if it carries an edit_token and was
    created on the current calendar day (Kotak tokens expire end-of-day)."""
    session = session or load_session()
    if not session or not session.get("edit_token"):
        return False
    stamp = session.get("logged_in_at")
    if not stamp:
        return False
    try:
        when = datetime.datetime.fromisoformat(stamp)
    except ValueError:
        return False
    return when.date() == datetime.datetime.now().date()


# --- Client construction -------------------------------------------------

def new_client(consumer_key=None, environment=DEFAULT_ENVIRONMENT, neo_fin_key=None):
    """Create a fresh (unauthenticated) NeoAPI client for the login flow."""
    try:
        from neo_api_client import NeoAPI
    except ImportError as exc:
        raise HFError(
            "neo_api_client SDK is not installed in this environment: %s" % exc,
            code="API_ERROR",
        )
    return NeoAPI(environment=environment, consumer_key=consumer_key, neo_fin_key=neo_fin_key)


def session_from_client(client, extra=None):
    """Extract the persistable fields from an authenticated client's config."""
    cfg = client.configuration
    data = {
        "consumer_key": getattr(cfg, "consumer_key", None),
        "environment": getattr(cfg, "host", DEFAULT_ENVIRONMENT),
        "neo_fin_key": getattr(cfg, "neo_fin_key", None),
        "edit_token": getattr(cfg, "edit_token", None),
        "edit_sid": getattr(cfg, "edit_sid", None),
        "edit_rid": getattr(cfg, "edit_rid", None),
        "serverId": getattr(cfg, "serverId", None),
        "base_url": getattr(cfg, "base_url", None),
        "data_center": getattr(cfg, "data_center", None),
        "bearer_token": getattr(cfg, "bearer_token", None),
        "logged_in_at": datetime.datetime.now().isoformat(),
        "token_type": "totp_validate",
    }
    if extra:
        data.update(extra)
    return data


def get_client(session_data=None):
    """Return session data for REST API calls.
    
    Loads the saved session and returns it as a dict. Raises HFError if
    no session or session is stale.
    
    Returns dict with: edit_token, edit_sid, edit_rid, serverId, dataCenter,
    consumer_key, environment, base_url
    """
    session = session_data or load_session()
    if not session:
        raise HFError("No active session. Run `hf login` first.", code="AUTH_REQUIRED")

    if not session.get("edit_token"):
        raise HFError("Session is incomplete. Please run `hf login` again.", code="AUTH_REQUIRED")

    if not session_is_valid(session):
        raise HFError(
            "Session has expired (Kotak tokens are valid for the trading day). "
            "Run `hf login` to refresh.",
            code="AUTH_EXPIRED",
        )
    
    return session
