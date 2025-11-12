import os
import sys
import json
import random
import re
import ast
import tokenize
import io
import textwrap
import autopep8
from tokenize import TokenInfo
from pydantic import BaseModel, ValidationError
from ollama import chat
###############################################################################
# Pydantic models for LLM outputs (for prospective mutation data)
###############################################################################

class DeadCodeLLM(BaseModel):
    dead_code_blocks: list[str]

class MisleadingCommentsLLM(BaseModel):
    misleading_comments: list[str]

class MisleadingVarsLLM(BaseModel):
    misleading_variables: list[str]

###############################################################################
# Functions to fetch mutation snippets from LLM
###############################################################################

def fetch_dead_code_blocks(code_text: str, max_inserts: int, llm_model="qwen2.5-coder") -> list[str]:
    prompt = f"""
Below is some code:
{code_text}

Using the above code as inspiration, generate {max_inserts} dead code blocks (2-3 lines).
Return them in a JSON structure with a key "dead_code_blocks" containing a list of strings.
No extra text, no explanations, just valid JSON.
"""
    response = chat(
        messages=[{"role": "user", "content": prompt}],
        model=llm_model,
        format=DeadCodeLLM.model_json_schema()
    )
    parsed = DeadCodeLLM.model_validate_json(response.message.content)
    return parsed.dead_code_blocks

def fetch_misleading_comments(code_text: str, max_inserts: int, llm_model="qwen2.5-coder") -> list[str]:
    prompt = f"""
Below is some code:
{code_text}

Using the above code as inspiration, generate {max_inserts} misleading single-line comments (like "# ...").
Return them in a JSON structure with a key "misleading_comments" containing a list of strings.
No extra text, no explanations, just valid JSON.
"""
    response = chat(
        messages=[{"role": "user", "content": prompt}],
        model=llm_model,
        format=MisleadingCommentsLLM.model_json_schema()
    )
    parsed = MisleadingCommentsLLM.model_validate_json(response.message.content)
    return parsed.misleading_comments

def fetch_misleading_variables(max_inserts: int, llm_model="qwen2.5-coder") -> list[str]:
    prompt = f"""
Generate {max_inserts} meaningless or misleading variable names.
Return them in a JSON structure with a key "misleading_variables" containing a list of strings.
No extra text, no explanations.
"""
    response = chat(
        messages=[{"role": "user", "content": prompt}],
        model=llm_model,
        format=MisleadingVarsLLM.model_json_schema()
    )
    parsed = MisleadingVarsLLM.model_validate_json(response.message.content)
    return parsed.misleading_variables

def generate_mutation_config(code_text: str, max_inserts: int, llm_model: str) -> dict:
    """
    Uses LLM to generate prospective mutation snippets based on the input code.
    Returns a dictionary with keys for dead code, misleading comments, and misleading variables.
    """
    seed_value = "seedlab-vt"
    decompose_max_inserts = 1  # Not used in current pipeline

    dead_code_list = fetch_dead_code_blocks(code_text, max_inserts, llm_model)
    comments_list = fetch_misleading_comments(code_text, max_inserts, llm_model)
    variables_list = fetch_misleading_variables(max_inserts, llm_model)

    result_dict = {
        "configs": {
            "seed": seed_value
        },
        "mutations": {
            "dead_code": {
                "max_inserts": max_inserts,
                "snippets": dead_code_list
            },
            "misleading_comments": {
                "max_inserts": max_inserts,
                "comments": comments_list
            },
            "misleading_variables": {
                "max_inserts": max_inserts,
                "variables": variables_list
            },
            "decompose": {
                "max_inserts": decompose_max_inserts
            }
        }
    }
    return result_dict

###############################################################################
# Helper Functions for Mutations on Code String
###############################################################################

def insert_comments_str(code: str, bug_line: int, num_comments: int, comments_list: list) -> tuple:
    """
    Inserts misleading comments into the code string at random statement positions.
    Returns (new_code, new_bug_line) with bug_line adjusted if insertions occur before it.
    """
    try:
        tree = ast.parse(code)
    except Exception as e:
        code = autopep8.fix_code(code)
        try:
            tree = ast.parse(code)
        except Exception as e:
            return code, bug_line

    statement_lines = sorted({node.lineno for node in ast.walk(tree) if hasattr(node, 'lineno')})
    if num_comments > len(comments_list):
        raise ValueError("Requested number of comments exceeds available comments")
    if not statement_lines:
        return code, bug_line

    random.shuffle(statement_lines)
    insert_positions = sorted(statement_lines[:num_comments])
    updated_lines = code.splitlines()
    new_bug_line = bug_line
    comment_index = 0
    for pos in insert_positions:
        if comment_index < num_comments:
            updated_lines.insert(pos - 1, comments_list[comment_index])
            comment_index += 1
            if pos <= bug_line:
                new_bug_line += 1
    new_code = "\n".join(updated_lines) + "\n"
    return new_code, new_bug_line

def update_variable_names_str(code: str, bug_line: int, num_vars: int, vars_list: list) -> tuple:
    """
    Renames variables in the code string by replacing some variable names with new names.
    Returns (new_code, bug_line) — bug_line remains unchanged.
    """
    try:
        tree = ast.parse(code)
    except Exception as e:
        code = autopep8.fix_code(code)
        try:
            tree = ast.parse(code)
        except Exception as e:
            return code, bug_line

    class VariableCollector(ast.NodeVisitor):
        def __init__(self):
            self.variables = set()
        def visit_Name(self, node):
            if isinstance(node.ctx, ast.Store):
                self.variables.add(node.id)
            self.generic_visit(node)

    collector = VariableCollector()
    collector.visit(tree)
    old_vars = list(collector.variables)
    rename_map = dict(zip(old_vars[:num_vars], vars_list[:num_vars]))

    tokens = []
    try:
        bytes_io = io.BytesIO(code.encode('utf-8'))
        for tok in tokenize.tokenize(bytes_io.readline):
            if tok.type == tokenize.NAME and tok.string in rename_map:
                tok = TokenInfo(tok.type, rename_map[tok.string], tok.start, tok.end, tok.line)
            tokens.append(tok)
    except tokenize.TokenError as e:
        return code, bug_line

    new_code_bytes = tokenize.untokenize(tokens)
    new_code = new_code_bytes.decode('utf-8') if isinstance(new_code_bytes, bytes) else new_code_bytes
    return new_code, bug_line

def get_base_indent(lines: list, pos: int) -> str:
    """
    Determines the base indentation at a given line position in the list of lines.
    """
    if pos < len(lines):
        line = lines[pos]
        match = re.match(r'^(\s*)', line)
        if match:
            return match.group(1)
    for i in range(pos - 1, -1, -1):
        if lines[i].strip():
            match = re.match(r'^(\s*)', lines[i])
            if match:
                return match.group(1)
    return ""

def indent_snippet(snippet: str, base_indent: str) -> list:
    """
    Dedents the snippet and re-indents each line with base_indent.
    Returns a list of lines.
    """
    dedented = textwrap.dedent(snippet)
    snippet_lines = dedented.splitlines()
    return [base_indent + line + "\n" for line in snippet_lines if line.strip() != ""]

def insert_dead_code_snippets_str(code: str, bug_line: int, num_dead: int, dead_snippets: list) -> tuple:
    """
    Inserts dead-code snippets into the code string at random positions.
    Adjusts bug_line if insertions occur before the original bug line.
    Returns (new_code, new_bug_line).
    """
    original_lines = code.splitlines(keepends=True)
    total_lines = len(original_lines)
    num_snippets = min(num_dead, len(dead_snippets), total_lines)
    if num_snippets <= 0:
        return code, bug_line

    chosen_snippets = random.sample(dead_snippets, num_snippets)
    insertion_positions = sorted(random.sample(range(0, total_lines + 1), num_snippets))
    extra_lines_before_bug = 0
    for pos, snippet in zip(insertion_positions, chosen_snippets):
        if pos <= (bug_line - 1):
            extra_lines_before_bug += len(textwrap.dedent(snippet).splitlines())
    new_bug_line = bug_line + extra_lines_before_bug

    new_lines = []
    current_index = 0
    for pos, snippet in sorted(zip(insertion_positions, chosen_snippets), key=lambda tup: tup[0]):
        while current_index < pos:
            new_lines.append(original_lines[current_index])
            current_index += 1
        base_indent = get_base_indent(original_lines, pos)
        snippet_lines = indent_snippet(snippet, base_indent)
        new_lines.extend(snippet_lines)
    while current_index < total_lines:
        new_lines.append(original_lines[current_index])
        current_index += 1

    new_code = "".join(new_lines)
    return new_code, new_bug_line

###############################################################################
# Combined Pipeline: Generate Mutation Config and Apply Mutations
###############################################################################

def process_dataset(dataset_folder: str, output_folder: str, max_inserts: int, llm_model: str) -> None:
    """
    Processes each JSON file in dataset_folder. Each JSON is expected to contain:
      {
         "instruction": "...",
         "buggy_code": "...",
         "line_no": <line number>,
         "line_no_percent": "..."
      }
    For each file, the function:
      1. Generates mutation configuration via LLM calls.
      2. Applies three mutation phases in two variants:
         a. Non-cumulative mutations applied directly on the original buggy code:
            - Insert misleading comments -> output folder "commented"
            - Update variable names -> output folder "variable"
            - Insert dead code snippets -> output folder "dead_code"
         b. Cumulative mutations where:
            - First, misleading comments are inserted,
            - Then variable renaming is applied to the commented code,
            - Finally, dead code is inserted on the variable-renamed (cumulative) code.
            These outputs are saved in "variable_cumulative" and "dead_code_cumulative" folders.
    """
    # Create required output folders.
    os.makedirs(output_folder, exist_ok=True)
    commented_folder = os.path.join(output_folder, "commented")
    variable_folder = os.path.join(output_folder, "variable")
    dead_code_folder = os.path.join(output_folder, "dead_code")
    variable_cumulative_folder = os.path.join(output_folder, "variable_cumulative")
    dead_code_cumulative_folder = os.path.join(output_folder, "dead_code_cumulative")
    for folder in [commented_folder, variable_folder, dead_code_folder, variable_cumulative_folder, dead_code_cumulative_folder]:
        os.makedirs(folder, exist_ok=True)

    code_files = [f for f in os.listdir(dataset_folder) if f.lower().endswith(".json")]
    total_files = len(code_files)
    processed_count = 0

    for file_name in code_files:
        file_path = os.path.join(dataset_folder, file_name)
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                code_data = json.load(f)
        except Exception as e:
            print(f"Error reading {file_name}: {e}")
            continue

        instruction = code_data.get("instruction", "").strip()
        buggy_code = code_data.get("buggy_code", "").strip()
        bug_line = code_data.get("line_no")
        # We will recompute line_no_percent based on the mutated code.
        if not buggy_code or bug_line is None:
            print(f"Missing required fields in {file_name}. Skipping.")
            continue

        # Generate mutation configuration using LLM (without saving intermediate JSON)
        try:
            mutation_config = generate_mutation_config(buggy_code, max_inserts, llm_model)
        except Exception as e:
            print(f"Error generating mutation config for {file_name}: {e}. Skipping file.")
            continue

        mutations = mutation_config.get("mutations", {})
        misleading_comments_data = mutations.get("misleading_comments", {})
        misleading_vars_data = mutations.get("misleading_variables", {})
        dead_code_data = mutations.get("dead_code", {})

        num_comments = misleading_comments_data.get("max_inserts", 0)
        comments_list = misleading_comments_data.get("comments", [])
        num_vars = misleading_vars_data.get("max_inserts", 0)
        vars_list = misleading_vars_data.get("variables", [])
        num_dead = dead_code_data.get("max_inserts", 0)
        dead_snippets = dead_code_data.get("snippets", [])

        # Non-cumulative mutations on original buggy code.
        try:
            # a. Insert misleading comments on original buggy code.
            commented_code, new_line_commented = insert_comments_str(buggy_code, bug_line, num_comments, comments_list)
            total_lines = len(commented_code.splitlines())
            updated_percent = f"{round((new_line_commented/total_lines)*100)}%"
        except Exception as e:
            print(f"Error inserting comments in {file_name}: {e}")
            continue
        commented_json = {
            "instruction": instruction,
            "buggy_code": commented_code,
            "line_no": new_line_commented,
            "line_no_percent": updated_percent
        }
        out_commented = os.path.join(commented_folder, file_name)
        try:
            with open(out_commented, "w", encoding="utf-8") as f:
                json.dump(commented_json, f, indent=2)
        except Exception as e:
            print(f"Error writing commented file {file_name}: {e}")
            continue

        try:
            # b. Update variable names on original buggy code.
            variable_code, new_line_variable = update_variable_names_str(buggy_code, bug_line, num_vars, vars_list)
            total_lines = len(variable_code.splitlines())
            updated_percent = f"{round((new_line_variable/total_lines)*100)}%"
        except Exception as e:
            print(f"Error updating variable names in {file_name}: {e}")
            continue
        variable_json = {
            "instruction": instruction,
            "buggy_code": variable_code,
            "line_no": new_line_variable,
            "line_no_percent": updated_percent
        }
        out_variable = os.path.join(variable_folder, file_name)
        try:
            with open(out_variable, "w", encoding="utf-8") as f:
                json.dump(variable_json, f, indent=2)
        except Exception as e:
            print(f"Error writing variable file {file_name}: {e}")
            continue

        try:
            # c. Insert dead code snippets on original buggy code.
            dead_code_final, new_line_dead = insert_dead_code_snippets_str(buggy_code, bug_line, num_dead, dead_snippets)
            total_lines = len(dead_code_final.splitlines())
            updated_percent = f"{round((new_line_dead/total_lines)*100)}%"
        except Exception as e:
            print(f"Error inserting dead code in {file_name}: {e}")
            continue
        dead_code_json = {
            "instruction": instruction,
            "buggy_code": dead_code_final,
            "line_no": new_line_dead,
            "line_no_percent": updated_percent
        }
        out_dead = os.path.join(dead_code_folder, file_name)
        try:
            with open(out_dead, "w", encoding="utf-8") as f:
                json.dump(dead_code_json, f, indent=2)
        except Exception as e:
            print(f"Error writing dead code file {file_name}: {e}")
            continue

        # Cumulative mutations: apply variable mutation on commented code, then dead code on that result.
        try:
            # d. Update variable names on the commented code.
            variable_comm_code, new_line_var_comm = update_variable_names_str(commented_code, new_line_commented, num_vars, vars_list)
            total_lines = len(variable_comm_code.splitlines())
            updated_percent = f"{round((new_line_var_comm/total_lines)*100)}%"
        except Exception as e:
            print(f"Error updating variable names cumulatively in {file_name}: {e}")
            continue
        variable_comm_json = {
            "instruction": instruction,
            "buggy_code": variable_comm_code,
            "line_no": new_line_var_comm,
            "line_no_percent": updated_percent
        }
        out_variable_comm = os.path.join(variable_cumulative_folder, file_name)
        try:
            with open(out_variable_comm, "w", encoding="utf-8") as f:
                json.dump(variable_comm_json, f, indent=2)
        except Exception as e:
            print(f"Error writing cumulative variable file {file_name}: {e}")
            continue

        try:
            # e. Insert dead code snippets on the cumulative variable code.
            dead_code_comm_code, new_line_dead_comm = insert_dead_code_snippets_str(variable_comm_code, new_line_var_comm, num_dead, dead_snippets)
            total_lines = len(dead_code_comm_code.splitlines())
            updated_percent = f"{round((new_line_dead_comm/total_lines)*100)}%"
        except Exception as e:
            print(f"Error inserting dead code cumulatively in {file_name}: {e}")
            continue
        dead_code_comm_json = {
            "instruction": instruction,
            "buggy_code": dead_code_comm_code,
            "line_no": new_line_dead_comm,
            "line_no_percent": updated_percent
        }
        out_dead_comm = os.path.join(dead_code_cumulative_folder, file_name)
        try:
            with open(out_dead_comm, "w", encoding="utf-8") as f:
                json.dump(dead_code_comm_json, f, indent=2)
        except Exception as e:
            print(f"Error writing cumulative dead code file {file_name}: {e}")
            continue

        processed_count += 1
        print(f"Processed {file_name}")

    print(f"\nTotal files processed: {processed_count} out of {total_files}")

def main():
    if len(sys.argv) != 5:
        print("Usage: python pipeline.py <dataset_folder> <output_folder> <max_inserts> <llm_model>")
        sys.exit(1)

    dataset_folder = sys.argv[1]         # Folder with original JSON files.
    output_folder = sys.argv[2]           # Base output folder.
    max_inserts = int(sys.argv[3])        # Max inserts for mutations.
    llm_model = sys.argv[4]               # LLM model name.
    process_dataset(dataset_folder, output_folder, max_inserts, llm_model)

if __name__ == "__main__":
    main()
