from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from copilot.db import Base


def uid() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    tenant: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(40))
    body: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    visibility: Mapped[str] = mapped_column(String(30), default="internal")


class EmbeddingCache(Base):
    __tablename__ = "embedding_cache"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant: Mapped[str] = mapped_column(String(80), index=True)
    model: Mapped[str] = mapped_column(String(100))
    dimensions: Mapped[int] = mapped_column(Integer)
    vector: Mapped[list] = mapped_column(JSON)


class DocumentAccess(Base):
    __tablename__ = "document_access"
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), primary_key=True)
    allowed_roles: Mapped[list] = mapped_column(JSON, default=list)


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(100), primary_key=True, default=uid)
    tenant: Mapped[str] = mapped_column(String(80), index=True)
    actor: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ConversationTurn(Base):
    __tablename__ = "conversation_turns"
    id: Mapped[str] = mapped_column(String(100), primary_key=True, default=uid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    question: Mapped[str] = mapped_column(Text)
    incident_id: Mapped[str | None] = mapped_column(String(100))
    run_id: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OperationMetric(Base):
    __tablename__ = "operation_metrics"
    id: Mapped[str] = mapped_column(String(100), primary_key=True, default=uid)
    tenant: Mapped[str] = mapped_column(String(80), index=True)
    actor: Mapped[str] = mapped_column(String(100))
    operation: Mapped[str] = mapped_column(String(80))
    data: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    tenant: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(200))
    account_manager: Mapped[str | None] = mapped_column(String(200))


class Subscription(Base):
    __tablename__ = "subscriptions"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), unique=True)
    tier: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(40))


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"))
    description: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(40))


class Incident(Base):
    __tablename__ = "incidents"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    tenant: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(300))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    report_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    workaround_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    policy_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    workaround_approved: Mapped[bool]


class Impact(Base):
    __tablename__ = "impacts"
    __table_args__ = (UniqueConstraint("incident_id", "customer_id"),)
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"))
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"))
    evidence_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    certainty: Mapped[str] = mapped_column(String(30))
    failed_logins: Mapped[int] = mapped_column(Integer)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(100), primary_key=True, default=uid)
    tenant: Mapped[str] = mapped_column(String(80), index=True)
    actor: Mapped[str] = mapped_column(String(100))
    question: Mapped[str] = mapped_column(Text)
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Proposal(Base):
    __tablename__ = "proposals"
    id: Mapped[str] = mapped_column(String(100), primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    tenant: Mapped[str] = mapped_column(String(80), index=True)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"))
    status: Mapped[str] = mapped_column(String(30), default="pending")
    payload: Mapped[dict] = mapped_column(JSON)
    digest: Mapped[str] = mapped_column(String(64))
    evidence_digest: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str | None] = mapped_column(String(100))


class Ticket(Base):
    __tablename__ = "tickets"
    __table_args__ = (UniqueConstraint("tenant", "incident_id", "customer_id", name="uq_followup"),)
    id: Mapped[str] = mapped_column(String(100), primary_key=True, default=uid)
    tenant: Mapped[str] = mapped_column(String(80), index=True)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"))
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"))
    proposal_id: Mapped[str] = mapped_column(ForeignKey("proposals.id"))
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    assigned_to: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(100), primary_key=True, default=uid)
    tenant: Mapped[str] = mapped_column(String(80), index=True)
    actor: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(80))
    target_id: Mapped[str] = mapped_column(String(100))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
