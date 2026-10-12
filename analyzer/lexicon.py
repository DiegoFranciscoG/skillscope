"""Weighted vocabularies for categories and causes (docs/algoritmo.md §3.4).

Terms are written as plain words; ``analyzer.taxonomy`` stems them with the same tokenizer
used for repository text, so "testing", "tests" and "pruebas" all hit the ``test`` entry.
Weight 2 marks terms that are strong evidence on their own.
"""

from __future__ import annotations

CATEGORY_LABELS: dict[str, str] = {
    "development": "Desarrollo",
    "testing": "Pruebas",
    "code_review": "Revisión de código",
    "devops": "DevOps/CI",
    "security": "Seguridad",
    "data": "Datos y BI",
    "ai_ml": "IA/ML",
    "docs_writing": "Documentación y escritura",
    "design_ux": "Diseño/UX",
    "productivity": "Productividad y oficina",
    "finance_legal": "Finanzas y legal",
    "research": "Investigación",
    "education": "Educación",
    "integrations": "Integraciones",
}

CAUSE_LABELS: dict[str, str] = {
    "automate": "Automatizar una tarea repetitiva",
    "standardize": "Estandarizar un estilo",
    "comply": "Cumplir una norma",
    "onboard": "Acelerar la incorporación de gente nueva",
    "integrate": "Integrar una herramienta externa",
    "reduce_errors": "Reducir errores",
    "generate_docs": "Generar documentos",
}

TYPE_LABELS: dict[str, str] = {
    "skill": "Skill suelta",
    "plugin": "Plugin",
    "marketplace": "Marketplace/colección",
    "mcp_server": "Servidor MCP",
    "agent": "Agente",
    "command": "Comando",
    "hook": "Hook",
    "awesome_list": "Lista awesome",
    "template": "Plantilla",
}

CATEGORY_TERMS: dict[str, dict[str, float]] = {
    "development": {
        "refactor": 2, "debug": 2, "programming": 1.5, "developer": 1, "bug": 1, "fix": 1,
        "git": 1.5, "commit": 1.5, "branch": 1, "merge": 1, "typescript": 1, "javascript": 1,
        "python": 1, "java": 1, "rust": 1, "golang": 1, "frontend": 1, "backend": 1, "sdk": 1,
        "cli": 1, "framework": 1, "react": 1, "nextjs": 1, "vue": 1, "angular": 1, "django": 1,
        "spring": 1, "dotnet": 1, "kotlin": 1, "swift": 1, "android": 1, "ios": 1, "mobile": 1,
        "compiler": 1, "codebase": 1.5, "conventional": 1, "simplify": 1, "clean": 1,
        "duplication": 1, "rename": 1, "jupyter": 0.5, "notebook": 0.5, "coding": 1.5,
        "template": 1.5, "starter": 1.5, "scaffold": 1.5, "boilerplate": 1.5,
    },
    "testing": {
        "test": 2, "unit": 1.5, "e2e": 2, "playwright": 2, "cypress": 2, "jest": 1.5,
        "pytest": 1.5, "vitest": 1.5, "coverage": 1.5, "tdd": 2, "qa": 1.5, "flaky": 2,
        "mock": 1, "regression": 1, "selenium": 1.5, "smoke": 1,
    },
    "code_review": {
        "review": 2.5, "pr": 2, "diff": 2, "lint": 1.5, "linter": 1.5, "approve": 1,
        "reviewer": 1.5, "smell": 1, "quality": 1, "style": 0.5,
    },
    "devops": {
        "ci": 2, "cd": 1, "pipeline": 1.5, "deploy": 2, "docker": 1.5, "kubernetes": 2,
        "helm": 2, "terraform": 2, "ansible": 1.5, "infrastructure": 1.5, "iac": 2,
        "cloud": 1, "aws": 1, "azure": 1, "gcp": 1, "actions": 1, "observability": 1.5,
        "monitoring": 1, "sre": 1.5, "incident": 1, "release": 1, "container": 1.5,
        "rollout": 1, "workflow": 0.5,
    },
    "security": {
        "security": 2.5, "secret": 2, "vulnerability": 2, "cve": 2, "owasp": 2.5, "audit": 1,
        "pentest": 2, "threat": 1.5, "authentication": 1, "encryption": 1.5, "sast": 2,
        "dast": 2, "sbom": 2, "supply": 1, "malware": 2, "gitleaks": 2, "appsec": 2,
        "credential": 1, "syft": 1, "grype": 1, "checkov": 1,
    },
    "data": {
        "data": 1.5, "sql": 2, "database": 2, "query": 1.5, "csv": 2, "spreadsheet": 1.5,
        "pandas": 2, "analytics": 1.5, "bi": 2, "powerbi": 2, "dashboard": 1.5, "etl": 2,
        "warehouse": 1.5, "dax": 2, "tableau": 2, "jupyter": 1, "notebook": 1,
        "visualization": 1.5, "chart": 1, "statistics": 1.5, "postgres": 1.5, "mysql": 1.5,
        "schema": 1, "index": 0.5, "outlier": 1, "analysis": 1,
    },
    "ai_ml": {
        "ai": 1.5, "ml": 2, "llm": 2, "prompt": 2, "model": 1, "embedding": 2, "rag": 2.5,
        "fine": 0.5, "training": 1, "evaluation": 1.5, "eval": 1.5, "neural": 1.5,
        "vector": 1.5, "transformer": 1.5, "inference": 1.5, "dataset": 1, "chunk": 1,
        "retrieval": 1.5,
    },
    "docs_writing": {
        "docs": 2.5, "readme": 2, "writing": 2, "writer": 2, "style": 1, "grammar": 1.5,
        "blog": 1.5, "article": 1.5, "copywriting": 2, "editing": 1, "markdown": 1,
        "changelog": 2, "guide": 1, "translate": 1.5, "translation": 1.5, "spanish": 1,
        "chinese": 1, "release": 0.5, "notes": 0.5, "document": 1, "clarity": 1,
        "technical": 0.5,
    },
    "design_ux": {
        "design": 2, "ui": 2, "ux": 2, "figma": 2.5, "accessibility": 2.5, "wcag": 2.5,
        "css": 1.5, "tailwind": 1.5, "component": 1, "layout": 1.5, "color": 1,
        "typography": 1.5, "mockup": 1.5, "prototype": 1, "token": 1.5, "brand": 1,
        "contrast": 1.5, "screenshot": 1,
    },
    "productivity": {
        "productivity": 2, "email": 2, "inbox": 2, "calendar": 2, "meeting": 1.5,
        "note": 1, "notes": 1, "todo": 1.5, "standup": 2, "notion": 1, "obsidian": 1.5,
        "office": 1.5, "docx": 1.5, "xlsx": 1.5, "pptx": 1.5, "pdf": 1, "presentation": 1.5,
        "planning": 1, "triage": 1, "reply": 1,
    },
    "finance_legal": {
        "finance": 2, "accounting": 2, "invoice": 2.5, "tax": 2, "vat": 2, "legal": 2,
        "contract": 2.5, "law": 1.5, "compliance": 1, "regulation": 1.5, "gdpr": 1.5,
        "payroll": 2, "bank": 1.5, "budget": 1, "nda": 2, "liability": 1.5, "filing": 1,
    },
    "research": {
        "research": 2.5, "paper": 2, "arxiv": 2.5, "literature": 2, "citation": 1.5,
        "scientific": 1.5, "science": 1.5, "study": 1, "academic": 1.5, "experiment": 1,
        "hypothesis": 1.5, "scholar": 1.5, "pdf": 0.5,
    },
    "education": {
        "education": 2.5, "student": 2, "teach": 2, "tutor": 2.5, "learn": 1.5, "course": 1.5,
        "exam": 2, "flashcard": 2.5, "lesson": 2, "quiz": 2, "homework": 2, "school": 1.5,
        "university": 1, "math": 1.5, "study": 1,
    },
    "integrations": {
        "integration": 2, "mcp": 1.5, "connector": 2, "connect": 1, "slack": 2, "jira": 2,
        "notion": 1, "google": 1, "salesforce": 2, "hubspot": 2, "webhook": 1.5, "zapier": 2,
        "bridge": 1, "sync": 1, "tracker": 1, "server": 0.5, "export": 0.5, "api": 0.5,
    },
}  # fmt: skip

CAUSE_TERMS: dict[str, dict[str, float]] = {
    "automate": {
        "automate": 2, "repetitive": 2, "workflow": 1, "batch": 1, "hook": 1, "schedule": 1,
        "cron": 1, "routine": 1, "triage": 1, "deploy": 0.5, "pipeline": 0.5,
    },
    "standardize": {
        "style": 2, "convention": 2, "conventional": 2, "consistent": 2, "standard": 1.5,
        "guideline": 1.5, "format": 1, "template": 1, "best": 0.5, "practice": 0.5,
        "unify": 1.5,
    },
    "comply": {
        "compliance": 2, "regulation": 2, "audit": 1.5, "policy": 1.5, "owasp": 2, "gdpr": 2,
        "tax": 1.5, "legal": 1, "wcag": 1.5, "accessibility": 1, "iso": 1, "vat": 1.5,
        "control": 0.5, "checklist": 1,
    },
    "onboard": {
        "onboard": 2.5, "onboarding": 2.5, "learn": 1.5, "tutorial": 2, "explain": 1.5,
        "beginner": 2, "teach": 1.5, "newcomer": 2, "tutor": 1.5, "student": 1, "study": 1,
    },
    "integrate": {
        "integration": 2, "connect": 1.5, "connector": 2, "mcp": 1.5, "sync": 1.5,
        "bridge": 1.5, "export": 1, "import": 1, "slack": 1, "jira": 1, "figma": 1,
        "api": 0.5, "server": 0.5,
    },
    "reduce_errors": {
        "bug": 1.5, "error": 1.5, "fix": 1, "test": 1, "review": 1, "validate": 1.5,
        "check": 1, "lint": 1.5, "secure": 1, "security": 1, "safety": 1, "prevent": 1.5,
        "quality": 1, "flaky": 1.5, "secret": 1, "vulnerability": 1, "risk": 1,
    },
    "generate_docs": {
        "docs": 2, "documentation": 2, "readme": 2, "report": 1.5, "changelog": 2,
        "summary": 1.5, "summarize": 1.5, "document": 1.5, "pdf": 1, "presentation": 1,
        "card": 1, "notes": 1, "write": 0.5, "writing": 0.5, "slide": 1,
    },
}  # fmt: skip
