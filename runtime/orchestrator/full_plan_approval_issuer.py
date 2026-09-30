"""Issuer-side authority for one authenticated, confirmed Full Plan decision.

Deploy this behind a user-authenticated MCP endpoint. The endpoint must supply
the principal and confirmation identifier from trusted auth/confirmation
context; neither is accepted from the model's tool arguments.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from .full_plan_owner_attestation import SCHEMA as ATTESTATION_SCHEMA
from .full_plan_owner_delegation import EXCLUDED, FIELDS as SCOPE_FIELDS, SCHEMA as SCOPE_SCHEMA

STATUS_SCHEMA = "orchestration.full-plan-owner-status.v1"
SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
HEAD = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


class ApprovalIssuerError(ValueError):
    pass


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _time(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ApprovalIssuerError("TIME_INVALID")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError as exc:
        raise ApprovalIssuerError("TIME_INVALID") from exc


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _scope(scope: Mapping[str, Any], now: datetime) -> None:
    if not isinstance(scope, Mapping) or set(scope) != SCOPE_FIELDS:
        raise ApprovalIssuerError("SCOPE_INVALID")
    if (scope["schema_version"] != SCOPE_SCHEMA
            or any(not isinstance(scope[k], str) or not SAFE.fullmatch(scope[k])
                   for k in ("decision_id", "project_id"))
            or any(not isinstance(scope[k], str) or not SHA.fullmatch(scope[k])
                   for k in ("plan_sha256", "spec_sha256", "runtime_sha256"))
            or not isinstance(scope["source_head"], str)
            or not HEAD.fullmatch(scope["source_head"])
            or not isinstance(scope["gate_ids"], list) or not scope["gate_ids"]
            or any(not isinstance(g, str) or not SAFE.fullmatch(g) for g in scope["gate_ids"])
            or len(set(scope["gate_ids"])) != len(scope["gate_ids"])
            or not isinstance(scope["excluded_actions"], list)
            or len(scope["excluded_actions"]) != len(EXCLUDED)
            or set(scope["excluded_actions"]) != EXCLUDED):
        raise ApprovalIssuerError("SCOPE_INVALID")
    start, end = _time(scope["issued_at"]), _time(scope["expires_at"])
    if (now.tzinfo is None or not start <= now < end
            or (end - start).total_seconds() > 86400):
        raise ApprovalIssuerError("SCOPE_EXPIRED")


class FullPlanApprovalIssuer:
    def __init__(self, *, database: str | Path, private_key: str | Path,
                 owner_user_id: str, owner_actor_id: str, issuer: str, audience: str):
        self.database = Path(database)
        self.private_key = Path(private_key)
        self.owner_user_id = owner_user_id
        self.owner_actor_id = owner_actor_id
        self.issuer = issuer
        self.audience = audience
        if (not self.database.parent.is_dir() or self.database.is_symlink()
                or not self.private_key.is_absolute() or self.private_key.is_symlink()
                or not self.private_key.is_file()
                or not owner_user_id or not owner_actor_id.isdecimal()
                or not issuer or not audience):
            raise ApprovalIssuerError("ISSUER_CONFIG_INVALID")
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS decisions(
                decision_id TEXT PRIMARY KEY, confirmation_id TEXT UNIQUE NOT NULL,
                user_id TEXT NOT NULL, scope_sha256 TEXT NOT NULL,
                activation_id TEXT, revoked INTEGER NOT NULL DEFAULT 0,
                attestation TEXT NOT NULL)""")

    def _connect(self):
        db = sqlite3.connect(self.database, timeout=10, isolation_level=None)
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def _sign(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="owner-issuer-") as directory:
            data, signature = Path(directory) / "data", Path(directory) / "signature"
            data.write_bytes(canonical(payload))
            result = subprocess.run(
                ["openssl", "pkeyutl", "-sign", "-inkey", str(self.private_key),
                 "-rawin", "-in", str(data), "-out", str(signature)],
                capture_output=True, check=False, timeout=10)
            if result.returncode != 0:
                raise ApprovalIssuerError("SIGNING_FAILED")
            encoded = base64.urlsafe_b64encode(signature.read_bytes()).rstrip(b"=").decode()
        return {"payload": dict(payload), "signature": encoded}

    def issue(self, *, scope: Mapping[str, Any], authenticated_user_id: str,
              trusted_confirmation_id: str, now: datetime) -> dict[str, Any]:
        if authenticated_user_id != self.owner_user_id:
            raise ApprovalIssuerError("OWNER_AUTH_REQUIRED")
        if (not isinstance(trusted_confirmation_id, str)
                or not SAFE.fullmatch(trusted_confirmation_id)):
            raise ApprovalIssuerError("CONFIRMATION_REQUIRED")
        _scope(scope, now)
        end = min(_time(scope["expires_at"]), now + timedelta(hours=24))
        payload = {
            "schema_version": ATTESTATION_SCHEMA, "issuer": self.issuer,
            "audience": self.audience, "decision_id": scope["decision_id"],
            "owner_actor_id": self.owner_actor_id,
            "confirmation_id": trusted_confirmation_id, "scope": dict(scope),
            "issued_at": _stamp(now), "expires_at": _stamp(end),
        }
        envelope = self._sign(payload)
        encoded = canonical(envelope).decode()
        with self._connect() as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                db.execute("""INSERT INTO decisions
                    (decision_id, confirmation_id, user_id, scope_sha256, attestation)
                    VALUES (?, ?, ?, ?, ?)""",
                    (scope["decision_id"], trusted_confirmation_id, authenticated_user_id,
                     hashlib.sha256(canonical(scope)).hexdigest(), encoded))
                db.execute("COMMIT")
            except sqlite3.IntegrityError as exc:
                db.execute("ROLLBACK")
                raise ApprovalIssuerError("DECISION_OR_CONFIRMATION_REPLAY") from exc
        return envelope

    def revoke(self, *, decision_id: str, authenticated_user_id: str) -> None:
        if authenticated_user_id != self.owner_user_id:
            raise ApprovalIssuerError("OWNER_AUTH_REQUIRED")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT user_id FROM decisions WHERE decision_id=?",
                             (decision_id,)).fetchone()
            if row is None or row[0] != authenticated_user_id:
                db.execute("ROLLBACK")
                raise ApprovalIssuerError("DECISION_UNKNOWN")
            db.execute("UPDATE decisions SET revoked=1 WHERE decision_id=?", (decision_id,))
            db.execute("COMMIT")

    def status(self, *, decision_id: str, activation_id: str,
               challenge: str, now: datetime) -> dict[str, Any]:
        """Atomically bind first use to one activation and sign a fresh answer."""
        if (not isinstance(activation_id, str) or not SAFE.fullmatch(activation_id)
                or not isinstance(challenge, str) or not SAFE.fullmatch(challenge)
                or len(challenge) < 32 or now.tzinfo is None):
            raise ApprovalIssuerError("STATUS_REQUEST_INVALID")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT scope_sha256, activation_id, revoked, attestation
                                FROM decisions WHERE decision_id=?""",
                             (decision_id,)).fetchone()
            if row is None:
                db.execute("ROLLBACK")
                raise ApprovalIssuerError("DECISION_UNKNOWN")
            scope_sha, bound, revoked, raw = row
            attestation = json.loads(raw)
            expires = _time(attestation["payload"]["expires_at"])
            active = not revoked and now < expires and (bound is None or bound == activation_id)
            if active and bound is None:
                db.execute("UPDATE decisions SET activation_id=? WHERE decision_id=?",
                           (activation_id, decision_id))
            db.execute("COMMIT")
        payload = {
            "schema_version": STATUS_SCHEMA, "issuer": self.issuer,
            "audience": self.audience, "decision_id": decision_id,
            "scope_sha256": scope_sha, "activation_id": activation_id,
            "challenge": challenge, "active": active, "checked_at": _stamp(now),
        }
        return self._sign(payload)
