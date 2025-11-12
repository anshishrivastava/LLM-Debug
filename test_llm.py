from pydantic import BaseModel
import json
import re
import os
import shutil
import sys
import csv
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
    # First argument is the LLM model.
    global LLM_MODEL
    LLM_MODEL = sys.argv[1] if len(sys.argv) > 1 else LLM_MODEL
    print(f"Using LLM model: {LLM_MODEL}")

    # Second argument is the input folder containing the buggy JSON files.
    buggy_dataset_folder = sys.argv[2] if len(sys.argv) > 2 else None
    if not buggy_dataset_folder:
        print("Input folder is required. Exiting.")
        sys.exit(1)
    
    # Optional third argument is the output folder for matched files.
    output_folder = sys.argv[3] if len(sys.argv) > 3 else None

    success_count = 0 
    failure_count = 0 
    total_count = 0

    # Initialize window counters for matches and mismatches.
    match_counts = {"0-25": 0, "25-50": 0, "50-75": 0, "75-100": 0}
    mismatch_counts = {"0-25": 0, "25-50": 0, "50-75": 0, "75-100": 0}

    # Lists to store filenames for match and mismatch verdicts.
    success_files = []
    failure_files = []

    # If an output folder is provided, ensure it exists.
    if output_folder is not None and not os.path.exists(output_folder):
        os.makedirs(output_folder)

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
        if predicted_line_no is None or predicted_line_no == -1:
            print("  LLM did not return a valid line number. Skipping file.")
            failure_count += 1
            continue

        if abs(predicted_line_no - original_line_no) <= 2:
            print(f"  LLM predicted line number: {original_line_no}")
            print("  Verdict: MATCH")
            success_count += 1
            match_counts[window] += 1
            success_files.append(filename)
            # If output folder is provided, copy the file to that folder.
            if output_folder is not None:
                shutil.copy(file_path, os.path.join(output_folder, filename))
        else:
            print(f"  LLM predicted line number: {predicted_line_no}")
            print("  Verdict: MISMATCH")
            failure_count += 1
            mismatch_counts[window] += 1
            failure_files.append(filename)

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

    # Extract metadata from the folder structure.
    # Assume folder structure: .../mutated_<language>_<BugType>_<MutationStrength>/<MutationType>
    mutation_type = os.path.basename(buggy_dataset_folder)
    parent_folder = os.path.basename(os.path.dirname(buggy_dataset_folder))
    language, bug_type, mutation_strength = "", "", ""
    if parent_folder.startswith("mutated_"):
        parent_info = parent_folder[len("mutated_"):]  # e.g., python_MisplacedReturn_1
        parts = parent_info.split("_")
        if len(parts) >= 3:
            language = parts[0]
            bug_type = parts[1]
            mutation_strength = parts[2]

    # Derive LLM type from the model string (e.g., "qwen2.5-coder" -> "coder").
    llm_type = LLM_MODEL.split("-")[-1]

    # Prepare CSV output.
    csv_file = f"results_{LLM_MODEL}_{language}.csv"
    header = [
        "Mutation Type",
        "Total Programs",
        "Success",
        "Failure",
        "Accuracy %",
        "Tested LLM",
        "Bug Type",
        "Mutation Strength",
        "LLM - Type",
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
        mutation_type,
        total_count,
        success_count,
        failure_count,
        accuracy_percent,
        LLM_MODEL,
        bug_type,
        mutation_strength,
        llm_type,
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
        # If the file exists, append a new row; otherwise, create a new file with header.
        file_exists = os.path.exists(csv_file)
        with open(csv_file, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(header)
            writer.writerow(row)
        print(f"\nResults written to {csv_file}")
    except Exception as e:
        print(f"Error writing to {csv_file}: {e}")

    # Write success and failure filenames to text files inside the input folder.
    success_txt_path = os.path.join(buggy_dataset_folder, "success.txt")
    fail_txt_path = os.path.join(buggy_dataset_folder, "fail.txt")
    try:
        with open(success_txt_path, "w", encoding="utf-8") as f:
            for fname in success_files:
                f.write(fname + "\n")
        with open(fail_txt_path, "w", encoding="utf-8") as f:
            for fname in failure_files:
                f.write(fname + "\n")
        print(f"\nMatch filenames written to {success_txt_path}")
        print(f"Mismatch filenames written to {fail_txt_path}")
    except Exception as e:
        print(f"Error writing success/failure files: {e}")

if __name__ == "__main__":
    main()
