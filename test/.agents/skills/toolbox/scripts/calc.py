#!/usr/bin/env python3
# Safely evaluate a math expression passed as arguments.
# Only numbers and + - * / // % ** ( ) are allowed (parsed via ast, never eval'd).
import sys
import ast
import operator

_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow,
    ast.USub: operator.neg, ast.UAdd: operator.pos,
}


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    raise ValueError("only numbers and + - * / // % ** ( ) are allowed")


def main():
    expr = " ".join(sys.argv[1:]).strip()
    if not expr:
        print('usage: calc <expression>   e.g. calc "2 * (3 + 4)"')
        sys.exit(1)
    try:
        result = _eval(ast.parse(expr, mode="eval"))
        print(f"{expr} = {result}")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
