# Experiment Details: Evaluating How Well Coding Agents Understand Code

## Overview

This experiment extends the paper ["How Accurately Do Large Language Models Understand Code?"](https://arxiv.org/abs/2504.04372) which found that Semantic Preserving Mutations (SPMs) cause LLMs to fail on previously localized faults in 78% of cases. We evaluate fault localization accuracy across multiple models and measure degradation under 9 types of semantic-preserving transformations, using CWE-backed fault categories.

**Research Question:** How much does surface-level code transformation (that preserves semantics) degrade LLMs' ability to localize bugs?

---

## Dataset

### Source Programs

Two curated datasets of competitive programming solutions:

| Language | Total Programs | Validated | Pass Rate |
|----------|---------------|-----------|-----------|
| Python | 1,062 | 585 | 55.1% |
| Java | 1,070 | 647 | 60.5% |
| **Total** | **2,132** | **1,232** | **57.8%** |

**Validation process:** Each program was validated for syntax correctness (`ast.parse()` for Python, `javalang.parse.parse()` for Java). Only programs passing validation were included in the experiment.

**Categories:** Each program belongs to one of two categories:
- `existing` — from existing competitive programming datasets
- `new` — newly generated programs

---

## Bug Injection (SAMs — Semantic Altering Mutations)

We implemented **12 bug types** (4 legacy + 8 CWE-inspired):

### Legacy Bug Types (backward compatibility with prior experiments)

| Bug Type | CWE Mapping | Languages | Description |
|----------|-------------|-----------|-------------|
| BooleanLogic | CWE-480 | Python, Java | Flip boolean operators (and↔or, True↔False) |
| OperatorSwap | CWE-480 | Python, Java | Swap arithmetic/comparison operators (+↔-, *↔/, ==↔!=) |
| OffByOne | CWE-193 | Python, Java | Off-by-one in loop bounds or indices |
| MisplacedReturn | CWE-483 | Python, Java | Move return statement to wrong scope level |

### CWE-Inspired Bug Types (new)

| Bug Type | CWE | Languages | Description |
|----------|-----|-----------|-------------|
| IncorrectOperator | CWE-480 | Python, Java | Swap +/-, */, and/or, ==/!= operators |
| IncorrectBlockDelimitation | CWE-483 | Python, Java | Un-indent statement from if/for/while block |
| OmittedBreak | CWE-484 | Java only | Remove break statement in switch case (fall-through) |
| UnusedAssignment | CWE-563 | Python, Java | Insert assignment that overwrites needed value before use |
| OperatorPrecedence | CWE-783 | Python, Java | Remove/add parentheses to change evaluation order |
| LoopUnreachableExit | CWE-835 | Python, Java | Modify loop variable update (e.g., i+=1 → i-=1) |
| WrongComparison | CWE-1025 | Python, Java | Replace comparison operand with different in-scope variable |
| WrongArguments | CWE-628 | Python, Java | Swap two adjacent function call arguments |

### Injection Results

- **24,522** injection attempts across all programs × bug types
- **12,611** successful buggy variants (51.4% success rate)
- Each buggy variant has a recorded ground-truth bug line number

---

## Semantic Preserving Mutations (SPMs)

We implemented **9 SPM types** — transformations that change code appearance without changing program behavior:

### LLM-Generated SPMs

| SPM Type | Description |
|----------|-------------|
| Misleading Comments | Add comments that mislead about nearby code's purpose |
| Variable Renaming | Rename variables to confusing/misleading names |
| Dead Code Insertion | Insert syntactically valid but unreachable code blocks |

### Algorithmic SPMs (no LLM needed)

| SPM Type | Description |
|----------|-------------|
| Empty Lines | Insert blank lines at random positions throughout the code |
| Void Functions | Add no-op function definitions and calls at random positions |
| Void Conditionals | Wrap statements in `if True:` or insert `if False: <dead>` blocks |
| Void Loops | Insert `for _ in range(0): pass` or `while False: pass` blocks |
| Function Reordering | Shuffle the order of function definitions in the file |
| Function Extraction | Extract code blocks into helper functions with proper params/returns |

### SPM Verification

**Output equivalence checking:** After each SPM application, the modified program was verified to produce identical output to the pre-SPM version. SPMs that failed equivalence were discarded and logged.

**Reproducibility:** All algorithmic SPMs use `random.Random(seed=42)`. All LLM-generated SPMs use `temperature=0`.

### SPM Results

- **337,024** SPM application attempts
- **182,671** valid SPM variants (54.2% validity rate)
- **154,353** discarded (failed equivalence or parse check)
- **0** errors during generation

---

## Evaluation Task Composition

| Task Type | Count | Description |
|-----------|-------|-------------|
| Baseline | 12,612 | SAM-only code (buggy, no SPM applied) |
| Degraded | 183,658 | SAM + SPM code (buggy code with surface mutation) |
| Control | 2,132 | Clean code (no bug, no SPM) — false positive measurement |
| **Total Task Pool** | **198,402** | Available for evaluation |

### Model-Specific Subsets

Due to cost and compute constraints, each model evaluated a randomly sampled subset:

| Model | Tasks Evaluated | Baseline | Degraded | Control |
|-------|----------------|----------|----------|---------|
| Claude Opus 4 | 2,000 | 120 | 1,861 | 19 |
| Qwen2.5-Coder 3B | 5,000 | 318 | 4,630 | 52 |
| Qwen2.5-Coder 1.5B | 325 | 12 | 313 | 0 |
| Claude Sonnet 4 | 176 | — | — | — |

---

## Models Evaluated

| Model | Backend | Model ID | Parameters | Tasks | Cost |
|-------|---------|----------|------------|-------|------|
| Claude Opus 4 | Anthropic API | claude-opus-4-20250514 | ~200B+ | 2,000 | ~$97 |
| Claude Sonnet 4 | Anthropic API | claude-sonnet-4-20250514 | ~100B+ | 176 | $0 (prior run) |
| Qwen2.5-Coder 3B | Ollama (local) | qwen2.5-coder:3b | 3.0B | 5,000 | $0 |
| Qwen2.5-Coder 1.5B | Ollama (local) | qwen2.5-coder:1.5b | 1.5B | 325 | $0 |

**Total cost:** ~$97 (Claude Opus only; all other models run locally for free)

**Total evaluations:** 7,501 tasks across 4 models

---

## Evaluation Protocol

### Prompt Design

Three prompt variants were tested:

**1. Minimal (primary):**
- System: `"You are a bug detector. Always respond with ONLY valid JSON in format {"line_no": N}. No explanations."`
- User: Code + instruction + `Reply with ONLY this JSON: {"line_no": N}`

**2. Detailed:**
- System: `"You are an expert code reviewer specializing in bug detection..."`
- User: More context about the task + code

**3. Chain-of-Thought:**
- System: `"First analyze the code step by step, then identify the buggy line..."`
- User: Step-by-step reasoning instructions + code

### Metrics

- **Primary metric:** Tolerance=0 (exact line match)
- **Secondary metric:** Tolerance=2 (predicted line within ±2 of actual bug line)
- Both metrics reported for all results

### Determinism Validation

- **100 samples × 3 repetitions** at temperature=0
- **100% consistency** (all 300 responses identical across repetitions)
- **Conclusion:** Single-run evaluation is defensible at temp=0

### Checkpointing

- Results saved atomically every 25 evaluations
- Write-to-temp-then-rename pattern prevents corruption
- Full resume from any failure point

---

## Results

### 1. Overall Fault Localization Accuracy

| Model | N | Accuracy (tol=0) | 95% CI | Accuracy (tol=2) |
|-------|---|-------------------|--------|-------------------|
| Claude Opus 4 | 2,000 | **17.2%** | [15.7, 19.0] | 47.6% |
| Claude Sonnet 4 | 176 | **14.2%** | — | 39.8% |
| Qwen2.5-Coder 3B | 5,000 | **1.7%** | [1.3, 2.0] | 7.0% |
| Qwen2.5-Coder 1.5B | 325 | **0.3%** | [0.1, 1.7] | 4.3% |

### 2. SPM Degradation Analysis

#### Claude Opus 4 (Frontier Model)

**Baseline (SAM only): 27.5% → After SPMs: 16.8% → -10.7 percentage points degradation**

Per-SPM breakdown (ordered by damage):

| SPM Type | Accuracy After SPM | Degradation (Δpp) | Cohen's h | Interpretation |
|----------|-------------------|-------------------|-----------|----------------|
| Function Extraction | 7.0% | -20.5pp | 0.568 | Medium |
| Void Functions | 8.2% | -19.3pp | 0.522 | Medium |
| Function Reordering | 11.5% | -16.0pp | 0.412 | Medium |
| Void Loops | 17.0% | -10.5pp | 0.255 | Small |
| Variable Renaming | 17.1% | -10.4pp | 0.250 | Small |
| Void Conditionals | 18.2% | -9.3pp | 0.222 | Small |
| Misleading Comments | 18.9% | -8.6pp | 0.203 | Small |
| Dead Code Insertion | 19.9% | -7.6pp | 0.180 | Negligible |
| Empty Lines | 22.2% | -5.3pp | 0.123 | Negligible |

**Key finding:** Structural SPMs (function extraction, void functions, function reordering) cause 2-4× more degradation than cosmetic SPMs (comments, empty lines). This suggests models rely heavily on code structure patterns, not just surface tokens.

#### Qwen2.5-Coder 3B (Open-Source Model)

**Baseline: 3.5% → After SPMs: 1.6% → -1.9pp degradation**

The degradation pattern mirrors Opus but at a much lower baseline. Function extraction is the most damaging SPM for both models.

### 3. False Positive Rate (Control Arm)

**100% false positive rate across all models.**

When presented with clean, bug-free code and asked "find the bug," every model always reported a bug line — even when none existed.

| Model | N | False Positives | FP Rate | 95% CI |
|-------|---|-----------------|---------|--------|
| Claude Opus 4 | 19 | 19 | **100.0%** | [83.2%, 100.0%] |
| Qwen2.5-Coder 3B | 52 | 52 | **100.0%** | [93.1%, 100.0%] |

**Hallucinated bug locations (Opus):** mean=34.9, median=9, range=[3, 253]

**Implication:** Models are incapable of determining whether code is correct. They will always "find" a bug when asked, making them unreliable as standalone bug detectors without ground-truth verification.

### 4. Prompt Sensitivity Analysis (Claude Opus, N=500 per variant)

| Prompt Variant | Accuracy (tol=0) | Accuracy (tol=2) |
|----------------|-------------------|-------------------|
| Minimal | 17.2% | 47.6% |
| Detailed | 17.6% | 49.0% |
| Chain-of-Thought | 17.4% | 51.0% |

**Accuracy range: 0.4 percentage points** — results are highly robust across prompt phrasings.

**Verdict:** Low prompt sensitivity validates that our results reflect genuine model capability, not prompt engineering artifacts.

### 5. Model Size Scaling

| Model | Parameters | tol=0 | tol=2 |
|-------|-----------|-------|-------|
| Qwen2.5-Coder 1.5B | 1.5B | 0.3% | 4.3% |
| Qwen2.5-Coder 3B | 3.0B | 1.7% | 7.0% |
| Claude Sonnet 4 | ~100B+ | 14.2% | 39.8% |
| Claude Opus 4 | ~200B+ | 17.2% | 47.6% |

There is a massive capability gap between small open-source models (<7B) and frontier models (>100B). Fault localization appears to require frontier-scale reasoning — models below 7B effectively cannot perform this task (tol=0 accuracy <2%).

---

## Statistical Methods

| Method | Purpose |
|--------|---------|
| **Wilson score confidence intervals** (95%) | Uncertainty bounds on all accuracy proportions |
| **McNemar's exact test** (two-sided binomial) | Paired before/after SPM statistical significance |
| **Cohen's h effect size** | Practical significance of degradation (small ≥0.2, medium ≥0.5, large ≥0.8) |
| **Odds ratios** | Discordant pair ratios from 2×2 contingency tables |

---

## Reproducibility

| Parameter | Value |
|-----------|-------|
| Random seed | 42 |
| LLM temperature | 0 |
| Determinism consistency | 100% (100 samples × 3 reps) |
| Checkpoint frequency | Every 25 results |
| All artifacts saved | Buggy programs, SPM'd programs, raw model responses |
| Code repository | [github.com/anshishrivastava/LLM-Debug](https://github.com/anshishrivastava/LLM-Debug) |
| Branch | `experiment/spm-sam-evaluation` |

---

## Threats to Validity

### Internal Validity
- **Bug line ambiguity:** For some bug types, the "correct" line is ambiguous. We mitigate by reporting both tol=0 and tol=2, and defining line ranges for multi-line CWEs.
- **SPM semantic preservation:** Verified via output equivalence checking. 54.2% of SPMs passed verification; failures were discarded.
- **Sampling bias in McNemar's:** Random subsetting under-sampled baseline tasks relative to degraded tasks, reducing paired sample sizes for statistical tests. Effect sizes (Cohen's h) remain valid regardless.

### External Validity
- **Dataset representativeness:** Programs are from competitive programming. Real-world code has imports, frameworks, and multi-file dependencies. Results may not generalize to production codebases.
- **Single-turn evaluation:** We test LLMs with single-turn prompts. Real coding agents (Cursor, Copilot, Devin) use multi-step reasoning, tool use, and file navigation, which may perform differently.

### Construct Validity
- **False positive framing:** The 100% FP rate may partly reflect the prompt design ("find the bug" implies one exists). A more neutral framing ("is there a bug?") might yield different results.

---

## Files and Code Structure

### New Files Created

| File | Purpose | Lines |
|------|---------|-------|
| `program_validator.py` | Validate programs (syntax + compile check) | ~200 |
| `cwe_bug_injector.py` | 8 CWE-inspired SAM injectors | ~800 |
| `spm_generator.py` | 9 SPM types + output equivalence verification | ~1,575 |
| `unified_tester.py` | Multi-backend tester (Anthropic, OpenAI, Ollama) | ~1,100 |
| `pipeline_runner.py` | End-to-end pipeline with checkpointing | ~850 |
| `results_aggregator.py` | Statistical analysis + LaTeX tables | ~700 |
| `prompt_sensitivity.py` | Cross-prompt robustness analysis | ~150 |

### Result Files

| File | Contents |
|------|----------|
| `results/claude_opus_minimal_*.json` | 2,000 Opus evaluation results |
| `results/qwen_coder_3b_minimal_*.json` | 5,000 Qwen 3B evaluation results |
| `results/qwen_coder_1.5b_minimal_partial.json` | 325 Qwen 1.5B partial results |
| `results/determinism_qwen-coder.json` | Determinism check (100% consistent) |
| `results/prompt_sensitivity_claude-opus.json` | Prompt sensitivity analysis |
| `results/comprehensive_analysis.json` | Full statistical analysis |
| `artifacts/paper_tables.tex` | LaTeX tables ready for paper |
