#!/usr/bin/env python3
import os
import sys
import json
import re
import shutil
import csv
from pydantic import BaseModel
from ollama import chat

# Default model name, can be overwritten from the command line.
LLM_MODEL = "qwen2.5-coder"

class BugLine(BaseModel):
    line_no: int

def ask_llm_for_bug_line(instruction: str, buggy_code: str) -> int:
    """
    Calls the LLM with a structured format to obtain the bug's exact line number.
    Returns the predicted line number (int) or -1 if parsing fails.
    """
    response = chat(
        messages=[
            {
                'role': 'user',
                'content': f'I want this code to "{instruction}" but I am experiencing unexpected output.\n'
                           f'Buggy Code:\n{buggy_code}\n'
                           f'Can you give me the exact line number where the bug is?',
            }
        ],
        model=LLM_MODEL,
        format=BugLine.model_json_schema()
    )

    try:
        bug_line_obj = BugLine.model_validate_json(response.message.content)
        return bug_line_obj.line_no
    except Exception as e:
        print("Failed to parse LLM response as JSON:", response.message.content)
        return -1
    
def main():
    global LLM_MODEL
    # First argument: LLM model (optional)
    LLM_MODEL = sys.argv[1] if len(sys.argv) > 1 else LLM_MODEL
    print(f"Using LLM model: {LLM_MODEL}")

    # Second argument: input folder containing buggy JSON files.
    buggy_dataset_folder = sys.argv[2] if len(sys.argv) > 2 else None
    if not buggy_dataset_folder:
        print("Input folder is required. Exiting.")
        sys.exit(1)
    
    # Optional third argument: output folder for matched files.
    output_folder = sys.argv[3] if len(sys.argv) > 3 else None
    if output_folder is not None and not os.path.exists(output_folder):
        os.makedirs(output_folder)
    
    success_count = 0 
    failure_count = 0 
    total_count = 0

    # Initialize window counters for matches and mismatches.
    match_counts = {"0-25": 0, "25-50": 0, "50-75": 0, "75-100": 0}
    mismatch_counts = {"0-25": 0, "25-50": 0, "50-75": 0, "75-100": 0}

    # Process every JSON file in the buggy_dataset folder.
    for filename in os.listdir(buggy_dataset_folder):
        if not filename.lower().endswith(".json"):
            continue
        file_path = os.path.join(buggy_dataset_folder, filename)
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"Error reading {filename}: {e}")
            continue

        # Each JSON is expected to have "instruction", "buggy_code", "line_no", and "line_no_percent"
        instruction = data.get("instruction", "").strip()
        buggy_code = data.get("buggy_code", "").strip()
        original_line_no = data.get("line_no")
        line_no_percent = data.get("line_no_percent", "").strip()
        
        if not instruction or not buggy_code or original_line_no is None or not line_no_percent:
            print(f"Missing required fields in {filename}. Skipping.")
            failure_count += 1
            continue

        # Determine the window based on line_no_percent.
        try:
            percent_value = float(line_no_percent.strip('%'))
        except ValueError:
            print(f"Invalid line_no_percent value in {filename}. Skipping.")
            failure_count += 1
            continue

        if percent_value < 25:
            window = "0-25"
        elif percent_value < 50:
            window = "25-50"
        elif percent_value < 75:
            window = "50-75"
        else:
            window = "75-100"

        print(f"\nProcessing {filename}:")
        print(f"  Original line number: {original_line_no}")

        # Ask LLM for the bug line using a new context.
        predicted_line_no = ask_llm_for_bug_line(instruction, buggy_code)
        if predicted_line_no == -1:
            print("  LLM did not return a valid line number. Skipping file.")
            failure_count += 1
            continue

        if abs(predicted_line_no - original_line_no) <= 2:
            print(f"  LLM predicted line number: {original_line_no}")
            print("  Verdict: MATCH")
            success_count += 1
            match_counts[window] += 1
            if output_folder is not None:
                shutil.copy(file_path, os.path.join(output_folder, filename))
        else:
            print(f"  LLM predicted line number: {predicted_line_no}")
            print("  Verdict: MISMATCH")
            failure_count += 1
            mismatch_counts[window] += 1

        total_count += 1
        print(f"  Total Count: {total_count}")
        print(f"  Success count (match): {success_count}")
        print(f"  Failure count (mismatch or error): {failure_count}")

    print("\nSummary:")
    print(f"  Tested Folder: {buggy_dataset_folder}")
    print(f"  Total files processed: {total_count}")
    print(f"  Success count (match): {success_count}")
    print(f"  Failure count (mismatch or error): {failure_count}")

    print("\nWindowed Results:")
    for win in ["0-25", "25-50", "50-75", "75-100"]:
        print(f"  Window {win}%: Matches = {match_counts[win]}, Mismatches = {mismatch_counts[win]}")

    # Compute overall accuracy.
    accuracy_percent = round((success_count / total_count) * 100, 2) if total_count > 0 else 0

    # Extract language and bug type from the folder name.
    # Expected folder name example: "java_buggy_dataset_BooleanLogic"
    folder_basename = os.path.basename(buggy_dataset_folder)
    parts = folder_basename.split('_')
    if len(parts) >= 3:
        language = parts[0].capitalize()  # e.g., "java" -> "Java"
        bug_type = parts[-1]
    else:
        language = ""
        bug_type = ""

    # Prepare CSV output.
    csv_file = f"results_original_{LLM_MODEL}_{language}.csv"
    header = [
        "Total Programs",
        "Success",
        "Failure",
        "Accuracy %",
        "Tested LLM",
        "Bug Type",
        "Language",
        "0-25 Success",
        "25-50 Success",
        "50-75 Success",
        "75-100 Success",
        "0-25 Failures",
        "25-50 Failures",
        "50-75 Failures",
        "75-100 Failures"
    ]
    row = [
        total_count,
        success_count,
        failure_count,
        accuracy_percent,
        LLM_MODEL,
        bug_type,
        language,
        match_counts["0-25"],
        match_counts["25-50"],
        match_counts["50-75"],
        match_counts["75-100"],
        mismatch_counts["0-25"],
        mismatch_counts["25-50"],
        mismatch_counts["50-75"],
        mismatch_counts["75-100"]
    ]

    # Write header and row to results.csv.
    try:
        file_exists = os.path.exists(csv_file)
        with open(csv_file, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(header)
            writer.writerow(row)
        print(f"\nResults written to {csv_file}")
    except Exception as e:
        print(f"Error writing to {csv_file}: {e}")

if __name__ == "__main__":
    main()
