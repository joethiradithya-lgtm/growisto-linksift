# Migration from the Claude Code plugin

If you were using the previous version of this repo (the Claude Code plugin that produced a 5-tab Excel from the terminal), here's what changed and what to do.

## What's gone

- `.claude-plugin/` — plugin manifest, no longer needed
- `skills/linksift/` — the Skill that triggered on "score these backlinks"
- `scripts/run_linksift.py` — the CLI script that built the Excel
- `requires.json`

These were removed because the architecture is now a web app, not a Claude Code plugin.

## What's new

- **Browser UI** — upload CSV/Excel in the browser, see live results, sort/filter, export
- **Site activity detection** — every domain checked for recent blog posts; dead sites get penalized
- **Agentic scoring** — Claude Agent SDK loop with custom MCP tools (`check_site_activity`, `fetch_homepage_summary`, `finalize_backlink_decision`) instead of a deterministic Python scoring function
- **Live streaming** — verdicts appear as the agent works, not after a batch completes

## What's still the same

- Same 4 recommendation tiers (Strong / Good / Weak / Reject)
- Same composite scoring philosophy (DR + traffic + spam + relevance)
- Same input formats — Ahrefs, Semrush, Moz, and a generic Render-style schema all auto-detect via header aliases
- CSV export of results

## If you have the old plugin installed in Claude Code

```bash
claude plugins uninstall growisto-linksift
```

Then follow the [setup guide](SETUP.md) to run the new web app.

## If you want the old plugin's behavior back

The old code is preserved in git history. You can checkout the previous version:

```bash
git log --oneline                    # find the commit before the rewrite
git checkout <commit-hash> -- .       # restore that state in your working tree
```

Or browse the history on GitHub directly.

## Behavioral differences to know

| Aspect                | Old plugin                          | New web app                            |
| --------------------- | ----------------------------------- | -------------------------------------- |
| Trigger               | "score these backlinks" in Claude Code | Open browser, upload file              |
| Relevance scoring     | Deterministic keyword matching      | Claude agent (LLM-based)               |
| Reproducibility       | Same input → same scores            | Scores may vary slightly between runs  |
| Site activity         | Not checked                         | Checked (sitemap/RSS/scrape)           |
| Output                | 5-tab Excel file                    | Browser UI + single-tab CSV export     |
| API key needed        | No                                  | Yes (Anthropic API key)                |
| Cost per run          | Free                                | ~$0.01–$0.05 per 100 backlinks         |
| Offline use           | Yes                                 | No (needs internet for LLM + activity) |

If deterministic scoring matters to you (e.g. you need the same input to produce identical output for compliance), the old plugin in git history is the better fit.
