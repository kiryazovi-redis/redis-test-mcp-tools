"""
Security tests for the MCP server tools

Tests for path injection prevention, access control, and other security vulnerabilities.
"""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch
import sys

# Add the parent directory to the path to import modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from redis_test_mcp_tools.tools.file_tools import find_python_files, read_file_content, get_directory_structure
from redis_test_mcp_tools.tools.test_tools import analyze_test_files


class TestPathSecurity:
    """Test path security and injection prevention"""
    
    def test_path_injection_prevention_dots(self, temp_project_dir):
        """Test that path traversal with .. is prevented"""
        with patch('redis_test_mcp_tools.config.config.project_root', temp_project_dir):
            # Try to access parent directory
            malicious_paths = [
                "../../../etc/passwd",
                "..\\..\\..\\windows\\system32\\config\\sam",
                "tests/../../../etc/passwd",
                "tests\\..\\..\\..\\windows\\system32",
                "../../..",
                "../",
                "./../..",
            ]
            
            for malicious_path in malicious_paths:
                # Test file reading
                result = read_file_content(malicious_path)
                assert 'error' in result, f"Path injection should be blocked for: {malicious_path}"
                
                # Test directory structure
                result = get_directory_structure(Path(malicious_path))
                assert result is None or 'error' in str(result), f"Directory access should be blocked for: {malicious_path}"
    
    def test_path_injection_prevention_absolute_paths(self, temp_project_dir):
        """Test that absolute paths outside project are prevented"""
        with patch('redis_test_mcp_tools.config.config.project_root', temp_project_dir):
            malicious_paths = [
                "/etc/passwd",
                "/root/.ssh/id_rsa",
                "C:\\Windows\\System32\\config\\SAM",
                "C:\\Users\\Administrator\\Desktop",
                "/var/log/auth.log",
                "/proc/self/environ",
            ]
            
            for malicious_path in malicious_paths:
                result = read_file_content(malicious_path)
                assert 'error' in result, f"Absolute path access should be blocked for: {malicious_path}"
    
    def test_special_characters_in_paths(self, temp_project_dir):
        """Test handling of special characters in file paths"""
        with patch('redis_test_mcp_tools.config.config.project_root', temp_project_dir):
            special_chars = [
                "file with spaces.py",
                "file'with'quotes.py", 
                'file"with"double"quotes.py',
                "file;with;semicolons.py",
                "file&with&ampersands.py",
                "file|with|pipes.py",
                "file$(command).py",
                "file`command`.py",
                "file\x00null.py",  # null byte
                "file\rwith\rcarriage.py",
                "file\nwith\nnewlines.py",
            ]
            
            for special_path in special_chars:
                # Should handle gracefully without crashing
                result = read_file_content(special_path)
                assert isinstance(result, dict), f"Should return dict for special path: {special_path}"
                # Should either succeed or fail gracefully with error
                assert 'content' in result or 'error' in result, f"Should have content or error for: {special_path}"
    
    def test_unicode_filename_handling(self, temp_project_dir):
        """Test handling of unicode characters in filenames"""
        # Create files with unicode names
        unicode_files = [
            "测试文件.py",  # Chinese
            "тест_файл.py",  # Cyrillic
            "αρχείο_δοκιμής.py",  # Greek
            "файл_тест.py",  # Russian
            "ファイル.py",  # Japanese
            "🚀_rocket_file.py",  # Emoji
            "café_résumé.py",  # Accented characters
        ]
        
        for unicode_file in unicode_files:
            file_path = temp_project_dir / unicode_file
            try:
                file_path.write_text("# Unicode test file\ndef hello():\n    pass\n", encoding='utf-8')
            except (OSError, UnicodeError):
                # Skip if filesystem doesn't support this filename
                continue
                
        with patch('redis_test_mcp_tools.config.config.project_root', temp_project_dir):
            # Should not crash when encountering unicode filenames
            result = find_python_files()
            assert isinstance(result, list), "Should return list even with unicode files"
            
            for unicode_file in unicode_files:
                if (temp_project_dir / unicode_file).exists():
                    content_result = read_file_content(unicode_file)
                    assert isinstance(content_result, dict), f"Should handle unicode file: {unicode_file}"
    
    def test_very_long_path_handling(self, temp_project_dir):
        """Test handling of very long file paths"""
        # Create a deeply nested directory structure
        long_path = temp_project_dir
        for i in range(50):  # Create deep nesting
            long_path = long_path / f"very_long_directory_name_{i:03d}"
            if len(str(long_path)) > 250:  # Stop before hitting OS limits
                break
        
        try:
            long_path.mkdir(parents=True, exist_ok=True)
            long_file = long_path / "test_file.py"
            long_file.write_text("def test(): pass")
        except OSError:
            # Skip test if filesystem doesn't support long paths
            return
            
        with patch('redis_test_mcp_tools.config.config.project_root', temp_project_dir):
            # Should handle long paths gracefully
            result = find_python_files()
            assert isinstance(result, list), "Should return list even with long paths"
            
            # Test reading the deeply nested file
            relative_path = str(long_file.relative_to(temp_project_dir))
            content_result = read_file_content(relative_path)
            assert isinstance(content_result, dict), "Should handle long paths"


class TestAccessControl:
    """Test access control and permission handling"""
    
    def test_unreadable_file_handling(self, temp_project_dir):
        """Test handling of files with restricted permissions"""
        test_file = temp_project_dir / "restricted.py"
        test_file.write_text("def secret(): pass")
        
        try:
            # Make file unreadable (Unix-like systems)
            test_file.chmod(0o000)
            
            with patch('redis_test_mcp_tools.config.config.project_root', temp_project_dir):
                result = read_file_content("restricted.py")
                assert 'error' in result, "Should report error for unreadable file"
                assert 'permission' in result['error'].lower() or 'access' in result['error'].lower()
                
        except (OSError, PermissionError):
            # Skip on systems where chmod doesn't work as expected
            pass
        finally:
            # Restore permissions for cleanup
            try:
                test_file.chmod(0o644)
            except (OSError, PermissionError):
                pass
    
    def test_directory_boundary_enforcement(self, temp_project_dir):
        """Test that operations stay within project boundaries"""
        # Create a file outside project directory
        with tempfile.TemporaryDirectory() as outside_dir:
            outside_file = Path(outside_dir) / "outside.py"
            outside_file.write_text("def outside(): pass")
            
            with patch('redis_test_mcp_tools.config.config.project_root', temp_project_dir):
                # Try to access file outside project
                result = read_file_content(str(outside_file))
                assert 'error' in result, "Should not access files outside project"
                
                # Try with relative path to outside
                relative_outside = Path("..") / outside_file.name
                result = read_file_content(str(relative_outside))
                assert 'error' in result, "Should not access files outside project via relative path"


class TestEncodingRobustness:
    """Test handling of various file encodings"""
    
    def test_different_encodings(self, temp_project_dir):
        """Test handling of files with different encodings"""
        encodings_to_test = [
            ('utf-8', '# UTF-8 file with unicode: café résumé 测试'),
            ('latin-1', '# Latin-1 file with accents: café résumé'),
            ('cp1252', '# Windows-1252 encoding test'),
        ]
        
        for encoding, content in encodings_to_test:
            test_file = temp_project_dir / f"test_{encoding}.py"
            try:
                test_file.write_text(content + "\ndef test(): pass\n", encoding=encoding)
            except UnicodeEncodeError:
                # Skip if content can't be encoded in this encoding
                continue
                
            with patch('redis_test_mcp_tools.config.config.project_root', temp_project_dir):
                result = read_file_content(f"test_{encoding}.py")
                assert isinstance(result, dict), f"Should handle {encoding} encoding"
                # Should either succeed or fail gracefully
                assert 'content' in result or 'error' in result, f"Should process {encoding} file"
    
    def test_binary_file_detection(self, temp_project_dir):
        """Test that binary files are properly detected and rejected"""
        # Create a binary file with .py extension
        binary_file = temp_project_dir / "binary.py"
        binary_content = b'\x89\x50\x4E\x47\x0D\x0A\x1A\x0A'  # PNG header
        binary_file.write_bytes(binary_content)
        
        with patch('redis_test_mcp_tools.config.config.project_root', temp_project_dir):
            result = read_file_content("binary.py")
            assert 'error' in result, "Should detect and reject binary files"
            assert 'binary' in result['error'].lower() or 'text' in result['error'].lower()
    
    def test_malformed_unicode(self, temp_project_dir):
        """Test handling of files with malformed unicode"""
        malformed_file = temp_project_dir / "malformed.py"
        # Write invalid UTF-8 sequence
        malformed_file.write_bytes(b'# Test file\ndef test():\n    \xff\xfe invalid unicode\n    pass')
        
        with patch('redis_test_mcp_tools.config.config.project_root', temp_project_dir):
            result = read_file_content("malformed.py")
            assert isinstance(result, dict), "Should handle malformed unicode gracefully"
            # Should either decode with replacement chars or report encoding error
            assert 'content' in result or 'error' in result, "Should process malformed unicode file" 