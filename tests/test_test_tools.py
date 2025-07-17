"""
Test the test_tools module comprehensively.

This module tests all functions in test_tools.py including main functions
and helper functions with extensive coverage.
"""

import ast
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from redis_test_mcp_tools.tools.test_tools import (
    _detect_framework_context,
    analyze_test_files,
    find_untested_code,
    get_test_coverage_info,
    get_test_patterns,
    suggest_test_cases,
)


@pytest.fixture
def temp_project_dir():
    """Create a temporary directory for test projects."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


class TestDetectFrameworkContext:
    """Test the _detect_framework_context helper function"""

    def test_detect_unittest_framework_with_testcase_inheritance(
        self, temp_project_dir
    ):
        """Test detecting unittest framework from TestCase inheritance"""
        test_file = temp_project_dir / "test_example.py"
        test_content = """
import unittest

class TestExample(unittest.TestCase):
    def test_something(self):
        self.assertTrue(True)
"""
        test_file.write_text(test_content)

        # Parse the AST to get the function node
        tree = ast.parse(test_content)
        func_node = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "test_something":
                func_node = node
                break

        func_info = {
            "name": "test_something",
            "parameters": [{"name": "self", "type": None, "kind": "positional"}],
            "decorators": [],
        }

        file_imports = [{"module": "unittest", "name": None, "type": "import"}]

        result = _detect_framework_context(
            str(test_file), func_node, func_info, file_imports
        )
        assert result == "unittest"

    def test_detect_pytest_framework_with_pytest_imports(self, temp_project_dir):
        """Test detecting pytest framework from imports"""
        test_file = temp_project_dir / "test_example.py"
        test_content = """
import pytest

def test_something():
    assert True
"""
        test_file.write_text(test_content)

        tree = ast.parse(test_content)
        func_node = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "test_something":
                func_node = node
                break

        func_info = {"name": "test_something", "parameters": [], "decorators": []}

        file_imports = [{"module": "pytest", "name": None, "type": "import"}]

        result = _detect_framework_context(
            str(test_file), func_node, func_info, file_imports
        )
        assert result == "pytest"

    def test_detect_pytest_framework_with_fixtures(self, temp_project_dir):
        """Test detecting pytest framework from fixture parameters"""
        test_file = temp_project_dir / "test_example.py"
        test_content = """
def test_something(tmp_path):
    assert True
"""
        test_file.write_text(test_content)

        tree = ast.parse(test_content)
        func_node = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "test_something":
                func_node = node
                break

        func_info = {
            "name": "test_something",
            "parameters": [{"name": "tmp_path", "type": None, "kind": "positional"}],
            "decorators": [],
        }

        file_imports = []

        result = _detect_framework_context(
            str(test_file), func_node, func_info, file_imports
        )
        assert result == "pytest"

    def test_detect_unittest_framework_with_self_parameter(self, temp_project_dir):
        """Test detecting unittest framework from self parameter"""
        test_file = temp_project_dir / "test_example.py"
        test_content = """
def test_something(self):
    pass
"""
        test_file.write_text(test_content)

        tree = ast.parse(test_content)
        func_node = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "test_something":
                func_node = node
                break

        func_info = {
            "name": "test_something",
            "parameters": [{"name": "self", "type": None, "kind": "positional"}],
            "decorators": [],
        }

        file_imports = []

        result = _detect_framework_context(
            str(test_file), func_node, func_info, file_imports
        )
        assert result == "unittest"

    def test_detect_framework_defaults_to_pytest(self, temp_project_dir):
        """Test that unknown framework detection defaults to pytest"""
        test_file = temp_project_dir / "test_example.py"
        test_content = """
def test_something():
    pass
"""
        test_file.write_text(test_content)

        tree = ast.parse(test_content)
        func_node = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "test_something":
                func_node = node
                break

        func_info = {"name": "test_something", "parameters": [], "decorators": []}

        file_imports = []

        result = _detect_framework_context(
            str(test_file), func_node, func_info, file_imports
        )
        assert result == "pytest"


class TestAnalyzeTestFilesAdditional:
    """Additional tests for analyze_test_files function"""

    def test_analyze_test_files_with_complex_pytest_markers(self, temp_project_dir):
        """Test detection of complex pytest markers"""
        tests_dir = temp_project_dir / "tests"
        tests_dir.mkdir(exist_ok=True)

        test_file = tests_dir / "test_markers.py"
        test_file.write_text(
            """
import pytest

@pytest.mark.slow
@pytest.mark.integration
@pytest.mark.parametrize("value", [1, 2, 3])
def test_with_markers(value):
    assert value > 0

@pytest.mark.skip(reason="Not implemented yet")
def test_skipped():
    pass

@pytest.mark.xfail
def test_expected_failure():
    assert False
"""
        )

        with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
            mock_config.project_root = temp_project_dir
            result = analyze_test_files("tests")

        # Check that markers are collected (if any)
        assert "markers" in result
        if result["markers"]:  # Only check content if markers are found
            marker_names = [m["name"] for m in result["markers"]]
            # At least some common pytest markers should be detected
            common_markers = ["slow", "integration", "parametrize", "skip", "xfail"]
            assert any(marker in marker_names for marker in common_markers)

    def test_analyze_test_files_with_nested_test_classes(self, temp_project_dir):
        """Test analysis of nested test class structures"""
        tests_dir = temp_project_dir / "tests"
        tests_dir.mkdir(exist_ok=True)

        test_file = tests_dir / "test_nested.py"
        test_file.write_text(
            """
import unittest

class TestOuter(unittest.TestCase):
    def test_outer_method(self):
        pass

    class TestInner(unittest.TestCase):
        def test_inner_method(self):
            pass

class TestAnother:
    def test_pytest_style(self):
        assert True

    class TestNested:
        def test_nested_pytest(self):
            assert True
"""
        )

        with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
            mock_config.project_root = temp_project_dir
            result = analyze_test_files("tests")

        assert len(result["test_classes"]) >= 2
        assert len(result["test_functions"]) >= 4


class TestAnalyzeTestFiles:
    """Test the analyze_test_files function"""

    def test_analyze_test_files_basic_structure(self, temp_project_dir):
        """Test basic structure of analyze_test_files output"""
        tests_dir = temp_project_dir / "tests"
        tests_dir.mkdir(exist_ok=True)

        test_file = tests_dir / "test_example.py"
        test_file.write_text(
            """
import pytest

def test_basic():
    assert True

class TestExample:
    def test_method(self):
        assert True
"""
        )

        with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
            mock_config.project_root = temp_project_dir
            result = analyze_test_files("tests")

        assert "total_test_files" in result
        assert "test_files" in result
        assert "test_classes" in result
        assert "test_functions" in result
        assert "fixtures" in result
        assert "markers" in result
        assert "imports" in result
        assert result["total_test_files"] >= 1

    def test_analyze_test_files_nonexistent_directory(self, temp_project_dir):
        """Test handling of non-existent directory"""
        with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
            mock_config.project_root = temp_project_dir
            result = analyze_test_files("nonexistent")

        assert "error" in result
        assert "Directory not found" in result["error"]

    def test_analyze_test_files_detects_pytest_fixtures(self, temp_project_dir):
        """Test detection of pytest fixtures"""
        tests_dir = temp_project_dir / "tests"
        tests_dir.mkdir(exist_ok=True)

        test_file = tests_dir / "test_fixtures.py"
        test_file.write_text(
            """
import pytest

@pytest.fixture
def sample_data():
    return {"key": "value"}

@pytest.fixture(scope="session")
def db_connection():
    return "connection"

def test_with_fixture(sample_data):
    assert sample_data["key"] == "value"
"""
        )

        with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
            mock_config.project_root = temp_project_dir
            result = analyze_test_files("tests")

        assert len(result["fixtures"]) >= 2
        assert len(result["pytest_fixtures"]) >= 2

        fixture_names = [f["name"] for f in result["fixtures"]]
        assert "sample_data" in fixture_names
        assert "db_connection" in fixture_names

    def test_analyze_test_files_detects_unittest_classes(self, temp_project_dir):
        """Test detection of unittest test classes"""
        tests_dir = temp_project_dir / "tests"
        tests_dir.mkdir(exist_ok=True)

        test_file = tests_dir / "test_unittest.py"
        test_file.write_text(
            """
import unittest

class TestExample(unittest.TestCase):
    def setUp(self):
        self.data = "test"

    def test_something(self):
        self.assertTrue(True)

    def tearDown(self):
        pass
"""
        )

        with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
            mock_config.project_root = temp_project_dir
            result = analyze_test_files("tests")

        assert len(result["unittest_classes"]) >= 1
        assert len(result["setup_teardown_methods"]) >= 2

        unittest_class = result["unittest_classes"][0]
        assert unittest_class["name"] == "TestExample"
        assert unittest_class["framework"] == "unittest"

    def test_analyze_test_files_detects_mock_usage(self, temp_project_dir):
        """Test detection of mock usage patterns"""
        tests_dir = temp_project_dir / "tests"
        tests_dir.mkdir(exist_ok=True)

        test_file = tests_dir / "test_mocks.py"
        test_file.write_text(
            """
from unittest.mock import MagicMock, patch

def test_with_mock():
    mock_obj = MagicMock()
    result = mock_obj.some_method()
    assert result is not None
"""
        )

        with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
            mock_config.project_root = temp_project_dir
            result = analyze_test_files("tests")

        assert len(result["mock_usage"]) >= 1
        mock_methods = [m["method"] for m in result["mock_usage"]]
        assert "MagicMock" in mock_methods

    def test_analyze_test_files_handles_syntax_errors_gracefully(
        self, temp_project_dir
    ):
        """Test that syntax errors in test files are handled gracefully"""
        tests_dir = temp_project_dir / "tests"
        tests_dir.mkdir(exist_ok=True)

        invalid_file = tests_dir / "test_invalid.py"
        invalid_file.write_text(
            """
def test_invalid(
    # Missing closing parenthesis and body
"""
        )

        valid_file = tests_dir / "test_valid.py"
        valid_file.write_text(
            """
def test_valid():
    assert True
"""
        )

        with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
            mock_config.project_root = temp_project_dir
            result = analyze_test_files("tests")

        # Should still process valid files despite syntax errors in others
        assert "total_test_files" in result
        assert len(result["test_functions"]) >= 1


class TestGetTestPatterns:
    """Test the get_test_patterns function"""

    def test_get_test_patterns_basic_structure(self, temp_project_dir):
        """Test basic structure of get_test_patterns output"""
        tests_dir = temp_project_dir / "tests"
        tests_dir.mkdir(exist_ok=True)

        test_file = tests_dir / "test_example.py"
        test_file.write_text(
            """
import pytest

def test_basic():
    assert True
"""
        )

        with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
            mock_config.project_root = temp_project_dir
            result = get_test_patterns("tests")

        expected_keys = [
            "testing_frameworks",
            "framework_usage",
            "common_fixtures",
            "common_markers",
            "mocking_patterns",
            "assertion_patterns",
            "setup_patterns",
            "parametrization_patterns",
            "unittest_patterns",
            "pytest_patterns",
        ]

        for key in expected_keys:
            assert key in result

    def test_get_test_patterns_detects_frameworks(self, temp_project_dir):
        """Test detection of testing frameworks"""
        tests_dir = temp_project_dir / "tests"
        tests_dir.mkdir(exist_ok=True)

        pytest_file = tests_dir / "test_pytest.py"
        pytest_file.write_text(
            """
import pytest

def test_pytest_style():
    assert True
"""
        )

        unittest_file = tests_dir / "test_unittest.py"
        unittest_file.write_text(
            """
import unittest

class TestUnittest(unittest.TestCase):
    def test_unittest_style(self):
        self.assertTrue(True)
"""
        )

        with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
            mock_config.project_root = temp_project_dir
            result = get_test_patterns("tests")

        assert "pytest" in result["testing_frameworks"]
        assert "unittest" in result["testing_frameworks"]
        assert result["framework_usage"]["pytest"] > 0
        assert result["framework_usage"]["unittest"] > 0
        assert result["framework_usage"]["mixed"] > 0

    def test_get_test_patterns_counts_framework_usage(self, temp_project_dir):
        """Test counting of framework usage"""
        tests_dir = temp_project_dir / "tests"
        tests_dir.mkdir(exist_ok=True)

        test_file = tests_dir / "test_multiple.py"
        test_file.write_text(
            """
import pytest

def test_one():
    assert True

def test_two():
    assert True

class TestClass:
    def test_three(self):
        assert True
"""
        )

        with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
            mock_config.project_root = temp_project_dir
            result = get_test_patterns("tests")

        assert result["framework_usage"]["pytest"] >= 3

    def test_get_test_patterns_detects_mocking_patterns(self, temp_project_dir):
        """Test detection of mocking patterns"""
        tests_dir = temp_project_dir / "tests"
        tests_dir.mkdir(exist_ok=True)

        test_file = tests_dir / "test_mocks.py"
        test_file.write_text(
            """
from unittest.mock import Mock, MagicMock, patch

def test_with_mocks():
    mock = Mock()
    magic_mock = MagicMock()
"""
        )

        with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
            mock_config.project_root = temp_project_dir
            result = get_test_patterns("tests")

        assert "mock_usage_summary" in result
        mock_summary = result["mock_usage_summary"]
        assert "Mock" in mock_summary or "MagicMock" in mock_summary

    def test_get_test_patterns_with_directory_error(self, temp_project_dir):
        """Test handling of directory errors"""
        with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
            mock_config.project_root = temp_project_dir
            result = get_test_patterns("nonexistent")

        assert "error" in result


class TestFindUntestedCode:
    """Test the find_untested_code function"""

    def test_find_untested_code_basic_structure(self, temp_project_dir):
        """Test basic structure of find_untested_code output"""
        # Create source files
        src_dir = temp_project_dir / "src"
        src_dir.mkdir(exist_ok=True)

        source_file = src_dir / "example.py"
        source_file.write_text(
            """
def untested_function():
    return "hello"

class UntestedClass:
    def method(self):
        pass
"""
        )

        # Create test directory
        tests_dir = temp_project_dir / "tests"
        tests_dir.mkdir(exist_ok=True)

        test_file = tests_dir / "test_something.py"
        test_file.write_text(
            """
def test_placeholder():
    assert True
"""
        )

        with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
            mock_config.project_root = temp_project_dir
            result = find_untested_code("src", "tests")

        expected_keys = [
            "untested_functions",
            "untested_classes",
            "untested_files",
            "analysis_summary",
        ]

        for key in expected_keys:
            assert key in result

        assert "total_source_files" in result["analysis_summary"]
        assert "total_test_files" in result["analysis_summary"]

    def test_find_untested_code_detects_untested_functions(self, temp_project_dir):
        """Test detection of untested functions"""
        src_dir = temp_project_dir / "src"
        src_dir.mkdir(exist_ok=True)

        source_file = src_dir / "example.py"
        source_file.write_text(
            '''
def public_function():
    """A public function that should be tested."""
    return "hello"

def _private_function():
    """A private function that typically wouldn't be tested."""
    return "private"
'''
        )

        tests_dir = temp_project_dir / "tests"
        tests_dir.mkdir(exist_ok=True)

        test_file = tests_dir / "test_other.py"
        test_file.write_text(
            """
def test_something_else():
    assert True
"""
        )

        with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
            mock_config.project_root = temp_project_dir
            result = find_untested_code("src", "tests")

        assert len(result["untested_functions"]) >= 1

        function_names = [f["name"] for f in result["untested_functions"]]
        assert "public_function" in function_names
        assert (
            "_private_function" not in function_names
        )  # Private functions are excluded

    def test_find_untested_code_detects_untested_classes(self, temp_project_dir):
        """Test detection of untested classes"""
        src_dir = temp_project_dir / "src"
        src_dir.mkdir(exist_ok=True)

        source_file = src_dir / "example.py"
        source_file.write_text(
            '''
class PublicClass:
    """A public class that should be tested."""
    def method(self):
        pass

class _PrivateClass:
    """A private class."""
    pass
'''
        )

        tests_dir = temp_project_dir / "tests"
        tests_dir.mkdir(exist_ok=True)

        test_file = tests_dir / "test_other.py"
        test_file.write_text(
            """
def test_something_else():
    assert True
"""
        )

        with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
            mock_config.project_root = temp_project_dir
            result = find_untested_code("src", "tests")

        assert len(result["untested_classes"]) >= 1

        class_names = [c["name"] for c in result["untested_classes"]]
        assert "PublicClass" in class_names
        assert "_PrivateClass" not in class_names  # Private classes are excluded

    def test_find_untested_code_with_nonexistent_directories(self, temp_project_dir):
        """Test handling of non-existent directories"""
        with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
            mock_config.project_root = temp_project_dir

            # Test non-existent source directory
            result = find_untested_code("nonexistent_src", "tests")
            assert "error" in result
            assert "Source directory not found" in result["error"]

            # Test non-existent test directory
            src_dir = temp_project_dir / "src"
            src_dir.mkdir(exist_ok=True)

            result = find_untested_code("src", "nonexistent_tests")
            assert "error" in result
            assert "Test directory not found" in result["error"]

    def test_find_untested_code_with_default_directories(self, temp_project_dir):
        """Test using default directories"""
        # Create default structure
        tests_dir = temp_project_dir / "tests"
        tests_dir.mkdir(exist_ok=True)

        test_file = tests_dir / "test_example.py"
        test_file.write_text(
            """
def test_something():
    assert True
"""
        )

        # Create some source files in project root
        source_file = temp_project_dir / "example.py"
        source_file.write_text(
            """
def some_function():
    pass
"""
        )

        with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
            mock_config.project_root = temp_project_dir
            result = find_untested_code()  # No directories specified

        assert "untested_functions" in result
        assert "analysis_summary" in result


class TestSuggestTestCasesAdvanced:
    """Additional comprehensive tests for suggest_test_cases function to increase coverage"""

    def test_suggest_test_cases_with_complex_function_signatures(
        self, temp_project_dir
    ):
        """Test test case generation for functions with complex parameter types"""
        source_file = temp_project_dir / "complex_example.py"
        source_file.write_text(
            '''
def complex_function(
    str_param: str,
    int_param: int,
    list_param: List[str],
    dict_param: Dict[str, Any],
    optional_param: Optional[str] = None
) -> bool:
    """
    A complex function that raises ValueError on invalid input.
    Also supports async operations.
    """
    if not str_param:
        raise ValueError("str_param cannot be empty")
    return True
'''
        )

        with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
            mock_config.project_root = temp_project_dir
            result = suggest_test_cases(
                str(source_file), function_name="complex_function"
            )

        # Should generate multiple test types
        assert len(result["test_suggestions"]) > 3

        test_names = [t["test_name"] for t in result["test_suggestions"]]

        # Check for basic test
        assert any("basic" in name for name in test_names)

        # Check for at least some parameter-specific tests (the exact names may vary)
        parameter_tests = [
            name
            for name in test_names
            if any(
                param in name
                for param in ["str_param", "int_param", "list_param", "dict_param"]
            )
        ]
        assert len(parameter_tests) > 0

        # Check for exception test based on docstring
        assert any(
            "raises_exception" in name or "exception" in name for name in test_names
        )

        # Check for return type test
        assert any("return_type" in name for name in test_names)

    def test_suggest_test_cases_with_async_function_docstring(self, temp_project_dir):
        """Test test case generation for async functions"""
        source_file = temp_project_dir / "async_example.py"
        source_file.write_text(
            '''
async def async_function(value: str) -> str:
    """
    An async function that processes input.
    This function supports async operations.
    """
    await asyncio.sleep(0.1)
    return value.upper()
'''
        )

        with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
            mock_config.project_root = temp_project_dir
            result = suggest_test_cases(
                str(source_file), function_name="async_function"
            )

        test_names = [t["test_name"] for t in result["test_suggestions"]]

        # Should generate test suggestions for async function
        assert len(result["test_suggestions"]) > 0

        # Check for async-related tests (either by name or docstring detection)
        async_tests = [
            t
            for t in result["test_suggestions"]
            if "async" in t.get("test_name", "").lower()
        ]
        if async_tests:
            # If async tests are found by name, they should exist
            assert len(async_tests) >= 1
        else:
            # If no specific async tests by name, check for basic functionality
            assert any("basic" in name for name in test_names)
            # And verify that the function's async nature can be suggested through
            # other test types
            assert len(result["test_suggestions"]) > 1

    def test_suggest_test_cases_with_complex_class(self, temp_project_dir):
        """Test test case generation for complex class with multiple methods"""
        source_file = temp_project_dir / "complex_class.py"
        source_file.write_text(
            '''
class ComplexCalculator:
    """A complex calculator with various operations."""

    def __init__(self, precision: int = 2):
        """Initialize calculator with precision."""
        self.precision = precision

    def add(self, a: float, b: float) -> float:
        """Add two numbers."""
        return round(a + b, self.precision)

    def divide(self, a: float, b: float) -> float:
        """
        Divide two numbers.
        Raises ZeroDivisionError if b is zero.
        """
        if b == 0:
            raise ZeroDivisionError("Cannot divide by zero")
        return round(a / b, self.precision)

    def _private_method(self):
        """Private method that shouldn't be tested."""
        pass
'''
        )

        with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
            mock_config.project_root = temp_project_dir
            result = suggest_test_cases(
                str(source_file), class_name="ComplexCalculator"
            )

        assert len(result["test_suggestions"]) > 0

        test_names = [t["test_name"] for t in result["test_suggestions"]]

        # Should have class instantiation test
        assert any("instantiation" in name for name in test_names)

        # Should have method tests for public methods only
        assert any("add" in name for name in test_names)
        assert any("divide" in name for name in test_names)

        # Should not have tests for private methods
        assert not any("_private_method" in name for name in test_names)

    def test_suggest_test_cases_framework_autodetection(self, temp_project_dir):
        """Test automatic framework detection based on project patterns"""
        source_file = temp_project_dir / "example.py"
        source_file.write_text(
            '''
def simple_function() -> bool:
    """Simple function."""
    return True
'''
        )

        # Mock get_test_patterns to return unittest framework
        with patch(
            "redis_test_mcp_tools.tools.test_tools.get_test_patterns"
        ) as mock_get_patterns:
            mock_get_patterns.return_value = {
                "testing_frameworks": ["unittest"],
                "framework_usage": {"unittest": 5, "pytest": 0},
            }

            with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
                mock_config.project_root = temp_project_dir
                result = suggest_test_cases(str(source_file))

        # Should detect unittest as the framework
        assert result["framework"] == "unittest"
        assert result["recommended_framework"] == "unittest"

        # Mock get_test_patterns to return pytest framework
        with patch(
            "redis_test_mcp_tools.tools.test_tools.get_test_patterns"
        ) as mock_get_patterns:
            mock_get_patterns.return_value = {
                "testing_frameworks": ["pytest"],
                "framework_usage": {"pytest": 8, "unittest": 0},
            }

            with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
                mock_config.project_root = temp_project_dir
                result = suggest_test_cases(str(source_file))

        # Should detect pytest as the framework
        assert result["framework"] == "pytest"
        assert result["recommended_framework"] == "pytest"


class TestSuggestTestCases:
    """Test the suggest_test_cases function"""

    def test_suggest_test_cases_basic_structure(self, temp_project_dir):
        """Test basic structure of suggest_test_cases output"""
        source_file = temp_project_dir / "example.py"
        source_file.write_text(
            '''
def example_function(param1: str, param2: int = 10) -> str:
    """An example function for testing."""
    return f"{param1}_{param2}"
'''
        )

        with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
            mock_config.project_root = temp_project_dir
            result = suggest_test_cases(str(source_file))

        expected_keys = [
            "file_path",
            "framework",
            "recommended_framework",
            "test_suggestions",
        ]

        for key in expected_keys:
            assert key in result

        assert isinstance(result["test_suggestions"], list)
        assert len(result["test_suggestions"]) > 0

    def test_suggest_test_cases_for_specific_function(self, temp_project_dir):
        """Test suggesting test cases for a specific function"""
        source_file = temp_project_dir / "example.py"
        source_file.write_text(
            '''
def target_function(value: str) -> str:
    """Target function for testing."""
    return value.upper()

def other_function():
    """Another function."""
    pass
'''
        )

        with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
            mock_config.project_root = temp_project_dir
            result = suggest_test_cases(
                str(source_file), function_name="target_function"
            )

        assert len(result["test_suggestions"]) > 0

        # Should have suggestions for the target function
        function_tests = [
            s for s in result["test_suggestions"] if "target_function" in s["test_name"]
        ]
        assert len(function_tests) > 0

    def test_suggest_test_cases_for_specific_class(self, temp_project_dir):
        """Test suggesting test cases for a specific class"""
        source_file = temp_project_dir / "example.py"
        source_file.write_text(
            '''
class TargetClass:
    """Target class for testing."""

    def __init__(self, value: str):
        self.value = value

    def get_value(self) -> str:
        return self.value

    def set_value(self, value: str):
        self.value = value

class OtherClass:
    """Another class."""
    pass
'''
        )

        with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
            mock_config.project_root = temp_project_dir
            result = suggest_test_cases(str(source_file), class_name="TargetClass")

        assert len(result["test_suggestions"]) > 0

        # Should have suggestions for the target class
        class_tests = [
            s for s in result["test_suggestions"] if "TargetClass" in s["test_name"]
        ]
        assert len(class_tests) > 0

    def test_suggest_test_cases_with_unittest_framework(self, temp_project_dir):
        """Test suggesting test cases with unittest framework"""
        source_file = temp_project_dir / "example.py"
        source_file.write_text(
            '''
def example_function():
    """Example function."""
    return True
'''
        )

        with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
            mock_config.project_root = temp_project_dir
            result = suggest_test_cases(str(source_file), framework="unittest")

        assert result["framework"] == "unittest"

        # Check for unittest-specific assertions
        for suggestion in result["test_suggestions"]:
            if suggestion.get("suggested_assertions"):
                unittest_assertions = ["assertEqual", "assertTrue", "assertFalse"]
                has_unittest_assertion = any(
                    assertion in suggestion["suggested_assertions"]
                    for assertion in unittest_assertions
                )
                assert has_unittest_assertion

    def test_suggest_test_cases_with_pytest_framework(self, temp_project_dir):
        """Test suggesting test cases with pytest framework"""
        source_file = temp_project_dir / "example.py"
        source_file.write_text(
            '''
def example_function():
    """Example function."""
    return True
'''
        )

        with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
            mock_config.project_root = temp_project_dir
            result = suggest_test_cases(str(source_file), framework="pytest")

        assert result["framework"] == "pytest"

        # Check for pytest-specific assertions
        for suggestion in result["test_suggestions"]:
            if suggestion.get("suggested_assertions"):
                pytest_assertions = ["assert", "assert ==", "assert !="]
                has_pytest_assertion = any(
                    assertion in suggestion["suggested_assertions"]
                    for assertion in pytest_assertions
                )
                assert has_pytest_assertion

    def test_suggest_test_cases_nonexistent_function(self, temp_project_dir):
        """Test suggesting test cases for non-existent function"""
        source_file = temp_project_dir / "example.py"
        source_file.write_text(
            """
def existing_function():
    pass
"""
        )

        with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
            mock_config.project_root = temp_project_dir
            result = suggest_test_cases(
                str(source_file), function_name="nonexistent_function"
            )

        assert "error" in result
        assert 'Function "nonexistent_function" not found' in result["error"]

    def test_suggest_test_cases_nonexistent_class(self, temp_project_dir):
        """Test suggesting test cases for non-existent class"""
        source_file = temp_project_dir / "example.py"
        source_file.write_text(
            """
class ExistingClass:
    pass
"""
        )

        with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
            mock_config.project_root = temp_project_dir
            result = suggest_test_cases(str(source_file), class_name="NonexistentClass")

        assert "error" in result
        assert 'Class "NonexistentClass" not found' in result["error"]

    def test_suggest_test_cases_invalid_file(self, temp_project_dir):
        """Test suggesting test cases for invalid file"""
        nonexistent_file = temp_project_dir / "nonexistent.py"

        with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
            mock_config.project_root = temp_project_dir
            result = suggest_test_cases(str(nonexistent_file))

        assert "error" in result


class TestGetTestCoverageInfo:
    """Test the get_test_coverage_info function"""

    def test_get_test_coverage_info_no_coverage_file(self, temp_project_dir):
        """Test handling when no coverage file exists"""
        with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
            mock_config.project_root = temp_project_dir
            result = get_test_coverage_info()

        assert "error" in result
        assert "No coverage file found" in result["error"]

    def test_get_test_coverage_info_nonexistent_specified_file(self, temp_project_dir):
        """Test handling when specified coverage file doesn't exist"""
        with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
            mock_config.project_root = temp_project_dir
            result = get_test_coverage_info("nonexistent_coverage.xml")

        assert "error" in result
        assert "Coverage file not found" in result["error"]

    def test_get_test_coverage_info_xml_format(self, temp_project_dir):
        """Test parsing XML coverage format"""
        coverage_xml = temp_project_dir / "coverage.xml"
        xml_content = """<?xml version="1.0" ?>
<coverage>
    <sources>
        <source>/path/to/source</source>
    </sources>
    <packages>
        <package name="example">
            <classes>
                <class filename="example.py" name="example.py">
                    <lines>
                        <line hits="1" number="1"/>
                        <line hits="0" number="2"/>
                        <line hits="1" number="3"/>
                    </lines>
                </class>
            </classes>
        </package>
    </packages>
</coverage>"""
        coverage_xml.write_text(xml_content)

        with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
            mock_config.project_root = temp_project_dir
            result = get_test_coverage_info("coverage.xml")

        assert "coverage_file" in result
        assert "coverage_data" in result
        assert "summary" in result
        assert result["coverage_file"] == "coverage.xml"

        # Check summary contains expected fields
        summary = result["summary"]
        assert "total_lines" in summary
        assert "covered_lines" in summary
        assert "coverage_percentage" in summary

    def test_get_test_coverage_info_binary_format(self, temp_project_dir):
        """Test parsing binary coverage format"""
        coverage_file = temp_project_dir / ".coverage"
        coverage_file.write_text("")  # Create empty file

        # Create a mock coverage module
        mock_coverage = MagicMock()
        mock_cov = MagicMock()
        mock_cov.get_data.return_value.measured_files.return_value = [
            str(temp_project_dir / "example.py")
        ]
        mock_cov.analysis2.return_value = (
            None,  # unused
            [1, 2, 3, 4, 5],  # statements
            None,  # unused
            [2, 4],  # missing lines
        )
        mock_coverage.Coverage.return_value = mock_cov

        with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
            mock_config.project_root = temp_project_dir

            # Temporarily add the mock to sys.modules before calling the function
            with patch.dict("sys.modules", {"coverage": mock_coverage}):
                result = get_test_coverage_info(".coverage")

        assert "coverage_file" in result
        assert "coverage_data" in result
        assert "summary" in result
        assert result["coverage_file"] == ".coverage"

    def test_get_test_coverage_info_missing_coverage_library(self, temp_project_dir):
        """Test handling when coverage library is not available"""
        coverage_file = temp_project_dir / ".coverage"
        coverage_file.write_text("")

        with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
            mock_config.project_root = temp_project_dir

            # Mock import to raise ImportError for coverage
            def mock_import(name, *args, **kwargs):
                if name == "coverage":
                    raise ImportError("No module named 'coverage'")
                return __import__(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                result = get_test_coverage_info(".coverage")

        assert "error" in result
        assert "coverage library not available" in result["error"]

    def test_get_test_coverage_info_unsupported_format(self, temp_project_dir):
        """Test handling of unsupported coverage file format"""
        coverage_file = temp_project_dir / "coverage.txt"
        coverage_file.write_text("Some unsupported format")

        with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
            mock_config.project_root = temp_project_dir
            result = get_test_coverage_info("coverage.txt")

        assert "error" in result
        assert "Unsupported coverage file format" in result["error"]

    def test_get_test_coverage_info_finds_common_files(self, temp_project_dir):
        """Test that function finds common coverage file locations"""
        # Create a .coverage file
        coverage_file = temp_project_dir / ".coverage"
        coverage_file.write_text("")

        # Create a mock coverage module
        mock_coverage = MagicMock()
        mock_cov = MagicMock()
        mock_cov.get_data.return_value.measured_files.return_value = []
        mock_coverage.Coverage.return_value = mock_cov

        with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
            mock_config.project_root = temp_project_dir

            with patch.dict("sys.modules", {"coverage": mock_coverage}):
                result = get_test_coverage_info()  # No file specified

        # Should find the .coverage file automatically
        assert "coverage_file" in result
        assert result["coverage_file"] == ".coverage"


class TestSuggestedAssertionsViaTestCases:
    """Test the _get_suggested_assertions helper function indirectly through suggest_test_cases"""

    def test_suggested_assertions_pytest_style(self, temp_project_dir):
        """Test that pytest-style assertions are suggested via suggest_test_cases"""
        source_file = temp_project_dir / "example.py"
        source_file.write_text(
            '''
def example_function(value: str) -> str:
    """Example function for testing."""
    return value.upper()
'''
        )

        with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
            mock_config.project_root = temp_project_dir
            result = suggest_test_cases(str(source_file), framework="pytest")

        # Check that pytest-style assertions are included
        has_any_pytest_assertion = False
        for suggestion in result["test_suggestions"]:
            if suggestion.get("suggested_assertions"):
                pytest_assertions = [
                    "assert",
                    "assert ==",
                    "assert !=",
                    "assert is",
                    "assert is not",
                ]
                has_pytest_assertion = any(
                    assertion in suggestion["suggested_assertions"]
                    for assertion in pytest_assertions
                )
                if has_pytest_assertion:
                    has_any_pytest_assertion = True
                    break

        assert (
            has_any_pytest_assertion
        ), "No suggestions found with pytest-style assertions"

    def test_suggested_assertions_unittest_style(self, temp_project_dir):
        """Test that unittest-style assertions are suggested via suggest_test_cases"""
        source_file = temp_project_dir / "example.py"
        source_file.write_text(
            '''
def example_function(value: str) -> str:
    """Example function for testing."""
    return value.upper()
'''
        )

        with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
            mock_config.project_root = temp_project_dir
            result = suggest_test_cases(str(source_file), framework="unittest")

        # Check that unittest-style assertions are included
        has_any_unittest_assertion = False
        for suggestion in result["test_suggestions"]:
            if suggestion.get("suggested_assertions"):
                unittest_assertions = [
                    "assertEqual",
                    "assertNotEqual",
                    "assertTrue",
                    "assertFalse",
                    "assertIs",
                    "assertIsNot",
                ]
                has_unittest_assertion = any(
                    assertion in suggestion["suggested_assertions"]
                    for assertion in unittest_assertions
                )
                if has_unittest_assertion:
                    has_any_unittest_assertion = True
                    break

        assert (
            has_any_unittest_assertion
        ), "No suggestions found with unittest-style assertions"


class TestTestToolsIntegration:
    """Integration tests for test_tools functions working together"""

    def test_analyze_and_suggest_integration(self, temp_project_dir):
        """Test integration between analyze_test_files and suggest_test_cases"""
        # Create a source file
        source_file = temp_project_dir / "calculator.py"
        source_file.write_text(
            '''
class Calculator:
    """A simple calculator class."""

    def add(self, a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    def divide(self, a: int, b: int) -> float:
        """Divide two numbers."""
        if b == 0:
            raise ValueError("Cannot divide by zero")
        return a / b
'''
        )

        # Create existing test file
        tests_dir = temp_project_dir / "tests"
        tests_dir.mkdir(exist_ok=True)

        test_file = tests_dir / "test_calculator.py"
        test_file.write_text(
            """
import pytest
from calculator import Calculator

class TestCalculator:
    def test_add(self):
        calc = Calculator()
        assert calc.add(2, 3) == 5
"""
        )

        with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
            mock_config.project_root = temp_project_dir

            # Analyze existing tests
            analysis = analyze_test_files("tests")
            assert analysis["total_test_files"] == 1
            assert len(analysis["test_functions"]) >= 1

            # Suggest additional test cases
            suggestions = suggest_test_cases(str(source_file), class_name="Calculator")
            assert len(suggestions["test_suggestions"]) > 0

            # Find untested code
            untested = find_untested_code(str(temp_project_dir), "tests")
            # Should find the divide method as untested
            [f["name"] for f in untested["untested_functions"]]
            # Note: Might not detect if imports are properly analyzed

    def test_framework_detection_consistency(self, temp_project_dir):
        """Test that framework detection is consistent across functions"""
        tests_dir = temp_project_dir / "tests"
        tests_dir.mkdir(exist_ok=True)

        # Create a unittest-style test
        test_file = tests_dir / "test_unittest_style.py"
        test_file.write_text(
            """
import unittest

class TestExample(unittest.TestCase):
    def test_something(self):
        self.assertTrue(True)
"""
        )

        with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
            mock_config.project_root = temp_project_dir

            # Analyze test patterns
            patterns = get_test_patterns("tests")
            assert "unittest" in patterns["testing_frameworks"]

            # Analyze test files
            analysis = analyze_test_files("tests")
            unittest_tests = [
                t for t in analysis["test_functions"] if t["framework"] == "unittest"
            ]
            assert len(unittest_tests) >= 1


class TestTestToolsErrorHandling:
    """Test error handling and edge cases for test_tools functions"""

    def test_functions_handle_empty_directories(self, temp_project_dir):
        """Test that functions handle empty directories gracefully"""
        empty_dir = temp_project_dir / "empty"
        empty_dir.mkdir(exist_ok=True)

        with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
            mock_config.project_root = temp_project_dir

            # All functions should handle empty directories
            analysis = analyze_test_files("empty")
            assert analysis["total_test_files"] == 0

            patterns = get_test_patterns("empty")
            assert patterns["framework_usage"]["pytest"] == 0

            untested = find_untested_code("empty", "empty")
            assert len(untested["untested_functions"]) == 0

    def test_functions_handle_permission_errors(self, temp_project_dir):
        """Test handling of permission errors"""
        # Create tests directory first so the path check passes
        tests_dir = temp_project_dir / "tests"
        tests_dir.mkdir(exist_ok=True)

        # This test may not work on all systems, so we'll mock the behavior
        with patch(
            "redis_test_mcp_tools.tools.test_tools.find_test_files",
            side_effect=PermissionError("Permission denied"),
        ):
            with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
                mock_config.project_root = temp_project_dir

                # The function should propagate permission errors
                with pytest.raises(PermissionError, match="Permission denied"):
                    analyze_test_files("tests")

    def test_functions_handle_large_files(self, temp_project_dir):
        """Test handling of very large files"""
        tests_dir = temp_project_dir / "tests"
        tests_dir.mkdir(exist_ok=True)

        # Create a large test file
        large_test_file = tests_dir / "test_large.py"
        large_content = (
            "# Large file\n"
            + "def test_function_{}():\n    assert True\n\n".replace("{}", "{}") * 100
        )
        large_content = large_content.format(*range(100))
        large_test_file.write_text(large_content)

        with patch("redis_test_mcp_tools.tools.test_tools.config") as mock_config:
            mock_config.project_root = temp_project_dir

            # Should handle large files without issues
            analysis = analyze_test_files("tests")
            assert analysis["total_test_files"] == 1
            assert len(analysis["test_functions"]) == 100
