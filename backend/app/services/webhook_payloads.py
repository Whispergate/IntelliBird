"""Webhook payload builders — HOOK-03, HOOK-04, HOOK-05, HOOK-06.

Pure functions. No I/O, no DB, no HTTP. 4 destination types:
  - Slack Block Kit (D-14..D-16)
  - Teams Power Automate AdaptiveCard v1.5 (D-17..D-19) — legacy O365 BANNED
  - Discord embeds (D-20..D-22)
  - Generic JSON matching EventItem schema (D-23..D-25)

Every builder accepts the same (events, preset_name, dashboard_url) contract
so the dispatcher (07-03) and test-send (07-04) can route polymorphically.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# D-15 — Slack TLP emoji shortcodes
_TLP_SLACK_EMOJI: dict[str, str] = {
    "clear": ":white_circle:",
    "green": ":large_green_circle:",
    "amber": ":large_yellow_circle:",
    "amber+strict": ":large_blue_circle:",
    "red": ":red_circle:",
}

# D-21 — Discord TLP color (decimal int)
_TLP_DISCORD_COLOR: dict[str, int] = {
    "clear": 10478027,        # #9FE1CB
    "green": 1940085,         # #1D9E75
    "amber": 15703847,        # #EF9F27
    "amber+strict": 13137682, # #C87912
    "red": 14428198,          # #DC2626
}

_MAX_EVENTS_DIGEST = 10  # D-10, D-22


def _plural(n: int, singular: str = "event", plural: str | None = None) -> str:
    """Return '1 event' vs 'N events' (plural='events' by default)."""
    word = plural or singular + "s"
    return f"{n} {singular if n == 1 else word}"


def _truncate(s: str | None, n: int) -> str:
    if s is None:
        return ""
    if len(s) <= n:
        return s
    return s[: n - 3] + "..."


# ---------------------------------------------------------------- Slack --
def build_slack_payload(
    events: list[dict],
    preset_name: str,
    dashboard_url: str,
    preset_query_params: dict | None = None,
) -> dict[str, Any]:
    """Slack Block Kit digest (D-14..D-16). D-14 verbatim header copy.

    Block structure per D-14:
      1 header + (1 section + 1 divider) * min(N, 10) + 1 context = 2 + 2*N blocks
    """
    n = len(events)
    # VERBATIM: D-14 header "N new events matched <preset>"
    header_text = f"{n} new events matched {preset_name}"
    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": header_text}}
    ]
    for ev in events[:_MAX_EVENTS_DIGEST]:
        tlp_emoji = _TLP_SLACK_EMOJI.get(ev.get("tlp") or "clear", ":white_circle:")
        title = _truncate(ev.get("title") or "Untitled", 200)  # D-16
        stix_type = ev.get("stix_type") or ""
        source_name = ev.get("source_name") or "unknown"
        observed_at = ev.get("observed_at") or ""
        section_text = (
            f"*{title}*\n"
            f"`{stix_type}` {tlp_emoji} · {source_name} · {observed_at}\n"
            f"<{dashboard_url}/events?event={ev.get('id')}|Open in IntelliBird>"
        )
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": section_text},
        })
        blocks.append({"type": "divider"})
    iso_now = datetime.now(timezone.utc).isoformat()
    blocks.append({
        "type": "context",
        "elements": [{
            "type": "mrkdwn",
            "text": (
                f"<{dashboard_url}/events?preset={preset_name}|View all matches> "
                f"· {iso_now}"
            ),
        }],
    })
    return {"blocks": blocks}


# ---------------------------------------------------------------- Teams --
def build_teams_payload(
    events: list[dict],
    preset_name: str,
    dashboard_url: str,
    preset_query_params: dict | None = None,
) -> dict[str, Any]:
    """Teams Power Automate workflow webhook + AdaptiveCard v1.5 (D-17..D-19).

    Pitfall 4: legacy O365 Connector format is BANNED (Microsoft EOL — D-19).
    Envelope MUST be {type:'message', attachments:[...]} for Power Automate.
    """
    n = len(events)
    header_text = f"{n} new events matched {preset_name}"
    facts = []
    for ev in events[:_MAX_EVENTS_DIGEST]:
        title = _truncate(ev.get("title") or "Untitled", 150)
        stix_type = ev.get("stix_type") or ""
        tlp = ev.get("tlp") or "clear"
        source_name = ev.get("source_name") or "unknown"
        facts.append({
            "title": title,
            "value": f"{stix_type} · {tlp} · {source_name}",
        })
    return {
        "type": "message",  # Pitfall 4: Power Automate envelope (AdaptiveCard, not legacy O365)
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "type": "AdaptiveCard",
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "version": "1.5",
                "body": [
                    {
                        "type": "TextBlock",
                        "size": "Large",
                        "weight": "Bolder",
                        "text": header_text,
                        "wrap": True,
                    },
                    {"type": "FactSet", "facts": facts},
                ],
                "actions": [{
                    "type": "Action.OpenUrl",
                    "title": "View all matches",
                    "url": f"{dashboard_url}/events?preset={preset_name}",
                }],
            },
        }],
    }


# ---------------------------------------------------------------- Discord -
def build_discord_payload(
    events: list[dict],
    preset_name: str,
    dashboard_url: str,
    preset_query_params: dict | None = None,
) -> dict[str, Any]:
    """Discord embeds digest (D-20..D-22). Max 10 embeds; footer on overflow.

    D-22 verbatim overflow string: '... and {N-10} more'
    """
    n = len(events)
    content = f"**{n} new events matched `{preset_name}`**"
    if n > _MAX_EVENTS_DIGEST:
        # VERBATIM: D-22 discord fallback '... and {N-10} more'
        content += f" ... and {n - _MAX_EVENTS_DIGEST} more"
    embeds: list[dict] = []
    for ev in events[:_MAX_EVENTS_DIGEST]:
        desc = _truncate(ev.get("description"), 2048)
        title = _truncate(ev.get("title") or "Untitled", 256)
        stix_type = ev.get("stix_type") or ""
        tlp = ev.get("tlp") or "clear"
        source_name = ev.get("source_name") or "unknown"
        embeds.append({
            "title": title,
            "description": desc,
            "color": _TLP_DISCORD_COLOR.get(tlp, _TLP_DISCORD_COLOR["clear"]),
            "url": f"{dashboard_url}/events?event={ev.get('id')}",
            "fields": [
                {"name": "Type", "value": stix_type, "inline": True},
                {"name": "TLP", "value": tlp, "inline": True},
                {"name": "Source", "value": source_name, "inline": True},
            ],
            "timestamp": ev.get("observed_at"),  # ISO 8601
        })
    return {"content": content, "embeds": embeds}


# ---------------------------------------------------------------- Generic -
def build_generic_payload(
    events: list[dict],
    preset_name: str,
    dashboard_url: str,
    preset_query_params: dict | None = None,
) -> dict[str, Any]:
    """Generic JSON POST (D-23..D-25). Shape is stable — operator integrations
    depend on this. Event shape mirrors Phase 4 EventItem."""
    return {
        "preset": {
            "name": preset_name,
            "query_params": preset_query_params or {},
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(events),
        # Events passed through unchanged — caller already serialised to dict.
        "events": events,
    }


# ---------------------------------------------------------------- dispatch
_BUILDERS = {
    "slack": build_slack_payload,
    "teams": build_teams_payload,
    "discord": build_discord_payload,
    "generic": build_generic_payload,
}


def build_payload_for_type(
    destination_type: str,
    events: list[dict],
    preset_name: str,
    dashboard_url: str,
    preset_query_params: dict | None = None,
) -> dict[str, Any]:
    """Polymorphic dispatch — used by dispatcher (07-03) and test-send (07-04).

    Raises ValueError on unknown destination_type.
    """
    builder = _BUILDERS.get(destination_type)
    if builder is None:
        raise ValueError(f"unknown destination_type: {destination_type!r}")
    return builder(events, preset_name, dashboard_url, preset_query_params)


# Alias expected by objective: build_digest_payload(destination_type, preset_name, events, dashboard_url)
def build_digest_payload(
    destination_type: str,
    preset_name: str,
    events: list[dict],
    dashboard_url: str,
    preset_query_params: dict | None = None,
) -> dict[str, Any]:
    """Single entry point alias for build_payload_for_type with reordered args.

    Matches the objective signature:
        build_digest_payload(destination_type, preset_name, events, dashboard_url) -> dict
    """
    return build_payload_for_type(
        destination_type=destination_type,
        events=events,
        preset_name=preset_name,
        dashboard_url=dashboard_url,
        preset_query_params=preset_query_params,
    )
