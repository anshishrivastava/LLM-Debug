#!/usr/bin/env python3
import os
import sys
import json
import ast

def get_off_by_one_candidates(code: str) -> list:
    """
    Walks the AST of the given code and returns a list of candidate mutation sites.
    Each candidate is a tuple: (candidate_type, lineno, col_offset, extra_data)
    
    - For a range() call candidate ("call"): extra_data is the original numeric value.
    - For a while candidate ("while"): extra_data is either "Lt" or "LtE".
    - For a subscript candidate ("subscript"): extra_data is the original index.
    """
    try:
        tree = ast.parse(code)
    except Exception as e:
        print("AST parsing error:", e)
        return []
    candidates = []
    for node in ast.walk(tree):
        # Candidate for range() call mutation.
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "range" and node.args:
            first_arg = node.args[0]
            if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, int):
                candidates.append(("call", node.lineno, node.col_offset, first_arg.value))
        # Candidate for while loop mutation.
        elif isinstance(node, ast.While) and isinstance(node.test, ast.Compare) and len(node.test.ops) == 1:
            op = node.test.ops[0]
            if isinstance(op, ast.Lt):
                candidates.append(("while", node.lineno, node.col_offset, "Lt"))
            elif isinstance(op, ast.LtE):
                candidates.append(("while", node.lineno, node.col_offset, "LtE"))
        # Candidate for subscript mutation.
        elif isinstance(node, ast.Subscript):
            # In Python 3.9+, node.slice is directly a Constant for simple cases.
            if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, int):
                candidates.append(("subscript", node.lineno, node.col_offset, node.slice.value))
    return candidates

class OffByOneCandidateMutator(ast.NodeTransformer):
    def __init__(self, candidate):
        super().__init__()
        self.candidate = candidate  # (type, lineno, col_offset, extra_data)
        self.mutation_applied = False
        self.bug_line = None

    def visit_Call(self, node):
        if not self.mutation_applied and self.candidate[0] == "call":
            if getattr(node, 'lineno', None) == self.candidate[1] and getattr(node, 'col_offset', None) == self.candidate[2]:
                # Mutate the first argument numeric constant in range()
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, int):
                    original_value = node.args[0].value
                    new_value = original_value - 1 if original_value > 0 else original_value + 1
                    node.args[0] = ast.Constant(value=new_value)
                    self.mutation_applied = True
                    self.bug_line = node.lineno
        return self.generic_visit(node)

    def visit_While(self, node):
        if not self.mutation_applied and self.candidate[0] == "while":
            if getattr(node, 'lineno', None) == self.candidate[1] and getattr(node, 'col_offset', None) == self.candidate[2]:
                if isinstance(node.test, ast.Compare) and len(node.test.ops) == 1:
                    op = node.test.ops[0]
                    if self.candidate[3] == "Lt" and isinstance(op, ast.Lt):
                        node.test.ops[0] = ast.LtE()
                        self.mutation_applied = True
                        self.bug_line = node.lineno
                    elif self.candidate[3] == "LtE" and isinstance(op, ast.LtE):
                        node.test.ops[0] = ast.Lt()
                        self.mutation_applied = True
                        self.bug_line = node.lineno
        return self.generic_visit(node)

    def visit_Subscript(self, node):
        if not self.mutation_applied and self.candidate[0] == "subscript":
            if getattr(node, 'lineno', None) == self.candidate[1] and getattr(node, 'col_offset', None) == self.candidate[2]:
                if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, int):
                    original_index = node.slice.value
                    new_index = original_index - 1 if original_index > 0 else original_index + 1
                    node.slice = ast.Constant(value=new_index)
                    self.mutation_applied = True
                    self.bug_line = node.lineno
        return self.generic_visit(node)

def introduce_off_by_one_error_variant(code: str, candidate: tuple) -> tuple:
    """
    Introduces an off-by-one error on the given candidate mutation site.
    Returns (modified_code, bug_line) where bug_line is the 1-indexed line number of the mutation.
    If mutation cannot be applied, returns (None, None).
    """
    try:
        tree = ast.parse(code)
    except Exception as e:
        print("AST parsing error:", e)
        return None, None

    mutator = OffByOneCandidateMutator(candidate)
    mutated_tree = mutator.visit(tree)
    if not mutator.mutation_applied:
        return None, None

    try:
        mutated_code = ast.unparse(mutated_tree)
    except Exception as e:
        print("Error unparsing AST:", e)
        return None, None

    return mutated_code, mutator.bug_line

def process_dataset(dataset_folder: str, output_folder: str) -> None:
    """
    Processes each JSON file in dataset_folder. Each JSON is expected to have the structure:
      {
         "instruction": "<instruction string>",
         "output": "<Python code>"
      }
    For each file:
      - Extracts the code from the "output" field.
      - Finds all eligible off-by-one candidate mutation sites.
      - For each candidate, applies the mutation to create a variant with exactly one bug.
      - Computes the bug's line number percentage (bug_line / total_lines * 100).
      - Writes each variant to a new JSON file in output_folder with keys:
            "instruction": <original instruction>,
            "buggy_code": <mutated code>,
            "line_no": <bug insertion line>,
            "line_no_percent": "<percentage>%"
        Output filenames are based on the original file name with an appended index (e.g. abc_1.json, abc_2.json, etc.).
    """
    os.makedirs(output_folder, exist_ok=True)

    files = [f for f in os.listdir(dataset_folder) if f.lower().endswith(".json")]
    success_variants = 0
    total_files = len(files)
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

        candidates = get_off_by_one_candidates(code)
        if not candidates:
            print(f"No eligible off-by-one candidates found in {file_name}. Skipping.")
            skip_count += 1
            continue

        base_name, _ = os.path.splitext(file_name)
        variant_index = 1
        for candidate in candidates:
            mutated_code, bug_line = introduce_off_by_one_error_variant(code, candidate)
            if mutated_code is None or bug_line is None:
                continue
            total_lines = len(mutated_code.splitlines())
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
                success_variants += 1
            except Exception as e:
                print(f"Error writing {out_file}: {e}")
                continue

    print(f"\nFinished processing. Generated {success_variants} buggy variants out of {total_files} files. Skipped: {skip_count} files.")

def main():
    dataset_folder = "python_dataset"                     # Folder containing original JSON files.
    buggy_dataset_folder = "python_buggy_dataset_off_by_one"  # Folder to store new JSON files with mutated code.
    process_dataset(dataset_folder, buggy_dataset_folder)

if __name__ == "__main__":
    main()
