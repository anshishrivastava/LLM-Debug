#!/usr/bin/env python3
import os
import sys
import json
import random
import ast

# Define allowed arithmetic operator swaps.
ALLOWED_OPS = {
    ast.Add: [ast.Sub, ast.Mult, ast.Div],
    ast.Sub: [ast.Add, ast.Mult, ast.Div],
    ast.Mult: [ast.Add, ast.Sub, ast.Div],
    ast.Div: [ast.Add, ast.Sub, ast.Mult]
}

def get_operator_candidates(code: str) -> list:
    """
    Walks the AST of the given code and returns a list of candidate mutation sites.
    Each candidate is represented as a tuple:
       ("binop", lineno, col_offset, original_operator_class)
    """
    try:
        tree = ast.parse(code)
    except Exception as e:
        print("AST parsing error:", e)
        return []
    candidates = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and type(node.op) in ALLOWED_OPS:
            if hasattr(node, "lineno") and hasattr(node, "col_offset"):
                candidates.append(("binop", node.lineno, node.col_offset, type(node.op)))
    return candidates

class OperatorSwapCandidateMutator(ast.NodeTransformer):
    """
    Mutates a binary operator at the candidate mutation site.
    The candidate is a tuple: ("binop", lineno, col_offset, original_operator_class).
    When a node with matching lineno and col_offset is found, its operator is replaced
    with a randomly chosen alternative from ALLOWED_OPS.
    """
    def __init__(self, candidate):
        super().__init__()
        self.candidate = candidate
        self.mutation_applied = False
        self.bug_line = None

    def visit_BinOp(self, node):
        if (not self.mutation_applied and self.candidate[0] == "binop" and
            getattr(node, "lineno", None) == self.candidate[1] and
            getattr(node, "col_offset", None) == self.candidate[2]):
            alternatives = ALLOWED_OPS[self.candidate[3]]
            new_op_class = random.choice(alternatives)
            node.op = new_op_class()
            self.mutation_applied = True
            self.bug_line = node.lineno
        return self.generic_visit(node)

def introduce_operator_bug_variant(code: str, candidate: tuple) -> tuple:
    """
    Applies the operator swap mutation at the candidate site and returns
    (mutated_code, bug_line). If the mutation cannot be applied, returns (None, None).
    """
    try:
        tree = ast.parse(code)
    except Exception as e:
        print("AST parsing error:", e)
        return None, None

    mutator = OperatorSwapCandidateMutator(candidate)
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
         "instruction": "...",
         "output": "# Python code ..."
      }
    For each file:
      - Extracts the code from the "output" field.
      - Collects all eligible operator swap candidates.
      - For each candidate, applies the mutation to produce a variant with exactly one bug.
      - Computes the bug's line percentage (bug_line / total_lines * 100).
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

        candidates = get_operator_candidates(code)
        if not candidates:
            print(f"No eligible operator candidates found in {file_name}. Skipping.")
            skip_count += 1
            continue

        base_name, _ = os.path.splitext(file_name)
        variant_index = 1
        for candidate in candidates:
            mutated_code, bug_line = introduce_operator_bug_variant(code, candidate)
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
    buggy_dataset_folder = "python_buggy_dataset_operator_swap"  # Folder to store new JSON files with mutated code.
    process_dataset(dataset_folder, buggy_dataset_folder)

if __name__ == "__main__":
    main()
