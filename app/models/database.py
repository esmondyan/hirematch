import json
from datetime import datetime

from sqlalchemy import Integer, String, Text, Boolean, DateTime, ForeignKey, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, Session


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
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


engine = create_engine("sqlite:///./hirematch.db", echo=False)


def init_db():
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE candidates ADD COLUMN marked_for_interview BOOLEAN DEFAULT 0"))
            conn.commit()
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN comparison_result TEXT"))
            conn.commit()
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE candidates ADD COLUMN resume_file_path VARCHAR(500)"))
            conn.commit()
        except Exception:
            pass


def get_session() -> Session:
    return Session(engine)
