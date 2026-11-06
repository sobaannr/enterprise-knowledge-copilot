"""Local BM25 baseline or OpenSearch BM25+dense retrieval with reciprocal rank fusion."""

import math
import re
from collections import Counter
from functools import lru_cache

from sqlalchemy import select

from copilot.models import Document, DocumentAccess
from copilot.chunking import parent_metadata, expand_parents
from copilot.security import injection_signals
from copilot.query import decompose_question


def tokens(text):
    return re.findall(r"[a-z0-9]+", text.lower())


def chunk_text(text, size=180, overlap=35):
    if size < 1 or overlap < 0 or overlap >= size:
        raise ValueError("Require 0 <= overlap < size")
    words = text.split()
    return [" ".join(words[i : i + size]) for i in range(0, len(words), size - overlap)]


def rewrite(query):
    """Bounded, explicit domain expansion, not an LLM query-rewriting claim."""
    terms = tokens(query)
    if any(word in terms for word in ["login", "signin", "sso"]):
        return query + " SAML identity authentication incident metadata workaround"
    return query


@lru_cache(maxsize=2)
def embedder(model):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model)


@lru_cache(maxsize=2)
def reranker(model):
    from sentence_transformers import CrossEncoder

    return CrossEncoder(model)


def visible_documents(session, tenant, user=None, kinds=None, document_ids=None, min_revision=None):
    query = select(Document).where(Document.tenant == tenant)
    if kinds:
        query = query.where(Document.kind.in_(kinds))
    if document_ids:
        query = query.where(Document.id.in_(document_ids))
    if min_revision is not None:
        query = query.where(Document.revision >= min_revision)
    documents = list(session.scalars(query))
    roles = {
        row.document_id: row.allowed_roles
        for row in session.scalars(
            select(DocumentAccess).where(DocumentAccess.document_id.in_([d.id for d in documents]))
        )
    }
    role = user.role if user else "analyst"
    return [
        d
        for d in documents
        if not injection_signals(d.body)
        and (role in roles[d.id] if d.id in roles else d.visibility == "internal")
    ]


def local_search(documents, query, limit):
    chunks = [
        (d, i, text, Counter(tokens(text))) for d in documents for i, text in enumerate(chunk_text(d.body))
    ]
    if not chunks:
        return []
    avg_length = sum(sum(c.values()) for _, _, _, c in chunks) / len(chunks)
    query_terms = set(tokens(query))
    frequency = {t: sum(t in c for _, _, _, c in chunks) for t in query_terms}
    ranked = []
    for doc, index, text, counts in chunks:
        score = 0.0
        for term in query_terms:
            tf = counts[term]
            idf = math.log(1 + (len(chunks) - frequency[term] + 0.5) / (frequency[term] + 0.5))
            score += idf * (tf * 2.5) / (tf + 1.5 * (0.25 + 0.75 * sum(counts.values()) / avg_length))
        if score > 0:
            ranked.append(hit(doc, index, text, score))
    return sorted(ranked, key=lambda h: (-h["score"], h["chunk_id"]))[:limit]


def hit(doc, index, text, score):
    return {
        **parent_metadata(doc, index),
        "document_id": doc.id,
        "chunk_id": f"{doc.id}#{index}",
        "title": doc.title,
        "kind": doc.kind,
        "revision": doc.revision,
        "excerpt": text,
        "score": round(float(score), 6),
    }


def client(settings):
    from opensearchpy import OpenSearch

    return OpenSearch(settings.opensearch_url, timeout=20, max_retries=2, retry_on_timeout=True)


def index_documents(session, settings):
    if settings.retrieval_backend == "gemini":
        from copilot.gemini_retrieval import index_gemini

        return index_gemini(session, settings, visible_documents(session, settings.tenant), settings.tenant)
    if settings.retrieval_backend == "local":
        return sum(len(chunk_text(d.body)) for d in visible_documents(session, settings.tenant))
    search = client(settings)
    model = embedder(settings.embedding_model)
    dimension = model.get_sentence_embedding_dimension()
    index = settings.opensearch_index
    if not search.indices.exists(index=index):
        search.indices.create(
            index=index,
            body={
                "settings": {"index": {"knn": True}},
                "mappings": {
                    "_meta": {"embedding_model": settings.embedding_model},
                    "properties": {
                        "tenant": {"type": "keyword"},
                        "document_id": {"type": "keyword"},
                        "revision": {"type": "integer"},
                        "body": {"type": "text"},
                        "ordinal": {"type": "integer"},
                        "vector": {
                            "type": "knn_vector",
                            "dimension": dimension,
                            "method": {"name": "hnsw", "engine": "lucene", "space_type": "cosinesimil"},
                        },
                    },
                },
            },
        )
    mapping = search.indices.get_mapping(index=index)[index]["mappings"]
    if mapping.get("_meta", {}).get("embedding_model") != settings.embedding_model:
        raise ValueError("Embedding model changed; use a new index name and reindex")
    docs = visible_documents(session, settings.tenant)
    # Remove stale chunks for this tenant before rebuilding. Other tenants are untouched.
    search.delete_by_query(
        index=index, body={"query": {"term": {"tenant": settings.tenant}}}, refresh=True, conflicts="proceed"
    )
    from opensearchpy.helpers import bulk

    actions = []
    for doc in docs:
        chunks = chunk_text(doc.body)
        vectors = model.encode(chunks, normalize_embeddings=True).tolist()
        for i, (body, vector) in enumerate(zip(chunks, vectors)):
            actions.append(
                {
                    "_index": index,
                    "_id": f"{doc.id}#{i}",
                    "_source": {
                        "tenant": doc.tenant,
                        "document_id": doc.id,
                        "revision": doc.revision,
                        "ordinal": i,
                        "body": body,
                        "vector": vector,
                    },
                }
            )
    if actions:
        bulk(search, actions, refresh=True)
    return len(actions)


def hybrid_search(documents, query, settings, tenant, limit):
    search = client(settings)
    vector = embedder(settings.embedding_model).encode(query, normalize_embeddings=True).tolist()
    filter_ = {"term": {"tenant": tenant}}
    lexical = {"bool": {"must": [{"match": {"body": query}}], "filter": [filter_]}}
    dense = {"knn": {"vector": {"vector": vector, "k": limit, "filter": filter_}}}
    fused = {}
    sources = {}
    for clause in [lexical, dense]:
        results = search.search(index=settings.opensearch_index, body={"size": limit, "query": clause})
        for rank, row in enumerate(results["hits"]["hits"], 1):
            fused[row["_id"]] = fused.get(row["_id"], 0) + 1 / (60 + rank)
            sources[row["_id"]] = row["_source"]
    allowed = {d.id: d for d in documents}
    hits = []
    for key, score in sorted(fused.items(), key=lambda p: -p[1]):
        source = sources[key]
        doc = allowed.get(source["document_id"])
        # Revalidate ACL and version against the authoritative DB, never trust index contents.
        if doc and doc.revision == source["revision"]:
            current_chunks = chunk_text(doc.body)
            i = source["ordinal"]
            if 0 <= i < len(current_chunks) and current_chunks[i] == source["body"]:
                hits.append(hit(doc, i, current_chunks[i], score))
    return hits[:limit]


def search_documents(session, settings, tenant, query, limit=8, user=None, filters=None, subqueries=None):
    documents = visible_documents(session, tenant, user, **(filters or {}))
    subqueries = subqueries or decompose_question(query)
    if settings.retrieval_backend == "gemini":
        from copilot.gemini_retrieval import gemini_search

        return expand_parents(
            gemini_search(session, settings, documents, tenant, query, 30, subqueries), limit
        )
    expanded = rewrite(query)
    if settings.retrieval_backend == "opensearch":
        results = hybrid_search(documents, expanded, settings, tenant, 30)
    else:
        fused, rows = {}, {}
        for part in list(dict.fromkeys([expanded] + subqueries)):
            for rank, row in enumerate(local_search(documents, part, 30), 1):
                key = row["chunk_id"]
                rows[key] = row
                fused[key] = fused.get(key, 0) + 1 / (60 + rank)
        results = [{**rows[key], "score": score} for key, score in sorted(fused.items(), key=lambda p: -p[1])]
    if settings.rerank and results:
        scores = reranker(settings.reranker_model).predict([(query, h["excerpt"]) for h in results])
        for row, score in zip(results, scores):
            row["score"] = float(score)
        results.sort(key=lambda h: -h["score"])
    return expand_parents(results, limit)
