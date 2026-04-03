from __future__ import annotations

import ast
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[2] / "app"


def _find_function(
    tree: ast.AST, function_name: str
) -> ast.AsyncFunctionDef | ast.FunctionDef:
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
            and node.name == function_name
        ):
            return node
    raise AssertionError(f"Function {function_name!r} not found")


def _called_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Name):
            names.add(func.id)
        elif isinstance(func, ast.Attribute):
            names.add(func.attr)
    return names


def test_high_risk_routes_use_shared_external_call_boundary_helpers() -> None:
    expectations = [
        (
            _APP_ROOT / "features/hub_agents/router.py",
            "validate_hub_agent_card",
            "load_for_external_call",
        ),
        (
            _APP_ROOT / "features/personal_agents/router.py",
            "validate_agent_card",
            "load_for_external_call",
        ),
        (
            _APP_ROOT / "features/extension_capabilities/common_router.py",
            "_get_runtime_for_external_call",
            "load_for_external_call",
        ),
        (
            _APP_ROOT / "features/invoke/route_runner.py",
            "_close_open_transaction",
            "prepare_for_external_call",
        ),
    ]

    for file_path, function_name, helper_name in expectations:
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
        function_node = _find_function(tree, function_name)
        assert helper_name in _called_names(function_node), (
            f"{file_path.name}:{function_name} must call {helper_name} "
            "to enforce the shared async-session boundary"
        )
