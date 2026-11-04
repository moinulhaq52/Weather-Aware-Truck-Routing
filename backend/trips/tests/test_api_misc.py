"""Health, SPA serving and the catch-all error handler."""

from rest_framework.test import APIClient

from trips.services import planner


def test_health():
    res = APIClient().get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_spa_index_served_for_client_routes(tmp_path, settings):
    (tmp_path / "index.html").write_text("<!doctype html><title>app</title>")
    settings.FRONTEND_DIST = tmp_path
    res = APIClient().get("/some/deep/link")
    assert res.status_code == 200
    assert b"<title>app</title>" in b"".join(res.streaming_content)
    assert res["Cache-Control"] == "no-cache"


def test_spa_index_404_when_frontend_not_built(tmp_path, settings):
    settings.FRONTEND_DIST = tmp_path  # empty: no index.html
    assert APIClient().get("/").status_code == 404


def test_unexpected_errors_return_generic_json_500(monkeypatch):
    def boom(req):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(planner, "providers_for", boom)
    from .test_planner import body

    client = APIClient(raise_request_exception=False)
    res = client.post("/api/plan", body(), format="json")
    assert res.status_code == 500
    assert res.json()["error"]["code"] == "internal_error"
    assert "secret" not in res.content.decode()


def test_plan_rejects_non_json(monkeypatch):
    res = APIClient().post(
        "/api/plan", "origin=1", content_type="application/x-www-form-urlencoded"
    )
    assert res.status_code == 415
