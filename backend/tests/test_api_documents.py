import uuid


API = "/api/v1"

TEXT = ("Photosynthesis converts light energy into chemical energy stored in glucose. " * 5).encode()


def test_upload_indexes_in_background_and_lists(make_user):
    u = make_user("uploader")
    r = u.upload("notes.txt", TEXT)
    assert r.status_code == 202
    doc_id = r.json()["document_id"]

    docs = u.documents()
    assert [d["doc_id"] for d in docs] == [doc_id]
    d = docs[0]
    assert d["filename"] == "notes.txt" and d["index_status"] == "READY" and d["chunk_count"] >= 1
    assert d["graph_status"] == "PAUSED"  # build_graph=false parks the job


def test_upload_rejects_bad_files(make_user):
    u = make_user("badfiles")
    assert u.upload("virus.exe", b"x" * 100).status_code == 415
    assert u.upload("noextension", b"x" * 100).status_code == 400


def test_text_without_extractable_content_fails_with_message(make_user):
    u = make_user("empty")
    assert u.upload("tiny.txt", b"too short").status_code == 202
    d = u.documents()[0]
    assert d["index_status"] == "FAILED" and "No extractable text" in d["index_error"]


def test_delete_removes_document_and_chunks(client, make_user):
    u = make_user("deleter")
    doc_id = u.upload("a.txt", TEXT).json()["document_id"]
    r = client.delete(f"{API}/documents/{doc_id}", headers=u.headers)
    assert r.status_code == 200
    assert u.documents() == []
    assert client.delete(f"{API}/documents/{doc_id}", headers=u.headers).status_code == 404


def test_delete_unknown_id_is_404(client, make_user):
    u = make_user("ghostdel")
    assert client.delete(f"{API}/documents/{uuid.uuid4()}", headers=u.headers).status_code == 404


def test_delete_malformed_id_is_a_client_error(client, make_user):
    u = make_user("baddel")
    r = client.delete(f"{API}/documents/not-a-uuid", headers=u.headers)
    assert r.status_code in (404, 422)


def test_stream_query_returns_sources_and_tokens(client, make_user):
    u = make_user("asker")
    u.upload("bio.txt", TEXT)
    question = TEXT.decode().strip()  # identical text -> embedding distance 0 with the fake embedder
    r = client.post(f"{API}/query/stream", json={"query": question}, headers=u.headers)
    assert r.status_code == 200
    events = [e[len("data: "):] for e in r.text.split("\n\n") if e.startswith("data: ")]
    assert events[-1] == "[DONE]"
    import json
    sources = json.loads(events[0])
    assert sources["type"] == "sources" and sources["sources"][0]["filename"] == "bio.txt"
    assert any(json.loads(e).get("content") == "fake answer" for e in events[1:-1] if e.startswith("{"))


def test_stream_query_without_documents_refuses_without_llm(client, make_user):
    u = make_user("nodocs")
    r = client.post(f"{API}/query/stream", json={"query": "anything at all"}, headers=u.headers)
    assert r.status_code == 200
    assert "I cannot find the answer in your documents." in r.text and "fake answer" not in r.text


def test_empty_and_overlong_queries_rejected(client, make_user):
    u = make_user("badq")
    assert client.post(f"{API}/query/stream", json={"query": "   "}, headers=u.headers).status_code == 400
    assert client.post(f"{API}/query/stream", json={"query": "x" * 1001}, headers=u.headers).status_code == 422
