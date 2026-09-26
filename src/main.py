from fastapi import FastAPI
from pydantic import BaseModel
from src.graph import myapp

app = FastAPI()


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
