#!/usr/bin/env python3

"""
Main application for Mistral Assistant
Handles commands, conversation flow, and AI interactions
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from textwrap import dedent

# Third-party imports
from cerebras.cloud.sdk import Cerebras
from pydantic import BaseModel
from dotenv import load_dotenv

# Rich console imports
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

# Prompt toolkit imports
from prompt_toolkit import PromptSession
from prompt_toolkit.styles import Style as PromptStyle

# Import our modules
from config import (
    os_info, base_dir, git_context, model_context, security_context,
    ADD_COMMAND_PREFIX, COMMIT_COMMAND_PREFIX, GIT_BRANCH_COMMAND_PREFIX,
    FUZZY_AVAILABLE, DEFAULT_MODEL, REASONER_MODEL, tools, SYSTEM_PROMPT,
    MAX_FILES_IN_ADD_DIR, MAX_FILE_CONTENT_SIZE_CREATE, EXCLUDED_FILES, EXCLUDED_EXTENSIONS
)
from utils import (
    console, detect_available_shells, get_context_usage_info, smart_truncate_history,
    validate_tool_calls, get_prompt_indicator, normalize_path, is_binary_file,
    read_local_file, add_file_context_smartly, find_best_matching_file,
    apply_fuzzy_diff_edit, run_bash_command, run_powershell_command,
    get_directory_tree_summary
)

# Initialize Cerebras client
load_dotenv()
client = Cerebras(api_key=os.getenv("CEREBRAS_API_KEY"))

# Initialize prompt session
prompt_session = PromptSession(
    style=PromptStyle.from_dict({
        'prompt': '#0066ff bold',
        'completion-menu.completion': 'bg:#1e3a8a fg:#ffffff',
        'completion-menu.completion.current': 'bg:#3b82f6 fg:#ffffff bold',
    })
)

# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class FileToCreate(BaseModel):
    path: str
    content: str

class FileToEdit(BaseModel):
    path: str
    original_snippet: str
    new_snippet: str

# =============================================================================
# FILE OPERATIONS
# =============================================================================

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

def add_directory_to_conversation(directory_path: str, conversation_history: List[Dict[str, Any]]) -> None:
    """
    Add all files from a directory to the conversation context.
    
    Args:
        directory_path: Path to directory to scan
        conversation_history: Conversation history to add files to
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
                if (file.startswith('.') or 
                    file in EXCLUDED_FILES or 
                    os.path.splitext(file)[1] in EXCLUDED_EXTENSIONS):
                    continue
                    
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

# =============================================================================
# GIT OPERATIONS
# =============================================================================

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
        console.print(f"[yellow]⚠ File {file_path_str} outside repo ({Path.cwd()}), skipping staging[/yellow]")
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
                if len(line) >= 2 and line[1] == ' ':
                    status_code = line[:2]
                    filename = line[2:]
                else:
                    parts = line.split(' ', 1)
                    if len(parts) == 2:
                        status_code = parts[0].ljust(2)
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

# =============================================================================
# COMMAND HANDLERS
# =============================================================================

def try_handle_add_command(user_input: str, conversation_history: List[Dict[str, Any]]) -> bool:
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
                add_directory_to_conversation(normalized_path, conversation_history)
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
    if not git_context['enabled']:
        console.print("[yellow]Git not enabled. Use `/git init` first.[/yellow]")
        return True

    message = user_input[len(COMMIT_COMMAND_PREFIX):].strip()

    if not message:
        try:
            message = prompt_session.prompt("🔵 Enter commit message: ").strip()
            if not message:
                console.print("[yellow]Commit aborted. Message cannot be empty.[/yellow]")
                return True
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Commit aborted by user.[/yellow]")
            return True

    user_commit_changes(message)
    return True

def try_handle_git_add_command(user_input: str) -> bool:
    """Handle the /git add command for staging files."""
    GIT_ADD_COMMAND_PREFIX = "/git add "
    
    if user_input.strip().lower().startswith(GIT_ADD_COMMAND_PREFIX.strip()):
        if not git_context['enabled']:
            console.print("[yellow]Git not enabled. Use `/git init` first.[/yellow]")
            return True
            
        files_to_add_str = user_input[len(GIT_ADD_COMMAND_PREFIX):].strip()
        if not files_to_add_str:
            console.print("[yellow]Usage: /git add <file1> <file2> ... or /git add .[/yellow]")
            return True
            
        file_paths = files_to_add_str.split()
        
        staged_ok: List[str] = []
        failed_stage: List[str] = []
        
        for fp_str in file_paths:
            if fp_str == ".":
                try:
                    subprocess.run(["git", "add", "."], cwd=str(base_dir), check=True, capture_output=True)
                    console.print("[green]✓ Staged all changes in the current directory.[/green]")
                    return True
                except subprocess.CalledProcessError as e:
                    console.print(f"[red]✗ Failed to stage all changes: {e.stderr}[/red]")
                    return True

            try:
                if stage_file(fp_str):
                    staged_ok.append(fp_str)
                else:
                    failed_stage.append(fp_str)
            except Exception as e:
                failed_stage.append(f"{fp_str} (error: {e})")
        
        if staged_ok:
            console.print(f"[green]✓ Staged:[/green] {', '.join(staged_ok)}")
        if failed_stage:
            console.print(f"[yellow]⚠ Failed to stage:[/yellow] {', '.join(failed_stage)}")
        
        show_git_status_cmd()
        return True
        
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

# All other command handlers...
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

def try_handle_r1_command(user_input: str, conversation_history: List[Dict[str, Any]]) -> bool:
    """Handle /r command for one-off reasoner calls."""
    if user_input.strip().lower() == "/r":
        try:
            user_prompt = prompt_session.prompt("🔵 Enter your reasoning prompt: ").strip()
            if not user_prompt:
                console.print("[yellow]No input provided. Aborting.[/yellow]")
                return True
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Cancelled.[/yellow]")
            return True
        
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
            
            full_response_content = ""
            accumulated_tool_calls = []
            
            console.print("[bold bright_magenta]🧠 Magistral:[/bold bright_magenta] ", end="")
            for chunk in response_stream:
                if chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    content = content.replace("<think>", "").replace("</think>", "")
                    console.print(content, end="", style="bright_magenta")
                    full_response_content += content
                
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
            
            conversation_history.append({"role": "user", "content": user_prompt})
            assistant_message = {"role": "assistant", "content": full_response_content}
            
            valid_tool_calls = validate_tool_calls(accumulated_tool_calls)
            if valid_tool_calls:
                assistant_message["tool_calls"] = valid_tool_calls
                console.print("[dim]Note: R1 reasoner made tool calls. Executing...[/dim]")
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

def try_handle_clear_context_command(user_input: str, conversation_history: List[Dict[str, Any]]) -> bool:
    """Handle /clear-context command to clear conversation history."""
    if user_input.strip().lower() == "/clear-context":
        if len(conversation_history) <= 1:
            console.print("[yellow]Context already empty (only system prompt).[/yellow]")
            return True
            
        file_contexts = sum(1 for msg in conversation_history if msg["role"] == "system" and "User added file" in msg["content"])
        total_messages = len(conversation_history) - 1
        
        console.print(f"[yellow]Current context: {total_messages} messages, {file_contexts} file contexts[/yellow]")
        
        confirm = prompt_session.prompt("🔵 Clear conversation context? This cannot be undone (y/n): ").strip().lower()
        if confirm in ["y", "yes"]:
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

def try_handle_context_command(user_input: str, conversation_history: List[Dict[str, Any]]) -> bool:
    """Handle /context command to show context usage statistics."""
    if user_input.strip().lower() == "/context":
        context_info = get_context_usage_info(conversation_history)
        
        context_table = Table(title="📊 Context Usage Statistics", show_header=True, header_style="bold bright_blue")
        context_table.add_column("Metric", style="bright_cyan")
        context_table.add_column("Value", style="white")
        context_table.add_column("Status", style="white")
        
        context_table.add_row("Total Messages", str(context_info["total_messages"]), "📝")
        context_table.add_row("Estimated Tokens", f"{context_info['estimated_tokens']:,}", f"{context_info['token_usage_percent']:.1f}% of {context_info['estimated_tokens']:,}")
        context_table.add_row("File Contexts", str(context_info["file_contexts"]), f"Max: 5")
        
        if context_info["critical_limit"]:
            status_color = "red"
            status_text = "🔴 Critical - aggressive truncation active"
        elif context_info["approaching_limit"]:
            status_color = "yellow"
            status_text = "🟡 Warning - approaching limits"
        else:
            status_color = "green"
            status_text = "🟢 Healthy - plenty of space"
        
        context_table.add_row("Context Health", status_text, "")
        console.print(context_table)
        
        if context_info["token_breakdown"]:
            breakdown_table = Table(title="📋 Token Breakdown by Role", show_header=True, header_style="bold bright_blue", border_style="blue")
            breakdown_table.add_column("Role", style="bright_cyan")
            breakdown_table.add_column("Tokens", style="white")
            breakdown_table.add_column("Percentage", style="white")