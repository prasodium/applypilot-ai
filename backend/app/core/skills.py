"""Shared skill vocabulary. Used to SUGGEST technologies from text and to compare job requirements with a candidate.

Deliberately modest: it recognises well-known technologies; anything it does not know is simply not detected (and then
reported as unknown), never guessed.
"""
from __future__ import annotations

import re

_TERMS = {
    # languages
    "python": "Python", "java": "Java", "javascript": "JavaScript", "typescript": "TypeScript", "c++": "C++", "c#": "C#",
    "go": "Go", "golang": "Go", "rust": "Rust", "ruby": "Ruby", "php": "PHP", "swift": "Swift", "kotlin": "Kotlin",
    "scala": "Scala", "sql": "SQL", "bash": "Bash", "r": "R",
    # frameworks / libs
    "react": "React", "vue": "Vue", "angular": "Angular", "node.js": "Node.js", "nodejs": "Node.js", "django": "Django",
    "flask": "Flask", "fastapi": "FastAPI", "spring": "Spring", "rails": "Rails", "next.js": "Next.js", "tailwind": "Tailwind",
    "pandas": "pandas", "numpy": "NumPy", "pytorch": "PyTorch", "tensorflow": "TensorFlow", "scikit-learn": "scikit-learn",
    "sqlalchemy": "SQLAlchemy", "pydantic": "Pydantic",
    # data
    "postgresql": "PostgreSQL", "postgres": "PostgreSQL", "mysql": "MySQL", "sqlite": "SQLite", "mongodb": "MongoDB",
    "redis": "Redis", "elasticsearch": "Elasticsearch", "kafka": "Kafka", "spark": "Spark", "airflow": "Airflow",
    # infra / tooling
    "docker": "Docker", "kubernetes": "Kubernetes", "aws": "AWS", "azure": "Azure", "gcp": "GCP", "terraform": "Terraform",
    "linux": "Linux", "git": "Git", "ci/cd": "CI/CD", "jenkins": "Jenkins", "github actions": "GitHub Actions",
    "graphql": "GraphQL", "rest": "REST", "grpc": "gRPC", "html": "HTML", "css": "CSS",
    # testing
    "pytest": "pytest", "playwright": "Playwright", "selenium": "Selenium", "jest": "Jest", "cypress": "Cypress",
    # practices
    "agile": "Agile", "scrum": "Scrum", "tdd": "TDD", "microservices": "Microservices", "machine learning": "Machine Learning",
    "data analysis": "Data Analysis", "api design": "API Design",
}
_ALIASES = {"golang": "go", "nodejs": "node.js", "postgres": "postgresql"}
_PATTERN = re.compile(
    r"(?<![\w+#.])(" + "|".join(sorted((re.escape(t) for t in _TERMS), key=len, reverse=True)) + r")(?![\w+#]|\.\w)", re.I
)
# single letters / very common words are only accepted in an unambiguous form
_RISKY = {"r", "go", "rest", "spring", "swift", "rails"}


def canonical(term: str) -> str:
    t = term.strip().lower()
    return _TERMS.get(_ALIASES.get(t, t), term.strip())


def find_skills(text: str) -> list[str]:
    """Canonical skill names mentioned in `text`, in order of first appearance, de-duplicated."""
    out: list[str] = []
    seen: set[str] = set()
    for m in _PATTERN.finditer(text or ""):
        raw = m.group(1)
        if raw.lower() in _RISKY and raw != _TERMS.get(raw.lower(), raw) and raw.islower():
            continue  # e.g. lowercase "go"/"rest"/"spring" in running prose is usually the English word
        c = canonical(raw)
        if c.lower() not in seen:
            seen.add(c.lower())
            out.append(c)
    return out
