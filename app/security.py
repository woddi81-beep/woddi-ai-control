from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PBKDF2_ALGORITHM = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 310_000
PBKDF2_SALT_BYTES = 16


def hash_password(password: str, *, iterations: int = PBKDF2_ITERATIONS) -> str:
    salt = secrets.token_bytes(PBKDF2_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, max(120_000, int(iterations)))
    return "$".join(
        [
            PBKDF2_ALGORITHM,
            str(max(120_000, int(iterations))),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(digest).decode("ascii"),
        ]
    )


def verify_password(password: str, password_hash: str) -> bool:
    stored = str(password_hash or "").strip()
    if not stored:
        return False
    if stored.startswith(f"{PBKDF2_ALGORITHM}$"):
        try:
            _algorithm, iterations_raw, salt_b64, digest_b64 = stored.split("$", 3)
            iterations = max(120_000, int(iterations_raw))
            salt = base64.b64decode(salt_b64.encode("ascii"))
            expected = base64.b64decode(digest_b64.encode("ascii"))
        except Exception:
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(expected, candidate)
    return hmac.compare_digest(stored.lower(), hashlib.sha256(password.encode("utf-8")).hexdigest())


def password_hash_scheme(password_hash: str) -> str:
    stored = str(password_hash or "").strip()
    if stored.startswith(f"{PBKDF2_ALGORITHM}$"):
        return PBKDF2_ALGORITHM
    if len(stored) == 64 and all(character in "0123456789abcdef" for character in stored.lower()):
        return "sha256_legacy"
    return "unknown"


def password_hash_is_modern(password_hash: str) -> bool:
    return password_hash_scheme(password_hash) == PBKDF2_ALGORITHM


@dataclass(frozen=True)
class UserRecord:
    username: str
    role: str
    password_sha256: str
    allowed_mcp_ids: tuple[str, ...]
    display_name: str
    groups: tuple[str, ...]
    persona_id: str


@dataclass
class AuthSession:
    token: str
    csrf_token: str
    username: str
    display_name: str
    role: str
    allowed_mcp_ids: tuple[str, ...]
    groups: tuple[str, ...]
    persona_id: str
    expires_at: float

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class LoginAttemptLimiter:
    def __init__(self, *, limit: int = 8, window_seconds: int = 300, block_seconds: int = 900) -> None:
        self.limit = max(3, int(limit))
        self.window_seconds = max(30, int(window_seconds))
        self.block_seconds = max(self.window_seconds, int(block_seconds))
        self._lock = threading.Lock()
        self._history: dict[str, deque[float]] = defaultdict(deque)
        self._blocked_until: dict[str, float] = {}

    def allow(self, key: str) -> bool:
        if not key:
            return True
        now = time.time()
        with self._lock:
            self._purge_locked(now)
            blocked_until = self._blocked_until.get(key, 0.0)
            return blocked_until <= now

    def register_failure(self, key: str) -> None:
        if not key:
            return
        now = time.time()
        with self._lock:
            self._purge_locked(now)
            history = self._history[key]
            history.append(now)
            if len(history) >= self.limit:
                self._blocked_until[key] = now + self.block_seconds
                history.clear()

    def clear(self, key: str) -> None:
        if not key:
            return
        with self._lock:
            self._history.pop(key, None)
            self._blocked_until.pop(key, None)

    def retry_after_seconds(self, key: str) -> int:
        if not key:
            return 0
        with self._lock:
            blocked_until = self._blocked_until.get(key, 0.0)
        return max(0, int(blocked_until - time.time()))

    def _purge_locked(self, now: float) -> None:
        cutoff = now - self.window_seconds
        for key, history in list(self._history.items()):
            while history and history[0] < cutoff:
                history.popleft()
            if not history:
                self._history.pop(key, None)
        for key, blocked_until in list(self._blocked_until.items()):
            if blocked_until <= now:
                self._blocked_until.pop(key, None)


class AuthManager:
    def __init__(self, users_path: Path, *, session_ttl_seconds: int = 60 * 60 * 12) -> None:
        self.users_path = users_path
        self.session_ttl_seconds = max(300, int(session_ttl_seconds))
        self._lock = threading.Lock()
        self._sessions: dict[str, AuthSession] = {}
        self.login_limiter = LoginAttemptLimiter()

    def load_users(self) -> list[UserRecord]:
        raw = self.load_passwd()
        items = raw.get("users", []) if isinstance(raw, dict) else []
        groups_index = self._groups_index(raw)
        users: list[UserRecord] = []
        for item in items:
            user = self._build_user_record(item, groups_index)
            if user is not None:
                users.append(user)
        return users

    def load_passwd(self) -> dict[str, Any]:
        if not self.users_path.exists():
            return {"groups": [], "users": []}
        try:
            raw = json.loads(self.users_path.read_text(encoding="utf-8"))
        except Exception:
            return {"groups": [], "users": []}
        if not isinstance(raw, dict):
            return {"groups": [], "users": []}
        if not isinstance(raw.get("groups"), list):
            raw["groups"] = []
        if not isinstance(raw.get("users"), list):
            raw["users"] = []
        return raw

    def _groups_index(self, raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
        items = raw.get("groups", []) if isinstance(raw, dict) else []
        index: dict[str, dict[str, Any]] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            group_id = str(item.get("id", "")).strip()
            if group_id:
                index[group_id] = item
        return index

    def _build_user_record(self, item: Any, groups_index: dict[str, dict[str, Any]]) -> UserRecord | None:
        if not isinstance(item, dict):
            return None
        username = str(item.get("username", "")).strip()
        password_sha256 = str(item.get("password_sha256", "")).strip()
        if not username or not password_sha256:
            return None
        role = str(item.get("role", "user")).strip().lower() or "user"
        group_ids_raw = item.get("groups", [])
        group_ids = tuple(str(value).strip() for value in group_ids_raw if str(value).strip()) if isinstance(group_ids_raw, list) else tuple()

        allowed_values: list[str] = []
        if role == "admin":
            allowed_values.append("*")
        for group_id in group_ids:
            group = groups_index.get(group_id) or {}
            group_allowed = group.get("allowed_mcp_ids", [])
            if isinstance(group_allowed, list):
                allowed_values.extend(str(value).strip() for value in group_allowed if str(value).strip())
        direct_allowed = item.get("allowed_mcp_ids", [])
        if isinstance(direct_allowed, list):
            allowed_values.extend(str(value).strip() for value in direct_allowed if str(value).strip())

        deduped_allowed: list[str] = []
        for value in allowed_values:
            if value and value not in deduped_allowed:
                deduped_allowed.append(value)

        persona_id = str(item.get("persona_id", "")).strip()
        if not persona_id:
            for group_id in group_ids:
                group = groups_index.get(group_id) or {}
                candidate = str(group.get("persona_id", "")).strip()
                if candidate:
                    persona_id = candidate
                    break
        if not persona_id:
            persona_id = "default"

        return UserRecord(
            username=username,
            role="admin" if role == "admin" else "user",
            password_sha256=password_sha256,
            allowed_mcp_ids=tuple(deduped_allowed),
            display_name=str(item.get("display_name", username)).strip() or username,
            groups=group_ids,
            persona_id=persona_id,
        )

    def verify_credentials(self, username: str, password: str) -> UserRecord | None:
        candidate_username = username.strip()
        if not candidate_username or not password:
            return None
        for user in self.load_users():
            if user.username != candidate_username:
                continue
            if verify_password(password, user.password_sha256):
                return user
        return None

    def setup_required(self) -> bool:
        return not bool(self.load_users())

    def create_session(self, user: UserRecord) -> AuthSession:
        token = secrets.token_urlsafe(32)
        session = AuthSession(
            token=token,
            csrf_token=secrets.token_urlsafe(24),
            username=user.username,
            display_name=user.display_name,
            role=user.role,
            allowed_mcp_ids=user.allowed_mcp_ids,
            groups=user.groups,
            persona_id=user.persona_id,
            expires_at=time.time() + self.session_ttl_seconds,
        )
        with self._lock:
            self._purge_locked()
            self._sessions[token] = session
        return session

    def get_session(self, token: str) -> AuthSession | None:
        if not token:
            return None
        with self._lock:
            self._purge_locked()
            session = self._sessions.get(token)
            if session is None:
                return None
            if session.expires_at <= time.time():
                self._sessions.pop(token, None)
                return None
            return session

    def clear_session(self, token: str) -> None:
        if not token:
            return
        with self._lock:
            self._sessions.pop(token, None)

    def _purge_locked(self) -> None:
        now = time.time()
        expired = [token for token, session in self._sessions.items() if session.expires_at <= now]
        for token in expired:
            self._sessions.pop(token, None)
