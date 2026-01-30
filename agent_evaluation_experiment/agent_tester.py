#!/usr/bin/env python3
"""Agent/LLM tester for bug detection evaluation."""

import os
import sys
import json
import csv
from datetime import datetime
from typing import Dict, List, Tuple
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_evaluation_experiment.config import (
    BUGGY_DATASETS_DIR, RESULTS_DIR, CODING_AGENTS, 
    LINE_TOLERANCE, BUG_TYPES, DATASET_CATEGORIES, LANGUAGES
)

try:
    from ollama import chat
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False
    print("Warning: ollama not available. Install with: pip install ollama")


class BugLine(BaseModel):
    line_no: int


def ask_llm_for_bug_line(model: str, instruction: str, buggy_code: str) -> int:
    """Ask LLM to identify the bug line number."""
    if not OLLAMA_AVAILABLE:
        return -1
    
    try:
        response = chat(
            messages=[{
                'role': 'user',
                'content': f'I want this code to "{instruction}" but I am experiencing unexpected output.\n'
                           f'Buggy Code:\n{buggy_code}\n'
                           f'Can you give me the exact line number where the bug is?',
            }],
            model=model,
            format=BugLine.model_json_schema()
        )
        
        bug_line_obj = BugLine.model_validate_json(response.message.content)
        return bug_line_obj.line_no
    except Exception as e:
        print(f"LLM error: {e}")
        return -1


def test_dataset(model: str, dataset_dir: str) -> Dict:
    """Test a model on a buggy dataset."""
    results = {
        'total': 0,
        'success': 0,
        'failure': 0,
        'errors': 0,
        'window_match': {"0-25": 0, "25-50": 0, "50-75": 0, "75-100": 0},
        'window_mismatch': {"0-25": 0, "25-50": 0, "50-75": 0, "75-100": 0},
        'predictions': []
    }
    
    if not os.path.exists(dataset_dir):
        print(f"Dataset not found: {dataset_dir}")
        return results
    
    files = [f for f in os.listdir(dataset_dir) if f.endswith('.json')]
    
    for filename in files:
        filepath = os.path.join(dataset_dir, filename)
        
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
        except Exception as e:
            results['errors'] += 1
            continue
        
        instruction = data.get('instruction', '')
        buggy_code = data.get('buggy_code', '')
        actual_line = data.get('line_no')
        line_percent_str = data.get('line_no_percent', '50%')
        
        if not instruction or not buggy_code or actual_line is None:
            results['errors'] += 1
            continue
        
        results['total'] += 1
        
        # Determine window
        try:
            percent_value = float(line_percent_str.strip('%'))
        except:
            percent_value = 50
        
        if percent_value < 25:
            window = "0-25"
        elif percent_value < 50:
            window = "25-50"
        elif percent_value < 75:
            window = "50-75"
        else:
            window = "75-100"
        
        # Get prediction
        predicted_line = ask_llm_for_bug_line(model, instruction, buggy_code)
        
        if predicted_line == -1:
            results['failure'] += 1
            results['window_mismatch'][window] += 1
            continue
        
        # Check if prediction is correct (within tolerance)
        is_match = abs(predicted_line - actual_line) <= LINE_TOLERANCE
        
        if is_match:
            results['success'] += 1
            results['window_match'][window] += 1
        else:
            results['failure'] += 1
            results['window_mismatch'][window] += 1
        
        results['predictions'].append({
            'file': filename,
            'actual': actual_line,
            'predicted': predicted_line,
            'match': is_match,
            'window': window
        })
        
        # Progress indicator
        if results['total'] % 10 == 0:
            print(f"  Processed {results['total']} files...")
    
    return results


def run_all_tests() -> Dict:
    """Run tests for all models on all datasets."""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    
    all_results = {}
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    for model in CODING_AGENTS:
        print(f"\n{'='*60}")
        print(f"Testing model: {model}")
        print('='*60)
        
        model_results = {}
        
        for language in LANGUAGES:
            for category in DATASET_CATEGORIES:
                for bug_type in BUG_TYPES:
                    dataset_name = f"{language}_{category}_{bug_type}"
                    dataset_dir = os.path.join(BUGGY_DATASETS_DIR, dataset_name)
                    
                    if not os.path.exists(dataset_dir):
                        print(f"Skipping {dataset_name} - not found")
                        continue
                    
                    print(f"\nTesting: {dataset_name}")
                    results = test_dataset(model, dataset_dir)
                    
                    accuracy = (results['success'] / results['total'] * 100) if results['total'] > 0 else 0
                    print(f"  Accuracy: {accuracy:.2f}% ({results['success']}/{results['total']})")
                    
                    model_results[dataset_name] = results
        
        all_results[model] = model_results
    
    # Save results
    results_file = os.path.join(RESULTS_DIR, f"agent_evaluation_results_{timestamp}.json")
    with open(results_file, 'w') as f:
        # Remove predictions for smaller file size
        summary_results = {}
        for model, model_data in all_results.items():
            summary_results[model] = {}
            for dataset, data in model_data.items():
                summary_results[model][dataset] = {k: v for k, v in data.items() if k != 'predictions'}
        json.dump(summary_results, f, indent=2)
    
    print(f"\nResults saved to: {results_file}")
    
    # Generate CSV summary
    generate_csv_summary(all_results, timestamp)
    
    return all_results


def generate_csv_summary(all_results: Dict, timestamp: str):
    """Generate CSV summary of results."""
    csv_file = os.path.join(RESULTS_DIR, f"agent_evaluation_summary_{timestamp}.csv")
    
    headers = [
        'Model', 'Language', 'Category', 'Bug Type', 
        'Total', 'Success', 'Failure', 'Accuracy %',
        '0-25 Match', '25-50 Match', '50-75 Match', '75-100 Match',
        '0-25 Miss', '25-50 Miss', '50-75 Miss', '75-100 Miss'
    ]
    
    rows = []
    for model, model_data in all_results.items():
        for dataset_name, results in model_data.items():
            parts = dataset_name.split('_')
            language = parts[0]
            category = parts[1]
            bug_type = '_'.join(parts[2:])
            
            accuracy = (results['success'] / results['total'] * 100) if results['total'] > 0 else 0
            
            row = [
                model, language, category, bug_type,
                results['total'], results['success'], results['failure'], f"{accuracy:.2f}",
                results['window_match']['0-25'], results['window_match']['25-50'],
                results['window_match']['50-75'], results['window_match']['75-100'],
                results['window_mismatch']['0-25'], results['window_mismatch']['25-50'],
                results['window_mismatch']['50-75'], results['window_mismatch']['75-100']
            ]
            rows.append(row)
    
    with open(csv_file, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)
    
    print(f"CSV summary saved to: {csv_file}")


if __name__ == "__main__":
    if not OLLAMA_AVAILABLE:
        print("ERROR: Ollama is required. Install with: pip install ollama")
        print("Also ensure Ollama is running with the required models.")
        sys.exit(1)
    
    print("Starting Agent Evaluation Tests...")
    results = run_all_tests()
    
    print("\n" + "="*60)
    print("FINAL SUMMARY")
    print("="*60)
    
    for model, model_data in results.items():
        print(f"\n{model}:")
        total_success = sum(d['success'] for d in model_data.values())
        total_tests = sum(d['total'] for d in model_data.values())
        overall_acc = (total_success / total_tests * 100) if total_tests > 0 else 0
        print(f"  Overall: {overall_acc:.2f}% ({total_success}/{total_tests})")
