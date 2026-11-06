"""Owned conversation pointers; historical answers never become current evidence."""

import re
from fastapi import HTTPException
from sqlalchemy import select
from copilot.models import Conversation, ConversationTurn


def context(session, user, question, conversation_id=None, incident_id=None):
    if conversation_id:
        conversation = session.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.tenant == user.tenant,
                Conversation.actor == user.actor,
            )
        )
        if not conversation:
            raise HTTPException(404, "Conversation not found")
    else:
        conversation = Conversation(tenant=user.tenant, actor=user.actor)
        session.add(conversation)
        session.commit()
    turns = list(
        session.scalars(
            select(ConversationTurn)
            .where(ConversationTurn.conversation_id == conversation.id)
            .order_by(ConversationTurn.created_at.desc())
            .limit(5)
        )
    )
    if not incident_id and not re.search(r"\bINC-\d+\b|last week", question, re.I):
        if re.search(r"\b(it|that|same|these|them|those)\b", question, re.I):
            incident_id = next((t.incident_id for t in turns if t.incident_id), None)
    return conversation.id, incident_id


def remember(session, conversation_id, question, incident_id=None, run_id=None):
    session.add(
        ConversationTurn(
            conversation_id=conversation_id, question=question, incident_id=incident_id, run_id=run_id
        )
    )
    session.commit()
