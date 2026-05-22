"""
agent.py
--------
Runs the Claude Agent SDK to analyze a batch of backlinks.

For each batch we:
  1. Build a prompt describing the target website + the candidate domains
  2. Let the agent call `check_site_activity` + `fetch_homepage_summary`
     as it sees fit
  3. Require the agent to call `finalize_backlink_decision` once per domain
  4. Read verdicts from the in-memory store, merge with the activity
     metadata we collected, and return the combined results

We also run a non-agent fast path: `check_site_activity` is called directly
for every domain *in parallel* before invoking the agent. This guarantees
fresh activity data and lets us pre-load it into the prompt — the agent
then doesn't need to re-fetch unless it wants to.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    ToolUseBlock,
    TextBlock,
)

from site_activity import check_site_activity, ActivityResult, USER_AGENT
import agent_tools


MODEL = "claude-sonnet-4-5"

import claude_agent_sdk as _sdk_pkg
_BUNDLED_CLI = Path(_sdk_pkg.__file__).parent / "_bundled" / "claude"

SYSTEM_PROMPT = """You are an expert SEO backlink analyst working inside an agentic pipeline.

Your job: for each backlink domain in the input, decide whether it is a worthwhile
backlink for the target website. You have access to these tools:

  - check_site_activity(domain, window_months): inspect sitemap/RSS/blog for recent posts
  - fetch_homepage_summary(domain): grab homepage title/description/snippet
  - finalize_backlink_decision(domain, relevance_score, recommendation, reasoning, activity_factored):
        record your final verdict — call this EXACTLY ONCE PER DOMAIN

For every domain you analyze, weigh THREE factors:

  1. TOPICAL RELEVANCE — does the site's niche match the target industry?
  2. GEOGRAPHIC RELEVANCE — does it serve the target geography?
  3. SITE ACTIVITY — is the site still publishing? An inactive site is a
     dead backlink even if topically perfect. Drop the score by at least
     20 points if activity check shows is_active=false. Set
     activity_factored=true when you do this.

Activity rules:
  - is_active=true  → no penalty
  - is_active=false → cap recommendation at "Weak" and reduce score by 20+

Scoring bands:
  80-100 = Strong  (relevant + active + good geo)
  60-79  = Good    (mostly relevant, active)
  40-59  = Weak    (tangential or inactive)
  0-39   = Reject  (irrelevant, dead, or spammy)

Workflow:
  - Activity data is PRE-LOADED for you in the prompt — you don't need to
    call check_site_activity again unless something looks suspicious.
  - Call fetch_homepage_summary only when the CSV data is too sparse to
    judge the niche (e.g. no category, no description, ambiguous domain).
  - Call finalize_backlink_decision exactly once per domain.
  - Be concise. Don't write a report — just make tool calls.
"""


def _build_user_prompt(
    batch: list[dict],
    activity_map: dict[str, dict],
    target_domain: str,
    industry: str,
    geography: str,
    window_months: int,
) -> str:
    lines = [
        f"TARGET WEBSITE: {target_domain}",
        f"INDUSTRY: {industry}",
        f"TARGET GEOGRAPHY: {geography}",
        f"ACTIVITY WINDOW: last {window_months} months",
        "",
        "CANDIDATE BACKLINKS (with pre-computed activity data):",
    ]
    for r in batch:
        d = r["domain"]
        a = activity_map.get(d, {})
        lines.append(
            json.dumps(
                {
                    "domain": d,
                    "dr": r.get("dr", 0),
                    "traffic": r.get("traffic", 0),
                    "spam_score": r.get("spam", 0),
                    "category": r.get("category", "") or "unknown",
                    "description": r.get("description", ""),
                    "country": r.get("country", ""),
                    "activity": {
                        "is_active": a.get("is_active", False),
                        "last_post_date": a.get("last_post_date"),
                        "days_since_last_post": a.get("days_since_last_post"),
                        "posts_in_window": a.get("posts_in_window", 0),
                        "method": a.get("method", "none"),
                    },
                }
            )
        )

    lines.append("")
    lines.append(
        f"Analyze all {len(batch)} domains. Call finalize_backlink_decision once per domain. "
        "Use fetch_homepage_summary only if niche is unclear from the data above."
    )
    return "\n".join(lines)


async def _gather_activity(
    domains: list[str], window_months: int, concurrency: int = 8
) -> AsyncIterator[tuple[str, dict]]:
    """Yield (domain, result) as each activity check completes — no waiting for all."""
    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT},
        timeout=8.0,
        limits=httpx.Limits(max_connections=20),
    ) as client:

        async def one(d: str) -> tuple[str, dict]:
            async with sem:
                try:
                    res: ActivityResult = await check_site_activity(
                        d, window_months=window_months, client=client
                    )
                    return d, res.to_dict()
                except Exception as e:  # noqa: BLE001
                    return d, {
                        "domain": d,
                        "is_active": False,
                        "method": "error",
                        "notes": f"Activity check failed: {e}",
                        "last_post_date": None,
                        "days_since_last_post": None,
                        "posts_in_window": 0,
                        "window_months": window_months,
                        "checked_urls": [],
                    }

        tasks = [asyncio.ensure_future(one(d)) for d in domains]
        for fut in asyncio.as_completed(tasks):
            yield await fut


async def analyze_batch_agentic(
    batch: list[dict],
    target_domain: str,
    industry: str,
    geography: str,
    window_months: int = 6,
) -> AsyncIterator[dict]:
    """
    Yields event dicts so the HTTP layer can stream progress:
      {"type":"activity_done", "domain":..., "data":...}
      {"type":"agent_tool", "tool":..., "domain":...}
      {"type":"agent_text", "text":...}
      {"type":"batch_done", "results":[...]}
    """
    # 1) Reset verdict store for this batch
    agent_tools.reset_verdicts()

    domains = [r["domain"] for r in batch]

    # 2) Stream activity checks — yield each result as it arrives
    yield {"type": "status", "msg": f"Checking site activity for {len(domains)} domains..."}
    activity_map: dict[str, dict] = {}
    async for domain, data in _gather_activity(domains, window_months):
        activity_map[domain] = data
        yield {"type": "activity_done", "domain": domain, "data": data}

    # 3) Build the agent prompt
    user_prompt = _build_user_prompt(
        batch, activity_map, target_domain, industry, geography, window_months
    )

    # 4) Configure the agent
    mcp_server = agent_tools.build_linksift_mcp_server()
    options = ClaudeAgentOptions(
        model=MODEL,
        system_prompt=SYSTEM_PROMPT,
        mcp_servers={"linksift": mcp_server},
        allowed_tools=[
            "mcp__linksift__check_site_activity",
            "mcp__linksift__fetch_homepage_summary",
            "mcp__linksift__finalize_backlink_decision",
        ],
        permission_mode="bypassPermissions",
        max_turns=max(8, len(batch) * 2 + 4),
        cli_path=_BUNDLED_CLI if _BUNDLED_CLI.exists() else None,
    )

    yield {"type": "status", "msg": f"Agent analyzing {len(batch)} backlinks..."}

    # 5) Run the agent
    async for message in query(prompt=user_prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, ToolUseBlock):
                    tool_name = block.name.split("__")[-1]
                    dom = (block.input or {}).get("domain", "")
                    yield {"type": "agent_tool", "tool": tool_name, "domain": dom}
                elif isinstance(block, TextBlock) and block.text.strip():
                    # Only emit non-trivial reasoning text
                    if len(block.text) > 8:
                        yield {"type": "agent_text", "text": block.text[:300]}
        elif isinstance(message, ResultMessage):
            yield {
                "type": "agent_done",
                "cost_usd": getattr(message, "total_cost_usd", None),
                "duration_ms": getattr(message, "duration_ms", None),
            }

    # 6) Merge verdicts with activity + original data
    verdicts = agent_tools.get_verdicts()
    results: list[dict] = []
    for r in batch:
        d = r["domain"].lower()
        v = verdicts.get(d)
        a = activity_map.get(r["domain"], {})

        if v:
            rel = v["relevance_score"]
            rec = v["recommendation"]
            reasoning = v["reasoning"]
        else:
            # Agent missed this domain — synthesize a fallback
            rel = 30 if not a.get("is_active") else 50
            rec = "Reject" if not a.get("is_active") else "Weak"
            reasoning = (
                "Agent did not return a verdict; auto-scored based on activity. "
                + (a.get("notes") or "")
            )[:500]

        composite = _compute_composite(
            r.get("dr", 0), r.get("traffic", 0), r.get("spam", 0), rel
        )

        results.append(
            {
                **r,
                "relevance_score": rel,
                "recommendation": rec,
                "reasoning": reasoning,
                "composite_score": composite,
                "activity": {
                    "is_active": a.get("is_active", False),
                    "last_post_date": a.get("last_post_date"),
                    "days_since_last_post": a.get("days_since_last_post"),
                    "posts_in_window": a.get("posts_in_window", 0),
                    "method": a.get("method", "none"),
                    "notes": a.get("notes", ""),
                },
            }
        )

    yield {"type": "batch_done", "results": results}


def _compute_composite(dr: float, traffic: float, spam: float, relevance: float) -> int:
    dr_s = min(dr / 100, 1) * 25
    traffic_s = min((max(traffic, 1) ** 0.5) / 1000, 1) * 20
    spam_s = (1 - spam / 100) * 15
    rel_s = (relevance / 100) * 40
    return round(dr_s + traffic_s + spam_s + rel_s)
