from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, Float, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from database import Base


class TestSuite(Base):
    __tablename__ = "test_suites"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    tests = relationship("TestCase", back_populates="suite", cascade="all, delete-orphan")
    suite_runs = relationship("SuiteRun", back_populates="suite", cascade="all, delete-orphan")


class TestCase(Base):
    __tablename__ = "test_cases"

    id = Column(Integer, primary_key=True, index=True)
    suite_id = Column(Integer, ForeignKey("test_suites.id"), nullable=False)
    name = Column(String(200), nullable=False)
    nl_description = Column(Text, default="")
    steps = Column(Text, default="[]")          # JSON array of step dicts
    base_url = Column(String(500), default="")
    tags = Column(Text, default="[]")           # JSON array of tag strings e.g. ["smoke","login"]
    retry_count = Column(Integer, default=1)    # how many times to retry on failure
    self_healed = Column(Boolean, default=False)
    last_status = Column(String(50), default="pending")
    last_duration = Column(Float, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    suite = relationship("TestSuite", back_populates="tests")
    runs = relationship("TestRun", back_populates="test", cascade="all, delete-orphan")


class TestRun(Base):
    __tablename__ = "test_runs"

    id = Column(Integer, primary_key=True, index=True)
    test_id = Column(Integer, ForeignKey("test_cases.id"), nullable=False)
    suite_run_id = Column(Integer, ForeignKey("suite_runs.id"), nullable=True)
    status = Column(String(50), default="pending")   # pending/running/passed/failed/self-healed
    attempt = Column(Integer, default=1)             # retry attempt number
    duration = Column(Float, default=0)
    results = Column(Text, default="[]")             # JSON array of step results
    screenshot_path = Column(String(500), default="")
    triggered_by = Column(String(100), default="ui") # ui / cli / api / github-actions / gitlab-ci
    git_sha = Column(String(64), default="")
    git_branch = Column(String(200), default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    test = relationship("TestCase", back_populates="runs")
    suite_run = relationship("SuiteRun", back_populates="test_runs")


class SuiteRun(Base):
    """Represents one complete CI/CD execution of an entire test suite."""
    __tablename__ = "suite_runs"

    id = Column(Integer, primary_key=True, index=True)
    suite_id = Column(Integer, ForeignKey("test_suites.id"), nullable=False)
    status = Column(String(50), default="running")  # running/passed/failed/partial
    total = Column(Integer, default=0)
    passed = Column(Integer, default=0)
    failed = Column(Integer, default=0)
    healed = Column(Integer, default=0)
    duration = Column(Float, default=0)
    base_url_override = Column(String(500), default="")  # CI can override base URL
    triggered_by = Column(String(100), default="cli")
    git_sha = Column(String(64), default="")
    git_branch = Column(String(200), default="")
    git_tag = Column(String(200), default="")
    report_path = Column(String(500), default="")  # path to JSON report file
    junit_path = Column(String(500), default="")   # path to JUnit XML file
    created_at = Column(DateTime, default=datetime.utcnow)

    suite = relationship("TestSuite", back_populates="suite_runs")
    test_runs = relationship("TestRun", back_populates="suite_run")
