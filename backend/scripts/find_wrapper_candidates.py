#!/usr/bin/env python3
"""Find low-call-count Python wrapper candidates in the backend codebase.

This script performs a lightweight AST-based scan over repository Python files and
reports functions/methods that look like thin wrappers:

- a single executable statement
- that statement returns/awaits a direct call
- most arguments are forwarded from the wrapper's own parameters

It also counts resolved call sites with simple static resolution, which is useful
for finding "single real consumer" layers before manual review.
"""

from __future__ import annotations

import argparse
import ast
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCAN_ROOTS = ("app", "tests")


@dataclass(frozen=True, slots=True)
class ImportTarget:
    kind: Literal["module", "symbol", "class"]
    target: str


@dataclass(frozen=True, slots=True)
class Symbol:
    symbol_id: str
    module: str
    qualname: str
    kind: Literal["function", "method"]
    path: Path
    lineno: int
    params: tuple[str, ...]
    class_name: str | None
    is_async: bool
    node: ast.FunctionDef | ast.AsyncFunctionDef


@dataclass(frozen=True, slots=True)
class CallSite:
    caller_symbol_id: str
    caller_path: Path
    lineno: int
    target_symbol_id: str
    target_expr: str


@dataclass(frozen=True, slots=True)
class WrapperCandidate:
    symbol: Symbol
    call_count: int
    target_expr: str
    target_symbol_id: str | None
    caller_sites: tuple[CallSite, ...]


def repo_rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def module_name_for_path(path: Path) -> str:
    rel = path.relative_to(REPO_ROOT)
    parts = rel.with_suffix("").parts
    return ".".join(parts)


def iter_python_files(roots: Iterable[str]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        base = REPO_ROOT / root
        if not base.exists():
            continue
        files.extend(
            path for path in base.rglob("*.py") if "__pycache__" not in path.parts
        )
    return sorted(set(files))


class SymbolCollector(ast.NodeVisitor):
    def __init__(self, module: str, path: Path) -> None:
        self.module = module
        self.path = path
        self.symbols: list[Symbol] = []
        self._class_stack: list[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._class_stack.append(node.name)
        self.generic_visit(node)
        self._class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._add_symbol(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._add_symbol(node, is_async=True)

    def _add_symbol(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        *,
        is_async: bool,
    ) -> None:
        class_name = self._class_stack[-1] if self._class_stack else None
        qualname = f"{class_name}.{node.name}" if class_name else node.name
        params = tuple(
            arg.arg
            for arg in (
                *node.args.posonlyargs,
                *node.args.args,
                *node.args.kwonlyargs,
            )
        )
        symbol_id = f"{self.module}:{qualname}"
        self.symbols.append(
            Symbol(
                symbol_id=symbol_id,
                module=self.module,
                qualname=qualname,
                kind="method" if class_name else "function",
                path=self.path,
                lineno=node.lineno,
                params=params,
                class_name=class_name,
                is_async=is_async,
                node=node,
            )
        )
        if class_name is None:
            return
        # Do not descend into nested defs. Methods are handled as their own symbols.


def collect_imports(tree: ast.AST, current_module: str) -> dict[str, ImportTarget]:
    imports: dict[str, ImportTarget] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound = alias.asname or alias.name.split(".")[-1]
                imports[bound] = ImportTarget("module", alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = resolve_relative_import(current_module, node.module, node.level)
            if module is None:
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                bound = alias.asname or alias.name
                target = f"{module}.{alias.name}"
                imports[bound] = ImportTarget("symbol", target)
    return imports


def resolve_relative_import(
    current_module: str, imported: str | None, level: int
) -> str | None:
    if level == 0:
        return imported
    base_parts = current_module.split(".")
    if len(base_parts) < level:
        return imported
    prefix = base_parts[:-level]
    if imported:
        prefix.extend(imported.split("."))
    return ".".join(prefix) if prefix else imported


def get_executable_body(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[ast.stmt]:
    body = list(node.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    return body


def unwrap_call_expression(expr: ast.AST) -> ast.Call | None:
    if isinstance(expr, ast.Await):
        return expr.value if isinstance(expr.value, ast.Call) else None
    return expr if isinstance(expr, ast.Call) else None


def is_simple_forward_value(expr: ast.AST, params: set[str]) -> bool:
    if isinstance(expr, ast.Name):
        return expr.id in params
    if isinstance(expr, ast.Constant):
        return True
    if isinstance(expr, ast.Attribute) and isinstance(expr.value, ast.Name):
        return expr.value.id in {"self", "cls"}
    if isinstance(expr, ast.Starred):
        return is_simple_forward_value(expr.value, params)
    return False


def format_expr(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return node.__class__.__name__


def looks_like_wrapper(symbol: Symbol) -> tuple[bool, str | None]:
    body = get_executable_body(symbol.node)
    if len(body) != 1:
        return False, None
    stmt = body[0]
    if not isinstance(stmt, ast.Return) or stmt.value is None:
        return False, None
    call = unwrap_call_expression(stmt.value)
    if call is None:
        return False, None
    params = set(symbol.params)
    if any(not is_simple_forward_value(arg, params) for arg in call.args):
        return False, None
    if any(
        keyword.value is not None and not is_simple_forward_value(keyword.value, params)
        for keyword in call.keywords
    ):
        return False, None
    return True, format_expr(call.func)


class CallResolver(ast.NodeVisitor):
    def __init__(
        self,
        *,
        caller: Symbol,
        symbols_by_id: dict[str, Symbol],
        module_top_level_functions: dict[str, str],
        module_class_methods: dict[tuple[str, str], str],
        imports: dict[str, ImportTarget],
    ) -> None:
        self.caller = caller
        self.symbols_by_id = symbols_by_id
        self.module_top_level_functions = module_top_level_functions
        self.module_class_methods = module_class_methods
        self.imports = imports
        self.calls: list[CallSite] = []

    def visit_Call(self, node: ast.Call) -> None:
        resolved_id = self._resolve_target(node.func)
        if resolved_id is not None:
            self.calls.append(
                CallSite(
                    caller_symbol_id=self.caller.symbol_id,
                    caller_path=self.caller.path,
                    lineno=node.lineno,
                    target_symbol_id=resolved_id,
                    target_expr=format_expr(node.func),
                )
            )
        self.generic_visit(node)

    def _resolve_target(self, func: ast.AST) -> str | None:
        if isinstance(func, ast.Name):
            imported = self.imports.get(func.id)
            if imported is not None:
                resolved = self._resolve_import_target(imported)
                if resolved is not None:
                    return resolved
            return self.module_top_level_functions.get(func.id)

        if not isinstance(func, ast.Attribute) or not isinstance(func.value, ast.Name):
            return None

        owner = func.value.id
        if owner in {"self", "cls"} and self.caller.class_name:
            return self.module_class_methods.get((self.caller.class_name, func.attr))

        imported = self.imports.get(owner)
        if imported is None:
            return None

        if imported.kind == "module":
            return self._resolve_symbol_in_module(imported.target, func.attr)
        if imported.kind in {"symbol", "class"}:
            imported_module, _, imported_name = imported.target.rpartition(".")
            if imported_name and (imported_name, func.attr) in {
                (symbol.class_name or "", symbol.qualname.split(".")[-1])
                for symbol in self.symbols_by_id.values()
            }:
                return self.module_class_methods.get((imported_name, func.attr)) or (
                    f"{imported_module}:{imported_name}.{func.attr}"
                    if f"{imported_module}:{imported_name}.{func.attr}"
                    in self.symbols_by_id
                    else None
                )
        return None

    def _resolve_import_target(self, imported: ImportTarget) -> str | None:
        if imported.kind == "module":
            return None
        module, _, name = imported.target.rpartition(".")
        return self._resolve_symbol_in_module(module, name)

    def _resolve_symbol_in_module(self, module: str, name: str) -> str | None:
        candidate = f"{module}:{name}"
        if candidate in self.symbols_by_id:
            return candidate
        method_candidates = [
            symbol.symbol_id
            for symbol in self.symbols_by_id.values()
            if symbol.module == module
            and symbol.class_name is not None
            and symbol.qualname.split(".")[-1] == name
        ]
        if len(method_candidates) == 1:
            return method_candidates[0]
        return None


def build_indices(
    symbols: Iterable[Symbol],
) -> tuple[
    dict[str, Symbol],
    dict[str, dict[str, str]],
    dict[str, dict[tuple[str, str], str]],
]:
    symbols_by_id: dict[str, Symbol] = {}
    module_functions: dict[str, dict[str, str]] = defaultdict(dict)
    module_methods: dict[str, dict[tuple[str, str], str]] = defaultdict(dict)
    for symbol in symbols:
        symbols_by_id[symbol.symbol_id] = symbol
        if symbol.class_name is None:
            module_functions[symbol.module][symbol.qualname] = symbol.symbol_id
        else:
            module_methods[symbol.module][
                (symbol.class_name, symbol.qualname.split(".")[-1])
            ] = symbol.symbol_id
    return symbols_by_id, module_functions, module_methods


def scan_symbols(
    roots: Iterable[str],
) -> tuple[list[Symbol], dict[str, ast.AST], dict[str, dict[str, ImportTarget]]]:
    symbols: list[Symbol] = []
    trees: dict[str, ast.AST] = {}
    imports_by_module: dict[str, dict[str, ImportTarget]] = {}
    for path in iter_python_files(roots):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        module = module_name_for_path(path)
        trees[module] = tree
        imports_by_module[module] = collect_imports(tree, module)
        collector = SymbolCollector(module, path)
        collector.visit(tree)
        symbols.extend(collector.symbols)
    return symbols, trees, imports_by_module


def build_call_graph(
    symbols: list[Symbol],
    trees: dict[str, ast.AST],
    imports_by_module: dict[str, dict[str, ImportTarget]],
) -> dict[str, list[CallSite]]:
    symbols_by_id, module_functions, module_methods = build_indices(symbols)
    calls_by_target: dict[str, list[CallSite]] = defaultdict(list)
    for symbol in symbols:
        resolver = CallResolver(
            caller=symbol,
            symbols_by_id=symbols_by_id,
            module_top_level_functions=module_functions.get(symbol.module, {}),
            module_class_methods=module_methods.get(symbol.module, {}),
            imports=imports_by_module.get(symbol.module, {}),
        )
        for stmt in get_executable_body(symbol.node):
            resolver.visit(stmt)
        for call in resolver.calls:
            calls_by_target[call.target_symbol_id].append(call)
    return calls_by_target


def find_candidates(
    symbols: list[Symbol],
    calls_by_target: dict[str, list[CallSite]],
    *,
    max_callers: int,
) -> list[WrapperCandidate]:
    candidates: list[WrapperCandidate] = []
    for symbol in symbols:
        looks_wrapper, target_expr = looks_like_wrapper(symbol)
        if not looks_wrapper or target_expr is None:
            continue
        caller_sites = tuple(calls_by_target.get(symbol.symbol_id, ()))
        if len(caller_sites) > max_callers:
            continue
        target_symbol_id = caller_sites[0].target_symbol_id if caller_sites else None
        candidates.append(
            WrapperCandidate(
                symbol=symbol,
                call_count=len(caller_sites),
                target_expr=target_expr,
                target_symbol_id=target_symbol_id,
                caller_sites=caller_sites,
            )
        )
    candidates.sort(
        key=lambda item: (
            item.call_count,
            repo_rel(item.symbol.path),
            item.symbol.lineno,
        )
    )
    return candidates


def print_report(candidates: list[WrapperCandidate], *, limit: int | None) -> None:
    if not candidates:
        print("No wrapper candidates found.")
        return
    shown = candidates if limit is None else candidates[:limit]
    print(f"Found {len(candidates)} wrapper candidates.")
    for candidate in shown:
        symbol = candidate.symbol
        print(
            f"\n[{candidate.call_count:>2} callers] {symbol.kind} "
            f"{symbol.symbol_id} @ {repo_rel(symbol.path)}:{symbol.lineno}"
        )
        print(f"  forwards -> {candidate.target_expr}")
        if candidate.caller_sites:
            print("  callers:")
            for site in candidate.caller_sites:
                print(
                    "   - "
                    f"{repo_rel(site.caller_path)}:{site.lineno} "
                    f"in {site.caller_symbol_id}"
                )
        else:
            print("  callers: none resolved")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find low-call-count thin-wrapper candidates in backend Python code."
    )
    parser.add_argument(
        "--roots",
        nargs="+",
        default=list(DEFAULT_SCAN_ROOTS),
        help="Repository-relative directories to scan. Defaults to app tests.",
    )
    parser.add_argument(
        "--max-callers",
        type=int,
        default=2,
        help="Only show wrapper candidates with at most this many callers.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of results to print. Use 0 for all.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    symbols, trees, imports_by_module = scan_symbols(args.roots)
    calls_by_target = build_call_graph(symbols, trees, imports_by_module)
    candidates = find_candidates(
        symbols,
        calls_by_target,
        max_callers=max(args.max_callers, 0),
    )
    print_report(candidates, limit=None if args.limit == 0 else args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
