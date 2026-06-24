"""Agent framework: events, context, and retry-capable base class."""
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

log = logging.getLogger("lincut.agents")


@dataclass
class AgentEvent:
    agent: str
    message: str
    progress: float
    data: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class ProductionContext:
    """Shared state passed between agents during a production run."""
    prompt: str
    runtime: int
    segment_count: int
    with_score: bool
    workspace: str
    blueprint: Optional[dict] = None
    plan: Optional[dict] = None
    clips: Optional[list] = None
    voice_tracks: Optional[list] = None
    score_path: Optional[str] = None
    deliverable: Optional[str] = None


class BaseAgent(ABC):
    """Base class for all production agents with configurable retry."""

    name: str = "base"
    max_retries: int = 2
    retry_delay: float = 1.5
    optional: bool = False

    def __init__(self, on_event: Callable[[AgentEvent], None] = None):
        self.on_event = on_event

    def emit(self, message: str, progress: float, data: dict = None):
        if self.on_event:
            self.on_event(AgentEvent(self.name, message, progress, data or {}))

    def invoke(self, ctx: ProductionContext) -> Any:
        """Execute agent logic with automatic retries on transient failures."""
        last_exc: Optional[Exception] = None
        attempts = self.max_retries + 1

        for attempt in range(attempts):
            try:
                return self.run(ctx)
            except Exception as exc:
                last_exc = exc
                if self.optional:
                    log.warning("%s agent skipped: %s", self.name, exc, exc_info=True)
                    self.emit(
                        f"{self.name} skipped: {exc}",
                        self._progress_hint(ctx),
                        {"level": "warning", "skipped": True},
                    )
                    return None
                if attempt < self.max_retries:
                    log.warning(
                        "%s agent attempt %d/%d failed: %s — retrying",
                        self.name, attempt + 1, attempts, exc,
                    )
                    self.emit(
                        f"Retry {attempt + 1}/{self.max_retries}: {exc}",
                        self._progress_hint(ctx),
                        {"level": "warning", "retry": attempt + 1},
                    )
                    time.sleep(self.retry_delay * (attempt + 1))
                else:
                    log.error("%s agent failed after %d attempts", self.name, attempts, exc_info=True)
                    raise RuntimeError(f"{self.name} agent failed: {exc}") from exc

        raise RuntimeError(f"{self.name} agent failed: {last_exc}")  # unreachable

    def _progress_hint(self, ctx: ProductionContext) -> float:
        return 0.0

    @abstractmethod
    def run(self, ctx: ProductionContext) -> Any:
        """Agent-specific work. Subclasses implement this."""

    def retry_call(self, fn: Callable, label: str, progress: float):
        """Retry a single sub-operation (e.g. one clip render)."""
        last_exc = None
        for attempt in range(self.max_retries + 1):
            try:
                return fn()
            except Exception as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    log.warning("%s: %s failed (attempt %d), retrying", self.name, label, attempt + 1)
                    self.emit(
                        f"{label}: retry {attempt + 1}/{self.max_retries}",
                        progress,
                        {"level": "warning", "retry": attempt + 1},
                    )
                    time.sleep(self.retry_delay * (attempt + 1))
        raise last_exc
