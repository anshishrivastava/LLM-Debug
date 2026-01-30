#!/usr/bin/env python3
"""
Unit Test Generator for Agent Evaluation Pipeline.

This module generates unit tests for programs to evaluate if an LLM/agent
truly understands the code by:
1. Testing original code works correctly
2. Applying semantic-preserving mutations (SPMs)
3. Verifying mutated code still passes tests (proves understanding vs pattern matching)
"""

import os
import json
import random
from datetime import datetime
from anthropic import Anthropic

API_KEY = os.environ.get("ANTHROPIC_API_KEY")
MODEL = "claude-sonnet-4-20250514"

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON_DATASET = os.path.join(BASE_DIR, "agent_evaluation_python_dataset")
OUTPUT_DIR = os.path.join(BASE_DIR, "agent_evaluation_experiment", "unit_tests")


def load_samples(dataset_path, n=100):
    """Load n samples from dataset."""
    samples = []
    for category in ['existing', 'new']:
        cat_path = os.path.join(dataset_path, category)
        if not os.path.exists(cat_path):
            continue
        for f in sorted(os.listdir(cat_path)):
            if f.endswith('.json'):
                try:
                    with open(os.path.join(cat_path, f)) as fp:
                        d = json.load(fp)
                        d['_category'] = category
                        d['_filename'] = f
                        samples.append(d)
                except:
                    pass
    random.seed(42)
    return random.sample(samples, min(n, len(samples)))


def generate_unit_test(client, instruction: str, code: str, func_name: str) -> str:
    """Generate unit test for a function using Claude."""
    prompt = f"""Generate a minimal pytest unit test for this Python function.

Function purpose: {instruction}

```python
{code}
```

Requirements:
1. Create 2-3 test cases covering normal inputs
2. Use simple, concrete test values
3. Include edge cases if obvious
4. Return ONLY the test code, no explanations

Format:
```python
import pytest
# any needed imports

def test_{func_name}_basic():
    # test implementation
```"""

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=500,
            system="You are a test engineer. Generate only valid pytest code. No explanations.",
            messages=[{"role": "user", "content": prompt}]
        )
        text = response.content[0].text.strip()
        # Extract code block
        if '```python' in text:
            start = text.find('```python') + 9
            end = text.find('```', start)
            return text[start:end].strip()
        elif '```' in text:
            start = text.find('```') + 3
            end = text.find('```', start)
            return text[start:end].strip()
        return text
    except Exception as e:
        print(f"  [Error: {e}]")
        return None


def extract_function_name(code: str) -> str:
    """Extract function name from code."""
    import re
    match = re.search(r'def\s+(\w+)\s*\(', code)
    if match:
        return match.group(1)
    return "unknown"


def main():
    if not API_KEY:
        print("ERROR: Set ANTHROPIC_API_KEY")
        return
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    client = Anthropic(api_key=API_KEY)
    
    print("Loading 100 Python samples...")
    samples = load_samples(PYTHON_DATASET, 100)
    print(f"Loaded {len(samples)} samples\n")
    
    results = []
    generated = 0
    
    for idx, sample in enumerate(samples):
        code = sample.get('output', '')
        instruction = sample.get('instruction', '')
        filename = sample.get('_filename', f'sample_{idx}')
        
        if not code or not instruction:
            continue
        
        func_name = extract_function_name(code)
        print(f"[{idx+1}/100] Generating test for {func_name}...", end=" ", flush=True)
        
        test_code = generate_unit_test(client, instruction, code, func_name)
        
        if test_code:
            results.append({
                'source_file': filename,
                'function_name': func_name,
                'instruction': instruction,
                'original_code': code,
                'test_code': test_code,
                'category': sample.get('_category', '')
            })
            generated += 1
            print("✓")
        else:
            print("✗")
        
        # Save intermediate every 20
        if (idx + 1) % 20 == 0:
            save_results(results, OUTPUT_DIR)
    
    # Final save
    save_results(results, OUTPUT_DIR)
    
    print(f"\n{'='*50}")
    print(f"Generated {generated} unit tests")
    print(f"Saved to: {OUTPUT_DIR}")


def save_results(results, output_dir):
    """Save results to JSON and individual test files."""
    # Save JSON summary
    with open(os.path.join(output_dir, 'generated_tests.json'), 'w') as f:
        json.dump(results, f, indent=2)
    
    # Save individual test files
    tests_dir = os.path.join(output_dir, 'test_files')
    os.makedirs(tests_dir, exist_ok=True)
    
    for r in results:
        test_filename = f"test_{r['function_name']}_{r['source_file'].replace('.json', '.py')}"
        with open(os.path.join(tests_dir, test_filename), 'w') as f:
            f.write(f"# Test for: {r['instruction']}\n")
            f.write(f"# Source: {r['source_file']}\n\n")
            f.write(r['test_code'])


if __name__ == "__main__":
    main()
