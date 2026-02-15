from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple


@dataclass(frozen=True)
class Konsulent:
    id: int
    navn: str
    ferdigheter: Tuple[str, ...]
    belastning_prosent: int  # 0..100


# Hardkodet datasett (25)
KONSULENTER: List[Konsulent] = [
    Konsulent(1, "Anna K.", ("python", "fastapi", "azure"), 10),
    Konsulent(2, "Leo T.", ("python", "docker", "kubernetes"), 50),
    Konsulent(3, "Erik B.", ("java", "kotlin", "spring"), 45),
    Konsulent(4, "Camilla J.", ("data engineering", "spark", "databricks"), 30),
    Konsulent(5, "Yusuf I.", ("python", "ml", "pandas"), 50),
    Konsulent(6, "Nora S.", ("react", "typescript", "ux"), 20),
    Konsulent(7, "Maja H.", ("project management", "scrum", "jira"), 60),
    Konsulent(8, "Omar A.", ("devops", "terraform", "aws"), 40),
    Konsulent(9, "Sofie L.", ("security", "iam", "siem"), 35),
    Konsulent(10, "Jon P.", ("dotnet", "csharp", "azure"), 70),
    Konsulent(11, "Kari M.", ("python", "etl", "sql"), 15),
    Konsulent(12, "Lars V.", ("go", "microservices", "grpc"), 55),
    Konsulent(13, "Ingrid R.", ("qa", "pytest", "playwright"), 25),
    Konsulent(14, "Håkon D.", ("node", "typescript", "api"), 65),
    Konsulent(15, "Fatima N.", ("python", "nlp", "llm"), 35),
    Konsulent(16, "Thomas E.", ("observability", "grafana", "prometheus"), 40),
    Konsulent(17, "Helene Q.", ("data science", "python", "numpy"), 80),
    Konsulent(18, "Mikkel G.", ("linux", "docker", "nginx"), 30),
    Konsulent(19, "Sara W.", ("powerbi", "sql", "analytics"), 55),
    Konsulent(20, "Ali Z.", ("python", "fastapi", "redis"), 45),
    Konsulent(21, "Eirik F.", ("security", "pentest", "owasp"), 75),
    Konsulent(22, "Rikke U.", ("product", "discovery", "stakeholders"), 50),
    Konsulent(23, "Kristian O.", ("python", "data engineering", "airflow"), 20),
    Konsulent(24, "Lina C.", ("mlops", "kubeflow", "kubernetes"), 60),
    Konsulent(25, "Petter Y.", ("sql", "postgres", "dbt"), 35),
]
