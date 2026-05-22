"""
agent_tools.py
--------------
Custom MCP tools exposed to the Claude Agent SDK.

The agent decides when to call these tools while reasoning about
each backlink. We give it three tools:

    check_site_activity(domain, window_months)
        → was this site publishing recently?

    fetch_homepage_summary(domain)
        → grab homepage text snippet for niche inference

    finalize_backlink_decision(...)
        → structured-output tool the agent calls *once per domain*
          to record its verdict. We collect these results.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup
from claude_agent_sdk import tool, create_sdk_mcp_server

from site_activity import check_site_activity, USER_AGENT, _base_url


# In-memory store for the agent's structured verdicts.
# The agent calls finalize_backlink_decision once per domain it analyzes;
# we collect those calls keyed by domain.
_verdict_store: dict[str, dict[str, Any]] = {}


def reset_verdicts() -> None:
    _verdict_store.clear()


def get_verdicts() -> dict[str, dict[str, Any]]:
    return dict(_verdict_store)


# ── Tool 1: site activity ──────────────────────────────────────────────
@tool(
    "check_site_activity",
    (
        "Check whether a website is actively publishing content by inspecting "
        "its sitemap.xml, RSS feed, and falling back to scraping its blog page. "
        "Use this for every backlink domain to determine if the site is alive."
    ),
    {"domain": str, "window_months": int},
)
async def check_site_activity_tool(args: dict[str, Any]) -> dict[str, Any]:
    domain = args["domain"]
    window = int(args.get("window_months", 6))
    result = await check_site_activity(domain, window_months=window)
    d = result.to_dict()
    # Format as compact text for the agent to read
    summary = (
        f"Domain: {d['domain']}\n"
        f"Active: {d['is_active']}\n"
        f"Method: {d['method']}\n"
        f"Last post: {d['last_post_date'] or 'none found'}\n"
        f"Days since last post: {d['days_since_last_post']}\n"
        f"Posts in last {window}mo: {d['posts_in_window']}\n"
        f"Notes: {d['notes']}"
    )
    return {
        "content": [{"type": "text", "text": summary}],
        # Embed structured data the orchestrator can read back
        "_meta": {"activity": d},
    }


# ── Tool 2: homepage snippet (for niche inference) ─────────────────────
@tool(
    "fetch_homepage_summary",
    (
        "Fetch a short snippet of a domain's homepage (title, meta description, "
        "first few paragraphs) to infer its niche/topic. Use this when the CSV "
        "data alone doesn't make the site's industry clear."
    ),
    {"domain": str},
)
async def fetch_homepage_summary_tool(args: dict[str, Any]) -> dict[str, Any]:
    domain = args["domain"]
    base = _base_url(domain)
    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT}, timeout=10.0
    ) as client:
        try:
            r = await client.get(base, follow_redirects=True)
            if r.status_code != 200:
                return {
                    "content": [
                        {"type": "text", "text": f"HTTP {r.status_code} when fetching {base}"}
                    ]
                }
        except httpx.HTTPError as e:
            return {"content": [{"type": "text", "text": f"Fetch error: {e}"}]}

    soup = BeautifulSoup(r.text, "html.parser")
    title = (soup.title.string.strip() if soup.title and soup.title.string else "")[:200]
    meta_desc = ""
    md = soup.find("meta", attrs={"name": "description"}) or soup.find(
        "meta", attrs={"property": "og:description"}
    )
    if md and md.get("content"):
        meta_desc = md["content"].strip()[:300]

    # First few paragraphs
    paras: list[str] = []
    for p in soup.find_all(["p", "h1", "h2"], limit=20):
        text = p.get_text(" ", strip=True)
        if 30 <= len(text) <= 300:
            paras.append(text)
        if len(paras) >= 5:
            break
    body = " | ".join(paras)[:800]

    snippet = (
        f"URL: {base}\n"
        f"Title: {title}\n"
        f"Description: {meta_desc}\n"
        f"Content: {body}"
    )
    return {"content": [{"type": "text", "text": snippet}]}


# ── Tool 3: structured verdict sink ────────────────────────────────────
@tool(
    "finalize_backlink_decision",
    (
        "Record your final verdict for a single backlink domain. Call this "
        "EXACTLY ONCE per domain after you have gathered enough evidence. "
        "All fields are required."
    ),
    {
        "domain": str,
        "relevance_score": int,        # 0-100
        "recommendation": str,         # Strong | Good | Weak | Reject
        "reasoning": str,              # one-sentence justification
        "activity_factored": bool,     # did inactive site lower the score?
    },
)
async def finalize_backlink_decision_tool(args: dict[str, Any]) -> dict[str, Any]:
    domain = args["domain"].strip().lower()
    # Clamp score
    score = max(0, min(100, int(args.get("relevance_score", 50))))
    rec = args.get("recommendation", "Weak")
    if rec not in ("Strong", "Good", "Weak", "Reject"):
        # Map score to recommendation if invalid
        rec = "Strong" if score >= 80 else "Good" if score >= 60 else "Weak" if score >= 40 else "Reject"

    _verdict_store[domain] = {
        "domain": domain,
        "relevance_score": score,
        "recommendation": rec,
        "reasoning": args.get("reasoning", "")[:500],
        "activity_factored": bool(args.get("activity_factored", False)),
    }
    return {
        "content": [
            {"type": "text", "text": f"Recorded verdict for {domain}: {rec} ({score}/100)"}
        ]
    }


# ── Build the MCP server ───────────────────────────────────────────────
def build_linksift_mcp_server():
    return create_sdk_mcp_server(
        name="linksift-tools",
        version="1.0.0",
        tools=[
            check_site_activity_tool,
            fetch_homepage_summary_tool,
            finalize_backlink_decision_tool,
        ],
    )
