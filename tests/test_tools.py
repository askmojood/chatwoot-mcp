"""Unit tests over a fake Chatwoot API (httpx.MockTransport): no Docker needed."""

import json
import time

import httpx
import pytest

from chatwoot_mcp import tools
from chatwoot_mcp.client import Chatwoot, ChatwootError

AGENTS = [{"id": 1, "name": "Claude Connector", "email": "admin@harbor-trading.example"},
          {"id": 3, "name": "Omar Siddiqui", "email": "omar.siddiqui@harbor-trading.example"}]
CONV = {"id": 1, "status": "open", "inbox_id": 1, "labels": ["quote"], "waiting_since": int(time.time()) - 9000,
        "last_activity_at": int(time.time()) - 9000, "last_non_activity_message": {"content": "Quote for 60 minibars?"},
        "meta": {"sender": {"name": "Noor Al-Saadi", "additional_attributes": {"company_name": "Bayt Interiors"}},
                 "assignee": None, "team": None}}


class Fake:
    def __init__(self):
        self.conv = json.loads(json.dumps(CONV))
        self.posts: list[tuple[str, dict]] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path.removeprefix("/api/v1/accounts/1/")
        if req.method == "POST":
            body = json.loads(req.content)
            self.posts.append((path, body))
            if "assignee_id" in body:
                self.conv["meta"]["assignee"] = next(a for a in AGENTS if a["id"] == body["assignee_id"])
            if "team_id" in body:
                self.conv["meta"]["team"] = {"name": "sales"}
            return httpx.Response(200, json={"id": 9})
        routes = {
            "inboxes": {"payload": [{"id": 1, "name": "Website chat"}]},
            "agents": AGENTS,
            "teams": [{"id": 1, "name": "sales"}, {"id": 2, "name": "service"}],
            "labels": {"payload": [{"title": "quote"}, {"title": "urgent"}]},
            "conversations": {"data": {"payload": [self.conv]}},
            "conversations/1": self.conv,
            "conversations/search": {"payload": [{"id": 1}] if req.url.params.get("q") == "minibar" else []},
            "conversations/1/messages": {"payload": [
                {"message_type": 0, "private": False, "created_at": 1, "content": "Quote for 60 minibars?", "sender": {"name": "Noor Al-Saadi"}},
                {"message_type": 2, "private": False, "created_at": 2, "content": "Assigned to …"}]},
        }
        if path in routes:
            return httpx.Response(200, json=routes[path])
        if path == "forbidden":
            return httpx.Response(401, json={"error": "You are not authorized to do this action"})
        return httpx.Response(404)


@pytest.fixture
def fake():
    return Fake()


def api(fake: Fake) -> Chatwoot:
    return Chatwoot("http://cw.test", "token", 1, transport=httpx.MockTransport(fake))


def test_needs_a_token(monkeypatch):
    monkeypatch.delenv("CHATWOOT_TOKEN", raising=False)
    with pytest.raises(ChatwootError):
        Chatwoot("http://cw.test", "")


def test_errors_carry_chatwoots_message(fake):
    with pytest.raises(ChatwootError, match="not authorized"):
        api(fake).get("forbidden")


def test_conversation_reads_contact_company_and_wait(fake):
    c = tools.conversation_of(CONV, {1: "Website chat"}, "http://cw.test", 1)
    assert (c.contact, c.company, c.inbox, c.assignee) == ("Noor Al-Saadi", "Bayt Interiors", "Website chat", None)
    assert c.waiting.startswith("2 h")
    assert tools.conversation_of(dict(CONV, status="resolved"), {}, "x", 1).waiting is None


def test_activity_lines_are_not_messages(fake):
    d = tools.get_conversation(api(fake), 1)
    assert [m.who for m in d.messages] == ["Noor Al-Saadi"]
    assert tools.get_conversation(api(fake), 99).problem


def test_search_reads_messages(fake):
    assert [c.id for c in tools.find_conversations(api(fake), query="minibar").conversations] == [1]
    assert tools.find_conversations(api(fake), query="helmets").total == 0


def test_needs_attention(fake):
    n = tools.needs_attention(api(fake))
    assert [c.id for c in n.unassigned] == [c.id for c in n.waiting_longest] == [1] and n.urgent == []


def test_note_changes_nothing_without_a_code(fake):
    c = tools.add_private_note(api(fake), 1, "Quote by Wednesday.")
    assert not c.done and c.confirmation and "won't see" in c.summary
    assert fake.posts == []


def test_note_with_the_code_is_private_and_marked(fake):
    a = api(fake)
    code = tools.add_private_note(a, 1, "Quote by Wednesday.").confirmation
    assert tools.add_private_note(a, 1, "Quote by Wednesday.", confirmation=code).done
    (path, body), = fake.posts
    assert path == "conversations/1/messages" and body["private"] is True and tools.NOTE in body["content"]
    assert not tools.add_private_note(a, 1, "Quote by Wednesday.", confirmation=code).done  # used once


def test_handover_previews_then_assigns_team_first(fake):
    a = api(fake)
    p = tools.update_conversation(a, 1, assignee="Omar", team="Sales")
    assert not p.done and "Omar Siddiqui" in p.summary and "Sales team" in p.summary and fake.posts == []
    d = tools.update_conversation(a, 1, assignee="Omar", team="Sales", confirmation=p.confirmation)
    assert d.done and (d.conversation.assignee, d.conversation.team) == ("Omar Siddiqui", "Sales")
    assert [b for _p, b in fake.posts] == [{"team_id": 1}, {"assignee_id": 3}]


def test_a_code_only_fits_its_own_request(fake):
    a = api(fake)
    code = tools.update_conversation(a, 1, assignee="Omar").confirmation
    assert not tools.update_conversation(a, 1, assignee="Omar", status="resolved", confirmation=code).done
    assert not tools.add_private_note(a, 1, "x", confirmation=code).done
    assert fake.posts == []


def test_the_token_user_is_never_an_assignee_and_labels_must_exist(fake):
    assert "no agent" in tools.update_conversation(api(fake), 1, assignee="Claude").problem
    assert "No such label" in tools.update_conversation(api(fake), 1, add_labels=["vip"]).problem
    assert "Nothing to change" in tools.update_conversation(api(fake), 1, add_labels=["quote"]).problem


def test_an_expired_code_is_refused(fake, monkeypatch):
    a = api(fake)
    code = tools.update_conversation(a, 1, status="pending").confirmation
    monkeypatch.setattr(tools, "CONFIRM_TTL_S", -1)
    assert not tools.update_conversation(a, 1, status="pending", confirmation=code).done
    assert fake.posts == []
