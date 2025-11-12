#!/usr/bin/env python3
import os
import sys
import json
import random
import ast
import copy

# New helper to collect all candidate boolean nodes (with their line & column)
def get_boolean_candidate_keys(code: str) -> list:
    """
    Returns a list of candidate keys for boolean expressions that can be mutated.
    Each candidate key is a tuple (lineno, col_offset).
    """
    try:
        tree = ast.parse(code)
    except Exception as e:
        print("AST parsing error:", e)
        return []
    candidate_keys = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And) or isinstance(node.op, ast.Or):
                if hasattr(node, 'lineno') and hasattr(node, 'col_offset'):
                    candidate_keys.append((node.lineno, node.col_offset))
    return candidate_keys

# New mutator that only mutates a given candidate (identified by its lineno and col_offset)
def introduce_boolean_logic_bug_variant(code: str, candidate_key: tuple) -> tuple:
    """
    Introduces a boolean logic bug by swapping 'and' <-> 'or' in the candidate
    boolean expression identified by candidate_key (a tuple of (lineno, col_offset)).
    Returns (modified_code, bug_line) where bug_line is the 1-indexed line number
    where the mutation occurred.
    """
    try:
        tree = ast.parse(code)
    except Exception as e:
        print("AST parsing error:", e)
        return None, None

    target_lineno, target_col = candidate_key

    class SingleCandidateBooleanMutator(ast.NodeTransformer):
        def __init__(self, target_lineno, target_col):
            super().__init__()
            self.target_lineno = target_lineno
            self.target_col = target_col
            self.mutation_applied = False
            self.bug_line = None

        def visit_BoolOp(self, node):
            # If not mutated yet and node matches the candidate key, swap the operator.
            if not self.mutation_applied:
                if getattr(node, 'lineno', None) == self.target_lineno and getattr(node, 'col_offset', None) == self.target_col:
                    if isinstance(node.op, ast.And):
                        node.op = ast.Or()
                        self.mutation_applied = True
                        self.bug_line = node.lineno
                    elif isinstance(node.op, ast.Or):
                        node.op = ast.And()
                        self.mutation_applied = True
                        self.bug_line = node.lineno
            return self.generic_visit(node)

    mutator = SingleCandidateBooleanMutator(target_lineno, target_col)
    mutated_tree = mutator.visit(tree)
    if not mutator.mutation_applied:
        print(f"No eligible boolean logic expression found for candidate {candidate_key}.")
        return None, None

    try:
        modified_code = ast.unparse(mutated_tree)
    except Exception as e:
        print("Error unparsing AST:", e)
        return None, None

    return modified_code, mutator.bug_line

class BooleanLogicMutator(ast.NodeTransformer):
    """
    (This class remains here for reference but is not used in the variant approach.)
    """
    def __init__(self):
        super().__init__()
        self.mutation_applied = False
        self.bug_line = None

    def visit_BoolOp(self, node):
        if not self.mutation_applied:
            if isinstance(node.op, ast.And):
                node.op = ast.Or()
                self.mutation_applied = True
                self.bug_line = getattr(node, 'lineno', None)
            elif isinstance(node.op, ast.Or):
                node.op = ast.And()
                self.mutation_applied = True
                self.bug_line = getattr(node, 'lineno', None)
        return self.generic_visit(node)

def process_dataset(dataset_folder: str, output_folder: str) -> None:
    """
    Processes each JSON file in dataset_folder. Each JSON is expected to have the structure:
      {
         "instruction": "...",
         "output": "# Python code ..."
      }
    For each file, the function:
      1. Extracts the Python code from "output".
      2. Finds all eligible boolean expressions (candidates) for mutation.
      3. For each candidate, applies a mutation (swapping the boolean operator) to create
         a buggy variant with exactly one bug.
      4. Computes the bug line number percentage (bug_line / total_lines * 100).
      5. Writes each variant as a new JSON file in output_folder. The filenames are appended
         with an index (e.g. abc_1.json, abc_2.json, ...).
    """
    os.makedirs(output_folder, exist_ok=True)
    files = [f for f in os.listdir(dataset_folder) if f.lower().endswith(".json")]
    total_files = len(files)
    total_variants = 0
    skip_count = 0

    for file_name in files:
        file_path = os.path.join(dataset_folder, file_name)
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"Error reading {file_name}: {e}")
            skip_count += 1
            continue

        code = data.get("output", "")
        instruction = data.get("instruction", "")
        if not code:
            print(f"No code found in 'output' for {file_name}. Skipping.")
            skip_count += 1
            continue

        candidate_keys = get_boolean_candidate_keys(code)
        if not candidate_keys:
            print(f"No eligible boolean expressions found in {file_name}. Skipping.")
            skip_count += 1
            continue

        base_name, _ = os.path.splitext(file_name)
        variant_index = 1
        for candidate_key in candidate_keys:
            mutated_code, bug_line = introduce_boolean_logic_bug_variant(code, candidate_key)
            if mutated_code is None or bug_line is None:
                continue

            total_lines = len(mutated_code.splitlines())
            # Compute the percentage of the bug line relative to the total lines.
            percent = round((bug_line / total_lines) * 100)
            variant_data = {
                "instruction": instruction,
                "buggy_code": mutated_code,
                "line_no": bug_line,
                "line_no_percent": f"{percent}%"
            }
            out_file = os.path.join(output_folder, f"{base_name}_{variant_index}.json")
            try:
                with open(out_file, "w", encoding="utf-8") as f:
                    json.dump(variant_data, f, indent=2)
                print(f"Created buggy variant: {out_file} (bug at line {bug_line}, {percent}% of total)")
                variant_index += 1
                total_variants += 1
            except Exception as e:
                print(f"Error writing {out_file}: {e}")
                continue

    print(f"\nFinished processing. Generated {total_variants} buggy variants out of {total_files} files. Skipped: {skip_count} files.")

def main():
    dataset_folder = "python_dataset"  # Folder containing original JSON files.
    buggy_dataset_folder = "python_buggy_dataset_boolean_logic"  # Folder to store new buggy JSON files.
    process_dataset(dataset_folder, buggy_dataset_folder)

if __name__ == "__main__":
    main()
