"""AiTaskClient — pure-stdlib REST client for the AiCodeTask API.

Uses urllib + http.cookiejar. ZERO external deps so it works on any
Python 3.10+ install (including embedded Pythons used by AI agents).

Auth strategy:
  * If `token` is provided (or AITASK_TOKEN env), used directly as Bearer
    header — no login round-trip.
  * Otherwise, on first call, POST /api/auth/login with username/password
    and cache the returned session_id as the token for subsequent calls
    (stateless from caller's view).

Error handling: HTTPError → RuntimeError with status code + truncated body.
Callers can wrap with try/except in CLI / MCP layer.
"""
from __future__ import annotations

import http.cookiejar
import json
import urllib.error
import urllib.request
from typing import Any, Optional

from .config import AiTaskConfig


class AiTaskError(RuntimeError):
    """Raised for non-2xx HTTP responses or malformed payloads."""
    def __init__(self, message: str, *, status: Optional[int] = None,
                 body: Optional[str] = None):
        super().__init__(message)
        self.status = status
        self.body = body


class AiTaskClient:
    """Thin REST client for an AiCodeTask project (tasks + documents modules).

    Usage:
        cfg = load_config()
        client = AiTaskClient.from_config(cfg)
        tasks = client.list_tasks()

    Or construct directly:
        client = AiTaskClient(base_url=..., project_id=..., token=...)
    """

    def __init__(
        self,
        *,
        base_url: str,
        project_id: Optional[int] = None,
        tasks_module: str = "tasks",
        docs_module: str = "documents",
        token: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.project_id = project_id
        self.tasks_module = tasks_module
        self.docs_module = docs_module
        self._token = token
        self._username = username
        self._password = password
        self._jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._jar)
        )
        self._logged_in = bool(token)

    @classmethod
    def from_config(cls, cfg: AiTaskConfig) -> "AiTaskClient":
        return cls(
            base_url=cfg.base_url,
            project_id=cfg.project_id,
            tasks_module=cfg.tasks_module,
            docs_module=cfg.docs_module,
            token=cfg.token,
            username=cfg.username,
            password=cfg.password,
        )

    # ── HTTP layer ──────────────────────────────────────────────────────

    def _request(self, method: str, path: str, body: Any = None,
                 *, skip_auth: bool = False, _retried: bool = False) -> Any:
        if not skip_auth:
            self._ensure_logged_in()
        url = self.base_url + path
        data = (
            json.dumps(body, ensure_ascii=False).encode("utf-8")
            if body is not None else None
        )
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with self._opener.open(req) as r:
                raw = r.read().decode("utf-8")
                if not raw:
                    return None
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            body_err = e.read().decode("utf-8", errors="replace")
            # dev8 #67: auto re-login on 401/403 when we have username/
            # password to fall back on. 401 = token rejected; 403 = backend
            # treated us as anonymous (bogus/expired token resolves to a
            # non-existent session → request.state.user_id=None → perm
            # check fails). Single-shot retry; if even fresh login still
            # gets the same error, surface it (probably a real perm issue).
            if (e.code in (401, 403) and not _retried and not skip_auth
                    and self._username and self._password):
                self._token = None
                self._logged_in = False
                self._ensure_logged_in()
                return self._request(method, path, body,
                                     skip_auth=skip_auth, _retried=True)
            raise AiTaskError(
                f"HTTP {e.code} {method} {path}: {body_err[:500]}",
                status=e.code, body=body_err,
            ) from None
        except urllib.error.URLError as e:
            raise AiTaskError(
                f"Connection failed for {method} {path}: {e.reason}"
            ) from None

    def _ensure_logged_in(self) -> None:
        if self._logged_in or self._token:
            return
        if not (self._username and self._password):
            raise AiTaskError(
                "No auth provided. Set `token` (Bearer session_id) or "
                "`username`+`password` in config."
            )
        resp = self._request(
            "POST", "/api/auth/login",
            {"name": self._username, "password": self._password},
            skip_auth=True,
        )
        if isinstance(resp, dict) and resp.get("session_id"):
            # Use returned session_id as bearer token for subsequent calls
            self._token = resp["session_id"]
        self._logged_in = True

    # ── Auth helpers (no project_id needed) ─────────────────────────────

    def logout(self) -> bool:
        """POST /api/auth/logout to invalidate the current session_id on the
        server. Best-effort: ignores HTTP errors (server may have already
        forgotten the session). Always clears in-memory auth state.
        Returns True if the server call succeeded, False otherwise."""
        if not self._token and not self._logged_in:
            return False
        ok = True
        try:
            self._request("POST", "/api/auth/logout", {}, skip_auth=True)
        except AiTaskError:
            ok = False
        self._token = None
        self._logged_in = False
        # Clear cookies too
        self._jar.clear()
        return ok

    def login_explicit(self, username: str, password: str) -> dict:
        """Force a login with explicit creds, ignoring any cached token.
        Returns the full /api/auth/login response (including session_id +
        user dict). Used by `aitask login` subcommand to print a token
        the user can copy into MCP config."""
        # Bypass _ensure_logged_in so we can return raw response
        resp = self._request(
            "POST", "/api/auth/login",
            {"name": username, "password": password},
            skip_auth=True,
        )
        if isinstance(resp, dict) and resp.get("session_id"):
            self._token = resp["session_id"]
            self._logged_in = True
        return resp

    # ── Projects (discovery — no project_id needed) ─────────────────────

    def list_projects(self) -> list[dict]:
        """List all visible projects. Useful for finding the project_id to
        put in config — no project_id required to call this."""
        resp = self._request("GET", "/api/projects")
        if isinstance(resp, dict) and "projects" in resp:
            return resp["projects"]
        return resp or []

    # dev8 #147 — graceful module-availability check (graph / phases /
    # milestone-view / commits all assume tasks+documents — defense)
    def list_enabled_modules(self) -> list[str]:
        """Return list of module names enabled for the current project_id.
        Returns empty list on error (caller can decide if that's fatal)."""
        pid = self._require_project_id()
        try:
            resp = self._request("GET", f"/api/projects/{pid}/modules")
            if isinstance(resp, dict) and "modules" in resp:
                return [m.get("name") for m in resp["modules"] if m.get("name")]
            return [m.get("name") for m in (resp or []) if m.get("name")]
        except Exception:
            return []

    # ── Tasks module ────────────────────────────────────────────────────

    def _require_project_id(self) -> int:
        if self.project_id is None:
            raise AiTaskError(
                "project_id is required for this operation. Set it in your "
                "aitask config (or via AITASK_PROJECT_ID env var). Run "
                "`aitask projects` to discover available IDs."
            )
        return self.project_id

    def _tasks_path(self, suffix: str = "") -> str:
        pid = self._require_project_id()
        return f"/api/projects/{pid}/modules/{self.tasks_module}/items{suffix}"

    def _tasks_module_path(self, suffix: str = "") -> str:
        """For module-level endpoints (search/refs/recent), not /items/*."""
        pid = self._require_project_id()
        return f"/api/projects/{pid}/modules/{self.tasks_module}{suffix}"

    # dev8 #135 Phase 2 — server-side token-efficient queries
    def search_tasks(self, q: str, limit: int = 50) -> dict:
        """Server-side text search. Returns {items: [{id, title, snippet}], count}."""
        import urllib.parse
        return self._request("GET",
            self._tasks_module_path(f"/search?q={urllib.parse.quote(q)}&limit={limit}"))

    def reverse_refs_tasks(self, item_id: int, limit: int = 50) -> dict:
        """Items mentioning #<item_id>. Returns {items: [{id, title, snippet}], count}."""
        return self._request("GET",
            self._tasks_module_path(f"/refs/{item_id}?limit={limit}"))

    # dev8 #140 Phase 3b-i — typed item relations
    def list_relations(self, kind: str = "") -> dict:
        """List all relations in project (optionally filter by kind)."""
        pid = self._require_project_id()
        suffix = f"?kind={kind}" if kind else ""
        return self._request("GET", f"/api/projects/{pid}/relations{suffix}")

    def create_relation(self, source_kind: str, source_id: int,
                        relation_kind: str, target_kind: str, target_id: int,
                        note: str = "") -> dict:
        """Create a typed relation. Idempotent (UNIQUE constraint)."""
        pid = self._require_project_id()
        body = {
            "source_kind": source_kind, "source_id": source_id,
            "relation_kind": relation_kind,
            "target_kind": target_kind, "target_id": target_id,
        }
        if note:
            body["note"] = note
        return self._request("POST", f"/api/projects/{pid}/relations", body=body)

    # dev8 #142 Phase 3b-iv — task_commits multi-value
    def list_task_commits(self, task_id: int) -> dict:
        """List all commits associated with a task."""
        pid = self._require_project_id()
        return self._request("GET", f"/api/projects/{pid}/tasks/{task_id}/commits")

    def add_task_commit(self, task_id: int, commit_hash: str,
                        message_first_line: str = "",
                        committed_at: str = "",
                        note: str = "") -> dict:
        """Idempotent — UNIQUE(task_id, commit_hash) dedups."""
        pid = self._require_project_id()
        body = {"commit_hash": commit_hash}
        if message_first_line:
            body["message_first_line"] = message_first_line
        if committed_at:
            body["committed_at"] = committed_at
        if note:
            body["note"] = note
        return self._request(
            "POST", f"/api/projects/{pid}/tasks/{task_id}/commits", body=body
        )

    def list_all_task_commits(self, since: str = "") -> dict:
        """All commits across all tasks (project-wide)."""
        pid = self._require_project_id()
        import urllib.parse
        q = ""
        if since:
            q = f"?since={urllib.parse.quote(since)}"
        return self._request("GET", f"/api/projects/{pid}/task-commits{q}")

    def find_task_by_commit(self, commit_hash: str) -> dict:
        """Reverse lookup — given hash, find task associations."""
        pid = self._require_project_id()
        return self._request("GET",
            f"/api/projects/{pid}/task-commits/{commit_hash}")

    def relations_by_item(self, kind: str, item_id: int,
                          direction: str = "both") -> dict:
        """Outgoing + incoming relations for one item."""
        pid = self._require_project_id()
        return self._request("GET",
            f"/api/projects/{pid}/relations/by-item"
            f"?kind={kind}&id={item_id}&direction={direction}")

    def recent_tasks(self, limit: int = 20, since: str = "") -> dict:
        """Items by updated_at desc. Returns {items: [...], count}."""
        import urllib.parse
        q = f"?limit={limit}"
        if since:
            q += f"&since={urllib.parse.quote(since)}"
        return self._request("GET", self._tasks_module_path(f"/recent{q}"))

    def list_tasks(self, fields: str = "full") -> list[dict]:
        """Return list of task items. Backend may wrap in {items: [...]} —
        this method always unwraps to a plain list.

        fields='minimal' (dev8 #138 perf) skips per-row hydration
        (assignees/watchers/field_values N+1 queries) — ~10x faster on
        large lists when caller only needs title/description/status."""
        suffix = "?fields=minimal" if fields == "minimal" else ""
        resp = self._request("GET", self._tasks_path() + suffix)
        if isinstance(resp, dict) and "items" in resp:
            return resp["items"]
        return resp or []

    def get_task(self, task_id: int) -> dict:
        return self._request("GET", self._tasks_path(f"/{task_id}"))

    def create_task(self, title: str, description: str = "") -> dict:
        return self._request("POST", self._tasks_path(),
                             {"title": title, "description": description})

    def update_task(self, task_id: int, **fields) -> dict:
        return self._request("PATCH", self._tasks_path(f"/{task_id}"), fields)

    def delete_task(self, task_id: int, force: bool = False) -> None:
        """Soft-delete (archive) by default; force=True permanently deletes."""
        suffix = f"/{task_id}" + ("?force=true" if force else "")
        self._request("DELETE", self._tasks_path(suffix))

    def set_task_status(self, task_id: int, status: str,
                        *, override: bool = False) -> dict:
        """Set a task's status.

        override=False (default) follows the project's workflow: when the
        tasks workflow is *disabled* for the project any member may set any
        status; when enabled the member's role needs the transition granted.
        override=True skips the workflow but is Owner/admin-only (decision
        #57 §6) — reach it only via an explicit --force.
        """
        return self._request("POST", self._tasks_path(f"/{task_id}/status"),
                             {"status": status, "override": override})

    def get_task_status_options(self) -> dict:
        pid = self._require_project_id()
        return self._request(
            "GET", f"/api/projects/{pid}/modules/{self.tasks_module}/status-options"
        )

    def get_task_fields(self) -> list[dict]:
        pid = self._require_project_id()
        resp = self._request(
            "GET", f"/api/projects/{pid}/modules/{self.tasks_module}/fields"
        )
        if isinstance(resp, dict) and "fields" in resp:
            return resp["fields"]
        return resp or []

    def set_task_field_values(self, task_id: int, values: list[dict]) -> dict:
        """values: list of {field_id: int, value: str}"""
        return self._request(
            "PATCH", self._tasks_path(f"/{task_id}/field-values"),
            {"values": values},
        )

    def mark_task_done(self, task_id: int, *, force: bool = False) -> dict:
        """Find the done status (is_done=True) and set it. Convenience over
        manually calling get_task_status_options + set_task_status.

        force=True uses the Owner/admin-only override path (skip workflow);
        default follows the workflow (see set_task_status)."""
        opts = self.get_task_status_options()
        done = next(
            (o for o in opts.get("options", []) if o.get("is_done")),
            None,
        )
        if not done:
            raise AiTaskError("No done status found in module status-options")
        return self.set_task_status(task_id, done["id"], override=force)

    def append_to_task_description(self, task_id: int, note: str) -> dict:
        """Append a timestamped note to the task's description (the `/aitask
        log` workflow). Returns the updated task."""
        import datetime
        item = self.get_task(task_id)
        old = item.get("description") or ""
        today = datetime.date.today().isoformat()
        new_desc = f"{old}\n\n---\n[{today}] {note}"
        return self.update_task(task_id, description=new_desc)

    def append_to_doc_body(self, doc_id: int, note: str) -> dict:
        """Append a timestamped note to a document's body_md — the doc
        analogue of append_to_task_description (`aitask log <id> --doc`).

        tasks/docs are SEPARATE id namespaces; `log` historically only hit
        tasks, so logging to a same-numbered task silently mis-fired when the
        caller meant a doc. This gives docs a first-class append path.
        Returns the updated doc."""
        import datetime
        item = self.get_doc(doc_id)
        old = item.get("body_md") or ""
        today = datetime.date.today().isoformat()
        new_body = f"{old}\n\n---\n[{today}] {note}"
        return self.update_doc(doc_id, body_md=new_body)

    def set_task_commit_hash(self, task_id: int, commit_hash: str) -> Optional[dict]:
        """Write `commit_hash` to the task's structured field (dev8 #66 —
        dual-track convention: description note + structured field).
        No-op (silent) when the module doesn't have a `commit_hash` field.
        Returns the field-values PATCH response or None when skipped."""
        fields = self.get_task_fields()
        field_id = next(
            (f["id"] for f in fields if f.get("name") == "commit_hash"),
            None,
        )
        if field_id is None:
            return None
        return self.set_task_field_values(
            task_id, [{"field_id": field_id, "value": commit_hash}]
        )

    # ── Documents module ────────────────────────────────────────────────

    def _docs_path(self, suffix: str = "") -> str:
        pid = self._require_project_id()
        return f"/api/projects/{pid}/modules/{self.docs_module}/items{suffix}"

    def _docs_module_path(self, suffix: str = "") -> str:
        pid = self._require_project_id()
        return f"/api/projects/{pid}/modules/{self.docs_module}{suffix}"

    # dev8 #135 Phase 2 — server-side token-efficient queries
    def search_docs(self, q: str, limit: int = 50) -> dict:
        import urllib.parse
        return self._request("GET",
            self._docs_module_path(f"/search?q={urllib.parse.quote(q)}&limit={limit}"))

    def reverse_refs_docs(self, item_id: int, limit: int = 50) -> dict:
        return self._request("GET",
            self._docs_module_path(f"/refs/{item_id}?limit={limit}"))

    def recent_docs(self, limit: int = 20, since: str = "") -> dict:
        import urllib.parse
        q = f"?limit={limit}"
        if since:
            q += f"&since={urllib.parse.quote(since)}"
        return self._request("GET", self._docs_module_path(f"/recent{q}"))

    def list_docs(self, fields: str = "full") -> list[dict]:
        """fields='minimal' skips per-row hydration (assignees/field_values/
        files) — ~10x faster on large lists. dev8 #138 perf."""
        suffix = "?fields=minimal" if fields == "minimal" else ""
        resp = self._request("GET", self._docs_path() + suffix)
        if isinstance(resp, dict) and "items" in resp:
            return resp["items"]
        return resp or []

    def get_doc(self, doc_id: int) -> dict:
        return self._request("GET", self._docs_path(f"/{doc_id}"))

    def create_doc(self, title: str, body_md: str = "") -> dict:
        return self._request("POST", self._docs_path(),
                             {"title": title, "body_md": body_md})

    def update_doc(self, doc_id: int, **fields) -> dict:
        return self._request("PATCH", self._docs_path(f"/{doc_id}"), fields)

    def delete_doc(self, doc_id: int, force: bool = False) -> None:
        """Soft-delete (archive) by default; force=True permanently deletes."""
        suffix = f"/{doc_id}" + ("?force=true" if force else "")
        self._request("DELETE", self._docs_path(suffix))

    def set_doc_status(self, doc_id: int, status: str,
                       *, override: bool = False) -> dict:
        """Set a document's status. Same semantics as set_task_status:
        override=False follows the workflow (any member when the documents
        workflow is disabled); override=True is the Owner/admin-only skip."""
        return self._request("POST", self._docs_path(f"/{doc_id}/status"),
                             {"status": status, "override": override})

    def get_doc_fields(self) -> list[dict]:
        pid = self._require_project_id()
        resp = self._request(
            "GET", f"/api/projects/{pid}/modules/{self.docs_module}/fields"
        )
        if isinstance(resp, dict) and "fields" in resp:
            return resp["fields"]
        return resp or []

    def set_doc_field_values(self, doc_id: int, values: list[dict]) -> dict:
        return self._request(
            "PATCH", self._docs_path(f"/{doc_id}/field-values"),
            {"values": values},
        )

    # ── High-level helpers (compose multiple calls) ─────────────────────

    def create_doc_typed(
        self,
        raw_title: str,
        body_md: str,
        *,
        doc_type: str = "note",
        prefix: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> int:
        """Create a document + set 「類型」 custom field + set status.

        dev8 #76 follow-up: 同 task 一樣標題前綴 `#NN`（POST 拿到 id 之後
        PATCH 加進去），讓 UI 列表跟 chat 提到的 ID 對得齊。

        Mirrors the CLAUDE.md convention:
          * doc_type='decision' → status='published', prefix='[decision]'
          * doc_type='plan'     → status='draft',     prefix='[plan]'
          * other               → status='draft',     prefix=None
        """
        # Step 1: POST (no #NN yet — we need the id first)
        initial_title = f"{prefix} {raw_title}" if prefix else raw_title
        doc = self.create_doc(initial_title, body_md)
        doc_id = doc["id"]

        # Step 2: PATCH title with #NN prefix
        final_title = f"#{doc_id} {initial_title}"
        self.update_doc(doc_id, title=final_title)

        fields = self.get_doc_fields()
        field_by_name = {f["name"]: f["id"] for f in fields}

        values = []
        if "類型" in field_by_name:
            values.append({"field_id": field_by_name["類型"], "value": doc_type})
        if tags and "標籤" in field_by_name:
            values.append({"field_id": field_by_name["標籤"], "value": ", ".join(tags)})
        if values:
            self.set_doc_field_values(doc_id, values)

        target_status = "published" if doc_type == "decision" else "draft"
        self.set_doc_status(doc_id, target_status)
        return doc_id
