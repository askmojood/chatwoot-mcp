"""Against the local Chatwoot with the SAMPLE inbox (scripts/reset.sh). Skipped when it isn't running.

Run: uv run --env-file .env pytest tests/test_live.py
"""

import os

import httpx
import pytest

from chatwoot_mcp import tools
from chatwoot_mcp.client import Chatwoot


def _up() -> bool:
    try:
        return bool(os.environ.get("CHATWOOT_TOKEN")) and httpx.get(
            os.environ.get("CHATWOOT_URL", "http://127.0.0.1:3010") + "/api", timeout=3).status_code == 200
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(not _up(), reason="local Chatwoot not running (scripts/up.sh)")


@pytest.fixture(scope="module")
def api():
    return Chatwoot()


def test_the_seeded_inbox_needs_attention(api):
    n = tools.needs_attention(api)
    # Noor's conversation is unassigned until the demo hands it to Omar; James's stays unassigned.
    assert "James Whitfield" in {c.contact for c in n.unassigned}
    assert n.waiting_longest[0].contact == "James Whitfield" and n.urgent


def test_al_noor_hotels_has_two_people(api):
    c = tools.contact_overview(api, "Al Noor Hotels")
    assert c.company == "Al Noor Hotels" and len(c.conversations) == 2


def test_note_on_a_resolved_conversation(api):
    conv = tools.find_conversations(api, "resolved", query="showroom").conversations[0]
    p = tools.add_private_note(api, conv.id, "Live test note.")
    assert tools.add_private_note(api, conv.id, "Live test note.", confirmation=p.confirmation).done
    last = tools.get_conversation(api, conv.id).messages[-1]
    assert last.private and tools.NOTE in last.text
