from __future__ import annotations

import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from runtime.orchestrator.nvidia_adapter import run_nvidia_reasoning_task


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class NvidiaAdapterTest(unittest.TestCase):
    def test_success_response_is_safe_payload(self) -> None:
        def opener(request, timeout):
            self.assertIn("Authorization", request.headers)
            body = json.loads(request.data)
            self.assertEqual(body["model"], "test-model")
            self.assertEqual(body["max_tokens"], 2048)
            self.assertFalse(body["stream"])
            return _Response({"choices": [{"message": {"content": "answer"}}]})

        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            "os.environ", {"NVIDIA_API_KEY": "secret", "NVIDIA_MODEL": "test-model"}, clear=True
        ):
            result = run_nvidia_reasoning_task(prompt="hello", project_root=temp_dir, urlopen=opener)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["provider"], "nvidia")
            self.assertNotIn("secret", json.dumps(result))

    def test_auth_error_fails_without_retrying_to_codex(self) -> None:
        for status_code in (401, 403):
            with self.subTest(status_code=status_code):
                calls = 0

                def opener(request, timeout):
                    nonlocal calls
                    calls += 1
                    raise urllib.error.HTTPError(request.full_url, status_code, "Unauthorized", {}, io.BytesIO())

                with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
                    "os.environ", {"NVIDIA_API_KEY": "secret", "NVIDIA_MODEL": "test-model"}, clear=True
                ):
                    result = run_nvidia_reasoning_task(prompt="hello", project_root=temp_dir, urlopen=opener)
                self.assertEqual(result["status"], "provider_failed")
                self.assertEqual(result["provider_error_class"], "nvidia_auth_error")
                self.assertEqual(calls, 1)

    def test_missing_key_or_model_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict("os.environ", {}, clear=True):
            result = run_nvidia_reasoning_task(prompt="hello", project_root=Path(temp_dir))
            self.assertEqual(result["provider_error_class"], "nvidia_config_error")

        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            "os.environ", {"NVIDIA_API_KEY": "secret"}, clear=True
        ):
            result = run_nvidia_reasoning_task(prompt="hello", project_root=Path(temp_dir))
            self.assertEqual(result["provider_error_class"], "nvidia_config_error")

    def test_governed_explicit_model_does_not_fall_back_to_environment_model(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            "os.environ", {"NVIDIA_API_KEY": "secret", "NVIDIA_MODEL": "environment-model"}, clear=True
        ):
            result = run_nvidia_reasoning_task(
                prompt="hello", project_root=temp_dir, model=None, require_explicit_model=True
            )
        self.assertEqual(result["status"], "provider_failed")
        self.assertEqual(result["provider_error_class"], "nvidia_config_error")
        self.assertNotEqual(result.get("model"), "environment-model")

    def test_transient_errors_retry_with_classified_terminal_failure(self) -> None:
        cases = ((408, "nvidia_timeout"), (429, "nvidia_rate_limit"), (503, "nvidia_server_error"))
        for status_code, error_class in cases:
            with self.subTest(status_code=status_code):
                calls = 0

                def opener(request, timeout):
                    nonlocal calls
                    calls += 1
                    raise urllib.error.HTTPError(request.full_url, status_code, "failure", {}, io.BytesIO())

                with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
                    "os.environ", {"NVIDIA_API_KEY": "secret", "NVIDIA_MODEL": "test-model"}, clear=True
                ), patch("runtime.orchestrator.nvidia_adapter.time.sleep"):
                    result = run_nvidia_reasoning_task(
                        prompt="hello", project_root=temp_dir, urlopen=opener, max_retries=1
                    )
                self.assertEqual(result["provider_error_class"], error_class)
                self.assertEqual(result["provider_attempts"], 2)
                self.assertEqual(calls, 2)

    def test_invalid_response_and_numeric_config_fail_without_network_retry(self) -> None:
        calls = 0

        def opener(request, timeout):
            nonlocal calls
            calls += 1
            return _Response({"choices": []})

        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            "os.environ", {"NVIDIA_API_KEY": "secret", "NVIDIA_MODEL": "test-model"}, clear=True
        ):
            result = run_nvidia_reasoning_task(prompt="hello", project_root=temp_dir, urlopen=opener)
        self.assertEqual(result["provider_error_class"], "nvidia_invalid_response")
        self.assertEqual(calls, 1)

        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            "os.environ",
            {"NVIDIA_API_KEY": "secret", "NVIDIA_MODEL": "test-model", "NVIDIA_MAX_RETRIES": "-1"},
            clear=True,
        ):
            result = run_nvidia_reasoning_task(prompt="hello", project_root=temp_dir, urlopen=opener)
        self.assertEqual(result["provider_error_class"], "nvidia_config_error")
        self.assertEqual(calls, 1)

    def test_network_timeout_and_other_client_error_are_classified(self) -> None:
        cases = (
            (TimeoutError(), "nvidia_timeout", 2),
            (urllib.error.URLError("offline"), "nvidia_network_error", 2),
            (urllib.error.HTTPError("https://example.invalid", 422, "invalid", {}, io.BytesIO()), "nvidia_client_error", 1),
        )
        for error, error_class, expected_calls in cases:
            with self.subTest(error_class=error_class):
                calls = 0

                def opener(request, timeout):
                    nonlocal calls
                    calls += 1
                    raise error

                with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
                    "os.environ", {"NVIDIA_API_KEY": "secret", "NVIDIA_MODEL": "test-model"}, clear=True
                ), patch("runtime.orchestrator.nvidia_adapter.time.sleep"):
                    result = run_nvidia_reasoning_task(
                        prompt="hello", project_root=temp_dir, urlopen=opener, max_retries=1
                    )
                self.assertEqual(result["provider_error_class"], error_class)
                self.assertEqual(result["provider_attempts"], expected_calls)
                self.assertEqual(calls, expected_calls)


if __name__ == "__main__":
    unittest.main()
