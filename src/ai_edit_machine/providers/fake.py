"""Deterministic provider used by offline workflow and golden replay tests."""

from __future__ import annotations

from ..m1_contracts import (
    EvidenceClaimRecordV2,
    EvidenceSourceRecordV2,
    ResearchIntentV2,
)
from ..research.synthesis import SynthesisProviderResult
from .base import (
    EMPTY_PROVIDER_RESEARCH_CONTEXT,
    CallAuthorization,
    CallMeter,
    CancellationToken,
    ProviderBatch,
    ProviderResearchContext,
)


class FakeResearchProvider:
    def __init__(self, *, name: str, operation: str, batches: list[ProviderBatch]) -> None:
        self.name = name
        self.operation = operation
        self._batches = list(batches)

    def collect(
        self,
        intent: ResearchIntentV2,
        *,
        authorization: CallAuthorization,
        cancellation: CancellationToken,
        context: ProviderResearchContext = EMPTY_PROVIDER_RESEARCH_CONTEXT,
    ) -> ProviderBatch:
        del intent, context
        cancellation.raise_if_cancelled()
        meter = CallMeter(authorization)
        meter.begin_request(provider=self.name, operation=self.operation)
        if not self._batches:
            raise AssertionError("fake provider has no remaining batch")
        return self._batches.pop(0)


class FakeResearchSynthesizer:
    """Queue-backed synthesis adapter for offline/golden replay."""

    def __init__(
        self,
        *,
        name: str,
        operation: str,
        results: list[SynthesisProviderResult],
    ) -> None:
        self.name = name
        self.operation = operation
        self._results = list(results)

    def synthesize(
        self,
        intent: ResearchIntentV2,
        *,
        evidence_sources: list[EvidenceSourceRecordV2],
        evidence_claims: list[EvidenceClaimRecordV2],
        authorization: CallAuthorization,
        cancellation: CancellationToken,
    ) -> SynthesisProviderResult:
        del intent, evidence_sources, evidence_claims
        cancellation.raise_if_cancelled()
        meter = CallMeter(authorization)
        meter.begin_request(provider=self.name, operation=self.operation)
        if not self._results:
            raise AssertionError("fake synthesizer has no remaining result")
        return self._results.pop(0)
