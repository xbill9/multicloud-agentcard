"""The failure taxonomy: what kind of thing went wrong, not just that it did.

The distinction these kinds draw is the one this project keeps paying to
preserve. ``authentication`` and ``transport`` are different afternoons;
``provider`` and ``protocol`` answer "did the platform break A2A, or did the
agent refuse" without anyone reading a log. A failure filed as ``protocol``
because nothing else matched is a diagnosis nobody made.

Carried over from the repo this forked from, where a researcher agent had to
raise these without importing the coordinator. Here there is no such split --
the taxonomy is kept because the *kinds* were earned, not the packaging.
"""

from enum import StrEnum


class FailureKind(StrEnum):
    VALIDATION = "validation"
    PROVIDER = "provider"
    AUTHENTICATION = "authentication"
    TRANSPORT = "transport"
    TIMEOUT = "timeout"
    PROTOCOL = "protocol"


class AdapterError(RuntimeError):
    def __init__(self, kind: FailureKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind

    def safe_message(self) -> str:
        return f"{self.kind.value}: {self}"


__all__ = ["AdapterError", "FailureKind"]
