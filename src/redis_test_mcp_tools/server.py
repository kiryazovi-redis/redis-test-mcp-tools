#!/usr/bin/env python3
"""
MCP Server Implementation for Redis-py Test Infrastructure

This module contains the MCP server setup and all tool handlers.
"""

import os
import sys
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server import NotificationOptions
from mcp.types import (
    Resource, Tool, TextContent, ImageContent, EmbeddedResource
)

# Import configuration and tool modules
from .config import config
from .tools.ast_tools import (
    get_ast_from_file, extract_docstring, extract_function_info, 
    extract_class_info, parse_module_ast, get_function_details,
    get_class_details, find_imports_in_file, get_type_hints_from_file
)
from .tools.file_tools import (
    find_test_files, find_python_files, read_file_content,
    get_directory_structure, get_project_info, get_relative_path, is_ignored_path
)
from .tools.test_tools import (
    analyze_test_files, get_test_patterns, find_untested_code,
    suggest_test_cases, get_test_coverage_info
)

def _safe_json_dumps(obj: Any, indent: int = 2) -> str:
    """
    Safely serialize an object to JSON with proper error handling.
    
    Args:
        obj: Object to serialize
        indent: JSON indentation
        
    Returns:
        JSON string or error message
    """
    try:
        # First attempt: direct serialization
        return json.dumps(obj, indent=indent)
    except TypeError as e:
        # Handle non-serializable objects
        try:
            # Convert Path objects and other common non-serializable types
            def convert_obj(item):
                if isinstance(item, Path):
                    return str(item)
                elif hasattr(item, '__dict__'):
                    return str(item)
                elif hasattr(item, 'isoformat'):  # datetime objects
                    return item.isoformat()
                elif isinstance(item, set):
                    return list(item)
                else:
                    return str(item)
            
            # Try to convert and serialize
            converted = json.loads(json.dumps(obj, default=convert_obj))
            return json.dumps(converted, indent=indent)
        except Exception:
            # Last resort: return error info
            return json.dumps({
                'error': f'Serialization error: {str(e)}',
                'type': str(type(obj)),
                'partial_data': str(obj)[:500] + '...' if len(str(obj)) > 500 else str(obj)
            }, indent=indent)
    except (ValueError, RecursionError) as e:
        # Handle circular references and other JSON errors
        return json.dumps({
            'error': f'JSON error: {str(e)}',
            'type': str(type(obj))
        }, indent=indent)
    except Exception as e:
        # Catch-all for any other errors
        return json.dumps({
            'error': f'Unexpected serialization error: {str(e)}',
            'type': str(type(obj))
        }, indent=indent)


def _validate_file_path(file_path: str) -> str:
    """
    Validate and sanitize file path parameter.
    
    Args:
        file_path: The file path to validate
        
    Returns:
        Validated file path
        
    Raises:
        ValueError: If path is invalid or unsafe
    """
    if not file_path or not isinstance(file_path, str):
        raise ValueError("file_path must be a non-empty string")
    
    # Basic path validation (more detailed validation is done in file_tools)
    if '..' in file_path or file_path.startswith('/'):
        raise ValueError("Invalid path: path traversal or absolute paths not allowed")
    
    return file_path.strip()


def _validate_max_size(max_size: Any) -> int:
    """
    Validate max_size parameter.
    
    Args:
        max_size: The max size value to validate
        
    Returns:
        Validated max size as integer
        
    Raises:
        ValueError: If max_size is invalid
    """
    if max_size is None:
        return config.max_file_size
    
    try:
        size = int(max_size)
        if size < 0:
            raise ValueError("max_size must be non-negative")
        if size > 100 * 1024 * 1024:  # 100MB limit
            raise ValueError("max_size too large (max 100MB)")
        return size
    except (TypeError, ValueError) as e:
        raise ValueError(f"max_size must be a valid integer: {str(e)}")


def _validate_max_depth(max_depth: Any) -> int:
    """
    Validate max_depth parameter.
    
    Args:
        max_depth: The max depth value to validate
        
    Returns:
        Validated max depth as integer
        
    Raises:
        ValueError: If max_depth is invalid
    """
    if max_depth is None:
        return config.max_directory_depth
    
    try:
        depth = int(max_depth)
        if depth < 0:
            raise ValueError("max_depth must be non-negative")
        if depth > 20:  # Reasonable limit
            raise ValueError("max_depth too large (max 20)")
        return depth
    except (TypeError, ValueError) as e:
        raise ValueError(f"max_depth must be a valid integer: {str(e)}")


def _validate_framework(framework: Any) -> Optional[str]:
    """
    Validate testing framework parameter.
    
    Args:
        framework: The framework value to validate
        
    Returns:
        Validated framework string or None
        
    Raises:
        ValueError: If framework is invalid
    """
    if framework is None:
        return None
    
    if not isinstance(framework, str):
        raise ValueError("framework must be a string")
    
    framework = framework.strip().lower()
    if framework not in ('pytest', 'unittest'):
        raise ValueError("framework must be 'pytest' or 'unittest'")
    
    return framework


def _validate_identifier(identifier: str, name: str) -> str:
    """
    Validate function/class name parameter.
    
    Args:
        identifier: The identifier to validate
        name: Name of the parameter for error messages
        
    Returns:
        Validated identifier
        
    Raises:
        ValueError: If identifier is invalid
    """
    if not identifier or not isinstance(identifier, str):
        raise ValueError(f"{name} must be a non-empty string")
    
    identifier = identifier.strip()
    
    # Basic Python identifier validation
    if not identifier.replace('_', '').replace('.', '').isalnum():
        raise ValueError(f"{name} must be a valid Python identifier")
    
    return identifier


# Create the server instance
server = Server(config.server_name)


@server.list_tools()
async def handle_list_tools() -> List[Tool]:
    """
    List available tools.
    
    Returns:
        List of Tool objects that this server provides.
    """
    return [
        Tool(
            name="find_python_files",
            description="List all Python files in the project",
            inputSchema={
                "type": "object",
                "properties": {
                    "directory": {
                        "type": "string",
                        "description": "Directory to search in (relative to project root). If not specified, searches entire project."
                    }
                },
                "additionalProperties": False
            }
        ),
        Tool(
            name="read_file",
            description="Read the contents of a file",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the file to read (relative to project root)"
                    },
                    "max_size": {
                        "type": "integer",
                        "description": "Maximum file size to read in bytes (default: 1MB)",
                        "default": 1048576
                    }
                },
                "required": ["file_path"],
                "additionalProperties": False
            }
        ),
        Tool(
            name="get_directory_structure",
            description="Show the directory structure of the project",
            inputSchema={
                "type": "object",
                "properties": {
                    "directory": {
                        "type": "string",
                        "description": "Directory to show structure for (relative to project root). If not specified, shows entire project."
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": "Maximum depth to traverse (default: 3)",
                        "default": 3
                    }
                },
                "additionalProperties": False
            }
        ),
        Tool(
            name="get_project_info",
            description="Get comprehensive information about the project",
            inputSchema={
                "type": "object",
                "properties": {
                    "random_string": {
                        "type": "string",
                        "description": "Dummy parameter for no-parameter tools"
                    }
                },
                "required": ["random_string"]
            }
        ),
        Tool(
            name="parse_module",
            description="Parse a Python file and return classes, functions, and their signatures",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the Python file to parse (relative to project root)"
                    }
                },
                "required": ["file_path"],
                "additionalProperties": False
            }
        ),
        Tool(
            name="get_function_details",
            description="Get detailed information about a specific function (params, return type, docstring)",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the Python file containing the function (relative to project root)"
                    },
                    "function_name": {
                        "type": "string",
                        "description": "Name of the function to analyze"
                    }
                },
                "required": ["file_path", "function_name"],
                "additionalProperties": False
            }
        ),
        Tool(
            name="get_class_details",
            description="Get class methods, properties, and inheritance information",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the Python file containing the class (relative to project root)"
                    },
                    "class_name": {
                        "type": "string",
                        "description": "Name of the class to analyze"
                    }
                },
                "required": ["file_path", "class_name"],
                "additionalProperties": False
            }
        ),
        Tool(
            name="find_imports",
            description="Show what modules/packages a file imports",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the Python file to analyze imports (relative to project root)"
                    }
                },
                "required": ["file_path"],
                "additionalProperties": False
            }
        ),
        Tool(
            name="get_type_hints",
            description="Extract type annotations from functions/methods in a Python file",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the Python file to extract type hints from (relative to project root)"
                    }
                },
                "required": ["file_path"],
                "additionalProperties": False
            }
        ),
        Tool(
            name="analyze_test_files",
            description="Find and parse existing test files, show test structure including fixtures, markers, and test functions",
            inputSchema={
                "type": "object",
                "properties": {
                    "directory": {
                        "type": "string",
                        "description": "Directory to search for test files (relative to project root). If not specified, searches entire project."
                    }
                },
                "additionalProperties": False
            }
        ),
        Tool(
            name="get_test_patterns",
            description="Identify common testing patterns used in the project (fixtures, mocks, frameworks, etc.)",
            inputSchema={
                "type": "object",
                "properties": {
                    "directory": {
                        "type": "string",
                        "description": "Directory to analyze for test patterns (relative to project root). If not specified, analyzes entire project."
                    }
                },
                "additionalProperties": False
            }
        ),
        Tool(
            name="find_untested_code",
            description="Compare source files with test files to find untested functions/classes",
            inputSchema={
                "type": "object",
                "properties": {
                    "source_dir": {
                        "type": "string",
                        "description": "Source directory to analyze (relative to project root). If not specified, analyzes entire project."
                    },
                    "test_dir": {
                        "type": "string",
                        "description": "Test directory to use for comparison (relative to project root). If not specified, uses 'tests' directory."
                    }
                },
                "additionalProperties": False
            }
        ),
        Tool(
            name="suggest_test_cases",
            description="Based on function signatures and docstrings, suggest what test cases should exist for both pytest and unittest frameworks",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the Python file to analyze (relative to project root)"
                    },
                    "function_name": {
                        "type": "string",
                        "description": "Name of specific function to generate test suggestions for. If not specified, generates suggestions for all functions and classes."
                    },
                    "class_name": {
                        "type": "string",
                        "description": "Name of specific class to generate test suggestions for. If not specified, generates suggestions for all functions and classes."
                    },
                    "framework": {
                        "type": "string",
                        "description": "Testing framework to target ('pytest' or 'unittest'). If not specified, auto-detects from project patterns.",
                        "enum": ["pytest", "unittest"]
                    }
                },
                "required": ["file_path"],
                "additionalProperties": False
            }
        ),
        Tool(
            name="get_test_coverage_info",
            description="Parse and show coverage information from pytest-cov data (supports .coverage, coverage.xml)",
            inputSchema={
                "type": "object",
                "properties": {
                    "coverage_file": {
                        "type": "string",
                        "description": "Path to coverage file (relative to project root). If not specified, searches for common coverage files."
                    }
                },
                "additionalProperties": False
            }
        )
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    """
    Handle tool calls.
    
    Args:
        name: Name of the tool to call
        arguments: Tool arguments
        
    Returns:
        List of TextContent with tool results
    """
    try:
        if name == "find_python_files":
            directory = arguments.get("directory")
            files = find_python_files(directory)
            return [TextContent(type="text", text=_safe_json_dumps(files))]
            
        elif name == "read_file":
            file_path = _validate_file_path(arguments["file_path"])
            max_size = _validate_max_size(arguments.get("max_size"))
            content = read_file_content(file_path, max_size)
            return [TextContent(type="text", text=_safe_json_dumps(content))]
            
        elif name == "get_directory_structure":
            directory = arguments.get("directory")
            if directory is not None:
                directory = _validate_file_path(directory)
            max_depth = _validate_max_depth(arguments.get("max_depth"))
            structure = get_directory_structure(directory, max_depth)
            return [TextContent(type="text", text=_safe_json_dumps(structure))]
            
        elif name == "get_project_info":
            info = get_project_info()
            return [TextContent(type="text", text=_safe_json_dumps(info))]
            
        elif name == "parse_module":
            file_path = _validate_file_path(arguments["file_path"])
            result = parse_module_ast(file_path)
            return [TextContent(type="text", text=_safe_json_dumps(result))]
            
        elif name == "get_function_details":
            file_path = _validate_file_path(arguments["file_path"])
            function_name = _validate_identifier(arguments["function_name"], "function_name")
            result = get_function_details(file_path, function_name)
            return [TextContent(type="text", text=_safe_json_dumps(result))]
            
        elif name == "get_class_details":
            file_path = _validate_file_path(arguments["file_path"])
            class_name = _validate_identifier(arguments["class_name"], "class_name")
            result = get_class_details(file_path, class_name)
            return [TextContent(type="text", text=_safe_json_dumps(result))]
            
        elif name == "find_imports":
            file_path = arguments["file_path"]
            result = find_imports_in_file(file_path)
            return [TextContent(type="text", text=_safe_json_dumps(result))]
            
        elif name == "get_type_hints":
            file_path = arguments["file_path"]
            result = get_type_hints_from_file(file_path)
            return [TextContent(type="text", text=_safe_json_dumps(result))]
            
        elif name == "analyze_test_files":
            directory = arguments.get("directory")
            result = analyze_test_files(directory)
            return [TextContent(type="text", text=_safe_json_dumps(result))]
            
        elif name == "get_test_patterns":
            directory = arguments.get("directory")
            result = get_test_patterns(directory)
            return [TextContent(type="text", text=_safe_json_dumps(result))]
            
        elif name == "find_untested_code":
            source_dir = arguments.get("source_dir")
            test_dir = arguments.get("test_dir")
            result = find_untested_code(source_dir, test_dir)
            return [TextContent(type="text", text=_safe_json_dumps(result))]
            
        elif name == "suggest_test_cases":
            file_path = _validate_file_path(arguments["file_path"])
            function_name = arguments.get("function_name")
            if function_name is not None:
                function_name = _validate_identifier(function_name, "function_name")
            class_name = arguments.get("class_name")
            if class_name is not None:
                class_name = _validate_identifier(class_name, "class_name")
            framework = _validate_framework(arguments.get("framework"))
            result = suggest_test_cases(file_path, function_name, class_name, framework)
            return [TextContent(type="text", text=_safe_json_dumps(result))]
            
        elif name == "get_test_coverage_info":
            coverage_file = arguments.get("coverage_file")
            result = get_test_coverage_info(coverage_file)
            return [TextContent(type="text", text=_safe_json_dumps(result))]
            
        else:
            raise ValueError(f"Unknown tool: {name}")
            
    except Exception as e:
        error_msg = f"Error executing {name}: {str(e)}"
        if config.debug:
            import traceback
            error_msg += f"\n\nTraceback:\n{traceback.format_exc()}"
        return [TextContent(type="text", text=error_msg)] 