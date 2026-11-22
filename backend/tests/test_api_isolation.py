"""SRS AC-10: one user must never see, query, change or delete another user's data."""
import json

from conftest import event, sse_events

API = "/api/v1"

SECRET_TEXT = ("The launch codes for the project are stored in the blue vault under the eastern stairwell. " * 3).encode()


def test_documents_are_not_listed_across_users(make_user):
    a, b = make_user("alice"), make_user("bob")
    a.upload("alice_private.txt", SECRET_TEXT)
    assert len(a.documents()) == 1
    assert b.documents() == []


def test_user_cannot_delete_another_users_document(client, make_user):
    a, b = make_user("alice"), make_user("bob")
    doc_id = a.upload("alice_private.txt", SECRET_TEXT).json()["document_id"]
    assert client.delete(f"{API}/documents/{doc_id}", headers=b.headers).status_code == 404
    assert [d["doc_id"] for d in a.documents()] == [doc_id]  # still there


def test_retrieval_never_returns_another_users_chunks(client, make_user):
    a, b = make_user("alice"), make_user("bob")
    a.upload("alice_private.txt", SECRET_TEXT)
    question = SECRET_TEXT.decode().strip()

    own = client.post(f"{API}/query/stream", json={"query": question}, headers=a.headers)
    assert "alice_private.txt" in own.text  # sanity: the data is retrievable by its owner

    other = client.post(f"{API}/query/stream", json={"query": question}, headers=b.headers)
    events = sse_events(other.text)
    assert event(events, "sources")["sources"] == []
    # Bob's own question comes back as his chat's title; nothing else may carry Alice's data.
    shown = json.dumps([e for e in events if not (isinstance(e, dict) and e.get("type") == "conversation")])
    assert "alice_private.txt" not in shown and "blue vault" not in shown


def test_graph_job_controls_are_owner_only(client, make_user):
    a, b = make_user("alice"), make_user("bob")
    doc_id = a.upload("alice_private.txt", SECRET_TEXT).json()["document_id"]  # job is PAUSED
    assert client.post(f"{API}/graph/jobs/{doc_id}/start", headers=b.headers).status_code == 409
    assert a.documents()[0]["graph_status"] == "PAUSED"  # untouched by the foreign attempt


def test_graph_status_is_per_user(client, make_user):
    a, b = make_user("alice"), make_user("bob")
    a.upload("alice_private.txt", SECRET_TEXT, build_graph=False)
    s = client.get(f"{API}/graph/status", headers=b.headers)
    assert s.status_code == 200
    assert s.json()["entities"] == 0 and s.json()["active_jobs"] == 0


def test_malformed_job_ids_are_422(client, make_user):
    u = make_user("alice")
    for action in ("start", "pause"):
        assert client.post(f"{API}/graph/jobs/not-a-uuid/{action}", headers=u.headers).status_code == 422
