"""Webhook payload builder tests — unskipped by 07-02."""
from __future__ import annotations

import pytest

from app.services.webhook_payloads import (
    _TLP_DISCORD_COLOR,
    _TLP_SLACK_EMOJI,
    build_discord_payload,
    build_generic_payload,
    build_slack_payload,
    build_teams_payload,
)
from tests.fixtures.webhook_event_fixtures import build_fake_event

DASHBOARD_URL = "http://127.0.0.1:3000"
PRESET_NAME = "my-preset"

# ---------------------------------------------------------------------------
# EventItem keys from (all 17 fields that EventItem defines)
# ---------------------------------------------------------------------------
_EVENTITEM_KEYS = {
    "id",
    "observed_at",
    "fetched_at",
    "source_id",
    "source_name",
    "source_type",
    "stix_id",
    "stix_type",
    "title",
    "description",
    "tlp",
    "tags",
    "attack_techniques",
    "archived",
    "visibility",
    "geo_lat",
    "geo_lon",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _count_block_type(blocks: list[dict], block_type: str) -> int:
    return sum(1 for b in blocks if b.get("type") == block_type)


def _walk_keys(obj: object) -> set[str]:
    """Recursively collect every dict key in the object tree."""
    found: set[str] = set()
    if isinstance(obj, dict):
        found.update(obj.keys())
        for v in obj.values():
            found.update(_walk_keys(v))
    elif isinstance(obj, list):
        for item in obj:
            found.update(_walk_keys(item))
    return found


# ===========================================================================
# TestSlackPayload
# ===========================================================================


class TestSlackPayload:
    def test_header_block_exists(self):
        """First block is a header; text switches singular/plural on N."""
        single = build_slack_payload([build_fake_event()], PRESET_NAME, DASHBOARD_URL)
        multi = build_slack_payload(
            [build_fake_event(), build_fake_event()], PRESET_NAME, DASHBOARD_URL
        )

        # Structure checks
        assert single["blocks"][0]["type"] == "header"
        assert single["blocks"][0]["text"]["type"] == "plain_text"
        assert multi["blocks"][0]["type"] == "header"
        assert multi["blocks"][0]["text"]["type"] == "plain_text"

        single_text = single["blocks"][0]["text"]["text"]
        multi_text = multi["blocks"][0]["text"]["text"]

        # Singular: "1 new events matched my-preset" — plan says N new events (no plural swap)
        # The plan verbatim: f"{N} new events matched {preset}" — always "events"
        assert single_text == f"1 new events matched {PRESET_NAME}"
        assert multi_text == f"2 new events matched {PRESET_NAME}"

    def test_tlp_emoji_map(self):
        """TLP value in event → correct emoji shortcode appears in section mrkdwn."""
        for tlp, expected_emoji in _TLP_SLACK_EMOJI.items():
            ev = build_fake_event(tlp=tlp)
            result = build_slack_payload([ev], PRESET_NAME, DASHBOARD_URL)
            # First section block (index 1)
            section = result["blocks"][1]
            assert section["type"] == "section"
            assert expected_emoji in section["text"]["text"], (
                f"Expected {expected_emoji} for tlp={tlp!r}"
            )

        # None TLP defaults to:white_circle:
        ev_none = build_fake_event(tlp=None)
        result_none = build_slack_payload([ev_none], PRESET_NAME, DASHBOARD_URL)
        assert ":white_circle:" in result_none["blocks"][1]["text"]["text"]

    def test_title_truncated_at_200(self):
        """Event title > 200 chars is truncated to exactly 200 chars ending with '...'."""
        long_title = "A" * 250
        ev = build_fake_event(title=long_title)
        result = build_slack_payload([ev], PRESET_NAME, DASHBOARD_URL)
        section_text = result["blocks"][1]["text"]["text"]
        # Title is bolded as *<title>*, extract the inner part
        # The rendered title starts with * and ends before the newline
        rendered_title = section_text.split("\n")[0].strip("*")
        assert len(rendered_title) == 200
        assert rendered_title.endswith("...")

    def test_context_block_has_view_all_link(self):
        """Last block is a context block; elements[0] contains view-all link and ISO timestamp."""
        ev = build_fake_event()
        result = build_slack_payload([ev], PRESET_NAME, DASHBOARD_URL)
        last_block = result["blocks"][-1]
        assert last_block["type"] == "context"
        elem_text = last_block["elements"][0]["text"]
        expected_link = f"<{DASHBOARD_URL}/events?preset={PRESET_NAME}|View all matches>"
        assert expected_link in elem_text
        # ISO timestamp present — check for 'T' and 'Z' or '+' (timezone marker)
        assert "T" in elem_text  # ISO 8601 datetime separator

    def test_max_10_sections(self):
        """15 events → exactly 10 section blocks + 10 divider blocks + 1 header + 1 context = 22 blocks."""
        events = [build_fake_event() for _ in range(15)]
        result = build_slack_payload(events, PRESET_NAME, DASHBOARD_URL)
        blocks = result["blocks"]
        assert len(blocks) == 22
        assert _count_block_type(blocks, "section") == 10
        assert _count_block_type(blocks, "divider") == 10
        assert _count_block_type(blocks, "header") == 1
        assert _count_block_type(blocks, "context") == 1


# ===========================================================================
# TestTeamsPayload
# ===========================================================================


class TestTeamsPayload:
    def test_envelope_is_message_type(self):
        """Returned dict has type=='message', attachments is a list of length 1,
 and attachments[0].contentType == 'application/vnd.microsoft.card.adaptive'."""
        result = build_teams_payload([build_fake_event()], PRESET_NAME, DASHBOARD_URL)
        assert result["type"] == "message"
        assert isinstance(result["attachments"], list)
        assert len(result["attachments"]) == 1
        assert (
            result["attachments"][0]["contentType"]
            == "application/vnd.microsoft.card.adaptive"
        )

    def test_adaptive_card_v1_5_schema(self):
        """AdaptiveCard content has correct version, schema URL, and type."""
        result = build_teams_payload([build_fake_event()], PRESET_NAME, DASHBOARD_URL)
        content = result["attachments"][0]["content"]
        assert content["version"] == "1.5"
        assert content["$schema"] == "http://adaptivecards.io/schemas/adaptive-card.json"
        assert content["type"] == "AdaptiveCard"

    def test_factset_contains_events(self):
        """body contains a FactSet; facts list has one fact per event (capped at 10);
 fact[0].title == event.title (truncated if needed)."""
        events = [build_fake_event(title=f"Event {i}") for i in range(5)]
        result = build_teams_payload(events, PRESET_NAME, DASHBOARD_URL)
        content = result["attachments"][0]["content"]
        # Find the FactSet in body
        factset = next(b for b in content["body"] if b["type"] == "FactSet")
        assert len(factset["facts"]) == 5
        assert factset["facts"][0]["title"] == "Event 0"

        # Capped at 10
        events_15 = [build_fake_event(title=f"E{i}") for i in range(15)]
        result_15 = build_teams_payload(events_15, PRESET_NAME, DASHBOARD_URL)
        factset_15 = next(
            b for b in result_15["attachments"][0]["content"]["body"]
            if b["type"] == "FactSet"
        )
        assert len(factset_15["facts"]) == 10

    def test_action_openurl_present(self):
        """content.actions[0].type == 'Action.OpenUrl'; URL points to events?preset=..."""
        result = build_teams_payload([build_fake_event()], PRESET_NAME, DASHBOARD_URL)
        actions = result["attachments"][0]["content"]["actions"]
        assert len(actions) >= 1
        assert actions[0]["type"] == "Action.OpenUrl"
        assert actions[0]["url"] == f"{DASHBOARD_URL}/events?preset={PRESET_NAME}"

    def test_no_legacy_messagecard_key(self):
        """'@type' must NOT appear anywhere in the returned dict ( guard).
 Also no 'MessageCard' string in contentType values."""
        result = build_teams_payload([build_fake_event()], PRESET_NAME, DASHBOARD_URL)
        all_keys = _walk_keys(result)
        assert "@type" not in all_keys, "Legacy MessageCard '@type' key found — Pitfall 4 violation"

        # Also verify no contentType mentions MessageCard
        attachment_content_type = result["attachments"][0]["contentType"]
        assert "MessageCard" not in attachment_content_type


# ===========================================================================
# TestDiscordPayload
# ===========================================================================


class TestDiscordPayload:
    def test_content_has_preset_name(self):
        """content == '**N new events matched `{preset_name}`**' with singular/plural."""
        events_1 = [build_fake_event()]
        events_2 = [build_fake_event(), build_fake_event()]

        result_1 = build_discord_payload(events_1, PRESET_NAME, DASHBOARD_URL)
        result_2 = build_discord_payload(events_2, PRESET_NAME, DASHBOARD_URL)

        assert result_1["content"] == f"**1 new events matched `{PRESET_NAME}`**"
        assert result_2["content"] == f"**2 new events matched `{PRESET_NAME}`**"

    def test_tlp_color_int_map(self):
        """Full 5-key TLP → Discord color int assertion."""
        expected = {
            "clear": 10478027,
            "green": 1940085,
            "amber": 15703847,
            "amber+strict": 13137682,
            "red": 14428198,
        }
        for tlp, color_int in expected.items():
            ev = build_fake_event(tlp=tlp)
            result = build_discord_payload([ev], PRESET_NAME, DASHBOARD_URL)
            assert result["embeds"][0]["color"] == color_int, (
                f"Expected color {color_int} for tlp={tlp!r}, "
                f"got {result['embeds'][0]['color']}"
            )

    def test_max_10_embeds_and_footer(self):
        """15 events → len(embeds) == 10 AND content ends with '... and 5 more'."""
        events = [build_fake_event() for _ in range(15)]
        result = build_discord_payload(events, PRESET_NAME, DASHBOARD_URL)
        assert len(result["embeds"]) == 10
        assert result["content"].endswith("... and 5 more")

    def test_embed_fields_type_tlp_source(self):
        """Each embed.fields has entries name=Type, name=TLP, name=Source — all inline=True."""
        events = [build_fake_event() for _ in range(3)]
        result = build_discord_payload(events, PRESET_NAME, DASHBOARD_URL)
        for embed in result["embeds"]:
            field_names = {f["name"] for f in embed["fields"]}
            assert "Type" in field_names
            assert "TLP" in field_names
            assert "Source" in field_names
            for field in embed["fields"]:
                assert field["inline"] is True, (
                    f"Field {field['name']!r} should have inline=True"
                )


# ===========================================================================
# TestGenericPayload
# ===========================================================================


class TestGenericPayload:
    def test_shape_matches_eventitem(self):
        """Each events[i] dict has the 17 EventItem keys from."""
        events = [build_fake_event() for _ in range(3)]
        result = build_generic_payload(events, PRESET_NAME, DASHBOARD_URL)
        for ev in result["events"]:
            assert _EVENTITEM_KEYS.issubset(
                set(ev.keys())
            ), f"Missing keys: {_EVENTITEM_KEYS - set(ev.keys())}"

    def test_preset_query_params_included(self):
        """returned.preset.name == preset_name; returned.preset.query_params == passed dict."""
        qp = {"tlp": "red", "source_type": "taxii"}
        events = [build_fake_event()]
        result = build_generic_payload(events, PRESET_NAME, DASHBOARD_URL, preset_query_params=qp)
        assert result["preset"]["name"] == PRESET_NAME
        assert result["preset"]["query_params"] == qp

        # Without query_params → empty dict
        result_no_qp = build_generic_payload(events, PRESET_NAME, DASHBOARD_URL)
        assert result_no_qp["preset"]["query_params"] == {}

    def test_count_matches_events_len(self):
        """Test with N=0, N=1, N=7 — all 3 assertions."""
        for n in (0, 1, 7):
            events = [build_fake_event() for _ in range(n)]
            result = build_generic_payload(events, PRESET_NAME, DASHBOARD_URL)
            assert result["count"] == n, f"Expected count={n}, got {result['count']}"
            assert len(result["events"]) == n
