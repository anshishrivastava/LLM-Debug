#!/usr/bin/env python3
import os
import sys
import json
import re

def generate_all_misplaced_return_variants_from_java_code(code: str) -> list:
    """
    Generates all buggy variants of the given Java code by inserting an extra
    "return;" statement into the beginning of each method definition's body.
    
    The approach:
      1. Splits the code into lines.
      2. Searches for every line that matches a typical Java method declaration (e.g. 
         starting with public, protected, or private, containing a parenthesis and an opening brace).
      3. For each such line, determines the insertion point (immediately after the method declaration)
         and the appropriate indentation (using the first non-empty line in the method body if available).
      4. Inserts a new line with "return;" and records the bug line (1-indexed).
    
    Returns:
      List of tuples: [(mutated_code, bug_line), ...]
      If no method declaration is found, returns an empty list.
    """
    lines = code.splitlines()
    variants = []
    # Regex to match a typical Java method declaration line.
    method_pattern = re.compile(r'^\s*(public|protected|private)\s+.*\s+\w+\s*\(.*\)\s*\{')
    
    for i, line in enumerate(lines):
        if method_pattern.match(line):
            # For this candidate method declaration, determine insertion index.
            insertion_index = i + 1

            # Determine indentation: use the indentation of the first non-empty line after the method declaration.
            indent = ""
            j = insertion_index
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines):
                match = re.match(r'^(\s*)', lines[j])
                if match:
                    indent = match.group(1)
            else:
                # If no non-empty line is found, use the method declaration's indentation plus 4 spaces.
                match = re.match(r'^(\s*)', lines[i])
                indent = (match.group(1) if match else "") + "    "

            extra_return_line = indent + "return;"
            # Create a new variant by copying the original lines.
            new_lines = lines.copy()
            new_lines.insert(insertion_index, extra_return_line)
            bug_line = insertion_index + 1  # Convert 0-index to 1-index.
            mutated_code = "\n".join(new_lines) + "\n"
            variants.append((mutated_code, bug_line))
    return variants

def process_dataset(dataset_folder: str, output_folder: str) -> None:
    """
    Processes each JSON file in dataset_folder. Each JSON is expected to have the structure:
      {
         "instruction": "<instruction string>",
         "output": "<Java code>"
      }
    
    For each file:
      - Extracts the code from the "output" field.
      - Generates all buggy variants by inserting an extra "return;" statement after each
        eligible method declaration.
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

        variants = generate_all_misplaced_return_variants_from_java_code(code)
        if not variants:
            print(f"No method definition found in {file_name}. Skipping.")
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
                total_variants += 1
            except Exception as e:
                print(f"Error writing {out_file}: {e}")
                continue

    print(f"\nFinished processing. Successfully generated {total_variants} buggy variants out of {total_files} files. Skipped: {skip_count} files.")

def main():
    dataset_folder = "java_dataset"  # Folder containing original JSON files with Java code.
    buggy_dataset_folder = "java_buggy_dataset_misplaced_return"  # Output folder for mutated JSON files.
    process_dataset(dataset_folder, buggy_dataset_folder)

if __name__ == "__main__":
    main()
