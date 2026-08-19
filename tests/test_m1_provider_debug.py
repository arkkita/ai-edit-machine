from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_edit_machine.provider_debug import (  # noqa: E402
    DEBUG_HARD_CAP_MICRO_USD,
    DEBUG_MODEL,
    DEBUG_RESERVED_MICRO_USD,
    load_fixture,
    run_replay,
)
from ai_edit_machine.providers.base import ProviderError  # noqa: E402
from ai_edit_machine.providers.transport import UrllibJsonTransport  # noqa: E402


FIXTURE = ROOT / "tests" / "fixtures" / "m1_provider_debug_response.json"


class _MockResponse:
    status = 200

    def __init__(self, payload: bytes) -> None:
        self.headers = Message()
        self.headers["Content-Type"] = "application/json"
        self.headers["X-Request-Id"] = "req_mock_transport"
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        del exc_type, exc, traceback
        return False

    def read(self, limit: int) -> bytes:
        return self._payload[:limit]


class _AssertingOpener:
    def __init__(self, response: _MockResponse) -> None:
        self.response = response
        self.requests = []

    def open(self, request, *, timeout: float):
        self.requests.append((request, timeout))
        return self.response


class ProviderDebugTests(unittest.TestCase):
    def test_contract_fixture_reaches_worker_ui_boundary_in_under_one_request(self) -> None:
        report = run_replay(load_fixture(FIXTURE), assert_contract=True)

        self.assertTrue(report["development_only"])
        self.assertEqual(report["hard_cap_micro_usd"], DEBUG_HARD_CAP_MICRO_USD)
        self.assertEqual(report["reserved_micro_usd"], DEBUG_RESERVED_MICRO_USD)
        self.assertLessEqual(DEBUG_RESERVED_MICRO_USD, DEBUG_HARD_CAP_MICRO_USD)
        self.assertLessEqual(DEBUG_HARD_CAP_MICRO_USD, 50_000)
        self.assertEqual(report["provider_outcome"], "SUCCESS")
        self.assertEqual(
            report["counts"],
            {
                "raw_provider_results": 2,
                "parsed_results": 2,
                "normalized_evidence": 3,
                "evidence_surviving_gates": 3,
                "ranked_opportunities": 1,
                "opportunities_returned_to_ui": 1,
            },
        )
        envelope = report["worker_envelope"]
        self.assertEqual(envelope["messageType"], "research.result")
        self.assertEqual(len(envelope["payload"]["result"]["opportunities"]), 1)

    def test_contract_trace_prints_all_headers_and_redacts_authorization(self) -> None:
        report = run_replay(load_fixture(FIXTURE), assert_contract=True)
        request = next(
            item for item in report["events"] if item["event"] == "http.request"
        )

        self.assertEqual(request["method"], "POST")
        self.assertEqual(request["url"], "https://api.openai.com/v1/responses")
        self.assertEqual(
            {name.casefold() for name in request["headers"]},
            {"accept", "authorization", "content-type"},
        )
        authorization_name = next(
            name for name in request["headers"] if name.casefold() == "authorization"
        )
        self.assertEqual(request["headers"][authorization_name], "<redacted>")
        serialized = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("debug-fixture-credential", serialized)
        self.assertEqual(request["body"]["model"], DEBUG_MODEL)
        self.assertFalse(request["body"]["store"])

    def test_real_transport_builds_documented_headers_and_captures_raw_response(self) -> None:
        payload = b'{"id":"resp_mock","status":"completed"}'
        opener = _AssertingOpener(_MockResponse(payload))
        events: list[dict[str, object]] = []
        transport = UrllibJsonTransport(max_attempts=1, debug_trace_sink=events.append)

        with patch(
            "ai_edit_machine.providers.transport.build_opener", return_value=opener
        ):
            response = transport.request_json(
                method="POST",
                url="https://api.openai.com/v1/responses",
                headers={"Authorization": "Bearer secret-must-not-appear"},
                body={"model": DEBUG_MODEL, "store": False},
                timeout_seconds=1,
                max_response_bytes=1_024,
                allowed_hosts=frozenset({"api.openai.com"}),
            )

        self.assertEqual(response.status, 200)
        request, timeout = opener.requests[0]
        self.assertEqual(timeout, 1)
        actual_headers = {
            name.casefold(): value for name, value in request.header_items()
        }
        self.assertEqual(
            set(actual_headers), {"accept", "authorization", "content-type"}
        )
        self.assertEqual(actual_headers["accept"], "application/json")
        self.assertEqual(actual_headers["content-type"], "application/json")
        self.assertEqual(
            json.loads(request.data.decode("utf-8")),
            {"model": DEBUG_MODEL, "store": False},
        )
        self.assertEqual(events[1]["status"], 200)
        self.assertEqual(events[1]["raw_body"], payload.decode("utf-8"))
        self.assertNotIn("secret-must-not-appear", json.dumps(events))

    def test_http_error_trace_keeps_status_headers_body_and_exact_exception(self) -> None:
        headers = Message()
        headers["Content-Type"] = "application/json"
        headers["X-Request-Id"] = "req_unauthorized"
        error = HTTPError(
            "https://api.openai.com/v1/responses",
            401,
            "Unauthorized",
            headers,
            io.BytesIO(b'{"error":{"message":"invalid key"}}'),
        )

        class ErrorOpener:
            def open(self, request, *, timeout: float):
                del request, timeout
                raise error

        events: list[dict[str, object]] = []
        transport = UrllibJsonTransport(max_attempts=1, debug_trace_sink=events.append)
        with patch(
            "ai_edit_machine.providers.transport.build_opener",
            return_value=ErrorOpener(),
        ):
            with self.assertRaisesRegex(ProviderError, "HTTP 401"):
                transport.request_json(
                    method="POST",
                    url="https://api.openai.com/v1/responses",
                    headers={"Authorization": "Bearer another-secret"},
                    body={"model": DEBUG_MODEL},
                    timeout_seconds=1,
                    max_response_bytes=1_024,
                    allowed_hosts=frozenset({"api.openai.com"}),
                )

        response_event = next(item for item in events if item["event"] == "http.response")
        exception_event = next(
            item for item in events if item["event"] == "http.exception"
        )
        self.assertEqual(response_event["status"], 401)
        self.assertIn("invalid key", response_event["raw_body"])
        self.assertIn("HTTPError: HTTP Error 401", exception_event["exception"])
        self.assertNotIn("another-secret", json.dumps(events))

    def test_captured_http_failure_replays_without_promoting_seed_metadata(self) -> None:
        value = json.loads(FIXTURE.read_text(encoding="utf-8"))
        value["response"] = {
            "status": 429,
            "headers": {
                "Content-Type": "application/json",
                "OpenAI-Organization": "org-must-not-appear",
                "OpenAI-Project": "project-must-not-appear",
                "Set-Cookie": "cookie-must-not-appear",
            },
            "body": {
                "error": {
                    "type": "insufficient_quota",
                    "code": "credit_balance_exhausted",
                    "message": "No credits remaining.",
                }
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = Path(directory) / "response.json"
            fixture_path.write_text(json.dumps(value), encoding="utf-8")
            report = run_replay(load_fixture(fixture_path), assert_contract=True)

        self.assertEqual(report["provider_outcome"], "ERROR")
        self.assertEqual(report["provider_error"], "provider returned HTTP 429")
        self.assertEqual(report["counts"]["raw_provider_results"], 0)
        self.assertEqual(report["counts"]["parsed_results"], 0)
        self.assertEqual(report["counts"]["evidence_surviving_gates"], 0)
        self.assertEqual(report["counts"]["ranked_opportunities"], 0)
        self.assertEqual(report["counts"]["opportunities_returned_to_ui"], 0)
        self.assertEqual(report["worker_envelope"]["messageType"], "research.error")
        serialized = json.dumps(report)
        self.assertNotIn("org-must-not-appear", serialized)
        self.assertNotIn("project-must-not-appear", serialized)
        self.assertNotIn("cookie-must-not-appear", serialized)


if __name__ == "__main__":
    unittest.main()
