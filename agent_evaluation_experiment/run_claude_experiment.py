#!/usr/bin/env python3
"""Run fault localization experiment with Claude on 100 Java + 100 Python samples."""

import os
import json
import csv
import random
from datetime import datetime
from anthropic import Anthropic

# Config
API_KEY = os.environ.get("ANTHROPIC_API_KEY")
MODEL = "claude-sonnet-4-20250514"
SAMPLE_SIZE = 100
LINE_TOLERANCE = 2

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON_DATASET = os.path.join(BASE_DIR, "agent_evaluation_python_dataset")
JAVA_DATASET = os.path.join(BASE_DIR, "agent_evaluation_java_dataset")
OUTPUT_DIR = os.path.join(BASE_DIR, "agent_evaluation_experiment", "results")


def load_samples(dataset_path, n=100):
    """Load n random samples from dataset."""
    samples = []
    for category in ['existing', 'new']:
        cat_path = os.path.join(dataset_path, category)
        if not os.path.exists(cat_path):
            continue
        for f in os.listdir(cat_path):
            if f.endswith('.json'):
                try:
                    with open(os.path.join(cat_path, f)) as fp:
                        d = json.load(fp)
                        d['_category'] = category
                        d['_filename'] = f
                        samples.append(d)
                except:
                    pass
    
    random.seed(42)  # Reproducibility
    return random.sample(samples, min(n, len(samples)))


def ask_claude_for_bug_line(client, instruction: str, buggy_code: str) -> int:
    """Ask Claude to identify the bug line number."""
    prompt = f"""Find the bug in this code. The code should: "{instruction}"

```
{buggy_code}
```

Reply with ONLY this JSON, nothing else: {{"line_no": N}}
Where N is the line number containing the bug."""

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=100,
            system="You are a bug detector. Always respond with ONLY valid JSON in format {\"line_no\": N}. No explanations.",
            messages=[{"role": "user", "content": prompt}]
        )
        
        text = response.content[0].text.strip()
        # Extract JSON from response
        if '{' in text:
            json_str = text[text.find('{'):text.rfind('}')+1]
            result = json.loads(json_str)
            return result.get('line_no', -1)
        else:
            print(f"  [No JSON in response: {text[:50]}]")
    except Exception as e:
        print(f"  [API Error: {e}]")
    return -1


def inject_bug(code: str, lang: str) -> tuple:
    """Simple operator swap bug injection."""
    lines = code.split('\n')
    swaps = [(' + ', ' - '), (' - ', ' + '), (' == ', ' != '), (' != ', ' == '),
             (' < ', ' > '), (' > ', ' < '), (' and ', ' or '), (' or ', ' and ')]
    
    if lang == 'java':
        swaps.extend([(' && ', ' || '), (' || ', ' && ')])
    
    for i, line in enumerate(lines):
        if '#' in line or '//' in line:  # Skip comments
            continue
        for old, new in swaps:
            if old in line:
                lines[i] = line.replace(old, new, 1)
                return '\n'.join(lines), i + 1
    return None, None


def run_experiment(client, samples, lang, output_file):
    """Run experiment on samples with intermediate saves."""
    results = []
    
    for idx, sample in enumerate(samples):
        code = sample.get('output', '')
        instruction = sample.get('instruction', '')
        
        if not code or not instruction:
            continue
        
        # Inject bug
        buggy_code, bug_line = inject_bug(code, lang)
        if buggy_code is None:
            continue
        
        # Ask Claude
        predicted = ask_claude_for_bug_line(client, instruction, buggy_code)
        is_correct = abs(predicted - bug_line) <= LINE_TOLERANCE if predicted > 0 else False
        
        results.append({
            'filename': sample.get('_filename', ''),
            'category': sample.get('_category', ''),
            'actual_line': bug_line,
            'predicted_line': predicted,
            'correct': is_correct,
            'loc': len(code.split('\n'))
        })
        
        status = "✓" if is_correct else "✗"
        print(f"[{idx+1}/{len(samples)}] {lang} {status} actual={bug_line} pred={predicted}", flush=True)
        
        # Save intermediate results every 10 samples
        if (idx + 1) % 10 == 0:
            save_intermediate(output_file, lang, results)
    
    return results


def save_intermediate(output_file, lang, results):
    """Save intermediate results to file."""
    partial_file = output_file.replace('.json', f'_{lang}_partial.json')
    correct = sum(1 for r in results if r['correct'])
    data = {
        'lang': lang,
        'processed': len(results),
        'correct': correct,
        'accuracy': round(correct / len(results) * 100, 2) if results else 0,
        'results': results
    }
    with open(partial_file, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"  [Saved {len(results)} {lang} results]", flush=True)


def main():
    if not API_KEY:
        print("ERROR: Set ANTHROPIC_API_KEY environment variable")
        return
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    client = Anthropic(api_key=API_KEY)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    print(f"Loading {SAMPLE_SIZE} samples per language...")
    python_samples = load_samples(PYTHON_DATASET, SAMPLE_SIZE)
    java_samples = load_samples(JAVA_DATASET, SAMPLE_SIZE)
    
    print(f"\nPython samples: {len(python_samples)}")
    print(f"Java samples: {len(java_samples)}")
    
    output_file = os.path.join(OUTPUT_DIR, f"claude_experiment_{timestamp}.json")
    
    # Run experiments
    print(f"\n{'='*50}")
    print("PYTHON EXPERIMENT")
    print('='*50)
    python_results = run_experiment(client, python_samples, 'python', output_file)
    
    print(f"\n{'='*50}")
    print("JAVA EXPERIMENT")
    print('='*50)
    java_results = run_experiment(client, java_samples, 'java', output_file)
    
    # Calculate stats
    def calc_stats(results):
        if not results:
            return {'total': 0, 'correct': 0, 'accuracy': 0}
        correct = sum(1 for r in results if r['correct'])
        return {
            'total': len(results),
            'correct': correct,
            'accuracy': round(correct / len(results) * 100, 2)
        }
    
    py_stats = calc_stats(python_results)
    java_stats = calc_stats(java_results)
    
    # Save results
    output = {
        'timestamp': timestamp,
        'model': MODEL,
        'sample_size': SAMPLE_SIZE,
        'python': {'stats': py_stats, 'results': python_results},
        'java': {'stats': java_stats, 'results': java_results}
    }
    
    output_file = os.path.join(OUTPUT_DIR, f"claude_experiment_{timestamp}.json")
    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2)
    
    # Print summary
    print(f"\n{'='*50}")
    print("RESULTS SUMMARY")
    print('='*50)
    print(f"Python: {py_stats['accuracy']}% ({py_stats['correct']}/{py_stats['total']})")
    print(f"Java:   {java_stats['accuracy']}% ({java_stats['correct']}/{java_stats['total']})")
    print(f"\nResults saved: {output_file}")


if __name__ == "__main__":
    main()
