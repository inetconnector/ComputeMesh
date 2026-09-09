# SPDX-License-Identifier: Apache-2.0
"""Bounded mathematical Python evaluator.

Only a small expression/assignment language is accepted. Evaluation happens in
an expendable child process so the advertised timeout is real and a pathological
numeric operation cannot wedge the MCP server process.
"""

from __future__ import annotations

import ast
import math
import multiprocessing
import time
from typing import Any, Dict

MAX_SOURCE_CHARS = 2000
MAX_AST_NODES = 400
MAX_LITERAL_ITEMS = 1000
MAX_RANGE_ITEMS = 10_000
MAX_POWER_EXPONENT = 1000
MAX_CALL_ARGS = 32
MAX_RESULT_REPR_CHARS = 100_000

MATH_FUNCTIONS = {
    "acos", "acosh", "asin", "asinh", "atan", "atan2", "atanh", "ceil",
    "copysign", "cos", "cosh", "degrees", "dist", "erf", "erfc", "exp",
    "expm1", "fabs", "floor", "fmod", "frexp", "fsum", "gamma", "gcd",
    "hypot", "isclose", "isfinite", "isinf", "isnan", "isqrt", "lcm",
    "ldexp", "lgamma", "log", "log10", "log1p", "log2", "modf",
    "radians", "remainder", "sin", "sinh", "sqrt", "tan", "tanh", "trunc",
}
STATISTICS_FUNCTIONS = {
    "mean", "fmean", "geometric_mean", "harmonic_mean", "median", "median_low",
    "median_high", "median_grouped", "mode", "multimode", "pstdev", "pvariance",
    "stdev", "variance", "quantiles", "correlation", "covariance", "linear_regression",
}
DIRECT_FUNCTIONS = {
    "abs", "round", "min", "max", "sum", "pow", "len", "int", "float",
    "str", "list", "dict", "tuple", "set", "range", "sorted",
}


def _bounded_range(*args: int) -> range:
    value = range(*args)
    if len(value) > MAX_RANGE_ITEMS:
        raise ValueError(f"range darf höchstens {MAX_RANGE_ITEMS} Elemente erzeugen")
    return value


def _bounded_pow(base: Any, exponent: Any, modulo: Any = None) -> Any:
    if not isinstance(exponent, (int, float)) or abs(exponent) > MAX_POWER_EXPONENT:
        raise ValueError(f"Exponent darf betragsmäßig höchstens {MAX_POWER_EXPONENT} sein")
    return pow(base, exponent) if modulo is None else pow(base, exponent, modulo)


def _bounded_collection(factory):
    def wrapper(value=()):
        result = factory(value)
        if len(result) > MAX_RANGE_ITEMS:
            raise ValueError(f"Sammlung darf höchstens {MAX_RANGE_ITEMS} Elemente enthalten")
        return result
    return wrapper


SAFE_GLOBALS: Dict[str, Any] = {
    "math": math,
    "statistics": __import__("statistics"),
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sum": sum,
    "pow": _bounded_pow,
    "len": len,
    "int": int,
    "float": float,
    "str": str,
    "list": _bounded_collection(list),
    "dict": _bounded_collection(dict),
    "tuple": _bounded_collection(tuple),
    "set": _bounded_collection(set),
    "range": _bounded_range,
    "sorted": _bounded_collection(sorted),
    "pi": math.pi,
    "e": math.e,
}

ALLOWED_NODE_TYPES = (
    ast.Module, ast.Expression, ast.Expr, ast.Assign,
    ast.Name, ast.Load, ast.Store, ast.Constant,
    ast.List, ast.Tuple, ast.Set, ast.Dict, ast.Subscript, ast.Slice,
    ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp,
    ast.Call, ast.Attribute, ast.keyword,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.UAdd, ast.USub, ast.Not,
    ast.And, ast.Or,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
)


class SecurityValidator(ast.NodeVisitor):
    def __init__(self) -> None:
        self.is_safe = True
        self.error_msg = ""
        self.node_count = 0
        self.sequence_names: set[str] = set()

    def reject(self, message: str) -> None:
        if self.is_safe:
            self.is_safe = False
            self.error_msg = message

    def visit(self, node: ast.AST) -> None:
        if not self.is_safe:
            return
        self.node_count += 1
        if self.node_count > MAX_AST_NODES:
            self.reject(f"Ausdruck ist zu komplex (maximal {MAX_AST_NODES} AST-Knoten)")
            return
        if not isinstance(node, ALLOWED_NODE_TYPES):
            self.reject(f"Operation '{type(node).__name__}' ist nicht erlaubt")
            return
        super().visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            self.reject("Nur einfache Variablenzuweisungen sind erlaubt")
            return
        target = node.targets[0].id
        if target.startswith("_") or target in SAFE_GLOBALS:
            self.reject(f"Variable '{target}' darf nicht überschrieben werden")
            return
        if isinstance(node.value, (ast.List, ast.Tuple, ast.Set, ast.Dict)):
            self.sequence_names.add(target)
        elif isinstance(node.value, ast.Constant) and isinstance(node.value.value, (str, bytes)):
            self.sequence_names.add(target)
        elif isinstance(node.value, ast.Name) and node.value.id in self.sequence_names:
            self.sequence_names.add(target)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id.startswith("_"):
            self.reject(f"Privater Name '{node.id}' ist nicht erlaubt")
            return
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("_"):
            self.reject(f"Privates Attribut '{node.attr}' ist nicht erlaubt")
            return
        if not isinstance(node.value, ast.Name) or node.value.id not in {"math", "statistics"}:
            self.reject("Attributzugriff ist nur auf math/statistics erlaubt")
            return
        allowed = MATH_FUNCTIONS if node.value.id == "math" else STATISTICS_FUNCTIONS
        if node.attr not in allowed:
            self.reject(f"Funktion '{node.value.id}.{node.attr}' ist nicht freigegeben")
            return
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if len(node.args) + len(node.keywords) > MAX_CALL_ARGS:
            self.reject(f"Funktionsaufruf hat zu viele Argumente (maximal {MAX_CALL_ARGS})")
            return
        if any(keyword.arg is None for keyword in node.keywords):
            self.reject("**kwargs-Expansion ist nicht erlaubt")
            return
        if isinstance(node.func, ast.Name):
            if node.func.id not in DIRECT_FUNCTIONS:
                self.reject(f"Funktionsaufruf '{node.func.id}' ist nicht freigegeben")
                return
        elif isinstance(node.func, ast.Attribute):
            # Attribute validation is handled in visit_Attribute.
            pass
        else:
            self.reject("Dynamische Funktionsaufrufe sind nicht erlaubt")
            return
        self.generic_visit(node)

    def visit_List(self, node: ast.List) -> None:
        if len(node.elts) > MAX_LITERAL_ITEMS:
            self.reject(f"Listenliteral darf höchstens {MAX_LITERAL_ITEMS} Elemente enthalten")
            return
        self.generic_visit(node)

    def visit_Tuple(self, node: ast.Tuple) -> None:
        if len(node.elts) > MAX_LITERAL_ITEMS:
            self.reject(f"Tupelliteral darf höchstens {MAX_LITERAL_ITEMS} Elemente enthalten")
            return
        self.generic_visit(node)

    def visit_Set(self, node: ast.Set) -> None:
        if len(node.elts) > MAX_LITERAL_ITEMS:
            self.reject(f"Set-Literal darf höchstens {MAX_LITERAL_ITEMS} Elemente enthalten")
            return
        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> None:
        if len(node.keys) > MAX_LITERAL_ITEMS:
            self.reject(f"Dict-Literal darf höchstens {MAX_LITERAL_ITEMS} Elemente enthalten")
            return
        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        if isinstance(node.op, ast.Pow):
            if not isinstance(node.right, ast.Constant) or not isinstance(node.right.value, (int, float)):
                self.reject("Exponent bei ** muss eine direkte numerische Konstante sein")
                return
            if abs(node.right.value) > MAX_POWER_EXPONENT:
                self.reject(f"Exponent darf betragsmäßig höchstens {MAX_POWER_EXPONENT} sein")
                return
        if isinstance(node.op, ast.Mult):
            sequence_operand = False
            for operand in (node.left, node.right):
                if isinstance(operand, (ast.List, ast.Tuple, ast.Set, ast.Dict)):
                    sequence_operand = True
                elif isinstance(operand, ast.Constant) and isinstance(operand.value, (str, bytes)):
                    sequence_operand = True
                elif isinstance(operand, ast.Name) and operand.id in self.sequence_names:
                    sequence_operand = True
            if sequence_operand:
                other = node.right if self._looks_sequence(node.left) else node.left
                if not isinstance(other, ast.Constant) or not isinstance(other.value, int) or abs(other.value) > MAX_RANGE_ITEMS:
                    self.reject(f"Sequenzmultiplikation ist auf Faktor {MAX_RANGE_ITEMS} begrenzt")
                    return
        self.generic_visit(node)

    def _looks_sequence(self, node: ast.AST) -> bool:
        return (
            isinstance(node, (ast.List, ast.Tuple, ast.Set, ast.Dict))
            or isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes))
            or isinstance(node, ast.Name) and node.id in self.sequence_names
        )


def _validate_source(raw_code: str) -> tuple[ast.Module | None, str | None]:
    try:
        parsed = ast.parse(raw_code, mode="exec")
    except SyntaxError as exc:
        return None, f"Syntaxfehler im Ausdruck: {exc.msg} (Zeile {exc.lineno})"
    validator = SecurityValidator()
    validator.visit(parsed)
    if not validator.is_safe:
        return None, f"Sicherheitsrichtlinie verweigert die Ausführung: {validator.error_msg}"
    return parsed, None


def _serialize_result(value: Any, depth: int = 0) -> Any:
    if depth > 8:
        return "[verschachteltes Ergebnis gekürzt]"
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_serialize_result(item, depth + 1) for item in value[:MAX_RANGE_ITEMS]]
    if isinstance(value, set):
        return [_serialize_result(item, depth + 1) for item in list(value)[:MAX_RANGE_ITEMS]]
    if isinstance(value, dict):
        return {
            str(key): _serialize_result(item, depth + 1)
            for key, item in list(value.items())[:MAX_RANGE_ITEMS]
        }
    text = repr(value)
    return text[:MAX_RESULT_REPR_CHARS]


def _worker(raw_code: str, connection: Any) -> None:
    try:
        parsed, error = _validate_source(raw_code)
        if error or parsed is None:
            connection.send({"ok": False, "error": error or "Validierung fehlgeschlagen"})
            return
        local_scope: Dict[str, Any] = {}
        if len(parsed.body) == 1 and isinstance(parsed.body[0], ast.Expr):
            compiled = compile(ast.Expression(body=parsed.body[0].value), "<calculator>", "eval")
            value = eval(compiled, {"__builtins__": {}, **SAFE_GLOBALS}, local_scope)
        else:
            compiled = compile(parsed, "<calculator>", "exec")
            exec(compiled, {"__builtins__": {}, **SAFE_GLOBALS}, local_scope)
            value = local_scope.get("result", local_scope)
        connection.send({"ok": True, "result": _serialize_result(value)})
    except BaseException as exc:
        try:
            connection.send({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        except Exception:
            pass
    finally:
        try:
            connection.close()
        except Exception:
            pass


def run_python_calc(
    expression: str = "",
    code: str = "",
    formula: str = "",
    query: str = "",
    timeout: float = 2.0,
) -> Dict[str, Any]:
    """Evaluate bounded mathematical expressions with a real process timeout."""
    raw_code = str(expression or code or formula or query or "").strip()
    if not raw_code:
        return {"error": "Berechnungsausdruck darf nicht leer sein (z. B. '2 + 2')."}
    if len(raw_code) > MAX_SOURCE_CHARS:
        return {"error": f"Ausdruck ist zu lang (maximal {MAX_SOURCE_CHARS} Zeichen)."}
    try:
        timeout_value = max(0.1, min(10.0, float(timeout)))
    except (TypeError, ValueError):
        return {"error": "timeout muss numerisch sein."}

    _parsed, validation_error = _validate_source(raw_code)
    if validation_error:
        return {"error": validation_error, "expression": raw_code}

    started = time.perf_counter()
    context = multiprocessing.get_context("spawn")
    parent_connection, child_connection = context.Pipe(duplex=False)
    process = context.Process(target=_worker, args=(raw_code, child_connection), daemon=True)
    try:
        process.start()
        child_connection.close()
        process.join(timeout_value)
        if process.is_alive():
            process.terminate()
            process.join(1.0)
            return {
                "error": f"Berechnung nach {timeout_value:.2f} Sekunden abgebrochen (Zeitlimit).",
                "expression": raw_code,
            }
        if not parent_connection.poll(0.5):
            return {"error": "Berechnungsprozess lieferte kein Ergebnis.", "expression": raw_code}
        payload = parent_connection.recv()
    except Exception as exc:
        if process.is_alive():
            process.terminate()
            process.join(1.0)
        return {"error": f"Berechnungsprozess fehlgeschlagen: {type(exc).__name__}: {exc}", "expression": raw_code}
    finally:
        try:
            parent_connection.close()
        except Exception:
            pass

    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    if not isinstance(payload, dict) or not payload.get("ok"):
        message = payload.get("error") if isinstance(payload, dict) else "Unbekannter Worker-Fehler"
        return {"error": f"Fehler bei Berechnung: {message}", "expression": raw_code}
    return {
        "result": payload.get("result"),
        "expression": raw_code,
        "duration_ms": duration_ms,
        "status": "success",
    }


calculate_math = run_python_calc
