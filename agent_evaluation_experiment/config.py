"""Configuration for Agent Evaluation Experiment."""

import os

# Base paths
PROJECT_ROOT = "/Users/anshishr/OfflineProjects/LLM-Debug"
EXPERIMENT_ROOT = os.path.join(PROJECT_ROOT, "agent_evaluation_experiment")

# Dataset paths
JAVA_DATASET = os.path.join(PROJECT_ROOT, "agent_evaluation_java_dataset")
PYTHON_DATASET = os.path.join(PROJECT_ROOT, "agent_evaluation_python_dataset")

# Output directories
BUGGY_DATASETS_DIR = os.path.join(EXPERIMENT_ROOT, "buggy_datasets")
RESULTS_DIR = os.path.join(EXPERIMENT_ROOT, "results")
MUTATED_DIR = os.path.join(EXPERIMENT_ROOT, "mutated_datasets")

# Bug types to inject
BUG_TYPES = ["BooleanLogic", "MisplacedReturn", "OffByOne", "OperatorSwap"]

# Dataset categories
DATASET_CATEGORIES = ["existing", "new"]

# Languages
LANGUAGES = ["python", "java"]

# Coding agents/models to test (Ollama models - free, local)
CODING_AGENTS = [
    "qwen2.5-coder:7b",   # Qwen coding model (downloaded)
]

# Backend configuration: "ollama" or "openai" or "anthropic"
LLM_BACKEND = "ollama"

# SPM mutation types
SPM_TYPES = ["commented", "variable", "dead_code", "variable_cumulative", "dead_code_cumulative"]

# Mutation strengths to test
MUTATION_STRENGTHS = [1, 2, 4]

# Tolerance for line number matching (±2 lines)
LINE_TOLERANCE = 2
