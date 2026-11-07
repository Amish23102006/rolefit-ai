"""Controlled skill vocabulary (deterministic; no model involved)."""
import re

VOCAB = {
    "python", "java", "c++", "javascript", "typescript", "sql", "docker", "kubernetes", "pytorch",
    "tensorflow", "scikit-learn", "pandas", "numpy", "fastapi", "flask", "django", "react", "git",
    "linux", "aws", "gcp", "azure", "nlp", "computer vision", "machine learning", "deep learning",
    "llm", "rest api", "postgresql", "mongodb", "ci/cd", "spark", "tableau", "excel", "rust", "golang",
    # AI / GenAI
    "generative ai", "rag", "langchain", "langgraph", "transformers", "hugging face", "prompt engineering",
    "fine-tuning", "mlops", "keras", "xgboost", "opencv", "reinforcement learning", "time series",
    "recommender systems", "a/b testing", "statistics", "data analysis", "data visualization", "power bi",
    "matplotlib", "seaborn", "big data", "hadoop", "kafka", "airflow", "snowflake", "bigquery", "databricks",
    "etl", "data engineering", "data modeling",
    # software
    "c#", "kotlin", "swift", "scala", "php", "html", "css", "node.js", "express.js", "spring boot", "angular",
    "vue", "next.js", "graphql", "microservices", "redis", "mysql", "nosql", "terraform", "jenkins",
    "github actions", "unit testing", "data structures", "algorithms", "object-oriented programming",
    "system design", "distributed systems", "cloud computing", "android", "ios", "selenium",
    # ways of working
    "agile", "scrum", "jira",
}
ALIASES = {"ml": "machine learning", "k8s": "kubernetes", "postgres": "postgresql",
           "sklearn": "scikit-learn", "js": "javascript", "ts": "typescript", "dl": "deep learning",
           "genai": "generative ai", "gen ai": "generative ai", "large language models": "llm", "llms": "llm",
           "huggingface": "hugging face", "retrieval-augmented generation": "rag", "nodejs": "node.js", "restful": "rest api", "rest apis": "rest api", "restful apis": "rest api", "expressjs": "express.js",
           "powerbi": "power bi", "dsa": "data structures", "oop": "object-oriented programming",
           "data analytics": "data analysis", "reactjs": "react", "react.js": "react", "vue.js": "vue",
           "nextjs": "next.js", "pyspark": "spark", "tf": "tensorflow", "fine tuning": "fine-tuning",
           "natural language processing": "nlp", "amazon web services": "aws", "google cloud": "gcp"}
_TERMS = sorted(list(VOCAB) + list(ALIASES), key=len, reverse=True)
_RX = re.compile(r"(?<![\w+#/])(" + "|".join(re.escape(t) for t in _TERMS) + r")(?![\w+#])", re.I)


def normalize(skill: str) -> str:
    s = skill.strip().lower()
    return ALIASES.get(s, s)


def find_skills(text: str) -> set:
    return {normalize(m) for m in _RX.findall(text)}
