"""
AST parsing resilience tests

Tests for handling syntax errors, malformed code, and ensuring analysis continues
when individual files fail to parse.
"""

from redis_test_mcp_tools.tools.test_tools import analyze_test_files
from redis_test_mcp_tools.tools.ast_tools import parse_module_ast
import sys
from pathlib import Path
from unittest.mock import patch


# Add the parent directory to the path to import modules
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestASTResilience:
    """Test AST parsing resilience and error recovery"""

    def test_syntax_error_resilience(self, temp_project_dir):
        """Test that analysis continues when files have syntax errors"""
        # Create valid test file
        valid_file = temp_project_dir / "tests" / "test_valid.py"
        valid_file.parent.mkdir(parents=True, exist_ok=True)
        valid_file.write_text(
            """
import pytest

def test_valid_function():
    assert True

class TestValidClass:
    def test_method(self):
        assert 1 == 1
"""
        )

        # Create files with various syntax errors
        syntax_error_files = [
            (
                "test_missing_colon.py",
                """
def test_function()  # Missing colon
    assert True
""",
            ),
            (
                "test_unclosed_paren.py",
                """
def test_function(
    assert True
""",
            ),
            (
                "test_invalid_indent.py",
                """
def test_function():
assert True  # Wrong indentation
""",
            ),
            (
                "test_unclosed_string.py",
                """
def test_function():
    assert "unclosed string
""",
            ),
            (
                "test_invalid_syntax.py",
                """
def test_function():
    if True
        assert True  # Missing colon after if
""",
            ),
            (
                "test_mixed_tabs_spaces.py",
                """
def test_function():
\tassert True  # Tab
    assert False  # Spaces (mixing tabs and spaces)
""",
            ),
        ]

        # Create syntax error files
        for filename, content in syntax_error_files:
            error_file = temp_project_dir / "tests" / filename
            error_file.write_text(content)

        with patch("redis_test_mcp_tools.config.config.project_root", temp_project_dir):
            # Analysis should continue despite syntax errors
            result = analyze_test_files("tests")

            # Should not crash and should return results
            assert isinstance(
                result, dict
            ), "Should return results despite syntax errors"
            assert (
                "error" not in result
            ), "Should not fail entirely due to syntax errors"

            # Should find the valid functions from the valid file
            assert "test_functions" in result
            valid_functions = [
                f
                for f in result["test_functions"]
                if f["file_path"].endswith("test_valid.py")
            ]
            assert len(valid_functions) > 0, "Should find functions from valid files"

            # Should report some parsing errors but continue
            if "parsing_errors" in result:
                assert len(result["parsing_errors"]) > 0, "Should report parsing errors"

    def test_ast_parsing_individual_failures(self, temp_project_dir):
        """Test individual AST parsing failures"""
        # Test files that should fail to parse
        invalid_files = [
            ("incomplete.py", "def func("),
            ("empty_broken.py", ""),  # Empty file should be handled
            ("only_comments.py", "# Just a comment\n# Another comment"),
            ("invalid_unicode.py", "def test():\n    # Invalid: \x00\x01\x02"),
        ]

        for filename, content in invalid_files:
            file_path = temp_project_dir / filename
            file_path.write_text(content)

            # Individual parsing should handle errors gracefully
            result = parse_module_ast(filename)
            assert isinstance(result, dict), f"Should return dict for {filename}"

            # Should either succeed or report error gracefully
            if "error" in result:
                assert isinstance(
                    result["error"], str
                ), f"Error should be string for {filename}"
            else:
                # If successful, should have expected structure
                assert "functions" in result and "classes" in result

    def test_complex_ast_structures(self, temp_project_dir):
        """Test parsing of complex but valid Python structures"""
        complex_file = temp_project_dir / "complex.py"
        complex_file.write_text(
            """
# Complex Python file with various structures
import asyncio
from typing import List, Dict, Optional, Union, Callable
from functools import wraps, lru_cache
from dataclasses import dataclass

@dataclass
class ComplexClass:
    '''A complex class with type hints'''
    name: str
    values: List[int]
    mapping: Dict[str, Union[int, str]]
    callback: Optional[Callable[[int], str]] = None

    def __post_init__(self):
        '''Post-init processing'''
        pass

    @property
    def computed_value(self) -> int:
        '''Complex property with type hint'''
        return sum(self.values) if self.values else 0

    @staticmethod
    def static_method(x: int, y: int = 5) -> int:
        '''Static method with defaults'''
        return x + y

    @classmethod
    def from_dict(cls, data: Dict[str, any]) -> 'ComplexClass':
        '''Class method returning self type'''
        return cls(**data)

def decorator_with_args(arg1: str, arg2: int = 10):
    '''Decorator factory'''
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        return wrapper
    return decorator

@decorator_with_args("test", 20)
@lru_cache(maxsize=128)
def complex_function(
    a: int,
    b: str = "default",
    *args: int,
    **kwargs: str
) -> Optional[Union[int, str]]:
    '''Function with complex signature'''
    if not args:
        return None
    return a + len(b)

async def async_function(items: List[str]) -> Dict[str, int]:
    '''Async function with type hints'''
    result = {}
    for item in items:
        await asyncio.sleep(0.01)
        result[item] = len(item)
    return result

class NestedClass:
    '''Class with nested structures'''

    class InnerClass:
        '''Nested class'''
        def inner_method(self):
            pass

    def method_with_nested_func(self):
        '''Method containing nested function'''
        def nested_function(x: int) -> int:
            return x * 2

        return nested_function(5)

# Complex comprehensions and generators
complex_comprehension = [
    {
        'key': f"item_{i}",
        'value': i ** 2,
        'processed': True
    }
    for i in range(10)
    if i % 2 == 0
]

generator_expression = (
    item.upper()
    for sublist in [['a', 'b'], ['c', 'd']]
    for item in sublist
    if len(item) == 1
)
"""
        )

        with patch("redis_test_mcp_tools.config.config.project_root", temp_project_dir):
            # Should parse complex structures without crashing
            result = parse_module_ast("complex.py")

            assert isinstance(result, dict), "Should handle complex structures"
            assert "error" not in result, "Should not error on valid complex code"
            assert "functions" in result and "classes" in result
            assert len(result["functions"]) > 0, "Should find functions"
            assert len(result["classes"]) > 0, "Should find classes"

            # Should handle type annotations
            functions_with_types = [
                f for f in result["functions"] if f.get("return_type")
            ]
            assert (
                len(functions_with_types) > 0
            ), "Should extract return type annotations"

    def test_import_analysis_failures(self, temp_project_dir):
        """Test that import analysis failures don't crash the system"""
        # Create files with problematic imports
        import_files = [
            ("circular_a.py", "from circular_b import something\ndef test_a(): pass"),
            ("circular_b.py", "from circular_a import something\ndef test_b(): pass"),
            (
                "missing_import.py",
                "from nonexistent_module import nothing\ndef test(): pass",
            ),
            ("relative_import.py", "from . import something\ndef test(): pass"),
            (
                "complex_import.py",
                """
try:
    import optional_dependency
except ImportError:
    optional_dependency = None

def test_with_optional():
    if optional_dependency:
        return optional_dependency.function()
    return None
""",
            ),
        ]

        for filename, content in import_files:
            file_path = temp_project_dir / filename
            file_path.write_text(content)

        with patch("redis_test_mcp_tools.config.config.project_root", temp_project_dir):
            # Import analysis should not crash on problematic imports
            for filename, _ in import_files:
                result = parse_module_ast(filename)
                assert isinstance(result, dict), f"Should handle imports in {filename}"

                # Should find imports even if they're problematic
                if "imports" in result:
                    assert isinstance(result["imports"], list)

    def test_encoding_edge_cases(self, temp_project_dir):
        """Test AST parsing with various encoding edge cases"""
        # File with unicode in comments and strings
        unicode_file = temp_project_dir / "unicode_test.py"
        unicode_file.write_text(
            """# -*- coding: utf-8 -*-
'''
Module with unicode characters: café, résumé, 测试, русский
'''

def test_unicode_strings():
    '''Test with unicode: 🚀 rocket'''
    chinese = "测试"
    russian = "тест"
    emoji = "🚀🎉"
    assert len(chinese) == 2
    return f"Hello {emoji}"

class Café:
    '''Class with unicode name - should work'''
    def résumé_method(self):
        pass
""",
            encoding="utf-8",
        )

        with patch("redis_test_mcp_tools.config.config.project_root", temp_project_dir):
            result = parse_module_ast("unicode_test.py")
            assert isinstance(result, dict), "Should handle unicode content"

            if "error" not in result:
                assert len(result["functions"]) > 0, "Should find unicode function"
                assert len(result["classes"]) > 0, "Should find unicode class"

    def test_very_large_ast(self, temp_project_dir):
        """Test handling of very large AST structures"""
        # Generate a large file with many functions
        large_content = ['"""Large test file with many functions"""']

        for i in range(100):  # Generate 100 functions
            large_content.append(
                f"""
def test_function_{i:03d}():
    '''Test function number {i}'''
    assert {i} >= 0
    for j in range({i % 10 + 1}):
        if j == {i % 3}:
            continue
        assert j != {i}
    return {i}
"""
            )

        large_file = temp_project_dir / "large_test.py"
        large_file.write_text("\n".join(large_content))

        with patch("redis_test_mcp_tools.config.config.project_root", temp_project_dir):
            # Should handle large files without excessive memory usage
            result = parse_module_ast("large_test.py")
            assert isinstance(result, dict), "Should handle large files"

            if "error" not in result:
                assert len(result["functions"]) == 100, "Should find all functions"

                # Check that function details are preserved
                for func in result["functions"]:
                    assert "name" in func
                    assert "line_number" in func
                    assert func["name"].startswith("test_function_")


class TestErrorRecovery:
    """Test error recovery and graceful degradation"""

    def test_partial_file_analysis(self, temp_project_dir):
        """Test that partial analysis succeeds when some files fail"""
        # Create mix of valid and invalid files
        files = [
            ("valid1.py", "def test_one(): pass"),
            ("invalid.py", "def broken("),  # Syntax error
            ("valid2.py", "def test_two(): pass"),
            ("empty.py", ""),  # Empty file
            ("valid3.py", "class TestClass:\n    def test_method(self): pass"),
        ]

        test_dir = temp_project_dir / "tests"
        test_dir.mkdir(parents=True, exist_ok=True)

        for filename, content in files:
            (test_dir / filename).write_text(content)

        with patch("redis_test_mcp_tools.config.config.project_root", temp_project_dir):
            result = analyze_test_files("tests")

            # Should succeed overall despite individual failures
            assert isinstance(result, dict), "Should return results"
            assert "total_test_files" in result

            # Should find valid functions from good files
            if "test_functions" in result:
                valid_functions = [f for f in result["test_functions"]]
                assert (
                    len(valid_functions) >= 2
                ), "Should find functions from valid files"

    def test_memory_efficient_parsing(self, temp_project_dir):
        """Test that parsing doesn't consume excessive memory"""
        # Create file with deeply nested structures
        nested_content = """
def test_deeply_nested():
    '''Test with deep nesting'''
"""

        # Add 20 levels of nesting
        indent = "    "
        for i in range(20):
            nested_content += f"{indent * (i + 2)}if True:\n"
        nested_content += f"{indent * 22}assert True\n"

        nested_file = temp_project_dir / "nested.py"
        nested_file.write_text(nested_content)

        with patch("redis_test_mcp_tools.config.config.project_root", temp_project_dir):
            # Should parse without running out of memory or stack overflow
            result = parse_module_ast("nested.py")
            assert isinstance(result, dict), "Should handle deeply nested structures"
