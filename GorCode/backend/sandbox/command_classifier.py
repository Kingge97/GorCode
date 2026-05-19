"""
Shell command behavior classification for the default sandbox.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from typing import List, Optional


READ_ONLY_COMMANDS = {
    "cat",
    "type",
    "get-content",
    "gc",
    "ls",
    "dir",
    "grep",
    "rg",
    "findstr",
    "select-string",
    "pwd",
    "echo",
    "where",
    "which",
    "head",
    "tail",
}
DELETE_COMMANDS = {"rm", "del", "erase", "remove-item"}
MOVE_COMMANDS = {"mv", "move", "ren", "rename-item", "move-item"}
COPY_COMMANDS = {"cp", "copy", "copy-item"}
WRITE_COMMANDS = {"set-content", "out-file", "add-content", "tee"}
SCRIPT_RUNNERS = {"python", "python3", "py", "node", "bash", "sh", "pwsh", "powershell"}


@dataclass(frozen=True)
class CommandTarget:
    """A path target discovered in a command."""

    path: str
    role: str = "target"


@dataclass(frozen=True)
class CommandClassification:
    """Classified shell command behavior."""

    category: str
    operation: str
    targets: List[CommandTarget] = field(default_factory=list)
    reason: str = ""


def classify_command(command: str) -> CommandClassification:
    """Classify a shell command for sandbox evaluation."""
    if _has_redirection(command):
        return _classify_redirection(command)
    tokens = _split(command)
    if not tokens:
        return CommandClassification("read_only", "read", reason="empty command")
    command_name = _command_name(tokens[0])
    if command_name in READ_ONLY_COMMANDS:
        return CommandClassification("read_only", "read", reason=command_name)
    if command_name in DELETE_COMMANDS or _has_find_delete(tokens):
        return _classify_delete(tokens)
    if command_name in MOVE_COMMANDS:
        return _classify_move(tokens)
    if command_name in COPY_COMMANDS:
        return _classify_copy(tokens)
    if command_name in WRITE_COMMANDS:
        return _classify_write_command(tokens)
    if _has_inplace_edit(tokens):
        return _classify_inplace_edit(tokens)
    if _runs_script_with_unknown_effect(command_name, tokens):
        return CommandClassification(
            "unknown_mutation",
            "execute",
            reason=f"{command_name} script effects are unknown",
        )
    if _has_write_keyword(tokens):
        return CommandClassification("unknown_mutation", "execute", reason="write-like command")
    return CommandClassification("read_only", "read", reason="no mutation signals")


def _split(command: str) -> List[str]:
    lexer = shlex.shlex(command, posix=False)
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        return [token.strip("'\"") for token in lexer]
    except ValueError:
        return []


def _command_name(token: str) -> str:
    return token.strip("'\"").split("/")[-1].split("\\")[-1].lower()


def _has_redirection(command: str) -> bool:
    return bool(re.search(r"(?<![<])>{1,2}\s*[^&\s]", command))


def _classify_redirection(command: str) -> CommandClassification:
    match = re.search(r">{1,2}\s*(?P<path>(?:\"[^\"]+\"|'[^']+'|[^\s&|;]+))", command)
    target = _clean_path(match.group("path")) if match else ""
    targets = [CommandTarget(target)] if target else []
    return CommandClassification("write_file", "write", targets, "shell redirection")


def _classify_delete(tokens: List[str]) -> CommandClassification:
    paths = _path_args(tokens[1:])
    targets = [CommandTarget(path) for path in paths]
    return CommandClassification("delete", "delete", targets, "delete command")


def _classify_move(tokens: List[str]) -> CommandClassification:
    paths = _path_args(tokens[1:])
    if len(paths) < 2:
        return CommandClassification("unknown_mutation", "move", reason="missing move target")
    targets = [CommandTarget(paths[0], "source"), CommandTarget(paths[-1], "target")]
    return CommandClassification("move_copy", "move", targets, "move command")


def _classify_copy(tokens: List[str]) -> CommandClassification:
    paths = _path_args(tokens[1:])
    if len(paths) < 2:
        return CommandClassification("unknown_mutation", "copy", reason="missing copy target")
    targets = [CommandTarget(paths[-1], "target")]
    return CommandClassification("move_copy", "copy", targets, "copy command")


def _classify_write_command(tokens: List[str]) -> CommandClassification:
    target = _extract_named_path(tokens) or _positional_write_target(tokens)
    targets = [CommandTarget(target)] if target else []
    return CommandClassification("write_file", "write", targets, "write command")


def _classify_inplace_edit(tokens: List[str]) -> CommandClassification:
    target = _last_path_arg(tokens[1:])
    targets = [CommandTarget(target)] if target else []
    return CommandClassification("edit_file", "edit", targets, "in-place edit")


def _path_args(tokens: List[str]) -> List[str]:
    return [_clean_path(token) for token in tokens if _looks_like_path_arg(token)]


def _last_path_arg(tokens: List[str]) -> Optional[str]:
    paths = _path_args(tokens)
    return paths[-1] if paths else None


def _first_path_arg(tokens: List[str]) -> Optional[str]:
    paths = _path_args(tokens)
    return paths[0] if paths else None


def _positional_write_target(tokens: List[str]) -> Optional[str]:
    command_name = _command_name(tokens[0])
    if command_name in {"set-content", "add-content"}:
        return _first_path_arg(tokens[1:])
    return _last_path_arg(tokens[1:])


def _extract_named_path(tokens: List[str]) -> Optional[str]:
    names = {"-path", "-filepath", "-literalpath", "-file", "-destination"}
    for index, token in enumerate(tokens[:-1]):
        if token.lower() in names:
            return _clean_path(tokens[index + 1])
    return None


def _looks_like_path_arg(token: str) -> bool:
    clean = _clean_path(token)
    if not clean or clean.startswith("-"):
        return False
    return clean not in {"|", "&&", "||", ";"}


def _clean_path(token: str) -> str:
    return token.strip().strip("'\"")


def _has_find_delete(tokens: List[str]) -> bool:
    return _command_name(tokens[0]) == "find" and "-delete" in [t.lower() for t in tokens]


def _has_inplace_edit(tokens: List[str]) -> bool:
    lowered = [token.lower() for token in tokens]
    return _command_name(tokens[0]) == "sed" and "-i" in lowered


def _runs_script_with_unknown_effect(command_name: str, tokens: List[str]) -> bool:
    if command_name not in SCRIPT_RUNNERS or len(tokens) < 2:
        return False
    first_arg = tokens[1].lower()
    if first_arg in {"-m", "-c", "/c"}:
        return first_arg == "-c"
    return _looks_like_path_arg(tokens[1])


def _has_write_keyword(tokens: List[str]) -> bool:
    joined = " ".join(token.lower() for token in tokens)
    keywords = ["install", "write", "create", "touch", "mkdir", "new-item", "chmod"]
    return any(keyword in joined for keyword in keywords)
