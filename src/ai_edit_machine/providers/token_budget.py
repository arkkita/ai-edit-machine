"""Conservative pre-spend input ceilings for provider JSON requests."""

from __future__ import annotations

import json
from dataclasses import dataclass

from .base import ProviderLimitError


REQUEST_TOKEN_OVERHEAD = 1_024


@dataclass(slots=True)
class AggregateInputBudget:
    """Reserve an aggregate upper bound before each paid request.

    Provider tokenizers used here are byte-level: each input token represents at
    least one UTF-8 byte. Counting every serialized request byte as one token is
    therefore intentionally conservative and also includes schema/instruction
    bytes that a narrower prompt-only estimate could miss. A fixed per-request
    margin additionally covers provider framing and special tokens.
    """

    maximum_tokens: int
    conservative_tokens_used: int = 0

    def reserve_body(self, body: dict[str, object]) -> int:
        upper_bound = REQUEST_TOKEN_OVERHEAD + len(
            json.dumps(
                body,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        )
        if self.conservative_tokens_used + upper_bound > self.maximum_tokens:
            raise ProviderLimitError(
                "provider request exceeds the aggregate input-token capability"
            )
        self.conservative_tokens_used += upper_bound
        return upper_bound
