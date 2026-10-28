"""The six tools, as plain functions over a Chatwoot client (the MCP wiring is in server.py).

Four only read. The two that change something (add a private note, update a conversation) never act on the first
call: they return a preview and a one-time confirmation code, and act only when called again with that code and
the same request. Nothing here sends a message to a customer: a private note is for agents only.
"""

import secrets
import time
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from chatwoot_mcp.client import Chatwoot, ChatwootError

NOTE = "via Claude (Mojood Connect demo)"
CONFIRM_TTL_S = 10 * 60
STATUSES = ("open", "pending", "resolved")


def _when(ts: int | None) -> str | None:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d %H:%M") if ts else None


def _waited(ts: int | None) -> str | None:
    if not ts:
        return None
    mins = int((time.time() - ts) // 60)
    return f"{mins} min" if mins < 60 else f"{mins // 60} h {mins % 60:02d} min" if mins < 48 * 60 else f"{mins // 1440} days"


class Conversation(BaseModel):
    id: int
    status: str
    contact: str | None = None
    company: str | None = None
    inbox: str | None = None
    assignee: str | None = Field(None, description="the agent it's assigned to; empty when unassigned")
    team: str | None = None
    labels: list[str] = Field(default_factory=list)
    waiting: str | None = Field(None, description="how long the customer has waited for a reply; empty when they aren't waiting")
    last_message: str | None = None
    last_activity: str | None = None
    link: str | None = None


def _inboxes(api: Chatwoot) -> dict[int, str]:
    return {i["id"]: i["name"] for i in api.get("inboxes")["payload"]}


def conversation_of(c: dict, inboxes: dict[int, str], base: str, account: int) -> Conversation:
    m = c.get("meta") or {}
    sender = m.get("sender") or {}
    last = c.get("last_non_activity_message") or {}
    return Conversation(
        id=c["id"], status=c["status"], contact=sender.get("name"),
        company=(sender.get("additional_attributes") or {}).get("company_name"),
        inbox=inboxes.get(c.get("inbox_id")), assignee=(m.get("assignee") or {}).get("name"),
        team=((m.get("team") or {}).get("name") or "").title() or None, labels=c.get("labels") or [],
        waiting=_waited(c.get("waiting_since")) if c["status"] == "open" else None,
        last_message=(last.get("content") or "")[:160] or None, last_activity=_when(c.get("last_activity_at")),
        link=f"{base}/app/accounts/{account}/conversations/{c['id']}",
    )


def _all(api: Chatwoot, status: str = "all") -> list[dict]:
    out, page = [], 1
    while True:
        rows = api.get("conversations", status=status, page=page)["data"]["payload"]
        out += rows
        if len(rows) < 25:
            return out
        page += 1


def _one(api: Chatwoot, cid: int) -> dict | None:
    try:
        return api.get(f"conversations/{int(cid)}")
    except (ChatwootError, ValueError):
        return None


# ---------- read ----------

class Conversations(BaseModel):
    conversations: list[Conversation]
    total: int


def find_conversations(api: Chatwoot, status: str = "open", query: str | None = None, label: str | None = None,
                       assignee: str | None = None) -> Conversations:
    rows = _all(api, status if status in (*STATUSES, "all") else "open")
    ib = _inboxes(api)
    convs = [conversation_of(c, ib, api.url, api.account) for c in rows]
    if label:
        convs = [c for c in convs if label.lower() in c.labels]
    if assignee:
        convs = [c for c in convs if c.assignee and assignee.lower() in c.assignee.lower()]
    if query:
        # Chatwoot's search reads every message; names and companies are matched here too.
        q = query.lower()
        hit = {r["id"] for r in api.get("conversations/search", q=query)["payload"]}
        convs = [c for c in convs if c.id in hit or any(q in (v or "").lower() for v in (c.contact, c.company))]
    return Conversations(conversations=convs[:25], total=len(convs))


class Message(BaseModel):
    who: str
    when: str | None
    private: bool = Field(description="a private note, never shown to the customer")
    text: str


class Detail(BaseModel):
    conversation: Conversation | None = None
    messages: list[Message] = Field(default_factory=list)
    problem: str | None = None


def get_conversation(api: Chatwoot, conversation_id: int) -> Detail:
    c = _one(api, conversation_id)
    if not c:
        return Detail(problem=f"No conversation has the id {conversation_id}.")
    msgs = [Message(who=(m.get("sender") or {}).get("name") or "Customer", when=_when(m.get("created_at")),
                    private=bool(m.get("private")), text=(m.get("content") or "")[:800])
            for m in api.get(f"conversations/{c['id']}/messages")["payload"] if m["message_type"] in (0, 1)]
    return Detail(conversation=conversation_of(c, _inboxes(api), api.url, api.account), messages=msgs)


class Contact(BaseModel):
    name: str | None = None
    email: str | None = None
    company: str | None = None
    city: str | None = None
    conversations: list[Conversation] = Field(default_factory=list)
    candidates: list[str] = Field(default_factory=list, description="when the search matched several: ask which")
    problem: str | None = None


def contact_overview(api: Chatwoot, name: str) -> Contact:
    rows = api.get("contacts/search", q=name)["payload"]
    by_company = [r for r in api.get("contacts")["payload"]
                  if name.lower() in ((r.get("additional_attributes") or {}).get("company_name") or "").lower()]
    found = {r["id"]: r for r in rows + by_company}
    if not found:
        return Contact(problem=f'No contact or company matches "{name}".')
    people = list(found.values())
    companies = {(p.get("additional_attributes") or {}).get("company_name") for p in people}
    if len(people) > 1 and len(companies) > 1:
        return Contact(candidates=[f"{p['name']} ({(p.get('additional_attributes') or {}).get('company_name') or 'no company'})" for p in people])
    first = people[0]
    attrs = first.get("additional_attributes") or {}
    ib = _inboxes(api)
    convs = [conversation_of(c, ib, api.url, api.account) for p in people
             for c in api.get(f"contacts/{p['id']}/conversations")["payload"]]
    return Contact(name=", ".join(p["name"] for p in people), email=first.get("email") if len(people) == 1 else None,
                   company=attrs.get("company_name"), city=attrs.get("city"),
                   conversations=sorted(convs, key=lambda c: (c.status != "open", c.id)))


class Attention(BaseModel):
    unassigned: list[Conversation] = Field(description="open conversations no agent owns")
    waiting_longest: list[Conversation] = Field(description="open conversations where the customer waits for a reply, longest first")
    urgent: list[Conversation] = Field(description="open conversations labelled urgent")


def needs_attention(api: Chatwoot) -> Attention:
    rows = _all(api, "open")
    ib = _inboxes(api)
    waiting = sorted([c for c in rows if c.get("waiting_since")], key=lambda c: c["waiting_since"])
    convs = {c["id"]: conversation_of(c, ib, api.url, api.account) for c in rows}
    return Attention(unassigned=[v for v in convs.values() if not v.assignee],
                     waiting_longest=[convs[c["id"]] for c in waiting],
                     urgent=[v for v in convs.values() if "urgent" in v.labels])


# ---------- change (preview, then confirm) ----------

class Change(BaseModel):
    done: bool = Field(description="false: nothing has changed yet; true: Chatwoot has made the change")
    summary: str
    confirmation: str | None = Field(None, description="when done is false: the code to pass back, only after the user says yes")
    expires_in_minutes: int | None = None
    conversation: Conversation | None = None
    problem: str | None = Field(None, description="why it can't be done; nothing was changed")


_pending: dict[str, tuple[float, tuple]] = {}


def _ask(request: tuple, summary: str, conv: Conversation) -> Change:
    now = time.monotonic()
    for k in [k for k, (t, _) in _pending.items() if now - t > CONFIRM_TTL_S]:
        del _pending[k]
    code = secrets.token_hex(3)
    _pending[code] = (now, request)
    return Change(done=False, summary=summary + " Nothing has changed yet: ask the user to confirm.",
                  confirmation=code, expires_in_minutes=CONFIRM_TTL_S // 60, conversation=conv)


def _confirmed(code: str, request: tuple) -> bool:
    held = _pending.get(code.strip())
    if not held or time.monotonic() - held[0] > CONFIRM_TTL_S or held[1] != request:
        return False
    del _pending[code.strip()]
    return True


def _expired(summary: str, conv: Conversation) -> Change:
    return Change(done=False, summary=summary, conversation=conv,
                  problem="That confirmation code doesn't match this request or has expired. Ask again.")


def _label(c: Conversation) -> str:
    return f"conversation {c.id} with {c.contact}" + (f" ({c.company})" if c.company else "")


def add_private_note(api: Chatwoot, conversation_id: int, text: str, confirmation: str | None = None) -> Change:
    c = _one(api, conversation_id)
    if not c:
        return Change(done=False, summary="", problem=f"No conversation has the id {conversation_id}.")
    if not text.strip():
        return Change(done=False, summary="", problem="The note is empty.")
    conv = conversation_of(c, _inboxes(api), api.url, api.account)
    request = ("note", c["id"], text.strip())
    summary = f'Add a private note to {_label(conv)}, which the customer won\'t see: "{text.strip()}"'
    if not confirmation:
        return _ask(request, summary, conv)
    if not _confirmed(confirmation, request):
        return _expired(summary, conv)
    api.post(f"conversations/{c['id']}/messages", {"content": f"{text.strip()}\n\n({NOTE})", "message_type": "outgoing",
                                                   "private": True})
    return Change(done=True, summary=f"Done: the note is on conversation {c['id']}.", conversation=conv)


def _find(rows: list[dict], name: str, kind: str) -> tuple[dict | None, str | None]:
    hits = [r for r in rows if name.strip().lower() in r["name"].lower()]
    exact = [r for r in hits if r["name"].lower() == name.strip().lower()]
    if len(exact) == 1 or len(hits) == 1:
        return (exact or hits)[0], None
    names = ", ".join(r["name"] for r in hits) or f"no {kind}"
    return None, f'"{name}" matches {names}. Ask which {kind}.'


def update_conversation(api: Chatwoot, conversation_id: int, assignee: str | None = None, team: str | None = None,
                        status: str | None = None, add_labels: list[str] | None = None,
                        confirmation: str | None = None) -> Change:
    c = _one(api, conversation_id)
    if not c:
        return Change(done=False, summary="", problem=f"No conversation has the id {conversation_id}.")
    conv = conversation_of(c, _inboxes(api), api.url, api.account)
    plan, parts = [], []
    if team:
        t, why = _find(api.get("teams"), team, "team")
        if not t:
            return Change(done=False, summary="", conversation=conv, problem=why)
        plan.append(("team", t["id"]))
        parts.append(f"put it in the {t['name'].title()} team")
    if assignee:
        agents = [a for a in api.get("agents") if a["email"] != "admin@harbor-trading.example"]
        a, why = _find(agents, assignee, "agent")
        if not a:
            return Change(done=False, summary="", conversation=conv, problem=why)
        plan.append(("assignee", a["id"]))
        parts.append(f"assign it to {a['name']}")
    if add_labels:
        known = {lb["title"] for lb in api.get("labels")["payload"]}
        bad = [lb for lb in add_labels if lb.lower() not in known]
        if bad:
            return Change(done=False, summary="", conversation=conv, problem=f"No such label: {', '.join(bad)}. Labels: {', '.join(sorted(known))}.")
        new = sorted({lb.lower() for lb in add_labels} - set(conv.labels))
        if new:
            plan.append(("labels", tuple(sorted(set(conv.labels) | set(new)))))
            parts.append("label it " + ", ".join(new))
    if status:
        if status not in STATUSES:
            return Change(done=False, summary="", conversation=conv, problem=f"Status must be one of: {', '.join(STATUSES)}.")
        plan.append(("status", status))
        parts.append(f"mark it {status}")
    if not parts:
        return Change(done=False, summary="", conversation=conv, problem="Nothing to change: give an assignee, a team, labels or a status.")
    request = ("update", c["id"], tuple(plan))
    summary = f"On {_label(conv)}: " + ", ".join(parts) + "."
    if not confirmation:
        return _ask(request, summary, conv)
    if not _confirmed(confirmation, request):
        return _expired(summary, conv)
    for kind, value in plan:  # team before assignee: assigning a team alone can clear the agent
        if kind == "team":
            api.post(f"conversations/{c['id']}/assignments", {"team_id": value})
        elif kind == "assignee":
            api.post(f"conversations/{c['id']}/assignments", {"assignee_id": value})
        elif kind == "labels":
            api.post(f"conversations/{c['id']}/labels", {"labels": list(value)})
        elif kind == "status":
            api.post(f"conversations/{c['id']}/toggle_status", {"status": value})
    fresh = conversation_of(api.get(f"conversations/{c['id']}"), _inboxes(api), api.url, api.account)
    return Change(done=True, summary=f"Done: conversation {c['id']} updated.", conversation=fresh)
