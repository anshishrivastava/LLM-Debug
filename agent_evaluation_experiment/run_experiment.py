#!/usr/bin/env python3
"""
Main experiment runner for Agent Evaluation.

This script orchestrates the full pipeline:
1. Bug injection into clean code
2. Testing multiple coding agents
3. Generating analysis reports
"""

import os
import sys
import json
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_evaluation_experiment.config import (
    EXPERIMENT_ROOT, RESULTS_DIR, BUGGY_DATASETS_DIR,
    CODING_AGENTS, BUG_TYPES, LANGUAGES, DATASET_CATEGORIES
)
from agent_evaluation_experiment.bug_injector import inject_all_bugs
from agent_evaluation_experiment.agent_tester import run_all_tests, test_dataset


def setup_directories():
    """Create necessary directories."""
    dirs = [EXPERIMENT_ROOT, RESULTS_DIR, BUGGY_DATASETS_DIR]
    for d in dirs:
        os.makedirs(d, exist_ok=True)
    print("Directories created.")


def run_bug_injection():
    """Step 1: Inject bugs into datasets."""
    print("\n" + "="*60)
    print("STEP 1: BUG INJECTION")
    print("="*60)
    
    results = inject_all_bugs()
    
    # Save injection stats
    stats_file = os.path.join(RESULTS_DIR, "bug_injection_stats.json")
    with open(stats_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\nBug injection stats saved to: {stats_file}")
    return results


def run_agent_tests():
    """Step 2: Test agents on buggy datasets."""
    print("\n" + "="*60)
    print("STEP 2: AGENT TESTING")
    print("="*60)
    
    results = run_all_tests()
    return results


def generate_analysis_report(test_results: dict):
    """Step 3: Generate comprehensive analysis report."""
    print("\n" + "="*60)
    print("STEP 3: ANALYSIS REPORT")
    print("="*60)
    
    report = {
        'timestamp': datetime.now().isoformat(),
        'summary': {},
        'by_model': {},
        'by_bug_type': {},
        'by_category': {},
        'by_language': {},
        'existing_vs_new': {}
    }
    
    # Aggregate by different dimensions
    for model, model_data in test_results.items():
        model_total = 0
        model_success = 0
        
        for dataset_name, results in model_data.items():
            parts = dataset_name.split('_')
            language = parts[0]
            category = parts[1]
            bug_type = '_'.join(parts[2:])
            
            model_total += results['total']
            model_success += results['success']
            
            # By bug type
            if bug_type not in report['by_bug_type']:
                report['by_bug_type'][bug_type] = {'total': 0, 'success': 0}
            report['by_bug_type'][bug_type]['total'] += results['total']
            report['by_bug_type'][bug_type]['success'] += results['success']
            
            # By category (existing vs new)
            if category not in report['by_category']:
                report['by_category'][category] = {'total': 0, 'success': 0}
            report['by_category'][category]['total'] += results['total']
            report['by_category'][category]['success'] += results['success']
            
            # By language
            if language not in report['by_language']:
                report['by_language'][language] = {'total': 0, 'success': 0}
            report['by_language'][language]['total'] += results['total']
            report['by_language'][language]['success'] += results['success']
        
        # Model summary
        accuracy = (model_success / model_total * 100) if model_total > 0 else 0
        report['by_model'][model] = {
            'total': model_total,
            'success': model_success,
            'accuracy': round(accuracy, 2)
        }
    
    # Calculate accuracies
    for key in ['by_bug_type', 'by_category', 'by_language']:
        for name, data in report[key].items():
            data['accuracy'] = round((data['success'] / data['total'] * 100) if data['total'] > 0 else 0, 2)
    
    # Existing vs New comparison
    if 'existing' in report['by_category'] and 'new' in report['by_category']:
        report['existing_vs_new'] = {
            'existing_accuracy': report['by_category']['existing']['accuracy'],
            'new_accuracy': report['by_category']['new']['accuracy'],
            'difference': round(
                report['by_category']['existing']['accuracy'] - report['by_category']['new']['accuracy'], 2
            )
        }
    
    # Save report
    report_file = os.path.join(RESULTS_DIR, f"analysis_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    with open(report_file, 'w') as f:
        json.dump(report, f, indent=2)
    
    # Print summary
    print("\n" + "-"*40)
    print("RESULTS BY MODEL:")
    print("-"*40)
    for model, data in report['by_model'].items():
        print(f"  {model}: {data['accuracy']}% ({data['success']}/{data['total']})")
    
    print("\n" + "-"*40)
    print("RESULTS BY BUG TYPE:")
    print("-"*40)
    for bug_type, data in report['by_bug_type'].items():
        print(f"  {bug_type}: {data['accuracy']}% ({data['success']}/{data['total']})")
    
    print("\n" + "-"*40)
    print("EXISTING vs NEW DATA:")
    print("-"*40)
    for category, data in report['by_category'].items():
        print(f"  {category}: {data['accuracy']}% ({data['success']}/{data['total']})")
    
    if report['existing_vs_new']:
        diff = report['existing_vs_new']['difference']
        direction = "better on existing" if diff > 0 else "better on new" if diff < 0 else "same"
        print(f"\n  Difference: {abs(diff)}% ({direction})")
    
    print("\n" + "-"*40)
    print("RESULTS BY LANGUAGE:")
    print("-"*40)
    for lang, data in report['by_language'].items():
        print(f"  {lang}: {data['accuracy']}% ({data['success']}/{data['total']})")
    
    print(f"\nFull report saved to: {report_file}")
    
    return report


def main():
    parser = argparse.ArgumentParser(description='Run Agent Evaluation Experiment')
    parser.add_argument('--skip-injection', action='store_true', 
                       help='Skip bug injection (use existing buggy datasets)')
    parser.add_argument('--skip-testing', action='store_true',
                       help='Skip agent testing (only generate report from existing results)')
    parser.add_argument('--models', nargs='+', default=None,
                       help='Specific models to test (default: all)')
    args = parser.parse_args()
    
    print("="*60)
    print("AGENT EVALUATION EXPERIMENT")
    print("="*60)
    print(f"Start time: {datetime.now().isoformat()}")
    print(f"Models: {args.models or CODING_AGENTS}")
    print(f"Bug types: {BUG_TYPES}")
    print(f"Languages: {LANGUAGES}")
    print(f"Categories: {DATASET_CATEGORIES}")
    
    # Setup
    setup_directories()
    
    # Step 1: Bug injection
    if not args.skip_injection:
        injection_results = run_bug_injection()
    else:
        print("\nSkipping bug injection (using existing datasets)")
    
    # Step 2: Agent testing
    if not args.skip_testing:
        test_results = run_agent_tests()
    else:
        print("\nSkipping agent testing")
        # Load most recent results
        result_files = [f for f in os.listdir(RESULTS_DIR) if f.startswith('agent_evaluation_results_')]
        if result_files:
            latest = sorted(result_files)[-1]
            with open(os.path.join(RESULTS_DIR, latest), 'r') as f:
                test_results = json.load(f)
        else:
            print("No existing results found!")
            return
    
    # Step 3: Analysis
    report = generate_analysis_report(test_results)
    
    print("\n" + "="*60)
    print("EXPERIMENT COMPLETE")
    print("="*60)
    print(f"End time: {datetime.now().isoformat()}")


if __name__ == "__main__":
    main()
