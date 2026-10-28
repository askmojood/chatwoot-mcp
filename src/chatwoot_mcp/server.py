"""Chatwoot MCP server (Mojood Connect demo): ask about the customer inbox in plain words, and hand over, label or
resolve conversations and leave private notes, with a confirmation step.

Run:  uv run --env-file .env chatwoot-mcp          → http://127.0.0.1:8004/mcp (Streamable HTTP)
      uv run --env-file .env chatwoot-mcp --stdio  → for Claude Desktop's config file

Settings (environment, written to .env by scripts/up.sh):
  CHATWOOT_URL      the Chatwoot instance (default http://127.0.0.1:3010)
  CHATWOOT_ACCOUNT  the account id (default 1)
  CHATWOOT_TOKEN    a user's API access token; the server acts as that user
  CHATWOOT_SAMPLE   "1" (default) says in every session that the data is SAMPLE
  CHATWOOT_MCP_PORT default 8004
"""

import logging
import os
import sys
from typing import Annotated, Literal

import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import Field

from chatwoot_mcp import tools
from chatwoot_mcp.client import Chatwoot

SAMPLE = os.environ.get("CHATWOOT_SAMPLE", "1") != "0"
_api: Chatwoot | None = None


def api() -> Chatwoot:
    global _api
    if _api is None:
        _api = Chatwoot()
    return _api


INSTRUCTIONS = f"""\
Chatwoot customer inbox: conversations from website chat and email, the contacts and companies behind them, who
is waiting for a reply, and the agents and teams who handle them.
{"This is a demo with SAMPLE data for a made-up company, Harbor Trading. " if SAMPLE else ""}\
Answer only from these tools; never guess what a customer wrote or who owns a conversation. Conversations are
numbered (e.g. 1). add_private_note and update_conversation change real conversations. Call one without
`confirmation` first: it changes nothing and returns what it would do plus a code. Show the user that summary and
ask them to confirm. Only after they say yes, call again with the same arguments and the code. Never confirm on the
user's behalf. If a tool returns `problem`, nothing changed: tell the user why. Never send a message to a customer:
there is no tool for it."""

READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
CHANGE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)

server = MCPServer(
    name="chatwoot-mcp",
    title="Chatwoot",
    description="The Chatwoot inbox: conversations, contacts, who's waiting, private notes and hand-overs.",
    instructions=INSTRUCTIONS,
    website_url="https://mojood.app/connect",
    version="0.1.0",
)


@server.tool(title="Find conversations", annotations=READ)
def find_conversations(
    status: Annotated[Literal["open", "pending", "resolved", "all"], Field(description="which conversations")] = "open",
    query: Annotated[str | None, Field(description='words from the messages, or a contact or company name')] = None,
    label: Annotated[str | None, Field(description='e.g. "quote"')] = None,
    assignee: Annotated[str | None, Field(description="an agent's name")] = None,
) -> tools.Conversations:
    """List conversations, filtered by status, words, label or agent. Each comes with its contact, company, inbox,
    assignee, team, labels and how long the customer has waited for a reply."""
    return tools.find_conversations(api(), status, query, label, assignee)


@server.tool(title="Read a conversation", annotations=READ)
def get_conversation(conversation_id: Annotated[int, Field(description="e.g. 1")]) -> tools.Detail:
    """One conversation with every message in order: who wrote it, when, and whether it was a private note."""
    return tools.get_conversation(api(), conversation_id)


@server.tool(title="A contact or company", annotations=READ)
def contact_overview(
    name: Annotated[str, Field(description='a person ("Noor Al-Saadi"), an email or a company ("Al Noor Hotels")')],
) -> tools.Contact:
    """A contact or a company: who they are and all their conversations. If the name matches people at several
    companies, returns them as candidates: ask which."""
    return tools.contact_overview(api(), name)


@server.tool(title="What needs attention", annotations=READ)
def needs_attention() -> tools.Attention:
    """Open conversations no agent owns, customers waiting for a reply (longest first), and urgent ones."""
    return tools.needs_attention(api())


@server.tool(title="Add a private note", annotations=CHANGE)
def add_private_note(
    conversation_id: Annotated[int, Field(description="e.g. 1")],
    text: Annotated[str, Field(description="the note, for agents only; the customer never sees it")],
    confirmation: Annotated[str | None, Field(description="leave empty first; pass the code only after the user confirms")] = None,
) -> tools.Change:
    """Add a private note to a conversation. The first call changes nothing and returns a summary and a
    confirmation code; the note is added only on a second call with the code, after the user has said yes."""
    return tools.add_private_note(api(), conversation_id, text, confirmation)


@server.tool(title="Update a conversation", annotations=CHANGE)
def update_conversation(
    conversation_id: Annotated[int, Field(description="e.g. 1")],
    assignee: Annotated[str | None, Field(description="an agent's name, to hand it over")] = None,
    team: Annotated[str | None, Field(description='a team, e.g. "Sales"')] = None,
    status: Annotated[Literal["open", "pending", "resolved"] | None, Field(description="new status")] = None,
    add_labels: Annotated[list[str] | None, Field(description='labels to add, e.g. ["quote"]')] = None,
    confirmation: Annotated[str | None, Field(description="leave empty first; pass the code only after the user confirms")] = None,
) -> tools.Change:
    """Hand a conversation to an agent or team, add labels, or change its status. The first call changes nothing
    and returns a summary and a confirmation code; the change happens only on a second call with the code, after
    the user has said yes."""
    return tools.update_conversation(api(), conversation_id, assignee, team, status, add_labels, confirmation)


def app():
    security = TransportSecuritySettings(
        allowed_hosts=["127.0.0.1:*", "localhost:*"],
        allowed_origins=["http://127.0.0.1:*", "http://localhost:*"],
    )
    # Stateful sessions: a confirmation code must reach the same server process that issued it.
    return server.streamable_http_app(json_response=True, transport_security=security)


def main() -> None:
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per Chatwoot call is noise in a client's log
    if "--stdio" in sys.argv:
        server.run("stdio")
        return
    uvicorn.run(app(), host="127.0.0.1", port=int(os.environ.get("CHATWOOT_MCP_PORT", "8004")), log_level="info",
                timeout_graceful_shutdown=5)
