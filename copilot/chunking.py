"""Search small child chunks, then supply a larger containing parent as context."""

CHILD_WORDS = 180
CHILD_OVERLAP = 35
PARENT_WORDS = 600
PARENT_STRIDE = PARENT_WORDS - CHILD_WORDS


def parent_metadata(doc, child_index):
    words = doc.body.split()
    child_start = child_index * (CHILD_WORDS - CHILD_OVERLAP)
    parent_index = child_start // PARENT_STRIDE
    start = parent_index * PARENT_STRIDE
    end = min(len(words), start + PARENT_WORDS)
    return {
        "parent_id": f"{doc.id}@{doc.revision}:p{parent_index}",
        "parent_excerpt": " ".join(words[start:end]),
        "parent_word_start": start,
        "parent_word_end": end,
        "child_word_start": child_start,
        "child_word_end": min(len(words), child_start + CHILD_WORDS),
    }


def expand_parents(hits, limit):
    parents = {}
    for hit in hits:
        key = hit["parent_id"]
        if key in parents:
            parents[key]["matched_child_ids"].append(hit["chunk_id"])
        elif len(parents) < limit:
            parents[key] = {
                **hit,
                "matched_excerpt": hit["excerpt"],
                "excerpt": hit["parent_excerpt"],
                "matched_child_ids": [hit["chunk_id"]],
            }
    return list(parents.values())
