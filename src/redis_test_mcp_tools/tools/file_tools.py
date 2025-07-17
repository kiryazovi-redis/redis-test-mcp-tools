"""
File system tools for Redis Test MCP Tools.

This module provides functions for finding files, reading file contents,
and getting directory structure information.
"""

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Import configuration
from ..config import config


def _validate_safe_path(file_path: str) -> str:
    """
    Validate and sanitize file path to prevent directory traversal attacks.
    
    Args:
        file_path: The input file path to validate
        
    Returns:
        Sanitized path string
        
    Raises:
        ValueError: If path is unsafe (contains .. or is absolute outside project)
    """
    # Convert to string and normalize
    path_str = str(file_path).strip()
    
    # Block obvious directory traversal attempts
    if '..' in path_str:
        raise ValueError(f"Path traversal not allowed: {file_path}")
    
    # Block absolute paths
    if path_str.startswith('/') or (len(path_str) > 1 and path_str[1] == ':'):
        raise ValueError(f"Absolute paths not allowed: {file_path}")
    
    # Block null bytes and other dangerous characters
    dangerous_chars = ['\x00', '\r', '\n']
    for char in dangerous_chars:
        if char in path_str:
            raise ValueError(f"Invalid character in path: {file_path}")
    
    # Convert to Path and resolve to ensure it's within project
    try:
        candidate_path = config.project_root / path_str
        resolved_path = candidate_path.resolve()
        
        # Ensure the resolved path is within project root
        try:
            resolved_path.relative_to(config.project_root.resolve())
        except ValueError:
            raise ValueError(f"Path outside project directory: {file_path}")
            
        return path_str
        
    except (OSError, ValueError) as e:
        raise ValueError(f"Invalid path: {file_path} - {str(e)}")


def find_test_files(directory: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Find all test files in the project."""
    if directory is None:
        directory = config.project_root
    
    test_files = []
    test_patterns = ['test_*.py', '*_test.py', 'tests.py']
    
    try:
        for pattern in test_patterns:
            for path in directory.rglob(pattern):
                if path.is_file() and not is_ignored_path(path):
                    rel_path = get_relative_path(path)
                    stat = path.stat()
                    test_files.append({
                        'path': rel_path,
                        'name': path.name,
                        'size': stat.st_size,
                        'directory': get_relative_path(path.parent),
                        'modified': stat.st_mtime,
                        'is_test': True
                    })
    except Exception as e:
        print(f"Error finding test files: {e}", file=sys.stderr)
    
    return sorted(test_files, key=lambda x: x['path'])


def get_relative_path(path: Path) -> str:
    """Get path relative to project root."""
    try:
        return str(path.relative_to(config.project_root))
    except ValueError:
        return str(path)


def is_ignored_path(path: Path) -> bool:
    """Check if path should be ignored."""
    return config.is_ignored_path(path)


def find_python_files(directory: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Find all Python files in the project."""
    if directory is None:
        directory = config.project_root
    
    python_files = []
    
    try:
        for path in directory.rglob('*'):
            if path.is_file() and config.is_python_file(path):
                if not is_ignored_path(path):
                    rel_path = get_relative_path(path)
                    stat = path.stat()
                    python_files.append({
                        'path': rel_path,
                        'name': path.name,
                        'size': stat.st_size,
                        'directory': get_relative_path(path.parent),
                        'modified': stat.st_mtime,
                        'is_test': config.is_test_file(path)
                    })
    except Exception as e:
        print(f"Error finding Python files: {e}", file=sys.stderr)
    
    return sorted(python_files, key=lambda x: x['path'])


def read_file_content(file_path: str, max_size: int = None) -> Dict[str, Any]:
    """Read file content with size limits."""
    if max_size is None:
        max_size = config.max_file_size
    
    try:
        # Validate path security first
        try:
            safe_path = _validate_safe_path(file_path)
        except ValueError as e:
            return {'error': f'Invalid path: {str(e)}'}
            
        full_path = config.project_root / safe_path
        
        # Check if file should be ignored
        if config.is_ignored_path(full_path):
            return {'error': f'File is ignored: {file_path}'}
        
        # Check if file exists and is actually a file
        if not full_path.exists():
            return {'error': f'File not found: {file_path}'}
        
        if not full_path.is_file():
            return {'error': f'Path is not a file: {file_path}'}
        
        file_size = full_path.stat().st_size
        truncated = file_size > max_size
        
        with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
            if truncated:
                # Read only up to max_size
                content = f.read(max_size)
                # Try to end at a reasonable boundary
                if len(content) == max_size:
                    # Find the last newline to avoid cutting in the middle of a line
                    last_newline = content.rfind('\n')
                    if last_newline > max_size * 0.9:  # Only if we don't lose too much
                        content = content[:last_newline + 1]
            else:
                content = f.read()
        
        return {
            'path': file_path,
            'content': content,
            'size': file_size,
            'lines': len(content.splitlines()),
            'is_python': config.is_python_file(full_path),
            'is_text': config.is_text_file(full_path),
            'truncated': truncated
        }
    except PermissionError:
        return {'error': f'Permission denied: {file_path}'}
    except Exception as e:
        return {'error': f'Error reading file: {str(e)}'}


def get_directory_structure(directory: Optional[Path] = None, max_depth: int = None) -> Dict[str, Any]:
    """Get directory structure as a tree."""
    if directory is None:
        directory = config.project_root
    else:
        # If directory is passed as string, validate it for security
        if isinstance(directory, str):
            try:
                safe_path = _validate_safe_path(directory)
                directory = config.project_root / safe_path
            except ValueError as e:
                return {'error': f'Invalid directory path: {str(e)}'}
        elif isinstance(directory, Path):
            # Validate that the Path is within project boundaries
            try:
                directory.resolve().relative_to(config.project_root.resolve())
            except ValueError:
                return {'error': f'Directory outside project: {directory}'}
    
    if max_depth is None:
        max_depth = config.max_directory_depth
    
    # Check if directory exists and is accessible
    try:
        if not directory.exists():
            return {'error': f'Directory not found: {directory}'}
        
        if not directory.is_dir():
            return {'error': f'Path is not a directory: {directory}'}
        
        # Test if we can access the directory
        try:
            list(directory.iterdir())
        except PermissionError:
            return {'error': f'Permission denied accessing directory: {directory}'}
        except OSError as e:
            return {'error': f'Cannot access directory: {directory} - {str(e)}'}
            
    except PermissionError:
        return {'error': f'Permission denied accessing path: {directory}'}
    except OSError as e:
        return {'error': f'OS error accessing path: {directory} - {str(e)}'}
    except Exception as e:
        return {'error': f'Unexpected error accessing directory: {directory} - {str(e)}'}
    
    def build_tree(path: Path, current_depth: int = 0) -> Dict[str, Any]:
        if current_depth > max_depth or is_ignored_path(path):
            return None
        
        # Check if path still exists (handle race conditions)
        try:
            if not path.exists():
                return None
        except (OSError, PermissionError):
            # Path became inaccessible during traversal
            return None
        
        try:
            # Determine type with race condition protection
            is_directory = path.is_dir()
            result = {
                'name': path.name,
                'type': 'directory' if is_directory else 'file',
                'path': get_relative_path(path)
            }
            
            if is_directory:
                children = []
                try:
                    # Use sorted() with error handling for race conditions
                    child_paths = list(path.iterdir())
                    for child in sorted(child_paths):
                        if not is_ignored_path(child):
                            child_tree = build_tree(child, current_depth + 1)
                            if child_tree:
                                children.append(child_tree)
                except PermissionError:
                    # No access to directory contents
                    result['access_denied'] = True
                except OSError:
                    # Directory became inaccessible or was deleted
                    result['inaccessible'] = True
                
                result['children'] = children
            else:
                # Handle file metadata with error recovery
                try:
                    stat = path.stat()
                    result['size'] = stat.st_size
                    result['modified'] = stat.st_mtime
                    result['is_python'] = config.is_python_file(path)
                    result['is_text'] = config.is_text_file(path)
                except (OSError, PermissionError):
                    # File became inaccessible or was deleted
                    result['size'] = 0
                    result['modified'] = 0
                    result['is_python'] = False
                    result['is_text'] = False
                    result['stat_failed'] = True
        
        except (OSError, PermissionError):
            # Path became completely inaccessible
            return None
        
        return result
    
    return build_tree(directory)


def get_project_info() -> Dict[str, Any]:
    """Get comprehensive project information."""
    info = config.get_project_info()
    
    # Count files by type
    file_counts = {'python': 0, 'test': 0, 'doc': 0, 'other': 0}
    total_size = 0
    
    for path in config.project_root.rglob('*'):
        if path.is_file() and not is_ignored_path(path):
            size = path.stat().st_size
            total_size += size
            
            if config.is_python_file(path):
                if config.is_test_file(path):
                    file_counts['test'] += 1
                else:
                    file_counts['python'] += 1
            elif path.suffix in {'.rst', '.md'}:
                file_counts['doc'] += 1
            else:
                file_counts['other'] += 1
    
    info['file_counts'] = file_counts
    info['total_size'] = total_size
    
    # Main directories
    main_dirs = []
    for item in config.project_root.iterdir():
        if item.is_dir() and not is_ignored_path(item):
            main_dirs.append({
                'name': item.name,
                'path': get_relative_path(item)
            })
    
    info['main_directories'] = sorted(main_dirs, key=lambda x: x['name'])
    
    # Read pyproject.toml if it exists
    pyproject_path = config.project_root / 'pyproject.toml'
    if pyproject_path.exists():
        try:
            with open(pyproject_path, 'r') as f:
                content = f.read()
                # Extract basic info from pyproject.toml
                lines = content.splitlines()
                for line in lines:
                    if line.startswith('name = '):
                        info['package_name'] = line.split('=')[1].strip().strip('"\'')
                    elif line.startswith('description = '):
                        info['description'] = line.split('=')[1].strip().strip('"\'')
                    elif line.startswith('requires-python = '):
                        info['python_requirement'] = line.split('=')[1].strip().strip('"\'')
        except Exception as e:
            print(f"Error reading pyproject.toml: {e}", file=sys.stderr)
    
    # Key files
    key_files = []
    for filename in ['README.md', 'CONTRIBUTING.md', 'LICENSE', 'pyproject.toml', 'tasks.py']:
        path = config.project_root / filename
        if path.exists():
            key_files.append({
                'name': filename,
                'path': get_relative_path(path),
                'size': path.stat().st_size
            })
    
    info['key_files'] = key_files
    
    # Get file lists
    info['python_files'] = find_python_files()
    info['test_files'] = find_test_files()
    
    # Add total count to file_counts
    info['file_counts']['total'] = sum(file_counts.values())
    
    # Calculate total lines of code
    total_lines = 0
    for file_info in info['python_files']:
        try:
            file_path = config.project_root / file_info['path']
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    total_lines += len(f.readlines())
        except Exception:
            pass  # Skip files that can't be read
    
    info['total_lines'] = total_lines
    
    # Configuration information
    info['configuration'] = {
        'max_file_size': config.max_file_size,
        'max_directory_depth': config.max_directory_depth,
        'python_extensions': list(config.python_extensions),
        'text_extensions': list(config.text_extensions),
        'ignore_dirs': list(config.ignore_dirs),
        'ignore_files': list(config.ignore_files),
        'debug': config.debug,
        'log_level': config.log_level
    }
    
    return info 