"""Config loading + resolution.

decision #114 (D1) — LAYERED MERGE, not pick-first. Old behavior tried
candidates in priority order and used the first file that existed whole —
which meant a global `~/.config/aitask/config.json` (if present) fully
shadowed a project's `.claude/aitask-config.json`, so per-project
`project_id` could never be reached. Now layers merge, later wins:

  1. `~/.config/aitask/config.json` (XDG global — base_url + token/username
     shared across every project on this machine)
  2. project layer, exactly ONE of (first found wins, NOT merged together):
       a. explicit `--config /path/to/config.json` (CLI flag)
       b. `AITASK_CONFIG` env var
       c. walk up from cwd for `.claude/aitask-config.json`
     (typically just `project_id` — everything else inherits from global)
  3. env var overrides (`AITASK_TOKEN` / `AITASK_BASE_URL` / ...) — always win

This is what makes `aitask setup` (once per machine, global) +
`aitask init -p <project>` (once per project, just project_id) work
together — see `cmd_setup` / `cmd_init` in cli.py.

Env overrides applied on top of any source:
  * `AITASK_TOKEN` — Bearer session_id (skip username/password login)
  * `AITASK_BASE_URL`
  * `AITASK_PROJECT_ID`

Config schema (JSON):
  {
    "base_url":      "http://localhost:5173",
    "project_id":    34,
    "project_slug":  "aicodetask",   # optional, used by URL builder
    "username":      "claude",       # fallback when no token
    "password":      "...",
    "token":         "<session_id>", # optional, overrides login
    "tasks_module":  "tasks",
    "docs_module":   "documents"
  }
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class AiTaskConfig:
    base_url: str
    project_id: Optional[int] = None  # optional so `aitask projects` works without one
    project_slug: Optional[str] = None
    tasks_module: str = "tasks"
    docs_module: str = "documents"
    username: Optional[str] = None
    password: Optional[str] = None
    token: Optional[str] = None
    source_path: Optional[Path] = None  # for error messages

    def save_token(self, token: str) -> Path:
        """Write `token` field to source_path config file, preserving other
        keys. Returns the path written. Raises if no source_path
        (env-only config — caller should print AITASK_TOKEN= line for user)."""
        if not self.source_path:
            raise ValueError(
                "Cannot save token: config was loaded from env vars only "
                "(no source file). Set --config or AITASK_CONFIG to a "
                "writable JSON path, or use the printed AITASK_TOKEN value "
                "manually in your env."
            )
        # Load → mutate → write to preserve unknown keys + formatting style
        try:
            with open(self.source_path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            data = {}
        data["token"] = token
        self.source_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self.token = token  # in-memory sync
        return self.source_path

    def remove_token(self) -> Optional[Path]:
        """Remove `token` field from source_path config. Returns path or None
        when no source_path (env-only) — caller decides if that's an error."""
        if not self.source_path or not self.source_path.is_file():
            self.token = None
            return None
        with open(self.source_path, encoding="utf-8") as f:
            data = json.load(f)
        if data.pop("token", None) is not None:
            self.source_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        self.token = None
        return self.source_path

    @classmethod
    def from_dict(cls, data: dict, *, source_path: Optional[Path] = None) -> "AiTaskConfig":
        # Accept either int or str for project_id (env strings coerce here)
        pid = data.get("project_id")
        if isinstance(pid, str):
            pid = int(pid) if pid.strip() else None
        elif pid is not None:
            pid = int(pid)
        return cls(
            base_url=str(data["base_url"]).rstrip("/"),
            project_id=pid,
            project_slug=data.get("project_slug"),
            tasks_module=data.get("tasks_module", "tasks"),
            docs_module=data.get("docs_module", "documents"),
            username=data.get("username"),
            password=data.get("password"),
            token=data.get("token"),
            source_path=source_path,
        )


def global_config_path() -> Path:
    """The one machine-wide config file — `aitask setup` writes here."""
    return Path.home() / ".config" / "aitask" / "config.json"


def _project_candidate_paths(explicit: Optional[str]) -> list[Path]:
    """Ordered project-layer candidates (first EXISTING one wins — these are
    NOT merged with each other, only with the global layer)."""
    paths: list[Path] = []
    if explicit:
        paths.append(Path(explicit).expanduser().resolve())
    env_path = os.environ.get("AITASK_CONFIG")
    if env_path:
        paths.append(Path(env_path).expanduser().resolve())
    # Walk up from cwd for `.claude/aitask-config.json`
    cur = Path.cwd().resolve()
    for _ in range(20):  # bounded walk
        candidate = cur / ".claude" / "aitask-config.json"
        paths.append(candidate)
        if cur.parent == cur:
            break
        cur = cur.parent
    return paths


def load_config(explicit_path: Optional[str] = None) -> AiTaskConfig:
    """Load + merge config: global (base) ← project (override) ← env (top).

    See module docstring for the layering rationale (decision #114 D1).
    `source_path` on the returned config is the project-layer file when one
    was found (so `login --save` / `setup` write to the more specific file),
    else the global file, else None (env-only).

    Raises FileNotFoundError listing tried paths if nothing found anywhere.
    """
    merged: dict = {}
    source: Optional[Path] = None
    tried: list[Path] = []

    global_path = global_config_path()
    tried.append(global_path)
    if global_path.is_file():
        with open(global_path, encoding="utf-8") as f:
            merged.update(json.load(f))
        source = global_path

    project_path: Optional[Path] = None
    for p in _project_candidate_paths(explicit_path):
        tried.append(p)
        if p.is_file():
            project_path = p
            break
    if project_path:
        with open(project_path, encoding="utf-8") as f:
            merged.update(json.load(f))
        source = project_path  # project layer is the more specific write target

    if not merged:
        # Maybe env vars alone provide enough — allow fully env-driven config
        if os.environ.get("AITASK_BASE_URL") and os.environ.get("AITASK_PROJECT_ID"):
            source = None
        else:
            tried_str = "\n  - ".join(str(p) for p in tried)
            raise FileNotFoundError(
                f"aitask config not found. Run `aitask setup` to bootstrap a "
                f"global config, then `aitask init -p <project>` per project. "
                f"Or set AITASK_CONFIG env var / pass --config. Tried:\n  - {tried_str}"
            )

    # Env overrides — always win, on top of the merged file layers
    if v := os.environ.get("AITASK_BASE_URL"):
        merged["base_url"] = v
    if v := os.environ.get("AITASK_PROJECT_ID"):
        merged["project_id"] = v
    if v := os.environ.get("AITASK_TOKEN"):
        merged["token"] = v
    if v := os.environ.get("AITASK_USERNAME"):
        merged["username"] = v
    if v := os.environ.get("AITASK_PASSWORD"):
        merged["password"] = v
    # base_url is the only hard requirement. project_id is validated per
    # subcommand — the `projects` discovery subcommand works without one.
    if "base_url" not in merged:
        raise ValueError("aitask config: base_url required (env AITASK_BASE_URL or config file)")

    return AiTaskConfig.from_dict(merged, source_path=source)
