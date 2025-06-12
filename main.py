#!/usr/bin/env python3

# =============================================================================
# Mistral Assistant - Enhanced Version
# Added fuzzy matching for file paths and code edits
# Added bash support and OS awareness
# =============================================================================

#------------------------------------------------------------------------------
# 1. IMPORTS (Organized by category)
# -----------------------------------------------------------------------------

# Standard library imports
import os
import sys
import json
import re
import time
import subprocess
import platform
from textwrap import dedent
from typing import List, Dict, Any, Optional, Tuple, Union

# Third-party imports
from cerebras.cloud.sdk import Cerebras
from pydantic import BaseModel
from dotenv import load_dotenv
from pathlib import Path

# Rich console imports
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.style import Style

# Prompt toolkit imports
from prompt_toolkit import PromptSession
from prompt_toolkit.styles import Style as PromptStyle

# Fuzzy matching imports
try:
    from thefuzz import fuzz, process as fuzzy_process
    FUZZY_AVAILABLE = True
except ImportError:
    FUZZY_AVAILABLE = False
    print("Warning: thefuzz not available. Install with: pip install thefuzz python-levenshtein")
    print("Falling back to exact matching only.")

# -----------------------------------------------------------------------------
# 2. CONSTANTS (NON-CONFIGURABLE)
# -----------------------------------------------------------------------------

# Command prefixes
ADD_COMMAND_PREFIX: str = "/add "
COMMIT_COMMAND_PREFIX: str = "/git commit "
GIT_BRANCH_COMMAND_PREFIX: str = "/git branch "

# -----------------------------------------------------------------------------
# 3. GLOBAL STATE MANAGEMENT
# -----------------------------------------------------------------------------

# Initialize Rich console and prompt session
console = Console()
prompt_session = PromptSession(
    style=PromptStyle.from_dict({
        'prompt': '#0066ff bold',
        'completion-menu.completion': 'bg:#1e3a8a fg:#ffffff',
        'completion-menu.completion.current': 'bg:#3b82f6 fg:#ffffff bold',
    })
)

# Global base directory for operations (default: current working directory)
base_dir: Path = Path.cwd()

# Git context state
git_context: Dict[str, Any] = {
    'enabled': False,
    'skip_staging': False,
    'branch': None
}

# Model context state (will be initialized after config load)
model_context: Dict[str, Any] = {}

# Security settings (will be loaded from config)
security_context: Dict[str, Any] = {}

# OS information
os_info: Dict[str, Any] = {
    'system': platform.system(),
    'release': platform.release(),
    'version': platform.version(),
    'machine': platform.machine(),
    'processor': platform.processor(),
    'python_version': platform.python_version(),
    'is_windows': platform.system() == "Windows",
    'is_mac': platform.system() == "Darwin",
    'is_linux': platform.system() == "Linux",
    'shell_available': {
        'bash': False,
        'powershell': False,
        'zsh': False,
        'cmd': False
    }
}

# Initialize Cerebras client
load_dotenv()
client = Cerebras(
    api_key=os.getenv("CEREBRAS_API_KEY")
)

# Load .env from the same directory as main.py
load_dotenv(dotenv_path=Path(__file__).parent / ".env")

# -----------------------------------------------------------------------------
# 4. TYPE DEFINITIONS & PYDANTIC MODELS
# -----------------------------------------------------------------------------

class FileToCreate(BaseModel):
    path: str
    content: str

class FileToEdit(BaseModel):
    path: str
    original_snippet: str
    new_snippet: str

# -----------------------------------------------------------------------------
# 5. COMMAND REGISTRY CLASS
# -----------------------------------------------------------------------------

class CommandRegistry:
    """Handles all user commands like /add, /git commit, etc."""
    
    def __init__(self, assistant: 'MistralAssistant'):
        self.assistant = assistant
        self.commands = {
            "/add": self._handle_add,
            "/git add": self._handle_git_add,
            "/git commit": self._handle_commit,
            "/git": self._handle_git,
            "/git-info": self._handle_git,  # Route git-info to same handler
            "/clear": self._handle_clear,
            "/clear-context": self._handle_clear,  # Route clear-context to same handler
            "/context": self._handle_context,
            "/folder": self._handle_folder,
            "/exit": self._handle_exit,
            "/quit": self._handle_exit,  # Route quit to same handler as exit
            "/help": self._handle_help,
            "/r": self._handle_r1,  # Single /r command for reasoner
            "/reasoner": self._handle_reasoner,
            "/os": self._handle_os,  # New OS info command
        }
    
    def handle_command(self, user_input: str) -> bool:
        """
        Handle user command, checking for the most specific command first.
        Returns True if a command was processed.
        """
        clean_input = user_input.strip()
        if not clean_input:
            return False

        # Sort commands by length in descending order to match more specific commands first.
        # e.g., "/git commit" will be checked before "/git".
        sorted_commands = sorted(self.commands.keys(), key=len, reverse=True)
        
        for command_key in sorted_commands:
            # Check if the user input starts with the command key, followed by either
            # a space (indicating arguments) or the end of the string (an exact match).
            # This prevents "/git-info" from partially matching "/git".
            if clean_input.startswith(command_key) and (len(clean_input) == len(command_key) or clean_input[len(command_key)].isspace()):
                handler = self.commands[command_key]
                # We found the correct, most-specific handler. Call it and stop.
                return handler(user_input)
                
        return False
    
    def _handle_add(self, user_input: str) -> bool:
        """Handle /add command - delegate to existing function."""
        return try_handle_add_command(user_input)
    
    def _handle_git_add(self, user_input: str) -> bool:
        """Handle /git add command - delegate to existing function."""
        return try_handle_git_add_command(user_input)
    
    def _handle_commit(self, user_input: str) -> bool:
        """Handle /git commit command - delegate to existing function.""" 
        return try_handle_commit_command(user_input)
    
    def _handle_git(self, user_input: str) -> bool:
        """Handle /git command - delegate to existing function."""
        # First try the main git command handler (for /git status, /git init, /git branch)
        if try_handle_git_command(user_input):
            return True
        # Fall back to git info command (for /git-info)
        return try_handle_git_info_command(user_input)
    
    def _handle_clear(self, user_input: str) -> bool:
        """Handle /clear command - delegate to existing function."""
        if user_input.strip() == "/clear-context":
            return try_handle_clear_context_command(user_input)
        else:
            return try_handle_clear_command(user_input)
    
    def _handle_context(self, user_input: str) -> bool:
        """Handle /context command - delegate to existing function."""
        return try_handle_context_command(user_input)
    
    def _handle_folder(self, user_input: str) -> bool:
        """Handle /folder command - delegate to existing function."""
        return try_handle_folder_command(user_input)
    
    def _handle_exit(self, user_input: str) -> bool:
        """Handle /exit command - delegate to existing function."""
        return try_handle_exit_command(user_input)
    
    def _handle_help(self, user_input: str) -> bool:
        """Handle /help command - delegate to existing function."""
        return try_handle_help_command(user_input)
    
    def _handle_r1(self, user_input: str) -> bool:
        """Handle /r command - delegate to existing function."""
        return try_handle_r1_command(user_input)
    
    def _handle_reasoner(self, user_input: str) -> bool:
        """Handle /reasoner command - delegate to existing function."""
        return try_handle_reasoner_command(user_input)
    
    def _handle_os(self, user_input: str) -> bool:
        """Handle /os command - show OS information."""
        return try_handle_os_command(user_input)

# -----------------------------------------------------------------------------
# 6. MISTRAL ASSISTANT CLASS
# -----------------------------------------------------------------------------

class MistralAssistant:
    """Main assistant class that encapsulates state and core functionality."""
    
    def __init__(self):
        # State management
        self.conversation_history: List[Dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]
        self.git_context: Dict[str, Any] = git_context.copy()
        self.model_context: Dict[str, Any] = {
            'current_model': DEFAULT_MODEL,
            'is_reasoner': False
        }
        self.security_context: Dict[str, Any] = DEFAULT_SECURITY_CONTEXT.copy()
        self.base_dir: Path = Path.cwd()
        
        # Initialize Mistral client
        #self.client = Mistral(api_key=os.getenv("MISTRAL_API_KEY"))
        
        # Initialize command registry
        self.command_registry = CommandRegistry(self)
    
    def process_user_input(self, user_input: str) -> bool:
        """Process user input, handling commands or adding to conversation."""
        if not user_input.strip():
            return False
        
        # Try to handle as command first
        if self.command_registry.handle_command(user_input):
            return True
        
        # Add to conversation history if not a command
        self.conversation_history.append({"role": "user", "content": user_input})
        return False
    
    def get_context_usage_info(self) -> Dict[str, Any]:
        """Get comprehensive context usage information."""
        total_tokens, breakdown = estimate_token_usage(self.conversation_history)
        file_contexts = sum(1 for msg in self.conversation_history 
                          if msg["role"] == "system" and "User added file" in msg["content"])
        
        return {
            "total_messages": len(self.conversation_history),
            "estimated_tokens": total_tokens,
            "token_usage_percent": (total_tokens / ESTIMATED_MAX_TOKENS) * 100,
            "file_contexts": file_contexts,
            "token_breakdown": breakdown,
            "approaching_limit": total_tokens > (ESTIMATED_MAX_TOKENS * CONTEXT_WARNING_THRESHOLD),
            "critical_limit": total_tokens > (ESTIMATED_MAX_TOKENS * AGGRESSIVE_TRUNCATION_THRESHOLD)
        }
    
    def process_streaming_response(self) -> Tuple[str, List[Dict[str, Any]]]:
        """Process streaming response from the Cerebras API."""
        current_model = self.model_context['current_model']
        model_name = "Magistral" if self.model_context['is_reasoner'] else "Mistral Medium"
        
        with console.status(f"[bold yellow]{model_name} is thinking...[/bold yellow]", spinner="dots"):
            stream = client.chat.completions.create(
                messages=self.conversation_history,
                model=current_model,
                stream=True,
                max_completion_tokens=5000,
                temperature=0.7,
                top_p=1
            )
        
        full_response_content = ""
        accumulated_tool_calls = []
        
        for chunk in stream:
            content = chunk.choices[0].delta.content or ""
            # Strip <think> and </think> tags from the content
            content = content.replace("<think>", "").replace("</think>", "")
            console.print(content, end="", style="bright_magenta")
            full_response_content += content
        
        return full_response_content, accumulated_tool_calls
    
    def main_loop(self) -> None:
        """Main application loop."""
        while True:
            try:
                # Update global state for compatibility with existing functions
                global conversation_history, git_context, model_context, security_context, base_dir
                conversation_history = self.conversation_history
                git_context = self.git_context
                model_context = self.model_context
                security_context = self.security_context
                base_dir = self.base_dir
                
                # Get user input
                prompt_indicator = get_prompt_indicator()
                user_input = prompt_session.prompt(f"{prompt_indicator} You: ")
                
                # Process input (commands or conversation)
                if self.process_user_input(user_input):
                    # Sync back any changes made by commands to global state
                    self.conversation_history = conversation_history
                    self.git_context = git_context
                    self.model_context = model_context
                    self.security_context = security_context
                    self.base_dir = base_dir
                    continue
                
                # Check context usage and warn if necessary
                context_info = self.get_context_usage_info()
                if context_info["critical_limit"] and len(self.conversation_history) % 10 == 0:
                    console.print(f"[red]⚠ Context critical: {context_info['token_usage_percent']:.1f}% used. Consider /clear-context or /context for details.[/red]")
                elif context_info["approaching_limit"] and len(self.conversation_history) % 20 == 0:
                    console.print(f"[yellow]⚠ Context high: {context_info['token_usage_percent']:.1f}% used. Use /context for details.[/yellow]")
                
                # Process streaming response
                response_content, tool_calls = self.process_streaming_response()
                console.print()  # New line after streaming
                
                # Build assistant message
                assistant_message = {"role": "assistant", "content": response_content}
                valid_tool_calls = validate_tool_calls(tool_calls)
                if valid_tool_calls:
                    assistant_message["tool_calls"] = valid_tool_calls
                
                self.conversation_history.append(assistant_message)
                
                # Handle tool calls
                if valid_tool_calls:
                    for tool_call in valid_tool_calls:
                        try:
                            result = execute_function_call_dict(tool_call)
                            tool_response = {
                                "role": "tool",
                                "content": str(result),
                                "tool_call_id": tool_call["id"]
                            }
                            self.conversation_history.append(tool_response)
                        except Exception as e:
                            console.print(f"[red]✗ Tool call error: {e}[/red]")
                            tool_response = {
                                "role": "tool", 
                                "content": f"Error: {e}",
                                "tool_call_id": tool_call["id"]
                            }
                            self.conversation_history.append(tool_response)
                    
                    # After tool calls, handle follow-up responses with loop prevention
                    max_continuation_rounds = 5
                    current_round = 0
                    
                    while current_round < max_continuation_rounds:
                        current_round += 1
                        
                        try:
                            follow_up_content, follow_up_tool_calls = self.process_streaming_response()
                            console.print()  # New line after streaming
                            
                            # Add the follow-up assistant message
                            follow_up_message = {"role": "assistant", "content": follow_up_content}
                            
                            # Check if there are more tool calls to execute
                            valid_follow_up_calls = validate_tool_calls(follow_up_tool_calls) if follow_up_tool_calls else []
                            
                            if valid_follow_up_calls:
                                follow_up_message["tool_calls"] = valid_follow_up_calls
                                self.conversation_history.append(follow_up_message)
                                
                                # Execute the additional tool calls
                                for tool_call in valid_follow_up_calls:
                                    try:
                                        result = execute_function_call_dict(tool_call)
                                        tool_response = {
                                            "role": "tool",
                                            "content": str(result),
                                            "tool_call_id": tool_call["id"]
                                        }
                                        self.conversation_history.append(tool_response)
                                    except Exception as e:
                                        console.print(f"[red]✗ Follow-up tool call error: {e}[/red]")
                                        tool_response = {
                                            "role": "tool",
                                            "content": f"Error: {e}",
                                            "tool_call_id": tool_call["id"]
                                        }
                                        self.conversation_history.append(tool_response)
                                
                                # Continue the loop to let assistant process these new results
                                continue
                            else:
                                # No more tool calls, add the final response and break
                                self.conversation_history.append(follow_up_message)
                                break
                                
                        except Exception as e:
                            console.print(f"[red]✗ Error getting assistant follow-up: {e}[/red]")
                            # Add a simple acknowledgment message to maintain conversation flow
                            self.conversation_history.append({
                                "role": "assistant", 
                                "content": "Tool execution completed."
                            })
                            break
                    
                    # If we hit the max rounds, warn about it
                    if current_round >= max_continuation_rounds:
                        console.print(f"[yellow]⚠ Reached maximum continuation rounds ({max_continuation_rounds}). Stopping additional tool calls.[/yellow]")
                
                # Smart truncation
                self.conversation_history = smart_truncate_history(self.conversation_history)
                
            except KeyboardInterrupt:
                console.print("\n[yellow]⚠ Interrupted. Ctrl+D or /exit to quit.[/yellow]")
            except EOFError:
                console.print("[blue]👋 Goodbye! (EOF)[/blue]")
                sys.exit(0)
            except Exception as e:
                console.print(f"\n[red]✗ Unexpected error: {e}[/red]")
                console.print_exception()

# Function calling tools definition
tools: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the content of a single file from the filesystem",
            "parameters": {
                "type": "object",
                "properties": {"file_path": {"type": "string", "description": "The path to the file to read"}},
                "required": ["file_path"]
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_multiple_files",
            "description": "Read the content of multiple files",
            "parameters": {
                "type": "object",
                "properties": {"file_paths": {"type": "array", "items": {"type": "string"}, "description": "Array of file paths to read"}},
                "required": ["file_paths"]
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_file",
            "description": "Create or overwrite a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path for the file"},
                    "content": {"type": "string", "description": "Content for the file"}
                },
                "required": ["file_path", "content"]
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_multiple_files",
            "description": "Create multiple files",
            "parameters": {
                "type": "object",
                "properties": {
                    "files": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                            "required": ["path", "content"]
                        },
                        "description": "Array of files to create (path, content)",
                    }
                },
                "required": ["files"]
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Edit a file by replacing a snippet (supports fuzzy matching)",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to the file"},
                    "original_snippet": {"type": "string", "description": "Snippet to replace (supports fuzzy matching)"},
                    "new_snippet": {"type": "string", "description": "Replacement snippet"}
                },
                "required": ["file_path", "original_snippet", "new_snippet"]
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_init",
            "description": "Initialize a new Git repository.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_commit",
            "description": "Commit staged changes with a message.",
            "parameters": {
                "type": "object",
                "properties": {"message": {"type": "string", "description": "Commit message"}},
                "required": ["message"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_create_branch",
            "description": "Create and switch to a new Git branch.",
            "parameters": {
                "type": "object",
                "properties": {"branch_name": {"type": "string", "description": "Name of the new branch"}},
                "required": ["branch_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "Show current Git status.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_add",
            "description": "Stage files for commit.",
            "parameters": {
                "type": "object",
                "properties": {"file_paths": {"type": "array", "items": {"type": "string"}, "description": "Paths of files to stage"}},
                "required": ["file_paths"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_powershell",
            "description": "Run a PowerShell command with security confirmation (Windows/Cross-platform PowerShell Core).",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The PowerShell command to execute"
                    }
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_bash",
            "description": "Run a bash command with security confirmation (macOS/Linux/WSL).",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The bash command to execute"
                    }
                },
                "required": ["command"]
            }
        }
    }
]

# -----------------------------------------------------------------------------
# 7. CONFIGURATION LOADING
# -----------------------------------------------------------------------------

def load_config() -> Dict[str, Any]:
    """Load configuration from config.json file."""
    try:
        config_path = Path(__file__).parent / "config.json"
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        console.print(f"[yellow]⚠ Could not load config.json: {e}. Using defaults.[/yellow]")
        return {}

def load_system_prompt() -> str:
    """Load system prompt from external file."""
    try:
        prompt_path = Path(__file__).parent / "system_prompt.txt"
        with open(prompt_path, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except FileNotFoundError:
        console.print("[yellow]⚠ system_prompt.txt not found. Using embedded prompt.[/yellow]")
        return DEFAULT_SYSTEM_PROMPT

# Load configuration
config = load_config()

# Configuration with fallbacks
file_limits = config.get("file_limits", {})
MAX_FILES_IN_ADD_DIR = file_limits.get("max_files_in_add_dir", 1000)
MAX_FILE_SIZE_IN_ADD_DIR = file_limits.get("max_file_size_in_add_dir", 5_000_000)
MAX_FILE_CONTENT_SIZE_CREATE = file_limits.get("max_file_content_size_create", 5_000_000)
MAX_MULTIPLE_READ_SIZE = file_limits.get("max_multiple_read_size", 100_000)

fuzzy_config = config.get("fuzzy_matching", {})
MIN_FUZZY_SCORE = fuzzy_config.get("min_fuzzy_score", 80)
MIN_EDIT_SCORE = fuzzy_config.get("min_edit_score", 85)

conversation_config = config.get("conversation", {})
MAX_HISTORY_MESSAGES = conversation_config.get("max_history_messages", 50)
MAX_CONTEXT_FILES = conversation_config.get("max_context_files", 5)
ESTIMATED_MAX_TOKENS = conversation_config.get("estimated_max_tokens", 66000)
TOKENS_PER_MESSAGE_ESTIMATE = conversation_config.get("tokens_per_message_estimate", 200)
TOKENS_PER_FILE_KB = conversation_config.get("tokens_per_file_kb", 300)
CONTEXT_WARNING_THRESHOLD = conversation_config.get("context_warning_threshold", 0.8)
AGGRESSIVE_TRUNCATION_THRESHOLD = conversation_config.get("aggressive_truncation_threshold", 0.9)

model_config = config.get("models", {})
DEFAULT_MODEL = model_config.get("default_model", "mistral-large-2411")
REASONER_MODEL = model_config.get("reasoner_model", "magistral-medium-2506")

security_config = config.get("security", {})
DEFAULT_SECURITY_CONTEXT = {
    'require_powershell_confirmation': security_config.get("require_powershell_confirmation", True),
    'require_bash_confirmation': security_config.get("require_bash_confirmation", True)
}

# File exclusion patterns from config
EXCLUDED_FILES = set(config.get("excluded_files", [
    ".DS_Store", "Thumbs.db", ".gitignore", ".python-version", "uv.lock", 
    ".uv", "uvenv", ".uvenv", ".venv", "venv", "__pycache__", ".pytest_cache", 
    ".coverage", ".mypy_cache", "node_modules", "package-lock.json", "yarn.lock", 
    "pnpm-lock.yaml", ".next", ".nuxt", "dist", "build", ".cache", ".parcel-cache", 
    ".turbo", ".vercel", ".output", ".contentlayer", "out", "coverage", 
    ".nyc_output", "storybook-static", ".env", ".env.local", ".env.development", 
    ".env.production", ".git", ".svn", ".hg", "CVS"
]))

EXCLUDED_EXTENSIONS = set(config.get("excluded_extensions", [
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp", ".avif", 
    ".mp4", ".webm", ".mov", ".mp3", ".wav", ".ogg", ".zip", ".tar", 
    ".gz", ".7z", ".rar", ".exe", ".dll", ".so", ".dylib", ".bin", 
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".pyc", 
    ".pyo", ".pyd", ".egg", ".whl", ".uv", ".uvenv", ".db", ".sqlite", 
    ".sqlite3", ".log", ".idea", ".vscode", ".map", ".chunk.js", 
    ".chunk.css", ".min.js", ".min.css", ".bundle.js", ".bundle.css", 
    ".cache", ".tmp", ".temp", ".ttf", ".otf", ".woff", ".woff2", ".eot"
]))

# Default system prompt (fallback)
DEFAULT_SYSTEM_PROMPT: str = dedent(f"""
    You are an elite software engineer called Mistral Engineer with decades of experience across all programming domains.
    Your expertise spans system design, algorithms, testing, and best practices.
    You provide thoughtful, well-structured solutions while explaining your reasoning.

    **Current Environment:**
    - Operating System: {os_info['system']} {os_info['release']}
    - Machine: {os_info['machine']}
    - Python: {os_info['python_version']}

    Core capabilities:
    1. Code Analysis & Discussion
       - Analyze code with expert-level insight
       - Explain complex concepts clearly
       - Suggest optimizations and best practices
       - Debug issues with precision

    2. File Operations (via function calls):
       - read_file: Read a single file's content
       - read_multiple_files: Read multiple files at once (returns structured JSON)
       - create_file: Create or overwrite a single file
       - create_multiple_files: Create multiple files at once
       - edit_file: Make precise edits to existing files using fuzzy-matched snippet replacement

    3. Git Operations (via function calls):
       - git_init: Initialize a new Git repository in the current directory.
       - git_add: Stage specified file(s) for the next commit. Use this before git_commit.
       - git_commit: Commit staged changes with a message. Ensure files are staged first using git_add.
       - git_create_branch: Create and switch to a new Git branch.
       - git_status: Show the current Git status, useful for seeing what is staged or unstaged.

    4. System Operations (with security confirmation):
       - run_powershell: Execute PowerShell commands (Windows/Cross-platform PowerShell Core)
       - run_bash: Execute bash commands (macOS/Linux/WSL)
       
       Note: Choose the appropriate shell command based on the operating system:
       - On Windows: Prefer run_powershell
       - On macOS/Linux: Prefer run_bash
       - Both commands require user confirmation for security

    Guidelines:
    1. Provide natural, conversational responses explaining your reasoning
    2. Use function calls when you need to read or modify files, or interact with Git.
    3. For file operations:
       - The /add command and edit_file function now support fuzzy matching for more forgiving file operations
       - Always read files first before editing them to understand the context
       - The edit_file function will attempt fuzzy matching if exact snippets aren't found
       - Explain what changes you're making and why
       - Consider the impact of changes on the overall codebase
    4. For Git operations:
       - Use `git_add` to stage files before using `git_commit`.
       - Provide clear commit messages.
       - Check `git_status` if unsure about the state of the repository.
    5. For system commands:
       - Always consider the operating system when choosing between run_bash and run_powershell
       - Explain what the command does before executing
       - Use safe, non-destructive commands when possible
       - Be cautious with commands that modify system state
    6. Follow language-specific best practices
    7. Suggest tests or validation steps when appropriate
    8. Be thorough in your analysis and recommendations

    IMPORTANT: In your thinking process, if you realize that something requires a tool call, cut your thinking short and proceed directly to the tool call. Don't overthink - act efficiently when file operations are needed.

    Remember: You're a senior engineer - be thoughtful, precise, and explain your reasoning clearly.
""")

# Load the actual system prompt
SYSTEM_PROMPT: str = load_system_prompt()

# Initialize global contexts with config values
model_context.update({
    'current_model': DEFAULT_MODEL,
    'is_reasoner': False
})
security_context.update(DEFAULT_SECURITY_CONTEXT)

# Conversation history
conversation_history: List[Dict[str, Any]] = [
    {"role": "system", "content": SYSTEM_PROMPT}
]

# -----------------------------------------------------------------------------
# 8. NEW FUZZY MATCHING UTILITIES
# -----------------------------------------------------------------------------

def find_best_matching_file(root_dir: Path, user_path: str, min_score: int = MIN_FUZZY_SCORE) -> Optional[str]:
    """
    Find the best file match for a given user path within a directory.

    Args:
        root_dir: The directory to search within.
        user_path: The (potentially messy) path provided by the user.
        min_score: The minimum fuzzy match score to consider a match.

    Returns:
        The full, corrected path of the best match, or None if no good match is found.
    """
    if not FUZZY_AVAILABLE:
        return None
        
    best_match = None
    highest_score = 0
    
    # Use the filename from the user's path for matching
    user_filename = Path(user_path).name

    for dirpath, _, filenames in os.walk(root_dir):
        # Skip hidden directories and excluded patterns for efficiency
        if any(part in EXCLUDED_FILES or part.startswith('.') for part in Path(dirpath).parts):
            continue

        for filename in filenames:
            if filename in EXCLUDED_FILES or os.path.splitext(filename)[1] in EXCLUDED_EXTENSIONS:
                continue

            # Compare user's filename with actual filenames
            score = fuzz.ratio(user_filename.lower(), filename.lower())
            
            # Boost score for files in the immediate directory
            if Path(dirpath) == root_dir:
                score += 10

            if score > highest_score:
                highest_score = score
                best_match = os.path.join(dirpath, filename)

    if highest_score >= min_score:
        return str(Path(best_match).resolve())
    
    return None

def apply_fuzzy_diff_edit(path: str, original_snippet: str, new_snippet: str) -> None:
    """
    Apply a diff edit to a file by replacing original snippet with new snippet.
    Uses fuzzy matching to find the best location for the snippet.
    """
    normalized_path_str = normalize_path(path)
    content = ""
    try:
        content = read_local_file(normalized_path_str)
        
        # 1. First, try for an exact match for performance and accuracy
        if content.count(original_snippet) == 1:
            updated_content = content.replace(original_snippet, new_snippet, 1)
            create_file(normalized_path_str, updated_content)
            console.print(f"[bold blue]✓[/bold blue] Applied exact diff edit to '[bright_cyan]{normalized_path_str}[/bright_cyan]'")
            return

        # 2. If exact match fails, use fuzzy matching (if available)
        if not FUZZY_AVAILABLE:
            raise ValueError("Original snippet not found and fuzzy matching not available")
            
        console.print("[dim]Exact snippet not found. Trying fuzzy matching...[/dim]")

        # Create a list of "choices" to match against. These are overlapping chunks of the file.
        lines = content.split('\n')
        original_lines_count = len(original_snippet.split('\n'))
        
        # Create sliding window of text chunks
        choices = []
        for i in range(len(lines) - original_lines_count + 1):
            chunk = '\n'.join(lines[i:i+original_lines_count])
            choices.append(chunk)
        
        if not choices:
            raise ValueError("File content is too short to perform a fuzzy match.")

        # Find the best match
        best_match, score = fuzzy_process.extractOne(original_snippet, choices)

        if score < MIN_EDIT_SCORE:
            raise ValueError(f"Fuzzy match score ({score}) is below threshold ({MIN_EDIT_SCORE}). Snippet not found or too different.")

        # Ensure the best match is unique to avoid ambiguity
        if choices.count(best_match) > 1:
            raise ValueError(f"Ambiguous fuzzy edit: The best matching snippet appears multiple times in the file.")
        
        # Replace the best fuzzy match
        updated_content = content.replace(best_match, new_snippet, 1)
        create_file(normalized_path_str, updated_content)
        console.print(f"[bold blue]✓[/bold blue] Applied [bold]fuzzy[/bold] diff edit to '[bright_cyan]{normalized_path_str}[/bright_cyan]' (score: {score})")

    except FileNotFoundError:
        console.print(f"[bold red]✗[/bold red] File not found for diff: '[bright_cyan]{path}[/bright_cyan]'")
        raise
    except ValueError as e:
        console.print(f"[bold yellow]⚠[/bold yellow] {str(e)} in '[bright_cyan]{path}[/bright_cyan]'. No changes.")
        if "Original snippet not found" in str(e) or "Fuzzy match score" in str(e) or "Ambiguous edit" in str(e):
            console.print("\n[bold blue]Expected snippet:[/bold blue]")
            console.print(Panel(original_snippet, title="Expected", border_style="blue"))
            if content:
                console.print("\n[bold blue]Actual content (or relevant part):[/bold blue]")
                start_idx = max(0, content.find(original_snippet[:20]) - 100)
                end_idx = min(len(content), start_idx + len(original_snippet) + 200)
                display_snip = ("..." if start_idx > 0 else "") + content[start_idx:end_idx] + ("..." if end_idx < len(content) else "")
                console.print(Panel(display_snip or content, title="Actual", border_style="yellow"))
        raise

# -----------------------------------------------------------------------------
# 9. CORE UTILITY FUNCTIONS (Including new OS detection)
# -----------------------------------------------------------------------------

def detect_available_shells() -> None:
    """Detect which shells are available on the system."""
    global os_info
    
    # Check for bash
    try:
        result = subprocess.run(["bash", "--version"], capture_output=True, text=True, timeout=2)
        os_info['shell_available']['bash'] = result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        os_info['shell_available']['bash'] = False
    
    # Check for PowerShell (Windows PowerShell or PowerShell Core)
    for ps_cmd in ["powershell", "pwsh"]:
        try:
            result = subprocess.run([ps_cmd, "-Command", "$PSVersionTable.PSVersion"], 
                                  capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                os_info['shell_available']['powershell'] = True
                break
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    
    # Check for zsh (macOS default)
    try:
        result = subprocess.run(["zsh", "--version"], capture_output=True, text=True, timeout=2)
        os_info['shell_available']['zsh'] = result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        os_info['shell_available']['zsh'] = False
    
    # Check for cmd (Windows)
    if os_info['is_windows']:
        os_info['shell_available']['cmd'] = True

def estimate_token_usage(conversation_history: List[Dict[str, Any]]) -> Tuple[int, Dict[str, int]]:
    """
    Estimate token usage for the conversation history.
    
    Args:
        conversation_history: List of conversation messages
        
    Returns:
        Tuple of (total_estimated_tokens, breakdown_by_role)
    """
    token_breakdown = {"system": 0, "user": 0, "assistant": 0, "tool": 0}
    total_tokens = 0
    
    for msg in conversation_history:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        
        # Basic token estimation: roughly 4 characters per token for English text
        content_tokens = len(content) // 4
        
        # Add extra tokens for tool calls and structured data
        if msg.get("tool_calls"):
            content_tokens += len(str(msg["tool_calls"])) // 4
        if msg.get("tool_call_id"):
            content_tokens += 10  # Small overhead for tool metadata
            
        token_breakdown[role] = token_breakdown.get(role, 0) + content_tokens
        total_tokens += content_tokens
    
    return total_tokens, token_breakdown

def get_context_usage_info() -> Dict[str, Any]:
    """
    Get comprehensive context usage information.
    
    Returns:
        Dictionary with context usage statistics
    """
    total_tokens, breakdown = estimate_token_usage(conversation_history)
    file_contexts = sum(1 for msg in conversation_history if msg["role"] == "system" and "User added file" in msg["content"])
    
    return {
        "total_messages": len(conversation_history),
        "estimated_tokens": total_tokens,
        "token_usage_percent": (total_tokens / ESTIMATED_MAX_TOKENS) * 100,
        "file_contexts": file_contexts,
        "token_breakdown": breakdown,
        "approaching_limit": total_tokens > (ESTIMATED_MAX_TOKENS * CONTEXT_WARNING_THRESHOLD),
        "critical_limit": total_tokens > (ESTIMATED_MAX_TOKENS * AGGRESSIVE_TRUNCATION_THRESHOLD)
    }

def smart_truncate_history(conversation_history: List[Dict[str, Any]], max_messages: int = MAX_HISTORY_MESSAGES) -> List[Dict[str, Any]]:
    """
    Truncate conversation history while preserving tool call sequences and important context.
    Now uses token-based estimation for more intelligent truncation.
    
    Args:
        conversation_history: List of conversation messages
        max_messages: Maximum number of messages to keep (fallback limit)
        
    Returns:
        Truncated conversation history
    """
    # Get current context usage
    context_info = get_context_usage_info()
    current_tokens = context_info["estimated_tokens"]
    
    # If we're not approaching limits, use message-based truncation
    if current_tokens < (ESTIMATED_MAX_TOKENS * CONTEXT_WARNING_THRESHOLD) and len(conversation_history) <= max_messages:
        return conversation_history
    
    # Determine target token count based on current usage
    if context_info["critical_limit"]:
        target_tokens = int(ESTIMATED_MAX_TOKENS * 0.6)  # Aggressive reduction
        console.print(f"[yellow]⚠ Critical context limit reached. Aggressively truncating to ~{target_tokens} tokens.[/yellow]")
    elif context_info["approaching_limit"]:
        target_tokens = int(ESTIMATED_MAX_TOKENS * 0.7)  # Moderate reduction
        console.print(f"[yellow]⚠ Context limit approaching. Truncating to ~{target_tokens} tokens.[/yellow]")
    else:
        target_tokens = int(ESTIMATED_MAX_TOKENS * 0.8)  # Gentle reduction
    
    # Separate system messages from conversation messages
    system_messages: List[Dict[str, Any]] = []
    other_messages: List[Dict[str, Any]] = []
    
    for msg in conversation_history:
        if msg["role"] == "system":
            system_messages.append(msg)
        else:
            other_messages.append(msg)
    
    # Always keep the main system prompt
    essential_system = [system_messages[0]] if system_messages else []
    
    # Handle file context messages more intelligently
    file_contexts = [msg for msg in system_messages[1:] if "User added file" in msg["content"]]
    if file_contexts:
        # Keep most recent and smallest file contexts
        file_contexts_with_size = []
        for msg in file_contexts:
            content_size = len(msg["content"])
            file_contexts_with_size.append((msg, content_size))
        
        # Sort by size (smaller first) and recency (newer first)
        file_contexts_with_size.sort(key=lambda x: (x[1], -file_contexts.index(x[0])))
        
        # Keep up to 3 file contexts that fit within token budget
        kept_file_contexts = []
        file_context_tokens = 0
        max_file_context_tokens = target_tokens // 4  # Reserve 25% for file contexts
        
        for msg, size in file_contexts_with_size[:3]:
            msg_tokens = size // 4
            if file_context_tokens + msg_tokens <= max_file_context_tokens:
                kept_file_contexts.append(msg)
                file_context_tokens += msg_tokens
            else:
                break
        
        essential_system.extend(kept_file_contexts)
    
    # Calculate remaining token budget for conversation messages
    system_tokens, _ = estimate_token_usage(essential_system)
    remaining_tokens = target_tokens - system_tokens
    
    # Work backwards through conversation messages, preserving tool call sequences
    keep_messages: List[Dict[str, Any]] = []
    current_token_count = 0
    i = len(other_messages) - 1
    
    while i >= 0 and current_token_count < remaining_tokens:
        current_msg = other_messages[i]
        msg_tokens = len(str(current_msg)) // 4
        
        # If this is a tool result, we need to keep the corresponding assistant message
        if current_msg["role"] == "tool":
            # Collect all tool results for this sequence
            tool_sequence: List[Dict[str, Any]] = []
            tool_sequence_tokens = 0
            
            while i >= 0 and other_messages[i]["role"] == "tool":
                tool_msg = other_messages[i]
                tool_msg_tokens = len(str(tool_msg)) // 4
                tool_sequence.insert(0, tool_msg)
                tool_sequence_tokens += tool_msg_tokens
                i -= 1
            
            # Find the corresponding assistant message with tool_calls
            assistant_msg = None
            assistant_tokens = 0
            if i >= 0 and other_messages[i]["role"] == "assistant" and other_messages[i].get("tool_calls"):
                assistant_msg = other_messages[i]
                assistant_tokens = len(str(assistant_msg)) // 4
                i -= 1
            
            # Check if the complete tool sequence fits in our budget
            total_sequence_tokens = tool_sequence_tokens + assistant_tokens
            if current_token_count + total_sequence_tokens <= remaining_tokens:
                # Add the complete sequence
                if assistant_msg:
                    keep_messages.insert(0, assistant_msg)
                    current_token_count += assistant_tokens
                keep_messages = tool_sequence + keep_messages
                current_token_count += tool_sequence_tokens
            else:
                # Sequence too large, stop here
                break
        else:
            # Regular message (user or assistant)
            if current_token_count + msg_tokens <= remaining_tokens:
                keep_messages.insert(0, current_msg)
                current_token_count += msg_tokens
                i -= 1
            else:
                # Message too large, stop here
                break
    
    # Combine system messages with kept conversation messages
    result = essential_system + keep_messages
    
    # Log truncation results
    final_tokens, _ = estimate_token_usage(result)
    console.print(f"[dim]Context truncated: {len(conversation_history)} → {len(result)} messages, ~{current_tokens} → ~{final_tokens} tokens[/dim]")
    
    return result

def validate_tool_calls(accumulated_tool_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Validate accumulated tool calls and provide debugging info.
    
    Args:
        accumulated_tool_calls: List of tool calls to validate
        
    Returns:
        List of valid tool calls
    """
    if not accumulated_tool_calls:
        return []
    
    valid_calls: List[Dict[str, Any]] = []
    for i, tool_call in enumerate(accumulated_tool_calls):
        # Check for required fields
        if not tool_call.get("id"):
            console.print(f"[yellow]⚠ Tool call {i} missing ID, skipping[/yellow]")
            continue
        
        func_name = tool_call.get("function", {}).get("name")
        if not func_name:
            console.print(f"[yellow]⚠ Tool call {i} missing function name, skipping[/yellow]")
            continue
        
        func_args = tool_call.get("function", {}).get("arguments", "")
        
        # Validate JSON arguments
        try:
            if func_args:
                json.loads(func_args)
        except json.JSONDecodeError as e:
            console.print(f"[red]✗ Tool call {i} has invalid JSON arguments: {e}[/red]")
            console.print(f"[red]  Arguments: {func_args}[/red]")
            continue
        
        valid_calls.append(tool_call)
    
    if len(valid_calls) != len(accumulated_tool_calls):
        console.print(f"[yellow]⚠ Kept {len(valid_calls)}/{len(accumulated_tool_calls)} tool calls[/yellow]")
    
    return valid_calls

def add_file_context_smartly(conversation_history: List[Dict[str, Any]], file_path: str, content: str, max_context_files: int = MAX_CONTEXT_FILES) -> bool:
    """
    Add file context while managing system message bloat and avoiding duplicates.
    Now includes token-aware management and file size limits.
    Also ensures file context doesn't break tool call conversation flow.

    Args:
        conversation_history: List of conversation messages
        file_path: Path to the file being added
        content: Content of the file
        max_context_files: Maximum number of file contexts to keep

    Returns:
        True if file was added successfully, False if rejected due to size limits
    """
    marker = f"User added file '{file_path}'"

    # Check file size and context limits
    content_size_kb = len(content) / 1024
    estimated_tokens = len(content) // 4
    context_info = get_context_usage_info()

    # Only reject files that would use more than 80% of context
    MAX_SINGLE_FILE_TOKENS = int(ESTIMATED_MAX_TOKENS * 0.8)
    if estimated_tokens > MAX_SINGLE_FILE_TOKENS:
        console.print(f"[yellow]⚠ File '{file_path}' too large ({content_size_kb:.1f}KB, ~{estimated_tokens} tokens). Limit is 80% of context window.[/yellow]")
        return False

    # Check if the last assistant message has pending tool calls
    # If so, defer adding file context until after tool responses are complete
    if conversation_history:
        last_msg = conversation_history[-1]
        if (last_msg.get("role") == "assistant" and 
            last_msg.get("tool_calls") and 
            len(conversation_history) > 0):
            
            # Check if all tool calls have corresponding responses
            tool_call_ids = {tc["id"] for tc in last_msg["tool_calls"]}
            
            # Count tool responses after this assistant message
            responses_after = 0
            for i in range(len(conversation_history) - 1, -1, -1):
                msg = conversation_history[i]
                if msg.get("role") == "tool" and msg.get("tool_call_id") in tool_call_ids:
                    responses_after += 1
                elif msg == last_msg:
                    break
            
            # If not all tool calls have responses, defer the file context addition
            if responses_after < len(tool_call_ids):
                console.print(f"[dim]Deferring file context addition for '{Path(file_path).name}' until tool responses complete[/dim]")
                return True  # Return True but don't add yet

    # Remove any existing context for this exact file to avoid duplicates
    conversation_history[:] = [
        msg for msg in conversation_history 
        if not (msg["role"] == "system" and marker in msg["content"])
    ]

    # Get current file contexts and their sizes
    file_contexts = []
    for msg in conversation_history:
        if msg["role"] == "system" and "User added file" in msg["content"]:
            # Extract file path from marker
            lines = msg["content"].split("\n", 1)
            if lines:
                context_file_path = lines[0].replace("User added file '", "").replace("'. Content:", "")
                context_size = len(msg["content"])
                file_contexts.append((msg, context_file_path, context_size))

    # If we're at the file limit, remove the largest or oldest file contexts
    while len(file_contexts) >= max_context_files:
        if context_info["approaching_limit"]:
            # Remove largest file context when approaching limits
            file_contexts.sort(key=lambda x: x[2], reverse=True)  # Sort by size, largest first
            to_remove = file_contexts.pop(0)
            console.print(f"[dim]Removed large file context: {Path(to_remove[1]).name} ({to_remove[2]//1024:.1f}KB)[/dim]")
        else:
            # Remove oldest file context normally
            to_remove = file_contexts.pop(0)
            console.print(f"[dim]Removed old file context: {Path(to_remove[1]).name}[/dim]")

        # Remove from conversation history
        conversation_history[:] = [msg for msg in conversation_history if msg != to_remove[0]]

    # Find the right position to insert the file context
    # Insert before the last user message or at the end if no user messages
    insertion_point = len(conversation_history)
    for i in range(len(conversation_history) - 1, -1, -1):
        if conversation_history[i].get("role") == "user":
            insertion_point = i
            break

    # Add new file context at the appropriate position
    new_context_msg = {
        "role": "system", 
        "content": f"{marker}. Content:\n\n{content}"
    }
    conversation_history.insert(insertion_point, new_context_msg)

    # Log the addition
    console.print(f"[dim]Added file context: {Path(file_path).name} ({content_size_kb:.1f}KB, ~{estimated_tokens} tokens)[/dim]")

    return True

def read_local_file(file_path: str) -> str:
    """
    Read content from a local file.
    
    Args:
        file_path: Path to the file to read
        
    Returns:
        File content as string
        
    Raises:
        FileNotFoundError: If file doesn't exist
        UnicodeDecodeError: If file can't be decoded as UTF-8
    """
    full_path = (base_dir / file_path).resolve()
    with open(full_path, "r", encoding="utf-8") as f:
        return f.read()

def run_bash_command(command: str) -> Tuple[str, str]:
    """
    Run a bash command and return (stdout, stderr).
    Includes platform checks to ensure bash is available.
    """
    # Check if we're on a supported platform
    current_platform = platform.system()
    if current_platform == "Windows":
        # Try WSL bash first, then Git Bash
        bash_paths = ["wsl", "bash"]
        bash_executable = None
        
        for bash_cmd in bash_paths:
            try:
                test_run = subprocess.run(
                    [bash_cmd, "-c", "echo test"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if test_run.returncode == 0:
                    bash_executable = bash_cmd
                    break
            except (subprocess.TimeoutExpired, FileNotFoundError):
                continue
        
        if not bash_executable:
            return "", "Bash not available on Windows. Install WSL or Git Bash."
    else:
        bash_executable = "bash"
    
    # Test if bash is available
    try:
        bash_check = subprocess.run(
            [bash_executable, "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if bash_check.returncode != 0:
            return "", f"Bash not available or not working properly on {current_platform}"
        
        bash_info = bash_check.stdout.split('\n')[0] if bash_check.stdout else "Bash"
        console.print(f"[dim]Running {bash_info} on {current_platform}[/dim]")
        
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return "", f"Bash not found on {current_platform}: {e}"
    
    # Execute the actual command
    try:
        if bash_executable == "wsl":
            # For WSL, we need to format the command differently
            completed = subprocess.run(
                ["wsl", "bash", "-c", command],
                capture_output=True,
                text=True,
                timeout=30
            )
        else:
            completed = subprocess.run(
                [bash_executable, "-c", command],
                capture_output=True,
                text=True,
                timeout=30
            )
        return completed.stdout, completed.stderr
    except subprocess.TimeoutExpired:
        return "", "Bash command timed out after 30 seconds"
    except Exception as e:
        return "", f"Error executing bash command: {e}"

def run_powershell_command(command: str) -> Tuple[str, str]:
    """
    Run a PowerShell command and return (stdout, stderr).
    Includes platform checks to ensure PowerShell is available.
    """
    # Check if we're on a supported platform
    current_platform = platform.system()
    if current_platform not in ["Windows", "Linux", "Darwin"]:
        return "", f"PowerShell is not supported on {current_platform}"
    
    # Determine the PowerShell executable
    pwsh_executable = "pwsh"  # PowerShell Core (cross-platform)
    if current_platform == "Windows":
        # Try Windows PowerShell first, fall back to PowerShell Core
        try:
            test_run = subprocess.run(
                ["powershell", "-Command", "$PSVersionTable.PSEdition"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if test_run.returncode == 0:
                pwsh_executable = "powershell"
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass  # Fall back to pwsh
    
    # Test if PowerShell is available
    try:
        os_check = subprocess.run(
            [pwsh_executable, "-Command", "$PSVersionTable.PSEdition"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if os_check.returncode != 0:
            return "", f"PowerShell not available or not working properly on {current_platform}"
        
        os_info = os_check.stdout.strip() if os_check.stdout else "PowerShell"
        console.print(f"[dim]Running PowerShell ({os_info}) on {current_platform}[/dim]")
        
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return "", f"PowerShell not found on {current_platform}: {e}"
    
    # Execute the actual command
    try:
        completed = subprocess.run(
            [pwsh_executable, "-Command", command],
            capture_output=True,
            text=True,
            timeout=30  # 30 second timeout for safety
        )
        return completed.stdout, completed.stderr
    except subprocess.TimeoutExpired:
        return "", "PowerShell command timed out after 30 seconds"
    except Exception as e:
        return "", f"Error executing PowerShell command: {e}"

def normalize_path(path_str: str, allow_outside_project: bool = False) -> str:
    """
    Normalize a file path relative to the base directory with security validation.
    
    Args:
        path_str: Path string to normalize
        allow_outside_project: If False, restricts paths to within the project directory
        
    Returns:
        Normalized absolute path string
        
    Raises:
        ValueError: If path is outside project directory when allow_outside_project=False
    """
    try:
        p = Path(path_str)
        
        # If path is absolute, use it as-is
        if p.is_absolute():
            if p.exists() or p.is_symlink(): 
                resolved_p = p.resolve(strict=True) 
            else:
                resolved_p = p.resolve()
        else:
            # For relative paths, resolve against base_dir instead of cwd
            base_path = base_dir / p
            if base_path.exists() or base_path.is_symlink():
                resolved_p = base_path.resolve(strict=True)
            else:
                resolved_p = base_path.resolve()
                
    except (FileNotFoundError, RuntimeError): 
        # Fallback: resolve relative to base_dir
        p = Path(path_str)
        if p.is_absolute():
            resolved_p = p.resolve()
        else:
            resolved_p = (base_dir / p).resolve()
    
    # Security validation: ensure path is within project directory
    if not allow_outside_project:
        base_resolved = base_dir.resolve()
        try:
            # Check if the resolved path is within the base directory
            resolved_p.relative_to(base_resolved)
        except ValueError:
            raise ValueError(f"Path '{path_str}' is outside the project directory '{base_resolved}'. "
                           "This is not allowed for security reasons.")
    
    return str(resolved_p)

def is_binary_file(file_path: str, peek_size: int = 1024) -> bool:
    """
    Check if a file is binary by looking for null bytes.
    
    Args:
        file_path: Path to the file to check
        peek_size: Number of bytes to check
        
    Returns:
        True if file appears to be binary
    """
    try:
        with open(file_path, 'rb') as f: 
            chunk = f.read(peek_size)
        return b'\0' in chunk
    except Exception: 
        return True

def ensure_file_in_context(file_path: str) -> bool:
    """
    Ensure a file is loaded in the conversation context.
    
    Args:
        file_path: Path to the file
        
    Returns:
        True if file was successfully added to context
    """
    try:
        normalized_path = normalize_path(file_path)
        content = read_local_file(normalized_path)
        marker = f"User added file '{normalized_path}'"
        if not any(msg["role"] == "system" and marker in msg["content"] for msg in conversation_history):
            return add_file_context_smartly(conversation_history, normalized_path, content)
        return True
    except (OSError, ValueError) as e:
        console.print(f"[red]✗ Error reading file for context '{file_path}': {e}[/red]")
        return False

def get_model_indicator() -> str:
    """
    Get the model indicator for the prompt.
    
    Returns:
        Emoji indicator for current model
    """
    return "🧠" if model_context['is_reasoner'] else "💬"

def get_prompt_indicator() -> str:
    """
    Get the full prompt indicator including git, model, and context status.
    
    Returns:
        Formatted prompt indicator string
    """
    indicators = []
    
    # Add model indicator
    indicators.append(get_model_indicator())
    
    # Add git branch if enabled
    if git_context['enabled'] and git_context['branch']:
        indicators.append(f"🌳 {git_context['branch']}")
    
    # Add context status indicator
    context_info = get_context_usage_info()
    if context_info["critical_limit"]:
        indicators.append("🔴")  # Critical context usage
    elif context_info["approaching_limit"]:
        indicators.append("🟡")  # Warning context usage
    else:
        indicators.append("🔵")  # Normal context usage
    
    return " ".join(indicators)

# -----------------------------------------------------------------------------
# 10. FILE OPERATIONS (Enhanced with fuzzy matching)
# -----------------------------------------------------------------------------

def create_file(path: str, content: str, require_confirmation: bool = True) -> None:
    """
    Create or overwrite a file with given content.
    
    Args:
        path: File path
        content: File content
        require_confirmation: If True, prompt for confirmation when overwriting existing files
        
    Raises:
        ValueError: If file content exceeds size limit, path contains invalid characters, 
                   or user cancels overwrite
    """
    file_path = Path(path)
    if any(part.startswith('~') for part in file_path.parts):
        raise ValueError("Home directory references not allowed")
    
    # Check content size limit
    if len(content.encode('utf-8')) > MAX_FILE_CONTENT_SIZE_CREATE:
        raise ValueError(f"File content exceeds maximum size limit of {MAX_FILE_CONTENT_SIZE_CREATE} bytes")
    
    normalized_path_str = normalize_path(str(file_path))
    normalized_path = Path(normalized_path_str)
    
    # Check if file exists and prompt for confirmation if required
    if require_confirmation and normalized_path.exists():
        try:
            # Get file info for the confirmation prompt
            file_size = normalized_path.stat().st_size
            file_size_str = f"{file_size:,} bytes" if file_size < 1024 else f"{file_size/1024:.1f} KB"
            
            confirm = prompt_session.prompt(
                f"🔵 File '{normalized_path_str}' exists ({file_size_str}). Overwrite? (y/N): ",
                default="n"
            ).strip().lower()
            
            if confirm not in ["y", "yes"]:
                raise ValueError("File overwrite cancelled by user")
                
        except (KeyboardInterrupt, EOFError):
            raise ValueError("File overwrite cancelled by user")
    
    # Create the file
    normalized_path.parent.mkdir(parents=True, exist_ok=True)
    with open(normalized_path_str, "w", encoding="utf-8") as f:
        f.write(content)
    
    action = "Updated" if normalized_path.exists() else "Created"
    console.print(f"[bold blue]✓[/bold blue] {action} file at '[bright_cyan]{normalized_path_str}[/bright_cyan]'")
    
    if git_context['enabled'] and not git_context['skip_staging']:
        stage_file(normalized_path_str)

def show_diff_table(files_to_edit: List[FileToEdit]) -> None:
    """
    Display a table showing proposed file edits.
    
    Args:
        files_to_edit: List of file edit operations
    """
    if not files_to_edit: 
        return
    table = Table(title="📝 Proposed Edits", show_header=True, header_style="bold bright_blue", show_lines=True, border_style="blue")
    table.add_column("File Path", style="bright_cyan", no_wrap=True)
    table.add_column("Original", style="red dim")
    table.add_column("New", style="bright_green")
    for edit in files_to_edit: 
        table.add_row(edit.path, edit.original_snippet, edit.new_snippet)
    console.print(table)

def add_directory_to_conversation(directory_path: str) -> None:
    """
    Add all files from a directory to the conversation context.
    
    Args:
        directory_path: Path to directory to scan
    """
    with console.status("[bold bright_blue]🔍 Scanning directory...[/bold bright_blue]") as status:
        skipped: List[str] = []
        added: List[str] = []
        total_processed = 0
        
        for root, dirs, files in os.walk(directory_path):
            if total_processed >= MAX_FILES_IN_ADD_DIR: 
                console.print(f"[yellow]⚠ Max files ({MAX_FILES_IN_ADD_DIR}) reached for dir scan.")
                break
            status.update(f"[bold bright_blue]🔍 Scanning {root}...[/bold bright_blue]")
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in EXCLUDED_FILES]
            
            for file in files:
                if total_processed >= MAX_FILES_IN_ADD_DIR: 
                    break
                #if file.startswith('.') or 
                #    file in EXCLUDED_FILES or 
                    
                full_path = os.path.join(root, file)
                try:
                    if is_binary_file(full_path): 
                        skipped.append(f"{full_path} (binary)")
                        continue
                        
                    norm_path = normalize_path(full_path)
                    content = read_local_file(norm_path)
                    if add_file_context_smartly(conversation_history, norm_path, content):
                        added.append(norm_path)
                    else:
                        skipped.append(f"{full_path} (too large for context)")
                    total_processed += 1
                except (OSError, ValueError) as e: 
                    skipped.append(f"{full_path} (error: {e})")
                    
        console.print(f"[bold blue]✓[/bold blue] Added folder '[bright_cyan]{directory_path}[/bright_cyan]'.")
        if added: 
            console.print(f"\n[bold bright_blue]📁 Added:[/bold bright_blue] ({len(added)} of {total_processed} valid) {[Path(f).name for f in added[:5]]}{'...' if len(added) > 5 else ''}")
        if skipped: 
            console.print(f"\n[yellow]⏭ Skipped:[/yellow] ({len(skipped)}) {[Path(f).name for f in skipped[:3]]}{'...' if len(skipped) > 3 else ''}")
        console.print()

# -----------------------------------------------------------------------------
# 11. GIT OPERATIONS
# -----------------------------------------------------------------------------

def create_gitignore() -> None:
    """Create a comprehensive .gitignore file if it doesn't exist."""
    gitignore_path = Path(".gitignore")
    if gitignore_path.exists(): 
        console.print("[yellow]⚠ .gitignore exists, skipping.[/yellow]")
        return
        
    patterns = [
        "# Python", "__pycache__/", "*.pyc", "*.pyo", "*.pyd", ".Python", 
        "env/", "venv/", ".venv", "ENV/", "*.egg-info/", "dist/", "build/", 
        ".pytest_cache/", ".mypy_cache/", ".coverage", "htmlcov/", "", 
        "# Env", ".env", ".env*.local", "!.env.example", "", 
        "# IDE", ".vscode/", ".idea/", "*.swp", "*.swo", ".DS_Store", "", 
        "# Logs", "*.log", "logs/", "", 
        "# Temp", "*.tmp", "*.temp", "*.bak", "*.cache", "Thumbs.db", 
        "desktop.ini", "", 
        "# Node", "node_modules/", "npm-debug.log*", "yarn-debug.log*", 
        "pnpm-lock.yaml", "package-lock.json", "", 
        "# Local", "*.session", "*.checkpoint"
    ]
    
    console.print("\n[bold bright_blue]📝 Creating .gitignore[/bold bright_blue]")
    if prompt_session.prompt("🔵 Add custom patterns? (y/n, default n): ", default="n").strip().lower() in ["y", "yes"]:
        console.print("[dim]Enter patterns (empty line to finish):[/dim]")
        patterns.append("\n# Custom")
        while True: 
            pattern = prompt_session.prompt("  Pattern: ").strip()
            if pattern: 
                patterns.append(pattern)
            else: 
                break 
    try:
        with gitignore_path.open("w", encoding="utf-8") as f: 
            f.write("\n".join(patterns) + "\n")
        console.print(f"[green]✓ Created .gitignore ({len(patterns)} patterns)[/green]")
        if git_context['enabled']: 
            stage_file(str(gitignore_path))
    except OSError as e: 
        console.print(f"[red]✗ Error creating .gitignore: {e}[/red]")

def stage_file(file_path_str: str) -> bool:
    """
    Stage a file for git commit.
    
    Args:
        file_path_str: Path to file to stage
        
    Returns:
        True if staging was successful
    """
    if not git_context['enabled'] or git_context['skip_staging']: 
        return False
    try:
        repo_root = Path.cwd()
        abs_file_path = Path(file_path_str).resolve() 
        rel_path = abs_file_path.relative_to(repo_root)
        result = subprocess.run(["git", "add", str(rel_path)], cwd=str(repo_root), capture_output=True, text=True, check=False)
        if result.returncode == 0: 
            console.print(f"[green dim]✓ Staged {rel_path}[/green dim]")
            return True
        else: 
            console.print(f"[yellow]⚠ Failed to stage {rel_path}: {result.stderr.strip()}[/yellow]")
            return False
    except ValueError: 
        console.print(f"[yellow]⚠ File {file_path_str} outside repo ({repo_root}), skipping staging[/yellow]")
        return False
    except Exception as e: 
        console.print(f"[red]✗ Error staging {file_path_str}: {e}[/red]")
        return False

def get_git_status_porcelain() -> Tuple[bool, List[Tuple[str, str]]]:
    """
    Get git status in porcelain format.
    
    Returns:
        Tuple of (has_changes, list_of_file_changes)
    """
    if not git_context['enabled']: 
        return False, []
    try:
        result = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=True, cwd=str(Path.cwd()))
        if not result.stdout.strip(): 
            return False, []
        changed_files = []
        for line in result.stdout.strip().split('\n'):
            if line:
                # The actual format seems to be "X filename" where X is 1 char + space
                # For "M mistral.py": status="M ", filename="mistral.py"
                if len(line) >= 2 and line[1] == ' ':
                    status_code = line[:2]  # "M "
                    filename = line[2:]     # "mistral.py"
                else:
                    # Fallback: try to split on first space
                    parts = line.split(' ', 1)
                    if len(parts) == 2:
                        status_code = parts[0].ljust(2)  # Pad to 2 chars
                        filename = parts[1]
                    else:
                        status_code = line[:2] if len(line) >= 2 else line
                        filename = line[2:] if len(line) > 2 else ""
                
                changed_files.append((status_code, filename))
        return True, changed_files
    except subprocess.CalledProcessError as e: 
        console.print(f"[red]Error getting Git status: {e.stderr}[/red]")
        return False, []
    except FileNotFoundError: 
        console.print("[red]Git not found.[/red]")
        git_context['enabled'] = False
        return False, []

def user_commit_changes(message: str) -> bool:
    """
    Commit STAGED changes with a given message. Prompts the user if nothing is staged.
    
    Args:
        message: Commit message
        
    Returns:
        True if commit was successful or action was taken.
    """
    if not git_context['enabled']:
        console.print("[yellow]Git not enabled.[/yellow]")
        return False
        
    try:
        # Check if there are any staged changes.
        staged_check = subprocess.run(["git", "diff", "--staged", "--quiet"], cwd=str(base_dir))
        
        # If exit code is 0, it means there are NO staged changes.
        if staged_check.returncode == 0:
            console.print("[yellow]No changes are staged for commit.[/yellow]")
            # Check if there are unstaged changes we can offer to add
            unstaged_check = subprocess.run(["git", "diff", "--quiet"], cwd=str(base_dir))
            if unstaged_check.returncode != 0: # Unstaged changes exist
                try:
                    confirm = prompt_session.prompt(
                        "🔵 However, there are unstaged changes. Stage all changes and commit? (y/N): ",
                        default="n"
                    ).strip().lower()
                    
                    if confirm in ["y", "yes"]:
                        console.print("[dim]Staging all changes...[/dim]")
                        subprocess.run(["git", "add", "-A"], cwd=str(base_dir), check=True)
                    else:
                        console.print("[yellow]Commit aborted. Use `/git add <files>` to stage changes.[/yellow]")
                        return True
                except (KeyboardInterrupt, EOFError):
                    console.print("\n[yellow]Commit aborted.[/yellow]")
                    return True
            else: # No staged and no unstaged changes
                console.print("[dim]Working tree is clean. Nothing to commit.[/dim]")
                return True

        # At this point, we know there are staged changes, so we can commit.
        commit_res = subprocess.run(["git", "commit", "-m", message], cwd=str(base_dir), capture_output=True, text=True)
        
        if commit_res.returncode == 0:
            console.print(f"[green]✓ Committed successfully![/green]")
            log_info = subprocess.run(["git", "log", "--oneline", "-1"], cwd=str(base_dir), capture_output=True, text=True).stdout.strip()
            if log_info:
                console.print(f"[dim]Commit: {log_info}[/dim]")
            return True
        else:
            console.print(f"[red]✗ Commit failed:[/red]\n{commit_res.stderr.strip()}")
            return False
            
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        console.print(f"[red]✗ Git error: {e}[/red]")
        if isinstance(e, FileNotFoundError):
            git_context['enabled'] = False
        return False

# -----------------------------------------------------------------------------
# 12. ENHANCED COMMAND HANDLERS
# -----------------------------------------------------------------------------

def try_handle_add_command(user_input: str) -> bool:
    """Handle /add command with fuzzy file finding support."""
    if user_input.strip().lower().startswith(ADD_COMMAND_PREFIX):
        path_to_add = user_input[len(ADD_COMMAND_PREFIX):].strip()
        
        # 1. Try direct path first
        try:
            p = (base_dir / path_to_add).resolve()
            if p.exists():
                normalized_path = str(p)
            else:
                # This will raise an error if it doesn't exist, triggering the fuzzy search
                _ = p.resolve(strict=True) 
        except (FileNotFoundError, OSError):
            # 2. If direct path fails, try fuzzy finding
            console.print(f"[dim]Path '{path_to_add}' not found directly, attempting fuzzy search...[/dim]")
            fuzzy_match = find_best_matching_file(base_dir, path_to_add)

            if fuzzy_match:
                # Optional: Confirm with user for better UX
                relative_fuzzy = Path(fuzzy_match).relative_to(base_dir)
                confirm = prompt_session.prompt(f"🔵 Did you mean '[bright_cyan]{relative_fuzzy}[/bright_cyan]'? (Y/n): ", default="y").strip().lower()
                if confirm in ["y", "yes"]:
                    normalized_path = fuzzy_match
                else:
                    console.print("[yellow]Add command cancelled.[/yellow]")
                    return True
            else:
                console.print(f"[bold red]✗[/bold red] Path does not exist: '[bright_cyan]{path_to_add}[/bright_cyan]'")
                if FUZZY_AVAILABLE:
                    console.print("[dim]Tip: Try a partial filename (e.g., 'main.py' instead of exact path)[/dim]")
                return True
        
        # --- Process the found file/directory ---
        try:
            if Path(normalized_path).is_dir():
                add_directory_to_conversation(normalized_path)
            else:
                content = read_local_file(normalized_path)
                if add_file_context_smartly(conversation_history, normalized_path, content):
                    console.print(f"[bold blue]✓[/bold blue] Added file '[bright_cyan]{normalized_path}[/bright_cyan]' to conversation.\n")
                else:
                    console.print(f"[bold yellow]⚠[/bold yellow] File '[bright_cyan]{normalized_path}[/bright_cyan]' too large for context.\n")
        except (OSError, ValueError) as e:
            console.print(f"[bold red]✗[/bold red] Could not add path '[bright_cyan]{path_to_add}[/bright_cyan]': {e}\n")
        return True
    return False

def try_handle_commit_command(user_input: str) -> bool:
    """Handle /git commit command for git commits."""
    # This function is now correctly called by the new dispatcher.
    # We just need to handle the logic of extracting the message.
    
    if not git_context['enabled']:
        console.print("[yellow]Git not enabled. Use `/git init` first.[/yellow]")
        return True

    # COMMIT_COMMAND_PREFIX is "/git commit ". This correctly grabs everything after it.
    message = user_input[len(COMMIT_COMMAND_PREFIX):].strip()

    # If the message is empty, it means the user typed `/git commit` or `/git commit `
    # In this case, we should interactively prompt for a message.
    if not message:
        try:
            message = prompt_session.prompt("🔵 Enter commit message: ").strip()
            if not message:
                console.print("[yellow]Commit aborted. Message cannot be empty.[/yellow]")
                return True
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Commit aborted by user.[/yellow]")
            return True

    # Now that we have a valid message, commit the changes.
    user_commit_changes(message)
    return True

def try_handle_git_add_command(user_input: str) -> bool:
    """Handle the /git add command for staging files."""
    # Define a new prefix for this command
    GIT_ADD_COMMAND_PREFIX = "/git add "
    
    if user_input.strip().lower().startswith(GIT_ADD_COMMAND_PREFIX.strip()):
        if not git_context['enabled']:
            console.print("[yellow]Git not enabled. Use `/git init` first.[/yellow]")
            return True
            
        # Get everything after "/git add " and split into file paths
        files_to_add_str = user_input[len(GIT_ADD_COMMAND_PREFIX):].strip()
        if not files_to_add_str:
            console.print("[yellow]Usage: /git add <file1> <file2> ... or /git add .[/yellow]")
            return True
            
        file_paths = files_to_add_str.split()
        
        staged_ok: List[str] = []
        failed_stage: List[str] = []
        
        for fp_str in file_paths:
            # Handle the special case of `.` for adding all changes
            if fp_str == ".":
                try:
                    subprocess.run(["git", "add", "."], cwd=str(base_dir), check=True, capture_output=True)
                    console.print("[green]✓ Staged all changes in the current directory.[/green]")
                    return True # Stop after this, as it's a special case
                except subprocess.CalledProcessError as e:
                    console.print(f"[red]✗ Failed to stage all changes: {e.stderr}[/red]")
                    return True

            # Handle individual files
            try:
                # We can reuse the existing `stage_file` logic
                if stage_file(fp_str):
                    staged_ok.append(fp_str)
                else:
                    failed_stage.append(fp_str)
            except Exception as e:
                failed_stage.append(f"{fp_str} (error: {e})")
        
        # Report results
        if staged_ok:
            console.print(f"[green]✓ Staged:[/green] {', '.join(staged_ok)}")
        if failed_stage:
            console.print(f"[yellow]⚠ Failed to stage:[/yellow] {', '.join(failed_stage)}")
        
        # After staging, it's helpful to show the status
        show_git_status_cmd()
        return True
        
    return False

def try_handle_git_command(user_input: str) -> bool:
    """Handle various git commands."""
    cmd = user_input.strip().lower()
    if cmd == "/git init": 
        return initialize_git_repo_cmd()
    elif cmd.startswith(GIT_BRANCH_COMMAND_PREFIX.strip()):
        branch_name = user_input[len(GIT_BRANCH_COMMAND_PREFIX.strip()):].strip()
        if not branch_name and cmd == GIT_BRANCH_COMMAND_PREFIX.strip():
             console.print("[yellow]Specify branch name: /git branch <name>[/yellow]")
             return True
        return create_git_branch_cmd(branch_name)
    elif cmd == "/git status": 
        return show_git_status_cmd()
    return False

def try_handle_git_info_command(user_input: str) -> bool:
    """Handle /git-info command to show git capabilities."""
    if user_input.strip().lower() == "/git-info":
        console.print("I can use Git commands to interact with a Git repository. Here's what I can do for you:\n\n"
                      "1. **Initialize a Git repository**: Use `git_init` to create a new Git repository in the current directory.\n"
                      "2. **Stage files for commit**: Use `git_add` to stage specific files for the next commit.\n"
                      "3. **Commit changes**: Use `git_commit` to commit staged changes with a message.\n"
                      "4. **Create and switch to a new branch**: Use `git_create_branch` to create a new branch and switch to it.\n"
                      "5. **Check Git status**: Use `git_status` to see the current state of the repository (staged, unstaged, or untracked files).\n\n"
                      "Let me know what you'd like to do, and I can perform the necessary Git operations for you. For example:\n"
                      "- Do you want to initialize a new repository?\n"
                      "- Stage and commit changes?\n"
                      "- Create a new branch? \n\n"
                      "Just provide the details, and I'll handle the rest!")
        return True
    return False

def try_handle_r1_command(user_input: str) -> bool:
    """Handle /r command for one-off reasoner calls."""
    if user_input.strip().lower() == "/r":
        # Prompt the user for input
        try:
            user_prompt = prompt_session.prompt("🔵 Enter your reasoning prompt: ").strip()
            if not user_prompt:
                console.print("[yellow]No input provided. Aborting.[/yellow]")
                return True
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Cancelled.[/yellow]")
            return True
        
        # Prepare the API call using current conversation state
        temp_conversation = conversation_history + [{"role": "user", "content": user_prompt}]
        
        try:
            with console.status("[bold yellow]Magistral (R1) is thinking...[/bold yellow]", spinner="dots"):
                response_stream = client.chat.completions.create(
                    model=REASONER_MODEL,
                    messages=temp_conversation,
                    tools=tools,
                    tool_choice="auto",
                    stream=True,
                    max_completion_tokens=5000,
                    temperature=0.7,
                    top_p=1
                )
            
            # Process and display the response
            full_response_content = ""
            accumulated_tool_calls = []
            
            console.print("[bold bright_magenta]🧠 Magistral:[/bold bright_magenta] ", end="")
            for chunk in response_stream:
                # Handle content chunks
                if chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    # Strip <think> and </think> tags from the content
                    content = content.replace("<think>", "").replace("</think>", "")
                    console.print(content, end="", style="bright_magenta")
                    full_response_content += content
                
                # Handle tool call chunks (though R1 calls usually don't use tools)
                if chunk.choices[0].delta.tool_calls:
                    for tool_call_chunk in chunk.choices[0].delta.tool_calls:
                        idx = tool_call_chunk.index
                        while len(accumulated_tool_calls) <= idx:
                            accumulated_tool_calls.append({
                                "id": "", "type": "function", 
                                "function": {"name": "", "arguments": ""}
                            })
                        current_tool_dict = accumulated_tool_calls[idx]
                        if tool_call_chunk.id:
                            current_tool_dict["id"] = tool_call_chunk.id
                        if tool_call_chunk.function:
                            if tool_call_chunk.function.name:
                                current_tool_dict["function"]["name"] = tool_call_chunk.function.name
                            if tool_call_chunk.function.arguments:
                                current_tool_dict["function"]["arguments"] += tool_call_chunk.function.arguments
            
            console.print()
            
            # Add both messages to conversation history
            conversation_history.append({"role": "user", "content": user_prompt})
            assistant_message = {"role": "assistant", "content": full_response_content}
            
            # Handle tool calls if any (rare for R1 but possible)
            valid_tool_calls = validate_tool_calls(accumulated_tool_calls)
            if valid_tool_calls:
                assistant_message["tool_calls"] = valid_tool_calls
                console.print("[dim]Note: R1 reasoner made tool calls. Executing...[/dim]")
                # Execute tool calls for R1 as well
                for tool_call in valid_tool_calls:
                    try:
                        result = execute_function_call_dict(tool_call)
                        tool_response = {
                            "role": "tool",
                            "content": str(result),
                            "tool_call_id": tool_call["id"]
                        }
                        conversation_history.append(tool_response)
                    except Exception as e:
                        console.print(f"[red]✗ R1 tool call error: {e}[/red]")
            
            conversation_history.append(assistant_message)
            return True
            
        except Exception as e:
            console.print(f"\n[red]✗ R1 reasoner error: {e}[/red]")
            return True
    
    return False

def try_handle_reasoner_command(user_input: str) -> bool:
    """Handle /reasoner command to toggle between models."""
    if user_input.strip().lower() == "/reasoner":
        # Toggle model
        if model_context['current_model'] == DEFAULT_MODEL:
            model_context['current_model'] = REASONER_MODEL
            model_context['is_reasoner'] = True
            console.print(f"[green]✓ Switched to {REASONER_MODEL} model 🧠[/green]")
            console.print("[dim]All subsequent conversations will use the reasoner model.[/dim]")
        else:
            model_context['current_model'] = DEFAULT_MODEL
            model_context['is_reasoner'] = False
            console.print(f"[green]✓ Switched to {DEFAULT_MODEL} model 💬[/green]")
            console.print("[dim]All subsequent conversations will use the chat model.[/dim]")
        return True
    return False

def try_handle_clear_command(user_input: str) -> bool:
    """Handle /clear command to clear screen."""
    if user_input.strip().lower() == "/clear":
        console.clear()
        return True
    return False

def try_handle_clear_context_command(user_input: str) -> bool:
    """Handle /clear-context command to clear conversation history."""
    if user_input.strip().lower() == "/clear-context":
        if len(conversation_history) <= 1:
            console.print("[yellow]Context already empty (only system prompt).[/yellow]")
            return True
            
        # Show current context size
        file_contexts = sum(1 for msg in conversation_history if msg["role"] == "system" and "User added file" in msg["content"])
        total_messages = len(conversation_history) - 1  # Exclude system prompt
        
        console.print(f"[yellow]Current context: {total_messages} messages, {file_contexts} file contexts[/yellow]")
        
        # Ask for confirmation since this is destructive
        confirm = prompt_session.prompt("🔵 Clear conversation context? This cannot be undone (y/n): ").strip().lower()
        if confirm in ["y", "yes"]:
            # Keep only the original system prompt
            original_system_prompt = conversation_history[0]
            conversation_history[:] = [original_system_prompt]
            console.print("[green]✓ Conversation context cleared. Starting fresh![/green]")
            console.print("[green]  All file contexts and conversation history removed.[/green]")
        else:
            console.print("[yellow]Context clear cancelled.[/yellow]")
        return True
    return False

def try_handle_folder_command(user_input: str) -> bool:
    """Handle /folder command to manage base directory."""
    global base_dir
    if user_input.strip().lower().startswith("/folder"):
        folder_path = user_input[len("/folder"):].strip()
        if not folder_path:
            console.print(f"[yellow]Current base directory: '{base_dir}'[/yellow]")
            console.print("[yellow]Usage: /folder <path> or /folder reset[/yellow]")
            return True
        if folder_path.lower() == "reset":
            old_base = base_dir
            base_dir = Path.cwd()
            console.print(f"[green]✓ Base directory reset from '{old_base}' to: '{base_dir}'[/green]")
            return True
        try:
            new_base = Path(folder_path).resolve()
            if not new_base.exists() or not new_base.is_dir():
                console.print(f"[red]✗ Path does not exist or is not a directory: '{folder_path}'[/red]")
                return True
            # Check write permissions
            test_file = new_base / ".eng-git-test"
            try:
                test_file.touch()
                test_file.unlink()
            except PermissionError:
                console.print(f"[red]✗ No write permissions in directory: '{new_base}'[/red]")
                return True
            old_base = base_dir
            base_dir = new_base
            console.print(f"[green]✓ Base directory changed from '{old_base}' to: '{base_dir}'[/green]")
            console.print(f"[green]  All relative paths will now be resolved against this directory.[/green]")
            return True
        except Exception as e:
            console.print(f"[red]✗ Error setting base directory: {e}[/red]")
            return True
    return False

def try_handle_exit_command(user_input: str) -> bool:
    """Handle /exit and /quit commands."""
    if user_input.strip().lower() in ("/exit", "/quit"):
        console.print("[bold blue]👋 Goodbye![/bold blue]")
        sys.exit(0)
    return False

def try_handle_context_command(user_input: str) -> bool:
    """Handle /context command to show context usage statistics."""
    if user_input.strip().lower() == "/context":
        context_info = get_context_usage_info()
        
        # Create context usage table
        context_table = Table(title="📊 Context Usage Statistics", show_header=True, header_style="bold bright_blue")
        context_table.add_column("Metric", style="bright_cyan")
        context_table.add_column("Value", style="white")
        context_table.add_column("Status", style="white")
        
        # Add rows with usage information
        context_table.add_row(
            "Total Messages", 
            str(context_info["total_messages"]), 
            "📝"
        )
        context_table.add_row(
            "Estimated Tokens", 
            f"{context_info['estimated_tokens']:,}", 
            f"{context_info['token_usage_percent']:.1f}% of {ESTIMATED_MAX_TOKENS:,}"
        )
        context_table.add_row(
            "File Contexts", 
            str(context_info["file_contexts"]), 
            f"Max: {MAX_CONTEXT_FILES}"
        )
        
        # Status indicators
        if context_info["critical_limit"]:
            status_color = "red"
            status_text = "🔴 Critical - aggressive truncation active"
        elif context_info["approaching_limit"]:
            status_color = "yellow"
            status_text = "🟡 Warning - approaching limits"
        else:
            status_color = "green"
            status_text = "🟢 Healthy - plenty of space"
        
        context_table.add_row(
            "Context Health", 
            status_text, 
            ""
        )
        
        console.print(context_table)
        
        # Show token breakdown
        if context_info["token_breakdown"]:
            breakdown_table = Table(title="📋 Token Breakdown by Role", show_header=True, header_style="bold bright_blue", border_style="blue")
            breakdown_table.add_column("Role", style="bright_cyan")
            breakdown_table.add_column("Tokens", style="white")
            breakdown_table.add_column("Percentage", style="white")
            
            total_tokens = context_info["estimated_tokens"]
            for role, tokens in context_info["token_breakdown"].items():
                if tokens > 0:
                    percentage = (tokens / total_tokens * 100) if total_tokens > 0 else 0
                    breakdown_table.add_row(
                        role.capitalize(),
                        f"{tokens:,}",
                        f"{percentage:.1f}%"
                    )
            
            console.print(breakdown_table)
        
        # Show recommendations if approaching limits
        if context_info["approaching_limit"]:
            console.print("\n[yellow]💡 Recommendations to manage context:[/yellow]")
            console.print("[yellow]  • Use /clear-context to start fresh[/yellow]")
            console.print("[yellow]  • Remove large files from context[/yellow]")
            console.print("[yellow]  • Work with smaller file sections[/yellow]")
        
        return True
    return False

def try_handle_help_command(user_input: str) -> bool:
    """Handle /help command to show available commands."""
    if user_input.strip().lower() == "/help":
        help_table = Table(title="📝 Available Commands", show_header=True, header_style="bold bright_blue")
        help_table.add_column("Command", style="bright_cyan")
        help_table.add_column("Description", style="white")
        
        # General commands
        help_table.add_row("/help", "Show this help")
        help_table.add_row("/r", "Call Reasoner model for one-off reasoning tasks")
        help_table.add_row("/reasoner", "Toggle between chat and reasoner models")
        help_table.add_row("/clear", "Clear screen")
        help_table.add_row("/clear-context", "Clear conversation context")
        help_table.add_row("/context", "Show context usage statistics")
        help_table.add_row("/os", "Show operating system information")
        help_table.add_row("/exit, /quit", "Exit application")
        
        # Directory & file management
        help_table.add_row("/folder", "Show current base directory")
        help_table.add_row("/folder <path>", "Set base directory for file operations")
        help_table.add_row("/folder reset", "Reset base directory to current working directory")
        help_table.add_row(f"{ADD_COMMAND_PREFIX.strip()} <path>", "Add file/dir to conversation context (supports fuzzy matching)")
        
        # Git workflow commands
        help_table.add_row("/git init", "Initialize Git repository")
        help_table.add_row("/git status", "Show Git status")
        help_table.add_row(f"{GIT_BRANCH_COMMAND_PREFIX.strip()} <name>", "Create & switch to new branch")
        help_table.add_row("/git add <. or <file1> <file2>", "Stage all files or specific ones for commit")
        help_table.add_row("/git commit", "Commit changes (prompts if no message)")
        help_table.add_row("/git-info", "Show detailed Git capabilities")
        
        console.print(help_table)
        
        # Show current model status
        current_model_name = "Reasoner 🧠" if model_context['is_reasoner'] else "Chat 💬"
        console.print(f"\n[dim]Current model: {current_model_name}[/dim]")
        
        # Show fuzzy matching status
        fuzzy_status = "✓ Available" if FUZZY_AVAILABLE else "✗ Not installed (pip install thefuzz python-levenshtein)"
        console.print(f"[dim]Fuzzy matching: {fuzzy_status}[/dim]")
        
        # Show OS and shell status
        available_shells = [shell for shell, available in os_info['shell_available'].items() if available]
        shell_status = ", ".join(available_shells) if available_shells else "None detected"
        console.print(f"[dim]OS: {os_info['system']} | Available shells: {shell_status}[/dim]")
        
        return True
    return False

def try_handle_os_command(user_input: str) -> bool:
    """Handle /os command to show operating system information."""
    if user_input.strip().lower() == "/os":
        os_table = Table(title="🖥️ Operating System Information", show_header=True, header_style="bold bright_blue")
        os_table.add_column("Property", style="bright_cyan")
        os_table.add_column("Value", style="white")
        
        # Basic OS info
        os_table.add_row("System", os_info['system'])
        os_table.add_row("Release", os_info['release'])
        os_table.add_row("Version", os_info['version'])
        os_table.add_row("Machine", os_info['machine'])
        if os_info['processor']:
            os_table.add_row("Processor", os_info['processor'])
        os_table.add_row("Python Version", os_info['python_version'])
        
        console.print(os_table)
        
        # Shell availability
        shell_table = Table(title="🐚 Shell Availability", show_header=True, header_style="bold bright_blue")
        shell_table.add_column("Shell", style="bright_cyan")
        shell_table.add_column("Status", style="white")
        
        for shell, available in os_info['shell_available'].items():
            status = "✓ Available" if available else "✗ Not available"
            shell_table.add_row(shell.capitalize(), status)
        
        console.print(shell_table)
        
        # Platform-specific recommendations
        if os_info['is_windows']:
            console.print("\n[yellow]💡 Windows detected:[/yellow]")
            console.print("[yellow]  • PowerShell commands are preferred[/yellow]")
            if os_info['shell_available']['bash']:
                console.print("[yellow]  • Bash is available (WSL or Git Bash)[/yellow]")
        elif os_info['is_mac']:
            console.print("\n[yellow]💡 macOS detected:[/yellow]")
            console.print("[yellow]  • Bash and zsh commands are preferred[/yellow]")
            console.print("[yellow]  • PowerShell Core may be available[/yellow]")
        elif os_info['is_linux']:
            console.print("\n[yellow]💡 Linux detected:[/yellow]")
            console.print("[yellow]  • Bash commands are preferred[/yellow]")
            console.print("[yellow]  • PowerShell Core may be available[/yellow]")
        
        return True
    return False

def initialize_git_repo_cmd() -> bool:
    """Initialize a git repository."""
    if Path(".git").exists(): 
        console.print("[yellow]Git repo already exists.[/yellow]")
        git_context['enabled'] = True
        return True
    try:
        subprocess.run(["git", "init"], cwd=str(Path.cwd()), check=True, capture_output=True)
        git_context['enabled'] = True
        branch_res = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(Path.cwd()), capture_output=True, text=True)
        git_context['branch'] = branch_res.stdout.strip() if branch_res.returncode == 0 else "main"
        console.print(f"[green]✓ Initialized Git repo in {Path.cwd()}/.git/ (branch: {git_context['branch']})[/green]")
        if not Path(".gitignore").exists() and prompt_session.prompt("🔵 No .gitignore. Create one? (y/n, default y): ", default="y").strip().lower() in ["y", "yes"]: 
            create_gitignore()
        elif git_context['enabled'] and Path(".gitignore").exists(): 
            stage_file(".gitignore")
        if prompt_session.prompt(f"🔵 Initial commit? (y/n, default n): ", default="n").strip().lower() in ["y", "yes"]: 
            user_commit_changes("Initial commit")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as e: 
        console.print(f"[red]✗ Failed to init Git: {e}[/red]")
        if isinstance(e, FileNotFoundError): 
            git_context['enabled'] = False
        return False

def create_git_branch_cmd(branch_name: str) -> bool:
    """Create and switch to a git branch."""
    if not git_context['enabled']: 
        console.print("[yellow]Git not enabled.[/yellow]")
        return True
    if not branch_name: 
        console.print("[yellow]Branch name empty.[/yellow]")
        return True
    try:
        existing_raw = subprocess.run(["git", "branch", "--list", branch_name], cwd=str(Path.cwd()), capture_output=True, text=True)
        if existing_raw.stdout.strip():
            console.print(f"[yellow]Branch '{branch_name}' exists.[/yellow]")
            current_raw = subprocess.run(["git", "branch", "--show-current"], cwd=str(Path.cwd()), capture_output=True, text=True)
            if current_raw.stdout.strip() != branch_name and prompt_session.prompt(f"🔵 Switch to '{branch_name}'? (y/n, default y): ", default="y").strip().lower() in ["y", "yes"]:
                subprocess.run(["git", "checkout", branch_name], cwd=str(Path.cwd()), check=True, capture_output=True)
                git_context['branch'] = branch_name
                console.print(f"[green]✓ Switched to branch '{branch_name}'[/green]")
            return True
        subprocess.run(["git", "checkout", "-b", branch_name], cwd=str(Path.cwd()), check=True, capture_output=True)
        git_context['branch'] = branch_name
        console.print(f"[green]✓ Created & switched to new branch '{branch_name}'[/green]")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as e: 
        console.print(f"[red]✗ Branch op failed: {e}[/red]")
        if isinstance(e, FileNotFoundError): 
            git_context['enabled'] = False
        return False

def show_git_status_cmd() -> bool:
    """Show git status."""
    if not git_context['enabled']: 
        console.print("[yellow]Git not enabled.[/yellow]")
        return True
    has_changes, files = get_git_status_porcelain()
    branch_raw = subprocess.run(["git", "branch", "--show-current"], cwd=str(Path.cwd()), capture_output=True, text=True)
    branch_msg = f"On branch {branch_raw.stdout.strip()}" if branch_raw.returncode == 0 and branch_raw.stdout.strip() else "Not on any branch?"
    console.print(Panel(branch_msg, title="Git Status", border_style="blue", expand=False))
    if not has_changes: 
        console.print("[green]Working tree clean.[/green]")
        return True
    table = Table(show_header=True, header_style="bold bright_blue", border_style="blue")
    table.add_column("Sts", width=3)
    table.add_column("File Path")
    table.add_column("Description", style="dim")
    s_map = {
        " M": (" M", "Mod (unstaged)"), "MM": ("MM", "Mod (staged&un)"), 
        " A": (" A", "Add (unstaged)"), "AM": ("AM", "Add (staged&mod)"), 
        "AD": ("AD", "Add (staged&del)"), " D": (" D", "Del (unstaged)"), 
        "??": ("??", "Untracked"), "M ": ("M ", "Mod (staged)"), 
        "A ": ("A ", "Add (staged)"), "D ": ("D ", "Del (staged)"), 
        "R ": ("R ", "Ren (staged)"), "C ": ("C ", "Cop (staged)"), 
        "U ": ("U ", "Unmerged")
    }
    staged, unstaged, untracked = False, False, False
    for code, filename in files:
        disp_code, desc = s_map.get(code, (code, "Unknown"))
        table.add_row(disp_code, filename, desc)
        if code == "??": 
            untracked = True
        elif code.startswith(" "): 
            unstaged = True
        else: 
            staged = True
    console.print(table)
    if not staged and (unstaged or untracked): 
        console.print("\n[yellow]No changes added to commit.[/yellow]")
    if staged: 
        console.print("\n[green]Changes to be committed.[/green]")
    if unstaged: 
        console.print("[yellow]Changes not staged for commit.[/yellow]")
    if untracked: 
        console.print("[cyan]Untracked files present.[/cyan]")
    return True

# -----------------------------------------------------------------------------
# 13. ENHANCED LLM TOOL HANDLER FUNCTIONS
# -----------------------------------------------------------------------------

def llm_git_init() -> str:
    """LLM tool handler for git init."""
    if Path(".git").exists(): 
        git_context['enabled'] = True
        return "Git repository already exists."
    try:
        subprocess.run(["git", "init"], cwd=str(Path.cwd()), check=True, capture_output=True)
        git_context['enabled'] = True
        branch_res = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(Path.cwd()), capture_output=True, text=True)
        git_context['branch'] = branch_res.stdout.strip() if branch_res.returncode == 0 else "main"
        if not Path(".gitignore").exists(): 
            create_gitignore()
        elif git_context['enabled']: 
            stage_file(".gitignore")
        return f"Git repository initialized successfully in {Path.cwd()}/.git/ (branch: {git_context['branch']})."

    except (subprocess.CalledProcessError, FileNotFoundError) as e: 
        if isinstance(e, FileNotFoundError):
            git_context['enabled'] = False
        return f"Failed to initialize Git repository: {e}"

def llm_git_add(file_paths: List[str]) -> str:
    """LLM tool handler for git add."""
    if not git_context['enabled']: 
        return "Git not initialized."
    if not file_paths: 
        return "No file paths to stage."
    staged_ok: List[str] = []
    failed_stage: List[str] = []
    for fp_str in file_paths:
        try: 
            norm_fp = normalize_path(fp_str)
            if stage_file(norm_fp):
                staged_ok.append(norm_fp)
            else:
                failed_stage.append(norm_fp)
        except ValueError as e: 
            failed_stage.append(f"{fp_str} (path error: {e})")
        except Exception as e: 
            failed_stage.append(f"{fp_str} (error: {e})")
    res = []
    if staged_ok: 
        res.append(f"Staged: {', '.join(Path(p).name for p in staged_ok)}")
    if failed_stage: 
        res.append(f"Failed to stage: {', '.join(str(Path(p).name if isinstance(p,str) else p) for p in failed_stage)}")
    return ". ".join(res) + "." if res else "No files staged. Check paths."

def llm_git_commit(message: str, require_confirmation: bool = True) -> str:
    """
    LLM tool handler for git commit with optional confirmation.
    
    Args:
        message: Commit message
        require_confirmation: If True, prompt for confirmation when there are uncommitted changes
    
    Returns:
        Commit result message
    """
    if not git_context['enabled']: 
        return "Git not initialized."
    if not message: 
        return "Commit message empty."
    
    try:
        # Check if there are staged changes
        staged_check = subprocess.run(["git", "diff", "--staged", "--quiet"], cwd=str(Path.cwd()))
        if staged_check.returncode == 0: 
            return "No changes staged. Use git_add first."
        
        # Check for uncommitted changes in working directory
        if require_confirmation:
            uncommitted_check = subprocess.run(["git", "diff", "--quiet"], cwd=str(Path.cwd()))
            if uncommitted_check.returncode != 0:
                # There are uncommitted changes
                try:
                    confirm = prompt_session.prompt(
                        "🔵 There are uncommitted changes in your working directory. "
                        "Commit staged changes anyway? (y/N): ",
                        default="n"
                    ).strip().lower()
                    
                    if confirm not in ["y", "yes"]:
                        return "Commit cancelled by user. Consider staging all changes first."
                        
                except (KeyboardInterrupt, EOFError):
                    return "Commit cancelled by user."
        
        # Show what will be committed
        staged_files = subprocess.run(
            ["git", "diff", "--staged", "--name-only"], 
            cwd=str(Path.cwd()), 
            capture_output=True, 
            text=True
        ).stdout.strip()
        
        if staged_files:
            console.print(f"[dim]Committing files: {staged_files.replace(chr(10), ', ')}[/dim]")
        
        # Perform the commit
        result = subprocess.run(["git", "commit", "-m", message], cwd=str(Path.cwd()), capture_output=True, text=True)
        if result.returncode == 0:
            info_raw = subprocess.run(["git", "log", "-1", "--pretty=%h %s"], cwd=str(Path.cwd()), capture_output=True, text=True).stdout.strip()
            return f"Committed successfully. Commit: {info_raw}"
        return f"Failed to commit: {result.stderr.strip()}"
        
    except (subprocess.CalledProcessError, FileNotFoundError) as e: 
        if isinstance(e, FileNotFoundError):
            git_context['enabled'] = False
        return f"Git commit error: {e}"
    except Exception as e: 
        console.print_exception()
        return f"Unexpected commit error: {e}"

def llm_git_create_branch(branch_name: str) -> str:
    """LLM tool handler for git branch creation."""
    if not git_context['enabled']: 
        return "Git not initialized."
    bn = branch_name.strip()
    if not bn: 
        return "Branch name empty."
    try:
        exist_res = subprocess.run(["git", "rev-parse", "--verify", f"refs/heads/{bn}"], cwd=str(Path.cwd()), capture_output=True, text=True)
        if exist_res.returncode == 0:
            current_raw = subprocess.run(["git", "branch", "--show-current"], cwd=str(Path.cwd()), capture_output=True, text=True)
            if current_raw.stdout.strip() == bn: 
                return f"Already on branch '{bn}'."
            subprocess.run(["git", "checkout", bn], cwd=str(Path.cwd()), check=True, capture_output=True, text=True)
            git_context['branch'] = bn
            return f"Branch '{bn}' exists. Switched to it."
        subprocess.run(["git", "checkout", "-b", bn], cwd=str(Path.cwd()), check=True, capture_output=True, text=True)
        git_context['branch'] = bn
        return f"Created & switched to new branch '{bn}'."
    except (subprocess.CalledProcessError, FileNotFoundError) as e: 
        if isinstance(e, FileNotFoundError):
            git_context['enabled'] = False
        return f"Branch op failed for '{bn}': {e}"

def llm_git_status() -> str:
    """LLM tool handler for git status."""
    if not git_context['enabled']: 
        return "Git not initialized."
    try:
        branch_res = subprocess.run(["git", "branch", "--show-current"], cwd=str(Path.cwd()), capture_output=True, text=True)
        branch_name = branch_res.stdout.strip() if branch_res.returncode == 0 and branch_res.stdout.strip() else "detached HEAD"
        has_changes, files = get_git_status_porcelain()
        if not has_changes: 
            return f"On branch '{branch_name}'. Working tree clean."
        lines = [f"On branch '{branch_name}'."]
        staged: List[str] = []
        unstaged: List[str] = []
        untracked: List[str] = []
        for code, filename in files:
            if code == "??": 
                untracked.append(filename)
            elif code.startswith(" "): 
                unstaged.append(f"{code.strip()} {filename}")
            else: 
                staged.append(f"{code.strip()} {filename}")
        if staged: 
            lines.extend(["\nChanges to be committed:"] + [f"  {s}" for s in staged])
        if unstaged: 
            lines.extend(["\nChanges not staged for commit:"] + [f"  {s}" for s in unstaged])
        if untracked: 
            lines.extend(["\nUntracked files:"] + [f"  {f}" for f in untracked])
        return "\n".join(lines)
    except (subprocess.CalledProcessError, FileNotFoundError) as e: 
        if isinstance(e, FileNotFoundError):
            git_context['enabled'] = False
        return f"Git status error: {e}"

def execute_function_call_dict(tool_call_dict: Dict[str, Any]) -> str:
    """
    Execute a function call from the LLM with enhanced fuzzy matching and security.
    
    Args:
        tool_call_dict: Dictionary containing function call information
        
    Returns:
        String result of the function execution
    """
    func_name = "unknown_function"
    try:
        func_name = tool_call_dict["function"]["name"]
        args = json.loads(tool_call_dict["function"]["arguments"])
        
        if func_name == "read_file":
            norm_path = normalize_path(args["file_path"])
            content = read_local_file(norm_path)
            return f"Content of file '{norm_path}':\n\n{content}"
            
        elif func_name == "read_multiple_files":
            response_data = {
                "files_read": {},
                "errors": {}
            }
            total_content_size = 0

            for fp in args["file_paths"]:
                try:
                    norm_path = normalize_path(fp)
                    content = read_local_file(norm_path)

                    if total_content_size + len(content) > MAX_MULTIPLE_READ_SIZE:
                        response_data["errors"][norm_path] = "Could not read file, as total content size would exceed the safety limit."
                        continue

                    response_data["files_read"][norm_path] = content
                    total_content_size += len(content)

                except (OSError, ValueError) as e:
                    # Use the original path in the error if normalization fails
                    error_key = str(base_dir / fp)
                    response_data["errors"][error_key] = str(e)

            # Return a JSON string, which is much easier for the LLM to parse reliably
            return json.dumps(response_data, indent=2)
            
        elif func_name == "create_file": 
            create_file(args["file_path"], args["content"])
            return f"File '{args['file_path']}' created/updated."
            
        elif func_name == "create_multiple_files":
            created: List[str] = []
            errors: List[str] = []
            for f_info in args["files"]:
                try: 
                    create_file(f_info["path"], f_info["content"])
                    created.append(f_info["path"])
                except Exception as e: 
                    errors.append(f"Error creating {f_info.get('path','?path')}: {e}")
            res_parts = []
            if created: 
                res_parts.append(f"Created/updated {len(created)} files: {', '.join(created)}")
            if errors: 
                res_parts.append(f"Errors: {'; '.join(errors)}")
            return ". ".join(res_parts) if res_parts else "No files processed."
            
        elif func_name == "edit_file":
            fp = args["file_path"]
            if not ensure_file_in_context(fp): 
                return f"Error: Could not read '{fp}' for editing."
            try: 
                apply_fuzzy_diff_edit(fp, args["original_snippet"], args["new_snippet"])
                return f"Edit applied successfully to '{fp}'. Check console for details."
            except Exception as e:
                return f"Error during edit_file call for '{fp}': {e}."
                
        elif func_name == "git_init": 
            return llm_git_init()
        elif func_name == "git_add": 
            return llm_git_add(args.get("file_paths", []))
        elif func_name == "git_commit": 
            return llm_git_commit(args.get("message", "Auto commit"))
        elif func_name == "git_create_branch": 
            return llm_git_create_branch(args.get("branch_name", ""))
        elif func_name == "git_status": 
            return llm_git_status()
        elif func_name == "run_powershell":
            command = args["command"]
            
            # SECURITY GATE
            if security_context["require_powershell_confirmation"]:
                console.print(Panel(
                    f"The assistant wants to run this PowerShell command:\n\n[bold yellow]{command}[/bold yellow]", 
                    title="🚨 Security Confirmation Required", 
                    border_style="red"
                ))
                confirm = prompt_session.prompt("🔵 Do you want to allow this command to run? (y/N): ", default="n").strip().lower()
                
                if confirm not in ["y", "yes"]:
                    console.print("[red]Execution denied by user.[/red]")
                    return "PowerShell command execution was denied by the user."
            
            output, error = run_powershell_command(command)
            if error:
                return f"PowerShell Error:\n{error}"
            return f"PowerShell Output:\n{output}"
        elif func_name == "run_bash":
            command = args["command"]
            
            # SECURITY GATE
            if security_context["require_bash_confirmation"]:
                console.print(Panel(
                    f"The assistant wants to run this bash command:\n\n[bold yellow]{command}[/bold yellow]", 
                    title="🚨 Security Confirmation Required", 
                    border_style="red"
                ))
                confirm = prompt_session.prompt("🔵 Do you want to allow this command to run? (y/N): ", default="n").strip().lower()
                
                if confirm not in ["y", "yes"]:
                    console.print("[red]Execution denied by user.[/red]")
                    return "Bash command execution was denied by the user."
            
            output, error = run_bash_command(command)
            if error:
                return f"Bash Error:\n{error}"
            return f"Bash Output:\n{output}"
        else: 
            return f"Unknown LLM function: {func_name}"
            
    except json.JSONDecodeError as e: 
        console.print(f"[red]JSON Decode Error for {func_name}: {e}\nArgs: {tool_call_dict.get('function',{}).get('arguments','')}[/red]")
        return f"Error: Invalid JSON args for {func_name}."
    except KeyError as e: 
        console.print(f"[red]KeyError in {func_name}: Missing key {e}[/red]")
        return f"Error: Missing param for {func_name} (KeyError: {e})."
    except Exception as e: 
        console.print(f"[red]Unexpected Error in LLM func '{func_name}':[/red]")
        console.print_exception()
        return f"Unexpected error in {func_name}: {e}"

# -----------------------------------------------------------------------------
# 14. MAIN LOOP & ENTRY POINT
# -----------------------------------------------------------------------------

def main_loop() -> None:
    """Main application loop."""
    global conversation_history

    while True:
        try:
            prompt_indicator = get_prompt_indicator()
            user_input = prompt_session.prompt(f"{prompt_indicator} You: ")
            
            if not user_input.strip(): 
                continue

            # Handle commands
            if try_handle_add_command(user_input): continue
            if try_handle_git_add_command(user_input): continue
            if try_handle_commit_command(user_input): continue
            if try_handle_git_command(user_input): continue
            if try_handle_git_info_command(user_input): continue
            if try_handle_r1_command(user_input): continue
            if try_handle_reasoner_command(user_input): continue
            if try_handle_clear_command(user_input): continue
            if try_handle_clear_context_command(user_input): continue
            if try_handle_context_command(user_input): continue
            if try_handle_folder_command(user_input): continue
            if try_handle_os_command(user_input): continue
            if try_handle_exit_command(user_input): continue
            if try_handle_help_command(user_input): continue
            
            # Add user message to conversation
            conversation_history.append({"role": "user", "content": user_input})
            
            # Check context usage and warn if necessary
            context_info = get_context_usage_info()
            if context_info["critical_limit"] and len(conversation_history) % 10 == 0:  # Warn every 10 messages when critical
                console.print(f"[red]⚠ Context critical: {context_info['token_usage_percent']:.1f}% used. Consider /clear-context or /context for details.[/red]")
            elif context_info["approaching_limit"] and len(conversation_history) % 20 == 0:  # Warn every 20 messages when approaching
                console.print(f"[yellow]⚠ Context high: {context_info['token_usage_percent']:.1f}% used. Use /context for details.[/yellow]")
            
            # Determine which model to use
            current_model = model_context['current_model']
            model_name = "Magistral" if model_context['is_reasoner'] else "Mistral Medium"

            
            # Make API call
            with console.status(f"[bold yellow]{model_name} is thinking...[/bold yellow]", spinner="dots"):
                response_stream = client.chat.completions.create(
                    model=current_model,
                    messages=conversation_history, # type: ignore
                    tools=tools, # type: ignore
                    tool_choice="auto",
                    stream=True,
                    max_completion_tokens=5000,
                    temperature=0.7,
                    top_p=1
                )
            
            # Process streaming response
            full_response_content = ""
            accumulated_tool_calls: List[Dict[str, Any]] = []

            console.print(f"[bold bright_magenta]🤖 {model_name}:[/bold bright_magenta] ", end="")
            for chunk in response_stream:
                if chunk.choices[0].delta.content:
                    content_part = chunk.choices[0].delta.content
                    # Strip <think> and </think> tags from the content
                    content_part = content_part.replace("<think>", "").replace("</think>", "")
                    console.print(content_part, end="", style="bright_magenta")
                    full_response_content += content_part
                
                if chunk.choices[0].delta.tool_calls:
                    for tool_call_chunk in chunk.choices[0].delta.tool_calls:
                        idx = tool_call_chunk.index
                        while len(accumulated_tool_calls) <= idx:
                            accumulated_tool_calls.append({"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                        
                        current_tool_dict = accumulated_tool_calls[idx]
                        if tool_call_chunk.id: 
                            current_tool_dict["id"] = tool_call_chunk.id
                        if tool_call_chunk.function:
                            if tool_call_chunk.function.name: 
                                current_tool_dict["function"]["name"] = tool_call_chunk.function.name
                            if tool_call_chunk.function.arguments: 
                                current_tool_dict["function"]["arguments"] += tool_call_chunk.function.arguments
            console.print()

            # Always add assistant message to maintain conversation flow
            assistant_message: Dict[str, Any] = {"role": "assistant"}
            
            # Always include content (even if empty) to maintain conversation flow
            assistant_message["content"] = full_response_content

            # Validate and add tool calls if any
            valid_tool_calls = validate_tool_calls(accumulated_tool_calls)
            if valid_tool_calls:
                assistant_message["tool_calls"] = valid_tool_calls
            
            # Always add the assistant message (maintains conversation flow)
            conversation_history.append(assistant_message)

            # Execute tool calls and allow assistant to continue naturally
            if valid_tool_calls:
                # Execute all tool calls first
                for tool_call_to_exec in valid_tool_calls: 
                    console.print(Panel(
                        f"[bold blue]Calling:[/bold blue] {tool_call_to_exec['function']['name']}\n"
                        f"[bold blue]Args:[/bold blue] {tool_call_to_exec['function']['arguments']}",
                        title="🛠️ Function Call", border_style="yellow", expand=False
                    ))
                    tool_output = execute_function_call_dict(tool_call_to_exec) 
                    console.print(Panel(tool_output, title=f"↪️ Output of {tool_call_to_exec['function']['name']}", border_style="green", expand=False))
                    conversation_history.append({
                        "role": "tool",
                        "tool_call_id": tool_call_to_exec["id"],
                        "name": tool_call_to_exec["function"]["name"],
                        "content": tool_output 
                    })
                
                # Now let the assistant continue with the tool results
                # This creates a natural conversation flow where the assistant processes the results
                max_continuation_rounds = 5
                current_round = 0
                
                while current_round < max_continuation_rounds:
                    current_round += 1
                    
                    with console.status(f"[bold yellow]{model_name} is processing results...[/bold yellow]", spinner="dots"):
                        continue_response_stream = client.chat.completions.create(
                            model=current_model, 
                            messages=conversation_history, # type: ignore
                            tools=tools, # type: ignore
                            tool_choice="auto",
                            stream=True,
                            max_completion_tokens=5000,
                            temperature=0.7,
                            top_p=1
                        )
                    
                    # Process the continuation response
                    continuation_content = ""
                    continuation_tool_calls: List[Dict[str, Any]] = []
                    
                    console.print(f"[bold bright_magenta]🤖 {model_name}:[/bold bright_magenta] ", end="")
                    for chunk in continue_response_stream:
                        if chunk.choices[0].delta.content:
                            content_part = chunk.choices[0].delta.content
                            # Strip <think> and </think> tags from the content
                            content_part = content_part.replace("<think>", "").replace("</think>", "")
                            console.print(content_part, end="", style="bright_magenta")
                            continuation_content += content_part
                        
                        if chunk.choices[0].delta.tool_calls:
                            for tool_call_chunk in chunk.choices[0].delta.tool_calls:
                                idx = tool_call_chunk.index
                                while len(continuation_tool_calls) <= idx:
                                    continuation_tool_calls.append({"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                                
                                current_tool_dict = continuation_tool_calls[idx]
                                if tool_call_chunk.id: 
                                    current_tool_dict["id"] = tool_call_chunk.id
                                if tool_call_chunk.function:
                                    if tool_call_chunk.function.name: 
                                        current_tool_dict["function"]["name"] = tool_call_chunk.function.name
                                    if tool_call_chunk.function.arguments: 
                                        current_tool_dict["function"]["arguments"] += tool_call_chunk.function.arguments
                    console.print()
                    
                    # Add the continuation response to conversation history
                    continuation_message: Dict[str, Any] = {"role": "assistant", "content": continuation_content}
                    
                    # Check if there are more tool calls to execute
                    valid_continuation_tools = validate_tool_calls(continuation_tool_calls)
                    if valid_continuation_tools:
                        continuation_message["tool_calls"] = valid_continuation_tools
                        conversation_history.append(continuation_message)
                        
                        # Execute the additional tool calls
                        for tool_call_to_exec in valid_continuation_tools:
                            console.print(Panel(
                                f"[bold blue]Calling:[/bold blue] {tool_call_to_exec['function']['name']}\n"
                                f"[bold blue]Args:[/bold blue] {tool_call_to_exec['function']['arguments']}",
                                title="🛠️ Function Call", border_style="yellow", expand=False
                            ))
                            tool_output = execute_function_call_dict(tool_call_to_exec)
                            console.print(Panel(tool_output, title=f"↪️ Output of {tool_call_to_exec['function']['name']}", border_style="green", expand=False))
                            conversation_history.append({
                                "role": "tool",
                                "tool_call_id": tool_call_to_exec["id"],
                                "name": tool_call_to_exec["function"]["name"],
                                "content": tool_output
                            })
                        
                        # Continue the loop to let assistant process these new results
                        continue
                    else:
                        # No more tool calls, add the final response and break
                        conversation_history.append(continuation_message)
                        break
                
                # If we hit the max rounds, warn about it
                if current_round >= max_continuation_rounds:
                    console.print(f"[yellow]⚠ Reached maximum continuation rounds ({max_continuation_rounds}). Conversation continues.[/yellow]")
            
            # Smart truncation that preserves tool call sequences
            conversation_history = smart_truncate_history(conversation_history, MAX_HISTORY_MESSAGES)

        except KeyboardInterrupt: 
            console.print("\n[yellow]⚠ Interrupted. Ctrl+D or /exit to quit.[/yellow]")
        except EOFError: 
            console.print("[blue]👋 Goodbye! (EOF)[/blue]")
            sys.exit(0)
        except Exception as e:
            console.print(f"\n[red]✗ Unexpected error in main loop:[/red]")
            console.print_exception(width=None, extra_lines=1, show_locals=True)

def initialize_application() -> None:
    """Initialize the application and check for existing git repository."""
    # Detect available shells
    detect_available_shells()
    
    if Path(".git").exists() and Path(".git").is_dir():
        git_context['enabled'] = True
        try:
            res = subprocess.run(["git", "branch", "--show-current"], cwd=str(Path.cwd()), capture_output=True, text=True, check=False)
            if res.returncode == 0 and res.stdout.strip(): 
                git_context['branch'] = res.stdout.strip()
            else:
                init_branch_res = subprocess.run(["git", "config", "init.defaultBranch"], cwd=str(Path.cwd()), capture_output=True, text=True)
                git_context['branch'] = init_branch_res.stdout.strip() if init_branch_res.returncode == 0 and init_branch_res.stdout.strip() else "main"
        except FileNotFoundError: 
            console.print("[yellow]Git not found. Git features disabled.[/yellow]")
            git_context['enabled'] = False
        except Exception as e: 
            console.print(f"[yellow]Could not get Git branch: {e}.[/yellow]")

def get_directory_tree_summary(root_dir: Path, max_depth: int = 3, max_entries: int = 100) -> str:
    """
    Generate a summary of the directory tree up to a certain depth and entry count.
    """
    lines = []
    entry_count = 0

    def walk(dir_path: Path, prefix: str = "", depth: int = 0):
        nonlocal entry_count
        if depth > max_depth or entry_count >= max_entries:
            return
        try:
            entries = sorted([e for e in dir_path.iterdir() if not e.name.startswith('.')])
        except Exception:
            return
        for entry in entries:
            if entry_count >= max_entries:
                lines.append(f"{prefix}... (truncated)")
                return
            if entry.is_dir():
                lines.append(f"{prefix}{entry.name}/")
                entry_count += 1
                walk(entry, prefix + "  ", depth + 1)
            else:
                lines.append(f"{prefix}{entry.name}")
                entry_count += 1

    walk(root_dir)
    return "\n".join(lines)

def main() -> None:
    """Application entry point."""
    console.print(Panel.fit(
        "[bold bright_blue] Mistral Assistant - Enhanced Edition[/bold bright_blue]\n"
        "[dim]✨ Now with fuzzy matching for files and cross-platform shell support![/dim]\n"
        "[dim]Type /help for commands. Ctrl+C to interrupt, Ctrl+D or /exit to quit.[/dim]",
        border_style="bright_blue"
    ))

    # Show fuzzy matching status on startup
    if FUZZY_AVAILABLE:
        console.print("[green]✓ Fuzzy matching enabled for intelligent file finding and code editing[/green]")
    else:
        console.print("[yellow]⚠ Fuzzy matching disabled. Install with: pip install thefuzz python-levenshtein[/yellow]")

    # Initialize application first (detects git repo and shells)
    initialize_application()
    
    # Show detected shells
    available_shells = [shell for shell, available in os_info['shell_available'].items() if available]
    if available_shells:
        console.print(f"[green]✓ Detected shells: {', '.join(available_shells)}[/green]")
    else:
        console.print("[yellow]⚠ No supported shells detected[/yellow]")
    
    # Initialize the assistant (inherits current global state)
    assistant = MistralAssistant()
    
    # Add directory structure and OS info as system messages
    dir_summary = get_directory_tree_summary(assistant.base_dir)
    assistant.conversation_history.append({
        "role": "system",
        "content": f"Project directory structure at startup:\n\n{dir_summary}"
    })
    
    # Add OS and shell info
    shell_status = ", ".join([f"{shell}({'✓' if available else '✗'})" 
                             for shell, available in os_info['shell_available'].items()])
    assistant.conversation_history.append({
        "role": "system",
        "content": f"Runtime environment: {os_info['system']} {os_info['release']}, "
                  f"Python {os_info['python_version']}, Shells: {shell_status}"
    })

    assistant.main_loop()

if __name__ == "__main__":
    main()