#!/usr/bin/env python3
"""Results aggregation and statistical analysis for the Agent Evaluation Experiment.

Produces:
    - Accuracy tables at both tolerance=0 and tolerance=2
    - Degradation heatmaps (SAM × SPM)
    - McNemar's tests with 95% confidence intervals
    - Cohen's h effect sizes for all comparisons
    - Breakdown by model, language, category, bug position
    - False positive rates from control arm (deep-dive)
    - Prompt sensitivity analysis
    - LaTeX tables for the paper

Usage:
    python -m agent_evaluation_experiment.results_aggregator
    python -m agent_evaluation_experiment.results_aggregator --latex
"""

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_evaluation_experiment.config import (
    RESULTS_DIR,
    CHECKPOINTS_DIR,
    ARTIFACTS_DIR,
    SPM_TYPES,
    CWE_BUG_TYPES,
    LEGACY_BUG_TYPES,
    LANGUAGES,
    MODELS,
)


# ======================================================================
# Confidence Intervals (Wilson score)
# ======================================================================

def wilson_ci(successes: int, total: int, z: float = 1.96) -> Tuple[float, float]:
    """Wilson score confidence interval for a proportion.

    Returns (lower, upper) as percentages.
    """
    if total == 0:
        return (0.0, 0.0)
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    spread = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    lower = max(0, center - spread) * 100
    upper = min(1, center + spread) * 100
    return (round(lower, 2), round(upper, 2))


# ======================================================================
# Effect sizes
# ======================================================================

def cohens_h(p1: float, p2: float) -> float:
    """Cohen's h effect size for comparing two proportions.

    Parameters are proportions (0-1), not percentages.
    Returns signed h: positive means p1 > p2.
    Interpretation: |h| < 0.2 = small, 0.2-0.8 = medium, > 0.8 = large.
    """
    def _arcsin_transform(p):
        return 2 * math.asin(math.sqrt(max(0, min(1, p))))
    return _arcsin_transform(p1) - _arcsin_transform(p2)


def odds_ratio(a: int, b: int, c: int, d: int) -> float:
    """Odds ratio from a 2x2 contingency table.

    For McNemar's table: a=both_correct, b=baseline_only, c=degraded_only, d=both_wrong.
    OR = b/c (discordant pair ratio).
    Returns OR, or inf/0 for edge cases.
    """
    if c == 0:
        return float('inf') if b > 0 else 1.0
    return b / c


# ======================================================================
# McNemar's test
# ======================================================================

def mcnemar_exact(b_correct_d_wrong: int, b_wrong_d_correct: int) -> float:
    """Exact McNemar's test (two-sided binomial).

    Returns p-value.
    """
    n = b_correct_d_wrong + b_wrong_d_correct
    if n == 0:
        return 1.0
    try:
        from scipy.stats import binom
        k = min(b_correct_d_wrong, b_wrong_d_correct)
        p_value = 2.0 * binom.cdf(k, n, 0.5)
        return min(p_value, 1.0)
    except ImportError:
        # Fallback: simple sign test approximation
        if n < 25:
            return 1.0  # can't approximate well
        chi2 = (b_correct_d_wrong - b_wrong_d_correct) ** 2 / n
        if chi2 > 10.83:
            return 0.001
        elif chi2 > 6.63:
            return 0.01
        elif chi2 > 3.84:
            return 0.05
        return 1.0


# ======================================================================
# Load results
# ======================================================================

def load_all_results() -> Dict[str, dict]:
    """Load all evaluation result files."""
    results = {}

    for filename in sorted(os.listdir(RESULTS_DIR)):
        if not filename.endswith(".json"):
            continue
        if filename.startswith("determinism"):
            continue
        if "checkpoint" in filename or "aggregated" in filename:
            continue
        if "comprehensive" in filename or "prompt_sensitivity" in filename:
            continue

        filepath = os.path.join(RESULTS_DIR, filename)
        try:
            with open(filepath, "r") as f:
                data = json.load(f)
        except Exception:
            continue

        if "results" not in data:
            continue

        model = data.get("model", "unknown")
        prompt = data.get("prompt_variant", "minimal")
        key = f"{model}_{prompt}"
        results[key] = data

    return results


def load_checkpoint_results(model_key: str) -> Optional[dict]:
    """Load results from a checkpoint file for a model that hasn't finished."""
    safe_name = model_key.replace("/", "_").replace(":", "_")
    # Try common checkpoint patterns
    patterns = [
        f"{safe_name}_minimal_progress.json",
        f"{safe_name}_progress.json",
    ]
    for pattern in patterns:
        path = os.path.join(CHECKPOINTS_DIR, pattern)
        if os.path.exists(path):
            try:
                with open(path) as f:
                    data = json.load(f)
                if data.get("results"):
                    return {
                        "model": data.get("model", model_key),
                        "prompt_variant": "minimal",
                        "results": data["results"],
                        "source": "checkpoint",
                    }
            except Exception:
                continue
    return None


# ======================================================================
# Analysis functions
# ======================================================================

def analyze_by_dimensions(results: List[dict]) -> dict:
    """Analyze results across all dimensions."""
    analysis = {
        "overall": _accuracy(results),
        "by_task_type": {},
        "by_language": {},
        "by_category": {},
        "by_bug_type": {},
        "by_spm_type": {},
        "by_spm_strength": {},
        "by_loc_bucket": {},
        "by_position_bucket": {},
    }

    # Group by dimensions
    groups = defaultdict(list)
    for r in results:
        meta = r.get("metadata", {})
        groups[("task_type", meta.get("task_type", "unknown"))].append(r)
        groups[("language", meta.get("language", "unknown"))].append(r)
        groups[("category", meta.get("category", "unknown"))].append(r)
        groups[("bug_type", meta.get("bug_type", "unknown"))].append(r)
        groups[("spm_type", meta.get("spm_type", "none"))].append(r)
        groups[("spm_strength", str(meta.get("spm_strength", 0)))].append(r)

        # LOC buckets
        loc = meta.get("loc", 0)
        if loc <= 20:
            bucket = "1-20"
        elif loc <= 50:
            bucket = "21-50"
        elif loc <= 100:
            bucket = "51-100"
        elif loc <= 200:
            bucket = "101-200"
        else:
            bucket = "200+"
        groups[("loc_bucket", bucket)].append(r)

        # Position buckets (where the bug is)
        bug_line = r.get("actual_line", r.get("bug_line", 0))
        total_lines = meta.get("loc", 1)
        if total_lines > 0 and bug_line > 0:
            pct = bug_line / total_lines * 100
            if pct <= 25:
                pos = "top_25%"
            elif pct <= 50:
                pos = "25-50%"
            elif pct <= 75:
                pos = "50-75%"
            else:
                pos = "bottom_25%"
            groups[("position", pos)].append(r)

    # Build analysis dicts
    for (dim, val), group_results in groups.items():
        key = f"by_{dim}"
        if key not in analysis:
            key = f"by_{dim}_bucket" if dim in ("loc", "position") else f"by_{dim}"
            if key not in analysis:
                continue
        analysis[key][val] = _accuracy(group_results)

    return analysis


def _accuracy(results: List[dict]) -> dict:
    """Calculate accuracy with confidence intervals."""
    total = len(results)
    if total == 0:
        return {"total": 0, "accuracy_tol0": 0, "accuracy_tol2": 0,
                "ci_tol0": (0, 0), "ci_tol2": (0, 0)}

    correct_0 = sum(1 for r in results if r.get("correct_tol0", False))
    correct_2 = sum(1 for r in results if r.get("correct_tol2", False))
    errors = sum(1 for r in results if r.get("error") is not None)

    return {
        "total": total,
        "correct_tol0": correct_0,
        "correct_tol2": correct_2,
        "accuracy_tol0": round(correct_0 / total * 100, 2),
        "accuracy_tol2": round(correct_2 / total * 100, 2),
        "ci_tol0": wilson_ci(correct_0, total),
        "ci_tol2": wilson_ci(correct_2, total),
        "errors": errors,
    }


def compute_degradation_matrix(results: List[dict]) -> dict:
    """Compute SAM × SPM degradation matrix with effect sizes.

    For each (bug_type, spm_type) pair, compute:
    - Baseline accuracy (SAM only)
    - Degraded accuracy (SAM + SPM)
    - Degradation rate
    - McNemar's p-value
    - Cohen's h effect size
    - Odds ratio
    """
    # Build lookup: source_file|bug_type -> baseline result
    baseline_lookup = {}
    for r in results:
        meta = r.get("metadata", {})
        if meta.get("task_type") != "baseline":
            continue
        key = f"{meta.get('source_file')}|{meta.get('bug_type')}"
        baseline_lookup[key] = r

    # Group degraded by (bug_type, spm_type)
    degraded_groups = defaultdict(list)
    for r in results:
        meta = r.get("metadata", {})
        if meta.get("task_type") != "degraded":
            continue
        group_key = (meta.get("bug_type", ""), meta.get("spm_type", ""))
        degraded_groups[group_key].append(r)

    matrix = {}
    for (bug_type, spm_type), deg_results in degraded_groups.items():
        # Pair with baseline
        both_correct = 0
        b_correct_d_wrong = 0
        b_wrong_d_correct = 0
        both_wrong = 0
        paired = 0

        for d_r in deg_results:
            d_meta = d_r.get("metadata", {})
            pair_key = f"{d_meta.get('source_file')}|{d_meta.get('bug_type')}"
            b_r = baseline_lookup.get(pair_key)
            if b_r is None:
                continue
            paired += 1
            b_ok = b_r.get("correct_tol0", False)
            d_ok = d_r.get("correct_tol0", False)
            if b_ok and d_ok:
                both_correct += 1
            elif b_ok and not d_ok:
                b_correct_d_wrong += 1
            elif not b_ok and d_ok:
                b_wrong_d_correct += 1
            else:
                both_wrong += 1

        if paired == 0:
            continue

        p_value = mcnemar_exact(b_correct_d_wrong, b_wrong_d_correct)
        deg_acc = _accuracy(deg_results)

        # Baseline accuracy for this bug type
        baseline_for_bt = [
            r for r in results
            if r.get("metadata", {}).get("task_type") == "baseline"
            and r.get("metadata", {}).get("bug_type") == bug_type
        ]
        bl_acc = _accuracy(baseline_for_bt)

        # Effect sizes
        p1 = bl_acc["accuracy_tol0"] / 100 if bl_acc["accuracy_tol0"] else 0
        p2 = deg_acc["accuracy_tol0"] / 100 if deg_acc["accuracy_tol0"] else 0
        h = cohens_h(p1, p2)
        or_val = odds_ratio(both_correct, b_correct_d_wrong, b_wrong_d_correct, both_wrong)

        h_interpretation = "negligible"
        if abs(h) >= 0.8:
            h_interpretation = "large"
        elif abs(h) >= 0.5:
            h_interpretation = "medium"
        elif abs(h) >= 0.2:
            h_interpretation = "small"

        matrix_key = f"{bug_type}|{spm_type}"
        matrix[matrix_key] = {
            "bug_type": bug_type,
            "spm_type": spm_type,
            "baseline_accuracy_tol0": bl_acc["accuracy_tol0"],
            "degraded_accuracy_tol0": deg_acc["accuracy_tol0"],
            "degradation_pp": round(bl_acc["accuracy_tol0"] - deg_acc["accuracy_tol0"], 2),
            "degradation_rate": round(
                b_correct_d_wrong / paired * 100, 2
            ) if paired > 0 else 0,
            "improvement_rate": round(
                b_wrong_d_correct / paired * 100, 2
            ) if paired > 0 else 0,
            "paired_samples": paired,
            "contingency": {
                "both_correct": both_correct,
                "baseline_only": b_correct_d_wrong,
                "degraded_only": b_wrong_d_correct,
                "both_wrong": both_wrong,
            },
            "p_value": round(p_value, 4),
            "significant": p_value < 0.05,
            "cohens_h": round(h, 4),
            "h_interpretation": h_interpretation,
            "odds_ratio": round(or_val, 4) if or_val != float('inf') else "inf",
        }

    return matrix


def compute_overall_degradation(results: List[dict]) -> dict:
    """Compute overall baseline vs degraded comparison with McNemar's and effect sizes."""
    baseline_lookup = {}
    for r in results:
        meta = r.get("metadata", {})
        if meta.get("task_type") != "baseline":
            continue
        key = f"{meta.get('source_file')}|{meta.get('bug_type')}"
        baseline_lookup[key] = r

    both_correct = 0
    b_correct_d_wrong = 0
    b_wrong_d_correct = 0
    both_wrong = 0
    paired = 0

    for r in results:
        meta = r.get("metadata", {})
        if meta.get("task_type") != "degraded":
            continue
        pair_key = f"{meta.get('source_file')}|{meta.get('bug_type')}"
        b_r = baseline_lookup.get(pair_key)
        if b_r is None:
            continue
        paired += 1
        b_ok = b_r.get("correct_tol0", False)
        d_ok = r.get("correct_tol0", False)
        if b_ok and d_ok:
            both_correct += 1
        elif b_ok and not d_ok:
            b_correct_d_wrong += 1
        elif not b_ok and d_ok:
            b_wrong_d_correct += 1
        else:
            both_wrong += 1

    if paired == 0:
        return {"paired": 0}

    bl_results = [r for r in results if r.get("metadata", {}).get("task_type") == "baseline"]
    dg_results = [r for r in results if r.get("metadata", {}).get("task_type") == "degraded"]
    bl_acc = _accuracy(bl_results)
    dg_acc = _accuracy(dg_results)

    p_value = mcnemar_exact(b_correct_d_wrong, b_wrong_d_correct)
    p1 = bl_acc["accuracy_tol0"] / 100
    p2 = dg_acc["accuracy_tol0"] / 100
    h = cohens_h(p1, p2)
    or_val = odds_ratio(both_correct, b_correct_d_wrong, b_wrong_d_correct, both_wrong)

    return {
        "paired": paired,
        "baseline_accuracy_tol0": bl_acc["accuracy_tol0"],
        "baseline_ci_tol0": bl_acc["ci_tol0"],
        "degraded_accuracy_tol0": dg_acc["accuracy_tol0"],
        "degraded_ci_tol0": dg_acc["ci_tol0"],
        "degradation_pp": round(bl_acc["accuracy_tol0"] - dg_acc["accuracy_tol0"], 2),
        "baseline_accuracy_tol2": bl_acc["accuracy_tol2"],
        "degraded_accuracy_tol2": dg_acc["accuracy_tol2"],
        "degradation_pp_tol2": round(bl_acc["accuracy_tol2"] - dg_acc["accuracy_tol2"], 2),
        "contingency": {
            "both_correct": both_correct,
            "baseline_only": b_correct_d_wrong,
            "degraded_only": b_wrong_d_correct,
            "both_wrong": both_wrong,
        },
        "mcnemar_p_value": round(p_value, 6),
        "significant": p_value < 0.05,
        "cohens_h": round(h, 4),
        "odds_ratio": round(or_val, 4) if or_val != float('inf') else "inf",
    }


def compute_false_positive_rate(results: List[dict]) -> dict:
    """Compute detailed false positive analysis from control arm."""
    control = [r for r in results
               if r.get("metadata", {}).get("task_type") == "control"]

    if not control:
        return {"total": 0, "false_positives": 0, "fp_rate": 0}

    fp = sum(1 for r in control if r.get("predicted_line", 0) > 0)

    # Break down by whether code has SPM applied
    control_clean = [r for r in control
                     if r.get("metadata", {}).get("spm_type") in (None, "none", "")]
    control_spm = [r for r in control
                   if r.get("metadata", {}).get("spm_type") not in (None, "none", "")]

    fp_clean = sum(1 for r in control_clean if r.get("predicted_line", 0) > 0)
    fp_spm = sum(1 for r in control_spm if r.get("predicted_line", 0) > 0)

    # Break down by SPM type for control+SPM
    fp_by_spm = defaultdict(lambda: {"total": 0, "fp": 0})
    for r in control_spm:
        spm = r.get("metadata", {}).get("spm_type", "unknown")
        fp_by_spm[spm]["total"] += 1
        if r.get("predicted_line", 0) > 0:
            fp_by_spm[spm]["fp"] += 1

    for v in fp_by_spm.values():
        v["fp_rate"] = round(v["fp"] / v["total"] * 100, 2) if v["total"] > 0 else 0

    # Predicted line distribution (where do models "see" bugs in clean code?)
    predicted_lines = [r.get("predicted_line", 0) for r in control if r.get("predicted_line", 0) > 0]
    line_distribution = {}
    if predicted_lines:
        line_distribution = {
            "mean": round(sum(predicted_lines) / len(predicted_lines), 1),
            "median": sorted(predicted_lines)[len(predicted_lines) // 2],
            "min": min(predicted_lines),
            "max": max(predicted_lines),
        }

    return {
        "total": len(control),
        "false_positives": fp,
        "fp_rate": round(fp / len(control) * 100, 2),
        "ci": wilson_ci(fp, len(control)),
        "clean_code": {
            "total": len(control_clean),
            "fp": fp_clean,
            "fp_rate": round(fp_clean / len(control_clean) * 100, 2) if control_clean else 0,
        },
        "spm_code": {
            "total": len(control_spm),
            "fp": fp_spm,
            "fp_rate": round(fp_spm / len(control_spm) * 100, 2) if control_spm else 0,
        },
        "fp_by_spm_type": dict(fp_by_spm),
        "predicted_line_distribution": line_distribution,
    }


def compute_per_spm_degradation(results: List[dict]) -> dict:
    """Compute degradation broken down by SPM type (aggregated across all SAMs)."""
    baseline_lookup = {}
    for r in results:
        meta = r.get("metadata", {})
        if meta.get("task_type") != "baseline":
            continue
        key = f"{meta.get('source_file')}|{meta.get('bug_type')}"
        baseline_lookup[key] = r

    spm_groups = defaultdict(list)
    for r in results:
        meta = r.get("metadata", {})
        if meta.get("task_type") != "degraded":
            continue
        spm_groups[meta.get("spm_type", "unknown")].append(r)

    per_spm = {}
    for spm_type, deg_results in spm_groups.items():
        b_correct_d_wrong = 0
        b_wrong_d_correct = 0
        paired = 0

        for d_r in deg_results:
            d_meta = d_r.get("metadata", {})
            pair_key = f"{d_meta.get('source_file')}|{d_meta.get('bug_type')}"
            b_r = baseline_lookup.get(pair_key)
            if b_r is None:
                continue
            paired += 1
            b_ok = b_r.get("correct_tol0", False)
            d_ok = d_r.get("correct_tol0", False)
            if b_ok and not d_ok:
                b_correct_d_wrong += 1
            elif not b_ok and d_ok:
                b_wrong_d_correct += 1

        deg_acc = _accuracy(deg_results)
        bl_results = [r for r in results if r.get("metadata", {}).get("task_type") == "baseline"]
        bl_acc = _accuracy(bl_results)

        p1 = bl_acc["accuracy_tol0"] / 100
        p2 = deg_acc["accuracy_tol0"] / 100

        per_spm[spm_type] = {
            "n": len(deg_results),
            "paired": paired,
            "accuracy_tol0": deg_acc["accuracy_tol0"],
            "accuracy_tol2": deg_acc["accuracy_tol2"],
            "degradation_pp": round(bl_acc["accuracy_tol0"] - deg_acc["accuracy_tol0"], 2),
            "degradation_rate": round(b_correct_d_wrong / paired * 100, 2) if paired > 0 else 0,
            "p_value": round(mcnemar_exact(b_correct_d_wrong, b_wrong_d_correct), 4),
            "cohens_h": round(cohens_h(p1, p2), 4),
        }

    return per_spm


# ======================================================================
# LaTeX table generation (comprehensive)
# ======================================================================

def generate_latex_tables(all_analyses: dict, all_degradations: dict,
                          all_fp: dict, all_per_spm: dict) -> str:
    """Generate comprehensive LaTeX tables for the paper."""
    latex = []

    # ---- Table 1: Overall accuracy by model ----
    latex.append("% Table 1: Overall Accuracy by Model")
    latex.append("\\begin{table}[h]")
    latex.append("\\centering")
    latex.append("\\caption{Fault Localization Accuracy by Model}")
    latex.append("\\label{tab:overall_accuracy}")
    latex.append("\\begin{tabular}{lrrrr}")
    latex.append("\\toprule")
    latex.append("Model & N & Acc (tol=0) & 95\\% CI & Acc (tol=2) \\\\")
    latex.append("\\midrule")

    for model_key, analysis in sorted(all_analyses.items()):
        overall = analysis.get("overall", {})
        n = overall.get("total", 0)
        acc0 = overall.get("accuracy_tol0", 0)
        ci0 = overall.get("ci_tol0", (0, 0))
        acc2 = overall.get("accuracy_tol2", 0)
        model_name = model_key.split("_")[0]
        latex.append(
            f"{model_name} & {n} & {acc0:.1f}\\% & "
            f"[{ci0[0]:.1f}, {ci0[1]:.1f}] & {acc2:.1f}\\% \\\\"
        )

    latex.append("\\bottomrule")
    latex.append("\\end{tabular}")
    latex.append("\\end{table}")
    latex.append("")

    # ---- Table 2: Baseline vs Degraded with McNemar's and effect size ----
    latex.append("% Table 2: Degradation Analysis (McNemar's + Effect Size)")
    latex.append("\\begin{table}[h]")
    latex.append("\\centering")
    latex.append("\\caption{Accuracy Degradation After Semantic-Preserving Mutations}")
    latex.append("\\label{tab:degradation}")
    latex.append("\\begin{tabular}{lrrrrrl}")
    latex.append("\\toprule")
    latex.append("Model & Baseline & Degraded & $\\Delta$ & $p$-value & Cohen's $h$ & Sig. \\\\")
    latex.append("\\midrule")

    for model_key in sorted(all_degradations.keys()):
        deg = all_degradations[model_key]
        if deg.get("paired", 0) == 0:
            continue
        model_name = model_key.split("_")[0]
        bl = deg["baseline_accuracy_tol0"]
        dg = deg["degraded_accuracy_tol0"]
        delta = deg["degradation_pp"]
        p = deg["mcnemar_p_value"]
        h = deg["cohens_h"]
        sig = "$^{***}$" if p < 0.001 else ("$^{**}$" if p < 0.01 else ("$^{*}$" if p < 0.05 else "n.s."))
        p_str = f"$<$0.001" if p < 0.001 else f"{p:.3f}"
        latex.append(
            f"{model_name} & {bl:.1f}\\% & {dg:.1f}\\% & "
            f"{delta:+.1f}pp & {p_str} & {h:.3f} & {sig} \\\\"
        )

    latex.append("\\bottomrule")
    latex.append("\\end{tabular}")
    latex.append("\\vspace{2mm}")
    latex.append("\\footnotesize{$^{*}p<0.05$, $^{**}p<0.01$, $^{***}p<0.001$}")
    latex.append("\\end{table}")
    latex.append("")

    # ---- Table 3: Per-SPM degradation (for models with enough data) ----
    for model_key, spm_data in sorted(all_per_spm.items()):
        if not spm_data:
            continue
        model_name = model_key.split("_")[0]
        latex.append(f"% Table 3: Per-SPM Degradation for {model_name}")
        latex.append("\\begin{table}[h]")
        latex.append("\\centering")
        latex.append(f"\\caption{{Per-SPM Degradation for {model_name}}}")
        latex.append(f"\\label{{tab:per_spm_{model_name.lower()}}}")
        latex.append("\\begin{tabular}{lrrrrl}")
        latex.append("\\toprule")
        latex.append("SPM Type & N & Acc (tol=0) & $\\Delta$ & Cohen's $h$ & Sig. \\\\")
        latex.append("\\midrule")

        for spm_type in sorted(spm_data.keys(), key=lambda x: spm_data[x].get("degradation_pp", 0), reverse=True):
            s = spm_data[spm_type]
            p = s.get("p_value", 1.0)
            sig = "$^{***}$" if p < 0.001 else ("$^{**}$" if p < 0.01 else ("$^{*}$" if p < 0.05 else "n.s."))
            spm_display = spm_type.replace("_", " ").title()
            latex.append(
                f"{spm_display} & {s['n']} & {s['accuracy_tol0']:.1f}\\% & "
                f"{s['degradation_pp']:+.1f}pp & {s['cohens_h']:.3f} & {sig} \\\\"
            )

        latex.append("\\bottomrule")
        latex.append("\\end{tabular}")
        latex.append("\\end{table}")
        latex.append("")

    # ---- Table 4: False Positive Rates ----
    latex.append("% Table 4: False Positive Rates")
    latex.append("\\begin{table}[h]")
    latex.append("\\centering")
    latex.append("\\caption{False Positive Rates (Clean Code Control Arm)}")
    latex.append("\\label{tab:false_positives}")
    latex.append("\\begin{tabular}{lrrr}")
    latex.append("\\toprule")
    latex.append("Model & N & FP Rate & 95\\% CI \\\\")
    latex.append("\\midrule")

    for model_key, fp in sorted(all_fp.items()):
        if fp.get("total", 0) == 0:
            continue
        model_name = model_key.split("_")[0]
        ci = fp.get("ci", (0, 0))
        latex.append(
            f"{model_name} & {fp['total']} & {fp['fp_rate']:.1f}\\% & "
            f"[{ci[0]:.1f}, {ci[1]:.1f}] \\\\"
        )

    latex.append("\\bottomrule")
    latex.append("\\end{tabular}")
    latex.append("\\end{table}")

    return "\n".join(latex)


# ======================================================================
# ASCII figures for terminal/markdown
# ======================================================================

def print_degradation_summary(model_key: str, per_spm: dict, degradation: dict):
    """Print a visual degradation summary for a model."""
    model_name = model_key.split("_")[0]
    print(f"\n  {'─' * 56}")
    print(f"  {model_name}: SPM Degradation Summary")
    print(f"  {'─' * 56}")

    if degradation.get("paired", 0) > 0:
        bl = degradation["baseline_accuracy_tol0"]
        dg = degradation["degraded_accuracy_tol0"]
        p = degradation["mcnemar_p_value"]
        h = degradation["cohens_h"]
        sig = "***" if p < 0.001 else ("**" if p < 0.01 else ("*" if p < 0.05 else "n.s."))
        print(f"  Overall: {bl:.1f}% → {dg:.1f}% ({dg-bl:+.1f}pp) "
              f"p={p:.4f} h={h:.3f} {sig}")

    if per_spm:
        print(f"\n  {'SPM Type':<25s} {'Acc':>6s} {'Δpp':>7s} {'h':>7s} {'Sig':>5s}")
        print(f"  {'─'*25} {'─'*6} {'─'*7} {'─'*7} {'─'*5}")
        for spm in sorted(per_spm.keys(), key=lambda x: per_spm[x].get("degradation_pp", 0), reverse=True):
            s = per_spm[spm]
            p = s.get("p_value", 1.0)
            sig = "***" if p < 0.001 else ("**" if p < 0.01 else ("*" if p < 0.05 else ""))
            print(f"  {spm:<25s} {s['accuracy_tol0']:5.1f}% {s['degradation_pp']:+6.1f} "
                  f"{s['cohens_h']:6.3f} {sig:>5s}")


def print_false_positive_deep_dive(model_key: str, fp: dict):
    """Print detailed false positive analysis."""
    model_name = model_key.split("_")[0]
    if fp.get("total", 0) == 0:
        return
    print(f"\n  {'─' * 56}")
    print(f"  {model_name}: False Positive Analysis")
    print(f"  {'─' * 56}")
    print(f"  Overall FP rate: {fp['fp_rate']:.1f}% ({fp['false_positives']}/{fp['total']})")
    print(f"  95% CI: [{fp['ci'][0]:.1f}%, {fp['ci'][1]:.1f}%]")

    clean = fp.get("clean_code", {})
    spm = fp.get("spm_code", {})
    if clean.get("total", 0) > 0:
        print(f"  Clean code (no SPM): {clean['fp_rate']:.1f}% ({clean['fp']}/{clean['total']})")
    if spm.get("total", 0) > 0:
        print(f"  SPM'd code (no SAM): {spm['fp_rate']:.1f}% ({spm['fp']}/{spm['total']})")

    fp_by_spm = fp.get("fp_by_spm_type", {})
    if fp_by_spm:
        print(f"\n  {'SPM Type':<25s} {'FP Rate':>8s} {'N':>5s}")
        print(f"  {'─'*25} {'─'*8} {'─'*5}")
        for spm_type, data in sorted(fp_by_spm.items(), key=lambda x: x[1].get("fp_rate", 0), reverse=True):
            print(f"  {spm_type:<25s} {data['fp_rate']:6.1f}% {data['total']:5d}")

    dist = fp.get("predicted_line_distribution", {})
    if dist:
        print(f"\n  Hallucinated bug locations: mean={dist['mean']}, "
              f"median={dist['median']}, range=[{dist['min']}, {dist['max']}]")


# ======================================================================
# Main
# ======================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Results aggregation for Agent Evaluation Experiment"
    )
    parser.add_argument("--latex", action="store_true",
                        help="Generate LaTeX tables")
    parser.add_argument("--include-checkpoints", action="store_true",
                        help="Include in-progress results from checkpoints")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  RESULTS AGGREGATION & STATISTICAL ANALYSIS")
    print("=" * 60)

    all_data = load_all_results()

    # Optionally load checkpoint results for in-progress runs
    if args.include_checkpoints:
        # Collect model names already loaded from final results
        loaded_models = {data.get("model", "") for data in all_data.values()}
        for ckpt_name in ["qwen_coder_3b", "qwen_coder_1.5b", "qwen_coder_7b"]:
            key_check = f"{ckpt_name}_minimal"
            # Skip if this model's final results are already loaded
            if key_check in all_data or ckpt_name.replace("_", "-") in loaded_models:
                continue
            ckpt_data = load_checkpoint_results(ckpt_name)
            if ckpt_data:
                all_data[key_check] = ckpt_data
                print(f"  Loaded checkpoint: {ckpt_name} ({len(ckpt_data['results'])} results)")

    if not all_data:
        print("\n  No result files found in", RESULTS_DIR)
        return

    all_analyses = {}
    all_matrices = {}
    all_fp = {}
    all_degradations = {}
    all_per_spm = {}

    for model_key, data in all_data.items():
        results = data.get("results", [])
        print(f"\n  Analyzing: {model_key} ({len(results)} results)")

        analysis = analyze_by_dimensions(results)
        all_analyses[model_key] = analysis

        # Degradation matrix
        matrix = compute_degradation_matrix(results)
        all_matrices[model_key] = matrix

        # Overall degradation with effect sizes
        degradation = compute_overall_degradation(results)
        all_degradations[model_key] = degradation

        # Per-SPM degradation
        per_spm = compute_per_spm_degradation(results)
        all_per_spm[model_key] = per_spm

        # False positives (deep-dive)
        fp = compute_false_positive_rate(results)
        all_fp[model_key] = fp

        # Print summary
        overall = analysis["overall"]
        print(f"    Overall: tol0={overall['accuracy_tol0']:.1f}% "
              f"CI={overall['ci_tol0']}, "
              f"tol2={overall['accuracy_tol2']:.1f}% "
              f"CI={overall['ci_tol2']}")

        by_type = analysis.get("by_task_type", {})
        for tt, stats in sorted(by_type.items()):
            print(f"    {tt}: tol0={stats['accuracy_tol0']:.1f}% "
                  f"(N={stats['total']})")

        # Overall degradation
        if degradation.get("paired", 0) > 0:
            sig = "YES" if degradation["significant"] else "no"
            print(f"    Degradation: {degradation['degradation_pp']:+.1f}pp "
                  f"(p={degradation['mcnemar_p_value']:.4f}, "
                  f"h={degradation['cohens_h']:.3f}, sig={sig})")

        # SPM degradation
        sig_count = sum(1 for v in matrix.values() if v.get("significant"))
        print(f"    Significant SAM×SPM degradations: {sig_count}/{len(matrix)}")

        if fp["total"] > 0:
            print(f"    False positive rate: {fp['fp_rate']:.1f}% "
                  f"(N={fp['total']})")

    # Print detailed summaries
    for model_key in sorted(all_per_spm.keys()):
        print_degradation_summary(model_key, all_per_spm[model_key], all_degradations[model_key])
        print_false_positive_deep_dive(model_key, all_fp[model_key])

    # Save comprehensive analysis
    output = {
        "timestamp": datetime.now().isoformat(),
        "analyses": {},
        "overall_degradations": {},
        "degradation_matrices": {},
        "per_spm_degradation": {},
        "false_positive_rates": {},
    }

    for k, v in all_analyses.items():
        output["analyses"][k] = json.loads(json.dumps(v, default=str))
    for k, v in all_degradations.items():
        output["overall_degradations"][k] = json.loads(json.dumps(v, default=str))
    for k, v in all_matrices.items():
        output["degradation_matrices"][k] = json.loads(json.dumps(v, default=str))
    for k, v in all_per_spm.items():
        output["per_spm_degradation"][k] = json.loads(json.dumps(v, default=str))
    for k, v in all_fp.items():
        output["false_positive_rates"][k] = json.loads(json.dumps(v, default=str))

    agg_file = os.path.join(RESULTS_DIR, "comprehensive_analysis.json")
    with open(agg_file, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n  Saved: {agg_file}")

    if args.latex:
        latex = generate_latex_tables(all_analyses, all_degradations, all_fp, all_per_spm)
        latex_file = os.path.join(ARTIFACTS_DIR, "paper_tables.tex")
        with open(latex_file, "w") as f:
            f.write(latex)
        print(f"  LaTeX tables saved: {latex_file}")
        print("\n" + latex)


if __name__ == "__main__":
    main()
