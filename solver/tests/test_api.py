"""The week API and its plan cache, run against temporary folders with made-up weeks."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import mycal.demo
from mycal import api
from mycal.api import CACHE_DIR_ENV, WEEKS_DIR_ENV, app
from mycal.solve import solve

WEEK = """
timezone = "America/Los_Angeles"
week_start = 2026-11-16

[[work_frames]]
name = "Mornings"
weekdays = [0]
start_time = 09:00:00
end_time = 11:00:00

[[items]]
title = "Lecture"
preset = "exact"
start = 2026-11-17T11:00:00
end = 2026-11-17T12:30:00

[[items]]
title = "Gym"
preset = "day"
day = 2026-11-16
estimate_min = 60

[[items]]
title = "Email advisor"
preset = "custom"
windows = []
estimate_min = 15
"""


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv(WEEKS_DIR_ENV, str(tmp_path))
    monkeypatch.setenv(CACHE_DIR_ENV, str(tmp_path / "cache"))
    (tmp_path / "2026-11-16.toml").write_text(WEEK, encoding="utf-8")
    return TestClient(app)


def test_week_is_solved_and_returned_in_utc(client: TestClient) -> None:
    response = client.get("/api/weeks/2026-11-16")
    assert response.status_code == 200
    week = response.json()
    assert (week["week_start"], week["timezone"], week["feasible"]) == ("2026-11-16", "America/Los_Angeles", True)

    blocks = {b["title"]: b for b in week["blocks"]}
    assert (blocks["Gym"]["start"], blocks["Gym"]["end"], blocks["Gym"]["fixed"]) == (
        "2026-11-16T17:00:00Z",  # 9am PST
        "2026-11-16T18:00:00Z",
        False,
    )
    assert blocks["Lecture"]["fixed"] is True
    assert week["frames"] == [{"start": "2026-11-16T17:00:00Z", "end": "2026-11-16T19:00:00Z"}]
    assert [i["title"] for i in week["unscheduled"]] == ["Email advisor"]


def test_missing_week_is_404(client: TestClient) -> None:
    assert client.get("/api/weeks/2026-11-23").status_code == 404


@pytest.mark.parametrize("bad", ["not-a-date", "2026-13-01"])
def test_bad_date_is_422(client: TestClient, bad: str) -> None:
    assert client.get(f"/api/weeks/{bad}").status_code == 422


def test_path_tricks_match_no_route(client: TestClient) -> None:
    # Only a valid date reaches the file lookup, so nothing outside the folder is read.
    assert client.get("/api/weeks/..%2F..%2Fpyproject").status_code == 404


def test_broken_week_file_is_400(client: TestClient, tmp_path: Path) -> None:
    (tmp_path / "2026-11-23.toml").write_text('timezone = "America/Los_Angeles"\n', encoding="utf-8")
    response = client.get("/api/weeks/2026-11-23")
    assert response.status_code == 400
    assert "week_start" in response.json()["detail"]


def test_infeasible_week_is_200_with_no_blocks(client: TestClient, tmp_path: Path) -> None:
    too_much = WEEK.replace("estimate_min = 60", "estimate_min = 600")
    (tmp_path / "2026-11-23.toml").write_text(too_much, encoding="utf-8")
    week = client.get("/api/weeks/2026-11-23").json()
    assert (week["feasible"], week["blocks"]) == (False, [])


# Plan cache


@pytest.fixture
def solves(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Counts calls to solve() made through plan_week()."""
    calls: list[int] = []

    def counting_solve(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(1)
        return solve(*args, **kwargs)

    monkeypatch.setattr(mycal.demo, "solve", counting_solve)
    return calls


def cache_files(tmp_path: Path) -> list[Path]:
    return sorted((tmp_path / "cache").glob("*.json"))


def test_unchanged_file_returns_the_cached_plan_without_solving(client: TestClient, solves: list[int]) -> None:
    first = client.get("/api/weeks/2026-11-16").json()
    second = client.get("/api/weeks/2026-11-16").json()
    assert len(solves) == 1
    assert second == first  # same ids too


def test_changed_file_solves_again_and_replaces_the_old_plan(
    client: TestClient, solves: list[int], tmp_path: Path
) -> None:
    client.get("/api/weeks/2026-11-16")
    [old] = cache_files(tmp_path)
    (tmp_path / "2026-11-16.toml").write_text(WEEK.replace("estimate_min = 60", "estimate_min = 30"), encoding="utf-8")
    week = client.get("/api/weeks/2026-11-16").json()
    assert len(solves) == 2
    gym = next(b for b in week["blocks"] if b["title"] == "Gym")
    assert (gym["start"], gym["end"]) == ("2026-11-16T17:00:00Z", "2026-11-16T17:30:00Z")
    [new] = cache_files(tmp_path)
    assert new != old


def test_cache_survives_a_restart(client: TestClient, solves: list[int]) -> None:
    first = client.get("/api/weeks/2026-11-16").json()
    assert TestClient(app).get("/api/weeks/2026-11-16").json() == first
    assert len(solves) == 1


def test_new_solver_version_solves_again(
    client: TestClient, solves: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    client.get("/api/weeks/2026-11-16")
    monkeypatch.setattr(api, "SOLVER_VERSION", "something-else")
    client.get("/api/weeks/2026-11-16")
    assert len(solves) == 2


@pytest.mark.parametrize("contents", ["", "not json", '{"week_start": "2026-11-16"}'])
def test_unreadable_cache_file_is_a_miss(
    client: TestClient, solves: list[int], tmp_path: Path, contents: str
) -> None:
    first = client.get("/api/weeks/2026-11-16").json()
    [cached] = cache_files(tmp_path)
    cached.write_text(contents, encoding="utf-8")
    response = client.get("/api/weeks/2026-11-16")
    assert response.status_code == 200
    assert len(solves) == 2
    assert [b["title"] for b in response.json()["blocks"]] == [b["title"] for b in first["blocks"]]
    assert api.WeekOut.model_validate_json(cached.read_bytes())  # rewritten with a good plan


def test_errors_are_not_cached(client: TestClient, tmp_path: Path) -> None:
    (tmp_path / "2026-11-23.toml").write_text('timezone = "America/Los_Angeles"\n', encoding="utf-8")
    assert client.get("/api/weeks/2026-11-23").status_code == 400
    assert client.get("/api/weeks/2026-11-30").status_code == 404
    assert cache_files(tmp_path) == []


def test_solver_version_is_stable_and_follows_ortools(monkeypatch: pytest.MonkeyPatch) -> None:
    assert api._solver_version() == api.SOLVER_VERSION  # same code, same version
    monkeypatch.setattr(api, "version", lambda package: "99.0")
    assert api._solver_version() != api.SOLVER_VERSION
