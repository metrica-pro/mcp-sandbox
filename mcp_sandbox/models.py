from typing import List, Optional
from pydantic import BaseModel


class FileLink(BaseModel):
    name: str
    url: str


class CodeExecutionResponse(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    files: List[str] = []
    file_links: List[FileLink] = []
    error: Optional[str] = None
