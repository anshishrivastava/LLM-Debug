#!/usr/bin/env python3
"""EDA Analysis for Agent Evaluation Datasets."""

import os
import json
import matplotlib.pyplot as plt
import numpy as np
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON_DATASET = os.path.join(BASE_DIR, "agent_evaluation_python_dataset")
JAVA_DATASET = os.path.join(BASE_DIR, "agent_evaluation_java_dataset")
OUTPUT_DIR = os.path.join(BASE_DIR, "agent_evaluation_experiment", "eda_output")


def load_dataset(dataset_path):
    """Load all JSON files from dataset directory."""
    data = []
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
                        data.append(d)
                except:
                    pass
    return data


def analyze_dataset(data, lang):
    """Analyze dataset and return stats."""
    stats = {
        'total': len(data),
        'by_category': defaultdict(int),
        'loc_distribution': [],
        'features': defaultdict(int),
        'has_docstring': 0,
        'instruction_lengths': []
    }
    
    for item in data:
        stats['by_category'][item.get('_category', 'unknown')] += 1
        
        # LOC
        code = item.get('output', '')
        loc = len(code.split('\n')) if code else 0
        if 'metadata' in item and 'lines_of_code' in item['metadata']:
            loc = item['metadata']['lines_of_code']
        stats['loc_distribution'].append(loc)
        
        # Features from metadata
        meta = item.get('metadata', {})
        for feat in ['has_boolean_logic', 'has_loops', 'has_conditionals', 'has_arithmetic', 'has_comparisons']:
            if meta.get(feat):
                stats['features'][feat] += 1
        if meta.get('has_docstring'):
            stats['has_docstring'] += 1
            
        # Instruction length
        instr = item.get('instruction', '')
        stats['instruction_lengths'].append(len(instr))
    
    return stats


def plot_eda(python_stats, java_stats):
    """Generate EDA visualizations."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    fig, axes = plt.subplots(2, 3, figsize=(15, 10))
    fig.suptitle('Agent Evaluation Dataset EDA', fontsize=14, fontweight='bold')
    
    # 1. Dataset Size Comparison
    ax = axes[0, 0]
    langs = ['Python', 'Java']
    existing = [python_stats['by_category']['existing'], java_stats['by_category']['existing']]
    new = [python_stats['by_category']['new'], java_stats['by_category']['new']]
    x = np.arange(len(langs))
    ax.bar(x - 0.2, existing, 0.4, label='Existing', color='steelblue')
    ax.bar(x + 0.2, new, 0.4, label='New', color='coral')
    ax.set_xticks(x)
    ax.set_xticklabels(langs)
    ax.set_ylabel('Count')
    ax.set_title('Dataset Size by Category')
    ax.legend()
    for i, (e, n) in enumerate(zip(existing, new)):
        ax.text(i - 0.2, e + 5, str(e), ha='center', fontsize=9)
        ax.text(i + 0.2, n + 5, str(n), ha='center', fontsize=9)
    
    # 2. LOC Distribution - Python
    ax = axes[0, 1]
    loc_py = python_stats['loc_distribution']
    ax.hist(loc_py, bins=30, color='steelblue', edgecolor='black', alpha=0.7)
    ax.axvline(np.median(loc_py), color='red', linestyle='--', label=f'Median: {np.median(loc_py):.0f}')
    ax.axvline(np.mean(loc_py), color='orange', linestyle='--', label=f'Mean: {np.mean(loc_py):.0f}')
    ax.set_xlabel('Lines of Code')
    ax.set_ylabel('Frequency')
    ax.set_title(f'Python LOC Distribution (n={len(loc_py)})')
    ax.legend(fontsize=8)
    
    # 3. LOC Distribution - Java
    ax = axes[0, 2]
    loc_java = java_stats['loc_distribution']
    ax.hist(loc_java, bins=30, color='coral', edgecolor='black', alpha=0.7)
    ax.axvline(np.median(loc_java), color='red', linestyle='--', label=f'Median: {np.median(loc_java):.0f}')
    ax.axvline(np.mean(loc_java), color='orange', linestyle='--', label=f'Mean: {np.mean(loc_java):.0f}')
    ax.set_xlabel('Lines of Code')
    ax.set_ylabel('Frequency')
    ax.set_title(f'Java LOC Distribution (n={len(loc_java)})')
    ax.legend(fontsize=8)
    
    # 4. Code Features Comparison
    ax = axes[1, 0]
    features = ['boolean_logic', 'loops', 'conditionals', 'arithmetic', 'comparisons']
    py_feats = [python_stats['features'][f'has_{f}'] for f in features]
    java_feats = [java_stats['features'][f'has_{f}'] for f in features]
    x = np.arange(len(features))
    ax.bar(x - 0.2, py_feats, 0.4, label='Python', color='steelblue')
    ax.bar(x + 0.2, java_feats, 0.4, label='Java', color='coral')
    ax.set_xticks(x)
    ax.set_xticklabels([f.replace('_', '\n') for f in features], fontsize=8)
    ax.set_ylabel('Count')
    ax.set_title('Code Features Distribution')
    ax.legend()
    
    # 5. LOC Box Plot Comparison
    ax = axes[1, 1]
    bp = ax.boxplot([loc_py, loc_java], labels=['Python', 'Java'], patch_artist=True)
    bp['boxes'][0].set_facecolor('steelblue')
    bp['boxes'][1].set_facecolor('coral')
    ax.set_ylabel('Lines of Code')
    ax.set_title('LOC Comparison (Box Plot)')
    
    # 6. Summary Stats Table
    ax = axes[1, 2]
    ax.axis('off')
    summary = [
        ['Metric', 'Python', 'Java'],
        ['Total Samples', python_stats['total'], java_stats['total']],
        ['Existing', python_stats['by_category']['existing'], java_stats['by_category']['existing']],
        ['New', python_stats['by_category']['new'], java_stats['by_category']['new']],
        ['Mean LOC', f"{np.mean(loc_py):.1f}", f"{np.mean(loc_java):.1f}"],
        ['Median LOC', f"{np.median(loc_py):.1f}", f"{np.median(loc_java):.1f}"],
        ['Min LOC', min(loc_py), min(loc_java)],
        ['Max LOC', max(loc_py), max(loc_java)],
        ['Total LOC', sum(loc_py), sum(loc_java)],
        ['Has Docstring', python_stats['has_docstring'], java_stats['has_docstring']],
    ]
    table = ax.table(cellText=summary, loc='center', cellLoc='center')
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1.2, 1.5)
    ax.set_title('Summary Statistics', pad=20)
    
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, 'eda_analysis.png'), dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: {os.path.join(OUTPUT_DIR, 'eda_analysis.png')}")
    
    return summary


def main():
    print("Loading datasets...")
    python_data = load_dataset(PYTHON_DATASET)
    java_data = load_dataset(JAVA_DATASET)
    
    print(f"Python samples: {len(python_data)}")
    print(f"Java samples: {len(java_data)}")
    
    print("\nAnalyzing datasets...")
    python_stats = analyze_dataset(python_data, 'python')
    java_stats = analyze_dataset(java_data, 'java')
    
    print("\nGenerating visualizations...")
    summary = plot_eda(python_stats, java_stats)
    
    print("\n" + "="*50)
    print("DATASET SUMMARY")
    print("="*50)
    for row in summary:
        print(f"{row[0]:<20} {str(row[1]):>12} {str(row[2]):>12}")
    
    # Save stats as JSON
    stats_output = {
        'python': {
            'total': python_stats['total'],
            'by_category': dict(python_stats['by_category']),
            'loc_stats': {
                'mean': float(np.mean(python_stats['loc_distribution'])),
                'median': float(np.median(python_stats['loc_distribution'])),
                'min': int(min(python_stats['loc_distribution'])),
                'max': int(max(python_stats['loc_distribution'])),
                'total': int(sum(python_stats['loc_distribution']))
            },
            'features': dict(python_stats['features'])
        },
        'java': {
            'total': java_stats['total'],
            'by_category': dict(java_stats['by_category']),
            'loc_stats': {
                'mean': float(np.mean(java_stats['loc_distribution'])),
                'median': float(np.median(java_stats['loc_distribution'])),
                'min': int(min(java_stats['loc_distribution'])),
                'max': int(max(java_stats['loc_distribution'])),
                'total': int(sum(java_stats['loc_distribution']))
            },
            'features': dict(java_stats['features'])
        }
    }
    
    with open(os.path.join(OUTPUT_DIR, 'eda_stats.json'), 'w') as f:
        json.dump(stats_output, f, indent=2)
    print(f"\nSaved: {os.path.join(OUTPUT_DIR, 'eda_stats.json')}")


if __name__ == "__main__":
    main()
