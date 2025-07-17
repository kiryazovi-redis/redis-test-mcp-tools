"""
Configuration settings for the Redis-py MCP Server
"""

import os
from pathlib import Path
from typing import Any, Dict


class MCPServerConfig:
    """Configuration class for the MCP server."""

    def __init__(self):
        self.project_root = Path(__file__).parent.parent.parent
        self.server_name = "redis-py-test-infra"
        self.server_version = "1.0.0"

        # File handling settings
        self.max_file_size = 1024 * 1024  # 1MB default
        self.python_extensions = {".py", ".pyi"}
        self.text_extensions = {
            ".txt",
            ".md",
            ".rst",
            ".yml",
            ".yaml",
            ".json",
            ".toml",
            ".cfg",
            ".ini",
        }

        # Directories to ignore
        self.ignore_dirs = {
            ".git",
            ".venv",
            "venv",
            "__pycache__",
            ".pytest_cache",
            "node_modules",
            ".tox",
            "build",
            "dist",
            ".eggs",
            "env",
            ".coverage",
            ".mypy_cache",
            ".ruff_cache",
        }

        # Files to ignore
        self.ignore_files = {
            ".DS_Store",
            ".gitignore",
            ".gitmodules",
            "Thumbs.db",
            ".coverage",
            ".coveragerc",
            ".python-version",
        }

        # Directory structure settings
        self.max_directory_depth = 3

        # Debug settings
        self.debug = self._parse_bool_env("MCP_DEBUG", False)

        # Logging settings
        self.log_level = os.getenv("MCP_LOG_LEVEL", "INFO")

    def _parse_bool_env(self, env_var: str, default: bool) -> bool:
        """
        Parse boolean environment variable with robust handling of various formats.

        Args:
            env_var: Environment variable name
            default: Default value if not set or invalid

        Returns:
            Boolean value
        """
        try:
            value = os.getenv(env_var)
            if value is None:
                return default

            # Handle string values
            if isinstance(value, str):
                value_lower = value.lower().strip()
                # Truthy values
                if value_lower in ("true", "1", "yes", "on", "enabled"):
                    return True
                # Falsy values
                elif value_lower in ("false", "0", "no", "off", "disabled", ""):
                    return False
                else:
                    # Invalid string value, use default
                    return default

            # Handle non-string values (shouldn't happen with os.getenv, but be safe)
            return bool(value)

        except Exception:
            # Any error in parsing, use default
            return default

    def is_ignored_path(self, path: Path) -> bool:
        """Check if a path should be ignored."""
        parts = path.parts
        for part in parts:
            if part in self.ignore_dirs:
                return True
            # Only ignore hidden files/directories, not path navigation like '..'
            if part.startswith(".") and part not in ("..", "."):
                return True
        return path.name in self.ignore_files

    def is_python_file(self, path: Path) -> bool:
        """Check if a file is a Python file."""
        return path.suffix in self.python_extensions

    def is_text_file(self, path: Path) -> bool:
        """Check if a file is a text file."""
        return path.suffix in self.text_extensions or self.is_python_file(path)

    def is_test_file(self, path: Path) -> bool:
        """Check if a file is a test file."""
        if not self.is_python_file(path):
            return False

        # Check if file is in a test directory
        path_parts = path.parts
        for part in path_parts:
            if part.startswith("test") or part == "tests":
                return True

        # Check if filename indicates it's a test file
        filename = path.name
        return (
            filename.startswith("test_")
            or filename.endswith("_test.py")
            or filename == "test.py"
        )

    def get_project_info(self) -> Dict[str, Any]:
        """Get basic project information."""
        return {
            "name": self.server_name,
            "version": self.server_version,
            "project_root": str(self.project_root),
            "debug": self.debug,
            "max_file_size": self.max_file_size,
            "supported_extensions": {
                "python": list(self.python_extensions),
                "text": list(self.text_extensions),
            },
        }


# Global configuration instance
config = MCPServerConfig()
