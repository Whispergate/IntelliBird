"""RED tests for AI attack path analysis - prompt constants and builder.

Plan 35-01 (TDD RED phase): These tests define the interface contract for
SYSTEM_PROMPT_ATTACK_PATH_V1 and build_attack_path_messages.

These tests MUST FAIL before Plan 35-02 implements the constants and builder.
They will be made GREEN in Plan 35-02/35-03.
"""
import json
import os
import re
import subprocess


os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)

from app.services.llm.prompts import (  # noqa: E402
    SYSTEM_PROMPT_ATTACK_PATH_V1,
    build_attack_path_messages,
)

# ---------------------------------------------------------------------------
# Minimal fixture payload for builder tests
# ---------------------------------------------------------------------------

SAMPLE_PAYLOAD = {
    "events": [
        {
            "title": "Spearphishing campaign detected",
            "description": "Targeted emails with malicious attachments observed.",
            "occurred_at": "2026-05-01",
            "tags": ["apt29", "spearphishing"],
            "attack_technique_ids": ["T1566.001"],
        }
    ],
    "truncated": False,
    "project_days_window": 30,
}


# ---------------------------------------------------------------------------
# Tests for SYSTEM_PROMPT_ATTACK_PATH_V1
# ---------------------------------------------------------------------------


def test_prompt_constant_is_non_empty_string():
    """SYSTEM_PROMPT_ATTACK_PATH_V1 is a non-empty string."""
    assert isinstance(SYSTEM_PROMPT_ATTACK_PATH_V1, str)
    assert len(SYSTEM_PROMPT_ATTACK_PATH_V1) > 0


def test_prompt_contains_mitre_attack():
    """SYSTEM_PROMPT_ATTACK_PATH_V1 references 'MITRE ATT&CK' for grounding."""
    assert "MITRE ATT&CK" in SYSTEM_PROMPT_ATTACK_PATH_V1


def test_prompt_contains_max_nodes_guard():
    """SYSTEM_PROMPT_ATTACK_PATH_V1 contains 'Max 12 nodes' as sprawl guard."""
    assert "Max 12 nodes" in SYSTEM_PROMPT_ATTACK_PATH_V1


def test_prompt_contains_technique_id_pattern():
    """SYSTEM_PROMPT_ATTACK_PATH_V1 contains technique ID format constraint (T\\d{4})."""
    assert re.search(r"T\\d\{4\}", SYSTEM_PROMPT_ATTACK_PATH_V1) or \
           "T\\d{4}" in SYSTEM_PROMPT_ATTACK_PATH_V1 or \
           re.search(r"T\d{4}", SYSTEM_PROMPT_ATTACK_PATH_V1)


# ---------------------------------------------------------------------------
# Tests for build_attack_path_messages
# ---------------------------------------------------------------------------


def test_builder_returns_list_of_two():
    """build_attack_path_messages returns a list with exactly 2 messages."""
    messages = build_attack_path_messages(SAMPLE_PAYLOAD)
    assert isinstance(messages, list)
    assert len(messages) == 2


def test_builder_first_message_is_system():
    """First message has role='system'."""
    messages = build_attack_path_messages(SAMPLE_PAYLOAD)
    assert messages[0]["role"] == "system"


def test_builder_second_message_is_user():
    """Second message has role='user'."""
    messages = build_attack_path_messages(SAMPLE_PAYLOAD)
    assert messages[1]["role"] == "user"


def test_builder_user_content_is_valid_json():
    """User message content is valid JSON (json.loads succeeds)."""
    messages = build_attack_path_messages(SAMPLE_PAYLOAD)
    user_content = messages[1]["content"]
    # Should not raise
    parsed = json.loads(user_content)
    assert parsed is not None


def test_builder_user_json_contains_events_key():
    """User message JSON contains the 'events' key."""
    messages = build_attack_path_messages(SAMPLE_PAYLOAD)
    parsed = json.loads(messages[1]["content"])
    assert "events" in parsed


def test_builder_user_json_contains_project_days_window_key():
    """User message JSON contains the 'project_days_window' key."""
    messages = build_attack_path_messages(SAMPLE_PAYLOAD)
    parsed = json.loads(messages[1]["content"])
    assert "project_days_window" in parsed


def test_builder_user_json_contains_truncated_key():
    """User message JSON contains the 'truncated' key."""
    messages = build_attack_path_messages(SAMPLE_PAYLOAD)
    parsed = json.loads(messages[1]["content"])
    assert "truncated" in parsed


def test_no_fstring_event_interpolation_in_prompts_module():
    """C-3 compliance: no f-string with event. appears in prompts.py.

    Uses ripgrep (rg) to assert zero matches for the prompt-injection pattern.
    rg returns exit code 1 when no matches found - that is the expected result.
    """
    import shutil
    prompts_path = os.path.join(
        os.path.dirname(__file__),
        "..", "..", "app", "services", "llm", "prompts.py"
    )
    prompts_path = os.path.abspath(prompts_path)

    if shutil.which("rg"):
        result = subprocess.run(
            ["rg", r'f".*event\.', prompts_path],
            capture_output=True,
            text=True,
        )
        # returncode 1 = no matches (which is what we want)
        # returncode 0 = matches found (bad - prompt injection risk)
        assert result.returncode != 0, (
            f"Prompt injection risk: f-string with event. found in prompts.py:\n"
            f"{result.stdout}"
        )
    else:
        # Fallback: read file and check manually
        with open(prompts_path, "r") as f:
            content = f.read()
        assert 'f"' not in content or 'event.' not in content, (
            "Possible prompt injection: f-string with event. in prompts.py"
        )
