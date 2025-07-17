"""
Redis Test MCP Tools

A Model Context Protocol (MCP) server for Redis-py test infrastructure.
Provides tools for test generation, code exploration, and project analysis.
"""

__version__ = "0.1.0"
__author__ = "Redis Team"
__email__ = "redis-team@example.com"

from .config import config
from .main import server

__all__ = ["server", "config"]
