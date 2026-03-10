"""Configuration for Agent Evaluation Experiment.

Extended for CWE-inspired SAMs, expanded SPMs, multi-model evaluation,
and dual tolerance reporting.
"""

import os
import random

# ──────────────────────────────────────────────────────────────────────
# Reproducibility
# ──────────────────────────────────────────────────────────────────────
RANDOM_SEED = 42
random.seed(RANDOM_SEED)

# ──────────────────────────────────────────────────────────────────────
# Base paths (environment-aware)
# ──────────────────────────────────────────────────────────────────────
PROJECT_ROOT = os.environ.get(
    "LLM_DEBUG_ROOT",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
EXPERIMENT_ROOT = os.path.join(PROJECT_ROOT, "agent_evaluation_experiment")

# Dataset paths
JAVA_DATASET = os.path.join(PROJECT_ROOT, "agent_evaluation_java_dataset")
PYTHON_DATASET = os.path.join(PROJECT_ROOT, "agent_evaluation_python_dataset")

# Output directories
BUGGY_DATASETS_DIR = os.path.join(EXPERIMENT_ROOT, "buggy_datasets")
RESULTS_DIR = os.path.join(EXPERIMENT_ROOT, "results")
CHECKPOINTS_DIR = os.path.join(RESULTS_DIR, "checkpoints")
MUTATED_DIR = os.path.join(EXPERIMENT_ROOT, "mutated_datasets")
ARTIFACTS_DIR = os.path.join(EXPERIMENT_ROOT, "artifacts")

# Ensure output dirs exist
for _d in [BUGGY_DATASETS_DIR, RESULTS_DIR, CHECKPOINTS_DIR, MUTATED_DIR, ARTIFACTS_DIR]:
    os.makedirs(_d, exist_ok=True)

# ──────────────────────────────────────────────────────────────────────
# Dataset categories & languages
# ──────────────────────────────────────────────────────────────────────
DATASET_CATEGORIES = ["existing", "new"]
LANGUAGES = ["python", "java"]

# ──────────────────────────────────────────────────────────────────────
# SAM (Semantic Altering Mutations) — Bug Types
# ──────────────────────────────────────────────────────────────────────

# Legacy bug types (backward compatibility with prior experiments)
LEGACY_BUG_TYPES = ["BooleanLogic", "MisplacedReturn", "OffByOne", "OperatorSwap"]

# CWE-inspired bug types (new direction)
CWE_BUG_TYPES = [
    "CWE-480_IncorrectOperator",         # swap +/-, */, and/or, ==/!=
    "CWE-483_IncorrectBlockDelimitation", # un-indent / misplace brace
    "CWE-484_OmittedBreak",              # Java only: remove break in switch
    "CWE-563_UnusedAssignment",           # overwrite needed value
    "CWE-783_OperatorPrecedence",         # remove/add parens
    "CWE-835_LoopUnreachableExit",        # modify loop update direction
    "CWE-1025_WrongComparison",           # swap comparison operand
    "CWE-628_WrongArguments",             # swap function call arguments
]

# CWE to language applicability
CWE_LANGUAGE_SUPPORT = {
    "CWE-480_IncorrectOperator": ["python", "java"],
    "CWE-483_IncorrectBlockDelimitation": ["python", "java"],
    "CWE-484_OmittedBreak": ["java"],  # Java only
    "CWE-563_UnusedAssignment": ["python", "java"],
    "CWE-783_OperatorPrecedence": ["python", "java"],
    "CWE-835_LoopUnreachableExit": ["python", "java"],
    "CWE-1025_WrongComparison": ["python", "java"],
    "CWE-628_WrongArguments": ["python", "java"],
}

# Legacy to CWE mapping (for paper reference)
LEGACY_TO_CWE_MAP = {
    "BooleanLogic": "CWE-480",
    "OperatorSwap": "CWE-480",
    "OffByOne": "CWE-193",
    "MisplacedReturn": "CWE-483",
}

# Active bug types for current experiments (legacy + CWE)
BUG_TYPES = LEGACY_BUG_TYPES + CWE_BUG_TYPES

# ──────────────────────────────────────────────────────────────────────
# SPM (Semantic Preserving Mutations)
# ──────────────────────────────────────────────────────────────────────

# Existing SPMs (LLM-generated)
EXISTING_SPM_TYPES = ["commented", "variable", "dead_code"]

# New SPMs (algorithmic, no LLM needed)
NEW_SPM_TYPES = [
    "empty_lines",
    "void_functions",
    "void_conditionals",
    "void_loops",
    "function_reordering",
    "function_extraction",
]

# All SPM types
SPM_TYPES = EXISTING_SPM_TYPES + NEW_SPM_TYPES

# Cumulative SPM combinations
SPM_CUMULATIVE = [
    "variable_cumulative",      # commented + variable
    "dead_code_cumulative",     # commented + variable + dead_code
]

# Mutation strengths to test
MUTATION_STRENGTHS = [1, 2, 4]

# ──────────────────────────────────────────────────────────────────────
# Evaluation Parameters
# ──────────────────────────────────────────────────────────────────────

# Dual tolerance: report both for the paper
LINE_TOLERANCE_PRIMARY = 0    # exact match (primary metric)
LINE_TOLERANCE_SECONDARY = 2  # ±2 lines (secondary metric, backward compat)
LINE_TOLERANCE = LINE_TOLERANCE_PRIMARY  # default used by testers

# Temperature for all LLM evaluations
LLM_TEMPERATURE = 0

# Determinism check parameters
DETERMINISM_SAMPLE_SIZE = 100
DETERMINISM_REPETITIONS = 3
DETERMINISM_THRESHOLD = 0.95  # >95% consistency → single-run is defensible

# Checkpoint persistence
CHECKPOINT_BATCH_SIZE = 25  # save every N results

# ──────────────────────────────────────────────────────────────────────
# Models Configuration
# ──────────────────────────────────────────────────────────────────────

MODELS = {
    "qwen-coder-3b": {
        "backend": "ollama",
        "model_id": "qwen2.5-coder:3b",
        "task_allocation": "subset",      # primary open-source results
        "subset_size": 5000,
        "max_workers": 3,
        "description": "Open-source primary — 3B model, free",
    },
    "qwen-coder-1.5b": {
        "backend": "ollama",
        "model_id": "qwen2.5-coder:1.5b",
        "task_allocation": "subset",      # size scaling data point
        "subset_size": 5000,
        "max_workers": 3,
        "description": "Open-source small — 1.5B model, free (partial: 325 tasks done)",
    },
    "qwen-coder-7b": {
        "backend": "ollama",
        "model_id": "qwen2.5-coder:7b",
        "task_allocation": "subset",      # scaling curve mid-point
        "subset_size": 1000,
        "max_workers": 1,                 # 7B is GPU-heavy, single worker
        "description": "Open-source mid — 7B model, free (scaling curve)",
    },
    "claude-opus": {
        "backend": "anthropic",
        "model_id": "claude-opus-4-20250514",
        "task_allocation": "subset",      # frontier comparison — 2K subset
        "subset_size": 2000,
        "description": "Frontier model — 'even the best degrades' (~$97)",
    },
    # Claude Sonnet baseline already exists (176 samples, 39.77% accuracy)
    # GPT-4o-mini excluded — no OPENAI_API_KEY available
}

# Legacy field for backward compatibility
CODING_AGENTS = ["qwen2.5-coder:7b"]
LLM_BACKEND = "ollama"  # default backend for new experiments

# ──────────────────────────────────────────────────────────────────────
# Prompt Variants (for sensitivity analysis)
# ──────────────────────────────────────────────────────────────────────

PROMPT_VARIANTS = {
    "minimal": {
        "system": "You are a bug detector. Always respond with ONLY valid JSON in format {\"line_no\": N}. No explanations.",
        "user_template": 'Find the bug in this code. The code should: "{instruction}"\n\n```\n{code}\n```\n\nReply with ONLY this JSON, nothing else: {{"line_no": N}}\nWhere N is the line number containing the bug.',
    },
    "detailed": {
        "system": "You are an expert code reviewer specializing in bug detection. Analyze the code carefully and identify the exact line containing a bug. Respond with ONLY valid JSON: {\"line_no\": N}.",
        "user_template": 'The following code is intended to: "{instruction}"\n\nHowever, it contains a bug. Carefully analyze the code and identify the exact line number where the bug is located.\n\n```\n{code}\n```\n\nRespond with ONLY: {{"line_no": N}} where N is the buggy line number.',
    },
    "chain_of_thought": {
        "system": "You are an expert code reviewer. First analyze the code step by step, then identify the buggy line. End your response with ONLY the JSON: {\"line_no\": N}.",
        "user_template": 'This code should: "{instruction}"\n\nIt contains a bug. Analyze step by step:\n1. What should the code do?\n2. Trace through the logic\n3. Where does it deviate from the expected behavior?\n\n```\n{code}\n```\n\nAfter your analysis, respond with ONLY: {{"line_no": N}}',
    },
}

# Primary prompt used for full experiments
PRIMARY_PROMPT = "minimal"

# Prompt sensitivity subset size
PROMPT_SENSITIVITY_SUBSET_SIZE = 5000

# ──────────────────────────────────────────────────────────────────────
# Control Arm (False Positive Testing)
# ──────────────────────────────────────────────────────────────────────
CONTROL_ARM_ENABLED = True  # test clean code and clean+SPM code
