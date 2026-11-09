"""Behavioral regressions for the synthetic list scenes; no platform qualification."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from tests.e2e.skill_ab_fixture import SceneError
from tests.e2e.skill_ab_lists import CASE_IDS, JUDGES, judge, make_scene


def _node_map(scene: Any) -> dict[str, dict[str, Any]]:
    return {str(item["key"]): item for item in scene.nodes()}


def _keys(scene: Any) -> list[str]:
    return [str(item["key"]) for item in scene.nodes()]


def _failed(checks: list[dict[str, Any]]) -> set[str]:
    return {str(check["id"]) for check in checks if not check["ok"]}


def _assert_ok(checks: list[dict[str, Any]]) -> None:
    assert all(check["ok"] for check in checks), checks


def _page_cards(scene: Any, snapshot: dict[str, Any]) -> list[str]:
    card_keys = {f"task-{record['id']}" for record in snapshot["records"]}
    return [key for key in _keys(scene) if key in card_keys]


def _observe(scene: Any) -> dict[str, Any]:
    return {
        "action": "source",
        "observedNodes": [
            {"key": str(item["key"]), "text": str(item.get("text", ""))} for item in scene.nodes()
        ],
    }


def _click(scene: Any, key: str) -> dict[str, Any]:
    scene.act("click", key)
    return {"action": "click", "key": key, "stateAfter": scene.snapshot()}


def _walk_covered(scene: Any) -> list[dict[str, Any]]:
    journal: list[dict[str, Any]] = []
    while True:
        journal.append(_observe(scene))
        if not _node_map(scene)["page-next"].get("enabled", True):
            return journal
        journal.append(_click(scene, "page-next"))


def _filtered_covered(scene: Any) -> list[dict[str, Any]]:
    journal = _filtered_state(scene)
    journal.extend(_walk_covered(scene))
    return journal


def _click_count(journal: list[dict[str, Any]]) -> int:
    return sum(1 for entry in journal if entry.get("action") == "click")


def _card_observations(record_ids: list[str], *, end: bool = False) -> list[dict[str, str]]:
    observed = [{"key": f"task-{record_id}", "text": ""} for record_id in record_ids]
    if end:
        observed.append({"key": "list-end", "text": "End of list"})
    return observed


def _full_traversal_journal(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    record_ids = [str(record["id"]) for record in snapshot["records"]]
    return [
        {
            "action": "source",
            "observedNodes": _card_observations(record_ids, end=True),
        }
    ]


def _filtered_state(scene: Any) -> list[dict[str, Any]]:
    return [
        _click(scene, "filter-category-work"),
        _click(scene, "filter-status-active"),
    ]


def _solve_dedup(delete_id: str) -> tuple[Any, list[str]]:
    scene = make_scene("safe-dedup")
    log: list[str] = []
    for entry_id in ("R-203", "R-204"):
        scene.act("click", f"recipe-{entry_id}-open")
        log.append(f"open-{entry_id}")
        assert _node_map(scene)["detail-body"]["text"].startswith("Steps: ")
        scene.act("click", "detail-back")
        log.append("detail-back")
    scene.act("click", f"recipe-{delete_id}-delete")
    log.append(f"delete-{delete_id}")
    assert _node_map(scene)["delete-dialog-message"]["text"]
    scene.act("click", "delete-confirm")
    log.append("delete-confirm")
    return scene, log


def _add(scene: Any, item_id: str, log: list[str]) -> None:
    scene.act("click", f"track-{item_id}-action")
    log.append(f"add-{item_id}")


def _scroll(scene: Any, direction: str, log: list[str]) -> None:
    scene.act("scroll", "catalog", direction)
    log.append(f"scroll-{direction}")


def _submit(scene: Any, log: list[str]) -> None:
    scene.act("click", "cart-submit")
    log.append("submit")


def _aggregate_snapshot(
    durations: list[int], submitted_total: int | None = None
) -> tuple[dict[str, Any], list[str], int]:
    snapshot = make_scene("measured-aggregate").snapshot()
    catalog = [
        {"id": f"X-{index}", "title": f"Track {index}", "duration": duration}
        for index, duration in enumerate(durations)
    ]
    keys = [f"X-{index}" for index in range(len(durations))]
    total = sum(durations) if submitted_total is None else submitted_total
    snapshot.update(
        {
            "catalog": catalog,
            "cartKeys": list(keys),
            "cartTotal": sum(durations),
            "committed": True,
            "submittedKeys": list(keys),
            "submittedTotal": total,
        }
    )
    return snapshot, keys, sum(durations)


def test_case_ids_identity_and_module_judge_are_stable() -> None:
    assert CASE_IDS == ("covered-count", "safe-dedup", "measured-aggregate")
    assert set(JUDGES) == set(CASE_IDS)
    for case_id in CASE_IDS:
        first = make_scene(case_id)
        second = make_scene(case_id)
        assert first.id == case_id
        assert first.goal == second.goal
        assert first.budget == second.budget > 0
        assert first.snapshot() == second.snapshot()
    with pytest.raises(ValueError):
        make_scene("unknown-case")
    scene = make_scene("covered-count")
    snapshot = scene.snapshot()
    assert judge(snapshot, {"count": 4}, []) == scene.judge(snapshot, {"count": 4}, [])
    with pytest.raises(ValueError):
        judge({"caseId": "unknown-case"}, {"count": 0}, [])


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_nodes_are_pure_and_snapshots_are_detached_json(case_id: str) -> None:
    scene = make_scene(case_id)
    first_nodes = scene.nodes()
    first_snapshot = scene.snapshot()
    assert json.loads(json.dumps(first_snapshot)) == first_snapshot
    assert scene.nodes() == first_nodes
    assert scene.snapshot() == first_snapshot
    first_snapshot["caseId"] = "mutated"
    assert scene.snapshot()["caseId"] == case_id


# ---------------------------------------------------------------------------
# covered-count
# ---------------------------------------------------------------------------


def test_covered_count_requires_full_distinct_coverage() -> None:
    scene = make_scene("covered-count")
    journal = _filtered_covered(scene)
    snapshot = scene.snapshot()
    _assert_ok(scene.judge(snapshot, {"count": 4}, journal))
    assert _click_count(journal) <= scene.budget

    assert "covered.count" in _failed(scene.judge(snapshot, {"count": 3}, journal))
    assert "covered.count" in _failed(scene.judge(snapshot, {"count": 5}, journal))
    assert "covered.count" in _failed(scene.judge(snapshot, {"count": "four"}, journal))


def test_covered_count_accepts_unfiltered_full_traversal() -> None:
    scene = make_scene("covered-count")
    journal = _walk_covered(scene)
    _assert_ok(scene.judge(scene.snapshot(), {"count": 4}, journal))
    assert _click_count(journal) <= scene.budget


def test_covered_count_accepts_element_text_observations() -> None:
    scene = make_scene("covered-count")
    journal = _filtered_state(scene)
    observed: list[dict[str, str]] = []
    while True:
        observed.extend(
            {"key": str(item["key"]), "text": str(item.get("text", ""))} for item in scene.nodes()
        )
        if not _node_map(scene)["page-next"].get("enabled", True):
            break
        journal.append(_click(scene, "page-next"))
    journal.append({"action": "read", "observedNodes": observed})
    _assert_ok(scene.judge(scene.snapshot(), {"count": 4}, journal))
    assert _click_count(journal) <= scene.budget


def test_covered_count_rejects_first_page_or_lucky_answer() -> None:
    scene = make_scene("covered-count")
    snapshot = scene.snapshot()
    checks = scene.judge(snapshot, {"count": 4}, [_observe(scene)])
    assert "covered.coverage" in _failed(checks)
    assert "covered.count" not in _failed(checks)


def test_covered_count_rejects_absent_observations() -> None:
    scene = make_scene("covered-count")
    checks = scene.judge(scene.snapshot(), {"count": 4}, [])
    assert "covered.coverage" in _failed(checks)
    assert "covered.count" not in _failed(checks)


def test_covered_count_rejects_handle_or_visible_keys_only() -> None:
    scene = make_scene("covered-count")
    snapshot = scene.snapshot()
    journal: list[dict[str, Any]] = [
        {
            "action": "find",
            "visibleKeys": [f"task-{record['id']}" for record in snapshot["records"]],
            "observedNodes": _card_observations(
                [str(record["id"]) for record in snapshot["records"]], end=True
            ),
        },
        {
            "action": "source",
            "visibleKeys": [f"task-{record['id']}" for record in snapshot["records"]]
            + ["list-end"],
        },
    ]
    checks = scene.judge(snapshot, {"count": 4}, journal)
    assert "covered.coverage" in _failed(checks)


def test_covered_count_rejects_partial_traversal_without_end() -> None:
    scene = make_scene("covered-count")
    journal = [_observe(scene)]
    for _ in range(2):
        journal.append(_click(scene, "page-next"))
        journal.append(_observe(scene))
    checks = scene.judge(scene.snapshot(), {"count": 4}, journal)
    assert "covered.coverage" in _failed(checks)
    assert "covered.count" not in _failed(checks)


def test_covered_count_rejects_full_population_without_end_marker() -> None:
    scene = make_scene("covered-count")
    snapshot = scene.snapshot()
    record_ids = [str(record["id"]) for record in snapshot["records"]]
    journal = [
        {
            "action": "source",
            "observedNodes": _card_observations(record_ids),
        }
    ]
    checks = scene.judge(snapshot, {"count": 4}, journal)
    assert "covered.coverage" in _failed(checks)
    assert "end marker" in checks[1]["detail"]


def test_covered_count_rejects_matching_rows_only_under_filter() -> None:
    scene = make_scene("covered-count")
    journal = _filtered_state(scene)
    journal.append(
        {
            "action": "source",
            "observedNodes": _card_observations(["T-1001", "T-1002", "T-1003", "T-1008"], end=True),
        }
    )
    checks = scene.judge(scene.snapshot(), {"count": 4}, journal)
    assert "covered.coverage" in _failed(checks)
    detail = checks[1]["detail"]
    assert "T-1004" in detail
    assert "T-1007" in detail


def test_covered_count_rejects_filter_hiding_matching_tasks() -> None:
    scene = make_scene("covered-count")
    journal = [
        _click(scene, "filter-category-home"),
        _click(scene, "filter-status-active"),
    ]
    snapshot = scene.snapshot()
    journal.append(
        {
            "action": "source",
            "observedNodes": _card_observations(
                [
                    str(record["id"])
                    for record in snapshot["records"]
                    if record["category"] == "home" and record["status"] == "active"
                ],
                end=True,
            ),
        }
    )
    checks = scene.judge(snapshot, {"count": 4}, journal)
    assert "covered.coverage" in _failed(checks)


def test_covered_count_does_not_deduplicate_repeated_titles() -> None:
    scene = make_scene("covered-count")
    journal = _filtered_covered(scene)
    observed_keys = {item["key"] for entry in journal for item in entry.get("observedNodes", [])}
    assert "task-T-1002" in observed_keys
    assert "task-T-1003" in observed_keys
    checks = scene.judge(scene.snapshot(), {"count": 3}, journal)
    assert "covered.count" in _failed(checks)
    assert "covered.coverage" not in _failed(checks)


@pytest.mark.parametrize(
    ("record_id", "field", "value", "expected"),
    [
        ("T-1003", "due", "2026-11-16", 3),
        ("T-1002", "priority", 1, 3),
        ("T-1008", "status", "done", 3),
        ("T-1004", "due", "2026-11-15", 5),
        ("T-1007", "priority", 2, 5),
    ],
)
def test_covered_count_applies_inclusive_boundaries(
    record_id: str, field: str, value: object, expected: int
) -> None:
    scene = make_scene("covered-count")
    snapshot = copy.deepcopy(scene.snapshot())
    for record in snapshot["records"]:
        if record["id"] == record_id:
            record[field] = value
    journal = _full_traversal_journal(snapshot)
    _assert_ok(scene.judge(snapshot, {"count": expected}, journal))
    checks = scene.judge(snapshot, {"count": expected - 1}, journal)
    assert _failed(checks) == {"covered.count"}


def test_covered_ui_exposes_reference_clock_and_task_identity() -> None:
    scene = make_scene("covered-count")
    nodes = _node_map(scene)
    assert nodes["reference-date"]["text"].endswith("2026-11-09")
    assert scene.snapshot()["referenceDate"] == "2026-11-09"
    assert nodes["task-T-1002-title"]["text"] == "Prepare weekly report"
    assert nodes["task-T-1003-title"]["text"] == "Prepare weekly report"
    assert nodes["task-T-1002-id"]["text"] != nodes["task-T-1003-id"]["text"]
    assert nodes["task-T-1003-due"]["text"] == "Due: 2026-11-15"
    assert nodes["task-T-1002-priority"]["text"] == "Priority: 2"


def test_covered_pages_overlap_and_end_signal_is_deterministic() -> None:
    scene = make_scene("covered-count")
    snapshot = scene.snapshot()
    page_zero = _page_cards(scene, snapshot)
    assert len(page_zero) == 4
    scene.act("click", "page-next")
    page_one = _page_cards(scene, snapshot)
    assert len(page_one) == 4
    assert len(set(page_zero) & set(page_one)) == 2
    scene.act("click", "page-next")
    scene.act("click", "page-next")
    nodes = _node_map(scene)
    assert "list-end" in nodes
    assert nodes["page-next"]["enabled"] is False
    assert nodes["page-prev"]["enabled"] is True
    last = scene.snapshot()["view"]
    assert last["page"] == 3
    assert last["pageCount"] == 4
    assert last["endOfList"] is True
    assert set(last["visibleTaskKeys"]) & set(page_zero) == set()
    with pytest.raises(SceneError):
        scene.act("click", "page-next")
    assert scene.snapshot()["view"]["page"] == 3


def test_covered_filters_change_membership_and_reset_paging() -> None:
    scene = make_scene("covered-count")
    scene.act("click", "page-next")
    scene.act("click", "filter-category-work")
    assert scene.snapshot()["view"]["page"] == 0
    scene.act("click", "filter-status-active")
    snapshot = scene.snapshot()
    assert snapshot["view"]["pageCount"] == 2
    visible = set(snapshot["view"]["visibleTaskKeys"])
    records = {f"task-{record['id']}": record for record in snapshot["records"]}
    for key in visible:
        assert records[key]["category"] == "work"
        assert records[key]["status"] == "active"
    scene.act("click", "filter-status-done")
    done_keys = set(scene.snapshot()["view"]["visibleTaskKeys"])
    assert done_keys == {"task-T-1006", "task-T-1010"}


# ---------------------------------------------------------------------------
# safe-dedup
# ---------------------------------------------------------------------------


def test_dedup_details_are_readable_only_through_ordinary_navigation() -> None:
    scene = make_scene("safe-dedup")
    originals = {record["id"]: record for record in scene.snapshot()["originalRecords"]}
    list_text = " ".join(str(item.get("text", "")) for item in scene.nodes())
    assert originals["R-201"]["body"] not in list_text
    scene.act("click", "recipe-R-201-open")
    detail = _node_map(scene)
    assert detail["detail-body"]["text"] == f"Steps: {originals['R-201']['body']}"
    assert detail["detail-title"]["text"] == originals["R-201"]["title"]
    scene.act("click", "detail-back")
    assert "recipes-title" in _node_map(scene)


@pytest.mark.parametrize("delete_id", ["R-203", "R-204"])
def test_dedup_keeps_same_summary_variants_and_one_exact_copy(
    delete_id: str,
) -> None:
    scene, log = _solve_dedup(delete_id)
    snapshot = scene.snapshot()
    retained = {record["id"] for record in snapshot["records"]}
    assert delete_id not in retained
    assert {"R-203", "R-204"} & retained
    assert {"R-201", "R-202", "R-207"} <= retained
    assert {"R-205", "R-206"} <= retained
    assert len(snapshot["records"]) == 6
    _assert_ok(scene.judge(snapshot, {"removed": 1}, []))
    assert len(log) <= scene.budget


def test_dedup_requires_confirmation_and_leaves_list_unchanged() -> None:
    scene = make_scene("safe-dedup")
    scene.act("click", "recipe-R-204-delete")
    snapshot = scene.snapshot()
    assert snapshot["dialogEntryId"] == "R-204"
    assert len(snapshot["records"]) == 7
    scene.act("click", "delete-cancel")
    snapshot = scene.snapshot()
    assert snapshot["dialogEntryId"] is None
    assert len(snapshot["records"]) == 7
    scene.act("click", "recipe-R-204-delete")
    scene.act("back")
    snapshot = scene.snapshot()
    assert snapshot["dialogEntryId"] is None
    assert len(snapshot["records"]) == 7
    checks = scene.judge(snapshot, {"removed": 0}, [])
    assert "dedup.duplicates-removed" in _failed(checks)
    assert "dedup.removed-count" in _failed(checks)


def test_dedup_title_only_merge_loses_distinct_content() -> None:
    scene = make_scene("safe-dedup")
    for entry_id in ("R-202", "R-207"):
        scene.act("click", f"recipe-{entry_id}-delete")
        scene.act("click", "delete-confirm")
    snapshot = scene.snapshot()
    checks = scene.judge(snapshot, {"removed": 2}, [])
    assert "dedup.unique-content-retained" in _failed(checks)
    assert "dedup.duplicates-removed" in _failed(checks)
    assert "dedup.removed-count" in _failed(checks)


def test_dedup_same_count_wrong_survivor_is_rejected() -> None:
    scene = make_scene("safe-dedup")
    scene.act("click", "recipe-R-202-delete")
    scene.act("click", "delete-confirm")
    snapshot = scene.snapshot()
    assert len(snapshot["records"]) == 6
    checks = scene.judge(snapshot, {"removed": 1}, [])
    assert "dedup.unique-content-retained" in _failed(checks)
    assert "dedup.duplicates-removed" in _failed(checks)


def test_dedup_no_deletion_is_rejected() -> None:
    scene = make_scene("safe-dedup")
    checks = scene.judge(scene.snapshot(), {"removed": 0}, [])
    assert "dedup.duplicates-removed" in _failed(checks)
    assert "dedup.removed-count" in _failed(checks)


def test_dedup_rejects_added_duplicate_or_corrupted_content() -> None:
    scene, _ = _solve_dedup("R-204")
    clean = scene.snapshot()
    _assert_ok(scene.judge(clean, {"removed": 1}, []))

    duplicated = copy.deepcopy(clean)
    duplicated["records"].append(
        {
            "id": "R-999",
            "title": "Overnight Oats",
            "summary": "No-cook breakfast jar",
            "body": "Mix oats, milk and chia. Chill overnight. Top with berries.",
        }
    )
    duplicate_checks = scene.judge(duplicated, {"removed": 0}, [])
    assert "dedup.duplicates-removed" in _failed(duplicate_checks)
    assert "dedup.removed-count" in _failed(duplicate_checks)

    corrupted = copy.deepcopy(clean)
    corrupted["records"][0]["body"] += " Add extra sugar."
    corrupted_checks = scene.judge(corrupted, {"removed": 1}, [])
    assert "dedup.no-unexpected-content" in _failed(corrupted_checks)
    assert "dedup.unique-content-retained" in _failed(corrupted_checks)


# ---------------------------------------------------------------------------
# measured-aggregate
# ---------------------------------------------------------------------------


def test_aggregate_min_boundary_submits_measured_total() -> None:
    scene = make_scene("measured-aggregate")
    log: list[str] = []
    _add(scene, "P-301", log)
    _add(scene, "P-302", log)
    _scroll(scene, "down", log)
    _add(scene, "P-308", log)
    assert scene.snapshot()["cartTotal"] == 600
    _submit(scene, log)
    snapshot = scene.snapshot()
    assert snapshot["committed"] is True
    assert snapshot["submittedTotal"] == 600
    assert snapshot["submittedKeys"] == ["P-301", "P-302", "P-308"]
    _assert_ok(scene.judge(snapshot, {"total": 600}, []))
    assert len(log) <= scene.budget
    committed_nodes = _node_map(scene)
    assert committed_nodes["order-confirmed"]["text"] == "Order confirmed"
    assert "600" in committed_nodes["order-total"]["text"]


def test_aggregate_max_boundary_is_inclusive() -> None:
    scene = make_scene("measured-aggregate")
    log: list[str] = []
    _add(scene, "P-302", log)
    _add(scene, "P-303", log)
    _scroll(scene, "down", log)
    _add(scene, "P-308", log)
    _submit(scene, log)
    snapshot = scene.snapshot()
    assert snapshot["submittedTotal"] == 660
    _assert_ok(scene.judge(snapshot, {"total": 660}, []))
    assert len(log) <= scene.budget


@pytest.mark.parametrize(
    ("track_ids", "expected_total", "scroll_after"),
    [
        (["P-301", "P-302", "P-303"], 450, False),
        (["P-302", "P-303", "P-304", "P-305"], 780, True),
    ],
)
def test_aggregate_rejects_totals_outside_interval(
    track_ids: list[str], expected_total: int, scroll_after: bool
) -> None:
    scene = make_scene("measured-aggregate")
    log: list[str] = []
    for item_id in track_ids[:3]:
        _add(scene, item_id, log)
    if scroll_after:
        _scroll(scene, "down", log)
        _add(scene, track_ids[3], log)
    _submit(scene, log)
    snapshot = scene.snapshot()
    assert snapshot["submittedTotal"] == expected_total
    checks = scene.judge(snapshot, {"total": expected_total}, [])
    assert "aggregate.interval" in _failed(checks)
    assert "aggregate.committed" not in _failed(checks)
    assert "aggregate.answer-total" not in _failed(checks)


def test_aggregate_missing_commit_is_rejected() -> None:
    scene = make_scene("measured-aggregate")
    log: list[str] = []
    _add(scene, "P-301", log)
    _add(scene, "P-302", log)
    _scroll(scene, "down", log)
    _add(scene, "P-308", log)
    snapshot = scene.snapshot()
    assert snapshot["committed"] is False
    checks = scene.judge(snapshot, {"total": 600}, [])
    assert "aggregate.committed" in _failed(checks)
    assert "aggregate.submitted-items" in _failed(checks)
    assert "aggregate.observable-measure" in _failed(checks)
    assert "aggregate.answer-total" in _failed(checks)


def test_aggregate_rejects_count_proxy_or_inconsistent_ui_total() -> None:
    scene = make_scene("measured-aggregate")
    log: list[str] = []
    _add(scene, "P-301", log)
    _add(scene, "P-302", log)
    _scroll(scene, "down", log)
    _add(scene, "P-308", log)
    _submit(scene, log)
    snapshot = scene.snapshot()

    count_checks = scene.judge(snapshot, {"total": 3}, [])
    assert "aggregate.answer-total" in _failed(count_checks)
    assert "aggregate.interval" not in _failed(count_checks)

    inconsistent = copy.deepcopy(snapshot)
    inconsistent["submittedTotal"] = len(inconsistent["submittedKeys"])
    checks = scene.judge(inconsistent, {"total": 3}, [])
    assert "aggregate.observable-measure" in _failed(checks)
    assert "aggregate.answer-total" in _failed(checks)


def test_aggregate_add_remove_is_reversible_then_commit_persists() -> None:
    scene = make_scene("measured-aggregate")
    log: list[str] = []
    _scroll(scene, "down", log)
    _add(scene, "P-308", log)
    assert scene.snapshot()["cartTotal"] == 330
    _add(scene, "P-308", log)
    assert scene.snapshot()["cartTotal"] == 0
    assert _node_map(scene)["track-P-308-action"]["text"] == "Add"
    _scroll(scene, "up", log)
    _add(scene, "P-301", log)
    _add(scene, "P-302", log)
    _scroll(scene, "down", log)
    _add(scene, "P-308", log)
    _submit(scene, log)
    snapshot = scene.snapshot()
    assert snapshot["submittedTotal"] == 600
    _assert_ok(scene.judge(snapshot, {"total": 600}, []))
    assert len(log) <= scene.budget

    committed = scene.snapshot()
    with pytest.raises(SceneError):
        scene.act("click", "track-P-301-action")
    assert scene.snapshot() == committed
    with pytest.raises(SceneError):
        scene.act("click", "cart-submit")
    assert scene.snapshot() == committed


def test_aggregate_scroll_reveals_whole_catalog_deterministically() -> None:
    scene = make_scene("measured-aggregate")
    first = scene.snapshot()
    assert first["visibleCatalogKeys"] == [
        "track-P-301",
        "track-P-302",
        "track-P-303",
        "track-P-304",
    ]
    scene.act("scroll", "catalog", "down")
    second = scene.snapshot()
    assert second["visibleCatalogKeys"] == [
        "track-P-305",
        "track-P-306",
        "track-P-307",
        "track-P-308",
    ]
    scene.act("scroll", "catalog", "down")
    assert scene.snapshot()["scrollOffset"] == 4
    scene.act("scroll", "catalog", "up")
    scene.act("scroll", "catalog", "up")
    assert scene.snapshot()["scrollOffset"] == 0
    assert scene.nodes() == scene.nodes()


@pytest.mark.parametrize(
    ("durations", "expected_total", "passes"),
    [
        ([300, 300], 600, True),
        ([330, 330], 660, True),
        ([300, 299], 599, False),
        ([330, 331], 661, False),
    ],
)
def test_aggregate_interval_judge_boundaries(
    durations: list[int], expected_total: int, passes: bool
) -> None:
    scene = make_scene("measured-aggregate")
    snapshot, _, computed = _aggregate_snapshot(durations)
    assert computed == expected_total
    checks = scene.judge(snapshot, {"total": expected_total}, [])
    if passes:
        _assert_ok(checks)
    else:
        assert _failed(checks) == {"aggregate.interval"}


def test_aggregate_judge_uses_computed_measure_not_reported_value() -> None:
    scene = make_scene("measured-aggregate")
    snapshot, _, _ = _aggregate_snapshot([300, 300], submitted_total=601)
    checks = scene.judge(snapshot, {"total": 601}, [])
    assert "aggregate.observable-measure" in _failed(checks)
    assert "aggregate.answer-total" in _failed(checks)
    assert "aggregate.interval" not in _failed(checks)
