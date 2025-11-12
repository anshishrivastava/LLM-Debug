#!/usr/bin/env python3
import os
import sys
import json
import re

def is_inside_string_or_comment(line: str, pos: int) -> bool:
    """
    Checks if position 'pos' in 'line' is inside a string literal or comment.
    Returns True if the position is inside a string or comment, False otherwise.
    """
    # Check for single-line comments
    comment_pos = line.find('//')
    if comment_pos != -1 and pos >= comment_pos:
        return True
    
    # Check for string literals (both single and double quotes)
    # We need to track whether we're inside a string
    in_double_quote = False
    in_single_quote = False
    escape_next = False
    
    for i, char in enumerate(line):
        if i >= pos:
            break
            
        if escape_next:
            escape_next = False
            continue
            
        if char == '\\':
            escape_next = True
            continue
            
        if char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
        elif char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
    
    return in_double_quote or in_single_quote

def generate_all_boolean_logic_bug_variants_from_java_code(code: str) -> list:
    """
    Generates all buggy variants of the given Java code by swapping exactly one boolean
    operator occurrence. A candidate occurrence is any instance of "&&" or "||" that is
    NOT inside a string literal or comment.
    
    For each candidate occurrence, a new variant is produced where that occurrence is
    swapped: "&&" becomes "||" and vice versa. The bug is recorded as the 1-indexed line 
    number where the swap occurred.
    
    Returns a list of tuples: [(mutated_code, bug_line), ...]
    If no eligible operator is found, returns an empty list.
    """
    # Preserve trailing newlines
    trailing_newlines = ""
    if code.endswith('\n'):
        trailing_newlines = code[len(code.rstrip('\n')):]
    
    lines = code.splitlines(keepends=False)
    variants = []
    
    # Loop over every line.
    for i, line in enumerate(lines):
        # Use regex to find all occurrences of && or || in the line.
        for match in re.finditer(r'(&&|\|\|)', line):
            # Check if this match is inside a string or comment
            if is_inside_string_or_comment(line, match.start()):
                continue  # Skip this match
            
            orig_op = match.group()
            replacement = "||" if orig_op == "&&" else "&&"
            # Create a copy of the lines.
            new_lines = lines.copy()
            # Replace only the occurrence at the match's position.
            start, end = match.start(), match.end()
            new_line = line[:start] + replacement + line[end:]
            new_lines[i] = new_line
            mutated_code = "\n".join(new_lines) + trailing_newlines
            bug_line = i + 1  # 1-indexed
            variants.append((mutated_code, bug_line))
    return variants

def process_dataset(dataset_folder: str, output_folder: str) -> None:
    """
    Processes each JSON file in dataset_folder. Each JSON file is expected to contain:
      {
         "instruction": "...",
         "output": "<Java code ...>"
      }
    For each file:
      - Extracts the Java code from the "output" field.
      - Generates all buggy variants by swapping each eligible boolean operator exactly once.
      - For each variant, computes the bug line number percentage relative to the total lines.
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

        variants = generate_all_boolean_logic_bug_variants_from_java_code(code)
        if not variants:
            print(f"No eligible boolean operator found in {file_name}. Skipping.")
            skip_count += 1
            continue

        base_name, _ = os.path.splitext(file_name)
        variant_index = 1
        for mutated_code, bug_line in variants:
            total_lines = len(mutated_code.splitlines())
            if total_lines == 0:
                percent = 0
            else:
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
    dataset_folder = "java_dataset"  # Folder containing original JSON files with Java code in "output"
    buggy_dataset_folder = "java_buggy_dataset_boolean_logic"  # Output folder for mutated files
    process_dataset(dataset_folder, buggy_dataset_folder)

if __name__ == "__main__":
    main()

