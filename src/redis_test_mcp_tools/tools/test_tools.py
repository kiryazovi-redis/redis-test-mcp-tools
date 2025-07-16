"""
Test analysis tools for Redis Test MCP Tools.

This module provides functions for analyzing test files, finding test patterns,
identifying untested code, suggesting test cases, and parsing coverage information.
"""

import ast
import sys
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

# Import configuration and other tools
from ..config import config
from .file_tools import find_test_files, get_relative_path, is_ignored_path
from .ast_tools import get_ast_from_file, extract_class_info, extract_function_info, find_imports_in_file, parse_module_ast


def _detect_framework_context(file_path: str, node: ast.FunctionDef, func_info: Dict[str, Any], file_imports: List[Dict[str, Any]]) -> str:
    """Intelligently detect the testing framework for a test function."""
    
    # Check if function is inside a unittest.TestCase class
    # We need to find the parent class in the AST
    current_file_tree = get_ast_from_file(file_path)
    if not isinstance(current_file_tree, dict):  # No error
        for class_node in ast.walk(current_file_tree):
            if isinstance(class_node, ast.ClassDef):
                # Check if this function is a method of this class
                for method_node in class_node.body:
                    if (isinstance(method_node, (ast.FunctionDef, ast.AsyncFunctionDef)) and 
                        method_node.name == node.name and method_node.lineno == node.lineno):
                        
                        # Check if class inherits from unittest.TestCase
                        is_unittest_class = False
                        for base in class_node.bases:
                            base_name = ast.unparse(base) if hasattr(ast, 'unparse') else str(base)
                            if 'TestCase' in base_name or 'unittest' in base_name:
                                is_unittest_class = True
                                break
                        
                        if is_unittest_class:
                            return 'unittest'
                        else:
                            # This is a class method but not unittest.TestCase
                            # Check if it's a pytest-style test class
                            if class_node.name.startswith('Test'):
                                # Likely pytest test class, check imports to confirm
                                pytest_imports = any('pytest' in imp.get('module', '').lower() 
                                                   for imp in file_imports)
                                if pytest_imports:
                                    return 'pytest'
                            break
    
    # Check file imports for framework indicators
    pytest_indicators = 0
    unittest_indicators = 0
    
    for import_info in file_imports:
        module = import_info.get('module', '').lower()
        name = import_info.get('name', '').lower()
        
        if 'pytest' in module or 'pytest' in name:
            pytest_indicators += 1
        elif 'unittest' in module or 'unittest' in name:
            unittest_indicators += 1
        elif module == 'mock' or name == 'mock':
            # Mock can be used with both, but unittest.mock is more common in unittest
            if 'unittest' in module:
                unittest_indicators += 1
    
    # Check decorators for pytest-specific patterns
    for decorator in func_info['decorators']:
        if any(pattern in decorator.lower() for pattern in ['pytest.', 'parametrize', 'fixture', 'mark.']):
            return 'pytest'
        elif any(pattern in decorator.lower() for pattern in ['unittest.', 'mock.patch']):
            unittest_indicators += 1
    
    # Check function parameters for pytest fixture patterns
    for param in func_info['parameters']:
        param_name = param['name']
        # Common pytest fixture names
        if param_name in ['request', 'tmp_path', 'tmpdir', 'capfd', 'capsys', 'monkeypatch']:
            return 'pytest'
        # unittest-style self parameter
        elif param_name == 'self' and func_info['parameters'][0]['name'] == 'self':
            return 'unittest'
    
    # Check function name patterns
    func_name = node.name
    if func_name in ['setUp', 'tearDown', 'setUpClass', 'tearDownClass']:
        return 'unittest'
    elif func_name.startswith('test_') and len(func_info['parameters']) > 1:
        # pytest tests often have fixture parameters
        return 'pytest'
    
    # Use import indicators to determine default
    if pytest_indicators > unittest_indicators:
        return 'pytest'
    elif unittest_indicators > pytest_indicators:
        return 'unittest'
    
    # If still unclear, default to pytest (modern preference)
    return 'pytest'


def analyze_test_files(directory: Optional[str] = None) -> Dict[str, Any]:
    """Analyze test files and extract test structure including unittest and pytest patterns."""
    if directory:
        search_dir = config.project_root / directory
        if not search_dir.exists():
            return {'error': f'Directory not found: {directory}'}
    else:
        search_dir = None
    
    test_files = find_test_files(search_dir)
    
    analysis = {
        'total_test_files': len(test_files),
        'test_files': [],
        'test_classes': [],
        'test_functions': [],
        'fixtures': [],
        'markers': [],
        'imports': [],
        'unittest_classes': [],
        'pytest_fixtures': [],
        'setup_teardown_methods': [],
        'assertion_patterns': [],
        'mock_usage': []
    }
    
    for test_file in test_files:
        file_path = test_file['path']
        tree = get_ast_from_file(file_path)
        
        if isinstance(tree, dict):  # Error occurred
            continue
        
        file_analysis = {
            'file_path': file_path,
            'classes': [],
            'functions': [],
            'fixtures': [],
            'markers': [],
            'unittest_classes': [],
            'setup_teardown_methods': [],
            'assertion_patterns': [],
            'mock_usage': []
        }
        
        # Get file imports early for framework detection
        file_imports_result = find_imports_in_file(file_path)
        file_imports = file_imports_result.get('imports', []) if 'imports' in file_imports_result else []
        
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                class_info = extract_class_info(node)
                file_analysis['classes'].append(class_info)
                
                # Check if it's a unittest TestCase
                is_unittest_class = any(
                    'TestCase' in base or 'unittest' in base 
                    for base in class_info['base_classes']
                )
                
                test_class_info = {
                    'name': node.name,
                    'file_path': file_path,
                    'line_number': node.lineno,
                    'methods': len(class_info['methods']),
                    'docstring': class_info['docstring'],
                    'framework': 'unittest' if is_unittest_class else 'pytest',
                    'base_classes': class_info['base_classes']
                }
                
                analysis['test_classes'].append(test_class_info)
                
                if is_unittest_class:
                    file_analysis['unittest_classes'].append(test_class_info)
                    analysis['unittest_classes'].append(test_class_info)
                
                # Analyze methods for setup/teardown patterns
                for method in class_info['methods']:
                    method_name = method['name']
                    if method_name in ['setUp', 'tearDown', 'setUpClass', 'tearDownClass', 
                                     'setUpModule', 'tearDownModule', 'setup_method', 'teardown_method',
                                     'setup_class', 'teardown_class']:
                        setup_teardown_info = {
                            'name': method_name,
                            'class_name': node.name,
                            'file_path': file_path,
                            'line_number': method.get('line_number', node.lineno),
                            'framework': 'unittest' if method_name in ['setUp', 'tearDown', 'setUpClass', 'tearDownClass'] else 'pytest',
                            'scope': 'class' if 'Class' in method_name or 'class' in method_name else 'method'
                        }
                        file_analysis['setup_teardown_methods'].append(setup_teardown_info)
                        analysis['setup_teardown_methods'].append(setup_teardown_info)
            
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_info = extract_function_info(node)
                file_analysis['functions'].append(func_info)
                
                # Check if it's a test function (pytest or unittest style)
                is_test_func = (node.name.startswith('test_') or 
                               any('test' in dec for dec in func_info['decorators']))
                
                # Check if it's a pytest fixture
                is_fixture = any('fixture' in dec for dec in func_info['decorators'])
                
                if is_fixture:
                    fixture_info = {
                        'name': node.name,
                        'file_path': file_path,
                        'line_number': node.lineno,
                        'scope': 'function',  # default
                        'params': func_info['parameters'],
                        'docstring': func_info['docstring'],
                        'autouse': False
                    }
                    
                    # Extract fixture scope and other parameters from decorators
                    for dec in func_info['decorators']:
                        if 'scope=' in dec:
                            scope_match = re.search(r'scope=[\'"](.*?)[\'"]', dec)
                            if scope_match:
                                fixture_info['scope'] = scope_match.group(1)
                        if 'autouse=' in dec:
                            autouse_match = re.search(r'autouse=(True|False)', dec)
                            if autouse_match:
                                fixture_info['autouse'] = autouse_match.group(1) == 'True'
                    
                    file_analysis['fixtures'].append(fixture_info)
                    analysis['fixtures'].append(fixture_info)
                    analysis['pytest_fixtures'].append(fixture_info)
                
                if is_test_func:
                    # Use intelligent framework detection
                    framework = _detect_framework_context(file_path, node, func_info, file_imports)
                    
                    test_func_info = {
                        'name': node.name,
                        'file_path': file_path,
                        'line_number': node.lineno,
                        'parameters': func_info['parameters'],
                        'docstring': func_info['docstring'],
                        'decorators': func_info['decorators'],
                        'framework': framework
                    }
                    analysis['test_functions'].append(test_func_info)
            
            # Extract pytest markers
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == 'mark':
                    marker_info = {
                        'name': getattr(node.func.value, 'id', 'unknown'),
                        'file_path': file_path,
                        'line_number': node.lineno
                    }
                    file_analysis['markers'].append(marker_info)
                    analysis['markers'].append(marker_info)
            
            # Extract assertion patterns
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr.startswith('assert') or node.func.attr in ['assertEqual', 'assertTrue', 'assertFalse', 'assertRaises']:
                    assertion_info = {
                        'method': node.func.attr,
                        'file_path': file_path,
                        'line_number': node.lineno,
                        'framework': 'unittest' if node.func.attr.startswith('assert') and len(node.func.attr) > 6 else 'pytest'
                    }
                    file_analysis['assertion_patterns'].append(assertion_info)
                    analysis['assertion_patterns'].append(assertion_info)
            
            # Extract mock usage patterns
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute) and 'mock' in node.func.attr.lower():
                    mock_info = {
                        'method': node.func.attr,
                        'file_path': file_path,
                        'line_number': node.lineno
                    }
                    file_analysis['mock_usage'].append(mock_info)
                    analysis['mock_usage'].append(mock_info)
                elif isinstance(node.func, ast.Name) and 'Mock' in node.func.id:
                    mock_info = {
                        'method': node.func.id,
                        'file_path': file_path,
                        'line_number': node.lineno
                    }
                    file_analysis['mock_usage'].append(mock_info)
                    analysis['mock_usage'].append(mock_info)
        
        # Extract imports
        imports = find_imports_in_file(file_path)
        if 'imports' in imports:
            file_analysis['imports'] = imports['imports']
            analysis['imports'].extend(imports['imports'])
        
        analysis['test_files'].append(file_analysis)
    
    return analysis


def get_test_patterns(directory: Optional[str] = None) -> Dict[str, Any]:
    """Identify common testing patterns used in the project (pytest, unittest, mocking, etc.)."""
    analysis = analyze_test_files(directory)
    
    if 'error' in analysis:
        return analysis
    
    patterns = {
        'testing_frameworks': set(),
        'framework_usage': {
            'pytest': 0,
            'unittest': 0,
            'mixed': 0
        },
        'common_fixtures': {},
        'common_markers': {},
        'mocking_patterns': [],
        'assertion_patterns': {},
        'setup_patterns': [],
        'parametrization_patterns': [],
        'unittest_patterns': {
            'test_case_classes': len(analysis.get('unittest_classes', [])),
            'setup_teardown_methods': []
        },
        'pytest_patterns': {
            'fixtures': len(analysis.get('pytest_fixtures', [])),
            'markers': len(analysis.get('markers', [])),
            'parametrized_tests': 0
        }
    }
    
    # Analyze imports to detect testing frameworks
    for import_info in analysis['imports']:
        module = import_info.get('module', '')
        if module in ['pytest', 'unittest', 'nose', 'nose2']:
            patterns['testing_frameworks'].add(module)
        elif module.startswith('pytest'):
            patterns['testing_frameworks'].add('pytest')
        elif module.startswith('unittest'):
            patterns['testing_frameworks'].add('unittest')
        elif 'mock' in module.lower():
            patterns['mocking_patterns'].append(import_info)
    
    # Count framework usage
    for test_func in analysis['test_functions']:
        framework = test_func.get('framework', 'unknown')
        if framework == 'pytest':
            patterns['framework_usage']['pytest'] += 1
        elif framework == 'unittest':
            patterns['framework_usage']['unittest'] += 1
    
    # Analyze fixtures
    for fixture in analysis['fixtures']:
        fixture_name = fixture['name']
        if fixture_name not in patterns['common_fixtures']:
            patterns['common_fixtures'][fixture_name] = []
        patterns['common_fixtures'][fixture_name].append(fixture)
    
    # Analyze markers
    for marker in analysis['markers']:
        marker_name = marker['name']
        if marker_name not in patterns['common_markers']:
            patterns['common_markers'][marker_name] = 0
        patterns['common_markers'][marker_name] += 1
    
    # Analyze assertion patterns
    assertion_counts = {}
    for assertion in analysis.get('assertion_patterns', []):
        method = assertion['method']
        framework = assertion['framework']
        key = f"{framework}:{method}"
        assertion_counts[key] = assertion_counts.get(key, 0) + 1
    patterns['assertion_patterns'] = assertion_counts
    
    # Analyze setup/teardown patterns
    for setup_teardown in analysis.get('setup_teardown_methods', []):
        patterns['setup_patterns'].append({
            'method': setup_teardown['name'],
            'class_name': setup_teardown.get('class_name', ''),
            'file_path': setup_teardown['file_path'],
            'framework': setup_teardown['framework'],
            'scope': setup_teardown['scope']
        })
        
        if setup_teardown['framework'] == 'unittest':
            patterns['unittest_patterns']['setup_teardown_methods'].append(setup_teardown)
    
    # Analyze test functions for patterns
    for test_func in analysis['test_functions']:
        decorators = test_func.get('decorators', [])
        
        # Check for parametrization
        for decorator in decorators:
            if 'parametrize' in decorator:
                patterns['parametrization_patterns'].append({
                    'function': test_func['name'],
                    'file_path': test_func['file_path'],
                    'decorator': decorator
                })
                patterns['pytest_patterns']['parametrized_tests'] += 1
        
        # Check for setup patterns (function-level)
        if test_func['name'].startswith('setup_') or test_func['name'].startswith('teardown_'):
            patterns['setup_patterns'].append({
                'function': test_func['name'],
                'file_path': test_func['file_path'],
                'type': 'setup' if test_func['name'].startswith('setup_') else 'teardown',
                'framework': 'pytest',
                'scope': 'function'
            })
    
    # Analyze mock usage
    mock_counts = {}
    for mock_usage in analysis.get('mock_usage', []):
        method = mock_usage['method']
        mock_counts[method] = mock_counts.get(method, 0) + 1
    patterns['mock_usage_summary'] = mock_counts
    
    # Determine if project uses mixed frameworks
    frameworks_used = len(patterns['testing_frameworks'])
    pytest_usage = patterns['framework_usage']['pytest']
    unittest_usage = patterns['framework_usage']['unittest']
    
    if frameworks_used > 1 or (pytest_usage > 0 and unittest_usage > 0):
        patterns['framework_usage']['mixed'] = 1
    
    # Convert sets to lists for JSON serialization
    patterns['testing_frameworks'] = list(patterns['testing_frameworks'])
    
    return patterns


def find_untested_code(source_dir: Optional[str] = None, test_dir: Optional[str] = None) -> Dict[str, Any]:
    """Compare source files with test files to find untested functions/classes."""
    if source_dir:
        source_path = config.project_root / source_dir
        if not source_path.exists():
            return {'error': f'Source directory not found: {source_dir}'}
    else:
        source_path = config.project_root
    
    if test_dir:
        test_path = config.project_root / test_dir
        if not test_path.exists():
            return {'error': f'Test directory not found: {test_dir}'}
    else:
        test_path = config.project_root / 'tests'
    
    # Find all source files (excluding test files)
    source_files = []
    for path in source_path.rglob('*.py'):
        if path.is_file() and not is_ignored_path(path):
            rel_path = get_relative_path(path)
            # Skip test files
            if not ('test' in rel_path or rel_path.startswith('tests/')):
                source_files.append(rel_path)
    
    # Analyze test files
    test_analysis = analyze_test_files(str(test_path.relative_to(config.project_root)))
    if 'error' in test_analysis:
        return test_analysis
    
    # Extract tested code references from test files
    tested_references = set()
    for test_file in test_analysis['test_files']:
        for import_info in test_file.get('imports', []):
            if import_info['type'] == 'from_import':
                tested_references.add(f"{import_info['module']}.{import_info['name']}")
            elif import_info['type'] == 'import':
                tested_references.add(import_info['module'])
    
    # Analyze source files
    untested_items = {
        'untested_functions': [],
        'untested_classes': [],
        'untested_files': [],
        'analysis_summary': {
            'total_source_files': len(source_files),
            'total_test_files': test_analysis['total_test_files'],
            'tested_references': len(tested_references)
        }
    }
    
    for source_file in source_files:
        module_info = parse_module_ast(source_file)
        if 'error' in module_info:
            continue
        
        # Check if file has any tests
        module_name = source_file.replace('/', '.').replace('.py', '')
        has_tests = any(module_name in ref for ref in tested_references)
        
        if not has_tests:
            untested_items['untested_files'].append({
                'file_path': source_file,
                'functions': len(module_info['functions']),
                'classes': len(module_info['classes'])
            })
        
        # Check functions
        for func in module_info['functions']:
            func_ref = f"{module_name}.{func['name']}"
            if func_ref not in tested_references and not func['name'].startswith('_'):
                untested_items['untested_functions'].append({
                    'name': func['name'],
                    'file_path': source_file,
                    'line_number': func['line_number'],
                    'docstring': func['docstring'],
                    'parameters': func['parameters']
                })
        
        # Check classes
        for cls in module_info['classes']:
            cls_ref = f"{module_name}.{cls['name']}"
            if cls_ref not in tested_references and not cls['name'].startswith('_'):
                untested_items['untested_classes'].append({
                    'name': cls['name'],
                    'file_path': source_file,
                    'line_number': cls['line_number'],
                    'docstring': cls['docstring'],
                    'methods': len(cls['methods']),
                    'public_methods': len([m for m in cls['methods'] if not m['name'].startswith('_')])
                })
    
    return untested_items


def suggest_test_cases(file_path: str, function_name: Optional[str] = None, class_name: Optional[str] = None, 
                      framework: Optional[str] = None) -> Dict[str, Any]:
    """Suggest test cases based on function signatures and docstrings for both pytest and unittest frameworks."""
    module_info = parse_module_ast(file_path)
    if 'error' in module_info:
        return module_info
    
    # Detect likely testing framework if not specified
    if framework is None:
        # Check for existing test patterns in the project
        test_patterns = get_test_patterns()
        frameworks = test_patterns.get('testing_frameworks', [])
        
        if 'pytest' in frameworks:
            framework = 'pytest'
        elif 'unittest' in frameworks:
            framework = 'unittest'
        else:
            framework = 'pytest'  # Default to pytest
    
    suggestions = {
        'file_path': file_path,
        'framework': framework,
        'recommended_framework': framework,
        'test_suggestions': []
    }
    
    def generate_function_tests(func_info: Dict[str, Any], framework: str) -> List[Dict[str, Any]]:
        """Generate test suggestions for a function based on the testing framework."""
        test_cases = []
        
        # Basic test case
        test_cases.append({
            'test_name': f"test_{func_info['name']}_basic",
            'description': f"Test basic functionality of {func_info['name']}",
            'test_type': 'positive',
            'priority': 'high',
            'framework': framework,
            'suggested_assertions': _get_suggested_assertions(func_info, framework)
        })
        
        # Parameter-based tests
        for param in func_info['parameters']:
            if param['kind'] == 'positional':
                # None/null test
                test_cases.append({
                    'test_name': f"test_{func_info['name']}_with_none_{param['name']}",
                    'description': f"Test {func_info['name']} with None value for {param['name']}",
                    'test_type': 'negative',
                    'priority': 'medium',
                    'framework': framework,
                    'suggested_assertions': ['raises exception' if framework == 'pytest' else 'assertRaises']
                })
                
                # Type-based tests
                if param['type']:
                    if 'str' in param['type']:
                        test_cases.append({
                            'test_name': f"test_{func_info['name']}_with_empty_string_{param['name']}",
                            'description': f"Test {func_info['name']} with empty string for {param['name']}",
                            'test_type': 'edge_case',
                            'priority': 'medium',
                            'framework': framework,
                            'suggested_assertions': _get_suggested_assertions(func_info, framework)
                        })
                    elif 'int' in param['type']:
                        test_cases.append({
                            'test_name': f"test_{func_info['name']}_with_zero_{param['name']}",
                            'description': f"Test {func_info['name']} with zero value for {param['name']}",
                            'test_type': 'edge_case',
                            'priority': 'medium',
                            'framework': framework,
                            'suggested_assertions': _get_suggested_assertions(func_info, framework)
                        })
                        test_cases.append({
                            'test_name': f"test_{func_info['name']}_with_negative_{param['name']}",
                            'description': f"Test {func_info['name']} with negative value for {param['name']}",
                            'test_type': 'edge_case',
                            'priority': 'medium',
                            'framework': framework,
                            'suggested_assertions': _get_suggested_assertions(func_info, framework)
                        })
                    elif 'list' in param['type']:
                        test_cases.append({
                            'test_name': f"test_{func_info['name']}_with_empty_list_{param['name']}",
                            'description': f"Test {func_info['name']} with empty list for {param['name']}",
                            'test_type': 'edge_case',
                            'priority': 'medium',
                            'framework': framework,
                            'suggested_assertions': _get_suggested_assertions(func_info, framework)
                        })
                    elif 'dict' in param['type']:
                        test_cases.append({
                            'test_name': f"test_{func_info['name']}_with_empty_dict_{param['name']}",
                            'description': f"Test {func_info['name']} with empty dict for {param['name']}",
                            'test_type': 'edge_case',
                            'priority': 'medium',
                            'framework': framework,
                            'suggested_assertions': _get_suggested_assertions(func_info, framework)
                        })
        
        # Return type-based tests
        if func_info['return_type']:
            test_cases.append({
                'test_name': f"test_{func_info['name']}_return_type",
                'description': f"Test that {func_info['name']} returns correct type: {func_info['return_type']}",
                'test_type': 'type_check',
                'priority': 'low',
                'framework': framework,
                'suggested_assertions': ['assert isinstance' if framework == 'pytest' else 'assertIsInstance']
            })
        
        # Docstring-based tests
        if func_info['docstring']:
            docstring = func_info['docstring'].lower()
            if 'raise' in docstring or 'exception' in docstring:
                test_cases.append({
                    'test_name': f"test_{func_info['name']}_raises_exception",
                    'description': f"Test that {func_info['name']} raises appropriate exceptions",
                    'test_type': 'exception',
                    'priority': 'high',
                    'framework': framework,
                    'suggested_assertions': ['pytest.raises' if framework == 'pytest' else 'assertRaises']
                })
            
            if 'async' in docstring or func_info['type'] == 'async_function':
                test_cases.append({
                    'test_name': f"test_{func_info['name']}_async",
                    'description': f"Test async behavior of {func_info['name']}",
                    'test_type': 'async',
                    'priority': 'high',
                    'framework': framework,
                    'suggested_assertions': ['await' if framework == 'pytest' else 'asyncio.run']
                })
        
        return test_cases
    
    def _get_suggested_assertions(func_info: Dict[str, Any], framework: str) -> List[str]:
        """Get suggested assertion methods based on the function and framework."""
        assertions = []
        
        if framework == 'pytest':
            assertions.extend(['assert', 'assert ==', 'assert !=', 'assert is', 'assert is not'])
        else:  # unittest
            assertions.extend(['assertEqual', 'assertNotEqual', 'assertTrue', 'assertFalse', 'assertIs', 'assertIsNot'])
        
        return assertions
    
    # Generate suggestions for specific function
    if function_name:
        for func in module_info['functions']:
            if func['name'] == function_name:
                suggestions['test_suggestions'].extend(generate_function_tests(func, framework))
                break
        else:
            return {'error': f'Function "{function_name}" not found in {file_path}'}
    
    # Generate suggestions for specific class
    elif class_name:
        for cls in module_info['classes']:
            if cls['name'] == class_name:
                # Class-level tests
                test_class_suggestion = {
                    'test_name': f"test_{cls['name']}_instantiation",
                    'description': f"Test that {cls['name']} can be instantiated",
                    'test_type': 'instantiation',
                    'priority': 'high',
                    'framework': framework,
                    'suggested_assertions': _get_suggested_assertions({'name': cls['name'], 'return_type': None}, framework)
                }
                
                # Add unittest-specific test class suggestion if needed
                if framework == 'unittest':
                    test_class_suggestion['test_class_name'] = f"Test{cls['name']}"
                    test_class_suggestion['inherits_from'] = 'unittest.TestCase'
                    test_class_suggestion['setup_methods'] = ['setUp', 'tearDown']
                
                suggestions['test_suggestions'].append(test_class_suggestion)
                
                # Method tests
                for method in cls['methods']:
                    if not method['name'].startswith('_') or method['name'] == '__init__':
                        suggestions['test_suggestions'].extend(generate_function_tests(method, framework))
                break
        else:
            return {'error': f'Class "{class_name}" not found in {file_path}'}
    
    # Generate suggestions for all functions and classes
    else:
        for func in module_info['functions']:
            if not func['name'].startswith('_'):
                suggestions['test_suggestions'].extend(generate_function_tests(func, framework))
        
        for cls in module_info['classes']:
            if not cls['name'].startswith('_'):
                test_class_suggestion = {
                    'test_name': f"test_{cls['name']}_instantiation",
                    'description': f"Test that {cls['name']} can be instantiated",
                    'test_type': 'instantiation',
                    'priority': 'high',
                    'framework': framework,
                    'suggested_assertions': _get_suggested_assertions({'name': cls['name'], 'return_type': None}, framework)
                }
                
                # Add unittest-specific test class suggestion if needed
                if framework == 'unittest':
                    test_class_suggestion['test_class_name'] = f"Test{cls['name']}"
                    test_class_suggestion['inherits_from'] = 'unittest.TestCase'
                    test_class_suggestion['setup_methods'] = ['setUp', 'tearDown']
                
                suggestions['test_suggestions'].append(test_class_suggestion)
                
                for method in cls['methods']:
                    if not method['name'].startswith('_') or method['name'] == '__init__':
                        suggestions['test_suggestions'].extend(generate_function_tests(method, framework))
    
    return suggestions


def get_test_coverage_info(coverage_file: Optional[str] = None) -> Dict[str, Any]:
    """Parse and show coverage information from pytest-cov data."""
    if coverage_file is None:
        # Try common coverage file locations
        coverage_files = ['.coverage', 'coverage.xml', 'htmlcov/index.html']
        for cf in coverage_files:
            coverage_path = config.project_root / cf
            if coverage_path.exists():
                coverage_file = cf
                break
    
    if coverage_file is None:
        return {'error': 'No coverage file found. Run tests with coverage first: pytest --cov=your_package --cov-report=xml'}
    
    coverage_path = config.project_root / coverage_file
    if not coverage_path.exists():
        return {'error': f'Coverage file not found: {coverage_file}'}
    
    coverage_info = {
        'coverage_file': coverage_file,
        'coverage_data': {},
        'summary': {},
        'uncovered_lines': [],
        'coverage_gaps': []
    }
    
    try:
        if coverage_file.endswith('.xml'):
            # Parse XML coverage report
            import xml.etree.ElementTree as ET
            tree = ET.parse(coverage_path)
            root = tree.getroot()
            
            total_lines = 0
            covered_lines = 0
            
            for package in root.findall('.//package'):
                for class_elem in package.findall('.//class'):
                    filename = class_elem.get('filename', '')
                    if filename:
                        rel_path = get_relative_path(Path(filename))
                        
                        file_coverage = {
                            'filename': rel_path,
                            'lines': [],
                            'covered': [],
                            'missed': []
                        }
                        
                        for line in class_elem.findall('.//line'):
                            line_num = int(line.get('number', 0))
                            hits = int(line.get('hits', 0))
                            
                            file_coverage['lines'].append(line_num)
                            if hits > 0:
                                file_coverage['covered'].append(line_num)
                                covered_lines += 1
                            else:
                                file_coverage['missed'].append(line_num)
                            
                            total_lines += 1
                        
                        coverage_info['coverage_data'][rel_path] = file_coverage
                        
                        if file_coverage['missed']:
                            coverage_info['coverage_gaps'].append({
                                'file': rel_path,
                                'uncovered_lines': file_coverage['missed'],
                                'coverage_percentage': (len(file_coverage['covered']) / len(file_coverage['lines'])) * 100 if file_coverage['lines'] else 0
                            })
            
            coverage_info['summary'] = {
                'total_lines': total_lines,
                'covered_lines': covered_lines,
                'coverage_percentage': (covered_lines / total_lines) * 100 if total_lines > 0 else 0
            }
        
        elif coverage_file == '.coverage':
            # Try to use coverage library to read binary coverage file
            try:
                import coverage
                cov = coverage.Coverage(data_file=str(coverage_path))
                cov.load()
                
                files = cov.get_data().measured_files()
                total_lines = 0
                covered_lines = 0
                
                for file_path in files:
                    try:
                        rel_path = get_relative_path(Path(file_path))
                        analysis = cov.analysis2(file_path)
                        
                        if analysis:
                            statements = analysis[1]
                            missing = analysis[3]
                            covered = [line for line in statements if line not in missing]
                            
                            coverage_info['coverage_data'][rel_path] = {
                                'filename': rel_path,
                                'lines': list(statements),
                                'covered': covered,
                                'missed': list(missing)
                            }
                            
                            total_lines += len(statements)
                            covered_lines += len(covered)
                            
                            if missing:
                                coverage_info['coverage_gaps'].append({
                                    'file': rel_path,
                                    'uncovered_lines': list(missing),
                                    'coverage_percentage': (len(covered) / len(statements)) * 100 if statements else 0
                                })
                    except Exception as e:
                        print(f"Error analyzing {file_path}: {e}", file=sys.stderr)
                
                coverage_info['summary'] = {
                    'total_lines': total_lines,
                    'covered_lines': covered_lines,
                    'coverage_percentage': (covered_lines / total_lines) * 100 if total_lines > 0 else 0
                }
                
            except ImportError:
                return {'error': 'coverage library not available. Install with: pip install coverage'}
        
        else:
            return {'error': f'Unsupported coverage file format: {coverage_file}'}
    
    except Exception as e:
        return {'error': f'Error parsing coverage file: {str(e)}'}
    
    return coverage_info 