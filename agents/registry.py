# agents/registry.py
from typing import Any

from agents.analytics_agent import AnalyticsAgent
from agents.comment_agent import CommentAgent
from agents.content_agent import ContentAgent
from agents.news_post_agent import NewsPostAgent
from agents.enrichment_agent import EnrichmentAgent
from agents.icp_agent import ICPAgent
from agents.kol_curator import KOLCuratorAgent
from agents.lead_magnet_builder import LeadMagnetBuilderAgent
from agents.outreach_sequencer import OutreachSequencerAgent
from agents.qa_guard import QAGuardAgent
from agents.scoring_agent import ScoringAgent
from agents.setup_agent import SetupAgent

AGENTS = {
    "setup_agent": SetupAgent,
    "icp_agent": ICPAgent,
    "enrichment_agent": EnrichmentAgent,
    "content_agent": ContentAgent,
    "comment_agent": CommentAgent,
    "news_post_agent": NewsPostAgent,
    "outreach_sequencer": OutreachSequencerAgent,
    "qa_guard": QAGuardAgent,
    "lead_magnet_builder": LeadMagnetBuilderAgent,
    "analytics_agent": AnalyticsAgent,
    "kol_curator": KOLCuratorAgent,
    "scoring_agent": ScoringAgent,
}


def get_agent(name: str, llm_client=None):
    from agents.llm_client import get_llm_client
    cls = AGENTS.get(name)
    if cls is None:
        raise ValueError(f"Unknown agent: {name}. Available: {list(AGENTS)}")
    if llm_client is not None:
        return cls(llm_client=llm_client)
    return cls()


async def run_agent(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    from agents.llm_client import get_llm_client
    payload = dict(payload)
    llm_provider = payload.pop("llm_provider", None)
    client = get_llm_client(provider=llm_provider) if llm_provider else None
    agent = get_agent(name, llm_client=client)
    return await agent.run(payload)
