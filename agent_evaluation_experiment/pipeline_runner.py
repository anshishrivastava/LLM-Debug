#!/usr/bin/env python3
"""Pipeline runner for the Agent Evaluation Experiment.

Orchestrates the full experiment flow:
    Phase 0: Validate programs
    Phase 1: Inject SAMs (legacy + CWE)
    Phase 2: Apply SPMs to buggy programs
    Phase 3: Build evaluation task list
    Phase 4: Run determinism check
    Phase 5: Run LLM evaluations (all models concurrently)
    Phase 6: Aggregate results + statistical analysis

Supports checkpointing at every phase — resume from any failure point.

Usage:
    python -m agent_evaluation_experiment.pipeline_runner --all
    python -m agent_evaluation_experiment.pipeline_runner --phase validate
    python -m agent_evaluation_experiment.pipeline_runner --phase inject
    python -m agent_evaluation_experiment.pipeline_runner --phase spm
    python -m agent_evaluation_experiment.pipeline_runner --phase tasks
    python -m agent_evaluation_experiment.pipeline_runner --phase determinism
    python -m agent_evaluation_experiment.pipeline_runner --phase evaluate --model gpt-4o-mini
    python -m agent_evaluation_experiment.pipeline_runner --phase aggregate
"""

import argparse
import json
import os
import random
import sys
import time
import hashlib
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from multiprocessing import cpu_count
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_evaluation_experiment.config import (
    RANDOM_SEED,
    PROJECT_ROOT,
    EXPERIMENT_ROOT,
    JAVA_DATASET,
    PYTHON_DATASET,
    BUGGY_DATASETS_DIR,
    RESULTS_DIR,
    CHECKPOINTS_DIR,
    MUTATED_DIR,
    ARTIFACTS_DIR,
    DATASET_CATEGORIES,
    LANGUAGES,
    LEGACY_BUG_TYPES,
    CWE_BUG_TYPES,
    CWE_LANGUAGE_SUPPORT,
    BUG_TYPES,
    SPM_TYPES,
    EXISTING_SPM_TYPES,
    NEW_SPM_TYPES,
    MUTATION_STRENGTHS,
    LINE_TOLERANCE_PRIMARY,
    LINE_TOLERANCE_SECONDARY,
    MODELS,
    PROMPT_VARIANTS,
    PRIMARY_PROMPT,
    LLM_TEMPERATURE,
    CHECKPOINT_BATCH_SIZE,
    CONTROL_ARM_ENABLED,
    PROMPT_SENSITIVITY_SUBSET_SIZE,
)


# ======================================================================
# Checkpoint helpers
# ======================================================================

def _checkpoint_path(name: str) -> str:
    return os.path.join(CHECKPOINTS_DIR, f"{name}_checkpoint.json")


def _save_checkpoint(name: str, data: dict) -> None:
    """Atomically save a checkpoint file."""
    path = _checkpoint_path(name)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)
    print(f"  [Checkpoint saved: {name}]")


def _load_checkpoint(name: str) -> Optional[dict]:
    """Load a checkpoint if it exists."""
    path = _checkpoint_path(name)
    if not os.path.isfile(path):
        return None
    with open(path, "r") as f:
        data = json.load(f)
    print(f"  [Checkpoint loaded: {name}]")
    return data


def _task_id(language: str, category: str, filename: str,
             bug_type: str, spm_type: str = "none",
             strength: int = 0) -> str:
    """Generate a deterministic task ID."""
    raw = f"{language}|{category}|{filename}|{bug_type}|{spm_type}|{strength}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


# ======================================================================
# Phase 0: Validate Programs
# ======================================================================

def phase_validate(force: bool = False) -> dict:
    """Validate all programs in the dataset."""
    print("\n" + "=" * 60)
    print("  PHASE 0: PROGRAM VALIDATION")
    print("=" * 60)

    from agent_evaluation_experiment.program_validator import (
        validate_all_programs,
        load_validated_programs,
        print_summary,
    )

    if not force:
        existing = load_validated_programs()
        if existing:
            print("  Using existing validation checkpoint.")
            return existing

    results = validate_all_programs()
    print_summary(results)
    return results


# ======================================================================
# Phase 1: Inject SAMs (bugs)
# ======================================================================

def phase_inject(validated: dict, force: bool = False) -> dict:
    """Inject all SAM types (legacy + CWE) into validated programs."""
    print("\n" + "=" * 60)
    print("  PHASE 1: SAM INJECTION (Bug Injection)")
    print("=" * 60)

    ckpt = _load_checkpoint("injection")
    if ckpt and not force:
        print(f"  Resuming from checkpoint: {len(ckpt.get('completed', []))} combinations done")
    else:
        ckpt = {"completed": [], "stats": {}, "timestamp": None}

    from agent_evaluation_experiment.bug_injector import BUG_INJECTORS, process_dataset
    from agent_evaluation_experiment.cwe_bug_injector import CWE_INJECTORS, process_cwe_dataset

    all_stats = ckpt["stats"]
    completed = set(ckpt["completed"])

    for language in LANGUAGES:
        dataset_base = PYTHON_DATASET if language == "python" else JAVA_DATASET

        for category in DATASET_CATEGORIES:
            input_dir = os.path.join(dataset_base, category)
            if not os.path.exists(input_dir):
                print(f"  Skipping {input_dir} — does not exist")
                continue

            # --- Legacy SAMs ---
            for bug_type in LEGACY_BUG_TYPES:
                key = f"{language}_{category}_{bug_type}"
                if key in completed:
                    continue

                if bug_type not in BUG_INJECTORS.get(language, {}):
                    continue

                output_dir = os.path.join(BUGGY_DATASETS_DIR, key)
                print(f"  Injecting: {key}")
                stats = process_dataset(input_dir, output_dir, language, bug_type)
                all_stats[key] = stats
                completed.add(key)

                ckpt["completed"] = list(completed)
                ckpt["stats"] = all_stats
                ckpt["timestamp"] = datetime.now().isoformat()
                _save_checkpoint("injection", ckpt)

            # --- CWE SAMs ---
            for bug_type in CWE_BUG_TYPES:
                key = f"{language}_{category}_{bug_type}"
                if key in completed:
                    continue

                supported = CWE_LANGUAGE_SUPPORT.get(bug_type, [])
                if language not in supported:
                    continue

                output_dir = os.path.join(BUGGY_DATASETS_DIR, key)
                print(f"  Injecting: {key}")
                stats = process_cwe_dataset(input_dir, output_dir, language, bug_type)
                all_stats[key] = stats
                completed.add(key)

                ckpt["completed"] = list(completed)
                ckpt["stats"] = all_stats
                ckpt["timestamp"] = datetime.now().isoformat()
                _save_checkpoint("injection", ckpt)

    # Print summary
    total_success = sum(s.get("success", 0) for s in all_stats.values())
    total_total = sum(s.get("total", 0) for s in all_stats.values())
    print(f"\n  Injection complete: {total_success} buggy variants from {total_total} attempts")

    return ckpt


# ======================================================================
# Phase 2: Apply SPMs to buggy programs
# ======================================================================

def _apply_spm_to_file(args: tuple) -> dict:
    """Worker function for parallel SPM application."""
    buggy_file, spm_type, strength, language, seed = args

    from agent_evaluation_experiment.spm_generator import (
        apply_spm_by_type,
        verify_spm_equivalence,
    )

    try:
        with open(buggy_file, "r") as f:
            data = json.load(f)
    except Exception as e:
        return {"status": "error", "error": str(e), "file": buggy_file}

    buggy_code = data.get("buggy_code", "")
    bug_line = data.get("line_no", 0)

    if not buggy_code or bug_line <= 0:
        return {"status": "skip", "file": buggy_file}

    try:
        spm_code, spm_bug_line = apply_spm_by_type(
            spm_type, buggy_code, bug_line,
            language=language, strength=strength, seed=seed,
        )
    except Exception as e:
        return {"status": "error", "error": str(e), "file": buggy_file}

    if spm_code is None:
        return {"status": "skip", "file": buggy_file, "reason": "SPM not applicable"}

    # Verify equivalence (for Python only; Java does syntax check)
    equiv = verify_spm_equivalence(buggy_code, spm_code, language)

    # Build output record
    output_data = {
        **data,
        "spm_code": spm_code,
        "spm_bug_line": spm_bug_line,
        "spm_type": spm_type,
        "spm_strength": strength,
        "spm_equivalent": equiv["equivalent"],
        "spm_equiv_reason": equiv["reason"],
        "original_buggy_code": buggy_code,
        "original_bug_line": bug_line,
    }

    return {"status": "ok", "data": output_data, "file": buggy_file}


def phase_spm(force: bool = False) -> dict:
    """Apply all SPMs to all buggy programs."""
    print("\n" + "=" * 60)
    print("  PHASE 2: SPM APPLICATION")
    print("=" * 60)

    ckpt = _load_checkpoint("spm")
    if ckpt and not force:
        print(f"  Resuming: {ckpt.get('total_processed', 0)} files already processed")
    else:
        ckpt = {"completed_keys": [], "stats": {}, "total_processed": 0, "timestamp": None}

    completed_keys = set(ckpt.get("completed_keys", []))
    spm_stats = ckpt.get("stats", {})

    # Discover all buggy dataset directories
    if not os.path.isdir(BUGGY_DATASETS_DIR):
        print("  No buggy datasets found. Run phase_inject first.")
        return ckpt

    buggy_dirs = sorted(os.listdir(BUGGY_DATASETS_DIR))
    total_spm_tasks = 0
    batch_tasks = []

    for buggy_dir_name in buggy_dirs:
        buggy_dir_path = os.path.join(BUGGY_DATASETS_DIR, buggy_dir_name)
        if not os.path.isdir(buggy_dir_path):
            continue

        # Parse language from dir name (e.g., "python_existing_CWE-480_IncorrectOperator")
        parts = buggy_dir_name.split("_", 2)
        if len(parts) < 3:
            continue
        language = parts[0]
        if language not in LANGUAGES:
            continue

        # List buggy files
        buggy_files = [
            os.path.join(buggy_dir_path, f)
            for f in sorted(os.listdir(buggy_dir_path))
            if f.endswith(".json")
        ]

        for spm_type in SPM_TYPES:
            for strength in MUTATION_STRENGTHS:
                for bf in buggy_files:
                    key = f"{buggy_dir_name}|{spm_type}|{strength}|{os.path.basename(bf)}"
                    if key in completed_keys:
                        continue
                    batch_tasks.append((bf, spm_type, strength, language, RANDOM_SEED))
                    total_spm_tasks += 1

    print(f"  SPM tasks to process: {total_spm_tasks}")
    if total_spm_tasks == 0:
        print("  Nothing to do.")
        return ckpt

    # Process in parallel batches
    num_workers = max(1, cpu_count() - 1)
    batch_size = 500
    processed = 0
    ok_count = 0
    skip_count = 0
    err_count = 0

    os.makedirs(MUTATED_DIR, exist_ok=True)

    for batch_start in range(0, len(batch_tasks), batch_size):
        batch = batch_tasks[batch_start:batch_start + batch_size]

        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            futures = {executor.submit(_apply_spm_to_file, t): t for t in batch}

            for future in as_completed(futures):
                task_args = futures[future]
                bf, spm_type, strength, language, seed = task_args
                key = (
                    f"{os.path.basename(os.path.dirname(bf))}|"
                    f"{spm_type}|{strength}|{os.path.basename(bf)}"
                )

                try:
                    result = future.result()
                except Exception as e:
                    err_count += 1
                    result = {"status": "error", "error": str(e)}

                if result["status"] == "ok":
                    # Save SPM'd file
                    out_dir_name = (
                        f"{os.path.basename(os.path.dirname(bf))}"
                        f"__{spm_type}_s{strength}"
                    )
                    out_dir = os.path.join(MUTATED_DIR, out_dir_name)
                    os.makedirs(out_dir, exist_ok=True)
                    out_path = os.path.join(out_dir, os.path.basename(bf))
                    with open(out_path, "w") as f:
                        json.dump(result["data"], f, indent=2)
                    ok_count += 1
                elif result["status"] == "skip":
                    skip_count += 1
                else:
                    err_count += 1

                completed_keys.add(key)
                processed += 1

        # Checkpoint after each batch
        ckpt["completed_keys"] = list(completed_keys)
        ckpt["total_processed"] = len(completed_keys)
        ckpt["stats"] = {"ok": ok_count, "skip": skip_count, "error": err_count}
        ckpt["timestamp"] = datetime.now().isoformat()
        _save_checkpoint("spm", ckpt)
        print(f"  Progress: {processed}/{total_spm_tasks} "
              f"(ok={ok_count}, skip={skip_count}, err={err_count})")

    print(f"\n  SPM application complete: {ok_count} variants created, "
          f"{skip_count} skipped, {err_count} errors")
    return ckpt


# ======================================================================
# Stratified subsetting (preserves McNemar pairing)
# ======================================================================

def _stratified_subset(tasks: List[dict], subset_size: int, rng: random.Random) -> List[dict]:
    """Subsample tasks while preserving baseline-degraded pairs for McNemar's test.

    Strategy:
    1. Sample source_file|bug_type pairs (each pair has 1 baseline + N degraded)
    2. Include ALL tasks for sampled pairs (baseline + all its degraded variants)
    3. Include proportional control tasks
    This ensures every baseline has matching degraded tasks for paired analysis.
    """
    from collections import defaultdict

    # Group tasks by their pairing key (source_file|bug_type)
    pair_groups = defaultdict(list)  # key -> [tasks]
    control_tasks = []
    for t in tasks:
        meta = t.get("metadata", {})
        task_type = meta.get("task_type", "unknown")
        if task_type == "control":
            control_tasks.append(t)
        else:
            pair_key = f"{meta.get('source_file', '')}|{meta.get('bug_type', '')}"
            pair_groups[pair_key].append(t)

    # Compute average tasks per pair group
    pair_keys = list(pair_groups.keys())
    rng.shuffle(pair_keys)

    # Greedily add pair groups until we approach subset_size
    # Reserve ~5% for control tasks
    control_budget = max(10, int(subset_size * 0.05))
    task_budget = subset_size - min(control_budget, len(control_tasks))

    selected_tasks = []
    for key in pair_keys:
        group = pair_groups[key]
        if len(selected_tasks) + len(group) > task_budget:
            # Check if we have at least some baseline-degraded pairs
            if len(selected_tasks) > 0:
                break
        selected_tasks.extend(group)

    # Add control tasks
    rng.shuffle(control_tasks)
    selected_tasks.extend(control_tasks[:control_budget])

    return selected_tasks


# ======================================================================
# Phase 3: Build evaluation task list
# ======================================================================

def phase_build_tasks(model_name: str = None, force: bool = False) -> List[dict]:
    """Build the evaluation task list from injected + SPM'd programs.

    Creates tasks for:
    1. Baseline: SAM-only (buggy code, no SPM)
    2. Degraded: SAM+SPM (buggy code + SPM applied)
    3. Control: Clean code (no SAM, no SPM) — false positive test
    4. Control+SPM: Clean code + SPM — false positive test
    """
    print("\n" + "=" * 60)
    print("  PHASE 3: BUILD EVALUATION TASKS")
    print("=" * 60)

    ckpt_name = f"tasks_{model_name}" if model_name else "tasks_all"
    ckpt = _load_checkpoint(ckpt_name)
    if ckpt and not force:
        tasks = ckpt.get("tasks", [])
        print(f"  Loaded {len(tasks)} tasks from checkpoint")
        return tasks

    tasks = []
    rng = random.Random(RANDOM_SEED)

    # --- 1. Baseline tasks (SAM-only, no SPM) ---
    print("  Building baseline tasks (SAM only)...")
    if os.path.isdir(BUGGY_DATASETS_DIR):
        for buggy_dir_name in sorted(os.listdir(BUGGY_DATASETS_DIR)):
            buggy_dir_path = os.path.join(BUGGY_DATASETS_DIR, buggy_dir_name)
            if not os.path.isdir(buggy_dir_path):
                continue

            parts = buggy_dir_name.split("_", 2)
            if len(parts) < 3:
                continue
            language = parts[0]
            category = parts[1]
            bug_type = "_".join(parts[2:])

            for filename in sorted(os.listdir(buggy_dir_path)):
                if not filename.endswith(".json"):
                    continue
                filepath = os.path.join(buggy_dir_path, filename)
                try:
                    with open(filepath, "r") as f:
                        data = json.load(f)
                except Exception:
                    continue

                task = {
                    "id": _task_id(language, category, filename, bug_type),
                    "instruction": data.get("instruction", ""),
                    "code": data.get("buggy_code", ""),
                    "bug_line": data.get("line_no", 0),
                    "bug_line_range": data.get("bug_line_range"),
                    "metadata": {
                        "language": language,
                        "category": category,
                        "bug_type": bug_type,
                        "spm_type": "none",
                        "spm_strength": 0,
                        "source_file": filename,
                        "task_type": "baseline",
                        "loc": len(data.get("buggy_code", "").split("\n")),
                    },
                }
                if task["code"] and task["bug_line"] > 0:
                    tasks.append(task)

    baseline_count = len(tasks)
    print(f"    Baseline tasks: {baseline_count}")

    # --- 2. Degraded tasks (SAM + SPM) ---
    print("  Building degraded tasks (SAM + SPM)...")
    if os.path.isdir(MUTATED_DIR):
        for mutated_dir_name in sorted(os.listdir(MUTATED_DIR)):
            mutated_dir_path = os.path.join(MUTATED_DIR, mutated_dir_name)
            if not os.path.isdir(mutated_dir_path):
                continue

            # Parse SPM info from dir name: "python_existing_BooleanLogic__empty_lines_s1"
            if "__" not in mutated_dir_name:
                continue
            base_part, spm_part = mutated_dir_name.rsplit("__", 1)

            # Parse spm_type and strength from spm_part like "empty_lines_s1"
            spm_strength_match = spm_part.rsplit("_s", 1)
            if len(spm_strength_match) != 2:
                continue
            spm_type = spm_strength_match[0]
            try:
                spm_strength = int(spm_strength_match[1])
            except ValueError:
                continue

            parts = base_part.split("_", 2)
            if len(parts) < 3:
                continue
            language = parts[0]
            category = parts[1]
            bug_type = "_".join(parts[2:])

            for filename in sorted(os.listdir(mutated_dir_path)):
                if not filename.endswith(".json"):
                    continue
                filepath = os.path.join(mutated_dir_path, filename)
                try:
                    with open(filepath, "r") as f:
                        data = json.load(f)
                except Exception:
                    continue

                # Only include SPM-equivalent programs
                if not data.get("spm_equivalent", False):
                    continue

                task = {
                    "id": _task_id(language, category, filename, bug_type,
                                   spm_type, spm_strength),
                    "instruction": data.get("instruction", ""),
                    "code": data.get("spm_code", ""),
                    "bug_line": data.get("spm_bug_line", 0),
                    "bug_line_range": data.get("bug_line_range"),
                    "metadata": {
                        "language": language,
                        "category": category,
                        "bug_type": bug_type,
                        "spm_type": spm_type,
                        "spm_strength": spm_strength,
                        "source_file": filename,
                        "task_type": "degraded",
                        "loc": len(data.get("spm_code", "").split("\n")),
                    },
                }
                if task["code"] and task["bug_line"] > 0:
                    tasks.append(task)

    degraded_count = len(tasks) - baseline_count
    print(f"    Degraded tasks: {degraded_count}")

    # --- 3. Control arm (clean code, no bug) ---
    control_count = 0
    if CONTROL_ARM_ENABLED:
        print("  Building control tasks (clean code, no bug)...")
        for language in LANGUAGES:
            dataset_base = PYTHON_DATASET if language == "python" else JAVA_DATASET
            for category in DATASET_CATEGORIES:
                cat_dir = os.path.join(dataset_base, category)
                if not os.path.isdir(cat_dir):
                    continue
                for filename in sorted(os.listdir(cat_dir)):
                    if not filename.endswith(".json"):
                        continue
                    filepath = os.path.join(cat_dir, filename)
                    try:
                        with open(filepath, "r") as f:
                            data = json.load(f)
                    except Exception:
                        continue

                    code = data.get("output", "")
                    instruction = data.get("instruction", "")
                    if not code or not instruction:
                        continue

                    task = {
                        "id": _task_id(language, category, filename, "CONTROL"),
                        "instruction": instruction,
                        "code": code,
                        "bug_line": 0,  # No bug — any response is a false positive
                        "bug_line_range": None,
                        "metadata": {
                            "language": language,
                            "category": category,
                            "bug_type": "CONTROL",
                            "spm_type": "none",
                            "spm_strength": 0,
                            "source_file": filename,
                            "task_type": "control",
                            "loc": len(code.split("\n")),
                        },
                    }
                    tasks.append(task)
                    control_count += 1

        print(f"    Control tasks: {control_count}")

    total = len(tasks)
    print(f"\n  Total tasks: {total}")
    print(f"    Baseline (SAM only): {baseline_count}")
    print(f"    Degraded (SAM+SPM):  {degraded_count}")
    print(f"    Control (clean):     {control_count}")

    # Apply model-specific subsetting (stratified to preserve McNemar pairing)
    if model_name and model_name in MODELS:
        model_cfg = MODELS[model_name]
        if model_cfg.get("task_allocation") == "subset":
            subset_size = model_cfg.get("subset_size", 10000)
            if total > subset_size:
                tasks = _stratified_subset(tasks, subset_size, rng)
                print(f"\n  Stratified subset for {model_name}: {len(tasks)} tasks "
                      f"(from {total})")
                # Recount
                bl = sum(1 for t in tasks if t.get("metadata", {}).get("task_type") == "baseline")
                dg = sum(1 for t in tasks if t.get("metadata", {}).get("task_type") == "degraded")
                ct = sum(1 for t in tasks if t.get("metadata", {}).get("task_type") == "control")
                print(f"    baseline={bl}, degraded={dg}, control={ct}")

    # Save checkpoint
    ckpt = {
        "tasks": tasks,
        "stats": {
            "total": len(tasks),
            "baseline": baseline_count,
            "degraded": degraded_count,
            "control": control_count,
        },
        "timestamp": datetime.now().isoformat(),
    }
    _save_checkpoint(ckpt_name, ckpt)

    return tasks


# ======================================================================
# Phase 4: Determinism check
# ======================================================================

def phase_determinism(model_name: str, tasks: List[dict]) -> dict:
    """Run determinism check on a model."""
    print("\n" + "=" * 60)
    print(f"  PHASE 4: DETERMINISM CHECK ({model_name})")
    print("=" * 60)

    from agent_evaluation_experiment.unified_tester import (
        get_backend,
        run_determinism_check,
    )

    backend = get_backend(model_name)
    result = run_determinism_check(backend, tasks, model_name)

    # Save result
    result_file = os.path.join(RESULTS_DIR, f"determinism_{model_name}.json")
    with open(result_file, "w") as f:
        json.dump(result, f, indent=2)

    print(f"\n  Consistency: {result['consistency_rate']:.1%}")
    print(f"  Recommendation: {result['recommendation']}")
    print(f"  Saved: {result_file}")

    return result


# ======================================================================
# Phase 5: Run LLM evaluations
# ======================================================================

def phase_evaluate(model_name: str, tasks: List[dict],
                   prompt_variant: str = None) -> List[dict]:
    """Run evaluation for a single model."""
    print("\n" + "=" * 60)
    print(f"  PHASE 5: LLM EVALUATION ({model_name})")
    print("=" * 60)

    from agent_evaluation_experiment.unified_tester import (
        get_backend,
        run_batch_evaluation,
        calculate_stats,
    )

    if prompt_variant is None:
        prompt_variant = PRIMARY_PROMPT

    backend = get_backend(model_name)
    checkpoint_file = os.path.join(
        CHECKPOINTS_DIR,
        f"{model_name.replace('-', '_')}_{prompt_variant}_progress.json"
    )

    # Use concurrent workers for local (Ollama) models
    model_cfg = MODELS.get(model_name, {})
    max_workers = 1
    if model_cfg.get("backend") == "ollama":
        max_workers = model_cfg.get("max_workers", 3)

    print(f"  Model: {model_name}")
    print(f"  Tasks: {len(tasks)}")
    print(f"  Prompt: {prompt_variant}")
    print(f"  Workers: {max_workers}")
    print(f"  Checkpoint: {checkpoint_file}")

    results = run_batch_evaluation(
        backend, tasks, model_name,
        checkpoint_file=checkpoint_file,
        prompt_variant=prompt_variant,
        max_workers=max_workers,
    )

    # Calculate and display stats
    stats = calculate_stats(results)
    print(f"\n  Results for {model_name}:")
    print(f"    Total: {stats['total']}")
    print(f"    Accuracy (tol=0): {stats['accuracy_tol0']:.2f}%")
    print(f"    Accuracy (tol=2): {stats['accuracy_tol2']:.2f}%")
    print(f"    Errors: {stats['errors']}")
    print(f"    Avg latency: {stats['avg_latency_ms']:.0f}ms")

    # Save final results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    result_file = os.path.join(
        RESULTS_DIR,
        f"{model_name.replace('-', '_')}_{prompt_variant}_{timestamp}.json"
    )
    output = {
        "model": model_name,
        "prompt_variant": prompt_variant,
        "timestamp": timestamp,
        "stats": stats,
        "results": results,
    }
    with open(result_file, "w") as f:
        json.dump(output, f, indent=2)
    print(f"  Saved: {result_file}")

    return results


# ======================================================================
# Phase 6: Results aggregation
# ======================================================================

def phase_aggregate() -> dict:
    """Aggregate results from all model evaluations."""
    print("\n" + "=" * 60)
    print("  PHASE 6: RESULTS AGGREGATION")
    print("=" * 60)

    from agent_evaluation_experiment.unified_tester import calculate_stats

    # Find all result files
    result_files = sorted([
        f for f in os.listdir(RESULTS_DIR)
        if f.endswith(".json") and not f.startswith("determinism")
        and "checkpoint" not in f and "aggregated" not in f
    ])

    if not result_files:
        print("  No result files found.")
        return {}

    aggregated = {
        "timestamp": datetime.now().isoformat(),
        "models": {},
        "comparisons": {},
    }

    all_results_by_model = {}

    for rf in result_files:
        filepath = os.path.join(RESULTS_DIR, rf)
        try:
            with open(filepath, "r") as f:
                data = json.load(f)
        except Exception:
            continue

        model = data.get("model", "unknown")
        prompt = data.get("prompt_variant", "unknown")
        results = data.get("results", [])
        stats = data.get("stats", {})

        key = f"{model}_{prompt}"
        aggregated["models"][key] = {
            "model": model,
            "prompt_variant": prompt,
            "stats": stats,
            "file": rf,
        }
        all_results_by_model[key] = results

    # --- Compute degradation analysis ---
    print("\n  Degradation Analysis:")
    for model_key, results in all_results_by_model.items():
        baseline_results = [r for r in results
                           if r.get("metadata", {}).get("task_type") == "baseline"]
        degraded_results = [r for r in results
                           if r.get("metadata", {}).get("task_type") == "degraded"]
        control_results = [r for r in results
                          if r.get("metadata", {}).get("task_type") == "control"]

        if baseline_results:
            b_stats = calculate_stats(baseline_results)
            print(f"\n  {model_key} — Baseline:")
            print(f"    N={b_stats['total']}, "
                  f"tol0={b_stats['accuracy_tol0']:.2f}%, "
                  f"tol2={b_stats['accuracy_tol2']:.2f}%")

        if degraded_results:
            d_stats = calculate_stats(degraded_results)
            print(f"  {model_key} — Degraded (SAM+SPM):")
            print(f"    N={d_stats['total']}, "
                  f"tol0={d_stats['accuracy_tol0']:.2f}%, "
                  f"tol2={d_stats['accuracy_tol2']:.2f}%")

            # Degradation by SPM type
            spm_degradation = {}
            for r in degraded_results:
                spm = r.get("metadata", {}).get("spm_type", "unknown")
                if spm not in spm_degradation:
                    spm_degradation[spm] = {"total": 0, "correct_tol0": 0}
                spm_degradation[spm]["total"] += 1
                if r.get("correct_tol0", False):
                    spm_degradation[spm]["correct_tol0"] += 1

            print(f"    By SPM type:")
            for spm, sd in sorted(spm_degradation.items()):
                acc = (sd["correct_tol0"] / sd["total"] * 100) if sd["total"] > 0 else 0
                print(f"      {spm}: {acc:.1f}% (N={sd['total']})")

            aggregated["comparisons"][model_key] = {
                "baseline": b_stats if baseline_results else None,
                "degraded": d_stats,
                "spm_degradation": spm_degradation,
            }

        if control_results:
            # False positive rate: any non-zero prediction on clean code
            fp = sum(1 for r in control_results
                     if r.get("predicted_line", 0) > 0)
            fp_rate = fp / len(control_results) * 100 if control_results else 0
            print(f"  {model_key} — Control (false positives):")
            print(f"    N={len(control_results)}, FP rate={fp_rate:.1f}%")
            aggregated["comparisons"].setdefault(model_key, {})
            aggregated["comparisons"][model_key]["control"] = {
                "total": len(control_results),
                "false_positives": fp,
                "fp_rate": fp_rate,
            }

    # --- McNemar's test for paired comparisons ---
    _run_mcnemar_tests(aggregated, all_results_by_model)

    # Save aggregated results
    agg_file = os.path.join(RESULTS_DIR, "aggregated_analysis.json")
    with open(agg_file, "w") as f:
        json.dump(aggregated, f, indent=2)
    print(f"\n  Saved: {agg_file}")

    return aggregated


def _run_mcnemar_tests(aggregated: dict, all_results_by_model: dict) -> None:
    """Run McNemar's test for paired before/after SPM comparisons."""
    try:
        from scipy.stats import binom
    except ImportError:
        print("\n  [scipy not available — skipping McNemar's test]")
        return

    print("\n  McNemar's Test (paired before/after SPM):")
    aggregated["mcnemar_tests"] = {}

    for model_key, results in all_results_by_model.items():
        baseline = {r.get("metadata", {}).get("source_file"): r
                    for r in results
                    if r.get("metadata", {}).get("task_type") == "baseline"}
        degraded_by_spm = {}
        for r in results:
            if r.get("metadata", {}).get("task_type") != "degraded":
                continue
            spm = r.get("metadata", {}).get("spm_type", "unknown")
            src = r.get("metadata", {}).get("source_file", "")
            bt = r.get("metadata", {}).get("bug_type", "")
            pair_key = f"{src}|{bt}"
            degraded_by_spm.setdefault(spm, {})[pair_key] = r

        # Build baseline lookup by source+bug_type
        baseline_lookup = {}
        for r in results:
            if r.get("metadata", {}).get("task_type") == "baseline":
                src = r.get("metadata", {}).get("source_file", "")
                bt = r.get("metadata", {}).get("bug_type", "")
                baseline_lookup[f"{src}|{bt}"] = r

        for spm_type, deg_map in degraded_by_spm.items():
            # Find paired samples
            b_correct_d_wrong = 0  # baseline correct, degraded wrong
            b_wrong_d_correct = 0  # baseline wrong, degraded correct
            paired = 0

            for pair_key, d_result in deg_map.items():
                b_result = baseline_lookup.get(pair_key)
                if b_result is None:
                    continue
                paired += 1
                b_ok = b_result.get("correct_tol0", False)
                d_ok = d_result.get("correct_tol0", False)
                if b_ok and not d_ok:
                    b_correct_d_wrong += 1
                elif not b_ok and d_ok:
                    b_wrong_d_correct += 1

            if paired < 10:
                continue

            # McNemar's test (exact binomial)
            n_discordant = b_correct_d_wrong + b_wrong_d_correct
            if n_discordant == 0:
                p_value = 1.0
            else:
                # Two-sided exact binomial test
                k = min(b_correct_d_wrong, b_wrong_d_correct)
                p_value = 2.0 * binom.cdf(k, n_discordant, 0.5)
                p_value = min(p_value, 1.0)

            degradation_pct = (
                (b_correct_d_wrong / paired * 100) if paired > 0 else 0
            )

            test_result = {
                "paired_samples": paired,
                "baseline_correct_degraded_wrong": b_correct_d_wrong,
                "baseline_wrong_degraded_correct": b_wrong_d_correct,
                "degradation_rate": degradation_pct,
                "p_value": p_value,
                "significant": p_value < 0.05,
            }

            aggregated["mcnemar_tests"][f"{model_key}|{spm_type}"] = test_result
            sig = "*" if p_value < 0.05 else ""
            print(f"    {model_key} × {spm_type}: "
                  f"degradation={degradation_pct:.1f}%, "
                  f"p={p_value:.4f}{sig} "
                  f"(N={paired})")


# ======================================================================
# Main CLI
# ======================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Pipeline runner for Agent Evaluation Experiment"
    )
    parser.add_argument(
        "--phase",
        choices=["validate", "inject", "spm", "tasks", "determinism",
                 "evaluate", "aggregate", "all"],
        default="all",
        help="Which phase to run (default: all)",
    )
    parser.add_argument(
        "--model",
        choices=list(MODELS.keys()),
        help="Model to evaluate (required for evaluate/determinism phases)",
    )
    parser.add_argument(
        "--prompt-variant",
        choices=list(PROMPT_VARIANTS.keys()),
        default=None,
        help="Prompt variant to use (default: minimal)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-run even if checkpoint exists",
    )
    parser.add_argument(
        "--all-models",
        action="store_true",
        help="Run evaluation for all configured models sequentially",
    )

    args = parser.parse_args()

    start_time = time.time()
    print(f"\nPipeline started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Random seed: {RANDOM_SEED}")

    if args.phase in ("all", "validate"):
        validated = phase_validate(force=args.force)
        if args.phase == "validate":
            return

    if args.phase in ("all", "inject"):
        validated = phase_validate()  # ensure validation exists
        injection_result = phase_inject(validated, force=args.force)
        if args.phase == "inject":
            return

    if args.phase in ("all", "spm"):
        phase_spm(force=args.force)
        if args.phase == "spm":
            return

    if args.phase in ("all", "tasks"):
        if args.model:
            tasks = phase_build_tasks(model_name=args.model, force=args.force)
        else:
            tasks = phase_build_tasks(force=args.force)
        if args.phase == "tasks":
            return

    if args.phase in ("all", "determinism"):
        model = args.model or "gpt-4o-mini"
        tasks = phase_build_tasks(model_name=model)
        phase_determinism(model, tasks)
        if args.phase == "determinism":
            return

    if args.phase in ("all", "evaluate"):
        if args.all_models:
            for model_name in MODELS:
                tasks = phase_build_tasks(model_name=model_name)
                phase_evaluate(model_name, tasks,
                               prompt_variant=args.prompt_variant)
        elif args.model:
            tasks = phase_build_tasks(model_name=args.model)
            phase_evaluate(args.model, tasks,
                           prompt_variant=args.prompt_variant)
        else:
            # Default: run all models
            for model_name in MODELS:
                tasks = phase_build_tasks(model_name=model_name)
                phase_evaluate(model_name, tasks,
                               prompt_variant=args.prompt_variant)
        if args.phase == "evaluate":
            return

    if args.phase in ("all", "aggregate"):
        phase_aggregate()

    elapsed = time.time() - start_time
    print(f"\nPipeline completed in {elapsed / 60:.1f} minutes")


if __name__ == "__main__":
    main()
