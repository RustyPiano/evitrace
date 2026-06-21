#!/usr/bin/env python3
from __future__ import annotations

import ast
import builtins
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1] / "app"
IGNORED_NAMES = set(dir(builtins)) | {
    "Annotated",
    "Any",
    "Callable",
    "ClassVar",
    "Literal",
    "Mapped",
    "Optional",
    "Self",
    "Union",
}


class AnnotationVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        self.names.add(node.id)


def has_future_annotations(tree: ast.Module) -> bool:
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            return any(alias.name == "annotations" for alias in node.names)
        if not isinstance(node, (ast.Expr, ast.Import, ast.ImportFrom)):
            break
    return False


def defined_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".", 1)[0])
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                names.update(target_names(target))
        elif isinstance(node, ast.AnnAssign):
            names.update(target_names(node.target))
    return names


def target_names(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, (ast.Tuple, ast.List)):
        names: set[str] = set()
        for element in node.elts:
            names.update(target_names(element))
        return names
    return set()


def annotation_names(tree: ast.Module) -> set[str]:
    visitor = AnnotationVisitor()
    for node in ast.walk(tree):
        annotations: list[ast.AST | None] = []
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            annotations.extend(arg.annotation for arg in node.args.args)
            annotations.extend(arg.annotation for arg in node.args.kwonlyargs)
            annotations.extend(arg.annotation for arg in node.args.posonlyargs)
            if node.args.vararg is not None:
                annotations.append(node.args.vararg.annotation)
            if node.args.kwarg is not None:
                annotations.append(node.args.kwarg.annotation)
            annotations.append(node.returns)
        elif isinstance(node, ast.AnnAssign):
            annotations.append(node.annotation)
        for annotation in annotations:
            if annotation is not None:
                visitor.visit(annotation)
    return visitor.names


def main() -> int:
    failures: list[str] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if has_future_annotations(tree):
            continue
        missing = annotation_names(tree) - defined_names(tree) - IGNORED_NAMES
        if missing:
            rel = path.relative_to(APP_ROOT.parents[0])
            failures.append(f"{rel}: {', '.join(sorted(missing))}")

    if failures:
        print("Annotation names would fail under Python 3.11 eager evaluation:")
        print("\n".join(failures))
        return 1
    print("OK: no backend/app annotation names are undefined under Python 3.11 eager evaluation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
