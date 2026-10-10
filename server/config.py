"""Explicit, process-wide service configuration (no per-request model settings)."""
from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path("data")
    allowed_origins: tuple[str, ...] = ("http://localhost:5173", "http://localhost:8000")
    secure_cookies: bool = True
    session_hours: int = 24
    worker_count: int = 2
    daily_research_limit: int = 5
    queue_capacity: int = 10
    execution_timeout: float = 3600
    cancel_grace: float = 5
    process_exit_grace: float = 5
    event_retention_days: int = 30
    poll_interval: float = 0.2
    require_safe_sqlite: bool = True

    @property
    def database(self) -> Path:
        return self.data_dir / "wenli.sqlite3"

    @classmethod
    def from_env(cls):
        origins = tuple(x.strip().rstrip("/") for x in os.getenv(
            "WENLI_ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:8000"
        ).split(",") if x.strip())
        if not origins or any(x == "*" for x in origins):
            raise ValueError("WENLI_ALLOWED_ORIGINS must list exact website origins")
        return cls(
            data_dir=Path(os.getenv("WENLI_DATA_DIR", "data")).resolve(),
            allowed_origins=origins,
            secure_cookies=os.getenv("WENLI_SECURE_COOKIES", "true").lower() != "false",
            require_safe_sqlite=os.getenv("WENLI_REQUIRE_SAFE_SQLITE", "true").lower() != "false",
        )
