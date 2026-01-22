"""Configuration for GitHub dataset collection."""

import os
from datetime import datetime

# GitHub API Configuration
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_API_BASE = "https://api.github.com"

# Search Parameters - Post-cutoff to ensure unseen data
# Most LLMs have training cutoffs around early 2024
REPO_CREATED_AFTER = "2024-06-01"  # Safe cutoff date
REPO_CREATED_BEFORE = "2025-01-22"  # Today

# Repository filters
MAX_STARS = 50  # Low-star repos less likely in training data
MIN_REPO_SIZE_KB = 10
MAX_REPO_SIZE_KB = 5000

# Code extraction settings
MIN_FUNCTION_LINES = 5
MAX_FUNCTION_LINES = 150
MIN_FILE_LINES = 10
MAX_FILE_LINES = 500

# Target samples per language
TARGET_SAMPLES_PYTHON = 400
TARGET_SAMPLES_JAVA = 400

# Output directories - use absolute paths relative to project root
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR_PYTHON = os.path.join(_PROJECT_ROOT, "agent_evaluation_python_dataset/new")
OUTPUT_DIR_JAVA = os.path.join(_PROJECT_ROOT, "agent_evaluation_java_dataset/new")

# Rate limiting
REQUESTS_PER_MINUTE = 30
SLEEP_BETWEEN_REQUESTS = 0.5  # seconds - reduced for speed

# Quality filters - code must contain at least one of these patterns
PYTHON_PATTERNS = {
    "boolean_logic": [" and ", " or ", " not ", "True", "False"],
    "loops": ["for ", "while "],
    "conditionals": ["if ", "elif ", "else:"],
    "arithmetic": [" + ", " - ", " * ", " / ", " % ", " // ", " ** "],
    "comparisons": [" == ", " != ", " < ", " > ", " <= ", " >= "],
}

JAVA_PATTERNS = {
    "boolean_logic": [" && ", " || ", "!", "true", "false"],
    "loops": ["for ", "for(", "while ", "while("],
    "conditionals": ["if ", "if(", "else ", "else{"],
    "arithmetic": [" + ", " - ", " * ", " / ", " % "],
    "comparisons": [" == ", " != ", " < ", " > ", " <= ", " >= "],
}

# Confidence scoring
def calculate_confidence(repo_created_date: str, stars: int, forks: int) -> str:
    """Calculate confidence that code is unseen in LLM training."""
    score = 0
    
    # Date-based scoring
    created = datetime.strptime(repo_created_date[:10], "%Y-%m-%d")
    cutoff = datetime.strptime("2024-06-01", "%Y-%m-%d")
    if created > cutoff:
        score += 40
    
    # Popularity-based scoring (less popular = more likely unseen)
    if stars == 0:
        score += 30
    elif stars < 5:
        score += 20
    elif stars < 20:
        score += 10
    
    if forks == 0:
        score += 20
    elif forks < 3:
        score += 10
    
    # Additional factors
    if created > datetime.strptime("2024-09-01", "%Y-%m-%d"):
        score += 10  # Very recent repos
    
    if score >= 80:
        return "very_high"
    elif score >= 60:
        return "high"
    elif score >= 40:
        return "medium"
    else:
        return "low"
