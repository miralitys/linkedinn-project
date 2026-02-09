# app/cli.py
"""Minimal CLI for LFAS: setup."""
import asyncio
import json
import os
import sys


def run_async(coro):
    return asyncio.run(coro)


async def cmd_setup(product: str = "", icp_raw: str = "", tone: str = "", goals: str = ""):
    from app.db import session_scope
    from app.models import LeadMagnet, Offer, SalesAvatar, Segment
    from agents.registry import run_agent

    if not product:
        product = os.environ.get("LFAS_PRODUCT", "Мой продукт")
    if not icp_raw:
        icp_raw = os.environ.get("LFAS_ICP", "CTO, малый и средний бизнес")
    if not tone:
        tone = os.environ.get("LFAS_TONE", "Профессиональный, дружелюбный")
    if not goals:
        goals = os.environ.get("LFAS_GOALS", "Лиды, нетворк")

    result = await run_agent("setup_agent", {"product": product, "icp_raw": icp_raw, "tone": tone, "goals": goals})
    data = result.get("data")
    if not data:
        print("Setup failed:", result.get("error", result.get("raw")))
        return 1

    async with session_scope() as session:
        av = data.get("sales_avatar") or {}
        avatar = SalesAvatar(
            name=av.get("name", "Default"),
            positioning=av.get("positioning"),
            tone_guidelines=av.get("tone_guidelines"),
            do_say=av.get("do_say"),
            dont_say=av.get("dont_say"),
            examples_good=av.get("examples_good"),
            examples_bad=av.get("examples_bad"),
        )
        session.add(avatar)
        await session.flush()
        for seg in data.get("segments") or []:
            s = Segment(name=seg.get("name", "Segment"), rules=seg.get("rules"), priority=seg.get("priority", 0), red_flags=seg.get("red_flags"), include_examples=seg.get("include_examples"), exclude_examples=seg.get("exclude_examples"))
            session.add(s)
        for off in data.get("offers") or []:
            o = Offer(name=off.get("name", "Offer"), promise=off.get("promise"), proof_points=off.get("proof_points"), objections=off.get("objections"), cta_style=off.get("cta_style"), notes=off.get("notes"))
            session.add(o)
        for lm in data.get("lead_magnets") or []:
            l = LeadMagnet(title=lm.get("title", "LM"), format=lm.get("format"), description=lm.get("description"), outline=lm.get("outline"), notes=lm.get("notes"))
            session.add(l)
    print("Setup OK. Sales Avatar + segments + offers + lead magnets created.")
    return 0


def main():
    argv = sys.argv[1:]
    if not argv:
        print("Usage: python -m app.cli setup")
        print("  setup: --product X --icp_raw Y --tone Z --goals W")
        return 0
    cmd = argv[0].lower()
    args = {}
    i = 1
    while i < len(argv):
        if argv[i].startswith("--") and i + 1 < len(argv):
            key = argv[i][2:].replace("-", "_")
            args[key] = argv[i + 1]
            i += 2
        else:
            i += 1

    if cmd == "setup":
        code = run_async(cmd_setup(args.get("product", ""), args.get("icp_raw", ""), args.get("tone", ""), args.get("goals", "")))
    else:
        print("Unknown command:", cmd)
        code = 1
    sys.exit(code)


if __name__ == "__main__":
    main()
