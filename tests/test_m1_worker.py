from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_edit_machine.worker_protocol import (  # noqa: E402
    WorkerProtocolError,
    read_json_frame,
)
from ai_edit_machine.providers.base import (  # noqa: E402
    CancellationToken,
    ProviderBatch,
    ProviderCancelledError,
    ProviderError,
    ProviderRunOutcome,
    ProviderUsage,
)
from ai_edit_machine.m1_contracts import ResearchSynthesisDraftV2  # noqa: E402
from ai_edit_machine.research.synthesis import SynthesisProviderResult  # noqa: E402
from ai_edit_machine.research.intent import intent_from_query  # noqa: E402
from ai_edit_machine.providers.transport import FakeJsonTransport, JsonResponse  # noqa: E402
from ai_edit_machine.provider_debug_contract import (  # noqa: E402
    DEBUG_MODE,
    DEBUG_PROMPT,
    DEBUG_SEED_EPISODE,
    DEBUG_SEED_EPISODE_TITLE,
    DEBUG_SEED_EVENT_AT,
    DEBUG_SEED_PROVIDER_RECORD_ID,
    DEBUG_SEED_SEASON,
    DEBUG_SEED_SHOW,
    DEBUG_SEED_URL,
)
from ai_edit_machine.worker import (  # noqa: E402
    _Capability,
    _ExecutePayload,
    _PreflightPayload,
    _OneShotOpenAIDebugTransport,
    _StartedProvider,
    _WorkerRuntime,
    _handle,
    _is_m1_provider_debug,
    _preflight,
    _recorded_outcome,
    _terminal_from_provider_batches,
    _validate_wire,
)


def _hash_intent(intent: dict[str, object]) -> str:
    payload = json.dumps(
        intent,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _intent(prompt: str = "romance TV from the last three days") -> dict[str, object]:
    return {
        "schemaVersion": "2.0.0",
        "prompt": prompt,
        "mediaKinds": None,
        "region": None,
        "freshnessDays": None,
        "spoilerPolicy": None,
        "exclusions": None,
        "maxResults": None,
    }


def _envelope(request_id, message_type: str, payload: dict[str, object]):
    return {
        "protocolVersion": "1.0.0",
        "requestId": str(request_id),
        "messageType": message_type,
        "payload": payload,
    }


def _tvmaze_capability(**updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "providerRunId": str(uuid4()),
        "reservationId": str(uuid4()),
        "plannedCallId": str(uuid4()),
        "provider": "tvmaze",
        "operation": "research.metadata",
        "configuredModel": None,
        "resolvedModel": None,
        "maximumMicroUsd": 0,
        "maxRequests": 3,
        "maxToolCalls": 0,
        "maxInputTokens": 0,
        "maxOutputTokens": 0,
        "allowOneRepair": False,
        "retentionMode": "public metadata",
        "dataUseMode": "public metadata",
        "noStorageMode": "not applicable",
        "privacyMode": "public_metadata",
        "policyClass": "tvmaze-metadata-v1",
        "evidenceTtlSeconds": 86_400,
        "refreshAfterSeconds": 21_600,
        "purgeAfterSeconds": 2_592_000,
        "deletionAfterSeconds": None,
        "credential": None,
        "providerConfig": {"kind": "TVMAZE"},
    }
    value.update(updates)
    return value


def _openai_capability(
    *, operation: str, config: dict[str, object], **updates: object
) -> dict[str, object]:
    value: dict[str, object] = {
        "providerRunId": str(uuid4()),
        "reservationId": str(uuid4()),
        "plannedCallId": str(uuid4()),
        "provider": "openai",
        "operation": operation,
        "configuredModel": "gpt-5.6-luna",
        "resolvedModel": "gpt-5.6-luna-2026-08-15",
        "maximumMicroUsd": 1_000,
        "maxRequests": 2,
        "maxToolCalls": 1 if operation == "research.web_verify" else 0,
        "maxInputTokens": 60_000 if operation == "research.synthesize" else 30_000,
        "maxOutputTokens": 1_000,
        "allowOneRepair": operation == "research.synthesize",
        "retentionMode": "up to 30 days",
        "dataUseMode": "no training by default",
        "noStorageMode": "store=false",
        "privacyMode": "store_false",
        "policyClass": "openai-web-evidence-v1",
        "evidenceTtlSeconds": 43_200,
        "refreshAfterSeconds": 21_600,
        "purgeAfterSeconds": 2_592_000,
        "deletionAfterSeconds": None,
        "credential": "test-only-secret",
        "providerConfig": config,
    }
    value.update(updates)
    return value


class WorkerProcess:
    def __init__(self) -> None:
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(ROOT / "src")
        self.process = subprocess.Popen(
            [sys.executable, "-m", "ai_edit_machine.worker"],
            cwd=ROOT,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert self.process.stdin is not None
        assert self.process.stdout is not None
        self.stdin = self.process.stdin
        self.stdout = self.process.stdout

    def read(self) -> dict[str, object]:
        line = self.stdout.readline()
        if not line:
            detail = ""
            if self.process.poll() is not None and self.process.stderr is not None:
                detail = self.process.stderr.read().decode("utf-8", errors="replace")
            raise AssertionError(
                f"worker reached unexpected EOF (return={self.process.poll()}): {detail}"
            )
        return json.loads(line)

    def send(self, value: dict[str, object]) -> None:
        self.stdin.write(
            json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            + b"\n"
        )
        self.stdin.flush()

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=5)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if stream is not None and not stream.closed:
                stream.close()


class M1WorkerTests(unittest.TestCase):
    def test_verified_release_rebuilds_worker_before_tauri(self) -> None:
        release_script = (
            ROOT / "scripts" / "build_verified_m1_release.ps1"
        ).read_text(encoding="utf-8")
        worker_build = release_script.find("build_worker_bundle.ps1")
        worker_invocation = release_script.find(
            "powershell.exe -NoProfile -ExecutionPolicy Bypass -File $workerBuilder"
        )
        tauri_build = release_script.find("npm.cmd run tauri:build")
        self.assertGreaterEqual(worker_build, 0)
        self.assertGreater(worker_invocation, worker_build)
        self.assertGreater(tauri_build, worker_invocation)

    def test_provider_failure_is_not_rendered_as_an_honest_no_opportunity(self) -> None:
        self.assertIsNone(
            _terminal_from_provider_batches(
                (ProviderBatch(provider="tvmaze", evidence=()),)
            )
        )
        cases = (
            (
                ProviderBatch(
                    provider="openai",
                    evidence=(),
                    outcome=ProviderRunOutcome.ERROR,
                    error="provider returned HTTP 400",
                ),
                "research.error",
            ),
            (
                ProviderBatch(
                    provider="openai",
                    evidence=(),
                    outcome=ProviderRunOutcome.REFUSAL,
                    refusal="request refused",
                ),
                "research.refusal",
            ),
            (
                ProviderBatch(
                    provider="openai",
                    evidence=(),
                    outcome=ProviderRunOutcome.INCOMPLETE,
                    incomplete="response incomplete",
                ),
                "research.incomplete",
            ),
        )
        for batch, expected_type in cases:
            with self.subTest(expected_type=expected_type):
                terminal = _terminal_from_provider_batches((batch,))
                self.assertIsNotNone(terminal)
                assert terminal is not None
                self.assertEqual(terminal[0], expected_type)
                self.assertIn("openai research did not complete", terminal[1])
                self.assertLessEqual(len(terminal[1]), 1_000)

    def test_preflight_reports_privacy_and_has_typed_error_envelope(self) -> None:
        payload = _validate_wire(
            _PreflightPayload,
            {
                "schemaVersion": "1.0.0",
                "provider": "tvmaze",
                "configuredModel": None,
                "credential": None,
            },
        )
        assert isinstance(payload, _PreflightPayload)
        with patch(
            "ai_edit_machine.worker.UrllibJsonTransport.request_json",
            return_value=JsonResponse(200, {}, []),
        ):
            result = _preflight(payload)
        self.assertEqual(result["privacyMode"], "public_metadata")
        self.assertTrue(result["available"])

        youtube_payload = _validate_wire(
            _PreflightPayload,
            {
                "schemaVersion": "1.0.0",
                "provider": "youtube",
                "configuredModel": None,
                "credential": "test-youtube-key",
            },
        )
        assert isinstance(youtube_payload, _PreflightPayload)
        with patch(
            "ai_edit_machine.worker.UrllibJsonTransport.request_json",
            return_value=JsonResponse(200, {}, {"items": []}),
        ):
            youtube_result = _preflight(youtube_payload)
        self.assertEqual(
            youtube_result["retentionMode"],
            "Public official-channel metadata is refreshed or deleted within 30 days.",
        )
        self.assertEqual(
            youtube_result["dataUseMode"],
            "Exact trusted-title search with local acceptance restricted to reviewed official channel IDs; no audiovisual retrieval.",
        )
        self.assertEqual(
            youtube_result["noStorageMode"],
            "Only canonical public metadata is normalized; no media or transcripts are requested.",
        )
        self.assertEqual(youtube_result["privacyMode"], "official_metadata_only")

        class Runtime:
            def __init__(self) -> None:
                self.emitted = []

            def has_active_job(self) -> bool:
                return False

            def emit(self, request_id, message_type, value):
                self.emitted.append((request_id, message_type, value))

        runtime = Runtime()
        request_id = uuid4()
        self.assertTrue(
            _handle(
                runtime,  # type: ignore[arg-type]
                _envelope(
                    request_id,
                    "provider.preflight",
                    {
                        "schemaVersion": "1.0.0",
                        "provider": "unknown",
                        "configuredModel": None,
                        "credential": None,
                    },
                ),
            )
        )
        self.assertEqual(runtime.emitted[0][1], "provider.preflight.error")
        self.assertEqual(runtime.emitted[0][2]["provider"], "unknown")
        self.assertNotIn("credential", runtime.emitted[0][2])

    def test_capability_privacy_drift_is_rejected(self) -> None:
        with self.assertRaisesRegex(Exception, "privacy mode"):
            _validate_wire(
                _Capability,
                _tvmaze_capability(privacyMode="zdr"),
            )

    def test_verifier_only_diagnostic_requires_the_exact_reserved_shape(self) -> None:
        intent = _intent()
        capability = _openai_capability(
            operation="research.web_verify",
            config={
                "kind": "OPENAI_WEB",
                "registryVersion": "test-registry",
                "searchContextSize": "low",
                "requestBodyMaxInputTokens": 30_000,
                "requestMaxToolCalls": 4,
                "officialHosts": ["example.com"],
            },
            maximumMicroUsd=91_200,
            maxRequests=6,
            maxToolCalls=6,
            maxInputTokens=120_000,
            maxOutputTokens=6_000,
            allowOneRepair=False,
        )
        payload = {
            "schemaVersion": "1.0.0",
            "jobId": str(uuid4()),
            "researchRunId": str(uuid4()),
            "inputSha256": _hash_intent(intent),
            "intent": intent,
            "normalizedIntent": {},
            "capabilities": [_tvmaze_capability(maxRequests=16), capability],
            "generatedAt": "2026-08-15T12:00:00Z",
        }
        self.assertIsInstance(_validate_wire(_ExecutePayload, payload), _ExecutePayload)

        overbroad = json.loads(json.dumps(payload))
        overbroad["capabilities"][1]["maxRequests"] = 7
        with self.assertRaisesRegex(Exception, "synthesis capability"):
            _validate_wire(_ExecutePayload, overbroad)

    def test_development_provider_debug_requires_the_exact_one_shot_shape(self) -> None:
        intent = {
            "schemaVersion": "2.0.0",
            "prompt": DEBUG_PROMPT,
            "mediaKinds": ["TV_EPISODE"],
            "region": "US",
            "freshnessDays": 14,
            "spoilerPolicy": "CURRENT_EPISODE",
            "exclusions": [],
            "maxResults": 5,
        }
        normalized = intent_from_query(DEBUG_PROMPT, region="US").model_dump(
            mode="json"
        )
        payload = {
            "schemaVersion": "1.0.0",
            "jobId": str(uuid4()),
            "researchRunId": str(uuid4()),
            "inputSha256": _hash_intent(intent),
            "intent": intent,
            "normalizedIntent": normalized,
            "capabilities": [
                _openai_capability(
                    operation="research.web_verify",
                    config={
                        "kind": "OPENAI_WEB",
                        "registryVersion": "m1-openai-web-2026-08-18-r60",
                        "searchContextSize": "low",
                        "requestBodyMaxInputTokens": 120_000,
                        "requestMaxToolCalls": 1,
                        "officialHosts": ["tomsguide.com", "techradar.com"],
                    },
                    configuredModel="gpt-5.6-luna",
                    resolvedModel="gpt-5.6-luna",
                    maximumMicroUsd=49_960,
                    maxRequests=8,
                    maxToolCalls=1,
                    maxInputTokens=198_000,
                    maxOutputTokens=300,
                    allowOneRepair=False,
                )
            ],
            "generatedAt": "2026-08-19T10:00:00Z",
            "developmentDebug": {
                "schemaVersion": "1.0.0",
                "mode": DEBUG_MODE,
                "traceId": str(uuid4()),
                "seed": {
                    "showOrTitle": DEBUG_SEED_SHOW,
                    "seasonNumber": DEBUG_SEED_SEASON,
                    "episodeNumber": DEBUG_SEED_EPISODE,
                    "episodeTitle": DEBUG_SEED_EPISODE_TITLE,
                    "eventOrReleaseAt": DEBUG_SEED_EVENT_AT,
                    "canonicalUrl": DEBUG_SEED_URL,
                    "providerRecordId": DEBUG_SEED_PROVIDER_RECORD_ID,
                },
            },
        }

        parsed = _validate_wire(_ExecutePayload, payload)
        assert isinstance(parsed, _ExecutePayload)
        self.assertTrue(_is_m1_provider_debug(parsed))

        drifted = json.loads(json.dumps(payload))
        drifted["capabilities"][0]["maxRequests"] = 9
        with self.assertRaisesRegex(Exception, "synthesis capability"):
            _validate_wire(_ExecutePayload, drifted)

    def test_development_provider_debug_transport_blocks_a_second_post(self) -> None:
        inner = FakeJsonTransport([JsonResponse(200, {}, {"id": "resp_one"})])
        transport = _OneShotOpenAIDebugTransport(inner)
        request = {
            "method": "POST",
            "url": "https://api.openai.com/v1/responses",
            "headers": {"Authorization": "Bearer test-only"},
            "body": {"model": "gpt-5.6-luna"},
            "timeout_seconds": 1.0,
            "max_response_bytes": 1_024,
            "allowed_hosts": frozenset({"api.openai.com"}),
        }

        self.assertEqual(transport.request_json(**request).status, 200)
        with self.assertRaisesRegex(ProviderError, "blocked a second OpenAI POST"):
            transport.request_json(**request)
        self.assertEqual(len(inner.requests), 1)

    def test_development_provider_debug_transport_cannot_retry_after_unknown_failure(
        self,
    ) -> None:
        class FailingTransport:
            def __init__(self) -> None:
                self.calls = 0

            def request_json(self, **kwargs):
                del kwargs
                self.calls += 1
                raise ProviderError("unknown transport outcome")

        inner = FailingTransport()
        transport = _OneShotOpenAIDebugTransport(inner)
        request = {
            "method": "POST",
            "url": "https://api.openai.com/v1/responses",
            "headers": {"Authorization": "Bearer test-only"},
            "body": {"model": "gpt-5.6-luna"},
            "timeout_seconds": 1.0,
            "max_response_bytes": 1_024,
            "allowed_hosts": frozenset({"api.openai.com"}),
        }

        with self.assertRaisesRegex(ProviderError, "unknown transport outcome"):
            transport.request_json(**request)
        with self.assertRaisesRegex(ProviderError, "blocked a second OpenAI POST"):
            transport.request_json(**request)
        self.assertEqual(inner.calls, 1)

    def test_execute_accepts_rust_camel_case_reusable_evidence_records(self) -> None:
        intent = _intent()
        source_id = str(uuid4())
        payload = {
            "schemaVersion": "1.0.0",
            "jobId": str(uuid4()),
            "researchRunId": str(uuid4()),
            "inputSha256": _hash_intent(intent),
            "intent": intent,
            "normalizedIntent": {},
            "capabilities": [
                _tvmaze_capability(maxRequests=16),
                _openai_capability(
                    operation="research.web_verify",
                    config={
                        "kind": "OPENAI_WEB",
                        "registryVersion": "test-registry",
                        "searchContextSize": "low",
                        "requestBodyMaxInputTokens": 30_000,
                        "requestMaxToolCalls": 4,
                        "officialHosts": ["example.com"],
                    },
                    maximumMicroUsd=91_200,
                    maxRequests=6,
                    maxToolCalls=6,
                    maxInputTokens=120_000,
                    maxOutputTokens=6_000,
                    allowOneRepair=False,
                ),
            ],
            "reusableEvidenceSources": [{
                "schemaVersion": "2.0.0",
                "sourceId": source_id,
                "provider": "openai",
                "providerRecordId": "cached:example",
                "sourceType": "ARTICLE",
                "canonicalUrl": "https://example.com/current-discussion",
                "title": "Example Show current discussion",
                "authorOrChannel": "Example",
                "sourceCreatedAt": "2026-08-15T10:00:00Z",
                "sourceUpdatedAt": None,
                "pagePublishedAt": "2026-08-15T10:00:00Z",
                "retrievedAt": "2026-08-15T12:00:00Z",
                "query": "Example Show romance",
                "windowStart": "2026-08-12T12:00:00Z",
                "windowEnd": "2026-08-15T12:00:00Z",
                "policyClass": "openai-web-evidence-v1",
                "refreshDueAt": "2026-08-16T00:00:00Z",
                "purgeDueAt": "2026-09-14T12:00:00Z",
                "expiresAt": "2026-08-16T00:00:00Z",
                "deletionRequiredAt": None,
                "contentSha256": "a" * 64,
                "independenceGroup": "owner:example",
            }],
            "reusableEvidenceClaims": [{
                "schemaVersion": "2.0.0",
                "claimId": str(uuid4()),
                "sourceId": source_id,
                "claimKind": "VIEWER_DISCUSSION",
                "excerptType": "PARAPHRASE",
                "text": "Current discussion about Example Show",
                "verification": "SECONDARY_CORROBORATED",
                "episodeLocator": None,
                "quoteFact": None,
                "whyNowEvent": None,
                "sceneFact": None,
                "castFact": None,
                "eventOrReleaseAt": None,
                "confidence": 0.72,
                "supportsWhyNow": True,
                "contentSha256": "b" * 64,
            }],
            "generatedAt": "2026-08-15T12:00:00Z",
        }
        parsed = _validate_wire(_ExecutePayload, payload)
        assert isinstance(parsed, _ExecutePayload)
        self.assertEqual(str(parsed.reusable_evidence_sources[0].source_id), source_id)
        self.assertEqual(str(parsed.reusable_evidence_claims[0].source_id), source_id)

    def test_verifier_only_diagnostic_cannot_enter_synthesis(self) -> None:
        intent = _intent()
        normalized = intent_from_query(str(intent["prompt"])).model_dump(mode="json")
        payload = _validate_wire(
            _ExecutePayload,
            {
                "schemaVersion": "1.0.0",
                "jobId": str(uuid4()),
                "researchRunId": str(uuid4()),
                "inputSha256": _hash_intent(intent),
                "intent": intent,
                "normalizedIntent": normalized,
                "capabilities": [
                    _tvmaze_capability(maxRequests=16),
                    _openai_capability(
                        operation="research.web_verify",
                        config={
                            "kind": "OPENAI_WEB",
                            "registryVersion": "test-registry",
                            "searchContextSize": "low",
                            "requestBodyMaxInputTokens": 30_000,
                            "requestMaxToolCalls": 4,
                            "officialHosts": ["example.com"],
                        },
                        maximumMicroUsd=91_200,
                        maxRequests=6,
                        maxToolCalls=6,
                        maxInputTokens=120_000,
                        maxOutputTokens=6_000,
                        allowOneRepair=False,
                    )
                ],
                "generatedAt": "2026-08-15T12:00:00Z",
            },
        )
        assert isinstance(payload, _ExecutePayload)

        class Runtime(_WorkerRuntime):
            def __init__(self) -> None:
                super().__init__()
                self.emitted: list[tuple[str, dict[str, object]]] = []

            def emit(self, request_id, message_type, value):  # type: ignore[override]
                self.emitted.append((message_type, value))

            def start_provider(self, request_id, job_id, capability, token):  # type: ignore[override]
                return None

        class FakeVerifier:
            name = "openai"

            def __init__(self, **kwargs) -> None:
                pass

            def collect(self, intent, *, authorization, cancellation, context=None):
                del intent, authorization, cancellation, context
                return ProviderBatch(
                    provider="openai",
                    evidence=(),
                    usage=ProviderUsage(
                        configured_model="gpt-5.6-luna",
                        resolved_model="gpt-5.6-luna-2026-08-15",
                        provider_request_id="resp_test_diagnostic",
                        request_count=1,
                        input_tokens=100,
                        cached_input_tokens=0,
                        output_tokens=20,
                        reasoning_tokens=5,
                        tool_calls=1,
                        tool_call_details=("web_search_call:test",),
                    ),
                    outcome=ProviderRunOutcome.ERROR,
                    error="OpenAI structured evidence contract rejected [evidence.0.title:missing]",
                )

        class FakeTVmaze:
            name = "tvmaze"

            def __init__(self, **kwargs) -> None:
                pass

            def collect(self, intent, *, authorization, cancellation):
                del intent, authorization, cancellation
                return ProviderBatch(provider="tvmaze", evidence=())

        runtime = Runtime()
        with (
            patch("ai_edit_machine.worker.TVmazeProvider", FakeTVmaze),
            patch("ai_edit_machine.worker.OpenAIWebVerifier", FakeVerifier),
        ):
            runtime._execute_thread(uuid4(), payload, CancellationToken())
        message_types = [item[0] for item in runtime.emitted]
        self.assertIn("research.error", message_types)
        self.assertNotIn("research.result", message_types)
        terminal = next(value for kind, value in runtime.emitted if kind == "research.error")
        self.assertIn("evidence.0.title:missing", str(terminal["message"]))
        self.assertEqual(len(terminal["providerOutcomes"]), 2)

    def test_started_adapter_error_preserves_unknown_usage_and_rust_ids(self) -> None:
        capability = _validate_wire(_Capability, _tvmaze_capability())
        assert isinstance(capability, _Capability)
        records = []

        class Failure:
            name = "tvmaze"

            def collect(self):
                raise ProviderError("network state is unknown")

        provider = _StartedProvider(
            Failure(), capability, lambda item: None, lambda item, result: records.append(result)
        )
        with self.assertRaises(ProviderError):
            provider.collect()
        self.assertEqual(records, [None])
        outcome = _recorded_outcome(capability, records[0])
        self.assertEqual(outcome["providerRunId"], str(capability.provider_run_id))
        self.assertEqual(outcome["plannedCallId"], str(capability.planned_call_id))
        self.assertEqual(outcome["outcome"], "FAILED")
        self.assertIsNone(outcome["requests"])

        class Cancelled:
            name = "tvmaze"

            def collect(self):
                raise ProviderCancelledError("cancelled after start")

        records.clear()
        provider = _StartedProvider(
            Cancelled(), capability, lambda item: None, lambda item, result: records.append(result)
        )
        with self.assertRaises(ProviderCancelledError):
            provider.collect()
        self.assertIsNone(_recorded_outcome(capability, records[0])["requests"])

    def test_success_outcomes_are_complete_per_operation_without_fake_metrics(self) -> None:
        tv = _validate_wire(_Capability, _tvmaze_capability())
        web = _validate_wire(
            _Capability,
            _openai_capability(
                operation="research.web_verify",
                config={
                    "kind": "OPENAI_WEB",
                    "registryVersion": "test-registry",
                    "searchContextSize": "low",
                    "requestBodyMaxInputTokens": 30_000,
                    "requestMaxToolCalls": 4,
                    "officialHosts": ["example.com"],
                },
            ),
        )
        synthesis = _validate_wire(
            _Capability,
            _openai_capability(
                operation="research.synthesize",
                config={"kind": "OPENAI_SYNTHESIS"},
            ),
        )
        assert isinstance(tv, _Capability)
        assert isinstance(web, _Capability)
        assert isinstance(synthesis, _Capability)
        tv_outcome = _recorded_outcome(
            tv,
            ProviderBatch(
                provider="tvmaze",
                evidence=(),
                usage=ProviderUsage(
                    request_count=3,
                    input_tokens=0,
                    cached_input_tokens=0,
                    output_tokens=0,
                    reasoning_tokens=0,
                ),
            ),
        )
        self.assertEqual(tv_outcome["requests"], 3)
        self.assertEqual(tv_outcome["outputTokens"], 0)
        self.assertFalse(tv_outcome["repairUsed"])

        web_outcome = _recorded_outcome(
            web,
            ProviderBatch(
                provider="openai",
                evidence=(),
                usage=ProviderUsage(
                    configured_model="gpt-5.6-luna",
                    resolved_model="gpt-5.6-luna-2026-08-15",
                    request_count=2,
                    input_tokens=100,
                    cached_input_tokens=20,
                    output_tokens=30,
                    reasoning_tokens=5,
                    tool_calls=1,
                    tool_call_details=("web_search_call:search_1",),
                ),
            ),
        )
        self.assertEqual(web_outcome["toolInvocations"], 1)
        self.assertEqual(web_outcome["cachedInputTokens"], 20)
        self.assertFalse(web_outcome["repairUsed"])

        synthesis_outcome = _recorded_outcome(
            synthesis,
            SynthesisProviderResult(
                provider="openai",
                draft=ResearchSynthesisDraftV2(
                    recommendations=[],
                    no_strong_opportunity_reason="No strong opportunity.",
                ),
                usage=ProviderUsage(
                    configured_model="gpt-5.6-luna",
                    resolved_model="gpt-5.6-luna-2026-08-15",
                    request_count=2,
                    input_tokens=200,
                    output_tokens=80,
                    reasoning_tokens=10,
                ),
            ),
        )
        self.assertTrue(synthesis_outcome["repairUsed"])
        self.assertEqual(synthesis_outcome["requests"], 2)
        self.assertEqual(synthesis_outcome["outputTokens"], 80)

    def test_preview_and_shutdown_are_exact_and_leave_no_trailing_stdout(self) -> None:
        worker = WorkerProcess()
        try:
            self.assertEqual(
                worker.read(),
                {
                    "messageType": "hello",
                    "protocolVersion": "1.0.0",
                    "target": "windows-x86_64",
                    "workerVersion": "0.1.0-m1.1b-dev",
                },
            )
            intent = _intent("x" * 4_000)
            request_id = uuid4()
            worker.send(
                _envelope(
                    request_id,
                    "research.preview",
                    {
                        "schemaVersion": "1.0.0",
                        "intent": intent,
                        "inputSha256": _hash_intent(intent),
                        "nowUnixMs": 1_786_830_000_000,
                    },
                )
            )
            preview = worker.read()
            self.assertEqual(preview["requestId"], str(request_id))
            self.assertEqual(preview["messageType"], "research.preview.result")
            self.assertEqual(
                set(preview["payload"]), {"schemaVersion", "normalizedIntent"}
            )
            shutdown_id = uuid4()
            worker.send(
                _envelope(
                    shutdown_id,
                    "shutdown",
                    {"schemaVersion": "1.0.0", "reason": "test complete"},
                )
            )
            self.assertEqual(
                worker.read(),
                {
                    "messageType": "shutdown.ack",
                    "payload": {"schemaVersion": "1.0.0"},
                    "protocolVersion": "1.0.0",
                    "requestId": str(shutdown_id),
                },
            )
            worker.process.wait(timeout=5)
            self.assertEqual(worker.stdout.read(), b"")
            self.assertEqual(worker.process.returncode, 0)
        finally:
            worker.close()

    def test_execute_waits_for_provider_ack_and_cancels_without_network(self) -> None:
        worker = WorkerProcess()
        try:
            worker.read()
            intent = _intent("Find one romance TV episode from the last one day")
            preview_id = uuid4()
            digest = _hash_intent(intent)
            worker.send(
                _envelope(
                    preview_id,
                    "research.preview",
                    {
                        "schemaVersion": "1.0.0",
                        "intent": intent,
                        "inputSha256": digest,
                        "nowUnixMs": 1_786_830_000_000,
                    },
                )
            )
            normalized = worker.read()["payload"]["normalizedIntent"]
            job_id = uuid4()
            research_run_id = uuid4()
            tv_run, tv_call = uuid4(), uuid4()
            synth_run, synth_call = uuid4(), uuid4()
            capabilities = [
                {
                    "providerRunId": str(tv_run),
                    "reservationId": str(uuid4()),
                    "plannedCallId": str(tv_call),
                    "provider": "tvmaze",
                    "operation": "research.metadata",
                    "configuredModel": None,
                    "resolvedModel": None,
                    "maximumMicroUsd": 0,
                    "maxRequests": 3,
                    "maxToolCalls": 0,
                    "maxInputTokens": 0,
                    "maxOutputTokens": 0,
                    "allowOneRepair": False,
                    "retentionMode": "public metadata",
                    "dataUseMode": "public metadata",
                    "noStorageMode": "not applicable",
                    "privacyMode": "public_metadata",
                    "policyClass": "tvmaze-metadata-v1",
                    "evidenceTtlSeconds": 86_400,
                    "refreshAfterSeconds": 21_600,
                    "purgeAfterSeconds": 2_592_000,
                    "deletionAfterSeconds": None,
                    "credential": None,
                    "providerConfig": {"kind": "TVMAZE"},
                },
                {
                    "providerRunId": str(synth_run),
                    "reservationId": str(uuid4()),
                    "plannedCallId": str(synth_call),
                    "provider": "openai",
                    "operation": "research.synthesize",
                    "configuredModel": "gpt-5.6-luna",
                    "resolvedModel": "gpt-5.6-luna",
                    "maximumMicroUsd": 1,
                    "maxRequests": 2,
                    "maxToolCalls": 0,
                    "maxInputTokens": 60_000,
                    "maxOutputTokens": 1_000,
                    "allowOneRepair": True,
                    "retentionMode": "up to 30 days",
                    "dataUseMode": "no training by default",
                    "noStorageMode": "store=false",
                    "privacyMode": "store_false",
                    "policyClass": "openai-web-evidence-v1",
                    "evidenceTtlSeconds": 43_200,
                    "refreshAfterSeconds": 21_600,
                    "purgeAfterSeconds": 2_592_000,
                    "deletionAfterSeconds": None,
                    "credential": "never-sent-because-not-acknowledged",
                    "providerConfig": {"kind": "OPENAI_SYNTHESIS"},
                },
            ]
            execute_id = uuid4()
            execute_payload = {
                "schemaVersion": "1.0.0",
                "jobId": str(job_id),
                "researchRunId": str(research_run_id),
                "inputSha256": digest,
                "intent": intent,
                "normalizedIntent": normalized,
                "capabilities": capabilities,
                "generatedAt": "2026-08-15T12:00:00Z",
            }
            _validate_wire(_ExecutePayload, execute_payload)
            worker.send(
                _envelope(
                    execute_id,
                    "research.execute",
                    execute_payload,
                )
            )
            started = None
            for _ in range(4):
                frame = worker.read()
                if frame["messageType"] == "provider.started":
                    started = frame
                    break
            self.assertIsNotNone(started)
            assert started is not None
            self.assertEqual(started["requestId"], str(execute_id))
            self.assertEqual(started["payload"]["providerRunId"], str(tv_run))
            self.assertEqual(started["payload"]["plannedCallId"], str(tv_call))

            cancel_id = uuid4()
            worker.send(
                _envelope(
                    cancel_id,
                    "research.cancel",
                    {"schemaVersion": "1.0.0", "jobId": str(job_id)},
                )
            )
            messages: dict[str, dict[str, object]] = {}
            for _ in range(3):
                frame = worker.read()
                messages[frame["messageType"]] = frame
                if {
                    "research.cancel.ack",
                    "research.cancelled",
                }.issubset(messages):
                    break
            self.assertEqual(messages["research.cancel.ack"]["requestId"], str(cancel_id))
            terminal = messages["research.cancelled"]
            self.assertEqual(terminal["requestId"], str(execute_id))
            self.assertEqual(terminal["payload"]["providerOutcomes"], [])

            shutdown_id = uuid4()
            worker.send(
                _envelope(
                    shutdown_id,
                    "shutdown",
                    {"schemaVersion": "1.0.0", "reason": "cancel test complete"},
                )
            )
            self.assertEqual(worker.read()["messageType"], "shutdown.ack")
        finally:
            worker.close()

    def test_malformed_secret_payload_never_reaches_stderr(self) -> None:
        worker = WorkerProcess()
        secret = "SUPER-SECRET-DO-NOT-PRINT"
        try:
            worker.read()
            worker.send(
                _envelope(
                    uuid4(),
                    "provider.preflight",
                    {
                        "schemaVersion": "1.0.0",
                        "provider": "openai",
                        "configuredModel": "gpt-5.6-luna",
                        "credential": secret,
                        "unexpected": secret,
                    },
                )
            )
            worker.process.wait(timeout=5)
            assert worker.process.stderr is not None
            stderr = worker.process.stderr.read().decode("utf-8")
            self.assertEqual(worker.process.returncode, 2)
            self.assertNotIn(secret, stderr)
            self.assertEqual(stderr.strip(), "worker protocol failure")
        finally:
            worker.close()

    def test_protocol_rejects_nonfinite_duplicate_and_truncated_frames(self) -> None:
        for raw in (
            b'{"x":NaN}\n',
            b'{"x":1,"x":2}\n',
            b'{"x":1}',
            b'{"x":1}\r\n',
        ):
            with self.subTest(raw=raw), self.assertRaises(WorkerProtocolError):
                read_json_frame(io.BytesIO(raw))


if __name__ == "__main__":
    unittest.main()
