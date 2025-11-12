#!/usr/bin/env python3
import os
import sys
import json
import re
import random

# Allowed arithmetic operators for Java.
ALLOWED_OPS = ["+", "-", "*", "/"]

def generate_all_operator_swap_variants_in_java_code(code: str) -> list:
    """
    Generates all buggy variants of the given Java code by replacing exactly one arithmetic operator
    with an alternative operator from ALLOWED_OPS at every eligible occurrence.
    
    Only lines that are not empty or comments (starting with "//" or "/*") are considered.
    
    Returns:
      List of tuples: [(mutated_code, bug_line), ...] where bug_line is the 1-indexed line number
      at which the mutation was applied.
    """
    lines = code.splitlines()
    variants = []
    # Regex to match any arithmetic operator; ensure it's not part of a larger token.
    operator_pattern = re.compile(r'(?<!\w)([+\-*/])(?!\w)')
    
    for i, line in enumerate(lines):
        stripped_line = line.strip()
        # Skip empty lines or lines that start with comment markers.
        if not stripped_line or stripped_line.startswith("//") or stripped_line.startswith("/*"):
            continue
        
        # Find all occurrences of an operator in the line.
        for match in operator_pattern.finditer(line):
            original_op = match.group(1)
            if original_op in ALLOWED_OPS:
                # For each alternative (excluding the original), produce a variant.
                alternatives = [op for op in ALLOWED_OPS if op != original_op]
                for new_op in alternatives:
                    new_lines = lines.copy()
                    start, end = match.start(), match.end()
                    new_line = line[:start] + new_op + line[end:]
                    new_lines[i] = new_line
                    mutated_code = "\n".join(new_lines) + "\n"
                    bug_line = i + 1  # Convert to 1-indexed.
                    variants.append((mutated_code, bug_line))
    return variants

def process_dataset(dataset_folder: str, output_folder: str) -> None:
    """
    Processes each JSON file in dataset_folder. Each JSON file is expected to have the structure:
      {
         "instruction": "<instruction string>",
         "output": "<Java code>"
      }
    
    For each file:
      - Extracts the Java code from the "output" field.
      - Generates all buggy variants by applying an operator swap mutation at every eligible occurrence.
      - For each variant, computes the bug's line number percentage relative to the total number of lines.
      - Writes each variant to a new JSON file in output_folder with keys:
            "instruction": <original instruction>,
            "buggy_code": <mutated code>,
            "line_no": <bug insertion line>,
            "line_no_percent": "<percentage>%"
        Output filenames are based on the original file name with an appended index 
        (e.g. abc_1.json, abc_2.json, etc.).
    """
    os.makedirs(output_folder, exist_ok=True)
    files = [f for f in os.listdir(dataset_folder) if f.lower().endswith(".json")]
    total_files = len(files)
    success_variants = 0
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

        variants = generate_all_operator_swap_variants_in_java_code(code)
        if not variants:
            print(f"No eligible operator found in {file_name}. Skipping.")
            skip_count += 1
            continue

        base_name, _ = os.path.splitext(file_name)
        variant_index = 1
        for mutated_code, bug_line in variants:
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
                print(f"Created buggy variant: {out_file} (mutation at line {bug_line}, {percent}% of total)")
                variant_index += 1
                success_variants += 1
            except Exception as e:
                print(f"Error writing {out_file}: {e}")
                continue

    print(f"\nFinished processing. Successfully generated {success_variants} buggy variants out of {total_files} files. Skipped: {skip_count} files.")

def main():
    dataset_folder = "java_dataset"  # Folder containing original JSON files with Java code.
    buggy_dataset_folder = "java_buggy_dataset_operator_swap"  # Output folder for mutated JSON files.
    process_dataset(dataset_folder, buggy_dataset_folder)

if __name__ == "__main__":
    main()
