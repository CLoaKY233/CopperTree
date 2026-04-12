"""
Unit tests for src/llm/utils.py

Covers parse_llm_json(raw, ModelClass):
  - Valid plain JSON → returns correct Pydantic model instance
  - JSON inside markdown ```json ... ``` fences → strips fences and parses
  - JSON inside plain ``` ... ``` fences → strips fences and parses
  - Leading/trailing whitespace → handled transparently
  - Invalid JSON → raises ValueError (not JSONDecodeError exposed to caller)
  - JSON missing a required field → raises ValueError (Pydantic validation)
  - Extra fields in JSON are allowed (Pydantic default)
  - Correct field values on the returned model instance

No external dependencies — no mocking required.
"""

import pytest
from pydantic import BaseModel

from src.llm.utils import parse_llm_json


# ---------------------------------------------------------------------------
# Shared test model
# ---------------------------------------------------------------------------

class TestModel(BaseModel):
    name: str
    value: int


class NestedModel(BaseModel):
    """Used to verify nested structures are handled correctly."""
    label: str
    count: int
    active: bool


# ---------------------------------------------------------------------------
# Happy path — plain JSON
# ---------------------------------------------------------------------------


class TestParseLlmJsonHappyPath:
    """Valid JSON inputs must return correct, fully-populated model instances."""

    def test_valid_json_returns_model_instance(self):
        raw = '{"name": "Alice", "value": 42}'
        result = parse_llm_json(raw, TestModel)
        assert isinstance(result, TestModel)

    def test_valid_json_correct_name_field(self):
        raw = '{"name": "Alice", "value": 42}'
        result = parse_llm_json(raw, TestModel)
        assert result.name == "Alice"

    def test_valid_json_correct_value_field(self):
        raw = '{"name": "Alice", "value": 42}'
        result = parse_llm_json(raw, TestModel)
        assert result.value == 42

    def test_value_zero_is_valid(self):
        raw = '{"name": "Zero", "value": 0}'
        result = parse_llm_json(raw, TestModel)
        assert result.value == 0

    def test_value_negative_is_valid(self):
        raw = '{"name": "Negative", "value": -1}'
        result = parse_llm_json(raw, TestModel)
        assert result.value == -1

    def test_empty_string_name_is_valid(self):
        raw = '{"name": "", "value": 1}'
        result = parse_llm_json(raw, TestModel)
        assert result.name == ""

    def test_unicode_name_handled(self):
        raw = '{"name": "Ångström", "value": 99}'
        result = parse_llm_json(raw, TestModel)
        assert result.name == "Ångström"

    def test_extra_fields_do_not_raise(self):
        # Pydantic v2 default: extra fields ignored
        raw = '{"name": "Bob", "value": 7, "extra_field": "ignored"}'
        result = parse_llm_json(raw, TestModel)
        assert result.name == "Bob"
        assert result.value == 7

    def test_nested_model_parsed_correctly(self):
        raw = '{"label": "open", "count": 3, "active": true}'
        result = parse_llm_json(raw, NestedModel)
        assert result.label == "open"
        assert result.count == 3
        assert result.active is True


# ---------------------------------------------------------------------------
# Markdown fence stripping
# ---------------------------------------------------------------------------


class TestParseLlmJsonMarkdownFences:
    """LLM outputs often wrap JSON in markdown code fences; these must be stripped."""

    def test_json_fence_with_json_language_tag(self):
        raw = '```json\n{"name": "Bob", "value": 7}\n```'
        result = parse_llm_json(raw, TestModel)
        assert result.name == "Bob"
        assert result.value == 7

    def test_json_fence_without_language_tag(self):
        raw = '```\n{"name": "Carol", "value": 3}\n```'
        result = parse_llm_json(raw, TestModel)
        assert result.name == "Carol"
        assert result.value == 3

    def test_json_fence_with_surrounding_prose(self):
        raw = (
            "Here is the response you asked for:\n"
            "```json\n"
            '{"name": "Dave", "value": 55}\n'
            "```\n"
            "Let me know if you need anything else."
        )
        result = parse_llm_json(raw, TestModel)
        assert result.name == "Dave"
        assert result.value == 55

    def test_json_fence_with_extra_whitespace_inside(self):
        raw = "```json\n\n  {\"name\": \"Eve\", \"value\": 1}  \n\n```"
        result = parse_llm_json(raw, TestModel)
        assert result.name == "Eve"
        assert result.value == 1

    def test_json_fence_multiline_json(self):
        raw = '```json\n{\n  "name": "Frank",\n  "value": 100\n}\n```'
        result = parse_llm_json(raw, TestModel)
        assert result.name == "Frank"
        assert result.value == 100


# ---------------------------------------------------------------------------
# Whitespace handling
# ---------------------------------------------------------------------------


class TestParseLlmJsonWhitespace:
    """Leading and trailing whitespace in raw input must be handled transparently."""

    def test_leading_whitespace_stripped(self):
        raw = '   {"name": "Grace", "value": 8}'
        result = parse_llm_json(raw, TestModel)
        assert result.name == "Grace"

    def test_trailing_whitespace_stripped(self):
        raw = '{"name": "Hank", "value": 9}   '
        result = parse_llm_json(raw, TestModel)
        assert result.value == 9

    def test_leading_and_trailing_newlines(self):
        raw = '\n\n{"name": "Iris", "value": 10}\n\n'
        result = parse_llm_json(raw, TestModel)
        assert result.name == "Iris"

    def test_tabs_and_spaces_mixed(self):
        raw = '\t  {"name": "Jay", "value": 11}  \t'
        result = parse_llm_json(raw, TestModel)
        assert result.value == 11


# ---------------------------------------------------------------------------
# Invalid JSON — raises ValueError
# ---------------------------------------------------------------------------


class TestParseLlmJsonInvalidJson:
    """Malformed JSON must raise ValueError (never JSONDecodeError directly)."""

    def test_completely_invalid_string_raises_value_error(self):
        with pytest.raises(ValueError):
            parse_llm_json("this is not json at all", TestModel)

    def test_truncated_json_raises_value_error(self):
        with pytest.raises(ValueError):
            parse_llm_json('{"name": "Alice"', TestModel)

    def test_empty_string_raises_value_error(self):
        with pytest.raises(ValueError):
            parse_llm_json("", TestModel)

    def test_json_array_instead_of_object_raises_value_error(self):
        # A JSON array is valid JSON but not a valid dict for Pydantic
        with pytest.raises(ValueError):
            parse_llm_json('[1, 2, 3]', TestModel)

    def test_plain_number_raises_value_error(self):
        with pytest.raises(ValueError):
            parse_llm_json("42", TestModel)

    def test_json_null_raises_value_error(self):
        with pytest.raises(ValueError):
            parse_llm_json("null", TestModel)

    def test_single_quotes_not_valid_json_raises_value_error(self):
        # Python dict repr — not valid JSON
        with pytest.raises(ValueError):
            parse_llm_json("{'name': 'bad', 'value': 1}", TestModel)

    def test_value_error_message_contains_useful_context(self):
        raw = "not json"
        with pytest.raises(ValueError, match=r"(?i)(json|LLM|valid)"):
            parse_llm_json(raw, TestModel)

    def test_prose_around_invalid_json_raises_value_error(self):
        raw = "The answer is: name=Alice and value=42"
        with pytest.raises(ValueError):
            parse_llm_json(raw, TestModel)


# ---------------------------------------------------------------------------
# Missing required fields — raises ValueError
# ---------------------------------------------------------------------------


class TestParseLlmJsonMissingFields:
    """JSON that omits required Pydantic fields must raise ValueError."""

    def test_missing_required_name_field_raises_value_error(self):
        raw = '{"value": 5}'
        with pytest.raises(ValueError):
            parse_llm_json(raw, TestModel)

    def test_missing_required_value_field_raises_value_error(self):
        raw = '{"name": "Alice"}'
        with pytest.raises(ValueError):
            parse_llm_json(raw, TestModel)

    def test_empty_json_object_raises_value_error(self):
        raw = '{}'
        with pytest.raises(ValueError):
            parse_llm_json(raw, TestModel)

    def test_wrong_type_for_value_field_raises_value_error(self):
        # "value" must be int; a non-coercible string should fail
        raw = '{"name": "Alice", "value": "not-an-int"}'
        with pytest.raises(ValueError):
            parse_llm_json(raw, TestModel)

    def test_null_required_field_raises_value_error(self):
        raw = '{"name": null, "value": 1}'
        with pytest.raises(ValueError):
            parse_llm_json(raw, TestModel)
