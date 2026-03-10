#!/usr/bin/env python3
"""Semantic Preserving Mutations (SPMs) for the Agent Evaluation Experiment.

SPMs modify source code WITHOUT changing its runtime behavior. If an LLM truly
understands code semantically, its bug-localisation accuracy should remain
stable after SPMs are applied. A drop in accuracy signals reliance on
superficial patterns (variable names, formatting, comments) rather than
genuine comprehension.

All nine SPM types are implemented here:
    1. empty_lines       -- insert blank lines
    2. void_functions    -- add no-op function defs + calls
    3. void_conditionals -- insert dead conditional blocks
    4. void_loops        -- insert zero-iteration loops
    5. function_reordering -- shuffle function definition order
    6. function_extraction -- extract code block into new helper
    7. commented         -- add misleading comments
    8. variable          -- rename variables to misleading names
    9. dead_code         -- insert unreachable code blocks

Every mutation function follows the same signature and contract:
    (code, bug_line, language, strength, seed) -> (modified_code, adjusted_bug_line)
    Returns (None, None) when the SPM cannot be safely applied.

Usage:
    python -m agent_evaluation_experiment.spm_generator
"""

import ast
import os
import random
import re
import subprocess
import sys
import tempfile
import textwrap
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_evaluation_experiment.config import (
    RANDOM_SEED,
    ARTIFACTS_DIR,
    SPM_TYPES,
    MUTATION_STRENGTHS,
)


# ======================================================================
# Helpers
# ======================================================================

def _make_rng(seed: int) -> random.Random:
    """Create a local Random instance -- never touches the global state."""
    return random.Random(seed)


def _lines(code: str) -> List[str]:
    """Split code into lines, preserving trailing content."""
    return code.split("\n")


def _join(lines: List[str]) -> str:
    return "\n".join(lines)


def _verify_python_syntax(code: str) -> bool:
    """Return True if *code* is valid Python (parseable by ast)."""
    try:
        ast.parse(code)
        return True
    except SyntaxError:
        return False


def _verify_java_syntax(code: str) -> bool:
    """Light-weight Java syntax check (balanced braces + class present)."""
    # Strip comments
    stripped = re.sub(r"//.*", "", code)
    stripped = re.sub(r"/\*.*?\*/", "", stripped, flags=re.DOTALL)

    # Brace balance
    depth = 0
    for ch in stripped:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        if depth < 0:
            return False
    if depth != 0:
        return False

    # Must still contain a class/interface/enum
    if not re.search(r"\b(class|interface|enum)\s+\w+", stripped):
        return False
    return True


def _verify_syntax(code: str, language: str) -> bool:
    if language == "python":
        return _verify_python_syntax(code)
    elif language == "java":
        return _verify_java_syntax(code)
    return False


def _safe_insert_positions(lines: List[str], language: str) -> List[int]:
    """Return line indices where it is safe to insert new code.

    Avoids positions inside multi-line strings, multi-line comments,
    and decorator blocks.  The returned indices are *between* existing
    lines (i.e. insertion pushes current line down).
    """
    safe = []
    in_multiline_str = False
    in_block_comment = False  # Java /* ... */
    triple_quote_char: Optional[str] = None

    for i, line in enumerate(lines):
        stripped = line.strip()

        # -- Python multi-line strings --
        if language == "python":
            if not in_multiline_str:
                for tq in ('"""', "'''"):
                    if tq in stripped:
                        count = stripped.count(tq)
                        if count == 1:
                            in_multiline_str = True
                            triple_quote_char = tq
                            break
                        # count >= 2 means open+close on same line; still safe
            else:
                if triple_quote_char and triple_quote_char in stripped:
                    in_multiline_str = False
                    triple_quote_char = None
                continue  # inside multi-line string -- skip

        # -- Java block comments --
        if language == "java":
            if in_block_comment:
                if "*/" in stripped:
                    in_block_comment = False
                continue
            if "/*" in stripped and "*/" not in stripped:
                in_block_comment = True
                continue

        # Skip decorator lines (Python)
        if language == "python" and stripped.startswith("@"):
            continue

        safe.append(i)

    return safe


def _get_indent(line: str) -> str:
    """Return the leading whitespace of *line*."""
    return line[: len(line) - len(line.lstrip())]


def _indented_block(text: str, indent: str) -> str:
    """Indent every line of *text* by *indent*."""
    return "\n".join(indent + l for l in text.split("\n"))


def _pick_positions(safe: List[int], count: int, rng: random.Random,
                    exclude: Optional[int] = None) -> List[int]:
    """Choose *count* distinct positions from *safe*, never choosing *exclude*.

    Positions are returned in ascending order.
    """
    candidates = [p for p in safe if p != exclude]
    if not candidates:
        return []
    chosen = rng.sample(candidates, min(count, len(candidates)))
    chosen.sort()
    return chosen


def _indented_safe_positions(lines: List[str], language: str,
                             safe: Optional[List[int]] = None) -> List[int]:
    """Return safe positions that are inside indented blocks (function bodies).

    For Python: positions where the line has leading whitespace.
    For Java: positions inside brace-delimited blocks.

    This is used by SPMs that insert block-level statements (conditionals,
    loops, dead code) which would cause syntax errors at module level.
    """
    if safe is None:
        safe = _safe_insert_positions(lines, language)
    safe_set = set(safe)

    indented = []
    if language == "python":
        for i in safe_set:
            if i < len(lines):
                line = lines[i]
                # Must be a non-empty line with indentation, OR an empty line
                # between two indented lines
                if line.strip() and _get_indent(line):
                    indented.append(i)
                elif not line.strip():
                    # Check neighbours for indentation context
                    prev_indent = ""
                    next_indent = ""
                    for j in range(i - 1, -1, -1):
                        if lines[j].strip():
                            prev_indent = _get_indent(lines[j])
                            break
                    for j in range(i + 1, len(lines)):
                        if lines[j].strip():
                            next_indent = _get_indent(lines[j])
                            break
                    if prev_indent and next_indent:
                        indented.append(i)
    elif language == "java":
        depth = 0
        for i in range(len(lines)):
            depth += lines[i].count("{") - lines[i].count("}")
            if depth > 0 and i in safe_set:
                indented.append(i)

    indented.sort()
    return indented


# ======================================================================
# 1. empty_lines
# ======================================================================

def apply_empty_lines(
    code: str,
    bug_line: int,
    language: str = "python",
    strength: int = 1,
    seed: int = 42,
) -> Tuple[Optional[str], Optional[int]]:
    """Insert blank lines at random safe positions.

    strength=1: 3-5 blanks, strength=2: 6-10, strength=4: 12-20.
    """
    rng = _make_rng(seed)
    lines = _lines(code)
    safe = _safe_insert_positions(lines, language)
    if not safe:
        return None, None

    counts = {1: (3, 5), 2: (6, 10), 4: (12, 20)}
    lo, hi = counts.get(strength, (3, 5))
    n_inserts = rng.randint(lo, hi)

    # Choose positions (with replacement allowed -- can stack blanks)
    positions = sorted(rng.choices(safe, k=n_inserts))

    new_lines: List[str] = []
    inserted_before_bug = 0
    src_idx = 0

    for pos in positions:
        # Copy lines up to this position
        while src_idx < pos and src_idx < len(lines):
            new_lines.append(lines[src_idx])
            src_idx += 1
        new_lines.append("")  # blank line
        # pos is 0-indexed; inserting at pos <= bug_line-1 pushes the bug down
        if pos <= bug_line - 1:
            inserted_before_bug += 1

    # Copy remaining
    while src_idx < len(lines):
        new_lines.append(lines[src_idx])
        src_idx += 1

    result = _join(new_lines)
    new_bug_line = bug_line + inserted_before_bug

    if not _verify_syntax(result, language):
        return None, None
    return result, new_bug_line


# ======================================================================
# 2. void_functions
# ======================================================================

_PLAUSIBLE_NAMES = [
    "_validate_cache", "_check_bounds", "_init_defaults",
    "_refresh_state", "_sync_metadata", "_clear_temp",
    "_verify_integrity", "_normalize_input", "_sanitize_output",
    "_prepare_context", "_reset_counters", "_flush_buffer",
    "_update_registry", "_log_diagnostics", "_trim_whitespace",
    "_coerce_types",
]


def apply_void_functions(
    code: str,
    bug_line: int,
    language: str = "python",
    strength: int = 1,
    seed: int = 42,
) -> Tuple[Optional[str], Optional[int]]:
    """Add no-op function definitions and calls.

    strength=1: 1 func + 1 call, strength=2: 2+2, strength=4: 4+4.
    """
    rng = _make_rng(seed)
    n_funcs = {1: 1, 2: 2, 4: 4}.get(strength, 1)

    lines = _lines(code)
    safe = _safe_insert_positions(lines, language)
    if len(safe) < 2:
        return None, None

    names = rng.sample(_PLAUSIBLE_NAMES, min(n_funcs, len(_PLAUSIBLE_NAMES)))

    # We will insert function defs near the top (after imports), calls elsewhere
    # Find a good def position -- after last import / before first function
    def_pos = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if language == "python":
            if stripped.startswith(("import ", "from ")):
                def_pos = i + 1
        elif language == "java":
            if stripped.startswith(("import ", "package ")):
                def_pos = i + 1

    # Build def blocks and call lines
    def_blocks: List[str] = []
    call_lines_text: List[str] = []

    for name in names:
        if language == "python":
            def_blocks.append(f"\ndef {name}():\n    pass\n")
            call_lines_text.append(f"{name}()")
        elif language == "java":
            java_name = name.lstrip("_")
            java_name = re.sub(r"_([a-z])", lambda m: m.group(1).upper(), java_name)
            def_blocks.append(
                f"\n    private static void {java_name}() {{}}\n"
            )
            call_lines_text.append(f"        {java_name}();")

    # Insert defs at def_pos
    def_text = "".join(def_blocks)
    # When split by "\n" and appended to new_lines, each element becomes
    # a separate line in the final output.  The number of *extra* lines
    # added is the number of elements produced by the split.
    def_split = def_text.split("\n")
    def_added_lines = len(def_split)

    # Determine call positions -- pick from indented positions AFTER the def block
    # so calls are valid Python statements inside function bodies.
    indented = _indented_safe_positions(lines, language, safe) if language == "python" else safe
    adjusted_safe = [s for s in indented if s > def_pos]
    if not adjusted_safe:
        adjusted_safe = indented if indented else safe

    call_positions = _pick_positions(
        adjusted_safe, n_funcs, rng,
        exclude=bug_line - 1,  # never insert ON the bug line
    )

    # Build the new file: insert defs first, then calls
    new_lines: List[str] = []
    inserted_before_bug = 0

    # Part 1: lines before def_pos
    for i in range(min(def_pos, len(lines))):
        new_lines.append(lines[i])

    # Part 2: def blocks
    for db_line in def_split:
        new_lines.append(db_line)
    if def_pos < bug_line:
        inserted_before_bug += def_added_lines

    # Part 3: remaining lines, injecting calls at chosen positions
    call_idx = 0
    for i in range(def_pos, len(lines)):
        new_lines.append(lines[i])
        if call_idx < len(call_positions) and i == call_positions[call_idx]:
            indent = _get_indent(lines[i])
            new_lines.append(indent + call_lines_text[call_idx % len(call_lines_text)])
            if i < bug_line - 1:
                inserted_before_bug += 1
            call_idx += 1

    result = _join(new_lines)
    new_bug_line = bug_line + inserted_before_bug

    if not _verify_syntax(result, language):
        return None, None
    return result, new_bug_line


# ======================================================================
# 3. void_conditionals
# ======================================================================

def apply_void_conditionals(
    code: str,
    bug_line: int,
    language: str = "python",
    strength: int = 1,
    seed: int = 42,
) -> Tuple[Optional[str], Optional[int]]:
    """Insert dead conditional blocks (if True: pass / if False: dead_code).

    strength=1: 1, strength=2: 2, strength=4: 4.
    """
    rng = _make_rng(seed)
    n = {1: 1, 2: 2, 4: 4}.get(strength, 1)

    lines = _lines(code)
    safe = _safe_insert_positions(lines, language)

    # For Python, only insert inside indented blocks (function bodies)
    # to avoid syntax errors at module level.
    if language == "python":
        safe = _indented_safe_positions(lines, language, safe)
    if not safe:
        return None, None

    positions = _pick_positions(safe, n, rng, exclude=bug_line - 1)
    if not positions:
        return None, None

    new_lines: List[str] = []
    inserted_before_bug = 0
    pos_iter = iter(sorted(set(positions)))
    next_pos = next(pos_iter, None)

    for i, line in enumerate(lines):
        # Insert BEFORE this line if this index matches
        if next_pos is not None and i == next_pos:
            indent = _get_indent(line) if line.strip() else "    "
            if language == "python":
                variant = rng.randint(0, 2)
                if variant == 0:
                    new_lines.append(f"{indent}if True:")
                    new_lines.append(f"{indent}    pass")
                elif variant == 1:
                    new_lines.append(f"{indent}if False:")
                    new_lines.append(f"{indent}    _unused = 0")
                else:
                    new_lines.append(f"{indent}if True:")
                    new_lines.append(f"{indent}    _ = None")
                added = 2
            else:  # java
                templates_java = [
                    "if (true) {}",
                    "if (false) { int _unused = 0; }",
                    "if (true) { /* no-op */ }",
                ]
                template = rng.choice(templates_java)
                new_lines.append(indent + template)
                added = 1

            if i <= bug_line - 1:
                inserted_before_bug += added

            next_pos = next(pos_iter, None)

        new_lines.append(line)

    result = _join(new_lines)
    new_bug_line = bug_line + inserted_before_bug

    if not _verify_syntax(result, language):
        return None, None
    return result, new_bug_line


# ======================================================================
# 4. void_loops
# ======================================================================

def apply_void_loops(
    code: str,
    bug_line: int,
    language: str = "python",
    strength: int = 1,
    seed: int = 42,
) -> Tuple[Optional[str], Optional[int]]:
    """Insert loops that execute zero times.

    strength=1: 1, strength=2: 2, strength=4: 4.
    """
    rng = _make_rng(seed)
    n = {1: 1, 2: 2, 4: 4}.get(strength, 1)

    lines = _lines(code)
    safe = _safe_insert_positions(lines, language)

    # For Python, only insert inside indented blocks (function bodies)
    if language == "python":
        safe = _indented_safe_positions(lines, language, safe)
    if not safe:
        return None, None

    positions = _pick_positions(safe, n, rng, exclude=bug_line - 1)
    if not positions:
        return None, None

    new_lines: List[str] = []
    inserted_before_bug = 0
    pos_iter = iter(sorted(set(positions)))
    next_pos = next(pos_iter, None)

    for i, line in enumerate(lines):
        if next_pos is not None and i == next_pos:
            indent = _get_indent(line) if line.strip() else "    "
            if language == "python":
                variant = rng.randint(0, 1)
                if variant == 0:
                    new_lines.append(f"{indent}for _ in range(0):")
                    new_lines.append(f"{indent}    pass")
                else:
                    new_lines.append(f"{indent}while False:")
                    new_lines.append(f"{indent}    pass")
                added = 2
            else:
                templates_java = [
                    "for (int _i = 0; _i < 0; _i++) {}",
                    "while (false) {}",
                ]
                template = rng.choice(templates_java)
                new_lines.append(indent + template)
                added = 1

            if i <= bug_line - 1:
                inserted_before_bug += added

            next_pos = next(pos_iter, None)

        new_lines.append(line)

    result = _join(new_lines)
    new_bug_line = bug_line + inserted_before_bug

    if not _verify_syntax(result, language):
        return None, None
    return result, new_bug_line


# ======================================================================
# 5. function_reordering
# ======================================================================

def _find_python_functions(code: str) -> List[dict]:
    """Identify top-level function definitions in Python code.

    Returns a list of dicts: {name, start, end} where start/end are
    0-indexed line numbers (inclusive).
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    lines = _lines(code)
    funcs = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.lineno - 1  # 0-indexed
            end = node.end_lineno - 1 if hasattr(node, "end_lineno") and node.end_lineno else start
            # Include decorators
            if node.decorator_list:
                dec_start = node.decorator_list[0].lineno - 1
                start = min(start, dec_start)
            funcs.append({"name": node.name, "start": start, "end": end})
    return funcs


def _find_java_methods(code: str) -> List[dict]:
    """Identify method definitions in Java code using regex.

    Returns a list of dicts: {name, start, end} (0-indexed line numbers).
    """
    lines = _lines(code)
    method_pattern = re.compile(
        r"^\s*(?:(?:public|private|protected|static|final|abstract|synchronized|native)\s+)*"
        r"(?:\w+(?:<[^>]*>)?(?:\[\])*\s+)"
        r"(\w+)\s*\([^)]*\)\s*(?:throws\s+[\w,\s]+)?\s*\{"
    )

    methods = []
    i = 0
    while i < len(lines):
        m = method_pattern.match(lines[i])
        if m:
            name = m.group(1)
            start = i
            # Find matching close brace
            depth = 0
            for j in range(i, len(lines)):
                depth += lines[j].count("{") - lines[j].count("}")
                if depth == 0:
                    methods.append({"name": name, "start": start, "end": j})
                    break
        i += 1
    return methods


def apply_function_reordering(
    code: str,
    bug_line: int,
    language: str = "python",
    strength: int = 1,
    seed: int = 42,
) -> Tuple[Optional[str], Optional[int]]:
    """Shuffle the order of top-level function/method definitions.

    The bug_line is tracked through the reorder so the new position is
    returned correctly. *strength* is ignored -- we do one full shuffle.
    """
    rng = _make_rng(seed)
    lines = _lines(code)

    if language == "python":
        funcs = _find_python_functions(code)
    elif language == "java":
        funcs = _find_java_methods(code)
    else:
        return None, None

    if len(funcs) < 2:
        return None, None  # nothing to reorder

    # Sort functions by start position (they should already be, but be safe)
    funcs.sort(key=lambda f: f["start"])

    # Extract function blocks and inter-function code
    segments: List[dict] = []  # {type: "func"|"other", lines: [...], contains_bug: bool}

    prev_end = 0
    for func in funcs:
        # Code between previous segment and this function
        if func["start"] > prev_end:
            seg_lines = lines[prev_end : func["start"]]
            contains_bug = prev_end < bug_line <= func["start"]
            segments.append({
                "type": "other",
                "lines": seg_lines,
                "contains_bug": contains_bug,
                "orig_start": prev_end,
            })
        # The function itself
        seg_lines = lines[func["start"] : func["end"] + 1]
        contains_bug = func["start"] < bug_line <= func["end"] + 1
        segments.append({
            "type": "func",
            "lines": seg_lines,
            "contains_bug": contains_bug,
            "orig_start": func["start"],
            "bug_offset": (bug_line - 1) - func["start"] if contains_bug else None,
        })
        prev_end = func["end"] + 1

    # Trailing code after last function
    if prev_end < len(lines):
        seg_lines = lines[prev_end:]
        contains_bug = prev_end < bug_line <= len(lines)
        segments.append({
            "type": "other",
            "lines": seg_lines,
            "contains_bug": contains_bug,
            "orig_start": prev_end,
        })

    # Separate func segments and other segments
    func_segments = [s for s in segments if s["type"] == "func"]
    other_segments = [s for s in segments if s["type"] == "other"]

    # Shuffle function segments
    rng.shuffle(func_segments)

    # Rebuild: other[0], func[0], other[1], func[1], ..., other[n]
    # We keep the first "other" block (imports etc.) at top, and trailing at bottom.
    # For simplicity, place all "other" blocks in their relative order,
    # interleave shuffled functions between them.
    new_lines: List[str] = []
    new_bug_line = None

    # Place first other segment (if it comes before all funcs)
    if other_segments and other_segments[0]["orig_start"] == 0:
        seg = other_segments.pop(0)
        if seg["contains_bug"]:
            new_bug_line = len(new_lines) + (bug_line - seg["orig_start"])
        new_lines.extend(seg["lines"])

    # Place shuffled functions, inserting other segments at the end
    for seg in func_segments:
        if seg["contains_bug"] and seg["bug_offset"] is not None:
            new_bug_line = len(new_lines) + seg["bug_offset"] + 1  # 1-indexed
        new_lines.extend(seg["lines"])
        # Add a blank separator between functions
        if language == "python":
            new_lines.append("")
            new_lines.append("")

    # Append remaining other segments
    for seg in other_segments:
        if seg["contains_bug"]:
            new_bug_line = len(new_lines) + (bug_line - seg["orig_start"])
        new_lines.extend(seg["lines"])

    if new_bug_line is None:
        # Bug line was not found in any segment -- cannot safely continue
        return None, None

    result = _join(new_lines)
    if not _verify_syntax(result, language):
        return None, None
    return result, new_bug_line


# ======================================================================
# 6. function_extraction
# ======================================================================

def _find_extractable_block_python(
    code: str, bug_line: int, rng: random.Random
) -> Optional[dict]:
    """Find a self-contained block of 2-5 lines suitable for extraction.

    A block is "self-contained" if it does not read any local variables
    that were assigned outside of it (it may assign new variables, call
    builtins, use literals, etc.).

    Returns {start, end, indent, parent_func} or None.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None

    lines = _lines(code)

    # Collect top-level function bodies as candidate regions
    candidate_regions: List[dict] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not hasattr(node, "end_lineno") or node.end_lineno is None:
                continue
            body_start = node.body[0].lineno - 1  # 0-indexed
            body_end = node.end_lineno - 1
            candidate_regions.append({
                "func_name": node.name,
                "body_start": body_start,
                "body_end": body_end,
            })

    if not candidate_regions:
        return None

    rng.shuffle(candidate_regions)

    for region in candidate_regions:
        body_start = region["body_start"]
        body_end = region["body_end"]

        # Try different block sizes (2-5 lines)
        for block_size in rng.sample(range(2, 6), min(4, body_end - body_start)):
            if body_end - body_start < block_size:
                continue

            # Pick a random start within the region
            max_start = body_end - block_size + 1
            if max_start <= body_start:
                continue

            possible_starts = list(range(body_start, max_start + 1))
            rng.shuffle(possible_starts)

            for start in possible_starts:
                end = start + block_size - 1  # inclusive

                # Must not overlap with bug_line (1-indexed)
                bug_0 = bug_line - 1
                if start <= bug_0 <= end:
                    continue

                # All lines must be non-empty and at the same indent
                block_lines = lines[start : end + 1]
                if any(not l.strip() for l in block_lines):
                    continue

                indents = [_get_indent(l) for l in block_lines]
                if len(set(indents)) != 1:
                    continue

                # Check self-containedness: parse the block and look for
                # Name nodes that are loaded but not stored within the block
                block_text = textwrap.dedent("\n".join(block_lines))
                try:
                    block_tree = ast.parse(block_text)
                except SyntaxError:
                    continue

                stored: set = set()
                loaded: set = set()
                for n in ast.walk(block_tree):
                    if isinstance(n, ast.Name):
                        if isinstance(n.ctx, ast.Store):
                            stored.add(n.id)
                        elif isinstance(n.ctx, ast.Load):
                            loaded.add(n.id)

                # Allow builtins and module-level names
                import builtins
                builtin_names = set(dir(builtins))
                external_deps = loaded - stored - builtin_names

                # If block depends on local vars, skip it
                if external_deps:
                    continue

                # Must not contain return, yield, break, continue
                for n in ast.walk(block_tree):
                    if isinstance(n, (ast.Return, ast.Yield, ast.YieldFrom,
                                      ast.Break, ast.Continue)):
                        break
                else:
                    return {
                        "start": start,
                        "end": end,
                        "indent": indents[0],
                        "parent_func": region["func_name"],
                    }

    return None


def apply_function_extraction(
    code: str,
    bug_line: int,
    language: str = "python",
    strength: int = 1,
    seed: int = 42,
) -> Tuple[Optional[str], Optional[int]]:
    """Extract a self-contained code block into a new helper function.

    Only implemented for Python (Java extraction is too fragile without a
    proper parser). Returns (None, None) if no suitable block is found.
    """
    if language != "python":
        # Java extraction would require a full Java parser; skip for safety
        return None, None

    rng = _make_rng(seed)
    block = _find_extractable_block_python(code, bug_line, rng)
    if block is None:
        return None, None

    lines = _lines(code)
    start, end = block["start"], block["end"]
    indent = block["indent"]

    # Generate a helper name
    helper_name = f"_extracted_helper_{rng.randint(1000, 9999)}"

    # Build the extracted function (at module level, no indent)
    extracted_lines = lines[start : end + 1]
    dedented = textwrap.dedent("\n".join(extracted_lines))
    func_def = f"def {helper_name}():\n"
    func_body = textwrap.indent(dedented, "    ")
    func_block = f"\n{func_def}{func_body}\n"

    # Replace original lines with a call
    call_line = f"{indent}{helper_name}()"

    # Figure out where to put the function definition -- just before the
    # parent function (so it is defined before it is called).
    # Find parent function start
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None, None

    insert_pos = 0
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == block["parent_func"]:
                insert_pos = node.lineno - 1
                if node.decorator_list:
                    insert_pos = min(insert_pos, node.decorator_list[0].lineno - 1)
                break

    # Build new code
    func_def_lines = func_block.split("\n")
    n_def_lines = len(func_def_lines)

    new_lines: List[str] = []
    inserted_before_bug = 0

    # Lines before insert_pos
    for i in range(insert_pos):
        new_lines.append(lines[i])

    # Insert function definition
    for fl in func_def_lines:
        new_lines.append(fl)
    if insert_pos < bug_line:
        inserted_before_bug += n_def_lines

    # Lines from insert_pos onward, replacing the extracted block
    removed_count = 0
    for i in range(insert_pos, len(lines)):
        if start <= i <= end:
            if i == start:
                # Replace with call
                new_lines.append(call_line)
            # Skip the rest of the block (lines are removed)
            if i > start:
                removed_count += 1
                if i < bug_line - 1:
                    inserted_before_bug -= 1
            continue
        new_lines.append(lines[i])

    result = _join(new_lines)
    new_bug_line = bug_line + inserted_before_bug

    if new_bug_line < 1:
        return None, None
    if not _verify_syntax(result, language):
        return None, None
    return result, new_bug_line


# ======================================================================
# 7. commented (misleading comments)
# ======================================================================

_MISLEADING_COMMENTS = [
    "Critical security check",
    "TODO: fix race condition here",
    "Deprecated: will be removed in v3.0",
    "Performance optimization -- do not modify",
    "Edge case handler for empty input",
    "Workaround for upstream bug #4821",
    "Memory leak fix -- see issue tracker",
    "Thread-safe implementation below",
    "Cache invalidation logic",
    "Boundary validation required here",
    "Temporary patch -- needs proper refactor",
    "Auth token refresh logic",
    "Handles Unicode edge cases",
    "Rate limiter checkpoint",
    "Rollback point for transaction safety",
]


def apply_commented(
    code: str,
    bug_line: int,
    language: str = "python",
    strength: int = 1,
    seed: int = 42,
) -> Tuple[Optional[str], Optional[int]]:
    """Insert misleading comments at random positions.

    strength=1: 2-3, strength=2: 4-6, strength=4: 8-12.
    """
    rng = _make_rng(seed)
    counts = {1: (2, 3), 2: (4, 6), 4: (8, 12)}
    lo, hi = counts.get(strength, (2, 3))
    n = rng.randint(lo, hi)

    lines = _lines(code)
    safe = _safe_insert_positions(lines, language)
    if not safe:
        return None, None

    positions = sorted(rng.choices(safe, k=n))
    comment_prefix = "#" if language == "python" else "//"

    new_lines: List[str] = []
    inserted_before_bug = 0
    src_idx = 0

    for pos in positions:
        while src_idx < pos and src_idx < len(lines):
            new_lines.append(lines[src_idx])
            src_idx += 1
        # Determine indent from the next line
        indent = _get_indent(lines[pos]) if pos < len(lines) and lines[pos].strip() else "    "
        comment_text = rng.choice(_MISLEADING_COMMENTS)
        new_lines.append(f"{indent}{comment_prefix} {comment_text}")
        # pos is 0-indexed; inserting at pos <= bug_line-1 pushes the bug down
        if pos <= bug_line - 1:
            inserted_before_bug += 1

    while src_idx < len(lines):
        new_lines.append(lines[src_idx])
        src_idx += 1

    result = _join(new_lines)
    new_bug_line = bug_line + inserted_before_bug

    if not _verify_syntax(result, language):
        return None, None
    return result, new_bug_line


# ======================================================================
# 8. variable (misleading variable renaming)
# ======================================================================

_RENAME_MAP = {
    "result": "temp_unused",
    "count": "index_offset",
    "total": "remainder",
    "data": "cache_ref",
    "items": "node_queue",
    "value": "sentinel",
    "output": "staging_buf",
    "answer": "placeholder",
    "current": "fallback_val",
    "found": "skip_flag",
    "target": "origin_ref",
    "index": "depth_counter",
    "sum": "partial_diff",
    "max_val": "min_threshold",
    "min_val": "max_threshold",
    "temp": "result_final",
    "flag": "counter_aux",
    "acc": "decay_rate",
    "prev": "next_candidate",
    "next_val": "prev_snapshot",
}


def _find_renamable_variables_python(code: str) -> List[str]:
    """Find variable names in Python code that appear in _RENAME_MAP."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    names_in_code: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names_in_code.add(node.id)

    # Only return names that exist in the rename map
    return [n for n in names_in_code if n in _RENAME_MAP]


def _all_names_in_code(code: str) -> set:
    """Collect every identifier used in the code."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return set()
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
            for arg in node.args.args:
                names.add(arg.arg)
        elif isinstance(node, ast.ClassDef):
            names.add(node.name)
    return names


def apply_variable(
    code: str,
    bug_line: int,
    language: str = "python",
    strength: int = 1,
    seed: int = 42,
) -> Tuple[Optional[str], Optional[int]]:
    """Rename variables to misleading names.

    strength=1: 1 rename, strength=2: 2, strength=4: 4.
    Bug line does not shift (renaming is in-place).
    """
    rng = _make_rng(seed)
    n = {1: 1, 2: 2, 4: 4}.get(strength, 1)

    if language == "python":
        candidates = _find_renamable_variables_python(code)
    elif language == "java":
        # For Java, use regex to find common variable declarations
        candidates = []
        for name in _RENAME_MAP:
            pattern = r"\b" + re.escape(name) + r"\b"
            if re.search(pattern, code):
                candidates.append(name)
    else:
        return None, None

    if not candidates:
        return None, None

    all_names = _all_names_in_code(code) if language == "python" else set(
        re.findall(r"\b\w+\b", code)
    )

    rng.shuffle(candidates)
    renames_applied = 0
    result = code

    for old_name in candidates:
        if renames_applied >= n:
            break
        new_name = _RENAME_MAP[old_name]

        # Collision check -- new name must not already exist
        if new_name in all_names:
            continue

        # Apply rename using word-boundary regex
        pattern = r"\b" + re.escape(old_name) + r"\b"
        new_result = re.sub(pattern, new_name, result)
        if new_result == result:
            continue

        # Verify syntax after rename
        if not _verify_syntax(new_result, language):
            continue

        result = new_result
        all_names.add(new_name)
        all_names.discard(old_name)
        renames_applied += 1

    if renames_applied == 0:
        return None, None

    # Variable renaming does not change line count
    return result, bug_line


# ======================================================================
# 9. dead_code
# ======================================================================

_DEAD_CODE_JAVA = [
    "if (false) { throw new RuntimeException(\"unreachable\"); }",
    "if (false) { int _dead = Integer.MAX_VALUE; }",
    "if (false) { System.exit(99); }",
]


def apply_dead_code(
    code: str,
    bug_line: int,
    language: str = "python",
    strength: int = 1,
    seed: int = 42,
) -> Tuple[Optional[str], Optional[int]]:
    """Insert unreachable code blocks.

    strength=1: 1, strength=2: 2, strength=4: 4.
    """
    rng = _make_rng(seed)
    n = {1: 1, 2: 2, 4: 4}.get(strength, 1)

    lines = _lines(code)
    safe = _safe_insert_positions(lines, language)

    # For Python, only insert inside indented blocks (function bodies)
    if language == "python":
        safe = _indented_safe_positions(lines, language, safe)
    if not safe:
        return None, None

    positions = _pick_positions(safe, n, rng, exclude=bug_line - 1)
    if not positions:
        return None, None

    _dead_py_bodies = [
        "raise RuntimeError('unreachable')",
        "_dead_var = 'never executed'",
        "import sys; sys.exit(99)",
        "assert False, 'dead path'",
    ]

    new_lines: List[str] = []
    inserted_before_bug = 0
    pos_iter = iter(sorted(positions))
    next_pos = next(pos_iter, None)

    for i, line in enumerate(lines):
        if next_pos is not None and i == next_pos:
            indent = _get_indent(line) if line.strip() else "    "
            if language == "python":
                body = rng.choice(_dead_py_bodies)
                new_lines.append(f"{indent}if False:")
                new_lines.append(f"{indent}    {body}")
                added = 2
            else:
                template = rng.choice(_DEAD_CODE_JAVA)
                new_lines.append(indent + template)
                added = 1

            if i <= bug_line - 1:
                inserted_before_bug += added

            next_pos = next(pos_iter, None)

        new_lines.append(line)

    result = _join(new_lines)
    new_bug_line = bug_line + inserted_before_bug

    if not _verify_syntax(result, language):
        return None, None
    return result, new_bug_line


# ======================================================================
# Dispatcher
# ======================================================================

_SPM_DISPATCH = {
    "empty_lines": apply_empty_lines,
    "void_functions": apply_void_functions,
    "void_conditionals": apply_void_conditionals,
    "void_loops": apply_void_loops,
    "function_reordering": apply_function_reordering,
    "function_extraction": apply_function_extraction,
    "commented": apply_commented,
    "variable": apply_variable,
    "dead_code": apply_dead_code,
}


def apply_spm_by_type(
    spm_type: str,
    code: str,
    bug_line: int,
    language: str = "python",
    strength: int = 1,
    seed: int = 42,
) -> Tuple[Optional[str], Optional[int]]:
    """Route to the correct SPM function based on *spm_type* string.

    Returns (modified_code, adjusted_bug_line) or (None, None).
    """
    func = _SPM_DISPATCH.get(spm_type)
    if func is None:
        raise ValueError(f"Unknown SPM type: {spm_type!r}. "
                         f"Valid types: {sorted(_SPM_DISPATCH)}")
    return func(code, bug_line, language=language, strength=strength, seed=seed)


# ======================================================================
# Cumulative application
# ======================================================================

def apply_cumulative_spms(
    code: str,
    bug_line: int,
    language: str = "python",
    spm_sequence: Optional[List[str]] = None,
    strength: int = 1,
    seed: int = 42,
) -> Tuple[Optional[str], Optional[int]]:
    """Apply multiple SPMs sequentially.

    Each subsequent SPM receives the output of the previous one.
    If any step fails, the entire chain returns (None, None).
    """
    if spm_sequence is None:
        spm_sequence = ["commented", "variable", "dead_code"]

    current_code = code
    current_bug = bug_line

    for i, spm_type in enumerate(spm_sequence):
        step_seed = seed + i  # vary seed across steps for diversity
        result_code, result_bug = apply_spm_by_type(
            spm_type, current_code, current_bug,
            language=language, strength=strength, seed=step_seed,
        )
        if result_code is None or result_bug is None:
            return None, None
        current_code = result_code
        current_bug = result_bug

    return current_code, current_bug


# ======================================================================
# Equivalence verification
# ======================================================================

def verify_spm_equivalence(
    original_code: str,
    spm_code: str,
    language: str = "python",
    timeout: int = 5,
) -> Dict[str, object]:
    """Verify that the SPM-transformed code is behaviourally equivalent.

    For Python: execute both versions in subprocesses and compare stdout +
    return code.  For Java: verify syntax only (compilation is expensive).

    Returns {"equivalent": bool, "reason": str}.
    """
    if language == "java":
        orig_ok = _verify_java_syntax(original_code)
        spm_ok = _verify_java_syntax(spm_code)
        if not spm_ok:
            return {"equivalent": False, "reason": "SPM code has invalid Java syntax"}
        if not orig_ok:
            return {"equivalent": False, "reason": "Original code has invalid Java syntax"}
        return {"equivalent": True, "reason": "Java syntax check passed"}

    # Python: execute both
    def _run(code: str) -> Tuple[Optional[str], Optional[int]]:
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False
            ) as tmp:
                tmp.write(code)
                tmp_path = tmp.name
            proc = subprocess.run(
                [sys.executable, tmp_path],
                capture_output=True, text=True, timeout=timeout,
            )
            return proc.stdout, proc.returncode
        except subprocess.TimeoutExpired:
            return None, -1
        except Exception as e:
            return None, -2
        finally:
            try:
                os.unlink(tmp_path)
            except (OSError, UnboundLocalError):
                pass

    orig_out, orig_rc = _run(original_code)
    spm_out, spm_rc = _run(spm_code)

    if orig_rc == -1 or spm_rc == -1:
        return {"equivalent": False, "reason": "Timeout during execution"}
    if orig_rc == -2 or spm_rc == -2:
        return {"equivalent": False, "reason": "Execution error"}

    if orig_out == spm_out and orig_rc == spm_rc:
        return {"equivalent": True, "reason": "Identical stdout and return code"}

    if orig_rc != spm_rc:
        return {
            "equivalent": False,
            "reason": f"Return codes differ: original={orig_rc}, spm={spm_rc}",
        }
    return {
        "equivalent": False,
        "reason": "Stdout differs between original and SPM version",
    }


# ======================================================================
# Batch generation
# ======================================================================

def generate_all_spm_variants(
    code: str,
    bug_line: int,
    language: str = "python",
    spm_types: Optional[List[str]] = None,
    strengths: Optional[List[int]] = None,
    seed: int = 42,
) -> List[Dict]:
    """Generate all SPM variants for a single program.

    Returns a list of dicts:
        [{"spm_type": str, "strength": int, "code": str,
          "bug_line": int, "valid": bool}, ...]
    """
    if spm_types is None:
        spm_types = list(SPM_TYPES)
    if strengths is None:
        strengths = list(MUTATION_STRENGTHS)

    variants: List[Dict] = []

    for spm_type in spm_types:
        for strength in strengths:
            try:
                mod_code, mod_bug = apply_spm_by_type(
                    spm_type, code, bug_line,
                    language=language, strength=strength, seed=seed,
                )
            except Exception as e:
                variants.append({
                    "spm_type": spm_type,
                    "strength": strength,
                    "code": None,
                    "bug_line": None,
                    "valid": False,
                    "error": str(e),
                })
                continue

            if mod_code is None:
                variants.append({
                    "spm_type": spm_type,
                    "strength": strength,
                    "code": None,
                    "bug_line": None,
                    "valid": False,
                    "error": "SPM could not be applied",
                })
            else:
                variants.append({
                    "spm_type": spm_type,
                    "strength": strength,
                    "code": mod_code,
                    "bug_line": mod_bug,
                    "valid": True,
                    "error": None,
                })

    return variants


# ======================================================================
# Main -- demonstration
# ======================================================================

_SAMPLE_PYTHON = '''\
import math


def compute_area(radius):
    """Compute the area of a circle."""
    if radius < 0:
        return 0
    area = math.pi * radius * radius
    return area


def compute_circumference(radius):
    """Compute the circumference of a circle."""
    if radius < 0:
        return 0
    result = 2 * math.pi * radius
    return result


def main():
    values = [1, 2, 3, -1, 5]
    total = 0
    for v in values:
        a = compute_area(v)
        c = compute_circumference(v)
        total = total + a + c
        print(f"r={v}: area={a:.2f}, circ={c:.2f}")
    count = len(values)
    print(f"Processed {count} values, total={total:.2f}")


if __name__ == "__main__":
    main()
'''


def main():
    """Demonstrate each SPM on a sample Python program."""
    bug_line = 8  # area = math.pi * radius * radius
    language = "python"
    seed = RANDOM_SEED

    print("=" * 72)
    print("  SPM Generator -- Demonstration")
    print("=" * 72)
    print(f"\nSample program ({len(_lines(_SAMPLE_PYTHON))} lines), "
          f"bug at line {bug_line}:")
    print("-" * 72)
    for i, line in enumerate(_lines(_SAMPLE_PYTHON), 1):
        marker = " <<< BUG" if i == bug_line else ""
        print(f"  {i:3d} | {line}{marker}")
    print("-" * 72)

    for spm_type in sorted(_SPM_DISPATCH):
        print(f"\n{'='*72}")
        print(f"  SPM: {spm_type}")
        print(f"{'='*72}")

        for strength in MUTATION_STRENGTHS:
            mod_code, mod_bug = apply_spm_by_type(
                spm_type, _SAMPLE_PYTHON, bug_line,
                language=language, strength=strength, seed=seed,
            )
            if mod_code is None:
                print(f"  strength={strength}: SKIPPED (could not apply)")
                continue

            n_lines = len(_lines(mod_code))
            print(f"  strength={strength}: {n_lines} lines, "
                  f"bug moved to line {mod_bug}")

            # Show a compact diff-like view for strength=1 only
            if strength == 1:
                print(f"  --- begin (first 40 lines) ---")
                for i, line in enumerate(_lines(mod_code)[:40], 1):
                    marker = " <<< BUG" if i == mod_bug else ""
                    print(f"    {i:3d} | {line}{marker}")
                if n_lines > 40:
                    print(f"    ... ({n_lines - 40} more lines)")
                print(f"  --- end ---")

    # Demonstrate cumulative SPMs
    print(f"\n{'='*72}")
    print("  Cumulative SPM: commented -> variable -> dead_code")
    print(f"{'='*72}")
    cum_code, cum_bug = apply_cumulative_spms(
        _SAMPLE_PYTHON, bug_line, language,
        spm_sequence=["commented", "variable", "dead_code"],
        strength=1, seed=seed,
    )
    if cum_code:
        n = len(_lines(cum_code))
        print(f"  Result: {n} lines, bug at line {cum_bug}")
        print("  --- begin (first 50 lines) ---")
        for i, line in enumerate(_lines(cum_code)[:50], 1):
            marker = " <<< BUG" if i == cum_bug else ""
            print(f"    {i:3d} | {line}{marker}")
        if n > 50:
            print(f"    ... ({n - 50} more lines)")
        print("  --- end ---")
    else:
        print("  Cumulative SPM: FAILED")

    # Demonstrate batch generation
    print(f"\n{'='*72}")
    print("  Batch generation summary")
    print(f"{'='*72}")
    variants = generate_all_spm_variants(
        _SAMPLE_PYTHON, bug_line, language, seed=seed,
    )
    success = sum(1 for v in variants if v["valid"])
    total = len(variants)
    print(f"  Generated {total} variants, {success} valid, "
          f"{total - success} failed")
    for v in variants:
        status = "OK" if v["valid"] else "FAIL"
        err = f" ({v['error']})" if v.get("error") else ""
        bl = f", bug_line={v['bug_line']}" if v["bug_line"] else ""
        print(f"    [{status}] {v['spm_type']:25s} strength={v['strength']}{bl}{err}")

    # Equivalence check on one variant
    print(f"\n{'='*72}")
    print("  Equivalence verification (empty_lines, strength=1)")
    print(f"{'='*72}")
    el_code, el_bug = apply_empty_lines(_SAMPLE_PYTHON, bug_line, language, 1, seed)
    if el_code:
        eq_result = verify_spm_equivalence(_SAMPLE_PYTHON, el_code, language)
        print(f"  equivalent: {eq_result['equivalent']}")
        print(f"  reason: {eq_result['reason']}")
    else:
        print("  Could not generate variant for equivalence check")

    print(f"\n{'='*72}")
    print("  Done.")
    print(f"{'='*72}")


if __name__ == "__main__":
    main()
