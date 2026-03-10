#!/usr/bin/env python3
"""Program validator for agent evaluation experiment.

Validates all programs in the dataset are syntactically valid and captures
baseline outputs. Supports both Python and Java programs with parallel
processing for efficiency.
"""

import os
import sys
import json
import ast
import re
import subprocess
import tempfile
import time
from multiprocessing import Pool, cpu_count
from functools import partial
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_evaluation_experiment.config import (
    JAVA_DATASET, PYTHON_DATASET, ARTIFACTS_DIR,
    DATASET_CATEGORIES, LANGUAGES, RANDOM_SEED
)

# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────

VALIDATION_OUTPUT_FILE = os.path.join(ARTIFACTS_DIR, "validated_programs.json")
PYTHON_EXEC_TIMEOUT = 5  # seconds
NUM_WORKERS = max(1, cpu_count() - 1)


# ──────────────────────────────────────────────────────────────────────
# Python Validation
# ──────────────────────────────────────────────────────────────────────

def validate_python_syntax(code: str) -> Tuple[bool, Optional[str]]:
    """Check Python code for syntax validity using ast.parse and compile.

    Returns:
        (is_valid, error_message) -- error_message is None when valid.
    """
    try:
        ast.parse(code)
    except SyntaxError as e:
        return False, f"SyntaxError: {e.msg} (line {e.lineno})"
    except Exception as e:
        return False, f"ParseError: {str(e)}"

    try:
        compile(code, "<string>", "exec")
    except SyntaxError as e:
        return False, f"CompileError: {e.msg} (line {e.lineno})"
    except Exception as e:
        return False, f"CompileError: {str(e)}"

    return True, None


def execute_python_code(code: str, timeout: int = PYTHON_EXEC_TIMEOUT) -> Dict:
    """Try to execute Python code in a subprocess and capture output.

    Returns a dict with keys: executed (bool), stdout, stderr, returncode.
    Execution is best-effort -- many programs depend on external imports
    or interactive input and will fail, which is acceptable.
    """
    result = {
        "executed": False,
        "stdout": "",
        "stderr": "",
        "returncode": None,
    }
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as tmp:
            tmp.write(code)
            tmp_path = tmp.name

        proc = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        result["executed"] = True
        result["stdout"] = proc.stdout[:2000]  # cap output size
        result["stderr"] = proc.stderr[:2000]
        result["returncode"] = proc.returncode
    except subprocess.TimeoutExpired:
        result["executed"] = True
        result["stderr"] = f"TimeoutExpired: exceeded {timeout}s"
        result["returncode"] = -1
    except Exception as e:
        result["stderr"] = f"ExecutionError: {str(e)}"
    finally:
        try:
            os.unlink(tmp_path)
        except (OSError, UnboundLocalError):
            pass

    return result


def validate_single_python(args: Tuple[str, str, str]) -> Dict:
    """Validate a single Python program file.

    Args:
        args: (file_path, category, filename) tuple for pool.map.

    Returns:
        Dict with validation results for this file.
    """
    file_path, category, filename = args
    record = {
        "filename": filename,
        "category": category,
        "language": "python",
        "syntax_valid": False,
        "error": None,
        "execution": None,
    }

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        record["error"] = f"FileError: {str(e)}"
        return record

    code = data.get("output", "")
    if not code or not code.strip():
        record["error"] = "EmptyCode: output field is empty"
        return record

    is_valid, err = validate_python_syntax(code)
    record["syntax_valid"] = is_valid
    record["error"] = err

    # Attempt execution only for syntactically valid programs
    if is_valid:
        record["execution"] = execute_python_code(code)

    return record


# ──────────────────────────────────────────────────────────────────────
# Java Validation
# ──────────────────────────────────────────────────────────────────────

def _check_brace_balance(code: str) -> Tuple[bool, Optional[str]]:
    """Check that braces, parens, and brackets are balanced."""
    stack = []
    matching = {")": "(", "]": "[", "}": "{"}
    openers = set("({[")
    closers = set(")}]")
    in_string = False
    in_char = False
    in_line_comment = False
    in_block_comment = False
    prev = ""

    for i, ch in enumerate(code):
        # Track comment and string state to skip their contents
        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            prev = ch
            continue
        if in_block_comment:
            if prev == "*" and ch == "/":
                in_block_comment = False
            prev = ch
            continue
        if in_string:
            if ch == '"' and prev != "\\":
                in_string = False
            prev = ch
            continue
        if in_char:
            if ch == "'" and prev != "\\":
                in_char = False
            prev = ch
            continue

        # Detect start of comments / strings
        if prev == "/" and ch == "/":
            in_line_comment = True
            # Pop the '/' we shouldn't have processed as opener
            prev = ch
            continue
        if prev == "/" and ch == "*":
            in_block_comment = True
            prev = ch
            continue
        if ch == '"':
            in_string = True
            prev = ch
            continue
        if ch == "'":
            in_char = True
            prev = ch
            continue

        if ch in openers:
            stack.append(ch)
        elif ch in closers:
            if not stack:
                return False, f"UnmatchedCloser: '{ch}' at position {i}"
            if stack[-1] != matching[ch]:
                return False, (
                    f"MismatchedBrace: expected closer for '{stack[-1]}' "
                    f"but got '{ch}' at position {i}"
                )
            stack.pop()

        prev = ch

    if stack:
        return False, f"UnclosedOpener: '{stack[-1]}' has no matching closer"
    return True, None


def _has_class_definition(code: str) -> bool:
    """Check whether code contains at least one Java class/interface/enum."""
    # Strip comments for cleaner matching
    stripped = re.sub(r"//.*", "", code)
    stripped = re.sub(r"/\*.*?\*/", "", stripped, flags=re.DOTALL)
    return bool(
        re.search(
            r"\b(class|interface|enum)\s+\w+", stripped
        )
    )


def _try_javalang_parse(code: str) -> Tuple[bool, Optional[str]]:
    """Attempt full parse with javalang if available."""
    try:
        import javalang
        javalang.parse.parse(code)
        return True, None
    except ImportError:
        # javalang not installed -- fall through to regex validation
        return True, None
    except Exception as e:
        return False, f"JavalangError: {str(e)[:200]}"


def validate_java_syntax(code: str) -> Tuple[bool, Optional[str]]:
    """Validate Java code syntax with a layered approach.

    1. Check brace balance.
    2. Check for class/interface/enum definition.
    3. If javalang is available, do a full AST parse.
    """
    if not code or not code.strip():
        return False, "EmptyCode: code is empty"

    # Layer 1: brace balance
    balanced, err = _check_brace_balance(code)
    if not balanced:
        return False, err

    # Layer 2: structural check
    if not _has_class_definition(code):
        return False, "MissingClass: no class/interface/enum definition found"

    # Layer 3: javalang full parse (best-effort)
    valid, err = _try_javalang_parse(code)
    if not valid:
        return False, err

    return True, None


def validate_single_java(args: Tuple[str, str, str]) -> Dict:
    """Validate a single Java program file.

    Args:
        args: (file_path, category, filename) tuple for pool.map.

    Returns:
        Dict with validation results for this file.
    """
    file_path, category, filename = args
    record = {
        "filename": filename,
        "category": category,
        "language": "java",
        "syntax_valid": False,
        "error": None,
        "execution": None,  # Java execution not attempted (needs javac)
    }

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        record["error"] = f"FileError: {str(e)}"
        return record

    code = data.get("output", "")
    if not code or not code.strip():
        record["error"] = "EmptyCode: output field is empty"
        return record

    is_valid, err = validate_java_syntax(code)
    record["syntax_valid"] = is_valid
    record["error"] = err

    return record


# ──────────────────────────────────────────────────────────────────────
# Dataset Enumeration
# ──────────────────────────────────────────────────────────────────────

def enumerate_dataset_files(
    dataset_root: str, categories: List[str]
) -> List[Tuple[str, str, str]]:
    """Collect all JSON files from a dataset directory.

    Returns:
        List of (file_path, category, filename) tuples.
    """
    files = []
    for category in categories:
        cat_dir = os.path.join(dataset_root, category)
        if not os.path.isdir(cat_dir):
            continue
        for fname in sorted(os.listdir(cat_dir)):
            if fname.endswith(".json"):
                files.append((os.path.join(cat_dir, fname), category, fname))
    return files


# ──────────────────────────────────────────────────────────────────────
# Core Validation Pipeline
# ──────────────────────────────────────────────────────────────────────

def validate_all_programs(
    num_workers: int = NUM_WORKERS,
) -> Dict:
    """Validate all Python and Java programs in the dataset.

    Uses multiprocessing to parallelize validation across files.

    Returns:
        The full validation result dict (also saved to ARTIFACTS_DIR).
    """
    t0 = time.time()
    print(f"[Validator] Starting validation with {num_workers} workers...")

    # Enumerate files
    python_files = enumerate_dataset_files(PYTHON_DATASET, DATASET_CATEGORIES)
    java_files = enumerate_dataset_files(JAVA_DATASET, DATASET_CATEGORIES)
    print(
        f"[Validator] Found {len(python_files)} Python files, "
        f"{len(java_files)} Java files"
    )

    # ── Validate Python ──────────────────────────────────────────────
    print("[Validator] Validating Python programs...")
    with Pool(processes=num_workers) as pool:
        python_results = pool.map(validate_single_python, python_files)

    # ── Validate Java ────────────────────────────────────────────────
    print("[Validator] Validating Java programs...")
    with Pool(processes=num_workers) as pool:
        java_results = pool.map(validate_single_java, java_files)

    # ── Aggregate ────────────────────────────────────────────────────
    output = _aggregate_results(python_results, java_results)
    output["metadata"] = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "num_workers": num_workers,
        "elapsed_seconds": round(time.time() - t0, 2),
        "random_seed": RANDOM_SEED,
    }

    # ── Save ─────────────────────────────────────────────────────────
    os.makedirs(ARTIFACTS_DIR, exist_ok=True)
    with open(VALIDATION_OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    print(f"[Validator] Results saved to {VALIDATION_OUTPUT_FILE}")

    return output


def _aggregate_results(
    python_results: List[Dict], java_results: List[Dict]
) -> Dict:
    """Build the output structure from individual validation records."""
    valid_python: Dict[str, List[str]] = {cat: [] for cat in DATASET_CATEGORIES}
    valid_java: Dict[str, List[str]] = {cat: [] for cat in DATASET_CATEGORIES}
    rejected_python: Dict[str, str] = {}
    rejected_java: Dict[str, str] = {}

    for rec in python_results:
        if rec["syntax_valid"]:
            valid_python[rec["category"]].append(rec["filename"])
        else:
            rejected_python[rec["filename"]] = rec["error"] or "UnknownError"

    for rec in java_results:
        if rec["syntax_valid"]:
            valid_java[rec["category"]].append(rec["filename"])
        else:
            rejected_java[rec["filename"]] = rec["error"] or "UnknownError"

    # Sort lists for deterministic output
    for cat in DATASET_CATEGORIES:
        valid_python[cat].sort()
        valid_java[cat].sort()

    py_valid = sum(len(v) for v in valid_python.values())
    java_valid = sum(len(v) for v in valid_java.values())
    py_rejected = len(rejected_python)
    java_rejected = len(rejected_java)

    return {
        "python": valid_python,
        "java": valid_java,
        "rejected": {
            "python": rejected_python,
            "java": rejected_java,
        },
        "stats": {
            "python_valid": py_valid,
            "java_valid": java_valid,
            "python_rejected": py_rejected,
            "java_rejected": java_rejected,
            "python_total": py_valid + py_rejected,
            "java_total": java_valid + java_rejected,
            "overall_valid": py_valid + java_valid,
            "overall_rejected": py_rejected + java_rejected,
            "overall_total": py_valid + java_valid + py_rejected + java_rejected,
        },
    }


# ──────────────────────────────────────────────────────────────────────
# Checkpoint Loading
# ──────────────────────────────────────────────────────────────────────

def load_validated_programs(
    path: str = VALIDATION_OUTPUT_FILE,
) -> Dict:
    """Load validated programs from the saved checkpoint.

    Args:
        path: Path to the validated_programs.json file.

    Returns:
        The validation dict, or an empty dict if the file doesn't exist.

    Raises:
        json.JSONDecodeError: If the file is corrupted.
    """
    if not os.path.isfile(path):
        print(
            f"[Validator] No checkpoint found at {path}. "
            "Run validate_all_programs() first."
        )
        return {}

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(
        f"[Validator] Loaded checkpoint: "
        f"{data.get('stats', {}).get('overall_valid', '?')} valid programs, "
        f"{data.get('stats', {}).get('overall_rejected', '?')} rejected"
    )
    return data


# ──────────────────────────────────────────────────────────────────────
# Pretty Printing
# ──────────────────────────────────────────────────────────────────────

def print_summary(results: Dict) -> None:
    """Print a human-readable summary of validation results."""
    stats = results.get("stats", {})
    rejected = results.get("rejected", {})

    print("\n" + "=" * 64)
    print("  PROGRAM VALIDATION SUMMARY")
    print("=" * 64)

    for lang in LANGUAGES:
        total = stats.get(f"{lang}_total", 0)
        valid = stats.get(f"{lang}_valid", 0)
        rej = stats.get(f"{lang}_rejected", 0)
        pct = (valid / total * 100) if total > 0 else 0
        print(f"\n  {lang.upper()}")
        print(f"    Total files:    {total}")
        print(f"    Valid:          {valid} ({pct:.1f}%)")
        print(f"    Rejected:       {rej}")
        if lang in results:
            for cat in DATASET_CATEGORIES:
                cat_count = len(results[lang].get(cat, []))
                print(f"      {cat}: {cat_count} valid")

    print(f"\n  OVERALL")
    print(f"    Total:          {stats.get('overall_total', 0)}")
    print(f"    Valid:          {stats.get('overall_valid', 0)}")
    print(f"    Rejected:       {stats.get('overall_rejected', 0)}")

    # Show a sample of rejections
    for lang in LANGUAGES:
        lang_rejected = rejected.get(lang, {})
        if lang_rejected:
            sample = dict(list(lang_rejected.items())[:5])
            print(f"\n  Sample {lang.upper()} rejections:")
            for fname, err in sample.items():
                print(f"    {fname}: {err[:80]}")
            if len(lang_rejected) > 5:
                print(f"    ... and {len(lang_rejected) - 5} more")

    meta = results.get("metadata", {})
    if meta:
        print(f"\n  Elapsed: {meta.get('elapsed_seconds', '?')}s")
        print(f"  Workers: {meta.get('num_workers', '?')}")
        print(f"  Timestamp: {meta.get('timestamp', '?')}")

    print("=" * 64 + "\n")


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────

def main():
    """Run validation on all programs and print summary."""
    results = validate_all_programs()
    print_summary(results)


if __name__ == "__main__":
    main()
