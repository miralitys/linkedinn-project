# app/models.py
import json
from datetime import datetime
from enum import Enum as PyEnum
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator


class JsonAsText(TypeDecorator):
    """Stores list/dict as JSON string for SQLite; returns list/dict on read."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, (list, dict)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value
        return value


class Base(DeclarativeBase):
    pass


class PersonStatus(str, PyEnum):
    NEW = "New"
    CONNECTED = "Connected"
    ENGAGED = "Engaged"
    WARM = "Warm"
    DM_SENT = "DM_Sent"
    REPLIED = "Replied"
    CALL_BOOKED = "Call_Booked"
    WON = "Won"
    LOST = "Lost"


class TouchType(str, PyEnum):
    LIKE = "like"
    COMMENT = "comment"
    DM = "dm"
    POST = "post"
    OTHER = "other"


class TouchDirection(str, PyEnum):
    OUTBOUND = "outbound"
    INBOUND = "inbound"


class TouchChannel(str, PyEnum):
    LINKEDIN = "linkedin"
    OTHER = "other"


class DraftType(str, PyEnum):
    POST = "post"
    COMMENT = "comment"
    DM = "dm"


class DraftStatus(str, PyEnum):
    DRAFT = "draft"
    QA_PENDING = "qa_pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class UserRole(str, PyEnum):
    USER = "user"
    ADMIN = "admin"


class UserApprovalStatus(str, PyEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class SubscriptionStatus(str, PyEnum):
    FREE = "free"
    TRIAL = "trial"
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


# --------------- Core entities ---------------


class User(Base):
    """Пользователь системы: регистрация, роли, подписка."""
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(256), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)  # bcrypt hash
    role: Mapped[str] = mapped_column(String(16), default=UserRole.USER.value, nullable=False)
    approval_status: Mapped[str] = mapped_column(String(16), default=UserApprovalStatus.APPROVED.value, nullable=False)
    subscription_status: Mapped[str] = mapped_column(String(32), default=SubscriptionStatus.FREE.value, nullable=False)
    subscription_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    plan_name: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # starter, pro, enterprise, tester, admin
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)  # владелец (multi-tenant)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    website_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    linkedin_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    industry: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    geo: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    size_range: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tech_stack: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # json or text
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    people: Mapped[list["Person"]] = relationship("Person", back_populates="company")


class Segment(Base):
    __tablename__ = "segments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)  # владелец (multi-tenant)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    rules: Mapped[Optional[dict]] = mapped_column(JsonAsText, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    red_flags: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    include_examples: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    exclude_examples: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    people: Mapped[list["Person"]] = relationship("Person", back_populates="segment")


class Person(Base):
    __tablename__ = "people"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)  # владелец (multi-tenant)
    company_id: Mapped[Optional[int]] = mapped_column(ForeignKey("companies.id"), nullable=True)
    full_name: Mapped[str] = mapped_column(String(256), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    linkedin_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    feed_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    geo: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    segment_id: Mapped[Optional[int]] = mapped_column(ForeignKey("segments.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=PersonStatus.NEW.value)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    hook_points: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    red_flags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_kol: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_touch_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    company: Mapped[Optional["Company"]] = relationship("Company", back_populates="people")
    segment: Mapped[Optional["Segment"]] = relationship("Segment", back_populates="people")
    touches: Mapped[list["Touch"]] = relationship("Touch", back_populates="person", order_by="Touch.created_at", cascade="all, delete-orphan")
    posts: Mapped[list["ContactPost"]] = relationship("ContactPost", back_populates="person", order_by="ContactPost.posted_at", cascade="all, delete-orphan")


class KOL(Base):
    __tablename__ = "kol"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    full_name: Mapped[str] = mapped_column(String(256), nullable=False)
    linkedin_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    topic_tags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class Touch(Base):
    __tablename__ = "touches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)  # TouchType
    direction: Mapped[str] = mapped_column(String(16), nullable=False)  # TouchDirection
    channel: Mapped[str] = mapped_column(String(16), nullable=False)  # TouchChannel
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    person: Mapped["Person"] = relationship("Person", back_populates="touches")


class ContactPost(Base):
    """Пост контакта (LinkedIn и др.): привязка к person_id, данные вносятся вручную или из интеграции."""
    __tablename__ = "contact_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    post_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    posted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    likes_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    comments_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    views_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tags: Mapped[Optional[list]] = mapped_column(JsonAsText, nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reply_variants: Mapped[Optional[dict]] = mapped_column(JsonAsText, nullable=True)  # { short, medium, long } — сохранённые варианты ответа
    comment_written: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # пользователь отметил, что комментарий написан
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    person: Mapped["Person"] = relationship("Person", back_populates="posts")


class RedditPostStatus(str, PyEnum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    HIDDEN = "hidden"


class RedditPost(Base):
    """Пост из сабреддита: данные из r/{subreddit}, логика как у постов (просмотр, комментарий, удаление)."""
    __tablename__ = "reddit_posts"
    __table_args__ = (UniqueConstraint("subreddit", "reddit_id", "user_id", name="uq_reddit_posts_subreddit_reddit_id_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)  # владелец (multi-tenant)
    subreddit: Mapped[str] = mapped_column(String(128), nullable=False)
    reddit_id: Mapped[str] = mapped_column(String(64), nullable=False)  # id поста на Reddit (для дедупа)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    post_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    posted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    author: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)  # reddit username
    score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    num_comments: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    person_id: Mapped[Optional[int]] = mapped_column(ForeignKey("people.id"), nullable=True)  # от чьего лица комментировать
    reply_variants: Mapped[Optional[dict]] = mapped_column(JsonAsText, nullable=True)
    comment_written: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    relevance_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # релевантность 0-100
    relevance_flag: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)  # YES/NO
    relevance_reason: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)  # причина оценки
    status: Mapped[str] = mapped_column(String(32), default=RedditPostStatus.NEW.value, nullable=False)  # new, in_progress, done, hidden
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    person: Mapped[Optional["Person"]] = relationship("Person", backref="reddit_posts")


class SavedSubreddit(Base):
    """Сохранённый сабреддит: список всегда отображается в UI."""
    __tablename__ = "saved_subreddits"
    __table_args__ = (UniqueConstraint("name", "user_id", name="uq_saved_subreddits_name_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)  # владелец (multi-tenant)
    name: Mapped[str] = mapped_column(String(128), nullable=False)  # имя без r/
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class NewsItem(Base):
    """Новость из RSS: хранится в БД для скоринга и постоянного доступа."""
    __tablename__ = "news_items"
    __table_args__ = (UniqueConstraint("link", name="uq_news_items_link"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    link: Mapped[str] = mapped_column(String(2048), nullable=False)
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    published: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    published_iso: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # исходная строка для API
    source: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    relevance_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    relevance_flag: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    relevance_reason: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SalesAvatar(Base):
    __tablename__ = "sales_avatar"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)  # владелец (multi-tenant)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    positioning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tone_guidelines: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    do_say: Mapped[Optional[list]] = mapped_column(JsonAsText, nullable=True)
    dont_say: Mapped[Optional[list]] = mapped_column(JsonAsText, nullable=True)
    examples_good: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    examples_bad: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Offer(Base):
    __tablename__ = "offers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)  # владелец (multi-tenant)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    target_segment_id: Mapped[Optional[int]] = mapped_column(ForeignKey("segments.id"), nullable=True)
    promise: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    proof_points: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # json or text
    objections: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cta_style: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class LeadMagnet(Base):
    __tablename__ = "lead_magnets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)  # владелец (multi-tenant)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    format: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # pdf/doc/checklist/template
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    outline: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    variants: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class KnowledgeBase(Base):
    __tablename__ = "knowledge_base"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tags: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)  # comma-separated
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Draft(Base):
    __tablename__ = "drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)  # владелец (multi-tenant)
    type: Mapped[str] = mapped_column(String(32), nullable=False)  # DraftType
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_agent: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    person_id: Mapped[Optional[int]] = mapped_column(ForeignKey("people.id"), nullable=True)
    kol_id: Mapped[Optional[int]] = mapped_column(ForeignKey("kol.id"), nullable=True)
    meta: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # CTA, question, etc.
    qa_result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=DraftStatus.DRAFT.value)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Usage(Base):
    """Учёт генераций (комментарии/посты) по пользователю и месяцу."""
    __tablename__ = "usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    year_month: Mapped[str] = mapped_column(String(7), nullable=False)  # YYYY-MM
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False)  # comment, post, etc.
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
