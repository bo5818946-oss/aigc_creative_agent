"""Data structures shared by evaluation cases, runner, and report."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class ExpectedOutcome:
    final_status: str
    revision_count: int | None = None
    validation_passed: bool | None = None
    check_results: dict[str, bool] = field(default_factory=dict)
    llm_calls: int | None = None
    error_contains: tuple[str, ...] = ()
    revision_reason_contains: tuple[str, ...] = ()
    revision_statuses: tuple[str, ...] = ()
    warning_count_min: int | None = None
    pending_confirmation_min: int | None = None
    forbidden_trace_nodes: tuple[str, ...] = ()
    tool_passed: bool | None = None
    tool_error_contains: tuple[str, ...] = ()
    tool_warning_contains: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "final_status": self.final_status,
            "revision_count": self.revision_count,
            "validation_passed": self.validation_passed,
            "check_results": dict(self.check_results),
            "llm_calls": self.llm_calls,
            "error_contains": list(self.error_contains),
            "revision_reason_contains": list(
                self.revision_reason_contains
            ),
            "revision_statuses": list(self.revision_statuses),
            "warning_count_min": self.warning_count_min,
            "pending_confirmation_min": self.pending_confirmation_min,
            "forbidden_trace_nodes": list(self.forbidden_trace_nodes),
            "tool_passed": self.tool_passed,
            "tool_error_contains": list(self.tool_error_contains),
            "tool_warning_contains": list(self.tool_warning_contains),
        }


@dataclass(frozen=True)
class ToolOutcome:
    passed: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    name: str
    category: str
    kind: str
    description: str
    expected: ExpectedOutcome
    requirement: dict[str, Any] | None = None
    responses: tuple[Any, ...] = ()
    max_revisions: int = 2
    target_video_model: str = "generic"
    duration_tolerance_seconds: float = 0.5
    tool_runner: Callable[[], ToolOutcome] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "name": self.name,
            "category": self.category,
            "kind": self.kind,
            "description": self.description,
            "max_revisions": self.max_revisions,
            "target_video_model": self.target_video_model,
            "duration_tolerance_seconds": self.duration_tolerance_seconds,
            "expected": self.expected.to_dict(),
        }


@dataclass
class CaseObservation:
    case_id: str
    kind: str
    duration_ms: float
    final_status: str
    revision_count: int = 0
    validation_passed: bool | None = None
    check_results: dict[str, bool] = field(default_factory=dict)
    llm_calls: int = 0
    llm_tokens: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    persisted_status: str | None = None
    trace_nodes: list[str] = field(default_factory=list)
    revision_statuses: list[str] = field(default_factory=list)
    revision_reasons: list[str] = field(default_factory=list)
    pending_confirmations: list[str] = field(default_factory=list)
    warning_count: int = 0
    tool_passed: bool | None = None
    tool_errors: list[str] = field(default_factory=list)
    tool_warnings: list[str] = field(default_factory=list)
    exception: str | None = None
    project_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "kind": self.kind,
            "duration_ms": round(self.duration_ms, 2),
            "final_status": self.final_status,
            "revision_count": self.revision_count,
            "validation_passed": self.validation_passed,
            "check_results": dict(self.check_results),
            "llm_calls": self.llm_calls,
            "llm_tokens": self.llm_tokens,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "persisted_status": self.persisted_status,
            "trace_nodes": list(self.trace_nodes),
            "revision_statuses": list(self.revision_statuses),
            "revision_reasons": list(self.revision_reasons),
            "pending_confirmations": list(self.pending_confirmations),
            "warning_count": self.warning_count,
            "tool_passed": self.tool_passed,
            "tool_errors": list(self.tool_errors),
            "tool_warnings": list(self.tool_warnings),
            "exception": self.exception,
            "project_id": self.project_id,
        }


@dataclass
class CaseResult:
    case: EvaluationCase
    observation: CaseObservation
    mismatches: list[str] = field(default_factory=list)
    project: dict[str, Any] | None = None

    @property
    def passed(self) -> bool:
        return not self.mismatches and self.observation.exception is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "case": self.case.to_dict(),
            "observation": self.observation.to_dict(),
            "mismatches": list(self.mismatches),
            "passed": self.passed,
        }
