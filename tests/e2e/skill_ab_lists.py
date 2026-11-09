"""Synthetic list tasks for the #98 Skill A/B experiment.

These scenes are in-memory endpoint fixtures only: no device, filesystem,
shell, network, or hidden answer store participates. They expose ordinary
Android-style nodes and the supported ``click``/``clear``/``type``/``scroll``/
``back`` actions, and produce JSON-primitive snapshots for oracle checks.

The parent harness must keep snapshots and judges outside the Agent project.
For ``covered-count``, the authoritative evidence for full-list coverage is
the union of ``journal.observedNodes`` recorded on page-source and
element-text reads; find handles and ``journal.visibleKeys`` alone are not
evidence that list text was read. ``nodes()`` itself is pure and never
records or consumes a UI action.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from typing import Any, TypeGuard

from tests.e2e.skill_ab_fixture import SceneError, node

CASE_IDS: tuple[str, ...] = ("covered-count", "safe-dedup", "measured-aggregate")

_CHECK_RESULT = dict[str, Any]
_JOURNAL = list[dict[str, Any]]
_JUDGE = Callable[[dict[str, Any], object, _JOURNAL], list[_CHECK_RESULT]]

# ---------------------------------------------------------------------------
# covered-count: paginated overlapping work tasks behind a status/category UI.
# ---------------------------------------------------------------------------

_COVER_REFERENCE_DATE = "2026-11-09"
_COVER_PAGE_SIZE = 4
_COVER_OVERLAP = 2
_COVER_CRITERIA: dict[str, Any] = {
    "category": "work",
    "status": "active",
    "dueOnOrBefore": "2026-11-15",
    "priorityAtLeast": 2,
}
_COVER_GOAL = (
    "In the Tasks app, count the work tasks that are still active (not done), "
    "due on or before 2026-11-15, and priority 2 or higher. Today is 2026-11-09. "
    "Each task has its own Task ID, so repeated titles are different tasks. "
    "The list is paginated; adjacent pages can repeat rows, and the last page "
    "shows an end-of-list marker. Inspect the whole relevant list through its "
    "end marker before answering; a count taken from only the first page or a "
    "partial traversal is not acceptable. If you use filters, inspect every "
    "row they show and do not hide a task that could match. Put the integer "
    "count in the answer object with key `count`."
)
_COVER_BUDGET = 12
_COVER_RECORDS: tuple[dict[str, Any], ...] = (
    {
        "id": "T-1001",
        "title": "Finalize quarterly budget",
        "category": "work",
        "status": "active",
        "due": "2026-11-12",
        "priority": 3,
    },
    {
        "id": "T-1002",
        "title": "Prepare weekly report",
        "category": "work",
        "status": "active",
        "due": "2026-11-14",
        "priority": 2,
    },
    {
        "id": "T-1003",
        "title": "Prepare weekly report",
        "category": "work",
        "status": "active",
        "due": "2026-11-15",
        "priority": 3,
    },
    {
        "id": "T-1004",
        "title": "Archive old notes",
        "category": "work",
        "status": "active",
        "due": "2026-11-16",
        "priority": 4,
    },
    {
        "id": "T-1005",
        "title": "Renew parking permit",
        "category": "home",
        "status": "active",
        "due": "2026-11-13",
        "priority": 3,
    },
    {
        "id": "T-1006",
        "title": "Book dentist",
        "category": "work",
        "status": "done",
        "due": "2026-11-10",
        "priority": 3,
    },
    {
        "id": "T-1007",
        "title": "Draft travel plan",
        "category": "work",
        "status": "active",
        "due": "2026-11-09",
        "priority": 1,
    },
    {
        "id": "T-1008",
        "title": "Submit expense claim",
        "category": "work",
        "status": "active",
        "due": "2026-11-09",
        "priority": 2,
    },
    {
        "id": "T-1009",
        "title": "Clean garage",
        "category": "home",
        "status": "active",
        "due": "2026-11-08",
        "priority": 2,
    },
    {
        "id": "T-1010",
        "title": "Prepare weekly report",
        "category": "work",
        "status": "done",
        "due": "2026-11-15",
        "priority": 3,
    },
)

# ---------------------------------------------------------------------------
# safe-dedup: exact duplicate content among same-title/same-summary variants.
# ---------------------------------------------------------------------------

_DEDUP_CONTENT_FIELDS = ("title", "summary", "body")
_DEDUP_GOAL = (
    "Clean up my recipe notebook. Entries are exact duplicates only when their "
    "title, summary, and steps are all identical; keep exactly one copy of each "
    "identical group. Entries that share a title or summary but differ in any "
    "of title, summary, or steps are distinct recipes and must stay. Delete only "
    "exact duplicates. Put the number of entries you removed in the answer "
    "object with key `removed`."
)
_DEDUP_BUDGET = 20
_DEDUP_ORIGINALS: tuple[dict[str, Any], ...] = (
    {
        "id": "R-201",
        "title": "Lemon Pasta",
        "summary": "Bright quick weeknight pasta",
        "body": "Boil 200g spaghetti. Whisk lemon zest, juice and olive oil. Toss with parmesan.",
    },
    {
        "id": "R-202",
        "title": "Lemon Pasta",
        "summary": "Bright quick weeknight pasta",
        "body": "Boil 250g rigatoni. Blend basil, lemon and garlic. Fold through mascarpone.",
    },
    {
        "id": "R-203",
        "title": "Tomato Soup",
        "summary": "Roasted tomato soup",
        "body": "Roast tomatoes for 25 minutes. Blend with stock. Simmer for 10 minutes.",
    },
    {
        "id": "R-204",
        "title": "Tomato Soup",
        "summary": "Roasted tomato soup",
        "body": "Roast tomatoes for 25 minutes. Blend with stock. Simmer for 10 minutes.",
    },
    {
        "id": "R-205",
        "title": "Overnight Oats",
        "summary": "No-cook breakfast jar",
        "body": "Mix oats, milk and chia. Chill overnight. Top with berries.",
    },
    {
        "id": "R-206",
        "title": "Cucumber Salad",
        "summary": "Crunchy five-minute side",
        "body": "Slice cucumbers. Toss with vinegar, dill and salt.",
    },
    {
        "id": "R-207",
        "title": "Lemon Pasta",
        "summary": "Creamy baked lemon pasta",
        "body": "Bake pasta with cream and lemon. Rest for five minutes before serving.",
    },
)

# ---------------------------------------------------------------------------
# measured-aggregate: per-track durations with an observed cart total.
# ---------------------------------------------------------------------------

_AGG_MIN_SECONDS = 600
_AGG_MAX_SECONDS = 660
_AGG_VIEWPORT = 4
_AGG_BUDGET = 16
_AGG_GOAL = (
    "Build and submit one playlist order. Choose distinct tracks from the "
    "catalog; each track contributes its own listed duration in seconds, and "
    "the number of tracks is not a substitute for the duration total. The "
    "submitted total must be at least 600 and at most 660 seconds inclusive. "
    "Adding or removing tracks before submission is allowed; after you submit, "
    "the order is final. Put the confirmed total duration in the answer object "
    "with key `total`."
)
_AGG_CATALOG: tuple[dict[str, Any], ...] = (
    {"id": "P-301", "title": "Morning Piano", "duration": 120},
    {"id": "P-302", "title": "Studio Drift", "duration": 150},
    {"id": "P-303", "title": "Night Signal", "duration": 180},
    {"id": "P-304", "title": "Paper Planes", "duration": 210},
    {"id": "P-305", "title": "Slow Tide", "duration": 240},
    {"id": "P-306", "title": "City Lights", "duration": 270},
    {"id": "P-307", "title": "Warm Static", "duration": 300},
    {"id": "P-308", "title": "Cloud Chamber", "duration": 330},
)
_AGG_BY_ID: dict[str, dict[str, Any]] = {str(item["id"]): item for item in _AGG_CATALOG}


# ---------------------------------------------------------------------------
# Shared helpers.
# ---------------------------------------------------------------------------


def _check(identifier: str, ok: bool, detail: str) -> _CHECK_RESULT:
    return {"id": identifier, "ok": bool(ok), "detail": detail}


def _is_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _integer_answer(answer: object, field: str) -> tuple[int | None, str]:
    if not isinstance(answer, Mapping):
        return None, "answer is not a JSON object"
    if field not in answer:
        return None, f"answer has no {field!r} value"
    value = answer[field]
    if _is_int(value):
        return int(value), f"{field}={value}"
    if isinstance(value, float) and value.is_integer():
        return int(value), f"{field}={value}"
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
            return int(text), f"{field}={value!r}"
    return None, f"{field} is not an integer: {value!r}"


def _visible_keys(nodes: list[dict[str, Any]]) -> set[str]:
    return {str(item["key"]) for item in nodes if isinstance(item.get("key"), str)}


def _no_such_element(key: str) -> SceneError:
    return SceneError(
        "no such element",
        f"Element {key!r} is not present on the current screen.",
    )


def _not_interactable(key: str) -> SceneError:
    return SceneError(
        "invalid element state",
        f"Element {key!r} cannot be interacted with in its current state.",
    )


def _unknown_action(action: str) -> SceneError:
    return SceneError("unknown command", f"Unsupported action {action!r}.")


def _raise_for_non_text(action: str) -> None:
    if action in {"clear", "type"}:
        raise SceneError(
            "invalid element state",
            "This screen has no editable text field.",
        )
    raise _unknown_action(action)


# ---------------------------------------------------------------------------
# covered-count judge.
# ---------------------------------------------------------------------------


def _covered_matches(
    snapshot: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
    records = snapshot.get("records")
    criteria = snapshot.get("criteria")
    if not isinstance(records, list):
        return [], [], "snapshot has no records list"
    if not isinstance(criteria, Mapping):
        return [], [], "snapshot has no criteria object"
    category = criteria.get("category")
    status = criteria.get("status")
    due_limit = criteria.get("dueOnOrBefore")
    priority_min = criteria.get("priorityAtLeast")
    if not isinstance(category, str) or not isinstance(status, str):
        return [], [], "criteria category/status are not strings"
    if not isinstance(due_limit, str) or not _is_int(priority_min):
        return [], [], "criteria due/priority are malformed"
    all_records: list[dict[str, Any]] = []
    matches: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, Mapping):
            return [], [], "record is not an object"
        fields = ("id", "category", "status", "due", "priority")
        if any(field not in record for field in fields):
            return [], [], "record is missing a required field"
        copied = dict(record)
        all_records.append(copied)
        if (
            record["category"] == category
            and record["status"] == status
            and isinstance(record["due"], str)
            and record["due"] <= due_limit
            and _is_int(record["priority"])
            and int(record["priority"]) >= int(priority_min)
        ):
            matches.append(copied)
    return all_records, matches, None


def _observed_node(item: object) -> tuple[str, str | None] | None:
    if isinstance(item, Mapping):
        key = item.get("key")
        text = item.get("text")
        if isinstance(key, str):
            return key, text if isinstance(text, str) else None
        return None
    if isinstance(item, (list, tuple)) and len(item) >= 2:
        key, text = item[0], item[1]
        if isinstance(key, str):
            return key, text if isinstance(text, str) else None
    if isinstance(item, str):
        return item, None
    return None


def _observed_nodes(entry: Mapping[str, Any]) -> list[tuple[str, str | None]] | None:
    if entry.get("action") not in {"source", "read"}:
        return None
    nodes = entry.get("observedNodes")
    if not isinstance(nodes, list):
        return None
    observed: list[tuple[str, str | None]] = []
    for item in nodes:
        parsed = _observed_node(item)
        if parsed is not None:
            observed.append(parsed)
    return observed


def _filter_state(snapshot: object) -> tuple[str, str] | None:
    if not isinstance(snapshot, Mapping):
        return None
    view = snapshot.get("view")
    if not isinstance(view, Mapping):
        return None
    category = view.get("category")
    status = view.get("status")
    if category in {"all", "work", "home"} and status in {"all", "active", "done"}:
        return str(category), str(status)
    return None


def _observed_record_id(key: str, records: list[dict[str, Any]]) -> str | None:
    for record in records:
        card = f"task-{record['id']}"
        if key == card or key.startswith(f"{card}-"):
            return str(record["id"])
    return None


def _population_ids(records: list[dict[str, Any]], category: str, status: str) -> set[str]:
    return {
        str(record["id"])
        for record in records
        if (category == "all" or record["category"] == category)
        and (status == "all" or record["status"] == status)
    }


def _covered_coverage(
    records: list[dict[str, Any]],
    matches: list[dict[str, Any]],
    journal: _JOURNAL,
) -> tuple[bool, str]:
    observed_by_state: dict[tuple[str, str], set[str]] = {}
    ended_states: set[tuple[str, str]] = set()
    current: tuple[str, str] = ("all", "all")
    saw_observation = False
    for entry in journal:
        if not isinstance(entry, Mapping):
            continue
        observed = _observed_nodes(entry)
        if observed is not None:
            saw_observation = True
            observed_ids = observed_by_state.setdefault(current, set())
            for observed_key, text in observed:
                if observed_key == "list-end" and text == "End of list":
                    ended_states.add(current)
                record_id = _observed_record_id(observed_key, records)
                if record_id is not None:
                    observed_ids.add(record_id)
        after = _filter_state(entry.get("stateAfter"))
        if after is not None:
            current = after
            continue
        key = entry.get("key")
        if entry.get("action") != "click" or not isinstance(key, str):
            continue
        if key.startswith("filter-category-"):
            category = key.removeprefix("filter-category-")
            if category in {"all", "work", "home"}:
                current = (category, current[1])
        elif key.startswith("filter-status-"):
            status = key.removeprefix("filter-status-")
            if status in {"all", "active", "done"}:
                current = (current[0], status)
    if not saw_observation:
        return False, "no page-source or element/text observations were recorded"
    match_ids = {str(record["id"]) for record in matches}
    failures: list[str] = []
    for (category, status), observed_ids in observed_by_state.items():
        population = _population_ids(records, category, status)
        if not match_ids <= population:
            continue
        missing = sorted(population - observed_ids)
        if missing:
            failures.append(f"{category}/{status} missing rows {missing}")
            continue
        if (category, status) not in ended_states:
            failures.append(f"{category}/{status} stopped before the end marker")
            continue
        return (
            True,
            f"observed the full {category}/{status} population "
            f"({len(population)} rows) and the end marker",
        )
    if failures:
        return False, "; ".join(failures)
    return (
        False,
        "no observed unfiltered or business-filtered traversal covered the "
        "relevant rows through the end marker",
    )


def _judge_covered(
    snapshot: dict[str, Any], answer: object, journal: _JOURNAL
) -> list[_CHECK_RESULT]:
    records, matches, error = _covered_matches(snapshot)
    if error is not None:
        return [_check("covered.state", False, error)]
    expected = len(matches)
    value, detail = _integer_answer(answer, "count")
    coverage_ok, coverage_detail = _covered_coverage(records, matches, journal)
    return [
        _check(
            "covered.count",
            value == expected,
            f"expected {expected} matching tasks; {detail}",
        ),
        _check("covered.coverage", coverage_ok, coverage_detail),
    ]


# ---------------------------------------------------------------------------
# safe-dedup judge.
# ---------------------------------------------------------------------------


def _dedup_content(record: object, fields: list[str]) -> tuple[str, ...] | None:
    if not isinstance(record, Mapping):
        return None
    values: list[str] = []
    for field in fields:
        value = record.get(field)
        if not isinstance(value, str):
            return None
        values.append(value)
    return tuple(values)


def _judge_dedup(
    snapshot: dict[str, Any], answer: object, journal: _JOURNAL
) -> list[_CHECK_RESULT]:
    del journal
    originals = snapshot.get("originalRecords")
    current = snapshot.get("records")
    fields = snapshot.get("contentFields")
    if (
        not isinstance(originals, list)
        or not isinstance(current, list)
        or not isinstance(fields, list)
        or not fields
        or not all(isinstance(field, str) for field in fields)
    ):
        return [_check("dedup.state", False, "snapshot lacks dedup content data")]
    field_names = [str(field) for field in fields]
    original_keys: list[tuple[str, ...]] = []
    for record in originals:
        key = _dedup_content(record, field_names)
        if key is None:
            return [_check("dedup.state", False, "original record is malformed")]
        original_keys.append(key)
    current_keys: list[tuple[str, ...]] = []
    for record in current:
        key = _dedup_content(record, field_names)
        if key is None:
            return [_check("dedup.state", False, "current record is malformed")]
        current_keys.append(key)
    expected_unique = set(original_keys)
    observed_unique = set(current_keys)
    missing = expected_unique - observed_unique
    unexpected = observed_unique - expected_unique
    counts = Counter(current_keys)
    duplicates = [key for key, count in counts.items() if count > 1]
    expected_removed = len(originals) - len(expected_unique)
    actual_removed = len(originals) - len(current)
    value, detail = _integer_answer(answer, "removed")
    return [
        _check(
            "dedup.unique-content-retained",
            not missing,
            (
                "all distinct original contents remain"
                if not missing
                else f"{len(missing)} distinct original contents are missing"
            ),
        ),
        _check(
            "dedup.duplicates-removed",
            not duplicates,
            (
                "no exact duplicate content remains"
                if not duplicates
                else f"{len(duplicates)} exact duplicate content groups remain"
            ),
        ),
        _check(
            "dedup.no-unexpected-content",
            not unexpected,
            (
                "every current entry matches an original content"
                if not unexpected
                else f"{len(unexpected)} entries have added or altered content"
            ),
        ),
        _check(
            "dedup.removed-count",
            value == actual_removed and actual_removed == expected_removed,
            (f"expected removed={expected_removed}, actual removed={actual_removed}, {detail}"),
        ),
    ]


# ---------------------------------------------------------------------------
# measured-aggregate judge.
# ---------------------------------------------------------------------------


def _judge_aggregate(
    snapshot: dict[str, Any], answer: object, journal: _JOURNAL
) -> list[_CHECK_RESULT]:
    del journal
    catalog = snapshot.get("catalog")
    acceptance = snapshot.get("acceptance")
    if not isinstance(catalog, list) or not isinstance(acceptance, Mapping):
        return [_check("aggregate.state", False, "snapshot lacks catalog data")]
    minimum = acceptance.get("minSeconds")
    maximum = acceptance.get("maxSeconds")
    if not _is_int(minimum) or not _is_int(maximum) or int(minimum) > int(maximum):
        return [_check("aggregate.state", False, "acceptance interval is malformed")]
    durations: dict[str, int] = {}
    for item in catalog:
        if not isinstance(item, Mapping):
            return [_check("aggregate.state", False, "catalog item is malformed")]
        item_id = item.get("id")
        duration = item.get("duration")
        if (
            not isinstance(item_id, str)
            or not _is_int(duration)
            or int(duration) < 0
            or item_id in durations
        ):
            return [_check("aggregate.state", False, "catalog item is malformed")]
        durations[item_id] = int(duration)

    committed = snapshot.get("committed") is True
    submitted = snapshot.get("submittedKeys")
    submitted_total = snapshot.get("submittedTotal")
    if isinstance(submitted, list):
        keys = [key for key in submitted if isinstance(key, str)]
        keys_ok = len(keys) == len(submitted)
    else:
        keys = []
        keys_ok = False
    keys_ok = keys_ok and all(key in durations for key in keys)
    keys_ok = keys_ok and len(set(keys)) == len(keys)
    if committed and keys_ok:
        computed: int | None = sum(durations[key] for key in keys)
    else:
        computed = None

    checks = [
        _check(
            "aggregate.committed",
            committed,
            "order was submitted" if committed else "order was not submitted",
        ),
        _check(
            "aggregate.submitted-items",
            committed and keys_ok,
            (
                f"{len(keys)} distinct known tracks submitted"
                if committed and keys_ok
                else "submitted track identity is missing, repeated, or unknown"
            ),
        ),
        _check(
            "aggregate.observable-measure",
            computed is not None and _is_int(submitted_total) and int(submitted_total) == computed,
            f"UI total={submitted_total!r}, per-item sum={computed!r}",
        ),
        _check(
            "aggregate.interval",
            computed is not None and int(minimum) <= computed <= int(maximum),
            (f"per-item sum={computed!r}, accepted interval=[{minimum}, {maximum}] seconds"),
        ),
    ]
    value, detail = _integer_answer(answer, "total")
    checks.append(
        _check(
            "aggregate.answer-total",
            computed is not None and value == computed,
            f"answer {detail}; confirmed per-item sum={computed!r}",
        )
    )
    return checks


JUDGES: dict[str, _JUDGE] = {
    "covered-count": _judge_covered,
    "safe-dedup": _judge_dedup,
    "measured-aggregate": _judge_aggregate,
}


def judge(
    snapshot: dict[str, Any],
    answer: object,
    journal: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return independent oracle checks for one finished case.

    The case is identified by the fixed ``caseId`` field of the scene snapshot.
    """
    case_id = snapshot.get("caseId")
    if not isinstance(case_id, str) or case_id not in JUDGES:
        raise ValueError(f"Unknown snapshot caseId {case_id!r}; expected one of {CASE_IDS}.")
    return JUDGES[case_id](snapshot, answer, journal)


# ---------------------------------------------------------------------------
# Scenes.
# ---------------------------------------------------------------------------


class _Scene:
    def __init__(self, case_id: str, goal: str, budget: int) -> None:
        self.id = case_id
        self.goal = goal
        self.budget = budget

    def nodes(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def act(self, action: str, key: str = "", value: str = "") -> None:
        raise NotImplementedError

    def snapshot(self) -> dict[str, Any]:
        raise NotImplementedError

    def judge(
        self,
        snapshot: dict[str, Any],
        answer: object,
        journal: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return judge(snapshot, answer, journal)


class CoveredCountScene(_Scene):
    def __init__(self) -> None:
        super().__init__("covered-count", _COVER_GOAL, _COVER_BUDGET)
        self._category = "all"
        self._status = "all"
        self._page = 0

    def _filtered(self) -> list[dict[str, Any]]:
        return [
            record
            for record in _COVER_RECORDS
            if (self._category == "all" or record["category"] == self._category)
            and (self._status == "all" or record["status"] == self._status)
        ]

    @staticmethod
    def _page_starts(count: int) -> list[int]:
        if count <= _COVER_PAGE_SIZE:
            return [0]
        starts = [0]
        step = _COVER_PAGE_SIZE - _COVER_OVERLAP
        while starts[-1] + _COVER_PAGE_SIZE < count:
            starts.append(starts[-1] + step)
        return starts

    def _page_records(self) -> tuple[list[dict[str, Any]], list[int]]:
        filtered = self._filtered()
        starts = self._page_starts(len(filtered))
        page = min(self._page, len(starts) - 1)
        start = starts[page]
        return filtered[start : start + _COVER_PAGE_SIZE], starts

    def act(self, action: str, key: str = "", value: str = "") -> None:
        if action == "click":
            self._click(key)
        elif action == "back":
            return
        elif action == "scroll":
            return
        else:
            _raise_for_non_text(action)

    def _click(self, key: str) -> None:
        category = key.removeprefix("filter-category-")
        if key.startswith("filter-category-") and category in {"all", "work", "home"}:
            self._category = category
            self._page = 0
            return
        status = key.removeprefix("filter-status-")
        if key.startswith("filter-status-") and status in {"all", "active", "done"}:
            self._status = status
            self._page = 0
            return
        _, starts = self._page_records()
        if key == "page-prev":
            if self._page <= 0:
                raise _not_interactable(key)
            self._page -= 1
            return
        if key == "page-next":
            if self._page >= len(starts) - 1:
                raise _not_interactable(key)
            self._page += 1
            return
        if key in _visible_keys(self.nodes()):
            raise _not_interactable(key)
        raise _no_such_element(key)

    def nodes(self) -> list[dict[str, Any]]:
        records, starts = self._page_records()
        result: list[dict[str, Any]] = [
            node("tasks-title", "Tasks", kind="android.widget.TextView"),
            node(
                "reference-date",
                f"Today: {_COVER_REFERENCE_DATE}",
                kind="android.widget.TextView",
            ),
            node(
                "filter-category-label",
                "Category",
                kind="android.widget.TextView",
            ),
            node(
                "filter-category-all",
                "All",
                checked=self._category == "all",
                clickable=True,
            ),
            node(
                "filter-category-work",
                "Work",
                checked=self._category == "work",
                clickable=True,
            ),
            node(
                "filter-category-home",
                "Home",
                checked=self._category == "home",
                clickable=True,
            ),
            node("filter-status-label", "Status", kind="android.widget.TextView"),
            node(
                "filter-status-all",
                "All",
                checked=self._status == "all",
                clickable=True,
            ),
            node(
                "filter-status-active",
                "Active",
                checked=self._status == "active",
                clickable=True,
            ),
            node(
                "filter-status-done",
                "Done",
                checked=self._status == "done",
                clickable=True,
            ),
        ]
        for record in records:
            record_id = str(record["id"])
            card = f"task-{record_id}"
            result.extend(
                [
                    node(card, kind="android.widget.LinearLayout"),
                    node(
                        f"{card}-title",
                        str(record["title"]),
                        kind="android.widget.TextView",
                        parent=card,
                    ),
                    node(
                        f"{card}-id",
                        f"Task ID: {record_id}",
                        kind="android.widget.TextView",
                        parent=card,
                    ),
                    node(
                        f"{card}-category",
                        f"Category: {str(record['category']).capitalize()}",
                        kind="android.widget.TextView",
                        parent=card,
                    ),
                    node(
                        f"{card}-status",
                        f"Status: {str(record['status']).capitalize()}",
                        kind="android.widget.TextView",
                        parent=card,
                    ),
                    node(
                        f"{card}-due",
                        f"Due: {record['due']}",
                        kind="android.widget.TextView",
                        parent=card,
                    ),
                    node(
                        f"{card}-priority",
                        f"Priority: {record['priority']}",
                        kind="android.widget.TextView",
                        parent=card,
                    ),
                ]
            )
        page_count = len(starts)
        result.extend(
            [
                node(
                    "page-indicator",
                    f"Page {self._page + 1} of {page_count}",
                    kind="android.widget.TextView",
                ),
                node(
                    "page-prev",
                    "Previous",
                    enabled=self._page > 0,
                    clickable=True,
                ),
                node(
                    "page-next",
                    "Next",
                    enabled=self._page < page_count - 1,
                    clickable=True,
                ),
            ]
        )
        if not records:
            result.append(
                node(
                    "tasks-empty",
                    "No tasks match the current filters.",
                    kind="android.widget.TextView",
                )
            )
        if self._page == page_count - 1:
            result.append(node("list-end", "End of list", kind="android.widget.TextView"))
        return result

    def snapshot(self) -> dict[str, Any]:
        records, starts = self._page_records()
        return {
            "caseId": self.id,
            "goal": self.goal,
            "budget": self.budget,
            "referenceDate": _COVER_REFERENCE_DATE,
            "criteria": dict(_COVER_CRITERIA),
            "records": [dict(record) for record in _COVER_RECORDS],
            "view": {
                "category": self._category,
                "status": self._status,
                "page": self._page,
                "pageCount": len(starts),
                "visibleTaskKeys": [f"task-{record['id']}" for record in records],
                "endOfList": self._page == len(starts) - 1,
            },
            "pageSize": _COVER_PAGE_SIZE,
            "overlap": _COVER_OVERLAP,
        }


class SafeDedupScene(_Scene):
    def __init__(self) -> None:
        super().__init__("safe-dedup", _DEDUP_GOAL, _DEDUP_BUDGET)
        self._records = [dict(record) for record in _DEDUP_ORIGINALS]
        self._screen = "list"
        self._detail_id: str | None = None
        self._dialog_id: str | None = None

    def _record(self, entry_id: str | None) -> dict[str, Any] | None:
        for record in self._records:
            if record["id"] == entry_id:
                return record
        return None

    def act(self, action: str, key: str = "", value: str = "") -> None:
        if action == "click":
            self._click(key)
        elif action == "back":
            if self._dialog_id is not None:
                self._dialog_id = None
            elif self._screen == "detail":
                self._screen = "list"
                self._detail_id = None
        elif action == "scroll":
            return
        else:
            _raise_for_non_text(action)

    def _click(self, key: str) -> None:
        if self._dialog_id is not None:
            if key == "delete-confirm":
                entry_id = self._dialog_id
                self._records = [record for record in self._records if record["id"] != entry_id]
                self._dialog_id = None
                if self._detail_id == entry_id:
                    self._screen = "list"
                    self._detail_id = None
                return
            if key == "delete-cancel":
                self._dialog_id = None
                return
            if key in _visible_keys(self.nodes()):
                raise _not_interactable(key)
            raise _no_such_element(key)

        if self._screen == "detail":
            if key == "detail-back":
                self._screen = "list"
                self._detail_id = None
                return
            if key in _visible_keys(self.nodes()):
                raise _not_interactable(key)
            raise _no_such_element(key)

        if key.startswith("recipe-") and key.endswith("-open"):
            entry_id = key[len("recipe-") : -len("-open")]
            if self._record(entry_id) is None:
                raise _no_such_element(key)
            self._screen = "detail"
            self._detail_id = entry_id
            return
        if key.startswith("recipe-") and key.endswith("-delete"):
            entry_id = key[len("recipe-") : -len("-delete")]
            if self._record(entry_id) is None:
                raise _no_such_element(key)
            self._dialog_id = entry_id
            return
        if key in _visible_keys(self.nodes()):
            raise _not_interactable(key)
        raise _no_such_element(key)

    def nodes(self) -> list[dict[str, Any]]:
        if self._dialog_id is not None:
            record = self._record(self._dialog_id)
            label = (
                f"{record['title']} ({record['id']})"
                if record is not None
                else str(self._dialog_id)
            )
            return [
                node(
                    "delete-dialog-title",
                    "Delete entry?",
                    kind="android.widget.TextView",
                ),
                node(
                    "delete-dialog-message",
                    f"Remove {label}? This cannot be undone.",
                    kind="android.widget.TextView",
                ),
                node("delete-confirm", "Delete", clickable=True),
                node("delete-cancel", "Cancel", clickable=True),
            ]
        if self._screen == "detail":
            record = self._record(self._detail_id)
            if record is None:
                return [
                    node(
                        "detail-missing",
                        "Entry is unavailable.",
                        kind="android.widget.TextView",
                    ),
                    node("detail-back", "Back", clickable=True),
                ]
            record_id = str(record["id"])
            return [
                node(
                    "detail-title",
                    str(record["title"]),
                    kind="android.widget.TextView",
                ),
                node(
                    "detail-id",
                    f"Entry ID: {record_id}",
                    kind="android.widget.TextView",
                ),
                node(
                    "detail-summary",
                    f"Summary: {record['summary']}",
                    kind="android.widget.TextView",
                ),
                node(
                    "detail-body",
                    f"Steps: {record['body']}",
                    kind="android.widget.TextView",
                ),
                node("detail-back", "Back", clickable=True),
            ]

        result: list[dict[str, Any]] = [
            node(
                "recipes-title",
                "Recipe Notebook",
                kind="android.widget.TextView",
            ),
            node(
                "recipes-count",
                f"{len(self._records)} entries",
                kind="android.widget.TextView",
            ),
        ]
        for record in self._records:
            record_id = str(record["id"])
            card = f"recipe-{record_id}"
            result.extend(
                [
                    node(card, kind="android.widget.LinearLayout"),
                    node(
                        f"{card}-title",
                        str(record["title"]),
                        kind="android.widget.TextView",
                        parent=card,
                    ),
                    node(
                        f"{card}-summary",
                        str(record["summary"]),
                        kind="android.widget.TextView",
                        parent=card,
                    ),
                    node(
                        f"{card}-id",
                        f"Entry ID: {record_id}",
                        kind="android.widget.TextView",
                        parent=card,
                    ),
                    node(f"{card}-open", "Open", clickable=True, parent=card),
                    node(f"{card}-delete", "Delete", clickable=True, parent=card),
                ]
            )
        return result

    def snapshot(self) -> dict[str, Any]:
        return {
            "caseId": self.id,
            "goal": self.goal,
            "budget": self.budget,
            "contentFields": list(_DEDUP_CONTENT_FIELDS),
            "originalRecords": [dict(record) for record in _DEDUP_ORIGINALS],
            "records": [dict(record) for record in self._records],
            "screen": self._screen,
            "detailId": self._detail_id,
            "dialogEntryId": self._dialog_id,
            "visibleKeys": sorted(_visible_keys(self.nodes())),
        }


class MeasuredAggregateScene(_Scene):
    def __init__(self) -> None:
        super().__init__("measured-aggregate", _AGG_GOAL, _AGG_BUDGET)
        self._cart: list[str] = []
        self._offset = 0
        self._committed = False
        self._submitted: list[str] = []
        self._submitted_total: int | None = None

    def _visible_catalog(self) -> list[dict[str, Any]]:
        return list(_AGG_CATALOG[self._offset : self._offset + _AGG_VIEWPORT])

    def _cart_total(self) -> int:
        return sum(int(_AGG_BY_ID[item_id]["duration"]) for item_id in self._cart)

    def act(self, action: str, key: str = "", value: str = "") -> None:
        if action == "click":
            self._click(key)
        elif action == "scroll":
            self._scroll(key, value)
        elif action == "back":
            return
        else:
            _raise_for_non_text(action)

    def _click(self, key: str) -> None:
        if key.startswith("track-") and key.endswith("-action"):
            item_id = key[len("track-") : -len("-action")]
            if item_id not in _AGG_BY_ID:
                raise _no_such_element(key)
            if self._committed:
                raise _not_interactable(key)
            if item_id in self._cart:
                self._cart.remove(item_id)
            else:
                self._cart.append(item_id)
            return
        if key == "cart-submit":
            if self._committed:
                raise _not_interactable(key)
            if not self._cart:
                raise _not_interactable(key)
            self._committed = True
            self._submitted = list(self._cart)
            self._submitted_total = self._cart_total()
            return
        if key in _visible_keys(self.nodes()):
            raise _not_interactable(key)
        raise _no_such_element(key)

    def _scroll(self, key: str, value: str) -> None:
        if key not in {"", "catalog", "catalog-list"}:
            raise _no_such_element(key)
        direction = value.strip().lower()
        if direction not in {"", "down", "up"}:
            raise SceneError(
                "invalid argument",
                f"Unsupported scroll direction {value!r}.",
            )
        if self._committed:
            return
        max_offset = max(0, len(_AGG_CATALOG) - _AGG_VIEWPORT)
        if direction == "up":
            self._offset = max(0, self._offset - _AGG_VIEWPORT)
        else:
            self._offset = min(max_offset, self._offset + _AGG_VIEWPORT)

    def nodes(self) -> list[dict[str, Any]]:
        if self._committed:
            result: list[dict[str, Any]] = [
                node(
                    "order-confirmed",
                    "Order confirmed",
                    kind="android.widget.TextView",
                ),
                node(
                    "order-total",
                    f"Confirmed total duration: {self._submitted_total} seconds",
                    kind="android.widget.TextView",
                ),
                node(
                    "order-count",
                    f"Tracks in order: {len(self._submitted)}",
                    kind="android.widget.TextView",
                ),
            ]
            for item_id in self._submitted:
                item = _AGG_BY_ID[item_id]
                result.append(
                    node(
                        f"order-{item_id}",
                        f"{item['title']} - {item['duration']} seconds",
                        kind="android.widget.TextView",
                    )
                )
            return result

        visible = self._visible_catalog()
        first = self._offset + 1
        last = self._offset + len(visible)
        result = [
            node(
                "catalog-title",
                "Track Catalog",
                kind="android.widget.TextView",
            ),
            node(
                "catalog-range",
                f"Showing tracks {first}-{last} of {len(_AGG_CATALOG)}",
                kind="android.widget.TextView",
            ),
        ]
        for item in visible:
            item_id = str(item["id"])
            card = f"track-{item_id}"
            in_cart = item_id in self._cart
            result.extend(
                [
                    node(card, kind="android.widget.LinearLayout"),
                    node(
                        f"{card}-title",
                        str(item["title"]),
                        kind="android.widget.TextView",
                        parent=card,
                    ),
                    node(
                        f"{card}-duration",
                        f"Duration: {item['duration']} seconds",
                        kind="android.widget.TextView",
                        parent=card,
                    ),
                    node(
                        f"{card}-action",
                        "Remove" if in_cart else "Add",
                        clickable=True,
                        parent=card,
                    ),
                ]
            )
        result.append(
            node(
                "cart-title",
                f"Selected tracks ({len(self._cart)})",
                kind="android.widget.TextView",
            )
        )
        if not self._cart:
            result.append(
                node(
                    "cart-empty",
                    "No tracks selected.",
                    kind="android.widget.TextView",
                )
            )
        for item_id in self._cart:
            item = _AGG_BY_ID[item_id]
            result.append(
                node(
                    f"cart-{item_id}",
                    f"{item['title']} - {item['duration']} seconds",
                    kind="android.widget.TextView",
                )
            )
        result.extend(
            [
                node(
                    "cart-total",
                    f"Total duration: {self._cart_total()} seconds",
                    kind="android.widget.TextView",
                ),
                node(
                    "cart-submit",
                    "Submit order",
                    enabled=bool(self._cart),
                    clickable=True,
                ),
            ]
        )
        return result

    def snapshot(self) -> dict[str, Any]:
        return {
            "caseId": self.id,
            "goal": self.goal,
            "budget": self.budget,
            "acceptance": {
                "minSeconds": _AGG_MIN_SECONDS,
                "maxSeconds": _AGG_MAX_SECONDS,
            },
            "catalog": [dict(item) for item in _AGG_CATALOG],
            "cartKeys": list(self._cart),
            "cartTotal": self._cart_total(),
            "committed": self._committed,
            "submittedKeys": list(self._submitted),
            "submittedTotal": self._submitted_total,
            "scrollOffset": self._offset,
            "visibleCatalogKeys": [f"track-{item['id']}" for item in self._visible_catalog()],
        }


def make_scene(case_id: str) -> _Scene:
    """Create a fresh deterministic scene for ``case_id``."""
    if case_id == "covered-count":
        return CoveredCountScene()
    if case_id == "safe-dedup":
        return SafeDedupScene()
    if case_id == "measured-aggregate":
        return MeasuredAggregateScene()
    raise ValueError(f"Unknown case id {case_id!r}; expected one of {CASE_IDS}.")
