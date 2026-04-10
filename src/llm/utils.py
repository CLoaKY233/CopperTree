import json
import re
from typing import TypeVar, Type

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

_JSON_BLOCK = re.compile(r"```(?:json)?\s*([\s\S]*?)```")


def parse_llm_json(raw: str, model: Type[T]) -> T:
    """
    Extract JSON from LLM output and validate through a Pydantic model.
    Handles common LLM habits: markdown code fences, leading/trailing text.
    Raises ValueError with a clear message on failure.
    """
    # Try markdown code fence first
    match = _JSON_BLOCK.search(raw)
    candidate = match.group(1).strip() if match else raw.strip()

    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        # Fallback: try the raw string in case there was no fence
        try:
            data = json.loads(raw.strip())
        except json.JSONDecodeError as e:
            raise ValueError(
                f"LLM did not produce valid JSON. Error: {e}\nRaw output: {raw[:300]}"
            ) from e

    try:
        return model.model_validate(data)
    except ValidationError as e:
        raise ValueError(
            f"LLM JSON failed Pydantic validation: {e}\nData: {data}"
        ) from e
