"""Bounded JSON HTTP transport with no SDK/environment credential fallback."""

from __future__ import annotations

import json
import http.client
import ipaddress
import re
import socket
import ssl
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .base import ProviderError


@dataclass(frozen=True, slots=True)
class JsonResponse:
    status: int
    headers: dict[str, str]
    payload: object


class JsonTransport(Protocol):
    def request_json(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        body: object | None,
        timeout_seconds: float,
        max_response_bytes: int,
        allowed_hosts: frozenset[str],
    ) -> JsonResponse: ...


class TextTransport(Protocol):
    def request_text(
        self,
        *,
        url: str,
        timeout_seconds: float,
        max_response_bytes: int,
        allowed_hosts: frozenset[str],
    ) -> str: ...


class UrllibJsonTransport:
    def __init__(
        self,
        *,
        max_attempts: int = 2,
        sleep_fn=time.sleep,
        debug_trace_sink: Callable[[dict[str, object]], None] | None = None,
    ) -> None:
        if not 1 <= max_attempts <= 3:
            raise ValueError("provider HTTP attempts must be within 1..3")
        self._max_attempts = max_attempts
        self._sleep_fn = sleep_fn
        self._debug_trace_sink = debug_trace_sink

    def request_json(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        body: object | None,
        timeout_seconds: float,
        max_response_bytes: int,
        allowed_hosts: frozenset[str],
    ) -> JsonResponse:
        if timeout_seconds <= 0 or timeout_seconds > 120:
            raise ValueError("provider timeout must be within 0..120 seconds")
        if max_response_bytes <= 0 or max_response_bytes > 8 * 1024 * 1024:
            raise ValueError("provider response limit must be within 0..8 MiB")
        parts = urlsplit(url)
        if (
            parts.scheme.casefold() != "https"
            or parts.username is not None
            or parts.password is not None
            or parts.hostname is None
            or parts.hostname.casefold() not in {value.casefold() for value in allowed_hosts}
        ):
            raise ValueError("provider transport target is outside the fixed HTTPS host set")
        encoded = None
        request_headers = {**headers, "Accept": "application/json"}
        if body is not None:
            encoded = json.dumps(body, separators=(",", ":")).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request = Request(
            url=url,
            data=encoded,
            headers=request_headers,
            method=method,
        )
        self._trace(
            {
                "event": "http.request",
                "method": method.upper(),
                "url": _sanitize_url(url),
                "headers": _sanitize_headers(request_headers),
                "body": _sanitize_json_value(body),
            }
        )
        opener = build_opener(_NoRedirectHandler())
        attempts = self._max_attempts if method.upper() in {"GET", "HEAD"} else 1
        for attempt in range(attempts):
            try:
                with opener.open(request, timeout=timeout_seconds) as response:
                    payload_bytes = response.read(max_response_bytes + 1)
                    self._trace_response(
                        status=int(response.status),
                        headers=response.headers,
                        payload_bytes=payload_bytes,
                    )
                    if len(payload_bytes) > max_response_bytes:
                        raise ProviderError("provider response exceeded the byte limit")
                    payload = json.loads(
                        payload_bytes.decode("utf-8"),
                        object_pairs_hook=_strict_object,
                        parse_constant=_reject_json_constant,
                    )
                    return JsonResponse(
                        status=int(response.status),
                        headers={key.casefold(): value for key, value in response.headers.items()},
                        payload=payload,
                    )
            except HTTPError as error:
                payload_bytes = error.read(max_response_bytes + 1)
                self._trace_response(
                    status=int(error.code),
                    headers=error.headers,
                    payload_bytes=payload_bytes,
                )
                retryable = error.code in {408, 429, 500, 502, 503, 504}
                if retryable and attempt + 1 < attempts:
                    retry_after = error.headers.get("Retry-After") if error.headers else None
                    try:
                        delay = min(2.0, max(0.0, float(retry_after or 0.1)))
                    except ValueError:
                        delay = 0.1
                    self._sleep_fn(delay)
                    continue
                if 300 <= error.code < 400:
                    self._trace_exception(error)
                    raise ProviderError("provider redirect was rejected") from None
                self._trace_exception(error)
                raise ProviderError(f"provider returned HTTP {error.code}") from None
            except URLError as error:
                if attempt + 1 < attempts:
                    self._sleep_fn(0.1)
                    continue
                self._trace_exception(error)
                raise ProviderError("provider network request failed") from None
            except ProviderError as error:
                self._trace_exception(error)
                raise
            except (UnicodeDecodeError, json.JSONDecodeError, _StrictJsonError) as error:
                self._trace_exception(error)
                raise ProviderError("provider returned invalid JSON") from None
        raise AssertionError("provider retry loop exhausted without a terminal outcome")

    def _trace(self, value: dict[str, object]) -> None:
        if self._debug_trace_sink is not None:
            self._debug_trace_sink(value)

    def _trace_response(
        self,
        *,
        status: int,
        headers: object,
        payload_bytes: bytes,
    ) -> None:
        header_items = headers.items() if hasattr(headers, "items") else ()
        self._trace(
            {
                "event": "http.response",
                "status": status,
                "headers": _sanitize_headers(dict(header_items)),
                "raw_body": _sanitize_text(
                    payload_bytes.decode("utf-8", errors="replace")
                ),
            }
        )

    def _trace_exception(self, error: BaseException) -> None:
        self._trace(
            {
                "event": "http.exception",
                "exception": (
                    f"{type(error).__name__}: {_sanitize_text(str(error))}"
                ),
            }
        )


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        del req, fp, code, msg, headers, newurl
        return None


class _StrictJsonError(ValueError):
    pass


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _StrictJsonError("duplicate provider JSON key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise _StrictJsonError(f"non-finite provider JSON value: {value}")


_SECRET_HEADER_NAMES = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "openai-organization",
        "openai-project",
        "set-cookie",
        "x-api-key",
    }
)
_SECRET_TEXT = re.compile(
    r"(?i)(?:bearer\s+[^\s\"']+|sk-[a-z0-9_-]{8,})"
)


def _sanitize_headers(headers: dict[str, object]) -> dict[str, str]:
    return {
        str(name): (
            "<redacted>"
            if str(name).casefold() in _SECRET_HEADER_NAMES
            else _sanitize_text(str(value))
        )
        for name, value in headers.items()
    }


def _sanitize_url(url: str) -> str:
    parts = urlsplit(url)
    hostname = parts.hostname or ""
    host = hostname
    if parts.port is not None:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


def _sanitize_text(value: str) -> str:
    return _SECRET_TEXT.sub("<redacted>", value)


def _sanitize_json_value(value: object) -> object:
    if isinstance(value, dict):
        return {
            str(key): (
                "<redacted>"
                if str(key).casefold()
                in {
                    "authorization",
                    "api_key",
                    "apikey",
                    "credential",
                    "password",
                    "token",
                }
                else _sanitize_json_value(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_json_value(item) for item in value]
    if isinstance(value, str):
        return _sanitize_text(value)
    return value


class FakeJsonTransport:
    """Queue-backed transport used by offline contract tests."""

    def __init__(self, responses: list[JsonResponse]) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []

    def request_json(self, **kwargs: Any) -> JsonResponse:
        self.requests.append(dict(kwargs))
        if not self.responses:
            raise AssertionError("unexpected provider request")
        return self.responses.pop(0)


class UrllibTextTransport:
    """Single-attempt credential-free HTML fetcher for exact official-page binding."""

    def request_text(
        self,
        *,
        url: str,
        timeout_seconds: float,
        max_response_bytes: int,
        allowed_hosts: frozenset[str],
    ) -> str:
        parts = urlsplit(url)
        allowed = {value.casefold() for value in allowed_hosts}
        if (
            parts.scheme.casefold() != "https"
            or parts.username is not None
            or parts.password is not None
            or parts.hostname is None
            or parts.hostname.casefold() not in allowed
        ):
            raise ValueError("official-page fetch target is outside its exact HTTPS host set")
        port = parts.port or 443
        if port != 443:
            raise ValueError("official-page fetch requires the default HTTPS port")
        try:
            addresses = {
                item[4][0]
                for item in socket.getaddrinfo(
                    parts.hostname, port, type=socket.SOCK_STREAM
                )
            }
        except OSError:
            raise ProviderError("official page DNS resolution failed") from None
        if not addresses:
            raise ProviderError("official page DNS returned no addresses")
        parsed_addresses = [ipaddress.ip_address(value) for value in addresses]
        if any(not value.is_global for value in parsed_addresses):
            raise ProviderError("official page DNS resolved to a non-public address")
        pinned_ip = sorted(addresses)[0]
        target = parts.path or "/"
        if parts.query:
            target += f"?{parts.query}"
        connection = _PinnedHttpsConnection(
            hostname=parts.hostname,
            pinned_ip=pinned_ip,
            port=port,
            timeout=timeout_seconds,
        )
        try:
            connection.request(
                "GET",
                target,
                headers={
                    "Accept": "text/html,application/xhtml+xml",
                    "Host": parts.hostname,
                    "User-Agent": "AIEditMachine/0.1",
                },
            )
            response = connection.getresponse()
            if 300 <= response.status < 400:
                raise ProviderError("official-page redirect was rejected") from None
            if response.status < 200 or response.status >= 300:
                raise ProviderError(f"official page returned HTTP {response.status}")
            payload = response.read(max_response_bytes + 1)
            if len(payload) > max_response_bytes:
                raise ProviderError("official page exceeded the byte limit")
            content_type = str(response.headers.get("Content-Type") or "").casefold()
            if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
                raise ProviderError("official page did not return HTML")
            return payload.decode("utf-8", errors="strict")
        except (OSError, UnicodeDecodeError, ssl.SSLError):
            raise ProviderError("official page fetch failed") from None
        finally:
            connection.close()


class _PinnedHttpsConnection(http.client.HTTPSConnection):
    def __init__(
        self,
        *,
        hostname: str,
        pinned_ip: str,
        port: int,
        timeout: float,
    ) -> None:
        super().__init__(hostname, port=port, timeout=timeout, context=ssl.create_default_context())
        self._pinned_ip = pinned_ip

    def connect(self) -> None:
        raw = socket.create_connection((self._pinned_ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


class FakeTextTransport:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []

    def request_text(self, **kwargs: Any) -> str:
        self.requests.append(dict(kwargs))
        if not self.responses:
            raise AssertionError("unexpected official-page request")
        return self.responses.pop(0)
