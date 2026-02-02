from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Generic, Optional, TypeVar, Union, Dict, Any, List, Tuple

T = TypeVar("T")
E = TypeVar("E")


class ErrorCode(str, Enum):
    KONSULENT_API_TIMEOUT = "konsulent_api_timeout"
    KONSULENT_API_UNAVAILABLE = "konsulent_api_unavailable"
    CIRCUIT_BREAKER_OPEN = "circuit_breaker_open"
    LLM_API_ERROR = "llm_api_error"
    LLM_VALIDATION_FAILED = "llm_validation_failed"
    COST_BUDGET_EXCEEDED = "cost_budget_exceeded"
    RATE_LIMITED = "rate_limited"


@dataclass(frozen=True)
class ServiceError:
    code: ErrorCode
    message: str
    details: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class Ok(Generic[T]):
    value: T


@dataclass(frozen=True)
class Err(Generic[E]):
    error: E


Result = Union[Ok[T], Err[E]]


@dataclass(frozen=True)
class Konsulent:
    id: int
    navn: str
    ferdigheter: Tuple[str, ...]
    belastning_prosent: int  # 0..100

    @property
    def tilgjengelighet_prosent(self) -> int:
        return max(0, 100 - int(self.belastning_prosent))


@dataclass(frozen=True)
class SammendragSchema:
    sammendrag: str
    listed_names: List[str]
    listed_availability: List[int]
