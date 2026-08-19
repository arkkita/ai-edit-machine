"""Provider-independent interface for bounded M1 recommendation synthesis."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..m1_contracts import (
    EvidenceClaimRecordV2,
    EvidenceSourceRecordV2,
    ResearchIntentV2,
    ResearchSynthesisDraftV2,
)
from ..providers.base import (
    CallAuthorization,
    CancellationToken,
    ProviderRunOutcome,
    ProviderUsage,
)


@dataclass(frozen=True, slots=True)
class SynthesisProviderResult:
    provider: str
    draft: ResearchSynthesisDraftV2 | None = None
    usage: ProviderUsage = field(default_factory=ProviderUsage)
    outcome: ProviderRunOutcome = ProviderRunOutcome.SUCCESS
    refusal: str | None = None
    incomplete: str | None = None
    error: str | None = None
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        details = [self.refusal, self.incomplete, self.error]
        if self.outcome is ProviderRunOutcome.SUCCESS:
            if self.draft is None or any(value is not None for value in details):
                raise ValueError("successful synthesis requires only a draft")
        elif self.draft is not None:
            raise ValueError("non-successful synthesis cannot carry a draft")
        elif self.outcome is ProviderRunOutcome.REFUSAL:
            if not self.refusal or self.incomplete is not None or self.error is not None:
                raise ValueError("REFUSAL requires only refusal detail")
        elif self.outcome is ProviderRunOutcome.INCOMPLETE:
            if not self.incomplete or self.refusal is not None or self.error is not None:
                raise ValueError("INCOMPLETE requires only incomplete detail")
        elif not self.error or self.refusal is not None or self.incomplete is not None:
            raise ValueError("ERROR requires only error detail")


class ResearchSynthesizer(Protocol):
    name: str

    def synthesize(
        self,
        intent: ResearchIntentV2,
        *,
        evidence_sources: list[EvidenceSourceRecordV2],
        evidence_claims: list[EvidenceClaimRecordV2],
        authorization: CallAuthorization,
        cancellation: CancellationToken,
    ) -> SynthesisProviderResult: ...

