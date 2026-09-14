from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.orchestrator.context_sanitizer import ContextSanitizationError, sanitize_context


class ContextSanitizerTest(unittest.TestCase):
    def test_redacts_known_secret_and_bounds_explicit_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict("os.environ", {"NVIDIA_API_KEY": "secret-value"}, clear=False):
            root = Path(temp_dir)
            (root / "docs").mkdir()
            (root / "docs" / "note.md").write_text("token=secret-value\nsafe", encoding="utf-8")
            result = sanitize_context("api_key=secret-value", ["docs/note.md"], root)
            rendered = result.prompt + result.files[0]["content"]
            self.assertNotIn("secret-value", rendered)
            self.assertIn("[REDACTED_SECRET]", rendered)

    def test_rejects_forbidden_and_unbounded_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".env").write_text("NVIDIA_API_KEY=x", encoding="utf-8")
            with self.assertRaises(ContextSanitizationError):
                sanitize_context("prompt", [".env"], root)
            with self.assertRaises(ContextSanitizationError):
                sanitize_context("prompt", ["../outside.txt"], root)


if __name__ == "__main__":
    unittest.main()
