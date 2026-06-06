import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import Integer, String, Text, Boolean, DateTime, ForeignKey, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, Session


class Base(DeclarativeBase):
    pass


class Organization(Base):
    """Simple org registry — no password, just namespace."""
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AccessLog(Base):
    """Record every access for audit trail."""
    __tablename__ = "access_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    org_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)  # LOGIN, PAGE, API, LOGOUT
    path: Mapped[str] = mapped_column(String(500), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    ip: Mapped[str] = mapped_column(String(45), nullable=True)  # IPv6 max 45 chars
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    client_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    detail: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    org_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    threshold: Mapped[int] = mapped_column(Integer, default=60)
    _comparison_result: Mapped[str | None] = mapped_column("comparison_result", Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    candidates: Mapped[list["Candidate"]] = relationship(back_populates="job", order_by="Candidate.created_at")

    @property
    def comparison_result(self) -> dict | None:
        if self._comparison_result:
            return json.loads(self._comparison_result)
        return None

    @comparison_result.setter
    def comparison_result(self, value: dict | None):
        self._comparison_result = json.dumps(value, ensure_ascii=False) if value else None


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), default="未知")
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    resume_text: Mapped[str] = mapped_column(Text, nullable=False)
    resume_file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    overall_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    _match_result: Mapped[str | None] = mapped_column("match_result", Text, nullable=True)
    _interview_result: Mapped[str | None] = mapped_column("interview_result", Text, nullable=True)
    _credibility_result: Mapped[str | None] = mapped_column("credibility_result", Text, nullable=True)
    _answers: Mapped[str | None] = mapped_column("answers", Text, nullable=True)
    _final_summary: Mapped[str | None] = mapped_column("final_summary", Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    marked_for_interview: Mapped[bool] = mapped_column(Boolean, default=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    job: Mapped["Job"] = relationship(back_populates="candidates")

    @property
    def match_result(self) -> dict | None:
        if self._match_result:
            return json.loads(self._match_result)
        return None

    @match_result.setter
    def match_result(self, value: dict | None):
        self._match_result = json.dumps(value, ensure_ascii=False) if value else None

    @property
    def interview_result(self) -> dict | None:
        if self._interview_result:
            return json.loads(self._interview_result)
        return None

    @interview_result.setter
    def interview_result(self, value: dict | None):
        self._interview_result = json.dumps(value, ensure_ascii=False) if value else None

    @property
    def credibility_result(self) -> dict | None:
        if self._credibility_result:
            return json.loads(self._credibility_result)
        return None

    @credibility_result.setter
    def credibility_result(self, value: dict | None):
        self._credibility_result = json.dumps(value, ensure_ascii=False) if value else None

    @property
    def answers(self) -> dict | None:
        if self._answers:
            return json.loads(self._answers)
        return None

    @answers.setter
    def answers(self, value: dict | None):
        self._answers = json.dumps(value, ensure_ascii=False) if value else None

    @property
    def final_summary(self) -> dict | None:
        if self._final_summary:
            return json.loads(self._final_summary)
        return None

    @final_summary.setter
    def final_summary(self, value: dict | None):
        self._final_summary = json.dumps(value, ensure_ascii=False) if value else None


engine = None


def _get_engine():
    global engine
    if engine is None:
        from app.config import get_settings
        db_url = get_settings().database_url
        engine = create_engine(db_url, echo=False)
    return engine


def init_db():
    eng = _get_engine()
    Base.metadata.create_all(eng)
    with eng.connect() as conn:
        for stmt in [
            "ALTER TABLE candidates ADD COLUMN marked_for_interview BOOLEAN DEFAULT 0",
            "ALTER TABLE jobs ADD COLUMN comparison_result TEXT",
            "ALTER TABLE candidates ADD COLUMN resume_file_path VARCHAR(500)",
            "ALTER TABLE jobs ADD COLUMN org_name VARCHAR(100)",
            # New: make password_hash optional (we dropped it from model, old column stays harmless)
        ]:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                pass


def get_session() -> Session:
    return Session(_get_engine())


def generate_client_id() -> str:
    return uuid.uuid4().hex
