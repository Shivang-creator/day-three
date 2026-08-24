"""Builds the Day Three writer LlmAgent (PLAN §4.9): a read/draft-only
toolset over a ReadOnlyStoreView, run via ADK's Runner + InMemorySessionService.

Verified against the installed `google-adk==2.7.1` (never from memory, per
Pit Crew doctrine): this version's `LlmAgent.output_schema` docstring says
plainly "The ADK supports using output_schema and tools together" — so
agent/reader.py (below) uses an LlmAgent with output_schema directly rather
than needing the genai-fallback path PLAN §4.9 anticipated for an older ADK
that forbade the combination.
"""
from __future__ import annotations

import os

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

from agent import tools as agent_tools

APP_NAME = "day_three"

WRITER_INSTRUCTION = (
    "You draft short, warm, SMS-length follow-up messages for new mothers in "
    "a postnatal follow-up programme, in English or Hindi. You have four "
    "tools: read_case to see a case's history, read_rule to quote the exact "
    "clinical rule behind an escalation (always quote it verbatim when one "
    "applies — never invent a citation), draft_message for any routine or "
    "known intent (prefer it whenever the intent has a template — it is "
    "reviewed text), and translate for the rare freely composed line that "
    "needs to move between English and Hindi. You cannot write anything back "
    "to the system — your only output is the message text itself."
)


def build_writer(store_view, pack, *, model: str | None = None) -> LlmAgent:
    """`store_view` must be a ReadOnlyStoreView; `pack` a loaded
    core.rulepack.RulePack. Neither is ever exposed to the model as a tool
    parameter — agent/tools.py closes over both when building the four
    callables handed to `tools=`."""
    model = model or os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
    read_case, read_rule, translate, draft_message = agent_tools.make_tools(store_view, pack)
    return LlmAgent(
        name="day_three_writer",
        model=model,
        instruction=WRITER_INSTRUCTION,
        tools=[read_case, read_rule, translate, draft_message],
    )


def runner_for(agent: LlmAgent) -> tuple[Runner, InMemorySessionService]:
    """A fresh InMemorySessionService per runner — Quiet Mode / replay never
    needs session state to survive past one render() call (PLAN §10:
    replay runs happen in scratch namespaces and are meant to be thrown
    away), so there is no session persistence to reason about here."""
    session_service = InMemorySessionService()
    runner = Runner(app_name=APP_NAME, agent=agent, session_service=session_service)
    return runner, session_service
