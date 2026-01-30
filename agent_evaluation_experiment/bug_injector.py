#!/usr/bin/env python3
"""Bug injection module for agent evaluation experiment."""

import os
import sys
import json
import ast
import re
import random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_evaluation_experiment.config import (
    JAVA_DATASET, PYTHON_DATASET, BUGGY_DATASETS_DIR, 
    BUG_TYPES, DATASET_CATEGORIES, LANGUAGES
)


# ============== PYTHON BUG INJECTORS ==============

def inject_boolean_logic_bug_python(code: str) -> tuple:
    """Inject boolean logic bug (and <-> or) in Python code."""
    try:
        tree = ast.parse(code)
    except:
        return None, None
    
    class BooleanMutator(ast.NodeTransformer):
        def __init__(self):
            self.mutation_applied = False
            self.bug_line = None
            
        def visit_BoolOp(self, node):
            if not self.mutation_applied:
                if isinstance(node.op, ast.And):
                    node.op = ast.Or()
                    self.mutation_applied = True
                    self.bug_line = node.lineno
                elif isinstance(node.op, ast.Or):
                    node.op = ast.And()
                    self.mutation_applied = True
                    self.bug_line = node.lineno
            return self.generic_visit(node)
    
    mutator = BooleanMutator()
    mutated_tree = mutator.visit(tree)
    
    if not mutator.mutation_applied:
        return None, None
    
    try:
        modified_code = ast.unparse(mutated_tree)
        return modified_code, mutator.bug_line
    except:
        return None, None


def inject_off_by_one_bug_python(code: str) -> tuple:
    """Inject off-by-one bug in Python code."""
    lines = code.split('\n')
    
    # Patterns for off-by-one bugs
    patterns = [
        (r'range\((\d+)\)', lambda m: f'range({int(m.group(1)) + 1})'),
        (r'range\((\w+)\)', lambda m: f'range({m.group(1)} + 1)'),
        (r'<= (\d+)', lambda m: f'< {m.group(1)}'),
        (r'>= (\d+)', lambda m: f'> {m.group(1)}'),
        (r'\[(\w+)\]', lambda m: f'[{m.group(1)} + 1]'),
    ]
    
    for i, line in enumerate(lines):
        for pattern, replacement in patterns:
            if re.search(pattern, line):
                new_line = re.sub(pattern, replacement, line, count=1)
                if new_line != line:
                    lines[i] = new_line
                    return '\n'.join(lines), i + 1
    
    return None, None


def inject_operator_swap_bug_python(code: str) -> tuple:
    """Inject operator swap bug in Python code."""
    lines = code.split('\n')
    
    swaps = [
        (r' \+ ', ' - '), (r' - ', ' + '),
        (r' \* ', ' / '), (r' / ', ' * '),
        (r' == ', ' != '), (r' != ', ' == '),
        (r' < ', ' > '), (r' > ', ' < '),
        (r' <= ', ' >= '), (r' >= ', ' <= '),
    ]
    
    for i, line in enumerate(lines):
        if '#' in line:  # Skip comments
            continue
        for old, new in swaps:
            if re.search(old, line):
                new_line = re.sub(old, new, line, count=1)
                if new_line != line:
                    lines[i] = new_line
                    return '\n'.join(lines), i + 1
    
    return None, None


def inject_misplaced_return_bug_python(code: str) -> tuple:
    """Inject misplaced return bug in Python code."""
    lines = code.split('\n')
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('return ') and i > 0:
            # Get indentation
            indent = len(line) - len(line.lstrip())
            # Check if previous line has same or less indentation (can move return up)
            if i > 1:
                prev_indent = len(lines[i-1]) - len(lines[i-1].lstrip())
                if prev_indent >= indent and lines[i-1].strip():
                    # Swap with previous line
                    lines[i], lines[i-1] = lines[i-1], lines[i]
                    return '\n'.join(lines), i  # Bug is now at previous line position
    
    return None, None


# ============== JAVA BUG INJECTORS ==============

def inject_boolean_logic_bug_java(code: str) -> tuple:
    """Inject boolean logic bug in Java code."""
    lines = code.split('\n')
    
    for i, line in enumerate(lines):
        if '&&' in line:
            lines[i] = line.replace('&&', '||', 1)
            return '\n'.join(lines), i + 1
        elif '||' in line:
            lines[i] = line.replace('||', '&&', 1)
            return '\n'.join(lines), i + 1
    
    return None, None


def inject_off_by_one_bug_java(code: str) -> tuple:
    """Inject off-by-one bug in Java code."""
    lines = code.split('\n')
    
    patterns = [
        (r'< (\w+)\.length', r'<= \1.length'),
        (r'<= (\w+)\.length', r'< \1.length'),
        (r'i < (\d+)', lambda m: f'i < {int(m.group(1)) + 1}'),
        (r'i <= (\d+)', lambda m: f'i < {m.group(1)}'),
    ]
    
    for i, line in enumerate(lines):
        for pattern, replacement in patterns:
            if re.search(pattern, line):
                if callable(replacement):
                    new_line = re.sub(pattern, replacement, line, count=1)
                else:
                    new_line = re.sub(pattern, replacement, line, count=1)
                if new_line != line:
                    lines[i] = new_line
                    return '\n'.join(lines), i + 1
    
    return None, None


def inject_operator_swap_bug_java(code: str) -> tuple:
    """Inject operator swap bug in Java code."""
    lines = code.split('\n')
    
    swaps = [
        (r' \+ ', ' - '), (r' - ', ' + '),
        (r' \* ', ' / '), (r' / ', ' * '),
        (r' == ', ' != '), (r' != ', ' == '),
        (r' < ', ' > '), (r' > ', ' < '),
    ]
    
    for i, line in enumerate(lines):
        if '//' in line:  # Skip comments
            continue
        for old, new in swaps:
            if re.search(old, line):
                new_line = re.sub(old, new, line, count=1)
                if new_line != line:
                    lines[i] = new_line
                    return '\n'.join(lines), i + 1
    
    return None, None


def inject_misplaced_return_bug_java(code: str) -> tuple:
    """Inject misplaced return bug in Java code."""
    lines = code.split('\n')
    
    for i, line in enumerate(lines):
        if 'return ' in line and i > 0:
            indent = len(line) - len(line.lstrip())
            if i > 1 and lines[i-1].strip() and not lines[i-1].strip().startswith('//'):
                lines[i], lines[i-1] = lines[i-1], lines[i]
                return '\n'.join(lines), i
    
    return None, None


# ============== MAIN INJECTION LOGIC ==============

BUG_INJECTORS = {
    'python': {
        'BooleanLogic': inject_boolean_logic_bug_python,
        'OffByOne': inject_off_by_one_bug_python,
        'OperatorSwap': inject_operator_swap_bug_python,
        'MisplacedReturn': inject_misplaced_return_bug_python,
    },
    'java': {
        'BooleanLogic': inject_boolean_logic_bug_java,
        'OffByOne': inject_off_by_one_bug_java,
        'OperatorSwap': inject_operator_swap_bug_java,
        'MisplacedReturn': inject_misplaced_return_bug_java,
    }
}


def process_dataset(input_dir: str, output_dir: str, language: str, bug_type: str) -> dict:
    """Process a dataset and inject bugs."""
    os.makedirs(output_dir, exist_ok=True)
    
    injector = BUG_INJECTORS[language][bug_type]
    stats = {'total': 0, 'success': 0, 'failed': 0}
    
    for filename in os.listdir(input_dir):
        if not filename.endswith('.json'):
            continue
        
        stats['total'] += 1
        filepath = os.path.join(input_dir, filename)
        
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
        except Exception as e:
            stats['failed'] += 1
            continue
        
        # Get code from 'output' field
        code = data.get('output', '')
        instruction = data.get('instruction', '')
        
        if not code:
            stats['failed'] += 1
            continue
        
        # Inject bug
        buggy_code, bug_line = injector(code)
        
        if buggy_code is None or bug_line is None:
            stats['failed'] += 1
            continue
        
        # Calculate line percentage
        total_lines = len(buggy_code.split('\n'))
        line_percent = round((bug_line / total_lines) * 100) if total_lines > 0 else 0
        
        # Create output record
        output_data = {
            'instruction': instruction,
            'buggy_code': buggy_code,
            'original_code': code,
            'line_no': bug_line,
            'line_no_percent': f"{line_percent}%",
            'bug_type': bug_type,
            'language': language,
            'source_file': filename,
            'metadata': data.get('metadata', {})
        }
        
        # Write output
        output_path = os.path.join(output_dir, filename)
        with open(output_path, 'w') as f:
            json.dump(output_data, f, indent=2)
        
        stats['success'] += 1
    
    return stats


def inject_all_bugs():
    """Inject all bug types into all datasets."""
    results = {}
    
    for language in LANGUAGES:
        dataset_base = PYTHON_DATASET if language == 'python' else JAVA_DATASET
        
        for category in DATASET_CATEGORIES:
            input_dir = os.path.join(dataset_base, category)
            
            if not os.path.exists(input_dir):
                print(f"Skipping {input_dir} - does not exist")
                continue
            
            for bug_type in BUG_TYPES:
                output_dir = os.path.join(
                    BUGGY_DATASETS_DIR, 
                    f"{language}_{category}_{bug_type}"
                )
                
                print(f"Processing: {language}/{category}/{bug_type}")
                stats = process_dataset(input_dir, output_dir, language, bug_type)
                
                key = f"{language}_{category}_{bug_type}"
                results[key] = stats
                print(f"  Total: {stats['total']}, Success: {stats['success']}, Failed: {stats['failed']}")
    
    return results


if __name__ == "__main__":
    print("Starting bug injection...")
    results = inject_all_bugs()
    
    print("\n" + "="*60)
    print("BUG INJECTION SUMMARY")
    print("="*60)
    
    for key, stats in results.items():
        success_rate = (stats['success'] / stats['total'] * 100) if stats['total'] > 0 else 0
        print(f"{key}: {stats['success']}/{stats['total']} ({success_rate:.1f}%)")
