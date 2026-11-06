from copilot.models import Document
from copilot.retrieval import hybrid_search


def test_hybrid_revalidates_acl_revision_and_content(monkeypatch, app):
    class Vector:
        def tolist(self):
            return [0.1, 0.2]

    class Encoder:
        def encode(self, *args, **kwargs):
            return Vector()

    class Search:
        def search(self, **kwargs):
            query = kwargs["body"]["query"]
            filter_ = query["bool"]["filter"][0] if "bool" in query else query["knn"]["vector"]["filter"]
            assert filter_ == {"term": {"tenant": "acme"}}
            return {
                "hits": {
                    "hits": [
                        {
                            "_id": "good#0",
                            "_source": {
                                "document_id": "good",
                                "revision": 1,
                                "ordinal": 0,
                                "body": "Current approved procedure.",
                            },
                        },
                        {
                            "_id": "other#0",
                            "_source": {
                                "document_id": "other",
                                "revision": 1,
                                "ordinal": 0,
                                "body": "Foreign tenant data.",
                            },
                        },
                        {
                            "_id": "stale#0",
                            "_source": {
                                "document_id": "stale",
                                "revision": 1,
                                "ordinal": 0,
                                "body": "Old approved procedure.",
                            },
                        },
                        {
                            "_id": "tampered#0",
                            "_source": {
                                "document_id": "tampered",
                                "revision": 1,
                                "ordinal": 0,
                                "body": "Injected index text.",
                            },
                        },
                    ]
                }
            }

    monkeypatch.setattr("copilot.retrieval.embedder", lambda _: Encoder())
    monkeypatch.setattr("copilot.retrieval.client", lambda _: Search())
    docs = [
        Document(
            id="good",
            tenant="acme",
            title="Current",
            body="Current approved procedure.",
            revision=1,
            kind="policy",
        ),
        Document(
            id="stale", tenant="acme", title="Revised", body="Updated procedure.", revision=2, kind="policy"
        ),
        Document(
            id="tampered", tenant="acme", title="Untampered", body="Original text.", revision=1, kind="policy"
        ),
    ]
    hits = hybrid_search(docs, "procedure", app.state.settings, "acme", 8)
    assert [hit["document_id"] for hit in hits] == ["good"]
    assert abs(hits[0]["score"] - 2 / 61) < 0.000001
