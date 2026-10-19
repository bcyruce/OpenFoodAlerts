"""Prompt files: `prompts/{task}/vN.md` in git (spec §6.3).

- The prompt version is the file name without `.md` ("v1"); a new version is a new file,
  never an edit of an old one, because cached outputs and `ai_classifications` rows name
  the version they were made with.
- A leading `<!-- ... -->` block holds maintainer notes and is removed; the rest is the
  system prompt, sent unchanged on every request so that the provider caches it as one
  prefix (the fixed part: task, category list, rules and few-shot examples).
- For checks, the file is also parsed: the category list (lines "- `name`: definition"
  under "## Categories") and the few-shot examples (an "Input: {json}" line followed by an
  "Output: {json}" line, under "## Examples").
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_VERSION = re.compile(r"^v(\d+)$")
_COMMENT = re.compile(r"\A\s*<!--.*?-->\s*", re.DOTALL)
_CATEGORY = re.compile(r"^- `([^`]+)`: ", re.MULTILINE)
_EXAMPLE = re.compile(r"^Input: (.+)\nOutput: (.+)$", re.MULTILINE)


class PromptError(ValueError):
    """A missing or malformed prompt file."""


@dataclass(frozen=True)
class Example:
    source: str
    input: dict[str, str]
    output: dict[str, Any]


@dataclass(frozen=True)
class Prompt:
    task: str
    version: str
    path: Path
    system: str
    categories: tuple[str, ...]
    examples: tuple[Example, ...]


def default_prompts_dir() -> Path:
    # prompts.py -> classify -> openfoodalerts -> src -> pipeline -> repo root
    return Path(__file__).resolve().parents[4] / "prompts"


def _versions(task: str, directory: Path) -> list[tuple[int, str]]:
    found = []
    for path in (directory / task).glob("v*.md"):
        match = _VERSION.match(path.stem)
        if match:
            found.append((int(match.group(1)), path.stem))
    return sorted(found)


def latest_version(task: str, directory: Path | None = None) -> str:
    versions = _versions(task, directory or default_prompts_dir())
    if not versions:
        raise PromptError(f"no prompt for task {task!r} (expected prompts/{task}/vN.md)")
    return versions[-1][1]


def _section(text: str, heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return match.group(1) if match else ""


def _examples(text: str, path: Path) -> tuple[Example, ...]:
    examples = []
    for n, match in enumerate(_EXAMPLE.finditer(_section(text, "Examples")), start=1):
        try:
            request, output = json.loads(match.group(1)), json.loads(match.group(2))
        except json.JSONDecodeError as exc:
            raise PromptError(f"{path.name}: example {n} is not JSON ({exc.msg})") from exc
        examples.append(Example(request["source"], request["input"], output))
    return tuple(examples)


def load_prompt(task: str, version: str | None = None, *, directory: Path | None = None) -> Prompt:
    directory = directory or default_prompts_dir()
    version = version or latest_version(task, directory)
    path = directory / task / f"{version}.md"
    if not _VERSION.match(version) or not path.is_file():
        raise PromptError(f"no prompt {task}/{version}.md in {directory}")
    raw = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    system = _COMMENT.sub("", raw, count=1).strip() + "\n"
    categories = tuple(_CATEGORY.findall(_section(system, "Categories")))
    return Prompt(task, version, path, system, categories, _examples(system, path))
