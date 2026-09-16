from __future__ import annotations

import ast
import sys
from pathlib import Path


def python_files(inputs: list[str]) -> list[Path]:
    files=[]
    for raw in inputs:
        path=Path(raw)
        if path.is_dir(): files.extend(p for p in path.rglob("*.py") if "__pycache__" not in p.parts)
        elif path.is_file() and path.suffix==".py": files.append(path)
        else: raise ValueError(f"unsupported lint input: {raw}")
    return sorted(set(files))


def import_name(node: ast.AST) -> list[str]:
    if isinstance(node,ast.Import): return [alias.name for alias in node.names]
    if isinstance(node,ast.ImportFrom): return [node.module or ""]
    return []


def lint_file(path: Path) -> list[str]:
    errors=[]; raw=path.read_bytes()
    if b"\r" in raw: errors.append("CR/LF text is forbidden")
    try: text=raw.decode("utf-8")
    except UnicodeError: return ["not UTF-8"]
    for no,line in enumerate(text.splitlines(),1):
        if line.rstrip(" \t") != line: errors.append(f"line {no}: trailing whitespace")
        prefix=line[:len(line)-len(line.lstrip())]
        if "\t" in prefix: errors.append(f"line {no}: tab indentation")
    try: tree=ast.parse(text,filename=str(path))
    except SyntaxError as exc: return errors+[f"AST parse failed: {exc.msg}"]
    normalized=path.as_posix().lower(); in_full_mcp="runtime/full_mcp/" in normalized
    for node in ast.walk(tree):
        for name in import_name(node):
            lowered=name.lower()
            if "project_memory" in lowered or "jarvis" in lowered: errors.append(f"forbidden dependency import: {name}")
            if in_full_mcp and (lowered.endswith("provider_router") or ".provider_router" in lowered): errors.append(f"provider routing import forbidden: {name}")
            if path.name=="production_execution_gateway.py" and (lowered=="runtime.full_mcp" or lowered.startswith("runtime.full_mcp.")):
                errors.append(f"gateway consumer boundary violation: {name}")
        if in_full_mcp and isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and "provider" in node.name.lower() and any(word in node.name.lower() for word in ("route","select","assign")):
            errors.append(f"provider routing function forbidden: {node.name}")
    return errors


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: full_mcp_lint.py <python-file-or-dir> [...]",file=sys.stderr); return 2
    try: files=python_files(argv)
    except ValueError as exc: print(str(exc),file=sys.stderr); return 2
    failures=[]
    for path in files:
        for error in lint_file(path): failures.append(f"{path}: {error}")
    if failures:
        print("\n".join(failures),file=sys.stderr); return 1
    print(f"FULL_MCP_LINT=PASS files={len(files)}"); return 0


if __name__=="__main__": raise SystemExit(main(sys.argv[1:]))
