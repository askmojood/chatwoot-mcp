"""Fill an empty local Chatwoot with the customer inbox of Harbor Trading, a made-up Gulf supplier (SAMPLE data).

Agents, teams, inboxes, labels, contacts and conversations go in through Chatwoot's own API, the customers'
messages as incoming messages on API-channel inboxes, the way an integration would deliver them. Chatwoot's API
can't set past times, so the seeder also writes docker/backdate.json (hours ago for each message), which
scripts/reset.sh applies inside the container: the inbox then has customers waiting for hours, an unassigned
quote request and resolved history, whatever day it is seeded. Run on an empty Chatwoot only (scripts/reset.sh).
"""

import json
from pathlib import Path

from chatwoot_mcp.client import Chatwoot

INBOXES = ["Website chat", "Email"]
LABELS = [("quote", "#D9A62E"), ("delivery", "#296282"), ("billing", "#7A590C"), ("urgent", "#B42318")]
# name, team, role
AGENTS = [("Aisha Rahman", "Sales"), ("Omar Siddiqui", "Sales"), ("Karim Nasser", "Service"), ("Lina Farah", "Service")]
TEAMS = ["Sales", "Service"]
# name, email, company, city
CONTACTS = [
    ("Rashid Al-Mutairi", "rashid@gulf-build.example", "Gulf Build Contracting", "Khobar"),
    ("Mona Farouk", "mona@alnoor-hotels.example", "Al Noor Hotels", "Dammam"),
    ("Sami Haddad", "sami@alnoor-hotels.example", "Al Noor Hotels", "Dammam"),
    ("Fatima Zaidi", "fatima@desertrose-catering.example", "Desert Rose Catering", "Khobar"),
    ("James Whitfield", "james@coastal-marine.example", "Coastal Marine Services", "Jubail"),
    ("Elena Petrova", "elena@redsea-fitout.example", "Red Sea Fit-Out", "Jeddah"),
    ("Noor Al-Saadi", "noor@bayt-interiors.example", "Bayt Interiors", "Riyadh"),
    ("Yusuf Demir", "yusuf.demir@mail.example", None, "Dammam"),
]

# contact, inbox, status, assignee, team, labels, messages
# Each message: (who, hours ago, text) with who = "c" customer, "a" the assignee, "n" the assignee's private note.
CONVERSATIONS = [
    ("Noor Al-Saadi", "Website chat", "open", None, None, ["quote"], [
        ("c", 2.5, "Hello, do you supply hotel minibars? We need a quote for 60 units, 40 litre, for a boutique hotel in Riyadh."),
        ("c", 2.4, "Delivery would be mid-December. Our client approves budgets on Thursday."),
    ]),
    ("James Whitfield", "Website chat", "open", None, None, [], [
        ("c", 5, "Do you have 200 A4 stainless M16×80 hex bolts in stock? It's for a hull job next week."),
    ]),
    ("Rashid Al-Mutairi", "Website chat", "open", "Omar Siddiqui", "Sales", ["quote", "urgent"], [
        ("c", 3.2, "We need 500 white safety helmets with chin straps at the Khobar site by Sunday."),
        ("a", 3.0, "Hi Rashid, checking stock with the warehouse now."),
        ("c", 1.1, "Any update? The site manager needs an answer before the 3 pm meeting."),
    ]),
    ("Fatima Zaidi", "Website chat", "open", "Karim Nasser", "Service", ["delivery"], [
        ("c", 9, "The conveyor dishwasher you installed on Monday stops after two minutes with error E14."),
        ("a", 8.5, "Sorry about that, Fatima. E14 is the rinse pump sensor; I'm booking the manufacturer's technician."),
        ("n", 8.4, "Technician can come Thursday morning, waiting for their confirmation."),
        ("c", 0.8, "We have a 600-cover event on Friday. Is Thursday confirmed?"),
    ]),
    ("Elena Petrova", "Email", "open", "Aisha Rahman", "Sales", ["quote"], [
        ("c", 0.4, "Could you send samples of the grey felt acoustic panels to our Jeddah office? We order 300 m² next week."),
    ]),
    ("Mona Farouk", "Email", "pending", "Aisha Rahman", "Sales", ["quote"], [
        ("c", 30, "Can you match last year's price for 300 bath towels, 600 gsm?"),
        ("a", 26, "Yes, the same price holds until 30 November. Shall I raise the order?"),
    ]),
    ("Sami Haddad", "Email", "pending", "Lina Farah", "Service", ["billing"], [
        ("c", 50, "Invoice HT-INV-2290 shows the old unit price for bath towels."),
        ("a", 20, "A corrected invoice will reach you tomorrow morning."),
    ]),
    ("Yusuf Demir", "Website chat", "resolved", "Karim Nasser", "Service", [], [
        ("c", 75, "Is your Dammam showroom open on Friday?"),
        ("a", 74.8, "Friday 4 pm to 10 pm. Welcome!"),
    ]),
    ("Rashid Al-Mutairi", "Email", "resolved", "Omar Siddiqui", "Sales", ["delivery"], [
        ("c", 200, "Please send the delivery note for last week's scaffolding clamps."),
        ("a", 198, "Attached. Thanks, Rashid."),
    ]),
]


def seed(api: Chatwoot, backdate_file: Path) -> dict:
    if api.get("conversations", status="all")["data"]["meta"]["all_count"]:
        raise SystemExit("Chatwoot already has conversations: seed an empty one (scripts/reset.sh)")
    inbox = {n: api.post("inboxes", {"name": n, "channel": {"type": "api"}})["id"] for n in INBOXES}
    for title, colour in LABELS:
        api.post("labels", {"title": title, "color": colour, "show_on_sidebar": True})
    agents = {}
    for name, _team in AGENTS:
        email = name.lower().replace(" ", ".") + "@harbor-trading.example"
        agents[name] = api.post("agents", {"name": name, "email": email, "role": "agent"})["id"]
    # The token's user (the demo admin) works every inbox too.
    me = next(a["id"] for a in api.get("agents") if a["email"] == "admin@harbor-trading.example")
    for i in inbox.values():
        api.patch("inbox_members", {"inbox_id": i, "user_ids": [me, *agents.values()]})
    teams = {}
    for t in TEAMS:
        teams[t] = api.post("teams", {"name": t})["id"]
        api.post(f"teams/{teams[t]}/team_members", {"user_ids": [agents[n] for n, team in AGENTS if team == t]})
    contacts = {}
    for name, email, company, city in CONTACTS:
        attrs = {"city": city, **({"company_name": company} if company else {})}
        contacts[name] = api.post("contacts", {"name": name, "email": email, "additional_attributes": attrs})["payload"]["contact"]["id"]

    backdate = []
    for who, box, status, assignee, team, labels, messages in CONVERSATIONS:
        ci = api.post(f"contacts/{contacts[who]}/contact_inboxes", {"inbox_id": inbox[box]})
        conv = api.post("conversations", {"source_id": ci["source_id"], "inbox_id": inbox[box],
                                          "contact_id": contacts[who], "status": "open"})
        ids = []
        for kind, _h, text in messages:
            m = api.post(f"conversations/{conv['id']}/messages", {
                "content": text, "message_type": "incoming" if kind == "c" else "outgoing", "private": kind == "n"})
            ids.append(m["id"])
        if assignee:
            api.post(f"conversations/{conv['id']}/assignments", {"assignee_id": agents[assignee]})
        if team:
            api.post(f"conversations/{conv['id']}/assignments", {"team_id": teams[team]})
        if labels:
            api.post(f"conversations/{conv['id']}/labels", {"labels": labels})
        if status != "open":
            api.post(f"conversations/{conv['id']}/toggle_status", {"status": status})
        backdate.append({"conversation": conv["id"], "messages": ids, "hours": [h for _k, h, _t in messages],
                         "senders": [agents[assignee] if k != "c" and assignee else None for k, _h, _t in messages]})
    backdate_file.write_text(json.dumps(backdate))
    return {"inboxes": len(inbox), "agents": len(agents), "teams": len(teams), "contacts": len(contacts),
            "conversations": len(CONVERSATIONS)}


def main() -> None:
    print(seed(Chatwoot(), Path(__file__).resolve().parents[2] / "docker" / "backdate.json"))
