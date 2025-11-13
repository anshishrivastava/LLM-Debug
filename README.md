# LLM Debug

A comprehensive framework for evaluating Large Language Models (LLMs) on their ability to detect and fix various types of bugs in Python and Java code. This project systematically injects bugs, tests LLM performance, and generates additional semantic preserving code mutations to assess model performance.

## Overview

This framework evaluates LLMs by:
1. **Injecting bugs** into clean code using specialized bug injection scripts
2. **Testing LLMs** on buggy code to see if they can identify and fix issues
3. **Generating mutants** with additional code variations (dead code, misleading comments, variable renames)
4. **Evaluating robustness** across multiple mutation levels and types

## Project Structure

```
.
├── add-bug-*.py              # Bug injection scripts
├── generate_mutants.py       # SPM generation
├── test_llm_original.py     # Test LLMs on buggy code
├── test_llm.py               # Test LLMs on mutated code
├── final_script_python.sh   # Main execution pipeline
├── python_dataset/          # Original Python code samples
├── java_dataset/             # Original Java code samples
```

## Bug Types

The framework supports four main bug categories:

### 1. Boolean Logic Bugs (`BooleanLogic`)
- **Python**: Swaps `and`/`or` operators in boolean expressions
- **Java**: Swaps `&&`/`||` operators in boolean expressions
- **Scripts**: 
  - `add-bug-boolean-logic-python-fixed.py`
  - `add-bug-boolean-logic-java-fixed.py`

### 2. Misplaced Return (`MisplacedReturn`)
- Inserts an early `return;` statement at the beginning of method bodies
- **Scripts**:
  - `add-bug-misplaced-return-python.py`
  - `add-bug-misplaced-return-java.py`

### 3. Off-by-One Errors (`OffByOne`)
- Introduces off-by-one errors in loops and array access
- **Scripts**:
  - `add-bug-off-by-one-python.py`
  - `add-bug-off-by-one-java.py`

### 4. Operator Swap (`OperatorSwap`)
- Swaps arithmetic operators (e.g., `+` ↔ `-`, `*` ↔ `/`)
- **Scripts**:
  - `add-bug-operator-swap-python.py`
  - `add-bug-operator-swap-java.py`

## Workflow

### Step 1: Bug Injection

Before running the main pipeline, inject bugs into your dataset using the `add-bug-*.py` scripts:

```bash
# For Python boolean logic bugs
python add-bug-boolean-logic-python.py

# For Java boolean logic bugs
python add-bug-boolean-logic-java.py

# For misplaced return bugs
python add-bug-misplaced-return-python.py
python add-bug-misplaced-return-java.py

# For off-by-one bugs
python add-bug-off-by-one-python.py
python add-bug-off-by-one-java.py

# For operator swap bugs
python add-bug-operator-swap-python.py
python add-bug-operator-swap-java.py
```

Each script:
- Reads JSON files from `python_dataset/` or `java_dataset/`
- Injects bugs and records the bug line number
- Outputs buggy variants to `python_buggy_dataset_*/` or `java_buggy_dataset_*/`

**Input Format** (JSON):
```json
{
  "instruction": "Write a function to...",
  "output": "def function():\n    return True"
}
```

**Output Format** (JSON):
```json
{
  "instruction": "Write a function to...",
  "buggy_code": "def function():\n    return False",
  "line_no": 2,
  "line_no_percent": "50%"
}
```

### Step 2: Main Pipeline Execution

Run the complete evaluation pipeline:

```bash
./final_script_python.sh <model_name>
```

**Example:**
```bash
./final_script_python.sh phi4:14b
./final_script_python.sh qwq
```

### Pipeline Stages

The `final_script_python.sh` script executes the following stages:

#### Stage 1: Initial LLM Testing
Tests the LLM on buggy code variants:
```bash
python test_llm_original.py <model> python_buggy_dataset_BooleanLogic python_buggy_dataset_boolean_logic_matched_<model>
python test_llm_original.py <model> python_buggy_dataset_MisplacedReturn python_buggy_dataset_misplaced_return_matched_<model>
python test_llm_original.py <model> python_buggy_dataset_OffByOne python_buggy_dataset_off_by_one_matched_<model>
python test_llm_original.py <model> python_buggy_dataset_OperatorSwap python_buggy_dataset_operator_swap_matched_<model>
```

#### Stage 2: Mutation Generation and Testing
For each mutation level (1, 2, 4, 6, 8):

1. **Generate Mutants**:
   ```bash
   python generate_mutants.py <input_dataset> <output_dir> <mutation_level> <model>
   ```
   
   Creates additional code variations:
   - **Dead Code**: Unreachable code blocks
   - **Misleading Comments**: Comments that don't match code behavior
   - **Variable Renames**: Renaming variables to misleading names
   - **Cumulative Variants**: Combinations of the above

2. **Test LLMs on Mutants**:
   ```bash
   python test_llm.py <model> <mutant_dir>/commented
   python test_llm.py <model> <mutant_dir>/variable
   python test_llm.py <model> <mutant_dir>/dead_code
   python test_llm.py <model> <mutant_dir>/variable_cumulative
   python test_llm.py <model> <mutant_dir>/dead_code_cumulative
   ```

## Mutation Types

The `generate_mutants.py` script creates five types of mutations:

1. **Commented** (`/commented`): Adds misleading comments that don't match code behavior
2. **Variable** (`/variable`): Renames variables to misleading names
3. **Dead Code** (`/dead_code`): Inserts unreachable code blocks
4. **Variable Cumulative** (`/variable_cumulative`): commented + variable
5. **Dead Code Cumulative** (`/dead_code_cumulative`): Commented + Variable + Dead code

## Output Structure

After running the pipeline, you'll find:

```
<model>-mutated_python_<BugType>_<level>/
├── commented/
├── variable/
├── dead_code/
├── variable_cumulative/
└── dead_code_cumulative/
```

Each directory contains:
- JSON files with mutated code
- Test results from LLM evaluations

## Requirements

### Python Dependencies
```bash
pip install ollama pydantic autopep8
```

### LLM Setup
The framework uses Ollama for LLM interactions. Ensure you have:
- Ollama installed and running
- Desired models pulled (e.g., `ollama pull qwq`)

### Dataset Format
- Input datasets should be in JSON format
- Each file contains `instruction` and `output` fields
- Place datasets in `python_dataset/` or `java_dataset/` directories

## Usage Examples

### Complete Workflow

```bash
# 1. Inject bugs
python add-bug-boolean-logic-python.py
python add-bug-misplaced-return-python.py
python add-bug-off-by-one-python.py
python add-bug-operator-swap-python.py

# 2. Run evaluation pipeline
./final_script_python.sh gemini-1.5-pro
```

### Testing Individual Components

```bash
# Test bug injection
python add-bug-boolean-logic-python.py

# Test LLM on buggy code
python test_llm_original.py gemini-1.5-pro python_buggy_dataset_BooleanLogic output_dir

# Generate mutants
python generate_mutants.py python_buggy_dataset_BooleanLogic output_dir 1 gemini-1.5-pro

# Test LLM on mutants
python test_llm.py qwq output_dir/commented
```

## Results Analysis

Results are stored in CSV format:
- `results_original_<model>_<Language>.csv`: Initial LLM performance on buggy code
- `results_<model>_<language>.csv`: Performance on mutated code

## Notes


- **Model Compatibility**: The framework is designed to work with any Ollama-compatible model
- **Scalability**: The pipeline can process large datasets, with results organized by model and bug type

## Troubleshooting

1. **Ollama Connection Issues**: Ensure Ollama is running (`ollama serve`)
2. **Model Not Found**: Pull the model first (`ollama pull <model_name>`)
3. **JSON Parsing Errors**: Verify input JSON files are valid
4. **Permission Errors**: Make scripts executable (`chmod +x final_script_python.sh`)

## Contributing

When adding new bug types:
1. Create `add-bug-<type>-<language>.py` script
2. Follow the existing JSON input/output format
3. Record bug line numbers for evaluation
4. Update this README with the new bug type

## License


