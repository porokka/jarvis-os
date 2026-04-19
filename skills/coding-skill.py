"""
JARVIS Coding Skill — File, Git, and PTY operations.

Provides file system operations, git commands, and terminal execution
with proper PTY support for interactive commands.
"""

import os
import subprocess
import json
import pty
import select
import tty
import termios
from pathlib import Path
from typing import Dict, List, Optional

SKILL_NAME = "coding"
SKILL_DESCRIPTION = "File system, Git, and terminal operations with PTY support"

# -- Config --
CONFIG_PATH = Path(__file__).parent.parent / "config" / "coding.json"
CONFIG = {}

def init():
    """Initialize coding skill with configuration."""
    global CONFIG
    try:
        if CONFIG_PATH.exists():
            CONFIG = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        print(f"[CODING] Skill initialized with config: {CONFIG}")
    except Exception as e:
        print(f"[CODING] Config error: {e}")

# -- File Operations --
def read_file(filepath: str) -> str:
    """Read content from a file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {e}"

def edit_file(filepath: str, old_content: str, new_content: str) -> str:
    """Edit a file by replacing old content with new content."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            current_content = f.read()

        if old_content not in current_content:
            return f"Error: Could not find the specified content in {filepath}"

        new_full_content = current_content.replace(old_content, new_content)
        with open(filepath, 'w', encoding=' 'utf-8') as f:
            f.write(new_full_content)
        return f"Successfully edited {filepath}"
    except Exception as e:
        return f"Error editing file: {e}"

def list_files(directory: str = ".") -> str:
    """List files in a directory."""
    try:
        files = os.listdir(directory)
        return f"Files in {directory}: {', '.join(files)}"
    except Exception as e:
        return f"Error listing files: {e}"

def create_directory(directory: str) -> str:
    """Create a directory."""
    try:
        os.makedirs(directory, exist_ok=True)
        return f"Successfully created directory: {directory}"
    except Exception as e:
        return f"Error creating directory: {e}"

# -- Git Operations --
def git_status() -> str:
    """Get git status."""
    try:
        result = subprocess.run(['git', 'status', '--porcelain'],
                              capture_output=True, text=True, check=True)
        return f"Git status:\n{result.stdout}"
    except subprocess.CalledProcessError as e:
        return f"Git error: {e.stderr}"

def git_commit(message: str) -> str:
    """Commit changes with message."""
    try:
        subprocess.run(['git', 'add', '.'], check=True)
        result = subprocess.run(['git', 'commit', '-m', message],
                              capture_output=True, text=True, check=True)
        return f"Committed: {message}\n{result.stdout}"
    except subprocess.CalledProcessError as e:
        return f"Git commit error: {e.stderr}"

def git_pull() -> str:
    """Pull latest changes."""
    try:
        result = subprocess.run(['git', 'pull'],
                              capture_output=True, text=True, check=True)
        return f"Git pull result:\n{result.stdout}"
    except subprocess.CalledProcessError as e:
        return f"Git pull error: {e.stderr}"

def git_push() -> str:
    """Push changes."""
    try:
        result = subprocess.run(['git', 'push'],
                              capture_output=True, text=True, check=True)
        return f"Git push result:\n{result.stdout}"
    except subprocess.CalledProcessError as e:
        return f"Git push error: {e.stderr}"

def git_clone(repo_url: str, directory: str) -> str:
    """Clone a git repository."""
    try:
        result = subprocess.run(['git', 'clone', repo_url, directory],
                              capture_output=True, text=True, check=True)
        return f"Git clone result:\n{result.stdout}"
    except subprocess.CalledProcessError as e:
        return f"Git clone error: {e.stderr}"

# -- PTY Terminal Operations --
def execute_command_pty(command: str) -> str:
    """Execute a command with PTY support for interactive commands."""
    try:
        # Create PTY pair
        master, slave = pty.openpty()

        # Set up the command
        process = subprocess.Popen(
            command,
            shell=True,
            stdout=slave,
            stderr=slave,
            stdin=slave,
            close_fds=True
        )

        # Close slave side in parent
        os.close(slave)

        # Read output
        output = ""
        while True:
            # Check if process is still running
            if process.poll() is not None:
                break

            # Read available data
            ready, _, _ = select.select([master], [], [], 0.1)
            if ready:
                try:
                    data = os.read(master, 1024)
                    if data:
                        output += data.decode('utf-8', errors='replace')
                except Exception:
                    break

        # Get final output
        if process.poll() is None:
            process.wait()

        os.close(master)
        return f"Command output:\n{output}"

    except Exception as e:
        return f"PTY command error: {e}"

def execute_command_simple(command: str) -> str:
    """Execute a simple command without PTY."""
    try:
        result = subprocess.run(command, shell=True,
                              capture_output=True, text=True, check=True)
        return f"Command result:\n{result.stdout}"
    except subprocess.CalledProcessError as e:
        return f"Command failed: {e.stderr}"

# -- Code Analysis --
def analyze_code(filepath: str) -> str:
    """Analyze code file for basic structure."""
    try:
        with open(filepath, 'r') as f:
            content = f.read()

        lines = content.split('\n')
        line_count = len(lines)
        char_count = len(content)

        # Simple analysis
        imports = [line for line in lines if line.startswith('import ') or line.startswith('from ')]
        functions = [line for line in lines if line.startswith('def ')]
        classes = [line for line in lines if line.startswith('class ')]

        analysis = f"""
Code Analysis for {filepath}:
- Lines: {line_count}
- Characters: {char_count}
- Imports: {len(imports)}
- Functions: {len(functions)}
- Classes: {len(classes)}

Imports:
{chr(10).join(imports) if imports else 'None'}

Functions:
{chr(10).join(functions) if functions else 'None'}

Classes:
{chr(10).join(classes) if classes else 'None'}
        """
        return analysis.strip()
    except Exception as e:
        return f"Error analyzing code: {e}"

# -- Tool Definitions --
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read content from a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "Path to the file to read"
                    }
                },
                "required": ["filepath"]
            }
        }
    },
    {
                "type": "function",
                "function": {
                    "name": "edit_file",
                    "description": "Edit a file by replacing old content with new content",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "filepath": {
                                "type": "string",
                                "description": "Path to the file to edit"
                            },
                            "old_content": {
                                "type": "string",
                                "description": "The content to be replaced"
                            },
                            "new_content": {
                                "type": "string",
                                "description": "The new content to insert"
                            }
                        },
                        "required": ["filepath", "old_content", "new_content"]
                    }
                }
            },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files in a directory",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {
                        "type": "string",
                        "description": "Directory to list files in (default: current directory)"
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_directory",
            "description": "Create a directory",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {
                        "type": "string",
                        "description": "Directory to create"
                    }
                },
                "required": ["directory"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "Get git repository status",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_commit",
            "description": "Commit changes to git repository",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "Commit message"
                    }
                },
                "required": ["message"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_pull",
            "description": "Pull latest changes from remote repository",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_push",
            "description": "Push changes to remote repository",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "execute_command_pty",
            "description": "Execute a command with PTY support for interactive commands",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Command to execute with PTY support"
                    }
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "execute_command_simple",
            "description": "Execute a simple command without PTY",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Simple command to execute"
                    }
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_code",
            "description": "Analyze code file for structure and content",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "Path to the code file to analyze"
                    }
                },
                "required": ["filepath"]
            }
        }
    }
]

TOOL_MAP = {
    "read_file": read_file,
    "write_file": write_file,
    "edit_file": edit_file,
    "list_files": list_files,
    "create_directory": create_directory,
    "create_directory": create_directory,
    "git_status": git_status,
    "git_commit": git_commit,
    "git_pull": git_pull,
    "git_push": git_push,
    "execute_command_pty": execute_command_pty,
    "execute_command_simple": execute_command_simple,
    "analyze_code": analyze_code
}

KEYWORDS = {
    "read_file": ["read file", "file content", "open file", "view file"],
    "write_file": ["write file", "save file", "create file", "edit file"],
    "list_files": ["list files", "directory listing", "show files", "browse directory"],
    "create_directory": ["create directory", "make folder", "new directory"],
    "git_status": ["git status", "repository status", "git check", "check git"],
    "git_commit": ["git commit", "commit changes", "save changes", "git save"],
    "git_pull": ["git pull", "pull changes", "update repository", "sync repository"],
    "git_push": ["git push", "push changes", "upload repository", "publish changes"],
    "execute_command_pty": ["run command", "execute", "shell command", "terminal"],
    "execute_command_simple": ["run simple command", "execute simple", "shell simple"],
    "analyze_code": ["analyze code", "code analysis", "check code", "review code"]
}