# Experiment Plan: Evaluating How Well Coding Agents Understand Code

## Context

This experiment extends the paper ["How Accurately Do Large Language Models Understand Code?"](https://arxiv.org/abs/2504.04372) which found that **Semantic Preserving Mutations (SPMs) cause LLMs to fail on previously localized faults in 78% of cases**, demonstrating heavy reliance on non-semantic features.

**Goal**: Produce ~500K evaluation tasks for a research paper measuring how coding agents' code understanding degrades under semantic-preserving transformations, using CWE-backed fault categories.

### Key Parameters
- **Line tolerance**: **0** (exact line match — no tolerance)
- **SAM strategy**: Keep existing 4 legacy SAMs + add 8 CWE-inspired SAMs (12 total)
- **SPM types**: Expand from 3 → 8 types
- **Models**: Claude Opus, GPT-4o, GPT-4o-mini, Ollama local models (Claude Sonnet baseline exists)
- **Compute**: Local machine + LLM APIs
- **Target scale**: ~500K total evaluation tasks

---

## Experiment Flow (Revised — All Gaps Addressed)

```
Step 1: VALIDATE             Clean programs → compile/run + output capture → keep runnable ones
                                      ↓
Step 2: INJECT SAMs          For each valid program × each applicable SAM → buggy program
                             Record: bug_line, bug_line_range (for multi-line CWEs)
                                      ↓
Step 3: APPLY SPMs           For each buggy program × each of 8 SPMs → SPM'd buggy program
                             VERIFY: run SPM'd program → assert output == buggy program output
                             (proves SPM preserved semantics; discard if not)
                                      ↓
Step 4: BASELINE TEST        Ask agent to find bug in SAM-only code (×3 runs, temp=0)
                             → record accuracy at BOTH tolerance=0 AND tolerance=2
                                      ↓
Step 5: DEGRADED TEST        Ask agent to find bug in SAM+SPM code (×3 runs, temp=0)
                             → record accuracy at BOTH tolerance=0 AND tolerance=2
                                      ↓
Step 6: FALSE POSITIVE TEST  Ask agent to find bug in CLEAN code (no SAM, no SPM)
                             Ask agent to find bug in CLEAN+SPM code (SPM only, no SAM)
                             → measure false positive rate
                                      ↓
Step 7: AGGREGATE            McNemar's test + 95% CIs for paired comparisons
                             Stratify by: model, SAM, SPM, language, complexity, position
```

### Scale Math (~500K+ tasks) — Single-run after determinism check
- ~2,132 programs → ~1,800 after validation
- × ~7 applicable SAMs per program (avg) ≈ **~13,000 buggy variants**
- Each variant: 1 baseline + 8 SPM evaluations = **9 tasks per variant per model**
- ~13,000 × 9 = ~117,000 tasks per model
- + Control arm: ~1,800 clean × (1 + 8 SPMs) = ~16,200 per model
- Per model total: **~133K tasks**
- **Budget-aware model allocation**:
  - Full run (~133K tasks): GPT-4o-mini + 1 Ollama model (cheap/fast)
  - Subset (~30K tasks): Claude Opus (expensive, representative subset)
  - Total: **~300K-500K tasks**

### Execution Timeline (target: 12pm noon tomorrow)
```
Hour 0:      Create experiment branch, persist plan to repo
Hour 0-1:    Implement config refactor + program validator
Hour 1-3:    Implement CWE SAM injectors + new SPMs
Hour 3-4:    Implement unified tester + pipeline runner (with checkpointing)
Hour 4-4.5:  Run determinism check (100 samples × 3 reps, temp=0)
Hour 4.5-5:  Run program validation + SAM injection + SPM application (CPU, fast)
Hour 5-12:   Run LLM evaluations — all models launched concurrently:
             → GPT-4o-mini full set: ~4.5 hrs (done by hour ~10)
             → Claude Opus subset: ~3 hrs (done by hour ~8)
             → Ollama local subset: runs in background
Hour 12-14:  Results aggregation + statistical analysis
Hour 14:     12pm noon — results ready
```

**API throughput estimates:**
- GPT-4o-mini: ~500 req/min → 133K tasks ≈ 4.4 hours ✓
- Claude Opus: ~60 req/min → 10K task subset ≈ 2.8 hours ✓
- Ollama local: ~5 req/min → 2K task subset ≈ 6.7 hours (run in background)

### Precise Cost Estimation

**Per-task token usage** (estimated):
- Input: system prompt (~50) + instruction (~50) + code (~3,000 avg) + prompt (~30) ≈ **3,130 tokens**
- Output: `{"line_no": N}` ≈ **20 tokens**

| Model | Price (input/output per 1M) | Tasks | Input Cost | Output Cost | **Total** |
|-------|----------------------------|-------|------------|-------------|-----------|
| GPT-4o-mini (full) | $0.15 / $0.60 | 133K | $62 | $2 | **$64** |
| GPT-4o-mini (prompt sensitivity) | $0.15 / $0.60 | 10K | $5 | $0.12 | **$5** |
| Claude Opus (subset) | $15 / $75 | 10K | $470 | $15 | **$485** |
| Claude Opus (full — NOT recommended) | $15 / $75 | 133K | $6,240 | $200 | **$6,440** |
| Ollama local | free | 2K | $0 | $0 | **$0** |
| Determinism check | $0.15 / $0.60 | 300 | $0.14 | $0.01 | **$0.15** |

### Budget-Optimal Model × Scale Design: **~$555 total**

| Model | Role in Paper | Tasks | Cost | Time |
|-------|---------------|-------|------|------|
| **GPT-4o-mini** | Main results (full coverage, statistically robust) | 133K full + 10K prompts | $69 | ~4.8 hrs |
| **Claude Opus** | "Even frontier models degrade" (representative subset) | 10K subset | $485 | ~2.8 hrs |
| **Ollama (qwen2.5-coder)** | Open-source model comparison | 2K subset | $0 | ~6.7 hrs |
| **Claude Sonnet** | Mid-tier baseline (already exists) | 176 (existing) | $0 | done |
| | | **Total: ~145K tasks** | **~$555** | |

**Why this is optimal for the paper:**
1. **GPT-4o-mini full set** → statistically robust main results table (all SAMs × all SPMs)
2. **Claude Opus subset** → headline finding: "even the most capable model shows X% degradation"
3. **Ollama** → open-source comparison, shows effect isn't API-model-specific
4. **Claude Sonnet existing** → 4th data point at zero additional cost
5. **4 models across 3 capability tiers** (frontier/mid/open-source) — strong paper narrative

### Intermediate Result Persistence Strategy
Every checkpoint is a JSON file that the pipeline can resume from:
```
results/
├── checkpoints/
│   ├── validation_checkpoint.json          # validated program list
│   ├── injection_checkpoint.json           # SAM injection status per program
│   ├── spm_checkpoint.json                 # SPM application status per program
│   ├── gpt4omini_progress.json             # eval results so far (append-only)
│   ├── claude_opus_progress.json           # eval results so far (append-only)
│   └── ollama_progress.json                # eval results so far (append-only)
├── gpt4omini_results_final.json
├── claude_opus_results_final.json
└── aggregated_analysis.json
```

**Persistence rules:**
- Save after every **batch of 25 results** (not just at end)
- Each checkpoint has: `{completed_ids: [...], results: [...], timestamp, resume_from}`
- On restart: load checkpoint → skip completed_ids → continue from where we left off
- If API rate limit hits → exponential backoff (1s, 2s, 4s, 8s, max 60s) → auto-resume
- If crash → re-run same command → pipeline detects checkpoint → resumes

---

## Phase 0: Program Validation (NEW)

**File**: Create `agent_evaluation_experiment/program_validator.py`

### For Python programs:
- `ast.parse()` — check syntax validity
- `compile()` — check compilability
- Optionally: execute with timeout to verify runtime behavior

### For Java programs:
- Syntax check via `javalang.parse.parse()` or shell out to `javac`
- Compile check (requires JDK available locally)

### Output:
- `validated_programs.json` — list of programs that pass validation
- Programs that fail validation are excluded from all subsequent phases
- Log why each program failed (syntax error, runtime error, etc.)

---

## Phase 1: CWE-Inspired SAM Implementation

**File**: Create `agent_evaluation_experiment/cwe_bug_injector.py`
**Modify**: `agent_evaluation_experiment/config.py`

### Tier 1 CWEs (Priority — implement first)

| CWE | Name | Python | Java | Implementation |
|-----|------|--------|------|----------------|
| CWE-480 | Incorrect Operator | Yes | Yes | Subsumes existing OperatorSwap + BooleanLogic; swap `+/-`, `*/`, `and/or`, `==/!=` |
| CWE-483 | Incorrect Block Delimitation | Yes | Yes | Python: un-indent statement from if/for/while block; Java: misplace closing brace |
| CWE-484 | Omitted Break in Switch | No | Yes | Remove `break` from switch case to create fall-through |
| CWE-563 | Unused Variable Assignment | Yes | Yes | Insert assignment that overwrites a needed value before its use |
| CWE-783 | Operator Precedence Error | Yes | Yes | Remove/add parentheses to change evaluation order |
| CWE-835 | Loop with Unreachable Exit | Yes | Yes | Modify loop variable update (e.g., `i += 1` -> `i -= 1`) |
| CWE-1025 | Wrong Comparison Factors | Yes | Yes | Replace comparison operand with different in-scope variable |
| CWE-628 | Wrong Function Arguments | Yes | Yes | Swap two adjacent function call arguments |

### Relationship to existing SAMs
- Keep existing 4 SAMs for **backward compatibility** and comparison
- Map them to CWEs: BooleanLogic → CWE-480, OperatorSwap → CWE-480, OffByOne → CWE-193, MisplacedReturn → CWE-483
- New CWE SAMs are **additional**, providing broader fault coverage

### Implementation approach
- Follow existing `bug_injector.py` pattern: each injector is `(code: str) -> tuple[str | None, int | None]`
- Python injectors use `ast` module; Java injectors use `javalang` library (or regex for simpler cases)
- Each injector validates the modified code still parses (`ast.parse()` / syntax check)
- Register in `CWE_INJECTORS` dict mirroring `BUG_INJECTORS` structure

---

## Phase 2: Expand SPMs (3 → 8 types)

**File**: Create `agent_evaluation_experiment/spm_generator.py`
**Modify**: `agent_evaluation_experiment/config.py`

### Current SPMs (implemented in `generate_mutants.py`)
1. Misleading Comments (LLM-generated)
2. Variable Renaming (LLM-generated)
3. Dead Code insertion (LLM-generated)

### New SPMs to implement

| SPM | Description | Needs LLM? | Complexity |
|-----|-------------|-------------|------------|
| **Void Functions** | Add no-op function defs + calls at random positions | No | Medium |
| **Empty Lines** | Insert blank lines at random positions | No | Low |
| **Void Conditionals** | Wrap statements in `if True:` or insert `if False: <dead>` | No | Medium |
| **Void Loops** | Insert `for _ in range(0): pass` or `while False: pass` | No | Low |
| **Function Extraction** | Extract code block into helper function with proper params/returns | No (AST) | High |
| **Function Reordering** | Shuffle order of function definitions | No (AST) | Medium |

### All SPMs share this contract
```python
def apply_spm(code: str, bug_line: int, **kwargs) -> tuple[str, int]:
    """Returns (modified_code, adjusted_bug_line)"""
```

- Each SPM must adjust `bug_line` when inserting lines before the bug
- Each SPM must verify modified code still parses
- Cumulative combinations: apply multiple SPMs sequentially

---

## Phase 3: Scale the Pipeline

**Files**: Create `agent_evaluation_experiment/unified_tester.py`, `agent_evaluation_experiment/pipeline_runner.py`
**Modify**: `agent_evaluation_experiment/config.py`

### 3a. Unified Model Tester
- Single interface supporting multiple backends: `anthropic`, `openai`, `ollama`
- Async support with rate limiting for API models
- Exponential backoff for rate limit errors
- Consistent prompt template and JSON output parsing across all models

### 3b. Pipeline Runner with Checkpointing
- Phases: Inject SAMs → Apply SPMs → Test Models → Aggregate Results
- Checkpoint after each phase and each file batch
- Resume from last checkpoint on failure
- Parallel processing: `ProcessPoolExecutor` for CPU-bound phases, `asyncio` for API-bound phases
- Support chunked execution for batch processing

### 3c. Models to evaluate
- **Claude Opus** (`claude-opus-4-20250514`) — most capable, comparison against Sonnet baseline
- **GPT-4o** (`gpt-4o`) — OpenAI flagship
- **GPT-4o-mini** (`gpt-4o-mini`) — cost-effective OpenAI comparison
- **Local via Ollama**: qwen2.5-coder:7b, deepseek-coder-v2 — free, tests open-source models
- *(Claude Sonnet baseline already exists at 39.77% on 176 samples)*

### 3d. Scale estimates & execution strategy
- ~2,132 programs × (4 legacy + 8 CWE) SAMs = ~25,584 buggy variants
- × 8 SPMs = ~204,672 mutated files (full matrix, single strength)
- × 5 models = ~1M evaluations at full scale
- **Execution**: Local machine only (no ARC clusters)
  - CPU-bound phases (injection, SPM generation): `ProcessPoolExecutor` with all cores
  - API-bound phases: `asyncio` with rate limiting
  - Ollama phases: sequential or threaded, depends on GPU memory
- **Strategy**: Pilot on 200 programs × 4 CWEs × 4 SPMs × 2 models first, then scale

---

## Phase 4: Results Aggregation & Paper Figures

**File**: Create `agent_evaluation_experiment/results_aggregator.py`

### Dimensions of analysis
- **Model × SAM type**: Which fault types are hardest for each model?
- **Model × SPM type**: Which surface-level changes cause most degradation?
- **SAM × SPM interaction**: Do certain SPMs affect certain bug types more?
- **Existing vs New**: Data contamination signal across all CWE types
- **Bug location (line_no_percent)**: Positional bias analysis (the paper found "reasoning is stronger when relevant code appears earlier in context")
- **Language (Python vs Java)**: Cross-language comparison

### Outputs
- Accuracy degradation heatmaps (SAM × SPM)
- Bar charts per model comparing original vs post-SPM accuracy
- Data contamination analysis (existing vs new accuracy by CWE type)
- LaTeX tables for paper

---

## Implementation Order

### Step 0: Branch + plan persistence
- `git checkout -b experiment/spm-sam-evaluation`
- Copy this plan to `agent_evaluation_experiment/EXPERIMENT_PLAN.md` (persisted in repo)
- All experiment work happens on this branch

### Step 1: Config refactor + infrastructure
- Add CWE types, new SPM types, multi-model support, env-aware paths
- **Report both tolerance=0 and tolerance=2** (primary and secondary metrics)
- Define `bug_line_range` field for multi-line CWEs (CWE-483, CWE-563)
- Add repetition count (N=3), temperature=0, random seeds
- **File**: [config.py](agent_evaluation_experiment/config.py), `agent_tester.py`, `run_claude_experiment.py`

### Step 2: Program validator + output capture
- Validate all 2,132 programs are runnable (syntax + compile/execute)
- **Capture baseline outputs** (needed for SPM equivalence checking in Step 4)
- Filter dataset to only valid programs
- **File**: New `program_validator.py`

### Step 3: CWE SAM injectors
- Implement 8 CWE injectors for Python and Java
- For each CWE, define **ground truth line range** (not just single line) for ambiguous bugs
- Validate on 20 samples each
- **File**: New `cwe_bug_injector.py`

### Step 4: New SPMs + equivalence verification
- Implement 5 new SPMs: Empty Lines, Void Functions, Void Conditionals, Void Loops, Function Reordering, Function Extraction
- **After each SPM application, verify output equivalence** against pre-SPM program
- Discard SPM'd programs that fail equivalence → log SPM validity rate
- Set random seeds for all algorithmic SPMs; temp=0 for LLM-generated SPMs
- **File**: New `spm_generator.py`

### Step 5: Unified tester + pipeline runner
- Multi-backend model testing (anthropic, openai, ollama) with checkpointing
- **3 prompt variants** defined; primary on full set, alternates on 5K subset
- **temperature=0** for all evaluations
- **Control arm**: clean code (no SAM) and clean+SPM code → false positive measurement
- Two-phase evaluation: baseline (SAM only) → degraded (SAM+SPM)
- Save all artifacts for reproducibility
- **Files**: New `unified_tester.py`, `pipeline_runner.py`

### Step 6: Determinism check (~30 min)
- Run 100 samples × 3 repetitions at temp=0 on GPT-4o-mini
- Measure consistency rate
- If >95% consistent → single-run for all experiments (defensible in paper)
- If <95% → use N=3 with majority vote (increases time 3×)

### Step 7: Run full experiment (all models launched concurrently)
- Run SAM injection + SPM application on all validated programs (CPU-bound, fast)
- **Launch concurrently** (separate processes, each with its own checkpoint file):
  - GPT-4o-mini on full set (~133K tasks, ~4.5 hours)
  - Claude Opus on representative subset (~10K tasks, ~2.8 hours)
  - Ollama on small subset (~2K tasks, runs in background)
- Include control arm (clean code) as part of each model's run
- Each process saves every 25 results → auto-resume on failure
- Monitor: `tail -f results/checkpoints/*_progress.json`

### Step 8: Results aggregation and paper figures
- **McNemar's test** for paired before/after SPM comparisons
- **95% confidence intervals** on all accuracy numbers
- Stratify by: model, SAM type, SPM type, language, program complexity (LOC buckets), bug position
- Report: false positive rates, SPM validity rates, determinism consistency rate, prompt sensitivity
- Generate: degradation heatmaps, accuracy comparison charts, LaTeX tables
- Report prompt sensitivity analysis (3 variants on 5K subset)
- Acknowledge dataset representativeness in threats to validity
- **File**: New `results_aggregator.py`

### Future Work (post-deadline)
- Agentic evaluation (multi-turn, tool use) vs single-turn comparison
- Non-LLM baselines (Pylint, SpotBugs) for context
- Additional CWE SAMs (Tier 2)
- More models (GPT-4o, additional Ollama models)

---

## Verification Plan

1. **Program validator**: Run on all 2,132 programs, spot-check 10 rejected programs
2. **CWE injectors**: Verify on 20 samples per CWE: (a) code parses, (b) semantic change is real, (c) bug line + line range correct
3. **SPMs**: Verify on 20 samples per SPM: (a) code parses, (b) **output equivalence** confirmed, (c) bug line adjusted correctly
4. **Determinism check**: 100 samples × 3 reps at temp=0 — >95% consistency validates single-run
5. **Dual tolerance sanity**: Check tol=0 vs tol=2 on first 50 results — confirm tol=0 is meaningful
6. **False positive check**: Included in control arm — clean code and clean+SPM code
7. **Full run**: Checkpoint monitoring, cost tracking, artifact saving throughout

---

## Key Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| CWE-483 (block delimitation) in Python causes parse errors | Validate with `ast.parse()`, skip if invalid |
| Function Extraction SPM requires dataflow analysis | Start with self-contained blocks (no cross-boundary variable deps) |
| API costs (~$555 with budget-optimal design) | GPT-4o-mini full ($69), Opus 10K subset ($485), Ollama free |
| Local compute insufficient | Batch processing with checkpointing; parallelize CPU-bound work |
| Bug line tracking errors across SPM transforms | Unit test each SPM with known bug lines; assertion checks |
| SPMs accidentally alter semantics | Output equivalence checking after every SPM; discard failures |
| Tolerance=0 yields near-zero accuracy | Report both tol=0 and tol=2; define line ranges for ambiguous CWEs |
| LLM non-determinism masks real signal | temp=0 + determinism check on 100 samples; single-run if >95% consistent |
| Prompt phrasing confounds results | 3 variants on 5K subset; report variance; ~20 min extra |
| Dataset is competitive programming only | Acknowledge in threats; optionally add small GitHub real-world set |

---

## Files Summary

### New files
- `agent_evaluation_experiment/program_validator.py` — Validate + capture baseline outputs
- `agent_evaluation_experiment/cwe_bug_injector.py` — CWE-inspired SAMs with line ranges
- `agent_evaluation_experiment/spm_generator.py` — All 8 SPMs + output equivalence checking
- `agent_evaluation_experiment/unified_tester.py` — Multi-backend tester (temp=0, single prompt)
- `agent_evaluation_experiment/pipeline_runner.py` — Pipeline with checkpointing + artifact saving
- `agent_evaluation_experiment/results_aggregator.py` — Statistical analysis + paper figures

### Modified files
- `agent_evaluation_experiment/config.py` — CWE types, SPMs, models, dual tolerance, seeds, temp=0
- `agent_evaluation_experiment/bug_injector.py` — Add CWE mapping + line range metadata
- `agent_evaluation_experiment/agent_tester.py` — Dual tolerance, temp=0
- `agent_evaluation_experiment/run_claude_experiment.py` — Dual tolerance, repetitions

### Existing files to reuse
- `agent_evaluation_experiment/bug_injector.py` — Pattern/contract for new injectors
- `generate_mutants.py` — Line-adjustment logic for SPMs
- `agent_evaluation_experiment/run_claude_experiment.py` — Claude API calling pattern
- `agent_evaluation_experiment/agent_tester.py` — Accuracy measurement (update tolerance from ±2 to 0)

---

## Senior Reviewer Critique: Identified Gaps

### GAP 1: No Statistical Rigor (CRITICAL)
**Problem**: Raw accuracy percentages with no statistical testing.
**Fix**: **McNemar's test + 95% confidence intervals** — minimal but sufficient.
- McNemar's is purpose-built for paired before/after comparisons (exactly "did SPM cause degradation?")
- CIs are trivial to compute (scipy.stats.binom)
- Skip Wilcoxon and effect sizes — marginal value, won't cause rejection if McNemar's is solid

### GAP 2: LLM Response Non-Determinism (CRITICAL)
**Problem**: LLMs are stochastic — single-run results could be noise.
**Fix**: **temperature=0 determinism check on 100 samples first** (~30 min).
- Run 100 samples 3× at temp=0, measure consistency rate
- If >95% identical responses → single-run is defensible (cite in methodology)
- This saves 3× cost/time — critical for 12-hour window
- Report the consistency rate in the paper as evidence

### GAP 3: No False Positive Control Group (MAJOR)
**Problem**: The experiment only tests "can you find the bug in buggy code?" It never asks "is there a bug?" on clean code. Without this, you can't distinguish a model that finds real bugs from one that always reports *something*.
**Fix needed**:
- Add a **control arm**: present clean (un-mutated) code and ask the agent to find bugs
- Measure **false positive rate** — how often does the agent report a bug when none exists?
- Present clean code + SPMs (no SAM) — does the SPM alone cause the agent to hallucinate bugs?
- This strengthens the paper significantly

### GAP 4: Bug Line Ambiguity with Tolerance=0 (MAJOR)
**Problem**: For many bug types, the "correct" line is ambiguous. Example:
```python
if x > 0 and y > 0:   # Line 5 — agent might report this
    result = x + y      # Line 6 — or this, where the effect manifests
```
With tolerance=0, a semantically correct answer pointing to the wrong line is counted as failure. This conflates "understanding" with "line reporting format."
**Fix needed**:
- Report results at **both tolerance=0 and tolerance=2** (primary metric: 0, secondary: 2)
- For CWE types where the bug is multi-line (CWE-483 block delimitation, CWE-563 unused assignment), define a **line range** as the ground truth, not a single line
- Document the ground truth definition for each CWE type explicitly

### GAP 5: SPM Semantic Preservation Not Verified (MAJOR)
**Problem**: The plan says SPMs "preserve semantics" but verification is weak. "Code still parses" is necessary but nowhere near sufficient. A reviewer will ask: "How do you know your SPMs don't accidentally change behavior?"
**Fix needed**:
- For each SPM'd program, run it against the **same test inputs** and verify **output equivalence**
- At minimum: `assert original_output == spm_output` for generated unit tests
- For Function Extraction and Function Reordering SPMs, formally argue semantic equivalence
- Log and report the **SPM validity rate** (% of SPMs that actually preserved semantics)
- Discard any SPM'd programs that fail equivalence checking

### GAP 6: Prompt Sensitivity Not Addressed (MODERATE)
**Problem**: Different prompt phrasings can change LLM accuracy.
**Fix**: **Test 3 prompt variants on a 5K subset** (~20 min extra runtime).
- Primary prompt runs on full set; 2 alternate prompts on 5K subset (GPT-4o-mini)
- If variance is low → report "prompt robustness validated" in methodology
- If variance is high → report it as a finding (also interesting for the paper)
- Document all 3 prompt texts in paper appendix
- Prompts: (1) Minimal "find the bug", (2) Detailed with context, (3) Chain-of-thought

### GAP 7: Confound Between SAM Applicability and Program Complexity (MODERATE)
**Problem**: Not all SAMs apply to all programs. CWE-835 (loop exit) only applies to programs with loops, which tend to be more complex. This means per-SAM accuracy is confounded by the subset of programs it applies to.
**Fix needed**:
- Report **program characteristics per SAM** (avg LOC, complexity for the subset each SAM applies to)
- Normalize comparisons: only compare SAM types on the **intersection** of programs where both apply
- Alternatively: stratify by program complexity (LOC buckets) within each SAM

### GAP 8: Agent vs LLM Distinction (MODERATE)
**Problem**: The title says "coding agents" but the experiment tests LLMs with a single-turn prompt. Real coding agents (Cursor, Copilot, Devin, Claude Code) use multi-step reasoning, tool use, file navigation, etc. A reviewer may flag this as misleading.
**Fix needed**:
- Either: rename scope to "LLMs as fault localization tools" (accurate but less impactful)
- Or: include at least one **agentic evaluation** where the agent can ask follow-up questions, run the code, examine test results, etc. — then compare single-turn vs agentic accuracy
- The Kiro blog insight about agents over-engineering is relevant here — agents might behave very differently from single-prompt LLMs

### GAP 9: Missing Reproducibility Protocol (MODERATE)
**Problem**: LLM-generated SPMs (comments, variables, dead code) are non-deterministic. Different runs produce different mutations, making results unreproducible.
**Fix needed**:
- Set `temperature=0` for all LLM-generated SPMs
- Set `random.seed()` for all algorithmic SPMs
- **Save all generated artifacts** (buggy programs, SPM'd programs) as part of the replication package
- Record exact model versions, API dates, and seeds

### GAP 10: Cost Estimate (RESOLVED)
**Precise estimate**: **~$555 total** with budget-optimal design.
- GPT-4o-mini full set (133K + 10K prompt sensitivity): $69
- Claude Opus 10K subset: $485
- Ollama 2K subset: $0
- See "Precise Cost Estimation" section above for full breakdown.

### GAP 11: No Comparison to Non-LLM Baselines (MINOR — DROPPED)
**Decision**: Skip. Most LLM evaluation papers don't include static analysis baselines. Can add in revisions if reviewer requests it.

### GAP 12: Dataset Representativeness (MINOR — acknowledge in threats)
**Problem**: Programs are from competitive programming / algorithmic challenges. Real-world code has imports, frameworks, multi-file dependencies. Results may not generalize.
**Fix**: Acknowledge in threats to external validity. Optionally add a small set of real-world programs from GitHub.

---

## Gap Resolution Summary

| Gap | Decision | Status |
|-----|----------|--------|
| GAP 1 (Statistics) | **McNemar's test + 95% CIs** only — sufficient | ✅ In plan |
| GAP 2 (Non-determinism) | **temp=0 determinism check → single-run** | ✅ In plan |
| GAP 3 (False positive control) | Control arm with clean + clean+SPM code | ✅ In plan |
| GAP 4 (Line ambiguity) | Report both tol=0 and tol=2; line ranges for multi-line CWEs | ✅ In plan |
| GAP 5 (SPM verification) | Output equivalence checking after every SPM | ✅ In plan |
| GAP 6 (Prompt sensitivity) | 3 prompts on 5K subset (~20 min extra) | ✅ In plan |
| GAP 7 (Complexity confound) | Stratify by LOC buckets in analysis | ✅ In plan |
| GAP 8 (Agent vs LLM) | **Future work** — single-turn for now | ✅ Deferred |
| GAP 9 (Reproducibility) | Seeds, temp=0, save all artifacts | ✅ In plan |
| GAP 10 (Cost) | Budget-aware: full on cheap, subset on expensive | ✅ In plan |
| GAP 11 (Non-LLM baselines) | **Dropped** — add in revisions if reviewer asks | ❌ Skipped |
| GAP 12 (Representativeness) | Acknowledge in threats to external validity | ✅ In plan |
