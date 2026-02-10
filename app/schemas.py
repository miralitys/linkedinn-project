# app/schemas.py
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# --------------- Setup ---------------
class SetupWizardInput(BaseModel):
    product: str
    icp_raw: str
    tone: str
    goals: str


class SetupSectionSave(BaseModel):
    section: str  # products | icp | tone | goals
    value: Any  # for products: list of {name, description}; for others: str


# --------------- Companies ---------------
class CompanyCreate(BaseModel):
    name: str
    website_url: Optional[str] = None
    linkedin_url: Optional[str] = None
    industry: Optional[str] = None
    geo: Optional[str] = None
    size_range: Optional[str] = None
    description: Optional[str] = None
    tech_stack: Optional[str] = None
    notes: Optional[str] = None


class CompanyUpdate(BaseModel):
    name: Optional[str] = None
    website_url: Optional[str] = None
    linkedin_url: Optional[str] = None
    industry: Optional[str] = None
    geo: Optional[str] = None
    size_range: Optional[str] = None
    description: Optional[str] = None
    tech_stack: Optional[str] = None
    notes: Optional[str] = None


class CompanyRead(BaseModel):
    id: int
    name: str
    website_url: Optional[str] = None
    linkedin_url: Optional[str] = None
    industry: Optional[str] = None
    geo: Optional[str] = None
    size_range: Optional[str] = None
    description: Optional[str] = None
    tech_stack: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# --------------- Segments ---------------
class SegmentCreate(BaseModel):
    name: str
    rules: Optional[dict] = None
    priority: int = 0
    red_flags: Optional[str] = None
    include_examples: Optional[str] = None
    exclude_examples: Optional[str] = None


class SegmentRead(BaseModel):
    id: int
    name: str
    rules: Optional[dict] = None
    priority: int
    red_flags: Optional[str] = None
    include_examples: Optional[str] = None
    exclude_examples: Optional[str] = None

    class Config:
        from_attributes = True


# --------------- People ---------------
class PersonCreate(BaseModel):
    company_id: Optional[int] = None
    full_name: str
    title: Optional[str] = None
    linkedin_url: Optional[str] = None
    feed_url: Optional[str] = None
    geo: Optional[str] = None
    segment_id: Optional[int] = None
    status: str = "New"
    priority: int = 0
    hook_points: Optional[list] = None
    red_flags: Optional[list] = None
    notes: Optional[str] = None
    is_kol: bool = False


class PersonUpdate(BaseModel):
    company_id: Optional[int] = None
    full_name: Optional[str] = None
    title: Optional[str] = None
    linkedin_url: Optional[str] = None
    feed_url: Optional[str] = None
    geo: Optional[str] = None
    segment_id: Optional[int] = None
    priority: Optional[int] = None
    hook_points: Optional[list] = None
    red_flags: Optional[list] = None
    notes: Optional[str] = None
    is_kol: Optional[bool] = None




class PersonStatusUpdate(BaseModel):
    status: str


class PersonRead(BaseModel):
    id: int
    company_id: Optional[int] = None
    full_name: str
    title: Optional[str] = None
    linkedin_url: Optional[str] = None
    feed_url: Optional[str] = None
    geo: Optional[str] = None
    segment_id: Optional[int] = None
    status: str
    priority: int
    hook_points: Optional[list] = None
    red_flags: Optional[list] = None
    notes: Optional[str] = None
    is_kol: bool = False
    last_touch_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# --------------- KOL ---------------
class KOLCreate(BaseModel):
    full_name: str
    linkedin_url: Optional[str] = None
    topic_tags: Optional[List[str]] = None
    priority: int = 0
    notes: Optional[str] = None


class KOLUpdate(BaseModel):
    full_name: Optional[str] = None
    linkedin_url: Optional[str] = None
    topic_tags: Optional[List[str]] = None
    priority: Optional[int] = None
    notes: Optional[str] = None


class KOLRead(BaseModel):
    id: int
    full_name: str
    linkedin_url: Optional[str] = None
    topic_tags: Optional[list] = None
    priority: int
    notes: Optional[str] = None
    last_seen_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# --------------- Contact posts (лента постов контактов) ---------------
class ContactPostCreate(BaseModel):
    person_id: int
    title: str
    content: Optional[str] = None
    post_url: Optional[str] = None
    posted_at: datetime
    likes_count: Optional[int] = None
    comments_count: Optional[int] = None
    views_count: Optional[int] = None
    tags: Optional[List[str]] = None


class ContactPostUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    post_url: Optional[str] = None
    posted_at: Optional[datetime] = None
    likes_count: Optional[int] = None
    comments_count: Optional[int] = None
    views_count: Optional[int] = None
    tags: Optional[List[str]] = None
    archived: Optional[bool] = None
    reply_variants: Optional[Dict[str, str]] = None  # { short, medium, long }
    comment_written: Optional[bool] = None


class ContactPostRead(BaseModel):
    id: int
    person_id: int
    person_name: Optional[str] = None
    title: str
    content: Optional[str] = None
    post_url: Optional[str] = None
    posted_at: datetime
    likes_count: Optional[int] = None
    comments_count: Optional[int] = None
    views_count: Optional[int] = None
    tags: Optional[list] = None
    archived: bool = False
    reply_variants: Optional[Dict[str, str]] = None
    comment_written: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


class PostParseFromUrlRequest(BaseModel):
    url: str
    person_id: Optional[int] = None


class PostParseFromUrlResponse(BaseModel):
    parsed: Optional[Dict[str, Any]] = None
    post: Optional[ContactPostRead] = None
    error: Optional[str] = None
    screenshot_base64: Optional[str] = None


# --------------- Reddit posts ---------------
class RedditPostCreate(BaseModel):
    subreddit: str
    reddit_id: str
    title: str
    content: Optional[str] = None
    post_url: Optional[str] = None
    posted_at: datetime
    author: Optional[str] = None
    score: Optional[int] = None
    num_comments: Optional[int] = None
    person_id: Optional[int] = None


class RedditPostUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    post_url: Optional[str] = None
    posted_at: Optional[datetime] = None
    score: Optional[int] = None
    num_comments: Optional[int] = None
    person_id: Optional[int] = None
    reply_variants: Optional[Dict[str, str]] = None
    comment_written: Optional[bool] = None
    status: Optional[str] = None  # new, in_progress, done, hidden


class SavedSubredditAdd(BaseModel):
    name: str


class RedditPostRead(BaseModel):
    id: int
    subreddit: str
    reddit_id: str
    title: str
    content: Optional[str] = None
    post_url: Optional[str] = None
    posted_at: datetime
    author: Optional[str] = None
    score: Optional[int] = None
    num_comments: Optional[int] = None
    person_id: Optional[int] = None
    person_name: Optional[str] = None
    reply_variants: Optional[Dict[str, str]] = None
    comment_written: bool = False
    relevance_score: Optional[int] = None
    relevance_flag: Optional[str] = None
    relevance_reason: Optional[str] = None
    status: str = "new"  # new, in_progress, done, hidden
    created_at: datetime

    class Config:
        from_attributes = True


# --------------- Touches ---------------
class TouchCreate(BaseModel):
    person_id: int
    type: str  # like/comment/dm/post/other
    direction: str = "outbound"
    channel: str = "linkedin"
    content: Optional[str] = None
    url: Optional[str] = None


class TouchRead(BaseModel):
    id: int
    person_id: int
    type: str
    direction: str
    channel: str
    content: Optional[str] = None
    url: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# --------------- Sales Avatar, Offers, Lead Magnets ---------------
class SalesAvatarRead(BaseModel):
    id: int
    name: str
    positioning: Optional[str] = None
    tone_guidelines: Optional[str] = None
    do_say: Optional[list] = None
    dont_say: Optional[list] = None
    examples_good: Optional[str] = None
    examples_bad: Optional[str] = None

    class Config:
        from_attributes = True


class OfferRead(BaseModel):
    id: int
    name: str
    target_segment_id: Optional[int] = None
    promise: Optional[str] = None
    proof_points: Optional[str] = None
    objections: Optional[str] = None
    cta_style: Optional[str] = None
    notes: Optional[str] = None

    class Config:
        from_attributes = True


class LeadMagnetRead(BaseModel):
    id: int
    title: str
    format: Optional[str] = None
    description: Optional[str] = None
    outline: Optional[str] = None
    variants: Optional[list] = None
    notes: Optional[str] = None

    class Config:
        from_attributes = True


# --------------- Agents ---------------
class AgentRunPayload(BaseModel):
    payload: Dict[str, Any] = Field(default_factory=dict)


class AgentRunResponse(BaseModel):
    agent_name: str
    result: Dict[str, Any]
    draft_id: Optional[int] = None


# --------------- Daily Queue ---------------
class DailyQueueResponse(BaseModel):
    comments: List[Dict[str, Any]]  # { kol_id, post_text, drafts }
    posts: List[Dict[str, Any]]    # { idea, draft }
    dm_queue: List[Dict[str, Any]]  # { person_id, draft, next_touch_date }


# --------------- Drafts ---------------
class DraftRead(BaseModel):
    id: int
    type: str
    content: str
    source_agent: Optional[str] = None
    person_id: Optional[int] = None
    kol_id: Optional[int] = None
    meta: Optional[dict] = None
    qa_result: Optional[dict] = None
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DraftQARequest(BaseModel):
    run_qa: bool = True


class QAResult(BaseModel):
    ok: bool
    risks: Dict[str, int]  # hallucination, tone_drift, spam_pattern, aggressiveness, policy_risk
    fixes: List[str]
    rewritten_text: Optional[str] = None


class DraftApproveRequest(BaseModel):
    approved: bool = True
    note: Optional[str] = None
