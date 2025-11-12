#!/usr/bin/env python3
import os
import sys
import json

def generate_all_misplaced_return_variants(code: str) -> list:
    """
    Generates all buggy variants by inserting an extra "return" statement into the 
    beginning of each function definition's body (one variant per function).
    
    The approach:
      1. Splits the code into lines.
      2. For every line that (after stripping leading whitespace) starts with "def ",
         finds the first line after it that is indented (i.e. the start of the function body).
      3. Inserts a new line with the same indentation containing "return" at that location.
    
    Returns:
      List of tuples: [(variant_code, bug_line), ...] where variant_code is the mutated
      code as a string and bug_line is the 1-indexed line number where the extra return
      was inserted.
      If no candidate is found, returns an empty list.
    """
    lines = code.splitlines()
    variants = []
    
    for i, line in enumerate(lines):
        if line.lstrip().startswith("def "):
            # Search for the first indented line after the function definition.
            for j in range(i + 1, len(lines)):
                if lines[j].startswith(" ") or lines[j].startswith("\t"):
                    # Determine indentation from the candidate body line.
                    indent = ""
                    for ch in lines[j]:
                        if ch in (" ", "\t"):
                            indent += ch
                        else:
                            break
                    extra_return_line = indent + "return"
                    new_lines = lines.copy()
                    new_lines.insert(j, extra_return_line)
                    variant_code = "\n".join(new_lines) + "\n"
                    bug_line = j + 1  # 1-indexed
                    variants.append((variant_code, bug_line))
                    break  # Only one variant per function definition.
    return variants

def process_dataset(dataset_folder: str, output_folder: str) -> None:
    """
    Processes each JSON file in dataset_folder. Each JSON is expected to have the structure:
      {
         "instruction": "<instruction string>",
         "output": "<Python code>"
      }
    
    For each file:
      - Extracts the code from the "output" field.
      - Generates all buggy variants by inserting a misplaced return in every eligible function.
      - For each variant, computes the percentage of the bug line number relative to the total lines.
      - Writes each variant to a new JSON file in output_folder with keys:
            "instruction": <original instruction>,
            "buggy_code": <mutated code>,
            "line_no": <bug insertion line>,
            "line_no_percent": "<percentage>%"
        The output filenames are based on the original file name with an appended index (e.g. abc_1.json, abc_2.json, etc.).
    
    Prints a summary of how many variants were generated.
    """
    os.makedirs(output_folder, exist_ok=True)
    files = [f for f in os.listdir(dataset_folder) if f.lower().endswith(".json")]
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

        # Generate all variants for this file.
        variants = generate_all_misplaced_return_variants(code)
        if not variants:
            print(f"No eligible function definitions found in {file_name}. Skipping.")
            skip_count += 1
            continue

        base_name, _ = os.path.splitext(file_name)
        variant_index = 1
        for variant_code, bug_line in variants:
            total_lines = len(variant_code.splitlines())
            # Compute percentage (rounded to nearest integer).
            percent = round((bug_line / total_lines) * 100)
            variant_data = {
                "instruction": instruction,
                "buggy_code": variant_code,
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

    print(f"\nFinished processing. Generated {total_variants} buggy variants. Skipped: {skip_count} files.")

def main():
    dataset_folder = "python_dataset"  # Folder containing original JSON files.
    buggy_dataset_folder = "python_buggy_dataset_misplaced_return"  # New folder for mutated JSON files.
    process_dataset(dataset_folder, buggy_dataset_folder)

if __name__ == "__main__":
    main()
