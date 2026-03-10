#!/usr/bin/env python3
"""Multi-backend LLM tester for agent evaluation experiment.

Supports OpenAI, Anthropic, and Ollama backends with a unified interface
for evaluating bug-detection accuracy across coding agents.

Usage:
    python -m agent_evaluation_experiment.unified_tester --model gpt-4o-mini --tasks-file tasks.json
    python -m agent_evaluation_experiment.unified_tester --model gpt-4o-mini --determinism-check --tasks-file tasks.json
    python -m agent_evaluation_experiment.unified_tester --model gpt-4o-mini --checkpoint results/checkpoints/gpt4omini_progress.json --tasks-file tasks.json
"""

import argparse
import json
import os
import random
import re
import sys
import tempfile
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_evaluation_experiment.config import (
    MODELS,
    PROMPT_VARIANTS,
    PRIMARY_PROMPT,
    LLM_TEMPERATURE,
    LINE_TOLERANCE_PRIMARY,
    LINE_TOLERANCE_SECONDARY,
    CHECKPOINT_BATCH_SIZE,
    CHECKPOINTS_DIR,
    RESULTS_DIR,
    DETERMINISM_SAMPLE_SIZE,
    DETERMINISM_REPETITIONS,
    DETERMINISM_THRESHOLD,
)

# ---------------------------------------------------------------------------
# Optional backend imports -- allow partial installs
# ---------------------------------------------------------------------------

try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    print(
        "Warning: openai package not installed. OpenAI backend unavailable. "
        "Install with: pip install openai",
        file=sys.stderr,
    )

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    print(
        "Warning: anthropic package not installed. Anthropic backend unavailable. "
        "Install with: pip install anthropic",
        file=sys.stderr,
    )

try:
    import requests as _requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    print(
        "Warning: requests package not installed. Ollama backend unavailable. "
        "Install with: pip install requests",
        file=sys.stderr,
    )


# ============================================================================
# Response parsing
# ============================================================================

def parse_llm_response(response_text: str) -> int:
    """Extract a line number from an LLM response.

    Handles the following formats (in priority order):
      1. Clean JSON:          {"line_no": 42}
      2. JSON with extra text: The bug is on... {"line_no": 42}
      3. Just a bare number:  42
      4. No valid content:    returns -1
    """
    if not response_text or not response_text.strip():
        return -1

    text = response_text.strip()

    # --- Attempt 1: find JSON object containing "line_no" -----------------
    # Scan for the outermost { ... } that contains "line_no"
    json_pattern = re.compile(r'\{[^{}]*"line_no"\s*:\s*(-?\d+)[^{}]*\}')
    match = json_pattern.search(text)
    if match:
        try:
            return int(match.group(1))
        except (ValueError, TypeError):
            pass

    # Also try a broader JSON parse in case there are nested braces or
    # slightly different formatting.
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end > brace_start:
        json_candidate = text[brace_start : brace_end + 1]
        try:
            parsed = json.loads(json_candidate)
            if isinstance(parsed, dict) and "line_no" in parsed:
                return int(parsed["line_no"])
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    # --- Attempt 2: bare integer ------------------------------------------
    bare_number = re.match(r"^\s*(\d+)\s*$", text)
    if bare_number:
        return int(bare_number.group(1))

    # --- Attempt 3: last integer in text ----------------------------------
    # Some models respond with prose and a single number; grab the last one
    # only if exactly one distinct number appears.
    numbers = re.findall(r"\b(\d+)\b", text)
    if len(numbers) == 1:
        return int(numbers[0])

    return -1


# ============================================================================
# Backend base class
# ============================================================================

class LLMBackend(ABC):
    """Abstract base class for LLM backends."""

    def __init__(self, model_id: str, temperature: float = 0):
        self.model_id = model_id
        self.temperature = temperature
        self.max_tokens = 100  # default, overridden for verbose prompts

    @abstractmethod
    def query(self, system_prompt: str, user_prompt: str) -> dict:
        """Send a prompt to the LLM and return a structured result.

        Returns
        -------
        dict
            {"line_no": int, "raw_response": str,
             "latency_ms": float, "error": str | None}
        """
        raise NotImplementedError


# ============================================================================
# OpenAI backend
# ============================================================================

class OpenAIBackend(LLMBackend):
    """Backend for OpenAI-compatible API (GPT-4o-mini, etc.)."""

    # Exponential backoff schedule (seconds)
    _BACKOFF_SCHEDULE = [1, 2, 4, 8, 16, 32, 60]

    def __init__(self, model_id: str, temperature: float = 0):
        super().__init__(model_id, temperature)
        if not OPENAI_AVAILABLE:
            raise RuntimeError(
                "openai package is not installed. Run: pip install openai"
            )
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY environment variable is not set.")
        self._client = openai.OpenAI(api_key=api_key)

    def query(self, system_prompt: str, user_prompt: str) -> dict:
        start_ms = time.monotonic() * 1000
        last_error: Optional[str] = None

        for attempt, wait in enumerate(self._BACKOFF_SCHEDULE):
            try:
                response = self._client.chat.completions.create(
                    model=self.model_id,
                    temperature=self.temperature,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                )
                raw = response.choices[0].message.content or ""
                latency = time.monotonic() * 1000 - start_ms
                return {
                    "line_no": parse_llm_response(raw),
                    "raw_response": raw,
                    "latency_ms": round(latency, 2),
                    "error": None,
                }
            except openai.RateLimitError as exc:
                last_error = f"RateLimitError (attempt {attempt + 1}): {exc}"
                time.sleep(wait)
            except openai.APIError as exc:
                last_error = f"APIError: {exc}"
                break
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                break

        latency = time.monotonic() * 1000 - start_ms
        return {
            "line_no": -1,
            "raw_response": "",
            "latency_ms": round(latency, 2),
            "error": last_error,
        }


# ============================================================================
# Anthropic backend
# ============================================================================

class AnthropicBackend(LLMBackend):
    """Backend for Anthropic API (Claude models)."""

    _BACKOFF_SCHEDULE = [1, 2, 4, 8, 16, 32, 60]

    def __init__(self, model_id: str, temperature: float = 0):
        super().__init__(model_id, temperature)
        if not ANTHROPIC_AVAILABLE:
            raise RuntimeError(
                "anthropic package is not installed. Run: pip install anthropic"
            )
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY environment variable is not set.")
        self._client = anthropic.Anthropic(api_key=api_key)

    def query(self, system_prompt: str, user_prompt: str) -> dict:
        start_ms = time.monotonic() * 1000
        last_error: Optional[str] = None

        for attempt, wait in enumerate(self._BACKOFF_SCHEDULE):
            try:
                response = self._client.messages.create(
                    model=self.model_id,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                )
                raw = response.content[0].text if response.content else ""
                latency = time.monotonic() * 1000 - start_ms
                return {
                    "line_no": parse_llm_response(raw),
                    "raw_response": raw,
                    "latency_ms": round(latency, 2),
                    "error": None,
                }
            except anthropic.RateLimitError as exc:
                last_error = f"RateLimitError (attempt {attempt + 1}): {exc}"
                time.sleep(wait)
            except anthropic.APIError as exc:
                last_error = f"APIError: {exc}"
                break
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                break

        latency = time.monotonic() * 1000 - start_ms
        return {
            "line_no": -1,
            "raw_response": "",
            "latency_ms": round(latency, 2),
            "error": last_error,
        }


# ============================================================================
# Ollama backend
# ============================================================================

class OllamaBackend(LLMBackend):
    """Backend for locally-running Ollama server."""

    OLLAMA_URL = "http://localhost:11434/api/generate"
    TIMEOUT_SECONDS = 30

    def __init__(self, model_id: str, temperature: float = 0):
        super().__init__(model_id, temperature)
        if not REQUESTS_AVAILABLE:
            raise RuntimeError(
                "requests package is not installed. Run: pip install requests"
            )

    def query(self, system_prompt: str, user_prompt: str) -> dict:
        start_ms = time.monotonic() * 1000

        payload = {
            "model": self.model_id,
            "prompt": user_prompt,
            "system": system_prompt,
            "stream": False,
            "options": {
                "temperature": self.temperature,
            },
        }

        try:
            resp = _requests.post(
                self.OLLAMA_URL,
                json=payload,
                timeout=self.TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            body = resp.json()
            raw = body.get("response", "")
            latency = time.monotonic() * 1000 - start_ms
            return {
                "line_no": parse_llm_response(raw),
                "raw_response": raw,
                "latency_ms": round(latency, 2),
                "error": None,
            }
        except _requests.exceptions.ConnectionError:
            latency = time.monotonic() * 1000 - start_ms
            return {
                "line_no": -1,
                "raw_response": "",
                "latency_ms": round(latency, 2),
                "error": "Ollama server not reachable at " + self.OLLAMA_URL,
            }
        except _requests.exceptions.Timeout:
            latency = time.monotonic() * 1000 - start_ms
            return {
                "line_no": -1,
                "raw_response": "",
                "latency_ms": round(latency, 2),
                "error": f"Ollama request timed out after {self.TIMEOUT_SECONDS}s",
            }
        except Exception as exc:
            latency = time.monotonic() * 1000 - start_ms
            return {
                "line_no": -1,
                "raw_response": "",
                "latency_ms": round(latency, 2),
                "error": f"{type(exc).__name__}: {exc}",
            }


# ============================================================================
# Backend factory
# ============================================================================

_BACKEND_MAP = {
    "openai": OpenAIBackend,
    "anthropic": AnthropicBackend,
    "ollama": OllamaBackend,
}


def get_backend(model_name: str) -> LLMBackend:
    """Create the appropriate LLMBackend for a model defined in MODELS config.

    Parameters
    ----------
    model_name : str
        Key in the ``MODELS`` dictionary from ``config.py``.

    Returns
    -------
    LLMBackend
        An instantiated backend ready for queries.
    """
    if model_name not in MODELS:
        available = ", ".join(sorted(MODELS.keys()))
        raise ValueError(
            f"Unknown model '{model_name}'. Available models: {available}"
        )

    cfg = MODELS[model_name]
    backend_type = cfg["backend"]
    model_id = cfg["model_id"]

    if backend_type not in _BACKEND_MAP:
        raise ValueError(
            f"Unknown backend type '{backend_type}' for model '{model_name}'. "
            f"Supported: {', '.join(_BACKEND_MAP.keys())}"
        )

    cls = _BACKEND_MAP[backend_type]
    return cls(model_id=model_id, temperature=LLM_TEMPERATURE)


# ============================================================================
# Single-sample evaluation
# ============================================================================

def evaluate_single(
    backend: LLMBackend,
    instruction: str,
    code: str,
    bug_line: int,
    bug_line_range: Optional[List[int]] = None,
    prompt_variant: str = "minimal",
) -> dict:
    """Evaluate a single code sample against a single LLM backend.

    Parameters
    ----------
    backend : LLMBackend
        The backend to query.
    instruction : str
        Natural-language description of what the code should do.
    code : str
        The buggy source code.
    bug_line : int
        The primary bug line number.
    bug_line_range : list[int] | None
        Optional list of additional acceptable line numbers (multi-line CWEs).
    prompt_variant : str
        Key into ``PROMPT_VARIANTS`` (default ``"minimal"``).

    Returns
    -------
    dict
        Result dictionary with prediction and correctness information.
    """
    if prompt_variant not in PROMPT_VARIANTS:
        raise ValueError(
            f"Unknown prompt variant '{prompt_variant}'. "
            f"Available: {', '.join(PROMPT_VARIANTS.keys())}"
        )

    variant = PROMPT_VARIANTS[prompt_variant]
    system_prompt = variant["system"]
    user_prompt = variant["user_template"].format(
        instruction=instruction, code=code
    )

    # Increase max_tokens for verbose prompt variants
    if prompt_variant in ("detailed", "chain_of_thought"):
        backend.max_tokens = 1000
    else:
        backend.max_tokens = 100

    response = backend.query(system_prompt, user_prompt)
    predicted = response["line_no"]

    # --- Tolerance-0 (exact match) ----------------------------------------
    correct_tol0 = predicted == bug_line
    if not correct_tol0 and bug_line_range:
        correct_tol0 = predicted in bug_line_range

    # --- Tolerance-2 (within +/- 2 lines) --------------------------------
    correct_tol2 = abs(predicted - bug_line) <= LINE_TOLERANCE_SECONDARY
    if not correct_tol2 and bug_line_range:
        correct_tol2 = any(
            abs(predicted - line) <= LINE_TOLERANCE_SECONDARY
            for line in bug_line_range
        )

    return {
        "predicted_line": predicted,
        "actual_line": bug_line,
        "actual_line_range": bug_line_range,
        "correct_tol0": correct_tol0,
        "correct_tol2": correct_tol2,
        "raw_response": response["raw_response"],
        "latency_ms": response["latency_ms"],
        "error": response["error"],
        "prompt_variant": prompt_variant,
    }


# ============================================================================
# Checkpoint helpers
# ============================================================================

def _load_checkpoint(checkpoint_file: str) -> dict:
    """Load an existing checkpoint, or return an empty structure."""
    if checkpoint_file and os.path.exists(checkpoint_file):
        try:
            with open(checkpoint_file, "r") as fh:
                data = json.load(fh)
            print(
                f"Loaded checkpoint: {len(data.get('completed_ids', []))} "
                f"tasks already completed."
            )
            return data
        except (json.JSONDecodeError, OSError) as exc:
            print(f"Warning: could not read checkpoint ({exc}). Starting fresh.")
    return {
        "model": "",
        "completed_ids": [],
        "results": [],
        "timestamp": "",
        "stats": {"total": 0, "correct_tol0": 0, "correct_tol2": 0},
    }


def _save_checkpoint(checkpoint_file: str, checkpoint_data: dict) -> None:
    """Atomically save checkpoint to disk (write-to-temp then rename)."""
    checkpoint_data["timestamp"] = datetime.now().isoformat()
    dir_name = os.path.dirname(checkpoint_file) or "."
    os.makedirs(dir_name, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        suffix=".tmp", prefix="ckpt_", dir=dir_name
    )
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(checkpoint_data, fh, indent=2)
        os.replace(tmp_path, checkpoint_file)
    except BaseException:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ============================================================================
# Batch evaluation
# ============================================================================

def run_batch_evaluation(
    backend: LLMBackend,
    tasks: List[Dict[str, Any]],
    model_name: str,
    checkpoint_file: Optional[str] = None,
    prompt_variant: str = "minimal",
    max_workers: int = 1,
) -> List[dict]:
    """Evaluate a batch of tasks with checkpointing and progress reporting.

    Parameters
    ----------
    backend : LLMBackend
        Instantiated backend.
    tasks : list[dict]
        Each dict must contain: ``id``, ``instruction``, ``code``,
        ``bug_line``, and optionally ``bug_line_range`` and ``metadata``.
    model_name : str
        Human-readable model name (for display and checkpoint metadata).
    checkpoint_file : str | None
        Path to checkpoint file. If ``None``, no checkpointing is performed.
    prompt_variant : str
        Prompt variant key.
    max_workers : int
        Number of concurrent evaluation threads (default 1 = sequential).
        Use >1 for local models like Ollama with OLLAMA_NUM_PARALLEL set.

    Returns
    -------
    list[dict]
        One result dict per task (see ``evaluate_single`` for schema, plus
        ``task_id`` and ``metadata`` fields).
    """
    # --- Load or initialise checkpoint ------------------------------------
    ckpt = _load_checkpoint(checkpoint_file) if checkpoint_file else {
        "model": model_name,
        "completed_ids": [],
        "results": [],
        "timestamp": "",
        "stats": {"total": 0, "correct_tol0": 0, "correct_tol2": 0},
    }
    ckpt["model"] = model_name

    completed_ids = set(ckpt["completed_ids"])
    results: List[dict] = list(ckpt["results"])

    total = len(tasks)

    # Filter to pending tasks only
    pending_tasks = [t for t in tasks if t["id"] not in completed_ids]
    skipped = total - len(pending_tasks)

    if skipped:
        print(f"Skipped {skipped} already-completed tasks from checkpoint.")

    if max_workers <= 1:
        # Sequential mode (original behavior)
        _run_sequential(
            backend, pending_tasks, model_name, prompt_variant,
            results, completed_ids, ckpt, checkpoint_file, total,
        )
    else:
        # Concurrent mode
        print(f"Running with {max_workers} concurrent workers", flush=True)
        _run_concurrent(
            backend, pending_tasks, model_name, prompt_variant,
            results, completed_ids, ckpt, checkpoint_file, total,
            max_workers,
        )

    # Final save
    ckpt["completed_ids"] = list(completed_ids)
    ckpt["results"] = results
    if checkpoint_file:
        _save_checkpoint(checkpoint_file, ckpt)

    return results


def _run_sequential(
    backend, pending_tasks, model_name, prompt_variant,
    results, completed_ids, ckpt, checkpoint_file, total,
):
    """Original sequential evaluation loop."""
    batch_counter = 0

    for idx, task in enumerate(pending_tasks):
        task_id = task["id"]
        result = evaluate_single(
            backend=backend,
            instruction=task["instruction"],
            code=task["code"],
            bug_line=task["bug_line"],
            bug_line_range=task.get("bug_line_range"),
            prompt_variant=prompt_variant,
        )
        result["task_id"] = task_id
        result["metadata"] = task.get("metadata", {})

        results.append(result)
        completed_ids.add(task_id)
        batch_counter += 1

        ckpt["stats"]["total"] = len(results)
        if result["correct_tol0"]:
            ckpt["stats"]["correct_tol0"] += 1
        if result["correct_tol2"]:
            ckpt["stats"]["correct_tol2"] += 1

        status = "\u2713" if result["correct_tol0"] else "\u2717"
        processed = len(results)
        print(
            f"[{processed}/{total}] {model_name} {status} "
            f"actual={result['actual_line']} pred={result['predicted_line']}"
            + (f"  err={result['error']}" if result["error"] else ""),
            flush=True,
        )

        if batch_counter >= CHECKPOINT_BATCH_SIZE:
            ckpt["completed_ids"] = list(completed_ids)
            ckpt["results"] = results
            if checkpoint_file:
                _save_checkpoint(checkpoint_file, ckpt)
            stats = ckpt["stats"]
            t = stats["total"]
            acc0 = stats["correct_tol0"] / t * 100 if t else 0
            acc2 = stats["correct_tol2"] / t * 100 if t else 0
            print(
                f"  [Running accuracy: tol0={acc0:.1f}% tol2={acc2:.1f}% "
                f"({processed}/{total})]",
                flush=True,
            )
            batch_counter = 0


def _run_concurrent(
    backend, pending_tasks, model_name, prompt_variant,
    results, completed_ids, ckpt, checkpoint_file, total,
    max_workers,
):
    """Concurrent evaluation using ThreadPoolExecutor."""
    import threading

    lock = threading.Lock()
    batch_counter = 0

    def _eval_task(task):
        return task, evaluate_single(
            backend=backend,
            instruction=task["instruction"],
            code=task["code"],
            bug_line=task["bug_line"],
            bug_line_range=task.get("bug_line_range"),
            prompt_variant=prompt_variant,
        )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_eval_task, task): task
            for task in pending_tasks
        }

        for future in as_completed(futures):
            try:
                task, result = future.result()
            except Exception as exc:
                task = futures[future]
                result = {
                    "predicted_line": -1,
                    "actual_line": task["bug_line"],
                    "correct_tol0": False,
                    "correct_tol2": False,
                    "raw_response": "",
                    "latency_ms": 0,
                    "error": f"{type(exc).__name__}: {exc}",
                    "prompt_variant": prompt_variant,
                }

            task_id = task["id"]
            result["task_id"] = task_id
            result["metadata"] = task.get("metadata", {})

            with lock:
                results.append(result)
                completed_ids.add(task_id)
                batch_counter_local = len(results) - (ckpt["stats"].get("_last_save", 0))

                ckpt["stats"]["total"] = len(results)
                if result["correct_tol0"]:
                    ckpt["stats"]["correct_tol0"] = ckpt["stats"].get("correct_tol0", 0) + 1
                if result["correct_tol2"]:
                    ckpt["stats"]["correct_tol2"] = ckpt["stats"].get("correct_tol2", 0) + 1

                processed = len(results)
                status = "\u2713" if result["correct_tol0"] else "\u2717"
                print(
                    f"[{processed}/{total}] {model_name} {status} "
                    f"actual={result['actual_line']} pred={result['predicted_line']}"
                    + (f"  err={result['error']}" if result["error"] else ""),
                    flush=True,
                )

                if batch_counter_local >= CHECKPOINT_BATCH_SIZE:
                    ckpt["completed_ids"] = list(completed_ids)
                    ckpt["results"] = results
                    ckpt["stats"]["_last_save"] = len(results)
                    if checkpoint_file:
                        _save_checkpoint(checkpoint_file, ckpt)
                    stats = ckpt["stats"]
                    t = stats["total"]
                    acc0 = stats["correct_tol0"] / t * 100 if t else 0
                    acc2 = stats["correct_tol2"] / t * 100 if t else 0
                    print(
                        f"  [Running accuracy: tol0={acc0:.1f}% tol2={acc2:.1f}% "
                        f"({processed}/{total})]",
                        flush=True,
                    )


# ============================================================================
# Determinism check
# ============================================================================

def run_determinism_check(
    backend: LLMBackend,
    tasks: List[Dict[str, Any]],
    model_name: str,
    sample_size: int = DETERMINISM_SAMPLE_SIZE,
    repetitions: int = DETERMINISM_REPETITIONS,
    prompt_variant: str = "minimal",
) -> dict:
    """Check response determinism by running a subset of tasks multiple times.

    Parameters
    ----------
    backend : LLMBackend
        Instantiated backend.
    tasks : list[dict]
        Full task list to sample from.
    model_name : str
        Model name for reporting.
    sample_size : int
        Number of tasks to sample.
    repetitions : int
        How many times to evaluate each sampled task.
    prompt_variant : str
        Prompt variant key.

    Returns
    -------
    dict
        Determinism report including consistency rate and recommendation.
    """
    actual_sample = min(sample_size, len(tasks))
    sampled = random.sample(tasks, actual_sample)

    details: List[dict] = []
    consistent_count = 0
    total_queries = actual_sample * repetitions

    print(f"\nDeterminism check: {actual_sample} tasks x {repetitions} repetitions "
          f"= {total_queries} queries")
    print("-" * 60)

    for i, task in enumerate(sampled):
        responses: List[int] = []
        for rep in range(repetitions):
            result = evaluate_single(
                backend=backend,
                instruction=task["instruction"],
                code=task["code"],
                bug_line=task["bug_line"],
                bug_line_range=task.get("bug_line_range"),
                prompt_variant=prompt_variant,
            )
            responses.append(result["predicted_line"])

        is_consistent = len(set(responses)) == 1
        if is_consistent:
            consistent_count += 1

        details.append({
            "task_id": task["id"],
            "responses": responses,
            "consistent": is_consistent,
        })

        status = "consistent" if is_consistent else f"INCONSISTENT {responses}"
        print(
            f"[{i + 1}/{actual_sample}] {task['id']}: {status}",
            flush=True,
        )

    consistency_rate = (
        consistent_count / actual_sample if actual_sample > 0 else 0.0
    )
    recommendation = (
        "single_run" if consistency_rate >= DETERMINISM_THRESHOLD else "majority_vote"
    )

    print("-" * 60)
    print(
        f"Consistency: {consistency_rate * 100:.1f}% "
        f"({consistent_count}/{actual_sample})"
    )
    print(f"Recommendation: {recommendation}")

    return {
        "model": model_name,
        "sample_size": actual_sample,
        "repetitions": repetitions,
        "consistency_rate": round(consistency_rate, 4),
        "consistent_count": consistent_count,
        "details": details,
        "recommendation": recommendation,
    }


# ============================================================================
# Statistics
# ============================================================================

def calculate_stats(results: List[dict]) -> dict:
    """Calculate accuracy statistics from a list of evaluation results.

    Parameters
    ----------
    results : list[dict]
        Output of ``run_batch_evaluation`` or accumulated ``evaluate_single``
        results.

    Returns
    -------
    dict
        Aggregate accuracy metrics, broken down by bug_type, language, and
        category where metadata is available.
    """
    total = len(results)
    if total == 0:
        return {
            "total": 0,
            "correct_tol0": 0,
            "correct_tol2": 0,
            "accuracy_tol0": 0.0,
            "accuracy_tol2": 0.0,
            "errors": 0,
            "avg_latency_ms": 0.0,
            "by_bug_type": {},
            "by_language": {},
            "by_category": {},
        }

    correct_tol0 = sum(1 for r in results if r.get("correct_tol0"))
    correct_tol2 = sum(1 for r in results if r.get("correct_tol2"))
    errors = sum(1 for r in results if r.get("error"))
    latencies = [r["latency_ms"] for r in results if r.get("latency_ms")]
    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

    def _group_stats(results: List[dict], key: str) -> dict:
        """Build per-group accuracy stats based on a metadata key."""
        groups: Dict[str, Dict[str, int]] = {}
        for r in results:
            val = r.get("metadata", {}).get(key, "unknown")
            if val not in groups:
                groups[val] = {"total": 0, "correct_tol0": 0, "correct_tol2": 0}
            groups[val]["total"] += 1
            if r.get("correct_tol0"):
                groups[val]["correct_tol0"] += 1
            if r.get("correct_tol2"):
                groups[val]["correct_tol2"] += 1

        # Add accuracy percentages
        for g in groups.values():
            t = g["total"]
            g["accuracy_tol0"] = round(g["correct_tol0"] / t * 100, 2) if t else 0.0
            g["accuracy_tol2"] = round(g["correct_tol2"] / t * 100, 2) if t else 0.0
        return groups

    return {
        "total": total,
        "correct_tol0": correct_tol0,
        "correct_tol2": correct_tol2,
        "accuracy_tol0": round(correct_tol0 / total * 100, 2),
        "accuracy_tol2": round(correct_tol2 / total * 100, 2),
        "errors": errors,
        "avg_latency_ms": round(avg_latency, 2),
        "by_bug_type": _group_stats(results, "bug_type"),
        "by_language": _group_stats(results, "language"),
        "by_category": _group_stats(results, "category"),
    }


# ============================================================================
# CLI
# ============================================================================

def _load_tasks(tasks_file: str, max_tasks: Optional[int] = None) -> List[dict]:
    """Load tasks from a JSON file and optionally limit the count."""
    with open(tasks_file, "r") as fh:
        tasks = json.load(fh)
    if not isinstance(tasks, list):
        raise ValueError("Tasks file must contain a JSON array of task objects.")
    for i, t in enumerate(tasks):
        if "id" not in t:
            raise ValueError(f"Task at index {i} is missing required 'id' field.")
        for field in ("instruction", "code", "bug_line"):
            if field not in t:
                raise ValueError(
                    f"Task '{t['id']}' is missing required field '{field}'."
                )
    if max_tasks is not None and max_tasks > 0:
        tasks = tasks[:max_tasks]
    return tasks


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Unified multi-backend LLM tester for bug-detection evaluation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--model",
        required=True,
        help=f"Model name from config. Available: {', '.join(sorted(MODELS.keys()))}",
    )
    parser.add_argument(
        "--tasks-file",
        required=True,
        help="Path to JSON file containing the task list.",
    )
    parser.add_argument(
        "--checkpoint",
        default=None,
        help="Path to checkpoint file (for resuming interrupted runs).",
    )
    parser.add_argument(
        "--determinism-check",
        action="store_true",
        help="Run determinism check instead of full evaluation.",
    )
    parser.add_argument(
        "--prompt-variant",
        default=PRIMARY_PROMPT,
        choices=list(PROMPT_VARIANTS.keys()),
        help=f"Prompt variant to use (default: {PRIMARY_PROMPT}).",
    )
    parser.add_argument(
        "--max-tasks",
        type=int,
        default=None,
        help="Limit number of tasks (useful for quick tests).",
    )

    args = parser.parse_args()

    # --- Validate model ---------------------------------------------------
    if args.model not in MODELS:
        print(
            f"Error: unknown model '{args.model}'. "
            f"Available: {', '.join(sorted(MODELS.keys()))}",
            file=sys.stderr,
        )
        sys.exit(1)

    # --- Load tasks -------------------------------------------------------
    print(f"Loading tasks from: {args.tasks_file}")
    try:
        tasks = _load_tasks(args.tasks_file, args.max_tasks)
    except (OSError, ValueError) as exc:
        print(f"Error loading tasks: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"Loaded {len(tasks)} tasks.")

    # --- Create backend ---------------------------------------------------
    print(f"Initialising backend for model: {args.model}")
    try:
        backend = get_backend(args.model)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    model_cfg = MODELS[args.model]
    print(
        f"Backend: {model_cfg['backend']} | "
        f"Model ID: {model_cfg['model_id']} | "
        f"Temperature: {LLM_TEMPERATURE}"
    )
    print("=" * 70)

    # --- Determinism check ------------------------------------------------
    if args.determinism_check:
        report = run_determinism_check(
            backend=backend,
            tasks=tasks,
            model_name=args.model,
            prompt_variant=args.prompt_variant,
        )
        # Save report
        report_file = os.path.join(
            RESULTS_DIR,
            f"determinism_{args.model}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
        )
        os.makedirs(RESULTS_DIR, exist_ok=True)
        with open(report_file, "w") as fh:
            json.dump(report, fh, indent=2)
        print(f"\nDeterminism report saved to: {report_file}")
        return

    # --- Full evaluation --------------------------------------------------
    checkpoint_file = args.checkpoint
    if checkpoint_file is None:
        # Auto-generate checkpoint path
        safe_name = args.model.replace("/", "_").replace(":", "_")
        checkpoint_file = os.path.join(
            CHECKPOINTS_DIR,
            f"{safe_name}_{args.prompt_variant}_checkpoint.json",
        )
    print(f"Checkpoint file: {checkpoint_file}")

    results = run_batch_evaluation(
        backend=backend,
        tasks=tasks,
        model_name=args.model,
        checkpoint_file=checkpoint_file,
        prompt_variant=args.prompt_variant,
    )

    # --- Report -----------------------------------------------------------
    stats = calculate_stats(results)

    print("\n" + "=" * 70)
    print(f"RESULTS: {args.model} ({args.prompt_variant} prompt)")
    print("=" * 70)
    print(f"Total:          {stats['total']}")
    print(f"Correct (tol0): {stats['correct_tol0']}  ({stats['accuracy_tol0']:.2f}%)")
    print(f"Correct (tol2): {stats['correct_tol2']}  ({stats['accuracy_tol2']:.2f}%)")
    print(f"Errors:         {stats['errors']}")
    print(f"Avg latency:    {stats['avg_latency_ms']:.1f} ms")

    if stats["by_bug_type"]:
        print("\nBy bug type:")
        for bt, s in sorted(stats["by_bug_type"].items()):
            print(
                f"  {bt:40s} tol0={s['accuracy_tol0']:5.1f}%  "
                f"tol2={s['accuracy_tol2']:5.1f}%  (n={s['total']})"
            )

    if stats["by_language"]:
        print("\nBy language:")
        for lang, s in sorted(stats["by_language"].items()):
            print(
                f"  {lang:40s} tol0={s['accuracy_tol0']:5.1f}%  "
                f"tol2={s['accuracy_tol2']:5.1f}%  (n={s['total']})"
            )

    if stats["by_category"]:
        print("\nBy category:")
        for cat, s in sorted(stats["by_category"].items()):
            print(
                f"  {cat:40s} tol0={s['accuracy_tol0']:5.1f}%  "
                f"tol2={s['accuracy_tol2']:5.1f}%  (n={s['total']})"
            )

    # Save final results
    safe_name = args.model.replace("/", "_").replace(":", "_")
    results_file = os.path.join(
        RESULTS_DIR,
        f"eval_{safe_name}_{args.prompt_variant}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
    )
    os.makedirs(RESULTS_DIR, exist_ok=True)
    output = {
        "model": args.model,
        "model_id": model_cfg["model_id"],
        "backend": model_cfg["backend"],
        "prompt_variant": args.prompt_variant,
        "temperature": LLM_TEMPERATURE,
        "timestamp": datetime.now().isoformat(),
        "stats": stats,
        "results": results,
    }
    with open(results_file, "w") as fh:
        json.dump(output, fh, indent=2)
    print(f"\nFull results saved to: {results_file}")


if __name__ == "__main__":
    main()
