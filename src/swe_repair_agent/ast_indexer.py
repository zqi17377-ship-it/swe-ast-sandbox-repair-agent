"""AST Repository Symbol & Dependency Graph Indexer with Hybrid Fault Localization."""

from __future__ import annotations

import ast
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

from swe_repair_agent.models import (
    ContextBundle,
    DependencyEdge,
    SandboxTestResult,
    ScoredSymbol,
    SymbolNode,
)

_TOKEN_RE = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\b)|\d+|[^\s\w]")
_IDENT_SPLIT_RE = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\b)|\d+")

_PYTHON_STOPWORDS = frozenset(
    {
        "self",
        "cls",
        "def",
        "class",
        "return",
        "none",
        "true",
        "false",
        "and",
        "or",
        "not",
        "in",
        "is",
        "if",
        "else",
        "elif",
        "for",
        "while",
        "try",
        "except",
        "finally",
        "with",
        "as",
        "from",
        "import",
        "pass",
        "raise",
        "yield",
        "int",
        "str",
        "float",
        "bool",
        "list",
        "dict",
        "set",
        "tuple",
        "any",
        "optional",
        "the",
        "a",
        "an",
        "to",
        "of",
        "on",
        "at",
        "by",
        "when",
        "should",
        "does",
        "into",
    }
)


def estimate_tokens(text: str) -> int:
    """Deterministic subword + punctuation token estimator aligned with code BPE."""
    if not text:
        return 0
    return len(_TOKEN_RE.findall(text))


def tokenize_identifiers(text: str) -> list[str]:
    """Split camelCase, snake_case, and prose into normalized lexical terms."""
    tokens: list[str] = []
    for raw_word in re.findall(r"[A-Za-z0-9_]+", text):
        for part in raw_word.split("_"):
            if not part:
                continue
            for sub in _IDENT_SPLIT_RE.findall(part):
                lowered = sub.lower()
                if len(lowered) > 1 and lowered not in _PYTHON_STOPWORDS:
                    tokens.append(lowered)
    return tokens


def _node_start_line(node: ast.AST) -> int:
    decorators = getattr(node, "decorator_list", None)
    if decorators:
        return min( decorators[0].lineno, getattr(node, "lineno", 1) )
    return getattr(node, "lineno", 1)


def _format_signature(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> str:
    if isinstance(node, ast.ClassDef):
        bases = [ast.unparse(b) for b in node.bases]
        base_str = f"({', '.join(bases)})" if bases else ""
        return f"class {node.name}{base_str}:"
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    args_str = ast.unparse(node.args)
    ret_str = f" -> {ast.unparse(node.returns)}" if node.returns is not None else ""
    return f"{prefix} {node.name}({args_str}){ret_str}:"


def _extract_calls(node: ast.AST) -> list[str]:
    """Extract called function, method, and attribute names inside an AST subtree."""
    calls: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Name):
                calls.append(func.id)
            elif isinstance(func, ast.Attribute):
                calls.append(func.attr)
                if isinstance(func.value, ast.Name):
                    calls.append(f"{func.value.id}.{func.attr}")
    # Preserve order while deduplicating
    return list(dict.fromkeys(calls))


class RepositoryASTIndexer:
    """Parses a Python repository into a symbol & call dependency graph for fault localization."""

    def __init__(self, repo_dir: Path) -> None:
        self.repo_dir = repo_dir.resolve()
        self.files_source: dict[str, str] = {}
        self.file_imports: dict[str, list[str]] = {}
        self.file_import_map: dict[str, dict[str, str]] = {}
        self.symbols: dict[str, SymbolNode] = {}
        self.edges: list[DependencyEdge] = []
        self._indexed = False

    def index(self) -> None:
        """Scan and parse all Python files in the repository."""
        self.files_source.clear()
        self.file_imports.clear()
        self.file_import_map.clear()
        self.symbols.clear()
        self.edges.clear()

        py_files = sorted(
            p
            for p in self.repo_dir.rglob("*.py")
            if not any(
                part.startswith(".") or part in {"__pycache__", ".sandbox_runs"}
                for part in p.relative_to(self.repo_dir).parts
            )
        )

        module_to_file: dict[str, str] = {}
        for path in py_files:
            rel_posix = path.relative_to(self.repo_dir).as_posix()
            mod_name = rel_posix[:-3].replace("/", ".")
            if mod_name.endswith(".__init__"):
                module_to_file[mod_name[: -len(".__init__")]] = rel_posix
            module_to_file[mod_name] = rel_posix

        for path in py_files:
            rel_posix = path.relative_to(self.repo_dir).as_posix()
            source = path.read_text(encoding="utf-8", errors="replace")
            self.files_source[rel_posix] = source
            is_test = rel_posix.startswith("tests/") or path.name.startswith("test_")
            self._parse_file(rel_posix, source, is_test, module_to_file)

        self._build_dependency_edges()
        self._indexed = True

    def _ensure_indexed(self) -> None:
        if not self._indexed:
            self.index()

    def _parse_file(
        self,
        file_path: str,
        source: str,
        is_test: bool,
        module_to_file: dict[str, str],
    ) -> None:
        try:
            tree = ast.parse(source, filename=file_path)
        except SyntaxError:
            self.file_imports[file_path] = []
            self.file_import_map[file_path] = {}
            return

        lines = source.splitlines()
        imports_raw: list[str] = []
        import_map: dict[str, str] = {}

        pkg_parts = file_path.split("/")[:-1]

        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    local_name = alias.asname or alias.name.split(".")[-1]
                    imports_raw.append(alias.name)
                    if alias.name in module_to_file:
                        import_map[local_name] = f"{module_to_file[alias.name]}::*"
            elif isinstance(node, ast.ImportFrom):
                base_mod = node.module or ""
                if node.level > 0:
                    up = max(0, len(pkg_parts) - (node.level - 1))
                    prefix_parts = pkg_parts[:up]
                    resolved_mod = ".".join(
                        prefix_parts + ([base_mod] if base_mod else [])
                    )
                else:
                    resolved_mod = base_mod
                imports_raw.append(resolved_mod)
                target_file = module_to_file.get(resolved_mod)
                for alias in node.names:
                    local_name = alias.asname or alias.name
                    if target_file:
                        import_map[local_name] = f"{target_file}::{alias.name}"
                    elif resolved_mod:
                        sub_mod = f"{resolved_mod}.{alias.name}"
                        if sub_mod in module_to_file:
                            import_map[local_name] = f"{module_to_file[sub_mod]}::*"

        self.file_imports[file_path] = imports_raw
        self.file_import_map[file_path] = import_map

        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                start = _node_start_line(node)
                end = getattr(node, "end_lineno", start)
                cls_source = "\n".join(lines[start - 1 : end])
                cls_id = f"{file_path}::{node.name}"
                cls_doc = ast.get_docstring(node) or ""
                method_nodes = [
                    item
                    for item in node.body
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
                # Extract calls at class body level only if no methods, otherwise methods track their own calls
                cls_calls = _extract_calls(node) if not method_nodes else []
                self.symbols[cls_id] = SymbolNode(
                    symbol_id=cls_id,
                    file_path=file_path,
                    name=node.name,
                    qualname=node.name,
                    kind="class",
                    start_line=start,
                    end_line=end,
                    signature=_format_signature(node),
                    docstring=cls_doc,
                    calls=cls_calls,
                    imports=imports_raw,
                    source=cls_source,
                    is_test=is_test,
                )
                for m_node in method_nodes:
                    m_start = _node_start_line(m_node)
                    m_end = getattr(m_node, "end_lineno", m_start)
                    m_source = "\n".join(lines[m_start - 1 : m_end])
                    qual = f"{node.name}.{m_node.name}"
                    m_id = f"{file_path}::{qual}"
                    self.symbols[m_id] = SymbolNode(
                        symbol_id=m_id,
                        file_path=file_path,
                        name=m_node.name,
                        qualname=qual,
                        kind="method",
                        start_line=m_start,
                        end_line=m_end,
                        signature=_format_signature(m_node),
                        docstring=ast.get_docstring(m_node) or "",
                        calls=_extract_calls(m_node),
                        imports=imports_raw,
                        source=m_source,
                        is_test=is_test,
                    )
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                start = _node_start_line(node)
                end = getattr(node, "end_lineno", start)
                fn_source = "\n".join(lines[start - 1 : end])
                fn_id = f"{file_path}::{node.name}"
                self.symbols[fn_id] = SymbolNode(
                    symbol_id=fn_id,
                    file_path=file_path,
                    name=node.name,
                    qualname=node.name,
                    kind="function",
                    start_line=start,
                    end_line=end,
                    signature=_format_signature(node),
                    docstring=ast.get_docstring(node) or "",
                    calls=_extract_calls(node),
                    imports=imports_raw,
                    source=fn_source,
                    is_test=is_test,
                )

    def _build_dependency_edges(self) -> None:
        """Resolve intra-file, self-method, and cross-file symbol calls into directed edges."""
        by_name: dict[str, list[SymbolNode]] = defaultdict(list)
        by_file_name: dict[tuple[str, str], list[SymbolNode]] = defaultdict(list)
        class_methods: dict[tuple[str, str], dict[str, SymbolNode]] = defaultdict(dict)

        for sym in self.symbols.values():
            by_name[sym.name].append(sym)
            by_file_name[(sym.file_path, sym.name)].append(sym)
            if sym.kind == "method" and "." in sym.qualname:
                cls_name, meth_name = sym.qualname.split(".", 1)
                class_methods[(sym.file_path, cls_name)][meth_name] = sym

        seen_edges: set[tuple[str, str, str]] = set()

        def add_edge(
            caller: str, callee: str, rel: str = "calls"
        ) -> None:
            if caller == callee:
                return
            key = (caller, callee, rel)
            if key not in seen_edges:
                seen_edges.add(key)
                self.edges.append(
                    DependencyEdge(caller_id=caller, callee_id=callee, relation=rel)  # type: ignore[arg-type]
                )

        for sym in self.symbols.values():
            imp_map = self.file_import_map.get(sym.file_path, {})
            enclosing_cls = (
                sym.qualname.split(".", 1)[0]
                if sym.kind == "method" and "." in sym.qualname
                else None
            )
            rel_kind = "test_invokes" if sym.is_test else "calls"

            # Find classes instantiated or imported in this symbol to resolve method calls
            referenced_classes: list[tuple[str, str]] = []
            for call_name in sym.calls:
                if call_name in imp_map:
                    target_spec = imp_map[call_name]
                    t_file, t_sym = target_spec.split("::", 1)
                    if (t_file, t_sym) in class_methods:
                        referenced_classes.append((t_file, t_sym))
                for cand in by_name.get(call_name, []):
                    if cand.kind == "class" and not cand.is_test:
                        referenced_classes.append((cand.file_path, cand.name))

            for call_name in sym.calls:
                # 1. self.method() inside a class
                if call_name.startswith("self.") and enclosing_cls:
                    meth = call_name.split(".", 1)[1]
                    sibling = class_methods.get((sym.file_path, enclosing_cls), {}).get(meth)
                    if sibling:
                        add_edge(sym.symbol_id, sibling.symbol_id, rel_kind)
                        continue

                # 2. Qualified module/class attribute call: Alias.func()
                if "." in call_name:
                    prefix, attr = call_name.split(".", 1)
                    if prefix in imp_map:
                        t_file, t_sym = imp_map[prefix].split("::", 1)
                        if t_sym == "*":
                            for cand in by_file_name.get((t_file, attr), []):
                                add_edge(sym.symbol_id, cand.symbol_id, rel_kind)
                        else:
                            meth_sym = class_methods.get((t_file, t_sym), {}).get(attr)
                            if meth_sym:
                                add_edge(sym.symbol_id, meth_sym.symbol_id, rel_kind)
                    continue

                # 3. Direct imported function/class call
                if call_name in imp_map:
                    t_file, t_sym = imp_map[call_name].split("::", 1)
                    for cand in by_file_name.get((t_file, t_sym), []):
                        add_edge(sym.symbol_id, cand.symbol_id, rel_kind)
                        if cand.kind == "class":
                            init_sym = class_methods.get((t_file, cand.name), {}).get("__init__")
                            if init_sym:
                                add_edge(sym.symbol_id, init_sym.symbol_id, rel_kind)
                    continue

                # 4. Same-file function/class call
                same_file_cands = by_file_name.get((sym.file_path, call_name), [])
                if same_file_cands:
                    for cand in same_file_cands:
                        add_edge(sym.symbol_id, cand.symbol_id, rel_kind)
                    continue

                # 5. Method invoked on an instantiated class in this scope (e.g. cache.get() in a test)
                matched_ref = False
                for ref_file, ref_cls in referenced_classes:
                    meth_sym = class_methods.get((ref_file, ref_cls), {}).get(call_name)
                    if meth_sym:
                        add_edge(sym.symbol_id, meth_sym.symbol_id, rel_kind)
                        matched_ref = True

                # 6. Unique non-test method/function name across repo
                if not matched_ref:
                    prod_cands = [
                        c for c in by_name.get(call_name, []) if not c.is_test
                    ]
                    if len(prod_cands) == 1:
                        add_edge(sym.symbol_id, prod_cands[0].symbol_id, rel_kind)

    def production_files(self) -> list[str]:
        """Return sorted list of non-test Python source file paths."""
        self._ensure_indexed()
        return sorted(
            fp
            for fp in self.files_source
            if not (fp.startswith("tests/") or Path(fp).name.startswith("test_"))
        )

    def candidate_symbols(self) -> list[SymbolNode]:
        """Return non-test candidate symbols suitable for fault localization."""
        self._ensure_indexed()
        # Classes that contain methods are represented via their methods + skeleton map;
        # standalone dataclasses/enums without methods remain direct candidates.
        classes_with_methods = {
            (sym.file_path, sym.qualname.split(".", 1)[0])
            for sym in self.symbols.values()
            if not sym.is_test and sym.kind == "method" and "." in sym.qualname
        }
        result: list[SymbolNode] = []
        for sym in self.symbols.values():
            if sym.is_test:
                continue
            if sym.kind == "class" and (sym.file_path, sym.name) in classes_with_methods:
                continue
            result.append(sym)
        return result

    def raw_repository_tokens(self) -> int:
        """Compute total tokens if every non-test Python file were dumped verbatim."""
        self._ensure_indexed()
        chunks = [
            f"# === File: {fp} ===\n{self.files_source[fp]}"
            for fp in self.production_files()
        ]
        return estimate_tokens("\n\n".join(chunks))

    def build_repo_skeleton_map(self) -> str:
        """Build a compact AST symbol skeleton map across all production files."""
        self._ensure_indexed()
        lines: list[str] = ["# AST Repository Map"]
        by_file: dict[str, list[SymbolNode]] = defaultdict(list)
        for sym in self.symbols.values():
            if not sym.is_test:
                by_file[sym.file_path].append(sym)

        for fp in self.production_files():
            syms = sorted(by_file.get(fp, []), key=lambda s: (s.start_line, s.kind != "class"))
            if not syms:
                continue
            entries: list[str] = []
            methods_by_cls: dict[str, list[str]] = defaultdict(list)
            for sym in syms:
                if sym.kind == "method" and "." in sym.qualname:
                    cls_name, meth_name = sym.qualname.split(".", 1)
                    methods_by_cls[cls_name].append(meth_name)
            for sym in syms:
                if sym.kind == "class":
                    meths = methods_by_cls.get(sym.name, [])
                    if meths:
                        entries.append(f"class {sym.name}({', '.join(meths)})")
                    else:
                        entries.append(f"class {sym.name}")
                elif sym.kind == "function":
                    entries.append(f"def {sym.name}()")
            lines.append(f"- {fp}: {'; '.join(entries)}")
        return "\n".join(lines)

    def localize_faults(
        self,
        issue_description: str,
        test_result: SandboxTestResult | None = None,
        top_k: int = 5,
    ) -> list[ScoredSymbol]:
        """Rank candidate production symbols using BM25 + Stacktrace/Test-Call + 1-Hop Graph."""
        self._ensure_indexed()
        candidates = self.candidate_symbols()
        if not candidates:
            return []

        # Build query tokens from issue + failure messages
        query_parts = [issue_description]
        if test_result and test_result.failures:
            for fail in test_result.failures:
                query_parts.append(fail.test_name)
                query_parts.append(fail.message)
                query_parts.append(fail.traceback_excerpt)
        query_tokens = tokenize_identifiers(" ".join(query_parts))

        # 1. Okapi BM25 over weighted symbol documents
        docs: dict[str, Counter[str]] = {}
        doc_lens: dict[str, int] = {}
        df: Counter[str] = Counter()

        for sym in candidates:
            header_toks = tokenize_identifiers(f"{sym.file_path} {sym.qualname}") * 3
            sig_doc_toks = tokenize_identifiers(f"{sym.signature} {sym.docstring}") * 2
            body_toks = tokenize_identifiers(sym.source)
            combined = header_toks + sig_doc_toks + body_toks
            counts = Counter(combined)
            docs[sym.symbol_id] = counts
            doc_lens[sym.symbol_id] = max(1, len(combined))
            for term in counts:
                df[term] += 1

        n_docs = len(candidates)
        avgdl = sum(doc_lens.values()) / max(1, n_docs)
        k1, b = 1.5, 0.75

        bm25_scores: dict[str, float] = {}
        reasons: dict[str, list[str]] = defaultdict(list)

        q_counts = Counter(query_tokens)
        for sym in candidates:
            sid = sym.symbol_id
            d_counts = docs[sid]
            dl = doc_lens[sid]
            score = 0.0
            matched_terms: list[str] = []
            for term, qf in q_counts.items():
                tf = d_counts.get(term, 0)
                if tf == 0:
                    continue
                idf = math.log(1.0 + (n_docs - df[term] + 0.5) / (df[term] + 0.5))
                denom = tf + k1 * (1.0 - b + b * dl / avgdl)
                score += idf * ((tf * (k1 + 1.0)) / denom) * (1.0 + 0.1 * min(qf, 3))
                matched_terms.append(term)
            bm25_scores[sid] = score
            if matched_terms:
                reasons[sid].append(f"bm25({','.join(matched_terms[:4])})")

        # 2. Stacktrace & failing-test invocation scoring
        trace_scores: dict[str, float] = defaultdict(float)
        if test_result and test_result.failures:
            failing_test_names = {
                f.test_name.split("::")[-1] for f in test_result.failures
            }
            failing_test_ids = {
                sym.symbol_id
                for sym in self.symbols.values()
                if sym.is_test and sym.name in failing_test_names
            }
            called_by_failing: set[str] = {
                edge.callee_id
                for edge in self.edges
                if edge.caller_id in failing_test_ids
            }

            frame_hits: list[tuple[str, int]] = []
            frame_files: set[str] = set()
            for fail in test_result.failures:
                for fr in fail.frames:
                    norm_fp = fr.file_path.replace("\\", "/")
                    frame_hits.append((norm_fp, fr.line))
                    frame_files.add(norm_fp)

            for sym in candidates:
                sid = sym.symbol_id
                for fp, line in frame_hits:
                    if fp.endswith(sym.file_path) or sym.file_path.endswith(fp):
                        if sym.start_line <= line <= sym.end_line:
                            trace_scores[sid] += 6.0
                            reasons[sid].append(f"stacktrace_line(L{line})")
                            break
                else:
                    if any(
                        fp.endswith(sym.file_path) or sym.file_path.endswith(fp)
                        for fp in frame_files
                    ):
                        trace_scores[sid] += 1.5
                        reasons[sid].append("stacktrace_file")

                if sid in called_by_failing:
                    trace_scores[sid] += 3.5
                    reasons[sid].append("called_by_failing_test")

        # 3. 1-Hop Call-Graph Propagation across candidate symbols
        cand_ids = {s.symbol_id for s in candidates}
        base_scores = {
            sid: bm25_scores.get(sid, 0.0) + trace_scores.get(sid, 0.0)
            for sid in cand_ids
        }
        graph_scores: dict[str, float] = defaultdict(float)

        for edge in self.edges:
            u, v = edge.caller_id, edge.callee_id
            if u in cand_ids and v in cand_ids:
                if base_scores[u] > 0:
                    contrib = 0.45 * base_scores[u]
                    graph_scores[v] += contrib
                    reasons[v].append(f"callee_of({u.split('::')[-1]})")
                if base_scores[v] > 0:
                    contrib = 0.25 * base_scores[v]
                    graph_scores[u] += contrib
                    reasons[u].append(f"caller_of({v.split('::')[-1]})")

        scored: list[ScoredSymbol] = []
        for sym in candidates:
            sid = sym.symbol_id
            b_s = round(bm25_scores.get(sid, 0.0), 4)
            t_s = round(trace_scores.get(sid, 0.0), 4)
            g_s = round(graph_scores.get(sid, 0.0), 4)
            tot = round(b_s + t_s + g_s, 4)
            scored.append(
                ScoredSymbol(
                    symbol_id=sid,
                    file_path=sym.file_path,
                    qualname=sym.qualname,
                    kind=sym.kind,
                    start_line=sym.start_line,
                    end_line=sym.end_line,
                    bm25_score=b_s,
                    stacktrace_score=t_s,
                    graph_score=g_s,
                    total_score=tot,
                    reasons=list(dict.fromkeys(reasons[sid]))[:5],
                )
            )

        scored.sort(key=lambda s: (-s.total_score, s.file_path, s.start_line))
        return scored[:top_k]

    def build_full_context(self, token_budget: int = 1550) -> ContextBundle:
        """Build unpruned full-file baseline context up to `token_budget` tokens."""
        self._ensure_indexed()
        raw_tokens = self.raw_repository_tokens()
        prod_files = self.production_files()

        included_files: list[str] = []
        truncated_files: list[str] = []
        chunks: list[str] = ["# Repository Source Files (Unpruned Alphabetical Window)"]
        used_tokens = estimate_tokens(chunks[0])

        for idx, fp in enumerate(prod_files):
            block = f"# === File: {fp} ===\n{self.files_source[fp]}"
            block_tokens = estimate_tokens(block)
            if used_tokens + block_tokens <= token_budget:
                chunks.append(block)
                used_tokens += block_tokens
                included_files.append(fp)
            else:
                remaining = token_budget - used_tokens
                if remaining > 135:
                    # Include partial lines up to budget
                    partial_lines: list[str] = [f"# === File: {fp} (TRUNCATED) ==="]
                    running = estimate_tokens(partial_lines[0])
                    for line in self.files_source[fp].splitlines():
                        lt = estimate_tokens(line)
                        if running + lt + 12 > remaining:
                            break
                        partial_lines.append(line)
                        running += lt
                    partial_lines.append("# ... [TRUNCATED DUE TO CONTEXT WINDOW BUDGET]")
                    chunks.append("\n".join(partial_lines))
                truncated_files.extend(prod_files[idx:])
                break

        prompt_context = "\n\n".join(chunks)
        ctx_tokens = estimate_tokens(prompt_context)
        red_vs_raw = (
            round(max(0.0, (raw_tokens - ctx_tokens) / raw_tokens * 100.0), 2)
            if raw_tokens > 0
            else 0.0
        )

        return ContextBundle(
            mode="full_context",
            prompt_context=prompt_context,
            repo_map="",
            ranked_symbols=[],
            selected_symbol_ids=[],
            included_files=included_files,
            truncated_files=truncated_files,
            raw_repo_tokens=raw_tokens,
            full_baseline_tokens=ctx_tokens,
            context_tokens=ctx_tokens,
            token_reduction_vs_raw_pct=red_vs_raw,
            token_reduction_vs_baseline_pct=0.0,
        )

    def build_localized_context(
        self,
        issue_description: str,
        test_result: SandboxTestResult | None = None,
        top_k: int = 4,
        baseline_token_budget: int = 1550,
    ) -> ContextBundle:
        """Build compressed AST Repo Map + Top-K Localized Symbol Source context."""
        self._ensure_indexed()
        raw_tokens = self.raw_repository_tokens()
        baseline_bundle = self.build_full_context(token_budget=baseline_token_budget)
        full_baseline_tokens = baseline_bundle.context_tokens

        ranked = self.localize_faults(
            issue_description=issue_description,
            test_result=test_result,
            top_k=top_k,
        )
        repo_map = self.build_repo_skeleton_map()

        # Group selected symbols by file and deduplicate overlapping spans
        by_file: dict[str, list[ScoredSymbol]] = defaultdict(list)
        for item in ranked:
            by_file[item.file_path].append(item)

        focused_sections: list[str] = [
            repo_map,
            "# Focused Suspect Symbols (Full Source for AST-Localized Targets)",
        ]
        included_files: list[str] = []

        for fp in sorted(by_file):
            included_files.append(fp)
            file_lines = self.files_source[fp].splitlines()
            # Include top-of-file import statements for context
            import_lines: list[str] = []
            for line in file_lines[:35]:
                stripped = line.strip()
                if stripped.startswith(("import ", "from ", "from __future__")):
                    import_lines.append(line)

            section_lines = [f"# === File: {fp} (AST-Localized Excerpts) ==="]
            if import_lines:
                section_lines.extend(import_lines)
                section_lines.append("")

            emitted_classes: set[str] = set()
            covered_ranges: list[tuple[int, int]] = []

            for scored_sym in sorted(by_file[fp], key=lambda s: s.start_line):
                sym = self.symbols[scored_sym.symbol_id]
                if any(
                    r_start <= sym.start_line and sym.end_line <= r_end
                    for r_start, r_end in covered_ranges
                ):
                    continue
                if sym.kind == "method" and "." in sym.qualname:
                    cls_name = sym.qualname.split(".", 1)[0]
                    cls_sym = self.symbols.get(f"{fp}::{cls_name}")
                    if cls_sym and cls_name not in emitted_classes:
                        section_lines.append(f"{cls_sym.signature}  # Enclosing class")
                        emitted_classes.add(cls_name)

                section_lines.append(
                    f"# [Suspect Symbol: {sym.qualname} | L{sym.start_line}-L{sym.end_line} | score={scored_sym.total_score:.2f}]"
                )
                section_lines.append(sym.source)
                section_lines.append("")
                covered_ranges.append((sym.start_line, sym.end_line))

            focused_sections.append("\n".join(section_lines).rstrip())

        prompt_context = "\n\n".join(focused_sections)
        ctx_tokens = estimate_tokens(prompt_context)

        red_vs_raw = (
            round((raw_tokens - ctx_tokens) / raw_tokens * 100.0, 2)
            if raw_tokens > 0
            else 0.0
        )
        red_vs_base = (
            round((full_baseline_tokens - ctx_tokens) / full_baseline_tokens * 100.0, 2)
            if full_baseline_tokens > 0
            else 0.0
        )

        return ContextBundle(
            mode="ast_localized",
            prompt_context=prompt_context,
            repo_map=repo_map,
            ranked_symbols=ranked,
            selected_symbol_ids=[s.symbol_id for s in ranked],
            included_files=included_files,
            truncated_files=[],
            raw_repo_tokens=raw_tokens,
            full_baseline_tokens=full_baseline_tokens,
            context_tokens=ctx_tokens,
            token_reduction_vs_raw_pct=red_vs_raw,
            token_reduction_vs_baseline_pct=red_vs_base,
        )
