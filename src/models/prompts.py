from pydantic import BaseModel
from typing import Optional


class EvalResults(BaseModel):
    eval_run_id: str
    composite_score_mean: float
    composite_score_ci_95: list[float]
    compliance_pass_rate: float
    decision: str


class PromptVersion(BaseModel):
    id: str
    agent: str
    version: int
    parent_version: Optional[int]
    prompt_text: str
    token_count: int
    is_current: bool
    change_description: str
    eval_results: Optional[EvalResults] = None
