"""Fast, replayable Milestone 1 provider diagnostics.

This module owns no credentials, persistence, or spending authority.  It can
exercise a captured/synthetic Responses payload entirely offline.  A live
transport and credential may only be injected by the debug-only Rust host.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from .contracts import EvidenceSourceType, ExcerptType, VerificationState
from .m1_contracts import (
    EpisodeLocatorFactV2,
    EvidenceClaimKind,
    ResearchSynthesisDraftV2,
)
from .providers.base import (
    CallAuthorization,
    CancellationToken,
    EvidenceCandidate,
    ProviderBatch,
    ProviderError,
    ProviderResearchContext,
    ProviderRunOutcome,
    ProviderUsage,
    SecretCredential,
)
from .providers.fake import FakeResearchProvider
from .providers.openai_web import OpenAIWebVerifier
from .providers.transport import (
    FakeTextTransport,
    JsonResponse,
    JsonTransport,
    _sanitize_headers,
    _sanitize_json_value,
    _sanitize_text,
    _sanitize_url,
)
from .provider_debug_contract import (
    DEBUG_ENDPOINT,
    DEBUG_HARD_CAP_MICRO_USD,
    DEBUG_MAX_INPUT_TOKENS,
    DEBUG_MAX_OUTPUT_TOKENS,
    DEBUG_MAX_TOOL_CALLS,
    DEBUG_MODEL,
    DEBUG_PROVIDER,
    DEBUG_RESERVED_MICRO_USD,
    DEBUG_PROMPT,
    DEBUG_SEED_EPISODE,
    DEBUG_SEED_EPISODE_TITLE,
    DEBUG_SEED_SEASON,
    DEBUG_SEED_SHOW,
)
from .research.intent import intent_from_query
from .research.synthesis import SynthesisProviderResult
from .research.workflow import ProviderPlan, ResearchWorkflow, ResearchWorkflowOutput
from .worker import PAYLOAD_SCHEMA_VERSION, _domain_payload
from .worker_protocol import PROTOCOL_VERSION, read_json_frame, write_json_frame


@dataclass(frozen=True, slots=True)
class DebugSeed:
    show_or_title: str
    season_number: int
    episode_number: int
    episode_title: str
    event_or_release_at: datetime
    canonical_url: str
    provider_record_id: str


@dataclass(frozen=True, slots=True)
class ProviderDebugFixture:
    prompt: str
    generated_at: datetime
    seed: DebugSeed
    response_status: int
    response_headers: dict[str, str]
    response_body: dict[str, object]


class ProviderDebugTrace:
    def __init__(self, trace_id: UUID | None = None) -> None:
        self.trace_id = trace_id or uuid4()
        self.events: list[dict[str, object]] = []

    def record(self, event: dict[str, object]) -> None:
        self.events.append({"trace_id": str(self.trace_id), **event})


class FixtureJsonTransport:
    """One-response transport that asserts the production request contract."""

    def __init__(
        self,
        response: JsonResponse,
        *,
        trace: ProviderDebugTrace,
        assert_contract: bool,
    ) -> None:
        self._response = response
        self._trace = trace
        self._assert_contract = assert_contract
        self._used = False

    def request_json(self, **kwargs: object) -> JsonResponse:
        if self._used:
            raise AssertionError("provider-debug fixture permits exactly one request")
        self._used = True
        headers = dict(kwargs["headers"])  # type: ignore[arg-type]
        headers["Accept"] = "application/json"
        if kwargs.get("body") is not None:
            headers["Content-Type"] = "application/json"
        if self._assert_contract:
            assert_openai_request_contract(
                method=kwargs.get("method"),
                url=kwargs.get("url"),
                headers=headers,
                body=kwargs.get("body"),
                allowed_hosts=kwargs.get("allowed_hosts"),
            )
        self._trace.record(
            {
                "event": "http.request",
                "method": str(kwargs.get("method", "")).upper(),
                "url": _sanitize_url(str(kwargs.get("url", ""))),
                "headers": _sanitize_headers(headers),
                "body": _sanitize_json_value(kwargs.get("body")),
            }
        )
        self._trace.record(
            {
                "event": "http.response",
                "status": self._response.status,
                "headers": _sanitize_headers(self._response.headers),
                "raw_body": _sanitize_text(
                    json.dumps(
                        self._response.payload,
                        ensure_ascii=False,
                        allow_nan=False,
                        separators=(",", ":"),
                    )
                ),
            }
        )
        if not 200 <= self._response.status < 300:
            raise ProviderError(f"provider returned HTTP {self._response.status}")
        return self._response


class _EmptyDebugSynthesizer:
    """Development-only zero-cost synthesis replacement for offline replay."""

    name = "debug-offline-synthesis"

    def synthesize(self, *args: object, **kwargs: object) -> SynthesisProviderResult:
        del args, kwargs
        return SynthesisProviderResult(
            provider=self.name,
            draft=ResearchSynthesisDraftV2(
                recommendations=[],
                no_strong_opportunity_reason=(
                    "Development replay delegates only to deterministic M1 fallbacks."
                ),
            ),
            usage=ProviderUsage(request_count=0),
        )


def load_fixture(path: Path) -> ProviderDebugFixture:
    value = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "schemaVersion",
        "prompt",
        "generatedAt",
        "seed",
        "response",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("provider-debug fixture has an unexpected shape")
    if value["schemaVersion"] != "1.0.0":
        raise ValueError("provider-debug fixture schema is unsupported")
    seed_value = value["seed"]
    response = value["response"]
    if not isinstance(seed_value, dict) or set(seed_value) != {
        "showOrTitle",
        "seasonNumber",
        "episodeNumber",
        "episodeTitle",
        "eventOrReleaseAt",
        "canonicalUrl",
        "providerRecordId",
    }:
        raise ValueError("provider-debug fixture seed is invalid")
    if not isinstance(response, dict) or set(response) != {"status", "headers", "body"}:
        raise ValueError("provider-debug fixture response is invalid")
    generated_at = _aware_datetime(value["generatedAt"], "generatedAt")
    seed = DebugSeed(
        show_or_title=_required_text(seed_value["showOrTitle"], "showOrTitle"),
        season_number=_positive_int(seed_value["seasonNumber"], "seasonNumber"),
        episode_number=_positive_int(seed_value["episodeNumber"], "episodeNumber"),
        episode_title=_required_text(seed_value["episodeTitle"], "episodeTitle"),
        event_or_release_at=_aware_datetime(
            seed_value["eventOrReleaseAt"], "eventOrReleaseAt"
        ),
        canonical_url=_required_text(seed_value["canonicalUrl"], "canonicalUrl"),
        provider_record_id=_required_text(
            seed_value["providerRecordId"], "providerRecordId"
        ),
    )
    headers = response["headers"]
    body = response["body"]
    if not isinstance(headers, dict) or not all(
        isinstance(key, str) and isinstance(item, str)
        for key, item in headers.items()
    ):
        raise ValueError("provider-debug response headers are invalid")
    if not isinstance(body, dict):
        raise ValueError("provider-debug response body is invalid")
    return ProviderDebugFixture(
        prompt=_required_text(value["prompt"], "prompt"),
        generated_at=generated_at,
        seed=seed,
        response_status=_positive_int(response["status"], "status"),
        response_headers=dict(headers),
        response_body=body,
    )


def run_replay(
    fixture: ProviderDebugFixture,
    *,
    assert_contract: bool = True,
    trace_id: UUID | None = None,
) -> dict[str, object]:
    trace = ProviderDebugTrace(trace_id)
    transport = FixtureJsonTransport(
        JsonResponse(
            fixture.response_status,
            fixture.response_headers,
            fixture.response_body,
        ),
        trace=trace,
        assert_contract=assert_contract,
    )
    return _run(
        fixture,
        credential=SecretCredential("debug-fixture-credential"),
        transport=transport,
        trace=trace,
    )


def run_live(
    fixture: ProviderDebugFixture,
    *,
    credential: SecretCredential,
    transport: JsonTransport,
    trace: ProviderDebugTrace,
) -> dict[str, object]:
    """Run only with a Rust-issued development capability and cost reservation."""

    return _run(
        fixture,
        credential=credential,
        transport=transport,
        trace=trace,
    )


def _run(
    fixture: ProviderDebugFixture,
    *,
    credential: SecretCredential,
    transport: JsonTransport,
    trace: ProviderDebugTrace,
) -> dict[str, object]:
    intent = intent_from_query(fixture.prompt)
    seed_candidate = _seed_candidate(fixture.seed)
    context = ProviderResearchContext(prior_evidence=(seed_candidate,))
    authorization = _authorization(
        provider=DEBUG_PROVIDER,
        operation="research.web_verify",
        model=DEBUG_MODEL,
        max_requests=1,
        max_tool_calls=DEBUG_MAX_TOOL_CALLS,
        max_input_tokens=DEBUG_MAX_INPUT_TOKENS,
        max_output_tokens=DEBUG_MAX_OUTPUT_TOKENS,
        live_calls_enabled=True,
    )
    verifier = OpenAIWebVerifier(
        credential=credential,
        model=DEBUG_MODEL,
        official_domains=(),
        search_context_size="low",
        request_body_max_input_tokens=DEBUG_MAX_INPUT_TOKENS,
        request_max_tool_calls=DEBUG_MAX_TOOL_CALLS,
        transport=transport,
        page_transport=FakeTextTransport([]),
        now_fn=lambda: fixture.generated_at,
    )
    trace.record(
        {
            "event": "provider.resolved",
            "provider": DEBUG_PROVIDER,
            "configured_model": DEBUG_MODEL,
            "resolved_model": DEBUG_MODEL,
            "development_only": True,
        }
    )
    batch = verifier.collect(
        intent,
        authorization=authorization,
        cancellation=CancellationToken(),
        context=context,
    )
    metadata_batch = ProviderBatch(provider="tvmaze", evidence=(seed_candidate,))
    workflow = ResearchWorkflow(
        providers=[
            ProviderPlan(
                FakeResearchProvider(
                    name="tvmaze",
                    operation="research.metadata",
                    batches=[metadata_batch],
                ),
                _authorization(
                    provider="tvmaze",
                    operation="research.metadata",
                    model=None,
                    max_requests=1,
                    max_tool_calls=0,
                    max_input_tokens=0,
                    max_output_tokens=0,
                    live_calls_enabled=True,
                ),
            ),
            ProviderPlan(
                FakeResearchProvider(
                    name=DEBUG_PROVIDER,
                    operation="research.web_verify",
                    batches=[batch],
                ),
                authorization,
            ),
        ],
        synthesizer=_EmptyDebugSynthesizer(),
        synthesis_authorization=_authorization(
            provider="debug-offline-synthesis",
            operation="research.synthesize",
            model=None,
            max_requests=0,
            max_tool_calls=0,
            max_input_tokens=0,
            max_output_tokens=0,
            live_calls_enabled=False,
        ),
        official_hosts=set(),
    )
    output = workflow.run(
        intent,
        generated_at=fixture.generated_at,
        cancellation=CancellationToken(),
    )
    worker_envelope = _worker_round_trip(output, provider_batch=batch)
    if worker_envelope["messageType"] == "research.result":
        worker_payload = worker_envelope["payload"]
        assert isinstance(worker_payload, dict)
        result_payload = worker_payload["result"]
        assert isinstance(result_payload, dict)
        ui_opportunities = result_payload["opportunities"]
        assert isinstance(ui_opportunities, list)
    else:
        ui_opportunities = []
    provider_succeeded = batch.outcome is ProviderRunOutcome.SUCCESS
    counts = {
        "raw_provider_results": _raw_result_count_from_trace(trace.events),
        "parsed_results": len(batch.evidence),
        "normalized_evidence": (
            output.stage_counts.normalized_evidence if provider_succeeded else 0
        ),
        "evidence_surviving_gates": (
            output.stage_counts.evidence_surviving_gates if provider_succeeded else 0
        ),
        "ranked_opportunities": (
            output.stage_counts.ranked_opportunities if provider_succeeded else 0
        ),
        "opportunities_returned_to_ui": len(ui_opportunities),
    }
    trace.record({"event": "pipeline.counts", **counts})
    return {
        "schema_version": "1.0.0",
        "trace_id": str(trace.trace_id),
        "development_only": True,
        "hard_cap_micro_usd": DEBUG_HARD_CAP_MICRO_USD,
        "reserved_micro_usd": DEBUG_RESERVED_MICRO_USD,
        "provider": DEBUG_PROVIDER,
        "configured_model": DEBUG_MODEL,
        "resolved_model": batch.usage.resolved_model or DEBUG_MODEL,
        "provider_outcome": batch.outcome.value,
        "provider_error": batch.error,
        "provider_warnings": list(batch.warnings),
        "usage": {
            "provider_request_id": batch.usage.provider_request_id,
            "request_count": batch.usage.request_count,
            "input_tokens": batch.usage.input_tokens,
            "cached_input_tokens": batch.usage.cached_input_tokens,
            "output_tokens": batch.usage.output_tokens,
            "reasoning_tokens": batch.usage.reasoning_tokens,
            "tool_calls": batch.usage.tool_calls,
        },
        "counts": counts,
        "events": trace.events,
        "worker_envelope": worker_envelope,
    }


def assert_openai_request_contract(
    *,
    method: object,
    url: object,
    headers: dict[str, object],
    body: object,
    allowed_hosts: object,
) -> None:
    """Assert the documented Responses web-search shape used by production."""

    if method != "POST" or url != DEBUG_ENDPOINT:
        raise AssertionError("OpenAI debug request must POST to /v1/responses")
    normalized_headers = {str(key).casefold(): str(value) for key, value in headers.items()}
    if set(normalized_headers) != {"accept", "authorization", "content-type"}:
        raise AssertionError("OpenAI request header names changed")
    if normalized_headers["accept"] != "application/json":
        raise AssertionError("OpenAI Accept header is invalid")
    if normalized_headers["content-type"] != "application/json":
        raise AssertionError("OpenAI Content-Type header is invalid")
    if not normalized_headers["authorization"].startswith("Bearer "):
        raise AssertionError("OpenAI Authorization header is not Bearer")
    if allowed_hosts != frozenset({"api.openai.com"}):
        raise AssertionError("OpenAI transport host allow-list changed")
    if not isinstance(body, dict):
        raise AssertionError("OpenAI request body is not an object")
    expected_keys = {
        "model",
        "store",
        "parallel_tool_calls",
        "max_output_tokens",
        "max_tool_calls",
        "tool_choice",
        "tools",
        "include",
        "instructions",
        "input",
    }
    if set(body) != expected_keys:
        raise AssertionError("OpenAI request body keys changed")
    if body["model"] != DEBUG_MODEL or body["store"] is not False:
        raise AssertionError("OpenAI model or store=false invariant changed")
    if body["parallel_tool_calls"] is not False:
        raise AssertionError("OpenAI parallel_tool_calls must remain false")
    if body["max_output_tokens"] != DEBUG_MAX_OUTPUT_TOKENS:
        raise AssertionError("OpenAI output cap changed")
    if body["max_tool_calls"] != 1 or body["tool_choice"] != "required":
        raise AssertionError("OpenAI single required-search cap changed")
    if body["include"] != ["web_search_call.action.sources"]:
        raise AssertionError("OpenAI source capture include changed")
    tools = body["tools"]
    if not isinstance(tools, list) or len(tools) != 1 or not isinstance(tools[0], dict):
        raise AssertionError("OpenAI web_search tool shape changed")
    tool = tools[0]
    if tool.get("type") != "web_search" or tool.get("search_context_size") != "low":
        raise AssertionError("OpenAI web_search configuration changed")
    filters = tool.get("filters")
    if not isinstance(filters, dict) or set(filters) != {
        "allowed_domains",
        "blocked_domains",
    }:
        raise AssertionError("OpenAI domain filters changed")
    for key in ("allowed_domains", "blocked_domains"):
        domains = filters[key]
        if not isinstance(domains, list) or not 1 <= len(domains) <= 100:
            raise AssertionError(f"OpenAI {key} limit changed")
        if any(
            not isinstance(domain, str)
            or "://" in domain
            or domain != domain.casefold().strip(" .")
            for domain in domains
        ):
            raise AssertionError(f"OpenAI {key} contains a non-bare domain")
    input_value = body["input"]
    if not isinstance(input_value, str):
        raise AssertionError("OpenAI input must be a string")
    parsed_input = json.loads(input_value)
    if not isinstance(parsed_input, dict):
        raise AssertionError("OpenAI input envelope changed")
    intent = parsed_input.get("intent")
    if not isinstance(intent, dict) or intent.get("query") != DEBUG_PROMPT:
        raise AssertionError("OpenAI debug prompt changed")
    candidates = parsed_input.get("trusted_tvmaze_episode_candidates")
    if (
        not isinstance(candidates, list)
        or len(candidates) != 1
        or not isinstance(candidates[0], dict)
        or candidates[0].get("candidate_number") != 1
    ):
        raise AssertionError("OpenAI immutable one-candidate scope changed")
    candidate = candidates[0]
    if (
        candidate.get("show_or_title") != DEBUG_SEED_SHOW
        or candidate.get("season_number") != DEBUG_SEED_SEASON
        or candidate.get("episode_number") != DEBUG_SEED_EPISODE
        or candidate.get("episode_title") != DEBUG_SEED_EPISODE_TITLE
    ):
        raise AssertionError("OpenAI immutable development seed changed")


def format_report(report: dict[str, object]) -> str:
    return json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2)


def _authorization(
    *,
    provider: str,
    operation: str,
    model: str | None,
    max_requests: int,
    max_tool_calls: int,
    max_input_tokens: int,
    max_output_tokens: int,
    live_calls_enabled: bool,
) -> CallAuthorization:
    return CallAuthorization(
        job_id=uuid4(),
        reservation_id=uuid4(),
        provider=provider,
        operation=operation,
        configured_model=model,
        allowed_resolved_models=(model,) if model is not None else (),
        max_requests=max_requests,
        max_tool_calls=max_tool_calls,
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
        allow_one_repair=False,
        privacy_mode="store_false" if provider == DEBUG_PROVIDER else "offline_debug",
        live_calls_enabled=live_calls_enabled,
    )


def _seed_candidate(seed: DebugSeed) -> EvidenceCandidate:
    locator = EpisodeLocatorFactV2(
        show_or_title=seed.show_or_title,
        season_number=seed.season_number,
        episode_number=seed.episode_number,
        episode_title=seed.episode_title,
    )
    return EvidenceCandidate(
        provider="tvmaze",
        provider_record_id=seed.provider_record_id,
        source_type=EvidenceSourceType.METADATA,
        canonical_url=seed.canonical_url,
        title=(
            f"{seed.show_or_title} - S{seed.season_number:02d}"
            f"E{seed.episode_number:02d}: {seed.episode_title}"
        ),
        author_or_channel="TVmaze",
        excerpt_type=ExcerptType.PARAPHRASE,
        excerpt=(
            f"TVmaze lists {seed.episode_title} as Season {seed.season_number} "
            f"Episode {seed.episode_number}."
        ),
        verification=VerificationState.SECONDARY_CORROBORATED,
        claim_kind=EvidenceClaimKind.EPISODE_IDENTITY,
        supports_why_now=False,
        policy_class="tvmaze-metadata-v1",
        event_or_release_at=seed.event_or_release_at,
        citation_verified=True,
        episode_locator=locator,
    )


def _worker_round_trip(
    output: ResearchWorkflowOutput,
    *,
    provider_batch: ProviderBatch,
) -> dict[str, object]:
    # Kept here rather than adding a second worker implementation: this uses
    # the same frame writer, strict reader, and domain serializer as the sidecar.
    request_id = uuid4()
    job_id = uuid4()
    if provider_batch.outcome is ProviderRunOutcome.SUCCESS:
        envelope = {
            "protocolVersion": PROTOCOL_VERSION,
            "requestId": str(request_id),
            "messageType": "research.result",
            "payload": {
                "schemaVersion": PAYLOAD_SCHEMA_VERSION,
                "jobId": str(job_id),
                "result": _domain_payload(output.result),
                "evidenceSources": [
                    _domain_payload(item) for item in output.evidence_sources
                ],
                "evidenceClaims": [
                    _domain_payload(item) for item in output.evidence_claims
                ],
                "providerOutcomes": [],
            },
        }
    else:
        message_type = {
            ProviderRunOutcome.REFUSAL: "research.refusal",
            ProviderRunOutcome.INCOMPLETE: "research.incomplete",
            ProviderRunOutcome.ERROR: "research.error",
        }[provider_batch.outcome]
        detail = (
            provider_batch.refusal
            or provider_batch.incomplete
            or provider_batch.error
            or "Provider debug replay did not complete."
        )
        envelope = {
            "protocolVersion": PROTOCOL_VERSION,
            "requestId": str(request_id),
            "messageType": message_type,
            "payload": {
                "schemaVersion": PAYLOAD_SCHEMA_VERSION,
                "jobId": str(job_id),
                "message": detail[:1_000],
                "providerOutcomes": [],
            },
        }
    stream = io.BytesIO()
    write_json_frame(stream, envelope)
    stream.seek(0)
    decoded = read_json_frame(stream)
    if decoded is None or stream.read(1) != b"":
        raise AssertionError("worker transport replay did not round-trip exactly one frame")
    return decoded


def _raw_result_count(payload: dict[str, object]) -> int:
    count = 0
    output = payload.get("output")
    if not isinstance(output, list):
        return 0
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "web_search_call":
            continue
        action = item.get("action")
        if not isinstance(action, dict):
            continue
        sources = action.get("sources")
        if isinstance(sources, list):
            count += len(sources)
    return count


def _raw_result_count_from_trace(events: list[dict[str, object]]) -> int:
    """Count the actual captured response, never a request-template fixture."""

    for event in reversed(events):
        if event.get("event") != "http.response":
            continue
        raw_body = event.get("raw_body")
        if not isinstance(raw_body, str):
            return 0
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError:
            return 0
        return _raw_result_count(payload) if isinstance(payload, dict) else 0
    return 0


def _aware_datetime(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"provider-debug {field} must be a timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"provider-debug {field} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"provider-debug {field} must be non-empty text")
    return value


def _positive_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"provider-debug {field} must be a positive integer")
    return value
