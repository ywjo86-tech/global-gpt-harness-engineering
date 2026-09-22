#!/usr/bin/env python3
"""Review-only manual activation/rollback instructions for OCPv2.

This helper deliberately never invokes a service manager.  It only projects the exact
paths produced by bootstrap installation and the commands that a human may choose to run
at the separately authorized activation boundary.
"""
from __future__ import annotations

from typing import Any


def manual_activation_preview(rendered: Any) -> dict[str, object]:
    for field in ("env_path", "service_path", "timer_path"):
        if not hasattr(rendered, field):
            raise ValueError("rendered package is incomplete")
    return {
        "service_manager_invoked": False,
        "generated_paths": {
            "env": str(rendered.env_path),
            "service": str(rendered.service_path),
            "timer": str(rendered.timer_path),
        },
        "activation_commands": [
            "systemctl --user daemon-reload",
            "systemctl --user enable --now ocpv2.timer",
        ],
        "rollback_commands": [
            "systemctl --user disable --now ocpv2.timer",
            "systemctl --user stop ocpv2.service",
        ],
    }
