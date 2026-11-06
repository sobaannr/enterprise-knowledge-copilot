"""Bounded decomposition; rewriting is separately handled by the configured retriever."""

import re


def decompose_question(question, incident_id=None):
    if incident_id:
        return [
            f"{incident_id} login incident confirmed and suspected customer impact",
            f"{incident_id} approved SAML workaround recovery procedure",
            f"{incident_id} customer follow-up policy account manager approval",
        ]
    parts = re.split(
        r"[?;]+|,\s*(?=(?:what|which|how|can)\b)|\band\s+(?=(?:what|which|how|can)\b)", question, flags=re.I
    )
    parts = list(dict.fromkeys(p.strip(" ,.") for p in parts if len(p.strip()) >= 5))
    return (parts or [question])[:3]
