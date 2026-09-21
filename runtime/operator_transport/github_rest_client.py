"""Bounded GitHub REST client for the OCPv2 private control channel."""
from __future__ import annotations

import json
import stat
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping


PUBLIC_SOURCE_REPOSITORY_ID = 1254385549


class GitHubRESTClientError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class VerifiedRepository:
    repository_id: int
    full_name: str
    private: bool


HTTPTransport = Callable[[str, str, Mapping[str, str], bytes | None], tuple[int, bytes]]


def _urllib_transport(
    method: str,
    url: str,
    headers: Mapping[str, str],
    body: bytes | None,
) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, headers=dict(headers), method=method)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return int(response.status), response.read()
    except urllib.error.HTTPError as exc:
        # Do not surface response bodies: they can echo credentials or private data.
        raise GitHubRESTClientError(f"github HTTP failure: {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise GitHubRESTClientError("github transport unavailable") from exc


class GitHubRESTClient:
    def __init__(
        self,
        *,
        repository_id: int,
        control_pr_number: int,
        token_file: str | Path,
        api_base: str = "https://api.github.com",
        max_comment_bytes: int = 65536,
        http_transport: HTTPTransport | None = None,
    ) -> None:
        if isinstance(repository_id, bool) or int(repository_id) <= 0:
            raise GitHubRESTClientError("repository ID must be positive")
        if int(repository_id) == PUBLIC_SOURCE_REPOSITORY_ID:
            raise GitHubRESTClientError("public source repository cannot be the control repository")
        if isinstance(control_pr_number, bool) or int(control_pr_number) <= 0:
            raise GitHubRESTClientError("control PR number must be positive")
        if isinstance(max_comment_bytes, bool) or int(max_comment_bytes) <= 0:
            raise GitHubRESTClientError("max comment bytes must be positive")
        base = str(api_base or "").rstrip("/")
        if not base.startswith("https://"):
            raise GitHubRESTClientError("GitHub API base must use https")
        self.repository_id = int(repository_id)
        self.control_pr_number = int(control_pr_number)
        self.token_file = Path(token_file).absolute()
        self.api_base = base
        self.max_comment_bytes = int(max_comment_bytes)
        self._http = http_transport or _urllib_transport
        self._verified: VerifiedRepository | None = None

    def _read_token(self) -> str:
        path = self.token_file
        if path.is_symlink():
            raise GitHubRESTClientError("token file must not be a symlink")
        try:
            metadata = path.stat()
        except OSError as exc:
            raise GitHubRESTClientError("token file is unavailable") from exc
        if not stat.S_ISREG(metadata.st_mode):
            raise GitHubRESTClientError("token file must be a regular file")
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise GitHubRESTClientError("token file permissions must deny group/world access")
        try:
            token = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise GitHubRESTClientError("token file is unreadable") from exc
        if not token:
            raise GitHubRESTClientError("token file is empty")
        return token

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        payload: Mapping[str, Any] | None = None,
    ) -> Any:
        token = self._read_token()
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ocpv2-private-control",
        }
        body: bytes | None = None
        if payload is not None:
            body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        try:
            status, response_body = self._http(method, url, headers, body)
        except GitHubRESTClientError:
            raise
        except Exception as exc:
            raise GitHubRESTClientError("github transport failure") from exc
        if status < 200 or status >= 300:
            raise GitHubRESTClientError(f"github HTTP failure: {status}")
        try:
            return json.loads(response_body.decode("utf-8"))
        except Exception as exc:
            raise GitHubRESTClientError("github response is not valid JSON") from exc

    def verify_repository(self) -> VerifiedRepository:
        if self._verified is not None:
            return self._verified
        value = self._request_json("GET", f"{self.api_base}/repositories/{self.repository_id}")
        if not isinstance(value, Mapping):
            raise GitHubRESTClientError("repository response is malformed")
        returned_id = value.get("id")
        if isinstance(returned_id, bool) or returned_id != self.repository_id:
            raise GitHubRESTClientError("repository numeric identity mismatch")
        if value.get("private") is not True:
            raise GitHubRESTClientError("repository must be private")
        full_name = value.get("full_name")
        if not isinstance(full_name, str) or not full_name or "/" not in full_name:
            raise GitHubRESTClientError("repository full_name is invalid")
        self._verified = VerifiedRepository(
            repository_id=self.repository_id,
            full_name=full_name,
            private=True,
        )
        return self._verified

    def list_comments(self) -> tuple[Mapping[str, Any], ...]:
        repository = self.verify_repository()
        url = (
            f"{self.api_base}/repos/{repository.full_name}/issues/{self.control_pr_number}/comments"
            "?per_page=100&sort=created&direction=desc"
        )
        value = self._request_json("GET", url)
        if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
            raise GitHubRESTClientError("comments response is malformed")
        # Query the latest bounded window, but process it chronologically so
        # receipt sequence fencing sees older controls before newer controls.
        return tuple(dict(item) for item in reversed(value))

    def publish_comment(self, body: str) -> Mapping[str, Any]:
        if not isinstance(body, str):
            raise GitHubRESTClientError("comment body must be text")
        encoded = body.encode("utf-8")
        if len(encoded) > self.max_comment_bytes:
            raise GitHubRESTClientError("comment exceeds configured byte limit")
        repository = self.verify_repository()
        url = f"{self.api_base}/repos/{repository.full_name}/issues/{self.control_pr_number}/comments"
        value = self._request_json("POST", url, payload={"body": body})
        if not isinstance(value, Mapping):
            raise GitHubRESTClientError("comment response is malformed")
        return dict(value)
