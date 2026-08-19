"""Narrow Milestone 1 provider adapters."""

from .base import (
    CallAuthorization,
    CallMeter,
    CancellationToken,
    EvidenceCandidate,
    ProviderBatch,
    ProviderDisabledError,
    ProviderError,
    ProviderResearchContext,
    SecretCredential,
)
from .fake import FakeResearchProvider, FakeResearchSynthesizer
from .openai_synthesis import OpenAIResearchSynthesizer
from .openai_web import OpenAIWebVerifier
from .tvmaze import TVmazeProvider
from .xai_search import XAIInvocationCapProof, XAISearchProvider
from .youtube import YouTubeOfficialProvider

__all__ = [
    "CallAuthorization",
    "CallMeter",
    "CancellationToken",
    "EvidenceCandidate",
    "FakeResearchProvider",
    "FakeResearchSynthesizer",
    "OpenAIResearchSynthesizer",
    "OpenAIWebVerifier",
    "ProviderBatch",
    "ProviderDisabledError",
    "ProviderError",
    "ProviderResearchContext",
    "SecretCredential",
    "TVmazeProvider",
    "XAIInvocationCapProof",
    "XAISearchProvider",
    "YouTubeOfficialProvider",
]
