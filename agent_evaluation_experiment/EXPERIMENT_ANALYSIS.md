# Agent Evaluation Experiment Analysis

## Overview

This experiment evaluates how accurately Large Language Models (LLMs) and coding agents understand code, based on the methodology from ["How Accurately Do Large Language Models Understand Code?"](https://arxiv.org/abs/2504.04372).

**Key Hypothesis:** LLMs often rely on superficial syntactic/lexical patterns rather than true semantic understanding. This can be tested by applying Semantic-Preserving Mutations (SPMs) and measuring performance degradation.

---

## Dataset Summary

| Metric | Python | Java |
|--------|--------|------|
| **Total Samples** | 1,062 | 1,070 |
| Existing (from paper) | 637 | 670 |
| New (post-cutoff) | 425 | 400 |
| **Median LOC** | 53 | 112 |
| Mean LOC | 83.5 | 389.4 |
| Total LOC | 88,702 | 416,649 |

### Code Feature Distribution
- Boolean logic: Python 330, Java 223
- Loops: Python 283, Java 330
- Conditionals: Python 357, Java 328
- Arithmetic: Python 177, Java 171
- Comparisons: Python 170, Java 261

---

## Experiment 1: Fault Localization

### Methodology
1. Inject operator-swap bugs into clean code (e.g., `+` → `-`, `and` → `or`)
2. Ask Claude to identify the bug line number
3. Measure accuracy with ±2 line tolerance

### Results (Claude Sonnet)

| Language | Overall | Existing | New |
|----------|---------|----------|-----|
| **Python** | 36.05% (31/86) | 27.6% (16/58) | 53.6% (15/28) |
| **Java** | 43.33% (39/90) | 22.7% (15/66) | 100.0% (24/24) |
| **Combined** | **39.77% (70/176)** | - | - |

### Key Finding
**New samples had significantly higher accuracy than existing samples.** This suggests potential data contamination - the model may have seen existing samples during training, leading to pattern-matching rather than true understanding.

---

## How LLMs Process Code

### Tokenization and Structure
Code gets broken into tokens (keywords, operators, identifiers, literals) that the model processes. Unlike human reading, the agent processes code as a sequence of tokens with learned relationships:
- **Syntactic structure** (what's grammatically valid)
- **Semantic meaning** (what the code actually does)

### Contextual Understanding
Modern coding agents use transformer architectures that excel at understanding context:
- Track variable scope across hundreds of lines
- Understand how changes in one part affect others
- Recognize design patterns and architectural choices
- Infer intent from variable names, comments, and surrounding code

**However:** When you add comments, agents break them down to tokens and consider their grammatical meaning combined with the code—even when unnecessary.

### Abstract Representations
Rather than "reading" code linearly, they build internal representations capturing:
- **Data flow** (how information moves through the program)
- **Control flow** (execution paths and conditions)
- **Dependencies** between components
- Relationship between code and intended behavior

### Limitations
LLMs don't "understand" code the way humans do with mental models of execution. They can't:
- Actually run code in their heads
- Guarantee correctness through formal reasoning

Their understanding is **statistical**—they recognize patterns that correlate with correct code based on training examples.

---

## Semantic-Preserving Mutations (SPMs)

SPMs modify code without changing its behavior. If an LLM truly understands code semantically, its performance should remain stable after SPMs.

### Types Implemented

| SPM Type | Description | Example |
|----------|-------------|---------|
| **Misleading Comments** | Add comments that don't match behavior | `# Critical security check` before unrelated code |
| **Variable Renaming** | Rename to misleading names | `result` → `temp_unused` |
| **Dead Code** | Insert unreachable blocks | `if False: raise Error()` |
| **Void Functions** | Add no-op function calls | - |
| **Empty Lines** | Add whitespace | - |

### Expected Impact
From the reference paper: **~78% of cases** show degraded performance after SPMs, indicating reliance on superficial cues.

---

## Evaluation Pipeline

### Phase 1: Unit Test Generation
For each program:
1. Generate pytest unit tests using Claude
2. Verify tests pass on original code

### Phase 2: Mutation Testing
1. Apply all SPMs to original code
2. Run same tests on mutated code
3. Compare results

### Metrics
- **Original Pass Rate**: % of tests passing on original code
- **Mutated Pass Rate**: % of tests passing after SPMs
- **Degradation Rate**: % of originally-passing tests that fail after SPMs
- **Understanding Preserved**: Cases where behavior is consistent

---

## Files Structure

```
agent_evaluation_experiment/
├── eda_analysis.py              # Dataset EDA
├── eda_output/
│   ├── eda_analysis.png         # Visualizations
│   └── eda_stats.json           # Statistics
├── run_claude_experiment.py     # Fault localization experiment
├── generate_unit_tests.py       # Unit test generator
├── evaluation_pipeline.py       # SPM evaluation pipeline
└── results/
    └── claude_experiment_*.json # Experiment results
```

---

## Conclusions

1. **Baseline Performance**: Claude achieves ~40% accuracy on fault localization with ±2 line tolerance
2. **Data Contamination Signal**: Significantly higher accuracy on new (post-cutoff) samples suggests training data overlap
3. **Pattern Matching Evidence**: The discrepancy between existing/new samples supports the hypothesis that LLMs rely on memorized patterns

---

## Next Steps

1. Run full SPM evaluation pipeline on 100 samples
2. Compare degradation rates across bug types
3. Test multiple models (GPT-4, local models)
4. Analyze which SPM types cause most degradation

---

## References

- [How Accurately Do Large Language Models Understand Code?](https://arxiv.org/abs/2504.04372)
- [LLM-Debug GitHub Repository](https://github.com/sabaat/LLM-Debug)
- [Dataset on Zenodo](https://zenodo.org/records/15028585)
