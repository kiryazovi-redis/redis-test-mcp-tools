#!/usr/bin/env python3
"""
MCP Server for Redis-py Test Infrastructure

This MCP server provides tools to help with test generation and code exploration
for the redis-py client library project.
"""

from src.redis_test_mcp_tools.server import server
from src.redis_test_mcp_tools.config import config
from mcp.server.models import InitializationOptions
from mcp.server import NotificationOptions
import mcp.server.stdio
import argparse
import asyncio
import sys
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


# Import configuration and server


async def main():
    """Run the MCP server."""
    if config.debug:
        print(
            f"Starting MCP server: {config.server_name} v{config.server_version}",
            file=sys.stderr,
        )
        print(f"Project root: {config.project_root}", file=sys.stderr)

    # Run the server using stdin/stdout streams
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name=config.server_name,
                server_version=config.server_version,
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=f"{config.server_name} MCP Server")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument(
        "--max-file-size",
        type=int,
        default=config.max_file_size,
        help="Maximum file size to read in bytes",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=config.max_directory_depth,
        help="Maximum directory depth to traverse",
    )
    args = parser.parse_args()

    # Update configuration from command line arguments
    if args.debug:
        config.debug = True
        import logging

        logging.basicConfig(level=logging.DEBUG)

    if args.max_file_size:
        config.max_file_size = args.max_file_size

    if args.max_depth:
        config.max_directory_depth = args.max_depth

    asyncio.run(main())
