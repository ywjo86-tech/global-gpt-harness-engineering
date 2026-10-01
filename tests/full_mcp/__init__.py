from __future__ import annotations

import importlib.util
import unittest


def mcp_available() -> bool:
    return importlib.util.find_spec("mcp") is not None


def require_mcp() -> None:
    if importlib.util.find_spec("mcp") is None:
        raise unittest.SkipTest("optional mcp package is not installed")
