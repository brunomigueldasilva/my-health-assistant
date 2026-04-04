import sys
sys.path.insert(0, ".")
try:
    from tools.credential_store import get_telegram_token
    print("ok" if get_telegram_token() else "missing")
except Exception:
    print("missing")
