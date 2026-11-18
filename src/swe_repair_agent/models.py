"""Domain models and telemetry schemas for the SWE Code Repair Agent."""

from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field

SymbolKind = Literal["class", "method", "function"]

FailureCategory = Literal[
    "NONE",
    "LOCALIZATION_TRUNCATION_MISS",
    "SINGLE_SHOT_EDGE_CASE_MISS",
    "CROSS_MODULE_INVARIANT_OSCILLATION",
    "DYNAMIC_DISPATCH_GRAPH_MISS",
    "LEXER_SPEC_REGRESSION",
    "PATCH_APPLICATION_FAILURE",
    "SANDBOX_TIMEOUT",
]


class SymbolNode(BaseModel):
    """AST-extracted symbol node inside a repository."""

    symbol_id: str
    file_path: str
    name: str
    qualname: str
    kind: SymbolKind
    start_line: int
    end_line: int
    signature: str
    docstring: str = ""
    calls: list[str] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)
    source: str
    is_test: bool = False


class DependencyEdge(BaseModel):
    """Directed dependency edge in the repository symbol call/import graph."""

    caller_id: str
    callee_id: str
    relation: Literal["calls", "imports", "test_invokes"] = "calls"


class ScoredSymbol(BaseModel):
    """Candidate symbol ranked by hybrid AST fault localization."""

    symbol_id: str
    file_path: str
    qualname: str
    kind: SymbolKind
    start_line: int
    end_line: int
    bm25_score: float = 0.0
    stacktrace_score: float = 0.0
    graph_score: float = 0.0
    total_score: float = 0.0
    reasons: list[str] = Field(default_factory=list)


class ContextBundle(BaseModel):
    """Constructed code context window and token-reduction accounting."""

    mode: Literal["ast_localized", "full_context"]
    prompt_context: str
    repo_map: str = ""
    ranked_symbols: list[ScoredSymbol] = Field(default_factory=list)
    selected_symbol_ids: list[str] = Field(default_factory=list)
    included_files: list[str] = Field(default_factory=list)
    truncated_files: list[str] = Field(default_factory=list)
    raw_repo_tokens: int
    full_baseline_tokens: int
    context_tokens: int
    token_reduction_vs_raw_pct: float
    token_reduction_vs_baseline_pct: float


class SearchReplaceEdit(BaseModel):
    """Structured SEARCH/REPLACE edit operation on a repository file."""

    file_path: str
    search: str
    replace: str


class PatchOutcome(BaseModel):
    """Result of applying and syntax-checking a candidate patch."""

    applied: bool
    rolled_back: bool = False
    syntax_valid: bool = True
    modified_files: list[str] = Field(default_factory=list)
    unified_diff: str = ""
    error_type: str | None = None
    error_message: str | None = None


class StackFrame(BaseModel):
    """Single stack frame parsed from a pytest failure traceback."""

    file_path: str
    line: int
    func_name: str = ""
    code_line: str = ""


class TestFailureDetail(BaseModel):
    """Structured failure diagnostic parsed from pytest output."""

    __test__ = False

    test_name: str
    exception_type: str = ""
    message: str = ""
    traceback_excerpt: str = ""
    frames: list[StackFrame] = Field(default_factory=list)


class SandboxTestResult(BaseModel):
    """Structured outcome from running pytest inside an isolated sandbox."""

    passed: bool
    exit_code: int
    passed_count: int = 0
    failed_count: int = 0
    error_count: int = 0
    duration_sec: float = 0.0
    timed_out: bool = False
    stdout: str = ""
    stderr: str = ""
    failures: list[TestFailureDetail] = Field(default_factory=list)


class ChatMessage(BaseModel):
    """Conversation turn message sent to or received from an LLM."""

    role: Literal["system", "user", "assistant"]
    content: str


class LLMResponse(BaseModel):
    """Parsed code-repair response from the LLM backend."""

    diagnosis: str = ""
    raw_content: str
    edits: list[SearchReplaceEdit] = Field(default_factory=list)
    unified_diff: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0


class TurnRecord(BaseModel):
    """Audit record for a single repair iteration."""

    turn_index: int
    localized_symbols: list[str] = Field(default_factory=list)
    context_tokens: int = 0
    diagnosis: str = ""
    patch_outcome: PatchOutcome
    test_result: SandboxTestResult | None = None


class TaskSpec(BaseModel):
    """Benchmark task specification for a repository-level bug."""

    task_id: str
    title: str
    repo_rel_path: str
    issue_description: str
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    category: str = ""
    expected_Hint_note: str = ""
    ground_truth_symbols: list[str] = Field(default_factory=list)


class AgentConfig(BaseModel):
    """Ablation and runtime hyperparameters for SWERepairAgent."""

    config_name: str = "ours_ast_self_healing"
    label: str = "Ours: AST Localization + Sandbox Self-Healing"
    use_ast_localization: bool = True
    use_test_loop: bool = True
    max_turns: int = 4
    top_k_symbols: int = 4
    full_context_token_budget: int = 1550
    sandbox_timeout_sec: float = 15.0


class RepairRunResult(BaseModel):
    """End-to-end outcome and telemetry for one repository repair run."""

    task_id: str
    config_name: str
    resolved: bool
    resolved_on_turn: int | None = None
    self_healed: bool = False
    turns_used: int
    initial_test_result: SandboxTestResult | None = None
    final_test_result: SandboxTestResult
    turns: list[TurnRecord] = Field(default_factory=list)
    final_unified_diff: str = ""
    avg_context_tokens: float
    raw_repo_tokens: int
    full_baseline_tokens: int
    token_reduction_vs_raw_pct: float
    token_reduction_vs_baseline_pct: float
    total_sandbox_time_sec: float
    total_wall_time_sec: float
    syntax_rollbacks: int = 0
    failure_category: FailureCategory = "NONE"
    failure_explanation: str = ""
