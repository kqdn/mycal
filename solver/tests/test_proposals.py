"""Proposals (Milestone 8): a change sent with propose=true waits for Accept or Discard instead of saving."""

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mycal import api, store
from mycal.importer import import_week

EXAMPLE = Path(__file__).parent.parent / "examples" / "week.toml"
WEEK, WEEK_2 = "2026-11-16", "2026-11-23"
BEFORE_THE_WEEK = datetime(2026, 11, 15, 12, tzinfo=UTC)
ESSAY = {"week_start": WEEK, "title": "Essay", "preset": "day", "day": "2026-11-18", "estimate_min": 60}


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "mycal.db"
    monkeypatch.setenv(store.DB_ENV, str(path))
    monkeypatch.setattr(api, "now", lambda: BEFORE_THE_WEEK)
    import_week(EXAMPLE, path)
    conn = store.connect(path)
    for series in store.list_series(conn):  # keep later weeks empty, as in the API tests
        store.put_series(conn, replace(series, end_date=date(2026, 11, 22)))
    conn.close()
    return path


@pytest.fixture
def client(db: Path) -> Iterator[TestClient]:
    api._drop_proposal()  # the proposal lives in the module, so no test sees another's
    api._notice = None
    yield TestClient(app=api.app)
    api._drop_proposal()
    api._notice = None


def titles(blocks: list[dict]) -> set[str]:
    return {b["title"] for b in blocks}


def stored_titles(db: Path) -> set[str]:
    return {i.title for i in store.list_items(store.connect(db))}


def get(client: TestClient, week: str = WEEK) -> dict:
    response = client.get(f"/api/weeks/{week}")
    assert response.status_code == 200, response.text
    return response.json()


def propose_essay(client: TestClient, **changes: object) -> dict:
    response = client.post("/api/items", json=ESSAY | {"propose": True} | changes)
    assert response.status_code == 201, response.text
    return response.json()


def test_a_proposed_change_waits_and_accept_saves_it(client: TestClient, db: Path) -> None:
    week = propose_essay(client)

    assert week["proposal"]["summary"] == "Add Essay"
    assert "Essay" in titles(week["proposal"]["blocks"]) and "Essay" not in titles(week["blocks"])
    assert "Essay" not in stored_titles(db)
    assert get(client)["proposal"]["summary"] == "Add Essay"  # it waits across requests

    accepted = client.post("/api/proposal/accept", params={"week": WEEK})

    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["proposal"] is None
    assert "Essay" in titles(accepted.json()["blocks"]) and "Essay" in stored_titles(db)


def test_discard_changes_nothing(client: TestClient, db: Path) -> None:
    before = get(client)["blocks"]
    propose_essay(client)

    discarded = client.post("/api/proposal/discard", params={"week": WEEK})

    assert discarded.status_code == 200, discarded.text
    assert discarded.json()["proposal"] is None and discarded.json()["blocks"] == before
    assert "Essay" not in stored_titles(db)


def test_other_changes_wait_until_the_proposal_is_answered(client: TestClient) -> None:
    propose_essay(client)
    other = ESSAY | {"title": "Errand"}
    assert client.post("/api/items", json=other | {"propose": True}).status_code == 409
    assert client.post("/api/items", json=other).status_code == 409  # saving right away too
    some_item = get(client)["blocks"][0]["item_id"]
    assert client.delete(f"/api/items/{some_item}", params={"week": WEEK}).status_code == 409
    client.post("/api/proposal/discard", params={"week": WEEK})
    assert client.post("/api/items", json=other).status_code == 201


def test_answering_with_nothing_waiting_is_404(client: TestClient) -> None:
    assert client.post("/api/proposal/accept", params={"week": WEEK}).status_code == 404
    assert client.post("/api/proposal/discard", params={"week": WEEK}).status_code == 404


def test_work_that_does_not_fit_is_proposed_with_what_is_left_over(client: TestClient, db: Path) -> None:
    assert client.post("/api/items", json=ESSAY | {"estimate_min": 20 * 60}).status_code == 422  # saving: refused

    week = propose_essay(client, estimate_min=20 * 60)

    # One long Essay block may also squeeze another item's session (fewest minutes left out overall).
    left = {item["title"]: item for item in week["proposal"]["left_over"]}
    assert 0 < left["Essay"]["minutes"] < 20 * 60
    assert left["Essay"]["message"].endswith("won't fit on Wed")
    assert "Essay" in titles(week["proposal"]["blocks"])  # as much as fits
    client.post("/api/proposal/accept", params={"week": WEEK})
    assert "Essay" in stored_titles(db)  # accepted with the rest left over


def test_other_weeks_show_the_proposal_too(client: TestClient) -> None:
    propose_essay(client)
    later = get(client, WEEK_2)
    assert later["proposal"]["summary"] == "Add Essay"


def test_a_proposal_names_the_other_weeks_it_changes(client: TestClient) -> None:
    # Due next week, so the change re-plans both weeks; with room this week, the report lands here.
    report = {"week_start": WEEK, "title": "Report", "preset": "before_deadline", "deadline_date": "2026-11-25",
              "deadline_time": "17:00", "estimate_min": 60, "propose": True}
    response = client.post("/api/items", json=report)
    assert response.status_code == 201, response.text
    here = response.json()["proposal"]
    assert "Report" in titles(here["blocks"])
    assert here["other_weeks"] == []  # nothing moves next week

    later = get(client, WEEK_2)["proposal"]

    assert later["other_weeks"] == [{"week_start": WEEK, "changes": 1}]


def test_a_proposed_delete_keeps_the_item_until_accepted(client: TestClient, db: Path) -> None:
    item = next(b for b in get(client)["blocks"] if not b["fixed"] and b["series_id"] is None)

    response = client.delete(f"/api/items/{item['item_id']}", params={"week": WEEK, "propose": True})

    assert response.status_code == 200, response.text
    assert response.json()["proposal"]["summary"] == f"Delete {item['title']}"
    assert item["id"] not in {b["id"] for b in response.json()["proposal"]["blocks"]}
    assert item["title"] in stored_titles(db)
    client.post("/api/proposal/accept", params={"week": WEEK})
    assert item["title"] not in stored_titles(db)


def test_a_check_in_saving_on_its_own_drops_the_proposal(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    get(client)  # plan the week before anything ends
    propose_essay(client)
    monkeypatch.setattr(api, "now", lambda: datetime(2026, 11, 21, 20, tzinfo=UTC))  # Sat noon: sessions went unanswered

    week = get(client)

    assert week["proposal"] is None
    assert week["notice"] == api.PROPOSAL_DROPPED
    assert get(client)["notice"] is None  # said once
