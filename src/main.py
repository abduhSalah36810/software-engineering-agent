import os
import re
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from src.graph import myapp
from src.api.routes import router as project_router

# Default explicit allowlist for local frontend development (Vite, React dev servers)
DEFAULT_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
]


def get_cors_origins() -> list[str]:
    """
    Returns explicit allowed origins for CORS.
    Reads comma- or semicolon-separated origins from the CORS_ALLOWED_ORIGINS
    environment variable if configured, otherwise falls back to standard
    local frontend development origins.
    """
    env_origins = os.getenv("CORS_ALLOWED_ORIGINS")
    if env_origins:
        parsed = [o.strip() for o in re.split(r"[,;]", env_origins) if o.strip()]
        if parsed:
            return parsed
    return DEFAULT_CORS_ORIGINS


app = FastAPI()

# Explicit CORS allowlist for local frontend development
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount read-only Project Overview router
app.include_router(project_router)


class InitialState(BaseModel):
    url: str
    problem: str


@app.post("/agent/run")
def call_the_agent(initialstate: InitialState):
    state = {
        "url": initialstate.url,
        "problem": initialstate.problem
    }

    result = myapp.invoke(state)

    return {
        "root_cause": result.get("root_cause"),
        "plan": result.get("plan"),
        "modified_files": result.get("modified_files"),
        "test_passed": result.get("test_passed"),
        "investigation": result.get("investigation"),
        "test_output": result.get("test_output"),
        "indexed_document_count": result.get("indexed_document_count"),
    }
