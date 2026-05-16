"""Seed country / motivation / sophistication for known MITRE ATT&CK groups.

Safe to re-run — uses UPDATE WHERE mitre_group_id = :mitre_group_id.
Only updates rows that already exist (from seed_actors.py bootstrap).
Rows without a mitre_group_id match are silently skipped.

Usage: uv run python -m app.scripts.seed_actor_attributions
"""
from __future__ import annotations

import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("seed_actor_attributions")

# ---------------------------------------------------------------------------
# Static attribution map.
# Fields: mitre_group_id, country, motivation, sophistication
# motivation: espionage | financial | hacktivism | sabotage | multi
# sophistication: nation-state | advanced | intermediate | basic
# ---------------------------------------------------------------------------
ATTRIBUTIONS: list[dict[str, str]] = [
    # ---- China ----
    {"mitre_group_id": "G0006", "country": "China", "motivation": "espionage", "sophistication": "nation-state"},
    {"mitre_group_id": "G0045", "country": "China", "motivation": "espionage", "sophistication": "nation-state"},
    {"mitre_group_id": "G0096", "country": "China", "motivation": "multi", "sophistication": "nation-state"},
    {"mitre_group_id": "G0019", "country": "China", "motivation": "espionage", "sophistication": "advanced"},
    {"mitre_group_id": "G0004", "country": "China", "motivation": "espionage", "sophistication": "nation-state"},
    {"mitre_group_id": "G0065", "country": "China", "motivation": "espionage", "sophistication": "nation-state"},
    {"mitre_group_id": "G0027", "country": "China", "motivation": "espionage", "sophistication": "advanced"},
    {"mitre_group_id": "G0035", "country": "China", "motivation": "espionage", "sophistication": "advanced"},
    {"mitre_group_id": "G0098", "country": "China", "motivation": "espionage", "sophistication": "advanced"},
    {"mitre_group_id": "G0114", "country": "China", "motivation": "espionage", "sophistication": "advanced"},
    {"mitre_group_id": "G0023", "country": "China", "motivation": "espionage", "sophistication": "advanced"},
    {"mitre_group_id": "G0025", "country": "China", "motivation": "espionage", "sophistication": "advanced"},
    {"mitre_group_id": "G0026", "country": "China", "motivation": "espionage", "sophistication": "advanced"},
    {"mitre_group_id": "G0066", "country": "China", "motivation": "espionage", "sophistication": "advanced"},
    {"mitre_group_id": "G0143", "country": "China", "motivation": "espionage", "sophistication": "advanced"},
    # ---- India ----
    {"mitre_group_id": "G0040", "country": "India", "motivation": "espionage", "sophistication": "intermediate"},
    # ---- Russia ----
    {"mitre_group_id": "G0007", "country": "Russia", "motivation": "espionage", "sophistication": "nation-state"},
    {"mitre_group_id": "G0016", "country": "Russia", "motivation": "espionage", "sophistication": "nation-state"},
    {"mitre_group_id": "G0034", "country": "Russia", "motivation": "sabotage", "sophistication": "nation-state"},
    {"mitre_group_id": "G0010", "country": "Russia", "motivation": "espionage", "sophistication": "nation-state"},
    {"mitre_group_id": "G0074", "country": "Russia", "motivation": "espionage", "sophistication": "nation-state"},
    {"mitre_group_id": "G0080", "country": "Russia", "motivation": "financial", "sophistication": "advanced"},
    {"mitre_group_id": "G0100", "country": "Russia", "motivation": "espionage", "sophistication": "advanced"},
    {"mitre_group_id": "G0047", "country": "Russia", "motivation": "espionage", "sophistication": "intermediate"},
    {"mitre_group_id": "G0102", "country": "Russia", "motivation": "financial", "sophistication": "advanced"},
    {"mitre_group_id": "G0119", "country": "Russia", "motivation": "financial", "sophistication": "advanced"},
    {"mitre_group_id": "G0091", "country": "Russia", "motivation": "financial", "sophistication": "advanced"},
    # ---- North Korea ----
    {"mitre_group_id": "G0032", "country": "North Korea", "motivation": "financial", "sophistication": "nation-state"},
    {"mitre_group_id": "G0082", "country": "North Korea", "motivation": "financial", "sophistication": "nation-state"},
    {"mitre_group_id": "G0094", "country": "North Korea", "motivation": "espionage", "sophistication": "advanced"},
    {"mitre_group_id": "G0105", "country": "North Korea", "motivation": "espionage", "sophistication": "advanced"},
    {"mitre_group_id": "G0138", "country": "North Korea", "motivation": "financial", "sophistication": "advanced"},
    {"mitre_group_id": "G0067", "country": "North Korea", "motivation": "espionage", "sophistication": "advanced"},
    # ---- Iran ----
    {"mitre_group_id": "G0049", "country": "Iran", "motivation": "espionage", "sophistication": "nation-state"},
    {"mitre_group_id": "G0064", "country": "Iran", "motivation": "sabotage", "sophistication": "nation-state"},
    {"mitre_group_id": "G0069", "country": "Iran", "motivation": "espionage", "sophistication": "advanced"},
    {"mitre_group_id": "G0142", "country": "Iran", "motivation": "sabotage", "sophistication": "advanced"},
    {"mitre_group_id": "G0059", "country": "Iran", "motivation": "espionage", "sophistication": "advanced"},
    {"mitre_group_id": "G0003", "country": "Iran", "motivation": "espionage", "sophistication": "advanced"},
    {"mitre_group_id": "G0043", "country": "Iran", "motivation": "espionage", "sophistication": "intermediate"},
    {"mitre_group_id": "G0117", "country": "Iran", "motivation": "espionage", "sophistication": "advanced"},
    # ---- Financial / FIN groups ----
    {"mitre_group_id": "G0037", "country": "Unknown", "motivation": "financial", "sophistication": "advanced"},
    {"mitre_group_id": "G0046", "country": "Unknown", "motivation": "financial", "sophistication": "advanced"},
    {"mitre_group_id": "G0061", "country": "Unknown", "motivation": "financial", "sophistication": "advanced"},
    {"mitre_group_id": "G0085", "country": "Unknown", "motivation": "financial", "sophistication": "advanced"},
    {"mitre_group_id": "G0092", "country": "Unknown", "motivation": "financial", "sophistication": "advanced"},
    {"mitre_group_id": "G0084", "country": "Unknown", "motivation": "financial", "sophistication": "advanced"},
    # ---- Nigeria ----
    {"mitre_group_id": "G0083", "country": "Nigeria", "motivation": "financial", "sophistication": "intermediate"},
    # ---- Vietnam ----
    {"mitre_group_id": "G0050", "country": "Vietnam", "motivation": "espionage", "sophistication": "advanced"},
    # ---- Palestine ----
    {"mitre_group_id": "G0021", "country": "Palestine", "motivation": "espionage", "sophistication": "intermediate"},
    # ---- United States ----
    {"mitre_group_id": "G0015", "country": "United States", "motivation": "espionage", "sophistication": "nation-state"},
    # ---- Unknown / mixed ----
    {"mitre_group_id": "G0022", "country": "Unknown", "motivation": "hacktivism", "sophistication": "advanced"},
]


def main() -> None:
    from app.config import settings  # lazy import — avoids circular deps at module load

    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    # Convert asyncpg DSN → psycopg DSN for sync use (mirrors actor_writer.py)
    url = settings.DATABASE_URL.replace("+asyncpg", "")
    engine = create_engine(url, future=True)

    updated = 0
    with Session(engine) as session:
        for entry in ATTRIBUTIONS:
            result = session.execute(
                text("""
                    UPDATE threat_actors
                    SET country = :country,
                        motivation = :motivation,
                        sophistication = :sophistication
                    WHERE mitre_group_id = :mitre_group_id
                """),
                entry,
            )
            updated += result.rowcount
        session.commit()

    engine.dispose()
    logger.info("seed_actor_attributions: updated %d rows", updated)


if __name__ == "__main__":
    main()
