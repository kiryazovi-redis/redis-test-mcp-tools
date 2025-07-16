"""
AST parsing tools for Redis Test MCP Tools.

This module provides functions for parsing Python AST and extracting
information about classes, functions, imports, and type hints.
"""

import ast
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# Import configuration
from ..config import config


def get_ast_from_file(file_path: str) -> Union[ast.AST, Dict[str, str]]:
    """Parse a Python file and return its AST or error information."""
    try:
        full_path = config.project_root / file_path
        if not full_path.exists():
            return {'error': f'File not found: {file_path}'}
        
        if not config.is_python_file(full_path):
            return {'error': f'Not a Python file: {file_path}'}
        
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return ast.parse(content)
    except SyntaxError as e:
        return {'error': f'Syntax error in {file_path}: {str(e)}'}
    except Exception as e:
        return {'error': f'Error parsing {file_path}: {str(e)}'}


def extract_docstring(node: ast.AST) -> Optional[str]:
    """Extract docstring from an AST node."""
    if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)) and
        node.body and isinstance(node.body[0], ast.Expr) and
        isinstance(node.body[0].value, ast.Constant) and
        isinstance(node.body[0].value.value, str)):
        return node.body[0].value.value
    return None


def get_type_annotation(annotation: Optional[ast.expr]) -> Optional[str]:
    """Convert type annotation AST node to string."""
    if annotation is None:
        return None
    try:
        return ast.unparse(annotation)
    except:
        return None


def extract_function_info(node: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> Dict[str, Any]:
    """Extract detailed information from a function/method AST node."""
    params = []
    for arg in node.args.args:
        param_info = {
            'name': arg.arg,
            'type': get_type_annotation(arg.annotation),
            'kind': 'positional'
        }
        params.append(param_info)
    
    # Handle *args
    if node.args.vararg:
        params.append({
            'name': node.args.vararg.arg,
            'type': get_type_annotation(node.args.vararg.annotation),
            'kind': 'vararg'
        })
    
    # Handle **kwargs
    if node.args.kwarg:
        params.append({
            'name': node.args.kwarg.arg,
            'type': get_type_annotation(node.args.kwarg.annotation),
            'kind': 'kwarg'
        })
    
    # Handle keyword-only arguments
    for arg in node.args.kwonlyargs:
        param_info = {
            'name': arg.arg,
            'type': get_type_annotation(arg.annotation),
            'kind': 'keyword_only'
        }
        params.append(param_info)
    
    # Handle default values
    defaults = node.args.defaults
    if defaults:
        # Map defaults to their corresponding parameters
        default_offset = len(node.args.args) - len(defaults)
        for i, default in enumerate(defaults):
            param_index = default_offset + i
            if param_index < len(params):
                try:
                    params[param_index]['default'] = ast.unparse(default)
                except:
                    params[param_index]['default'] = '<complex default>'
    
    return {
        'name': node.name,
        'type': 'async_function' if isinstance(node, ast.AsyncFunctionDef) else 'function',
        'docstring': extract_docstring(node),
        'parameters': params,
        'return_type': get_type_annotation(node.returns),
        'decorators': [ast.unparse(dec) for dec in node.decorator_list],
        'line_number': node.lineno
    }


def extract_class_info(node: ast.ClassDef) -> Dict[str, Any]:
    """Extract detailed information from a class AST node."""
    methods = []
    properties = []
    class_variables = []
    
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            method_info = extract_function_info(item)
            method_info['visibility'] = 'private' if item.name.startswith('_') else 'public'
            
            # Check if it's a property
            is_property = any(
                (isinstance(dec, ast.Name) and dec.id == 'property') or
                (isinstance(dec, ast.Attribute) and dec.attr == 'property')
                for dec in item.decorator_list
            )
            
            if is_property:
                properties.append(method_info)
            else:
                methods.append(method_info)
                
        elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
            # Class variable with type annotation
            class_variables.append({
                'name': item.target.id,
                'type': get_type_annotation(item.annotation),
                'line_number': item.lineno
            })
        elif isinstance(item, ast.Assign):
            # Class variable without type annotation
            for target in item.targets:
                if isinstance(target, ast.Name):
                    class_variables.append({
                        'name': target.id,
                        'type': None,
                        'line_number': item.lineno
                    })
    
    # Extract base classes
    base_classes = []
    for base in node.bases:
        try:
            base_classes.append(ast.unparse(base))
        except:
            base_classes.append('<complex base>')
    
    return {
        'name': node.name,
        'type': 'class',
        'docstring': extract_docstring(node),
        'base_classes': base_classes,
        'methods': methods,
        'properties': properties,
        'class_variables': class_variables,
        'decorators': [ast.unparse(dec) for dec in node.decorator_list],
        'line_number': node.lineno
    }


def parse_module_ast(file_path: str) -> Dict[str, Any]:
    """Parse a Python module and extract all classes and functions."""
    ast_result = get_ast_from_file(file_path)
    
    if isinstance(ast_result, dict) and 'error' in ast_result:
        return ast_result
    
    tree = ast_result
    result = {
        'file_path': file_path,
        'functions': [],
        'classes': [],
        'imports': [],
        'docstring': extract_docstring(tree)
    }
    
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Only include top-level functions (not methods)
            if any(isinstance(parent, ast.ClassDef) for parent in ast.walk(tree) 
                   if hasattr(parent, 'body') and node in getattr(parent, 'body', [])):
                continue
            result['functions'].append(extract_function_info(node))
        
        elif isinstance(node, ast.ClassDef):
            result['classes'].append(extract_class_info(node))
    
    return result


def get_function_details(file_path: str, function_name: str) -> Dict[str, Any]:
    """Get detailed information about a specific function."""
    ast_result = get_ast_from_file(file_path)
    
    if isinstance(ast_result, dict) and 'error' in ast_result:
        return ast_result
    
    tree = ast_result
    
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            return extract_function_info(node)
    
    return {'error': f'Function "{function_name}" not found in {file_path}'}


def get_class_details(file_path: str, class_name: str) -> Dict[str, Any]:
    """Get detailed information about a specific class."""
    ast_result = get_ast_from_file(file_path)
    
    if isinstance(ast_result, dict) and 'error' in ast_result:
        return ast_result
    
    tree = ast_result
    
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return extract_class_info(node)
    
    return {'error': f'Class "{class_name}" not found in {file_path}'}


def find_imports_in_file(file_path: str) -> Dict[str, Any]:
    """Find all imports in a Python file."""
    ast_result = get_ast_from_file(file_path)
    
    if isinstance(ast_result, dict) and 'error' in ast_result:
        return ast_result
    
    tree = ast_result
    imports = {
        'file_path': file_path,
        'standard_imports': [],
        'third_party_imports': [],
        'local_imports': [],
        'from_imports': []
    }
    
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                import_info = {
                    'module': alias.name,
                    'alias': alias.asname,
                    'line_number': node.lineno
                }
                
                # Categorize import
                if alias.name.startswith('.'):
                    imports['local_imports'].append(import_info)
                elif any(alias.name.startswith(lib) for lib in ['os', 'sys', 'json', 'ast', 'typing', 're', 'pathlib']):
                    imports['standard_imports'].append(import_info)
                else:
                    imports['third_party_imports'].append(import_info)
        
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                import_info = {
                    'module': node.module or '',
                    'name': alias.name,
                    'alias': alias.asname,
                    'level': node.level,
                    'line_number': node.lineno
                }
                imports['from_imports'].append(import_info)
    
    return imports


def get_type_hints_from_file(file_path: str) -> Dict[str, Any]:
    """Extract type annotations from functions/methods in a Python file."""
    ast_result = get_ast_from_file(file_path)
    
    if isinstance(ast_result, dict) and 'error' in ast_result:
        return ast_result
    
    tree = ast_result
    type_hints = {
        'file_path': file_path,
        'functions': [],
        'classes': []
    }
    
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_types = {
                'name': node.name,
                'parameters': [],
                'return_type': get_type_annotation(node.returns),
                'line_number': node.lineno
            }
            
            # Extract parameter types
            for arg in node.args.args:
                func_types['parameters'].append({
                    'name': arg.arg,
                    'type': get_type_annotation(arg.annotation)
                })
            
            # Check if this is a class method
            parent_class = None
            for parent in ast.walk(tree):
                if isinstance(parent, ast.ClassDef) and node in getattr(parent, 'body', []):
                    parent_class = parent.name
                    break
            
            if parent_class:
                # Add to class methods
                class_entry = next((c for c in type_hints['classes'] if c['name'] == parent_class), None)
                if not class_entry:
                    class_entry = {'name': parent_class, 'methods': []}
                    type_hints['classes'].append(class_entry)
                class_entry['methods'].append(func_types)
            else:
                # Add to top-level functions
                type_hints['functions'].append(func_types)
        
        elif isinstance(node, ast.ClassDef):
            # Ensure class exists in our list
            if not any(c['name'] == node.name for c in type_hints['classes']):
                type_hints['classes'].append({'name': node.name, 'methods': []})
    
    return type_hints 