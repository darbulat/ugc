"""Architecture guards for Max handlers."""

import ast
from pathlib import Path


def _repo_root() -> Path:
    """Return repository root for source-file based checks."""
    return Path(__file__).resolve().parents[4]


def _src_root() -> Path:
    """Return application source root."""
    return _repo_root() / "src"


def _max_handlers_dir() -> Path:
    """Return Max handlers directory."""
    return _src_root() / "ugc_bot" / "bot" / "max" / "handlers"


def _telegram_module_path(module_name: str) -> Path:
    """Convert a telegram module path to a source file path."""
    return _src_root() / Path(*module_name.split(".")).with_suffix(".py")


def _read_ast(path: Path) -> ast.AST:
    """Parse a Python file into AST."""
    return ast.parse(path.read_text(encoding="utf-8"))


def _iter_imported_telegram_functions(
    max_handler_path: Path,
) -> list[tuple[str, str]]:
    """Return imported telegram-handler function references."""
    imported: list[tuple[str, str]] = []
    tree = _read_ast(max_handler_path)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        if not node.module.startswith("ugc_bot.bot.telegram.handlers."):
            continue
        for alias in node.names:
            if alias.name == "*":
                continue
            imported.append((node.module, alias.name))
    return imported


def _function_contains_set_state(module_path: Path, function_name: str) -> bool:
    """Return True when a top-level function calls ``set_state``."""
    tree = _read_ast(module_path)
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != function_name:
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Call):
                continue
            func = inner.func
            if isinstance(func, ast.Attribute) and func.attr == "set_state":
                return True
    return False


def test_max_handlers_do_not_import_telegram_stateful_helpers() -> None:
    """Max handlers must not reuse telegram helpers that mutate FSM state."""
    offenders: list[str] = []

    for max_handler_path in sorted(_max_handlers_dir().glob("*.py")):
        for module_name, function_name in _iter_imported_telegram_functions(
            max_handler_path
        ):
            telegram_module_path = _telegram_module_path(module_name)
            if not telegram_module_path.exists():
                continue
            if not _function_contains_set_state(
                telegram_module_path, function_name
            ):
                continue
            offenders.append(
                (
                    f"{max_handler_path.relative_to(_repo_root())} imports "
                    f"{function_name} from {module_name}"
                )
            )

    assert offenders == [], (
        "Max handlers import telegram helpers that call set_state():\n"
        + "\n".join(offenders)
    )
