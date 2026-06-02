from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Iterable, List, Optional


def parse_token_specs(value: Optional[str]) -> List[str]:
    if not value:
        return []
    tokens: List[str] = []
    for part in value.split(","):
        item = part.strip()
        if not item:
            continue
        _, sep, token = item.partition(":")
        candidate = token if sep else item
        candidate = candidate.strip()
        if candidate:
            tokens.append(candidate)
    return tokens


@dataclass(frozen=True)
class TokenAuthenticator:
    tokens: tuple[str, ...] = ()

    @classmethod
    def from_values(
        cls,
        primary_token: Optional[str] = None,
        token_specs: Optional[str] = None,
    ) -> "TokenAuthenticator":
        values: List[str] = []
        if primary_token:
            values.append(primary_token)
        values.extend(parse_token_specs(token_specs))
        return cls(tokens=tuple(_dedupe(values)))

    @property
    def is_required(self) -> bool:
        return bool(self.tokens)

    @property
    def session_secret(self) -> str:
        return self.tokens[0] if self.tokens else ""

    def verify(self, supplied: Optional[str]) -> bool:
        if not self.tokens:
            return True
        if not supplied:
            return False
        return any(hmac.compare_digest(supplied, token) for token in self.tokens)


def _dedupe(values: Iterable[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
