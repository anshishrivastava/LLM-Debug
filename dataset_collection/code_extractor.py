"""Extract functions from Python and Java source files."""

import re
import ast
from typing import List, Dict, Optional, Tuple


def extract_python_functions(code: str) -> List[Dict]:
    """Extract functions from Python code using AST parsing."""
    functions = []
    
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return functions
    
    lines = code.split('\n')
    
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            try:
                # Get function source
                start_line = node.lineno - 1
                end_line = node.end_lineno if hasattr(node, 'end_lineno') else None
                
                if end_line is None:
                    # Fallback: find end by indentation
                    end_line = start_line + 1
                    base_indent = len(lines[start_line]) - len(lines[start_line].lstrip())
                    for i in range(start_line + 1, len(lines)):
                        if lines[i].strip() and not lines[i].startswith(' ' * (base_indent + 1)):
                            if not lines[i].strip().startswith('#'):
                                break
                        end_line = i + 1
                
                func_lines = lines[start_line:end_line]
                func_code = '\n'.join(func_lines)
                
                # Get docstring as instruction
                docstring = ast.get_docstring(node) or ""
                
                # Generate instruction from function name and docstring
                func_name = node.name
                if docstring:
                    instruction = docstring.split('\n')[0].strip()
                else:
                    # Convert function name to instruction
                    instruction = func_name.replace('_', ' ').title()
                
                functions.append({
                    "name": func_name,
                    "code": func_code,
                    "instruction": instruction,
                    "start_line": start_line + 1,
                    "end_line": end_line,
                    "num_lines": end_line - start_line,
                    "has_docstring": bool(docstring),
                })
            except Exception:
                continue
    
    return functions


def extract_java_functions(code: str) -> List[Dict]:
    """Extract methods from Java code using regex patterns."""
    functions = []
    lines = code.split('\n')
    
    # Pattern to match Java method declarations
    method_pattern = re.compile(
        r'^\s*(public|private|protected)?\s*(static)?\s*'
        r'(\w+(?:<[^>]+>)?)\s+(\w+)\s*\([^)]*\)\s*'
        r'(?:throws\s+[\w,\s]+)?\s*\{',
        re.MULTILINE
    )
    
    for match in method_pattern.finditer(code):
        try:
            start_pos = match.start()
            start_line = code[:start_pos].count('\n')
            
            # Find matching closing brace
            brace_count = 0
            end_line = start_line
            in_method = False
            
            for i, line in enumerate(lines[start_line:], start=start_line):
                brace_count += line.count('{') - line.count('}')
                if '{' in line:
                    in_method = True
                if in_method and brace_count == 0:
                    end_line = i + 1
                    break
            
            if end_line <= start_line:
                continue
            
            func_lines = lines[start_line:end_line]
            func_code = '\n'.join(func_lines)
            
            # Extract method name
            method_name = match.group(4)
            
            # Look for Javadoc comment above method
            docstring = ""
            if start_line > 0:
                for i in range(start_line - 1, max(0, start_line - 20), -1):
                    line = lines[i].strip()
                    if line.startswith('*/'):
                        # Found end of Javadoc, look for start
                        for j in range(i - 1, max(0, i - 30), -1):
                            if lines[j].strip().startswith('/**'):
                                doc_lines = lines[j:i+1]
                                docstring = ' '.join(
                                    l.strip().lstrip('/*').rstrip('*/').strip()
                                    for l in doc_lines
                                ).strip()
                                break
                        break
                    elif line and not line.startswith('*') and not line.startswith('@'):
                        break
            
            # Generate instruction
            if docstring:
                instruction = docstring.split('.')[0].strip()
            else:
                # Convert method name to instruction
                instruction = re.sub(r'([A-Z])', r' \1', method_name).strip().title()
            
            functions.append({
                "name": method_name,
                "code": func_code,
                "instruction": instruction,
                "start_line": start_line + 1,
                "end_line": end_line,
                "num_lines": end_line - start_line,
                "has_docstring": bool(docstring),
            })
        except Exception:
            continue
    
    return functions


def analyze_code_patterns(code: str, language: str) -> Dict[str, bool]:
    """Analyze what patterns exist in the code."""
    from config import PYTHON_PATTERNS, JAVA_PATTERNS
    
    patterns = PYTHON_PATTERNS if language == "python" else JAVA_PATTERNS
    results = {}
    
    for pattern_name, pattern_list in patterns.items():
        results[f"has_{pattern_name}"] = any(p in code for p in pattern_list)
    
    return results


def is_quality_function(func: Dict, language: str, min_lines: int = 5, max_lines: int = 150) -> bool:
    """Check if function meets quality criteria."""
    # Line count check
    if func["num_lines"] < min_lines or func["num_lines"] > max_lines:
        return False
    
    code = func["code"]
    
    # Must have meaningful instruction
    if len(func["instruction"]) < 10:
        return False
    
    # Skip test functions
    name_lower = func["name"].lower()
    if name_lower.startswith("test") or name_lower.startswith("_"):
        return False
    
    # Skip trivial getters/setters
    if name_lower.startswith("get") or name_lower.startswith("set"):
        if func["num_lines"] < 5:
            return False
    
    # Must contain some logic (not just pass/return)
    patterns = analyze_code_patterns(code, language)
    has_logic = any([
        patterns.get("has_loops", False),
        patterns.get("has_conditionals", False),
        patterns.get("has_boolean_logic", False),
    ])
    
    return has_logic
