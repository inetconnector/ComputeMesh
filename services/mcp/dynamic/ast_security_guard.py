# SPDX-License-Identifier: Apache-2.0
"""
Static AST Security Guard for Dynamic Self-Programming MCP Tools.
Zero-Trust static code analysis enforcing strict module whitelisting,
banning code-execution/introspections builtins, and blocking dunder escapes.
"""

from __future__ import annotations

import ast
from typing import Set


class SecurityASTViolation(Exception):
    """Raised when dynamically generated code violates security policies."""
    pass


class SecurityASTVisitor(ast.NodeVisitor):
    """Recursively validates Python AST against Zero-Trust security rules."""

    ALLOWED_MODULES: Set[str] = {
        "math", "cmath", "random", "re", "json", "datetime", "time",
        "itertools", "functools", "collections", "scipy", "numpy",
        "pandas", "shapely", "networkx", "sympy", "urllib.parse",
        "hashlib", "base64", "csv", "string", "typing", "dataclasses",
        "statistics", "decimal", "fractions", "bisect", "heapq"
    }

    FORBIDDEN_BUILTINS: Set[str] = {
        "eval", "exec", "compile", "open", "getattr", "setattr", "delattr",
        "globals", "locals", "vars", "__import__", "breakpoint", "memoryview",
        "input", "help", "exit", "quit", "super"
    }

    FORBIDDEN_ATTRIBUTES: Set[str] = {
        "__subclasses__", "__bases__", "__mro__", "__code__", "__globals__",
        "__dict__", "__class__", "__closure__", "__builtins__", "__import__",
        "__qualname__", "__module__", "__wrapped__", "__reduce__", "__reduce_ex__",
        "gi_frame", "f_globals", "f_locals", "f_builtins", "f_code"
    }

    def __init__(self) -> None:
        self.has_execute_function = False

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node.name == "execute":
            self.has_execute_function = True
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            base_module = alias.name.split(".")[0]
            if base_module not in self.ALLOWED_MODULES:
                raise SecurityASTViolation(
                    f"Modul '{alias.name}' ist nicht auf der Sicherheits-Whitelist erlaubt. "
                    f"Erlaubt sind: {', '.join(sorted(self.ALLOWED_MODULES))}"
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if not node.module:
            raise SecurityASTViolation("Relative Imports sind aus Sicherheitsgründen verboten.")
        base_module = node.module.split(".")[0]
        if base_module not in self.ALLOWED_MODULES:
            raise SecurityASTViolation(
                f"Import aus Modul '{node.module}' ist nicht erlaubt. "
                f"Erlaubt sind: {', '.join(sorted(self.ALLOWED_MODULES))}"
            )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # Check direct call to forbidden builtins (e.g. eval(), open())
        if isinstance(node.func, ast.Name):
            if node.func.id in self.FORBIDDEN_BUILTINS:
                raise SecurityASTViolation(
                    f"Aufruf der verbotenen Builtin-Funktion '{node.func.id}' ist strikt untersagt."
                )
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        # Check forbidden dunder attributes (e.g. obj.__subclasses__, obj.__globals__)
        if node.attr in self.FORBIDDEN_ATTRIBUTES:
            raise SecurityASTViolation(
                f"Zugriff auf internes Introspektions-Attribut '{node.attr}' ist strikt untersagt."
            )
        self.generic_visit(node)

    def visit_Global(self, node: ast.Global) -> None:
        raise SecurityASTViolation("Die Verwendung von 'global' ist im zustandslosen Dynamic MCP verboten.")

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        raise SecurityASTViolation("Die Verwendung von 'nonlocal' ist im zustandslosen Dynamic MCP verboten.")

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        raise SecurityASTViolation("Asynchrone Funktionsdefinitionen sind im synchronen Sandbox-Vertrag verboten.")


def validate_python_code_ast(code: str) -> None:
    """
    Parses and verifies the given Python code against Zero-Trust AST security policies.
    Raises SecurityASTViolation if any forbidden patterns or modules are detected.
    """
    if not code or not code.strip():
        raise SecurityASTViolation("Leerer Quellcode kann nicht validiert werden.")

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise SecurityASTViolation(f"Syntaxfehler im generierten Code: {e.msg} (Zeile {e.lineno})")

    visitor = SecurityASTVisitor()
    visitor.visit(tree)

    if not visitor.has_execute_function:
        raise SecurityASTViolation(
            "Der generierte Code muss eine zustandslose Funktion 'def execute(inputs: dict) -> dict' definieren."
        )
