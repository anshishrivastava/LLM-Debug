#!/usr/bin/env python3
"""CWE-inspired Semantic Altering Mutations (SAMs) for bug injection.

Implements 8 CWE-inspired injectors for Python and Java code:
    CWE-480  IncorrectOperator         – swap operators (+/-, */, and/or, ==/!=)
    CWE-483  IncorrectBlockDelimitation – un-indent / misplace brace
    CWE-484  OmittedBreak              – remove break in switch (Java only)
    CWE-563  UnusedAssignment          – overwrite a needed value
    CWE-783  OperatorPrecedence        – remove/add parentheses
    CWE-835  LoopUnreachableExit       – reverse loop update direction
    CWE-1025 WrongComparison           – swap a comparison operand
    CWE-628  WrongArguments            – swap adjacent function call arguments

Each injector returns (mutated_code, bug_line) or (None, None).
"""

import os
import sys
import json
import ast
import re
import copy
import random
import textwrap

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_evaluation_experiment.config import (
    JAVA_DATASET, PYTHON_DATASET, BUGGY_DATASETS_DIR,
    CWE_BUG_TYPES, CWE_LANGUAGE_SUPPORT, DATASET_CATEGORIES, LANGUAGES
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_parse_python(code: str):
    """Return an AST tree or None."""
    try:
        return ast.parse(code)
    except SyntaxError:
        return None


def _safe_unparse(tree) -> str | None:
    """Unparse an AST tree; return None on failure."""
    try:
        return ast.unparse(tree)
    except Exception:
        return None


def _validates_python(code: str) -> bool:
    """Return True if *code* is valid Python."""
    try:
        ast.parse(code)
        return True
    except SyntaxError:
        return False


def _line_in_string_or_comment_java(line: str) -> bool:
    """Heuristic: return True if the substantive content of a Java line is
    inside a comment or is a string literal."""
    stripped = line.strip()
    if stripped.startswith("//") or stripped.startswith("/*") or stripped.startswith("*"):
        return True
    # Very rough: if the line is dominated by a string literal, skip it
    if stripped.startswith('"') and stripped.endswith('";'):
        return True
    return False


def _line_in_string_or_comment_python(line: str) -> bool:
    """Heuristic: skip lines that are comments or pure strings."""
    stripped = line.strip()
    if stripped.startswith("#"):
        return True
    if (stripped.startswith('"""') or stripped.startswith("'''")
            or stripped.startswith('"') or stripped.startswith("'")):
        return True
    return False


# ======================================================================
# CWE-480: Incorrect Operator
# ======================================================================

def inject_cwe480_python(code: str) -> tuple:
    """Swap one operator using the AST (Python)."""
    tree = _safe_parse_python(code)
    if tree is None:
        return None, None

    class _OpSwapper(ast.NodeTransformer):
        BINOP_SWAPS = {
            ast.Add: ast.Sub, ast.Sub: ast.Add,
            ast.Mult: ast.Div, ast.Div: ast.Mult,
        }
        BOOLOP_SWAPS = {ast.And: ast.Or, ast.Or: ast.And}
        CMPOP_SWAPS = {ast.Eq: ast.NotEq, ast.NotEq: ast.Eq}

        def __init__(self):
            self.done = False
            self.bug_line = None

        def visit_BinOp(self, node):
            self.generic_visit(node)
            if not self.done and type(node.op) in self.BINOP_SWAPS:
                node.op = self.BINOP_SWAPS[type(node.op)]()
                self.done = True
                self.bug_line = node.lineno
            return node

        def visit_BoolOp(self, node):
            self.generic_visit(node)
            if not self.done and type(node.op) in self.BOOLOP_SWAPS:
                node.op = self.BOOLOP_SWAPS[type(node.op)]()
                self.done = True
                self.bug_line = node.lineno
            return node

        def visit_Compare(self, node):
            self.generic_visit(node)
            if not self.done:
                for idx, op in enumerate(node.ops):
                    if type(op) in self.CMPOP_SWAPS:
                        node.ops[idx] = self.CMPOP_SWAPS[type(op)]()
                        self.done = True
                        self.bug_line = node.lineno
                        break
            return node

    swapper = _OpSwapper()
    mutated = swapper.visit(tree)
    if not swapper.done:
        return None, None
    new_code = _safe_unparse(mutated)
    if new_code is None or not _validates_python(new_code):
        return None, None
    return new_code, swapper.bug_line


def inject_cwe480_java(code: str) -> tuple:
    """Swap one operator using regex (Java)."""
    lines = code.split("\n")
    swaps = [
        (r'(?<!\+)\+(?!\+|=)', '-'),   # + but not ++ or +=
        (r'(?<!-)-(?!-|=|>)', '+'),     # - but not --, -=, ->
        (r'(?<!\*)\*(?!\*|=)', '/'),    # * but not ** or *=
        (r'(?<!/)/(?!/|\*|=)', '*'),    # / but not //, /*, /=
        (r'&&', '||'),
        (r'\|\|', '&&'),
        (r'(?<!=|!)===?(?!=)', '!='),   # == but not === or !==
        (r'!=', '=='),
    ]

    for i, line in enumerate(lines):
        if _line_in_string_or_comment_java(line):
            continue
        for pattern, replacement in swaps:
            m = re.search(pattern, line)
            if m:
                new_line = line[:m.start()] + replacement + line[m.end():]
                if new_line != line:
                    lines[i] = new_line
                    return "\n".join(lines), i + 1

    return None, None


# ======================================================================
# CWE-483: Incorrect Block Delimitation
# ======================================================================

def inject_cwe483_python(code: str) -> tuple:
    """Un-indent the last statement of an if/for/while block (Python).

    Uses the AST to find a compound statement whose body has >= 2
    statements, then un-indents the last statement so it falls
    outside the block.
    """
    tree = _safe_parse_python(code)
    if tree is None:
        return None, None

    lines = code.split("\n")

    # Walk AST looking for compound statements with body >= 2
    compound_types = (ast.If, ast.For, ast.While)
    targets = []
    for node in ast.walk(tree):
        if isinstance(node, compound_types) and hasattr(node, "body") and len(node.body) >= 2:
            last_stmt = node.body[-1]
            targets.append((node, last_stmt))

    if not targets:
        return None, None

    # Pick the first suitable target
    for _parent, last_stmt in targets:
        start = last_stmt.lineno - 1  # 0-indexed
        end = getattr(last_stmt, "end_lineno", last_stmt.lineno) - 1

        if start >= len(lines) or end >= len(lines):
            continue

        # Detect the indentation of the last statement
        original_line = lines[start]
        stripped = original_line.lstrip()
        if not stripped:
            continue
        indent = len(original_line) - len(stripped)

        # Determine the parent block indentation: one level less
        # We assume 4-space or the detected indent of the parent header
        parent_line = lines[_parent.lineno - 1]
        parent_indent = len(parent_line) - len(parent_line.lstrip())

        if indent <= parent_indent:
            continue  # already at or below parent indent — skip

        # Un-indent lines [start..end] to parent_indent level
        new_lines = list(lines)
        for li in range(start, end + 1):
            old = new_lines[li]
            old_stripped = old.lstrip()
            old_indent = len(old) - len(old_stripped)
            # Shift left by (indent - parent_indent)
            shift = indent - parent_indent
            new_indent = max(old_indent - shift, 0)
            new_lines[li] = " " * new_indent + old_stripped

        new_code = "\n".join(new_lines)
        if _validates_python(new_code) and new_code != code:
            return new_code, start + 1  # 1-indexed
        # If validation fails, the un-indent broke syntax — try next target

    return None, None


def inject_cwe483_java(code: str) -> tuple:
    """Move a closing brace up by one statement (Java).

    Finds an if/for/while block and moves its `}` one statement earlier,
    effectively removing the last statement from the block.
    """
    lines = code.split("\n")

    # Find closing braces that close if/for/while blocks
    # Strategy: find `}` lines; check if the opening block was if/for/while.
    # Simple heuristic: look for `}` and see if moving it up creates valid-looking code.
    brace_stack = []
    block_info = []  # (open_line_idx, close_line_idx, keyword)

    kw_pattern = re.compile(r'\b(if|for|while)\s*\(')

    for i, line in enumerate(lines):
        stripped = line.strip()
        # Count opening braces
        for ch in stripped:
            if ch == '{':
                # Check if this line (or recent lines) has a keyword
                context = " ".join(l.strip() for l in lines[max(0, i - 2):i + 1])
                m = kw_pattern.search(context)
                kw = m.group(1) if m else None
                brace_stack.append((i, kw))
            elif ch == '}':
                if brace_stack:
                    open_idx, kw = brace_stack.pop()
                    if kw:
                        block_info.append((open_idx, i, kw))

    # Try to move the closing brace up by one statement
    for open_idx, close_idx, kw in block_info:
        # Need at least 2 statements between open and close
        body_lines = lines[open_idx + 1:close_idx]
        # Filter to non-empty, non-comment lines
        stmt_indices = []
        for li in range(open_idx + 1, close_idx):
            s = lines[li].strip()
            if s and not s.startswith("//") and not s.startswith("/*") and s != "{" and s != "}":
                stmt_indices.append(li)

        if len(stmt_indices) < 2:
            continue

        # Remove the closing brace at close_idx, insert it before the last statement
        last_stmt_idx = stmt_indices[-1]
        indent = " " * (len(lines[close_idx]) - len(lines[close_idx].lstrip()))

        new_lines = list(lines)
        # Remove old closing brace
        old_brace_line = new_lines.pop(close_idx)
        # Insert closing brace before the last statement
        # Adjust index if close_idx > last_stmt_idx
        insert_at = last_stmt_idx if close_idx > last_stmt_idx else last_stmt_idx - 1
        new_lines.insert(insert_at, indent + "}")

        new_code = "\n".join(new_lines)
        if new_code != code:
            return new_code, insert_at + 1  # 1-indexed

    return None, None


# ======================================================================
# CWE-484: Omitted Break (Java only)
# ======================================================================

def inject_cwe484_java(code: str) -> tuple:
    """Remove one `break;` from a switch-case to create fall-through."""
    lines = code.split("\n")
    break_pattern = re.compile(r'^\s*break\s*;')

    # Check that there is at least a switch statement
    has_switch = any("switch" in l for l in lines)
    if not has_switch:
        return None, None

    # Collect break lines inside switch blocks
    in_switch = False
    brace_depth = 0
    break_indices = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if "switch" in stripped and "(" in stripped:
            in_switch = True
            brace_depth = 0
        if in_switch:
            brace_depth += stripped.count("{") - stripped.count("}")
            if brace_depth <= 0 and i > 0 and in_switch and stripped == "}":
                in_switch = False
                continue
            if break_pattern.match(stripped):
                break_indices.append(i)

    if not break_indices:
        return None, None

    # Remove the first break found
    target = break_indices[0]
    removed_line_no = target + 1  # 1-indexed
    new_lines = lines[:target] + lines[target + 1:]
    return "\n".join(new_lines), removed_line_no


# ======================================================================
# CWE-563: Unused Assignment (dead store overwrite)
# ======================================================================

def inject_cwe563_python(code: str) -> tuple:
    """Insert a dead-store assignment between a variable's def and use (Python).

    Finds a variable that is assigned and later read; inserts ``var = 0``
    between the two so the correct value is overwritten.
    """
    tree = _safe_parse_python(code)
    if tree is None:
        return None, None

    lines = code.split("\n")

    # Collect assignments: (var_name, line_no 0-idx)
    assignments = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments.append((target.id, node.lineno - 1))

    if not assignments:
        return None, None

    # For each assignment, see if the variable is used later
    for var_name, assign_idx in assignments:
        # Skip common loop vars and trivial names
        if var_name in ("_", "__"):
            continue
        # Search for a later use (read) of var_name
        use_idx = None
        for j in range(assign_idx + 1, len(lines)):
            ln = lines[j]
            # Check that it's a read (appears in the line but is not
            # the sole left-hand side of another assignment)
            if re.search(r'\b' + re.escape(var_name) + r'\b', ln):
                stripped = ln.strip()
                # Skip if this line is just another assignment to the same var
                if stripped.startswith(var_name + " =") or stripped.startswith(var_name + "="):
                    continue
                use_idx = j
                break

        if use_idx is None or use_idx <= assign_idx + 1:
            continue  # need room to insert between

        # Determine indentation at the assignment line
        orig = lines[assign_idx]
        indent = " " * (len(orig) - len(orig.lstrip()))

        # Insert overwriting assignment right after the original
        insert_idx = assign_idx + 1
        dead_store = f"{indent}{var_name} = 0"

        new_lines = lines[:insert_idx] + [dead_store] + lines[insert_idx:]
        new_code = "\n".join(new_lines)
        if _validates_python(new_code) and new_code != code:
            return new_code, insert_idx + 1  # 1-indexed

    return None, None


def inject_cwe563_java(code: str) -> tuple:
    """Insert a dead-store assignment between def and use (Java)."""
    lines = code.split("\n")

    # Find assignments of the form: <type> var = ...; or var = ...;
    assign_pattern = re.compile(
        r'^(\s*)(?:(?:\w+\s+)+)?(\w+)\s*=\s*.+;'
    )

    for i, line in enumerate(lines):
        if _line_in_string_or_comment_java(line):
            continue
        m = assign_pattern.match(line)
        if not m:
            continue

        indent = m.group(1)
        var_name = m.group(2)
        if var_name in ("int", "long", "float", "double", "String",
                        "boolean", "char", "byte", "short", "var",
                        "final", "static", "public", "private", "protected"):
            continue

        # Find a later use
        use_idx = None
        for j in range(i + 1, len(lines)):
            ln = lines[j]
            if re.search(r'\b' + re.escape(var_name) + r'\b', ln):
                stripped = ln.strip()
                # Skip if just another assignment to the same var
                if re.match(r'^' + re.escape(var_name) + r'\s*=', stripped):
                    continue
                use_idx = j
                break

        if use_idx is None or use_idx <= i + 1:
            continue

        insert_idx = i + 1
        dead_store = f"{indent}{var_name} = null;"

        new_lines = lines[:insert_idx] + [dead_store] + lines[insert_idx:]
        new_code = "\n".join(new_lines)
        if new_code != code:
            return new_code, insert_idx + 1  # 1-indexed

    return None, None


# ======================================================================
# CWE-783: Operator Precedence
# ======================================================================

def inject_cwe783_python(code: str) -> tuple:
    """Remove explicit parentheses to change operator precedence (Python).

    Looks for patterns like ``(a + b) * c`` and removes parens so it becomes
    ``a + b * c``.  Falls back to adding parentheses around a lower-precedence
    sub-expression: ``a and b or c`` -> ``a and (b or c)``.
    """
    tree = _safe_parse_python(code)
    if tree is None:
        return None, None

    lines = code.split("\n")

    # Strategy 1: find parenthesized sub-expressions in source using regex
    # Match pattern: (expr OP expr) OP expr  where inner parens change meaning
    paren_pattern = re.compile(r'\(([^()]+?)\)\s*([*/])')
    for i, line in enumerate(lines):
        if _line_in_string_or_comment_python(line):
            continue
        m = paren_pattern.search(line)
        if m:
            inner = m.group(1).strip()
            # Only remove if inner has a lower-precedence op
            if any(op in inner for op in ['+', '-']):
                new_line = line[:m.start()] + inner + " " + m.group(2) + line[m.end():]
                new_lines = list(lines)
                new_lines[i] = new_line
                new_code = "\n".join(new_lines)
                if _validates_python(new_code) and new_code != code:
                    return new_code, i + 1

    # Strategy 2: add parentheses to change precedence of boolean expressions
    # e.g.  ``a and b or c`` -> ``a and (b or c)``
    bool_pattern = re.compile(r'\band\b\s+(.+?)\s+\bor\b\s+(.+)')
    for i, line in enumerate(lines):
        if _line_in_string_or_comment_python(line):
            continue
        m = bool_pattern.search(line)
        if m:
            # Wrap "b or c" in parens
            start = m.start(1)
            new_line = line[:start] + "(" + m.group(1) + " or " + m.group(2) + ")"
            # Remove the original "and b or c" portion and replace
            prefix = line[:m.start()]
            new_line = prefix + "and (" + m.group(1) + " or " + m.group(2) + ")"
            new_lines = list(lines)
            new_lines[i] = new_line
            new_code = "\n".join(new_lines)
            if _validates_python(new_code) and new_code != code:
                return new_code, i + 1

    return None, None


def inject_cwe783_java(code: str) -> tuple:
    """Remove explicit parentheses to change operator precedence (Java)."""
    lines = code.split("\n")

    # Pattern: (expr OP expr) OP expr  where inner has lower-precedence ops
    paren_pattern = re.compile(r'\(([^()]+?)\)\s*([*/])')
    for i, line in enumerate(lines):
        if _line_in_string_or_comment_java(line):
            continue
        m = paren_pattern.search(line)
        if m:
            inner = m.group(1).strip()
            if any(op in inner for op in ['+', '-']):
                new_line = line[:m.start()] + inner + " " + m.group(2) + line[m.end():]
                new_lines = list(lines)
                new_lines[i] = new_line
                new_code = "\n".join(new_lines)
                if new_code != code:
                    return new_code, i + 1

    # Strategy 2: wrap lower-precedence side of && / ||
    # e.g. ``a && b || c`` -> ``a && (b || c)``
    logic_pattern = re.compile(r'(&&)\s*(.+?)\s*(\|\|)\s*(.+?)(?=[;)\]])')
    for i, line in enumerate(lines):
        if _line_in_string_or_comment_java(line):
            continue
        m = logic_pattern.search(line)
        if m:
            # Wrap "b || c" in parens
            replacement = m.group(1) + " (" + m.group(2) + " " + m.group(3) + " " + m.group(4) + ")"
            new_line = line[:m.start()] + replacement + line[m.end():]
            new_lines = list(lines)
            new_lines[i] = new_line
            new_code = "\n".join(new_lines)
            if new_code != code:
                return new_code, i + 1

    return None, None


# ======================================================================
# CWE-835: Loop with Unreachable Exit Condition
# ======================================================================

_PY_INC_PATTERN = re.compile(
    r'(\b\w+)\s*(\+=|-=)\s*(\d+)'
)
_JAVA_INC_PATTERN = re.compile(
    r'(\b\w+)\s*(\+\+|--|(\+=|-=)\s*(\d+))'
)


def inject_cwe835_python(code: str) -> tuple:
    """Reverse the direction of a loop increment/decrement (Python)."""
    lines = code.split("\n")

    # Find lines inside a while/for block that contain += or -=
    for i, line in enumerate(lines):
        if _line_in_string_or_comment_python(line):
            continue
        m = _PY_INC_PATTERN.search(line)
        if m:
            var = m.group(1)
            op = m.group(2)
            val = m.group(3)
            # Check that this is inside a loop (any preceding for/while with
            # indentation less than this line)
            this_indent = len(line) - len(line.lstrip())
            in_loop = False
            for k in range(i - 1, -1, -1):
                prev = lines[k]
                prev_stripped = prev.strip()
                prev_indent = len(prev) - len(prev.lstrip())
                if prev_indent < this_indent and (prev_stripped.startswith("while ") or
                                                   prev_stripped.startswith("for ")):
                    in_loop = True
                    break
                if prev_indent < this_indent:
                    break

            if not in_loop:
                continue

            # Swap direction
            new_op = "-=" if op == "+=" else "+="
            new_line = line[:m.start(2)] + new_op + line[m.end(2):]
            new_lines = list(lines)
            new_lines[i] = new_line
            new_code = "\n".join(new_lines)
            if _validates_python(new_code) and new_code != code:
                return new_code, i + 1

    return None, None


def inject_cwe835_java(code: str) -> tuple:
    """Reverse the direction of a loop increment/decrement (Java)."""
    lines = code.split("\n")

    for i, line in enumerate(lines):
        if _line_in_string_or_comment_java(line):
            continue

        # Check for i++ / i-- in loop headers or bodies
        stripped = line.strip()

        # ++ <-> --
        pp_pattern = re.compile(r'(\b\w+)\s*\+\+')
        mm_pattern = re.compile(r'(\b\w+)\s*--')

        m_pp = pp_pattern.search(line)
        m_mm = mm_pattern.search(line)

        if m_pp:
            new_line = line[:m_pp.start()] + m_pp.group(1) + "--" + line[m_pp.end():]
            new_lines = list(lines)
            new_lines[i] = new_line
            return "\n".join(new_lines), i + 1

        if m_mm:
            new_line = line[:m_mm.start()] + m_mm.group(1) + "++" + line[m_mm.end():]
            new_lines = list(lines)
            new_lines[i] = new_line
            return "\n".join(new_lines), i + 1

        # += <-> -=
        pm_pattern = re.compile(r'(\b\w+)\s*(\+=|-=)\s*(\d+)')
        m_pm = pm_pattern.search(line)
        if m_pm:
            op = m_pm.group(2)
            new_op = "-=" if op == "+=" else "+="
            new_line = line[:m_pm.start(2)] + new_op + line[m_pm.end(2):]
            new_lines = list(lines)
            new_lines[i] = new_line
            return "\n".join(new_lines), i + 1

    return None, None


# ======================================================================
# CWE-1025: Comparison Using Wrong Factors
# ======================================================================

def inject_cwe1025_python(code: str) -> tuple:
    """Replace one operand of a comparison with a different in-scope variable (Python)."""
    tree = _safe_parse_python(code)
    if tree is None:
        return None, None

    # Collect all Name nodes (variables) in the module
    all_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            all_names.add(node.id)

    # Remove built-ins / dunder names
    all_names -= {"True", "False", "None", "__name__", "__main__"}
    if len(all_names) < 2:
        return None, None

    class _CmpSwapper(ast.NodeTransformer):
        def __init__(self):
            self.done = False
            self.bug_line = None

        def visit_Compare(self, node):
            self.generic_visit(node)
            if self.done:
                return node

            # Try replacing the left operand
            if isinstance(node.left, ast.Name):
                candidates = all_names - {node.left.id}
                if candidates:
                    replacement = sorted(candidates)[0]  # deterministic
                    node.left = ast.Name(id=replacement, ctx=ast.Load())
                    self.done = True
                    self.bug_line = node.lineno
                    return node

            # Try replacing a comparator
            for idx, comp in enumerate(node.comparators):
                if isinstance(comp, ast.Name):
                    candidates = all_names - {comp.id}
                    if candidates:
                        replacement = sorted(candidates)[0]
                        node.comparators[idx] = ast.Name(id=replacement, ctx=ast.Load())
                        self.done = True
                        self.bug_line = node.lineno
                        return node

            return node

    swapper = _CmpSwapper()
    mutated = swapper.visit(tree)
    if not swapper.done:
        return None, None

    new_code = _safe_unparse(mutated)
    if new_code is None or not _validates_python(new_code):
        return None, None
    return new_code, swapper.bug_line


def inject_cwe1025_java(code: str) -> tuple:
    """Replace one operand of a comparison with a different in-scope variable (Java)."""
    lines = code.split("\n")

    # Collect variable names: match declarations and assignments
    var_pattern = re.compile(r'\b(?:int|long|float|double|String|boolean|char|byte|short|var)\s+(\w+)')
    all_vars: set[str] = set()
    for line in lines:
        for m in var_pattern.finditer(line):
            all_vars.add(m.group(1))

    if len(all_vars) < 2:
        return None, None

    # Find comparison lines
    cmp_pattern = re.compile(r'(\b\w+)\s*(==|!=|<=|>=|<|>)\s*(\b\w+)')
    for i, line in enumerate(lines):
        if _line_in_string_or_comment_java(line):
            continue
        m = cmp_pattern.search(line)
        if m:
            left, op, right = m.group(1), m.group(2), m.group(3)
            # Try to replace left with a different var
            candidates = all_vars - {left, right}
            if not candidates:
                continue
            replacement = sorted(candidates)[0]
            new_line = line[:m.start(1)] + replacement + line[m.end(1):]
            new_lines = list(lines)
            new_lines[i] = new_line
            new_code = "\n".join(new_lines)
            if new_code != code:
                return new_code, i + 1

    return None, None


# ======================================================================
# CWE-628: Function Call with Wrongly Ordered Arguments
# ======================================================================

def inject_cwe628_python(code: str) -> tuple:
    """Swap two adjacent arguments in a function call (Python)."""
    tree = _safe_parse_python(code)
    if tree is None:
        return None, None

    class _ArgSwapper(ast.NodeTransformer):
        def __init__(self):
            self.done = False
            self.bug_line = None

        def visit_Call(self, node):
            self.generic_visit(node)
            if self.done:
                return node
            # Need at least 2 positional args
            if len(node.args) >= 2:
                # Swap first two args
                node.args[0], node.args[1] = node.args[1], node.args[0]
                self.done = True
                self.bug_line = node.lineno
            return node

    swapper = _ArgSwapper()
    mutated = swapper.visit(tree)
    if not swapper.done:
        return None, None

    new_code = _safe_unparse(mutated)
    if new_code is None or not _validates_python(new_code):
        return None, None
    # Check that the swap actually changed the code (args could be identical)
    if new_code == code:
        return None, None
    return new_code, swapper.bug_line


def inject_cwe628_java(code: str) -> tuple:
    """Swap two adjacent arguments in a function call (Java)."""
    lines = code.split("\n")

    # Match function calls: name(arg1, arg2, ...)
    # Simplified: match calls with at least two args on a single line.
    call_pattern = re.compile(
        r'(\b\w+)\s*\('
        r'([^,()]+)'    # first arg
        r',\s*'
        r'([^,()]+)'    # second arg
        r'((?:,[^()]*)?)\)'  # rest of args + closing paren
    )

    for i, line in enumerate(lines):
        if _line_in_string_or_comment_java(line):
            continue
        m = call_pattern.search(line)
        if m:
            func = m.group(1)
            arg1 = m.group(2).strip()
            arg2 = m.group(3).strip()
            rest = m.group(4)

            # Skip if args are identical
            if arg1 == arg2:
                continue
            # Skip common non-function keywords
            if func in ("if", "for", "while", "switch", "catch", "return"):
                continue

            swapped = f"{func}({arg2}, {arg1}{rest})"
            new_line = line[:m.start()] + swapped + line[m.end():]
            new_lines = list(lines)
            new_lines[i] = new_line
            new_code = "\n".join(new_lines)
            if new_code != code:
                return new_code, i + 1

    return None, None


# ======================================================================
# CWE_INJECTORS registry
# ======================================================================

CWE_INJECTORS = {
    "python": {
        "CWE-480_IncorrectOperator": inject_cwe480_python,
        "CWE-483_IncorrectBlockDelimitation": inject_cwe483_python,
        # CWE-484 is Java only — not registered for Python
        "CWE-563_UnusedAssignment": inject_cwe563_python,
        "CWE-783_OperatorPrecedence": inject_cwe783_python,
        "CWE-835_LoopUnreachableExit": inject_cwe835_python,
        "CWE-1025_WrongComparison": inject_cwe1025_python,
        "CWE-628_WrongArguments": inject_cwe628_python,
    },
    "java": {
        "CWE-480_IncorrectOperator": inject_cwe480_java,
        "CWE-483_IncorrectBlockDelimitation": inject_cwe483_java,
        "CWE-484_OmittedBreak": inject_cwe484_java,
        "CWE-563_UnusedAssignment": inject_cwe563_java,
        "CWE-783_OperatorPrecedence": inject_cwe783_java,
        "CWE-835_LoopUnreachableExit": inject_cwe835_java,
        "CWE-1025_WrongComparison": inject_cwe1025_java,
        "CWE-628_WrongArguments": inject_cwe628_java,
    },
}


# ======================================================================
# Dataset processing (mirrors process_dataset from bug_injector.py)
# ======================================================================

def process_cwe_dataset(
    input_dir: str,
    output_dir: str,
    language: str,
    bug_type: str,
) -> dict:
    """Process a dataset directory and inject CWE-inspired bugs.

    Parameters
    ----------
    input_dir : str
        Path to the directory containing clean ``.json`` program files.
    output_dir : str
        Where to write the mutated files.
    language : str
        ``"python"`` or ``"java"``.
    bug_type : str
        One of the keys in ``CWE_BUG_TYPES``.

    Returns
    -------
    dict
        ``{'total': N, 'success': N, 'failed': N, 'skipped': N}``
    """
    os.makedirs(output_dir, exist_ok=True)

    if language not in CWE_INJECTORS:
        return {"total": 0, "success": 0, "failed": 0, "skipped": 0}
    if bug_type not in CWE_INJECTORS[language]:
        return {"total": 0, "success": 0, "failed": 0, "skipped": 0}

    injector = CWE_INJECTORS[language][bug_type]
    stats = {"total": 0, "success": 0, "failed": 0, "skipped": 0}

    if not os.path.isdir(input_dir):
        return stats

    for filename in sorted(os.listdir(input_dir)):
        if not filename.endswith(".json"):
            continue

        stats["total"] += 1
        filepath = os.path.join(input_dir, filename)

        try:
            with open(filepath, "r") as f:
                data = json.load(f)
        except Exception:
            stats["failed"] += 1
            continue

        code = data.get("output", "")
        instruction = data.get("instruction", "")

        if not code:
            stats["skipped"] += 1
            continue

        # --- Attempt injection ------------------------------------------------
        try:
            buggy_code, bug_line = injector(code)
        except Exception:
            stats["failed"] += 1
            continue

        if buggy_code is None or bug_line is None:
            stats["skipped"] += 1
            continue

        # --- Compute metadata -------------------------------------------------
        total_lines = len(buggy_code.split("\n"))
        line_percent = round((bug_line / total_lines) * 100) if total_lines > 0 else 0

        # Bug line range: for single-line mutations start == end
        bug_line_range = (bug_line, bug_line)

        output_data = {
            "instruction": instruction,
            "buggy_code": buggy_code,
            "original_code": code,
            "line_no": bug_line,
            "line_no_percent": f"{line_percent}%",
            "bug_type": bug_type,
            "language": language,
            "source_file": filename,
            "bug_line_range": list(bug_line_range),
            "metadata": {
                **data.get("metadata", {}),
                "cwe_category": bug_type.split("_")[0],  # e.g. "CWE-480"
            },
        }

        output_path = os.path.join(output_dir, filename)
        try:
            with open(output_path, "w") as f:
                json.dump(output_data, f, indent=2)
        except Exception:
            stats["failed"] += 1
            continue

        stats["success"] += 1

    return stats


def inject_all_cwe_bugs() -> dict:
    """Inject all CWE bug types into all datasets.

    Mirrors ``inject_all_bugs()`` from ``bug_injector.py`` but iterates over
    ``CWE_BUG_TYPES`` and respects per-CWE language support.
    """
    results = {}

    for language in LANGUAGES:
        dataset_base = PYTHON_DATASET if language == "python" else JAVA_DATASET

        for category in DATASET_CATEGORIES:
            input_dir = os.path.join(dataset_base, category)

            if not os.path.exists(input_dir):
                print(f"Skipping {input_dir} — does not exist")
                continue

            for bug_type in CWE_BUG_TYPES:
                # Respect language applicability
                supported_langs = CWE_LANGUAGE_SUPPORT.get(bug_type, [])
                if language not in supported_langs:
                    continue

                output_dir = os.path.join(
                    BUGGY_DATASETS_DIR,
                    f"{language}_{category}_{bug_type}",
                )

                print(f"Processing: {language}/{category}/{bug_type}")
                stats = process_cwe_dataset(input_dir, output_dir, language, bug_type)

                key = f"{language}_{category}_{bug_type}"
                results[key] = stats
                print(
                    f"  Total: {stats['total']}, "
                    f"Success: {stats['success']}, "
                    f"Skipped: {stats['skipped']}, "
                    f"Failed: {stats['failed']}"
                )

    return results


# ======================================================================
# CLI entry point
# ======================================================================

if __name__ == "__main__":
    print("Starting CWE-inspired bug injection...")
    results = inject_all_cwe_bugs()

    print("\n" + "=" * 60)
    print("CWE BUG INJECTION SUMMARY")
    print("=" * 60)

    total_all, success_all = 0, 0
    for key, stats in sorted(results.items()):
        total_all += stats["total"]
        success_all += stats["success"]
        rate = (stats["success"] / stats["total"] * 100) if stats["total"] > 0 else 0
        print(f"  {key}: {stats['success']}/{stats['total']} ({rate:.1f}%)")

    overall = (success_all / total_all * 100) if total_all > 0 else 0
    print(f"\nOverall: {success_all}/{total_all} ({overall:.1f}%)")
