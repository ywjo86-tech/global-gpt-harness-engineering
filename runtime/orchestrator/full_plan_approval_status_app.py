"""Bounded issuer status WSGI endpoint for a separately hosted HTTPS service.

Mount at /status behind a TLS reverse proxy that permits only the host client.
The private signing key and decision database stay on the issuer host.
"""
from __future__ import annotations

import hmac
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .full_plan_approval_issuer import ApprovalIssuerError, FullPlanApprovalIssuer, SAFE, canonical


def create_status_app(*, issuer: FullPlanApprovalIssuer, token_file: str | Path) -> Callable:
    path = Path(token_file)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ApprovalIssuerError("STATUS_TOKEN_CONFIG_INVALID")
    if path.stat().st_mode & 0o777 != 0o600:
        raise ApprovalIssuerError("STATUS_TOKEN_PERMISSIONS_INVALID")
    token = path.read_text(encoding="utf-8").strip()
    if len(token) < 32 or not SAFE.fullmatch(token):
        raise ApprovalIssuerError("STATUS_TOKEN_CONFIG_INVALID")

    def app(environ, start_response):
        def response(code, payload):
            body = canonical(payload)
            start_response(code, [
                ("Content-Type", "application/json"),
                ("Content-Length", str(len(body))),
                ("Cache-Control", "no-store"),
            ])
            return [body]

        if (environ.get("PATH_INFO") != "/status"
                or environ.get("REQUEST_METHOD") != "POST"):
            return response("404 Not Found", {"error": "NOT_FOUND"})
        supplied = environ.get("HTTP_AUTHORIZATION", "")
        if not hmac.compare_digest(supplied, "Bearer " + token):
            return response("401 Unauthorized", {"error": "UNAUTHORIZED"})
        if environ.get("CONTENT_TYPE", "").split(";", 1)[0] != "application/json":
            return response("400 Bad Request", {"error": "REQUEST_INVALID"})
        length = environ.get("CONTENT_LENGTH", "")
        if not length.isdecimal() or not 1 <= int(length) <= 2048:
            return response("400 Bad Request", {"error": "REQUEST_INVALID"})
        try:
            data = json.loads(environ["wsgi.input"].read(int(length)))
            if not isinstance(data, dict) or set(data) != {
                "decision_id", "activation_id", "challenge"
            }:
                raise ValueError("fields")
            envelope = issuer.status(
                decision_id=data["decision_id"],
                activation_id=data["activation_id"],
                challenge=data["challenge"],
                now=datetime.now(timezone.utc),
            )
        except (ValueError, TypeError, KeyError, UnicodeError):
            return response("400 Bad Request", {"error": "REQUEST_INVALID"})
        return response("200 OK", envelope)

    return app
