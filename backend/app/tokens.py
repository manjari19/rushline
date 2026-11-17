"""HMAC-signed admission tokens: proof that the waiting room let this buyer in."""
import base64
import hashlib
import hmac
import json
import time


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _sign(secret: str, body: str) -> str:
    return hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()


def issue(secret: str, buyer_id: str, sale_id: int, ttl_seconds: int) -> str:
    payload = {"b": buyer_id, "s": sale_id, "exp": int(time.time()) + ttl_seconds}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    return f"{body}.{_sign(secret, body)}"


def verify(secret: str, token: str, buyer_id: str, sale_id: int) -> bool:
    """True only if the signature is genuine, unexpired, and bound to this buyer and sale."""
    try:
        body, signature = token.split(".", 1)
        if not hmac.compare_digest(signature, _sign(secret, body)):
            return False
        padded = body + "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, TypeError):
        return False
    return payload["b"] == buyer_id and payload["s"] == sale_id and payload["exp"] > time.time()
