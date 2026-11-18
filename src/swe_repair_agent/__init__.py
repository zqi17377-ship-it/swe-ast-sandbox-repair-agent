"""SWE Code Repair Agent: AST Fault Localization + Pluggable Sandbox + Self-Healing Loop."""

from swe_repair_agent.agent import SWERepairAgent, format_pytest_feedback
from swe_repair_agent.ast_indexer import RepositoryASTIndexer, estimate_tokens
from swe_repair_agent.llm import (
    MockRepairLLM,
    OpenAICompatibleLLM,
    RepairLLM,
    create_repair_llm,
)
from swe_repair_agent.models import (
    AgentConfig,
    ContextBundle,
    PatchOutcome,
    RepairRunResult,
    SandboxTestResult,
    SearchReplaceEdit,
    TaskSpec,
)
from swe_repair_agent.patcher import (
    ProtectedPathError,
    SafePatchEngine,
    SandboxSecurityError,
    compute_repo_diff,
    parse_search_replace_blocks,
)
from swe_repair_agent.sandbox import (
    DockerContainerSandbox,
    ProcessIsolatedSandbox,
    SandboxBackend,
    create_sandbox_backend,
    parse_pytest_output,
)

__all__ = [
    "AgentConfig",
    "ContextBundle",
    "DockerContainerSandbox",
    "MockRepairLLM",
    "OpenAICompatibleLLM",
    "PatchOutcome",
    "ProcessIsolatedSandbox",
    "ProtectedPathError",
    "RepairLLM",
    "RepairRunResult",
    "RepositoryASTIndexer",
    "SWERepairAgent",
    "SafePatchEngine",
    "SandboxBackend",
    "SandboxSecurityError",
    "SandboxTestResult",
    "SearchReplaceEdit",
    "TaskSpec",
    "compute_repo_diff",
    "create_repair_llm",
    "create_sandbox_backend",
    "estimate_tokens",
    "format_pytest_feedback",
    "parse_pytest_output",
    "parse_search_replace_blocks",
]
