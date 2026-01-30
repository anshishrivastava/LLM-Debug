#!/usr/bin/env python3
"""
Evaluation Pipeline: Test Code Understanding Before/After Mutations.

This pipeline evaluates whether LLMs truly understand code by:
1. Running unit tests on original code (baseline)
2. Applying Semantic-Preserving Mutations (SPMs)
3. Running same tests on mutated code
4. Comparing results to detect pattern-matching vs true understanding

Key insight from research: If an LLM relies on superficial patterns rather than
semantic understanding, its performance will degrade after SPMs even though
the code's behavior is unchanged.
"""

import os
import json
import subprocess
import tempfile
import re
from datetime import datetime
from typing import Dict, List, Tuple

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNIT_TESTS_DIR = os.path.join(BASE_DIR, "agent_evaluation_experiment", "unit_tests")
OUTPUT_DIR = os.path.join(BASE_DIR, "agent_evaluation_experiment", "evaluation_results")


# ============== SEMANTIC-PRESERVING MUTATIONS ==============

def add_misleading_comments(code: str) -> str:
    """Add comments that don't match code behavior (SPM Type 1)."""
    lines = code.split('\n')
    mutations = [
        "# This optimizes memory usage",
        "# Critical security check below", 
        "# TODO: Refactor this section",
        "# Legacy code - do not modify",
        "# Performance bottleneck here",
    ]
    
    # Insert misleading comment before first function body line
    for i, line in enumerate(lines):
        if line.strip() and not line.strip().startswith('#') and not line.strip().startswith('def'):
            import random
            lines.insert(i, "    " + random.choice(mutations))
            break
    
    return '\n'.join(lines)


def rename_variables(code: str) -> str:
    """Rename variables to misleading names (SPM Type 2)."""
    replacements = {
        'result': 'temp_unused',
        'count': 'index_val',
        'total': 'partial_sum',
        'data': 'buffer_cache',
        'items': 'node_list',
        'value': 'placeholder',
    }
    
    mutated = code
    for old, new in replacements.items():
        # Only replace if it's a variable (word boundary)
        pattern = r'\b' + old + r'\b'
        mutated = re.sub(pattern, new, mutated)
    
    return mutated


def add_dead_code(code: str) -> str:
    """Insert unreachable code blocks (SPM Type 3)."""
    dead_snippets = [
        "\n    if False:\n        raise RuntimeError('unreachable')\n",
        "\n    _ = lambda x: x  # unused\n",
        "\n    pass  # placeholder\n",
    ]
    
    lines = code.split('\n')
    # Find first line inside function body
    for i, line in enumerate(lines):
        if line.strip().startswith('def '):
            # Insert after docstring if present
            j = i + 1
            while j < len(lines) and (lines[j].strip().startswith('"""') or 
                                       lines[j].strip().startswith("'''")):
                j += 1
            import random
            lines.insert(j, dead_snippets[0])
            break
    
    return '\n'.join(lines)


def apply_all_mutations(code: str) -> str:
    """Apply all SPMs to code."""
    mutated = add_misleading_comments(code)
    mutated = rename_variables(mutated)
    mutated = add_dead_code(mutated)
    return mutated


# ============== TEST EXECUTION ==============

def run_test(code: str, test_code: str) -> Tuple[bool, str]:
    """Run pytest on code + test, return (passed, output)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Write code file
        code_file = os.path.join(tmpdir, "code_under_test.py")
        with open(code_file, 'w') as f:
            f.write(code)
        
        # Write test file with import
        test_file = os.path.join(tmpdir, "test_code.py")
        with open(test_file, 'w') as f:
            f.write("import sys\n")
            f.write(f"sys.path.insert(0, '{tmpdir}')\n")
            f.write("from code_under_test import *\n\n")
            f.write(test_code)
        
        # Run pytest
        try:
            result = subprocess.run(
                ['python', '-m', 'pytest', test_file, '-v', '--tb=short'],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=tmpdir
            )
            passed = result.returncode == 0
            output = result.stdout + result.stderr
            return passed, output
        except subprocess.TimeoutExpired:
            return False, "TIMEOUT"
        except Exception as e:
            return False, str(e)


# ============== EVALUATION PIPELINE ==============

def evaluate_sample(sample: Dict) -> Dict:
    """Evaluate a single sample: original vs mutated."""
    code = sample['original_code']
    test_code = sample['test_code']
    
    # Test original
    orig_passed, orig_output = run_test(code, test_code)
    
    # Apply mutations
    mutated_code = apply_all_mutations(code)
    
    # Test mutated
    mut_passed, mut_output = run_test(mutated_code, test_code)
    
    return {
        'function_name': sample['function_name'],
        'source_file': sample['source_file'],
        'original_passed': orig_passed,
        'mutated_passed': mut_passed,
        'understanding_preserved': orig_passed == mut_passed,
        'original_output': orig_output[:500] if orig_output else '',
        'mutated_output': mut_output[:500] if mut_output else '',
    }


def run_evaluation_pipeline():
    """Run full evaluation pipeline."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # Load generated tests
    tests_file = os.path.join(UNIT_TESTS_DIR, 'generated_tests.json')
    if not os.path.exists(tests_file):
        print("ERROR: No generated tests found. Run generate_unit_tests.py first.")
        return
    
    with open(tests_file) as f:
        samples = json.load(f)
    
    print(f"Loaded {len(samples)} samples with tests")
    print("="*60)
    
    results = []
    stats = {
        'total': 0,
        'original_passed': 0,
        'mutated_passed': 0,
        'understanding_preserved': 0,
        'degraded': 0,  # Passed original but failed mutated
    }
    
    for idx, sample in enumerate(samples):
        print(f"[{idx+1}/{len(samples)}] Testing {sample['function_name']}...", end=" ", flush=True)
        
        result = evaluate_sample(sample)
        results.append(result)
        
        stats['total'] += 1
        if result['original_passed']:
            stats['original_passed'] += 1
        if result['mutated_passed']:
            stats['mutated_passed'] += 1
        if result['understanding_preserved']:
            stats['understanding_preserved'] += 1
        if result['original_passed'] and not result['mutated_passed']:
            stats['degraded'] += 1
        
        status = "✓" if result['understanding_preserved'] else "✗"
        print(f"{status} (orig={result['original_passed']}, mut={result['mutated_passed']})")
    
    # Calculate metrics
    if stats['original_passed'] > 0:
        degradation_rate = stats['degraded'] / stats['original_passed'] * 100
    else:
        degradation_rate = 0
    
    summary = {
        'timestamp': datetime.now().isoformat(),
        'total_samples': stats['total'],
        'original_pass_rate': round(stats['original_passed'] / stats['total'] * 100, 2),
        'mutated_pass_rate': round(stats['mutated_passed'] / stats['total'] * 100, 2),
        'understanding_preserved_rate': round(stats['understanding_preserved'] / stats['total'] * 100, 2),
        'degradation_rate': round(degradation_rate, 2),
        'stats': stats,
        'results': results
    }
    
    # Save results
    output_file = os.path.join(OUTPUT_DIR, f"evaluation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    with open(output_file, 'w') as f:
        json.dump(summary, f, indent=2)
    
    # Print summary
    print("\n" + "="*60)
    print("EVALUATION SUMMARY")
    print("="*60)
    print(f"Total samples:              {stats['total']}")
    print(f"Original tests passed:      {stats['original_passed']} ({summary['original_pass_rate']}%)")
    print(f"Mutated tests passed:       {stats['mutated_passed']} ({summary['mutated_pass_rate']}%)")
    print(f"Understanding preserved:    {stats['understanding_preserved']} ({summary['understanding_preserved_rate']}%)")
    print(f"Degradation rate:           {summary['degradation_rate']}%")
    print(f"\nResults saved: {output_file}")
    
    return summary


if __name__ == "__main__":
    run_evaluation_pipeline()
