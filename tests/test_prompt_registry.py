"""
Unit tests for src/storage/prompt_registry.py

All MongoDB calls are intercepted by patching `prompt_versions` at the
module level inside prompt_registry (i.e. `src.storage.prompt_registry.prompt_versions`).
No real MongoDB connection is established.

Key architectural note:
  - `rollback` inlines its own update_many / update_one calls rather than
    delegating to `promote_version`. Tests therefore assert on raw mongo
    mock calls for rollback, not on promote_version being called.
  - `promote_version("nonexistent")` → raises ValueError because find_one returns None.
"""

from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Fixture: fresh mock collection for every test
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_pv():
    """
    Patch `prompt_versions` collection inside prompt_registry for the duration
    of one test.  Returns the mock so tests can configure return values and
    assert calls.
    """
    with patch("src.storage.prompt_registry.prompt_versions") as mock:
        yield mock


# ---------------------------------------------------------------------------
# get_current_prompt
# ---------------------------------------------------------------------------


class TestGetCurrentPrompt:
    """get_current_prompt must call find_one with the correct filter."""

    def test_calls_find_one_with_agent_and_is_current_filter(self, mock_pv):
        from src.storage.prompt_registry import get_current_prompt

        mock_pv.find_one.return_value = {"_id": "collector_v3", "agent": "collector"}

        get_current_prompt("collector")

        mock_pv.find_one.assert_called_once_with(
            {"agent": "collector", "is_current": True}
        )

    def test_returns_document_from_find_one(self, mock_pv):
        from src.storage.prompt_registry import get_current_prompt

        expected = {"_id": "collector_v3", "agent": "collector", "is_current": True}
        mock_pv.find_one.return_value = expected

        result = get_current_prompt("collector")

        assert result == expected

    def test_returns_none_when_no_current_prompt_exists(self, mock_pv):
        from src.storage.prompt_registry import get_current_prompt

        mock_pv.find_one.return_value = None

        result = get_current_prompt("collector")

        assert result is None

    def test_different_agent_names_produce_correct_filters(self, mock_pv):
        from src.storage.prompt_registry import get_current_prompt

        mock_pv.find_one.return_value = None

        get_current_prompt("negotiator")

        mock_pv.find_one.assert_called_once_with(
            {"agent": "negotiator", "is_current": True}
        )


# ---------------------------------------------------------------------------
# save_new_version
# ---------------------------------------------------------------------------


class TestSaveNewVersion:
    """save_new_version must insert a correctly shaped document and return the doc_id."""

    def _call(self, mock_pv, **kwargs):
        from src.storage.prompt_registry import save_new_version

        defaults = dict(
            agent="collector",
            prompt_text="You are a collections agent.",
            parent_version=2,
            change_description="Improved tone",
            token_count=120,
        )
        defaults.update(kwargs)
        return save_new_version(**defaults)

    def test_returns_agent_v_version_format(self, mock_pv):
        doc_id = self._call(mock_pv)
        # parent_version=2 → version=3 → doc_id="collector_v3"
        assert doc_id == "collector_v3"

    def test_version_is_parent_plus_one(self, mock_pv):
        doc_id = self._call(mock_pv, agent="collector", parent_version=9)
        assert doc_id == "collector_v10"

    def test_doc_id_uses_agent_name(self, mock_pv):
        doc_id = self._call(mock_pv, agent="negotiator", parent_version=0)
        assert doc_id == "negotiator_v1"

    def test_calls_insert_one(self, mock_pv):
        self._call(mock_pv)
        mock_pv.insert_one.assert_called_once()

    def test_inserted_doc_has_correct_id(self, mock_pv):
        self._call(mock_pv, agent="collector", parent_version=2)
        inserted_doc = mock_pv.insert_one.call_args[0][0]
        assert inserted_doc["_id"] == "collector_v3"

    def test_inserted_doc_has_correct_agent(self, mock_pv):
        self._call(mock_pv, agent="collector")
        inserted_doc = mock_pv.insert_one.call_args[0][0]
        assert inserted_doc["agent"] == "collector"

    def test_inserted_doc_has_correct_version_number(self, mock_pv):
        self._call(mock_pv, parent_version=4)
        inserted_doc = mock_pv.insert_one.call_args[0][0]
        assert inserted_doc["version"] == 5

    def test_inserted_doc_has_correct_parent_version(self, mock_pv):
        self._call(mock_pv, parent_version=4)
        inserted_doc = mock_pv.insert_one.call_args[0][0]
        assert inserted_doc["parent_version"] == 4

    def test_inserted_doc_has_correct_prompt_text(self, mock_pv):
        self._call(mock_pv, prompt_text="Custom prompt text")
        inserted_doc = mock_pv.insert_one.call_args[0][0]
        assert inserted_doc["prompt_text"] == "Custom prompt text"

    def test_inserted_doc_has_correct_token_count(self, mock_pv):
        self._call(mock_pv, token_count=250)
        inserted_doc = mock_pv.insert_one.call_args[0][0]
        assert inserted_doc["token_count"] == 250

    def test_inserted_doc_has_correct_change_description(self, mock_pv):
        self._call(mock_pv, change_description="Tone change")
        inserted_doc = mock_pv.insert_one.call_args[0][0]
        assert inserted_doc["change_description"] == "Tone change"

    def test_inserted_doc_is_not_current(self, mock_pv):
        # New versions are always saved as non-current
        self._call(mock_pv)
        inserted_doc = mock_pv.insert_one.call_args[0][0]
        assert inserted_doc["is_current"] is False

    def test_inserted_doc_has_null_eval_results(self, mock_pv):
        self._call(mock_pv)
        inserted_doc = mock_pv.insert_one.call_args[0][0]
        assert inserted_doc["eval_results"] is None

    def test_inserted_doc_contains_all_required_keys(self, mock_pv):
        self._call(mock_pv)
        inserted_doc = mock_pv.insert_one.call_args[0][0]
        required_keys = {
            "_id",
            "agent",
            "version",
            "parent_version",
            "prompt_text",
            "token_count",
            "is_current",
            "change_description",
            "eval_results",
        }
        assert required_keys.issubset(set(inserted_doc.keys()))


# ---------------------------------------------------------------------------
# promote_version
# ---------------------------------------------------------------------------


class TestPromoteVersion:
    """promote_version must clear old current flag then set new current flag."""

    def test_raises_value_error_when_doc_not_found(self, mock_pv):
        from src.storage.prompt_registry import promote_version

        mock_pv.find_one.return_value = None

        with pytest.raises(ValueError, match=r"collector_v99"):
            promote_version("collector_v99")

    def test_value_error_message_contains_doc_id(self, mock_pv):
        from src.storage.prompt_registry import promote_version

        mock_pv.find_one.return_value = None

        with pytest.raises(ValueError) as exc_info:
            promote_version("nonexistent_id")

        assert "nonexistent_id" in str(exc_info.value)

    def test_calls_update_many_to_clear_old_current(self, mock_pv):
        from src.storage.prompt_registry import promote_version

        mock_pv.find_one.return_value = {"_id": "collector_v3", "agent": "collector"}

        promote_version("collector_v3")

        mock_pv.update_many.assert_called_once_with(
            {"agent": "collector", "is_current": True},
            {"$set": {"is_current": False}},
        )

    def test_calls_update_one_to_set_new_current(self, mock_pv):
        from src.storage.prompt_registry import promote_version

        mock_pv.find_one.return_value = {"_id": "collector_v3", "agent": "collector"}

        promote_version("collector_v3")

        mock_pv.update_one.assert_called_with(
            {"_id": "collector_v3"},
            {"$set": {"is_current": True}},
        )

    def test_update_many_called_before_update_one(self, mock_pv):
        from src.storage.prompt_registry import promote_version

        mock_pv.find_one.return_value = {"_id": "collector_v3", "agent": "collector"}
        call_order = []

        mock_pv.update_many.side_effect = lambda *a, **kw: call_order.append(
            "update_many"
        )
        mock_pv.update_one.side_effect = lambda *a, **kw: call_order.append(
            "update_one"
        )

        promote_version("collector_v3")

        assert call_order[0] == "update_many"
        assert "update_one" in call_order

    def test_find_one_called_with_doc_id(self, mock_pv):
        from src.storage.prompt_registry import promote_version

        mock_pv.find_one.return_value = {"_id": "collector_v3", "agent": "collector"}

        promote_version("collector_v3")

        mock_pv.find_one.assert_called_with({"_id": "collector_v3"})

    def test_promote_with_eval_results_calls_update_one_for_eval(self, mock_pv):
        from src.storage.prompt_registry import promote_version

        mock_pv.find_one.return_value = {"_id": "collector_v3", "agent": "collector"}
        eval_data = {"score": 0.95, "pass": True}

        promote_version("collector_v3", eval_results=eval_data)

        # First update_one call should set eval_results
        first_update_call = mock_pv.update_one.call_args_list[0]
        assert first_update_call == call(
            {"_id": "collector_v3"},
            {"$set": {"eval_results": eval_data}},
        )


# ---------------------------------------------------------------------------
# rollback
# ---------------------------------------------------------------------------


class TestRollback:
    """rollback must restore is_current to the target version via direct mongo calls."""

    def test_rollback_raises_value_error_when_version_not_found(self, mock_pv):
        from src.storage.prompt_registry import rollback

        mock_pv.find_one.return_value = None

        with pytest.raises(ValueError, match=r"collector_v5"):
            rollback("collector", 5)

    def test_rollback_find_one_uses_agent_version_id_format(self, mock_pv):
        from src.storage.prompt_registry import rollback

        mock_pv.find_one.return_value = {"_id": "collector_v2", "agent": "collector"}

        rollback("collector", 2)

        mock_pv.find_one.assert_called_with({"_id": "collector_v2"})

    def test_rollback_calls_update_many_to_clear_old_current(self, mock_pv):
        from src.storage.prompt_registry import rollback

        mock_pv.find_one.return_value = {"_id": "collector_v2", "agent": "collector"}

        rollback("collector", 2)

        mock_pv.update_many.assert_called_once_with(
            {"agent": "collector", "is_current": True},
            {"$set": {"is_current": False}},
        )

    def test_rollback_calls_update_one_to_set_target_current(self, mock_pv):
        from src.storage.prompt_registry import rollback

        mock_pv.find_one.return_value = {"_id": "collector_v2", "agent": "collector"}

        rollback("collector", 2)

        mock_pv.update_one.assert_called_with(
            {"_id": "collector_v2"},
            {"$set": {"is_current": True}},
        )

    def test_rollback_constructs_correct_doc_id_for_different_version(self, mock_pv):
        from src.storage.prompt_registry import rollback

        mock_pv.find_one.return_value = {"_id": "negotiator_v7", "agent": "negotiator"}

        rollback("negotiator", 7)

        mock_pv.find_one.assert_called_with({"_id": "negotiator_v7"})

    def test_rollback_version_error_message_includes_agent_and_version(self, mock_pv):
        from src.storage.prompt_registry import rollback

        mock_pv.find_one.return_value = None

        with pytest.raises(ValueError) as exc_info:
            rollback("collector", 99)

        assert "collector" in str(exc_info.value)
        assert "99" in str(exc_info.value)

    def test_rollback_does_not_call_promote_version_function(self, mock_pv):
        """rollback inlines its own logic; it must not call promote_version indirectly."""
        from src.storage import prompt_registry

        mock_pv.find_one.return_value = {"_id": "collector_v1", "agent": "collector"}

        with patch.object(prompt_registry, "promote_version") as mock_promote:
            prompt_registry.rollback("collector", 1)
            # promote_version should NOT have been called
            mock_promote.assert_not_called()
