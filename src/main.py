from fastapi import FastAPI 
from pydantic import BaseModel
from graph import myapp 

app = FastAPI()


class InitialState(BaseModel) : 
  url : str 
  problem : str

@app.post("/agent/run")
def call_the_agent(initialstate: InitialState):

    state = {
        "url": initialstate.url,
        "problem": initialstate.problem
    }

    result = myapp.invoke(state)


