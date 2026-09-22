from dataclasses import dataclass

@dataclass 
class CodeDocument: 
    file: str 
    language:str
    symbol : str
    type : str
    parent: str | None
    start_line: int
    end_line : int
    content : str