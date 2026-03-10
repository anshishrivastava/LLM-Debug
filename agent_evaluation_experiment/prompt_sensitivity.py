#!/usr/bin/env python3
"""Prompt sensitivity analysis for the Agent Evaluation Experiment.

Runs a subset of tasks with alternate prompt variants to measure
how much prompt phrasing affects accuracy.

Usage:
    python -m agent_evaluation_experiment.prompt_sensitivity \
        --model claude-opus --subset-size 500
"""

import argparse
import json
import os
import random
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_evaluation_experiment.config import (
    PROMPT_VARIANTS,
    PRIMARY_PROMPT,
    RESULTS_DIR,
    CHECKPOINTS_DIR,
    RANDOM_SEED,
)
from agent_evaluation_experiment.unified_tester import (
    get_backend,
    run_batch_evaluation,
)


def main():
    parser = argparse.ArgumentParser(
        description="Prompt sensitivity analysis"
    )
    parser.add_argument("--model", required=True, help="Model name from config")
    parser.add_argument("--subset-size", type=int, default=500,
                        help="Number of tasks per prompt variant")
    parser.add_argument("--tasks-checkpoint", default=None,
                        help="Path to tasks checkpoint to sample from")
    args = parser.parse_args()

    # Find tasks from existing checkpoint
    if args.tasks_checkpoint:
        tasks_file = args.tasks_checkpoint
    else:
        # Auto-detect from model name
        safe_name = args.model.replace("/", "_").replace(":", "_").replace("-", "_")
        candidates = [
            os.path.join(CHECKPOINTS_DIR, f"tasks_{args.model}_checkpoint.json"),
            os.path.join(CHECKPOINTS_DIR, f"tasks_claude-opus_checkpoint.json"),
        ]
        tasks_file = None
        for c in candidates:
            if os.path.exists(c):
                tasks_file = c
                break
        if not tasks_file:
            print(f"No tasks checkpoint found for {args.model}")
            sys.exit(1)

    print(f"Loading tasks from: {tasks_file}")
    with open(tasks_file) as f:
        all_tasks = json.load(f)

    if isinstance(all_tasks, dict) and "tasks" in all_tasks:
        all_tasks = all_tasks["tasks"]

    print(f"Total tasks available: {len(all_tasks)}")

    # Sample a subset (seeded for reproducibility)
    rng = random.Random(RANDOM_SEED)
    subset = rng.sample(all_tasks, min(args.subset_size, len(all_tasks)))
    print(f"Sampled {len(subset)} tasks for prompt sensitivity analysis")

    # Get alternate prompts (skip primary)
    alt_prompts = [p for p in PROMPT_VARIANTS.keys() if p != PRIMARY_PROMPT]
    print(f"Alternate prompts to test: {alt_prompts}")

    # Create backend
    backend = get_backend(args.model)

    results_by_prompt = {}

    for prompt_variant in alt_prompts:
        print(f"\n{'='*60}")
        print(f"  Running prompt variant: {prompt_variant}")
        print(f"  Tasks: {len(subset)}")
        print(f"{'='*60}")

        checkpoint_file = os.path.join(
            CHECKPOINTS_DIR,
            f"{args.model}_{prompt_variant}_sensitivity_progress.json",
        )

        results = run_batch_evaluation(
            backend=backend,
            tasks=subset,
            model_name=args.model,
            checkpoint_file=checkpoint_file,
            prompt_variant=prompt_variant,
        )

        # Calculate accuracy
        total = len(results)
        correct_0 = sum(1 for r in results if r.get("correct_tol0", False))
        correct_2 = sum(1 for r in results if r.get("correct_tol2", False))

        results_by_prompt[prompt_variant] = {
            "total": total,
            "correct_tol0": correct_0,
            "correct_tol2": correct_2,
            "accuracy_tol0": round(correct_0 / total * 100, 2) if total else 0,
            "accuracy_tol2": round(correct_2 / total * 100, 2) if total else 0,
            "results": results,
        }

        print(f"\n  {prompt_variant}: tol0={correct_0}/{total} = "
              f"{correct_0/total*100:.1f}%, tol2={correct_2/total*100:.1f}%")

    # Also compute primary prompt accuracy on the same subset
    primary_results = []
    primary_checkpoint = os.path.join(
        CHECKPOINTS_DIR,
        f"{args.model}_{PRIMARY_PROMPT}_progress.json",
    )
    if os.path.exists(primary_checkpoint):
        with open(primary_checkpoint) as f:
            ckpt = json.load(f)
        subset_ids = {t["id"] for t in subset}
        primary_results = [r for r in ckpt.get("results", [])
                          if r.get("task_id") in subset_ids]

    if primary_results:
        total = len(primary_results)
        correct_0 = sum(1 for r in primary_results if r.get("correct_tol0", False))
        correct_2 = sum(1 for r in primary_results if r.get("correct_tol2", False))
        results_by_prompt[PRIMARY_PROMPT] = {
            "total": total,
            "correct_tol0": correct_0,
            "correct_tol2": correct_2,
            "accuracy_tol0": round(correct_0 / total * 100, 2) if total else 0,
            "accuracy_tol2": round(correct_2 / total * 100, 2) if total else 0,
        }

    # Print comparison
    print(f"\n{'='*60}")
    print(f"  PROMPT SENSITIVITY RESULTS ({args.model})")
    print(f"{'='*60}")
    print(f"  {'Prompt':<20s} {'N':>5s} {'tol0':>8s} {'tol2':>8s}")
    print(f"  {'─'*20} {'─'*5} {'─'*8} {'─'*8}")

    accs = []
    for prompt, data in sorted(results_by_prompt.items()):
        acc0 = data["accuracy_tol0"]
        acc2 = data["accuracy_tol2"]
        accs.append(acc0)
        marker = " ← primary" if prompt == PRIMARY_PROMPT else ""
        print(f"  {prompt:<20s} {data['total']:5d} {acc0:7.1f}% {acc2:7.1f}%{marker}")

    if len(accs) > 1:
        variance = max(accs) - min(accs)
        print(f"\n  Accuracy range: {variance:.1f}pp")
        if variance < 5:
            print("  Verdict: Low sensitivity — results are prompt-robust")
        elif variance < 10:
            print("  Verdict: Moderate sensitivity — report in paper")
        else:
            print("  Verdict: HIGH sensitivity — major finding, discuss in paper")

    # Save results
    output = {
        "model": args.model,
        "subset_size": len(subset),
        "timestamp": datetime.now().isoformat(),
        "prompt_variants_tested": list(results_by_prompt.keys()),
        "summary": {
            p: {k: v for k, v in data.items() if k != "results"}
            for p, data in results_by_prompt.items()
        },
    }

    out_file = os.path.join(RESULTS_DIR, f"prompt_sensitivity_{args.model}.json")
    with open(out_file, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n  Saved: {out_file}")


if __name__ == "__main__":
    main()
