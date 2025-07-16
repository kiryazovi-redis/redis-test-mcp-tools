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
            return [TextContent(type="text", text=json.dumps(files, indent=2))]
            
        elif name == "read_file":
            file_path = arguments["file_path"]
            max_size = arguments.get("max_size", config.max_file_size)
            content = read_file_content(file_path, max_size)
            return [TextContent(type="text", text=content)]
            
        elif name == "get_directory_structure":
            directory = arguments.get("directory")
            max_depth = arguments.get("max_depth", config.max_directory_depth)
            structure = get_directory_structure(directory, max_depth)
            return [TextContent(type="text", text=structure)]
            
        elif name == "get_project_info":
            info = get_project_info()
            return [TextContent(type="text", text=json.dumps(info, indent=2))]
            
        elif name == "parse_module":
            file_path = arguments["file_path"]
            result = parse_module_ast(file_path)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
            
        elif name == "get_function_details":
            file_path = arguments["file_path"]
            function_name = arguments["function_name"]
            result = get_function_details(file_path, function_name)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
            
        elif name == "get_class_details":
            file_path = arguments["file_path"]
            class_name = arguments["class_name"]
            result = get_class_details(file_path, class_name)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
            
        elif name == "find_imports":
            file_path = arguments["file_path"]
            result = find_imports_in_file(file_path)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
            
        elif name == "get_type_hints":
            file_path = arguments["file_path"]
            result = get_type_hints_from_file(file_path)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
            
        elif name == "analyze_test_files":
            directory = arguments.get("directory")
            result = analyze_test_files(directory)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
            
        elif name == "get_test_patterns":
            directory = arguments.get("directory")
            result = get_test_patterns(directory)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
            
        elif name == "find_untested_code":
            source_dir = arguments.get("source_dir")
            test_dir = arguments.get("test_dir")
            result = find_untested_code(source_dir, test_dir)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
            
        elif name == "suggest_test_cases":
            file_path = arguments["file_path"]
            function_name = arguments.get("function_name")
            class_name = arguments.get("class_name")
            framework = arguments.get("framework")
            result = suggest_test_cases(file_path, function_name, class_name, framework)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
            
        elif name == "get_test_coverage_info":
            coverage_file = arguments.get("coverage_file")
            result = get_test_coverage_info(coverage_file)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
            
        else:
            raise ValueError(f"Unknown tool: {name}")
            
    except Exception as e:
        error_msg = f"Error executing {name}: {str(e)}"
        if config.debug:
            import traceback
            error_msg += f"\n\nTraceback:\n{traceback.format_exc()}"
        return [TextContent(type="text", text=error_msg)] 