"""Deterministic regressions for the Skill A/B form, file and phase scenes."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from typing import Any

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.e2e.skill_ab_fixture import SceneError
from tests.e2e.skill_ab_forms import (
    _EXACT_SOURCES,
    _EXACT_TARGET_NAME,
    _EXACT_TARGET_TEXT,
    _FOCUS_SOURCE,
    _FOCUS_TARGET_KEY,
    _FOCUS_TARGET_VALUE,
    _OPENING_TOTAL,
    _PHASE_AMOUNTS,
    _TARGET_PHASE_COUNT,
    _TARGET_TOTAL,
    CASE_IDS,
    JUDGES,
    ExactFileScene,
    FocusSubmitScene,
    PhasedProgressScene,
    judge,
    make_scene,
)


def _failed(checks: list[dict[str, Any]]) -> set[str]:
    return {check["id"] for check in checks if not check["ok"]}


def _assert_ok(case: unittest.TestCase, checks: list[dict[str, Any]]) -> None:
    case.assertEqual(_failed(checks), set(), checks)


def _assert_failed(case: unittest.TestCase, checks: list[dict[str, Any]], *expected: str) -> None:
    failed = _failed(checks)
    for check_id in expected:
        case.assertIn(check_id, failed, checks)


def _nodes(scene: Any) -> dict[str, dict[str, Any]]:
    return {item["key"]: item for item in scene.nodes()}


def _focus_success() -> FocusSubmitScene:
    scene = FocusSubmitScene()
    scene.act("click", _FOCUS_TARGET_KEY)
    scene.act("clear", _FOCUS_TARGET_KEY)
    scene.act("type", _FOCUS_TARGET_KEY, _FOCUS_TARGET_VALUE)
    scene.act("click", "save-profile")
    return scene


def _create_file(
    scene: ExactFileScene,
    *,
    name: str = _EXACT_TARGET_NAME,
    extension: str | None = "",
    body: str = _EXACT_TARGET_TEXT,
    save: bool = True,
) -> None:
    scene.act("click", "new-file")
    scene.act("type", "file-name", name)
    if extension is not None:
        scene.act("click", "file-extension")
        scene.act("clear", "file-extension")
        if extension:
            scene.act("type", "file-extension", extension)
    scene.act("click", "create-file")
    if body:
        scene.act("type", "file-body", body)
    if save:
        scene.act("click", "save-file")


def _observation(scene: PhasedProgressScene, omit: set[str] | None = None) -> dict[str, Any]:
    omitted = omit or set()
    return {
        "action": "source",
        "observedNodes": [
            {"key": item["key"], "text": item["text"]}
            for item in scene.nodes()
            if item["key"] not in omitted
        ],
    }


def _review_all_phases(scene: PhasedProgressScene) -> list[dict[str, Any]]:
    journal = []
    for _ in range(_TARGET_PHASE_COUNT):
        journal.append(_observation(scene))
        scene.act("click", "next-phase")
    return journal


def _submit_phase_answer(
    scene: PhasedProgressScene, total: object = _TARGET_TOTAL, phases: object = 3
) -> None:
    scene.act("type", "answer-total", str(total))
    scene.act("click", "answer-phases")
    scene.act("type", "answer-phases", str(phases))
    scene.act("click", "submit-answer")


class SceneContractTests(unittest.TestCase):
    def test_exports_three_named_scenes(self) -> None:
        self.assertEqual(CASE_IDS, ("focus-submit", "exact-file", "phased-progress"))
        self.assertEqual(set(JUDGES), set(CASE_IDS))
        for case_id in CASE_IDS:
            scene = make_scene(case_id)
            self.assertEqual(scene.id, case_id)
            self.assertTrue(scene.goal)
            self.assertGreater(scene.budget, 0)
            snapshot = scene.snapshot()
            self.assertEqual(snapshot["id"], case_id)
            self.assertEqual(json.loads(json.dumps(snapshot)), snapshot)

    def test_unknown_case_and_unknown_snapshot_are_explicit(self) -> None:
        with self.assertRaises(ValueError):
            make_scene("not-a-scene")
        checks = judge({"id": "not-a-scene"}, None, [])
        self.assertEqual(_failed(checks), {"known-scene"})

    def test_node_reads_are_pure_and_keys_are_unique(self) -> None:
        for case_id in CASE_IDS:
            scene = make_scene(case_id)
            before = scene.snapshot()
            for _ in range(3):
                nodes = scene.nodes()
                self.assertEqual(len(nodes), len({item["key"] for item in nodes}))
            self.assertEqual(scene.snapshot(), before)

    def test_snapshots_are_defensive_copies(self) -> None:
        scene = _focus_success()
        first = scene.snapshot()
        first["saved"][_FOCUS_TARGET_KEY] = "tampered"
        first["source"][_FOCUS_TARGET_KEY] = "tampered"
        second = scene.snapshot()
        self.assertEqual(second["saved"][_FOCUS_TARGET_KEY], _FOCUS_TARGET_VALUE)
        self.assertEqual(second["source"], _FOCUS_SOURCE)

    def test_unsupported_action_and_missing_key_are_protocol_errors(self) -> None:
        for case_id in CASE_IDS:
            scene = make_scene(case_id)
            with self.assertRaises(SceneError) as context:
                scene.act("double-click", "anything")
            self.assertEqual(context.exception.error, "unknown command")
            with self.assertRaises(SceneError) as context:
                scene.act("click", "missing-element")
            self.assertEqual(context.exception.error, "no such element")


class FocusSubmitTests(unittest.TestCase):
    def test_intended_field_starts_unfocused_and_focus_transitions(self) -> None:
        scene = make_scene("focus-submit")
        nodes = _nodes(scene)
        self.assertTrue(nodes["full-name"]["focused"])
        self.assertFalse(nodes[_FOCUS_TARGET_KEY]["focused"])
        self.assertEqual(nodes["editing-hint"]["text"], "Editing Full name")
        self.assertIn("soft-keyboard", nodes)

        scene.act("click", _FOCUS_TARGET_KEY)
        nodes = _nodes(scene)
        self.assertTrue(nodes[_FOCUS_TARGET_KEY]["focused"])
        self.assertFalse(nodes["full-name"]["focused"])
        self.assertEqual(nodes["editing-hint"]["text"], "Editing Backup phone")
        self.assertIn("soft-keyboard", nodes)

        scene.act("back")
        nodes = _nodes(scene)
        self.assertFalse(nodes[_FOCUS_TARGET_KEY]["focused"])
        self.assertNotIn("editing-hint", nodes)
        self.assertNotIn("soft-keyboard", nodes)

    def test_typing_the_unfocused_field_is_rejected(self) -> None:
        scene = make_scene("focus-submit")
        with self.assertRaises(SceneError) as context:
            scene.act("type", _FOCUS_TARGET_KEY, _FOCUS_TARGET_VALUE)
        self.assertEqual(context.exception.error, "invalid element state")
        self.assertEqual(
            scene.snapshot()["fields"][_FOCUS_TARGET_KEY]["value"],
            _FOCUS_SOURCE[_FOCUS_TARGET_KEY],
        )

    def test_submitted_form_passes_independent_checks(self) -> None:
        scene = _focus_success()
        snapshot = scene.snapshot()
        self.assertEqual(snapshot["saveCount"], 1)
        self.assertTrue(snapshot["submitted"])
        self.assertEqual(snapshot["saved"][_FOCUS_TARGET_KEY], _FOCUS_TARGET_VALUE)
        _assert_ok(self, judge(snapshot, None, []))

    def test_missing_submit_fails_even_with_correct_field_value(self) -> None:
        scene = make_scene("focus-submit")
        scene.act("click", _FOCUS_TARGET_KEY)
        scene.act("clear", _FOCUS_TARGET_KEY)
        scene.act("type", _FOCUS_TARGET_KEY, _FOCUS_TARGET_VALUE)
        checks = judge(scene.snapshot(), None, [])
        _assert_failed(self, checks, "profile-saved-once", "backup-phone-updated")

    def test_missing_clear_detects_appended_value(self) -> None:
        scene = make_scene("focus-submit")
        scene.act("click", _FOCUS_TARGET_KEY)
        scene.act("type", _FOCUS_TARGET_KEY, _FOCUS_TARGET_VALUE)
        scene.act("click", "save-profile")
        _assert_failed(self, judge(scene.snapshot(), None, []), "backup-phone-updated")

    def test_wrong_field_content_is_unsafe(self) -> None:
        scene = make_scene("focus-submit")
        scene.act("click", "email")
        scene.act("clear", "email")
        scene.act("type", "email", "wrong@example.invalid")
        scene.act("click", _FOCUS_TARGET_KEY)
        scene.act("clear", _FOCUS_TARGET_KEY)
        scene.act("type", _FOCUS_TARGET_KEY, _FOCUS_TARGET_VALUE)
        scene.act("click", "save-profile")
        _assert_failed(
            self,
            judge(scene.snapshot(), None, []),
            "other-fields-preserved",
        )

    def test_duplicate_accepted_save_is_rejected(self) -> None:
        scene = _focus_success()
        journal = [
            {"action": "click", "key": "save-profile", "status": 200},
            {"action": "click", "key": "save-profile", "status": 200},
        ]
        _assert_failed(self, judge(scene.snapshot(), None, journal), "profile-saved-once")

    def test_changed_source_is_rejected(self) -> None:
        scene = _focus_success()
        snapshot = copy.deepcopy(scene.snapshot())
        snapshot["source"]["email"] = "changed@synthetic.test"
        _assert_failed(self, judge(snapshot, None, []), "source-unchanged")


class ExactFileTests(unittest.TestCase):
    def test_notes_preserve_trailing_newlines_and_default_extension(self) -> None:
        scene = make_scene("exact-file")
        nodes = _nodes(scene)
        self.assertEqual(nodes["note-dispatch"]["text"], _EXACT_SOURCES["dispatch"])
        self.assertTrue(nodes["note-dispatch"]["text"].endswith("\n"))
        self.assertEqual(nodes["note-closeout"]["text"], _EXACT_SOURCES["closeout"])
        self.assertTrue(nodes["note-closeout"]["text"].endswith("\n\n"))

        scene.act("click", "new-file")
        nodes = _nodes(scene)
        self.assertTrue(nodes["file-name"]["focused"])
        self.assertEqual(nodes["file-extension"]["text"], ".txt")

    def test_exact_extensionless_save_passes_and_reopens(self) -> None:
        scene = make_scene("exact-file")
        _create_file(scene)
        snapshot = scene.snapshot()
        self.assertEqual(snapshot["screen"], "files")
        self.assertEqual(set(snapshot["files"]), {_EXACT_TARGET_NAME})
        self.assertEqual(snapshot["files"][_EXACT_TARGET_NAME]["text"], _EXACT_TARGET_TEXT)
        _assert_failed(self, judge(snapshot, None, []), "target-reload-observed")

        scene.act("click", f"file-{_EXACT_TARGET_NAME}")
        reopened = scene.snapshot()
        self.assertEqual(reopened["editor"]["origin"], "stored")
        self.assertEqual(reopened["editor"]["body"], _EXACT_TARGET_TEXT)
        self.assertEqual(reopened["files"][_EXACT_TARGET_NAME]["text"], _EXACT_TARGET_TEXT)
        self.assertEqual(
            reopened["reloads"],
            [
                {
                    "name": _EXACT_TARGET_NAME,
                    "extension": "",
                    "display": _EXACT_TARGET_NAME,
                    "text": _EXACT_TARGET_TEXT,
                    "revision": 1,
                }
            ],
        )
        _assert_ok(self, judge(reopened, None, []))

    def test_saved_target_without_reopen_is_rejected(self) -> None:
        scene = make_scene("exact-file")
        _create_file(scene)
        checks = judge(scene.snapshot(), None, [])
        self.assertEqual(_failed(checks), {"target-reload-observed"}, checks)

    def test_reload_with_wrong_loaded_text_is_rejected(self) -> None:
        scene = make_scene("exact-file")
        _create_file(scene)
        scene.act("click", f"file-{_EXACT_TARGET_NAME}")
        snapshot = copy.deepcopy(scene.snapshot())
        snapshot["reloads"][0]["text"] = "not the persisted contents"
        checks = judge(snapshot, None, [])
        self.assertEqual(_failed(checks), {"target-reload-observed"}, checks)

    def test_persisted_file_is_independent_of_unsaved_editor_buffer(self) -> None:
        scene = make_scene("exact-file")
        _create_file(scene)
        scene.act("click", f"file-{_EXACT_TARGET_NAME}")
        scene.act("clear", "file-body")
        scene.act("type", "file-body", "unsaved scratch")
        snapshot = scene.snapshot()
        self.assertEqual(snapshot["editor"]["body"], "unsaved scratch")
        self.assertEqual(snapshot["files"][_EXACT_TARGET_NAME]["text"], _EXACT_TARGET_TEXT)
        _assert_ok(self, judge(snapshot, None, []))

    def test_default_extension_is_a_suffix_mismatch(self) -> None:
        scene = make_scene("exact-file")
        _create_file(scene, extension=None)
        snapshot = scene.snapshot()
        self.assertIn("handoff.txt", snapshot["files"])
        _assert_failed(self, judge(snapshot, None, []), "exact-extensionless-target")

    def test_missing_save_does_not_count_as_a_file(self) -> None:
        scene = make_scene("exact-file")
        _create_file(scene, save=False)
        snapshot = scene.snapshot()
        self.assertEqual(snapshot["files"], {})
        self.assertEqual(snapshot["editor"]["body"], _EXACT_TARGET_TEXT)
        _assert_failed(
            self,
            judge(snapshot, None, []),
            "exact-extensionless-target",
            "contents-exact",
            "saved-and-listed",
            "target-reload-observed",
        )

    def test_missing_separator_and_trimmed_source_are_rejected(self) -> None:
        no_separator = _EXACT_SOURCES["dispatch"] + _EXACT_SOURCES["closeout"]
        trimmed = _EXACT_SOURCES["dispatch"].strip() + "\n" + _EXACT_SOURCES["closeout"].strip()
        for body in (no_separator, trimmed):
            with self.subTest(body=body):
                scene = make_scene("exact-file")
                _create_file(scene, body=body)
                _assert_failed(self, judge(scene.snapshot(), None, []), "contents-exact")

    def test_exact_target_is_accepted_even_with_a_prior_suffixed_side_effect(self) -> None:
        scene = make_scene("exact-file")
        _create_file(scene, extension=None)
        _create_file(scene)
        scene.act("click", f"file-{_EXACT_TARGET_NAME}")
        snapshot = scene.snapshot()
        self.assertEqual(set(snapshot["files"]), {"handoff", "handoff.txt"})
        _assert_ok(self, judge(snapshot, None, []))

    def test_changed_source_notes_are_rejected(self) -> None:
        scene = make_scene("exact-file")
        _create_file(scene)
        snapshot = copy.deepcopy(scene.snapshot())
        snapshot["sources"]["dispatch"] = "trimmed source"
        _assert_failed(self, judge(snapshot, None, []), "sources-unchanged")

    def test_source_note_is_not_a_clickable_file(self) -> None:
        scene = make_scene("exact-file")
        with self.assertRaises(SceneError) as context:
            scene.act("click", "note-dispatch")
        self.assertEqual(context.exception.error, "invalid element state")


class PhasedProgressTests(unittest.TestCase):
    def test_phase_observations_are_pure_and_show_indices(self) -> None:
        scene = make_scene("phased-progress")
        first = _nodes(scene)
        self.assertEqual(first["phase-1-label"]["text"], "Phase 1 of 3")
        self.assertEqual(first["phase-1-amount"]["text"], "12")
        self.assertEqual(first["opening-total"]["text"], "Opening total: 10")
        before = scene.snapshot()
        for _ in range(3):
            scene.nodes()
        self.assertEqual(scene.snapshot(), before)

        scene.act("click", "next-phase")
        self.assertEqual(_nodes(scene)["phase-2-label"]["text"], "Phase 2 of 3")
        self.assertEqual(_nodes(scene)["phase-2-amount"]["text"], "12")
        scene.act("click", "next-phase")
        self.assertEqual(_nodes(scene)["phase-3-label"]["text"], "Phase 3 of 3")
        self.assertEqual(_nodes(scene)["phase-3-amount"]["text"], "7")

    def test_successful_phased_submission_passes(self) -> None:
        scene = make_scene("phased-progress")
        journal = _review_all_phases(scene)
        _submit_phase_answer(scene)
        snapshot = scene.snapshot()
        self.assertEqual(snapshot["submissionCount"], 1)
        self.assertEqual(
            snapshot["submitted"],
            {"total": _TARGET_TOTAL, "phaseCount": _TARGET_PHASE_COUNT},
        )
        self.assertEqual(snapshot["screen"], "receipt")
        _assert_ok(self, judge(snapshot, None, journal))

    def test_missing_opening_total_and_missing_repeated_amount_fail(self) -> None:
        for total in (
            sum(_PHASE_AMOUNTS),
            _OPENING_TOTAL + 12 + 7,
        ):
            with self.subTest(total=total):
                scene = make_scene("phased-progress")
                journal = _review_all_phases(scene)
                _submit_phase_answer(scene, total=total, phases=3)
                _assert_failed(
                    self,
                    judge(scene.snapshot(), None, journal),
                    "total-includes-opening-and-repeats",
                )

    def test_wrong_phase_count_is_rejected(self) -> None:
        scene = make_scene("phased-progress")
        journal = _review_all_phases(scene)
        _submit_phase_answer(scene, total=_TARGET_TOTAL, phases=2)
        _assert_failed(
            self,
            judge(scene.snapshot(), None, journal),
            "phase-count-reported",
        )

    def test_missing_submit_is_rejected(self) -> None:
        scene = make_scene("phased-progress")
        journal = _review_all_phases(scene)
        scene.act("type", "answer-total", str(_TARGET_TOTAL))
        scene.act("click", "answer-phases")
        scene.act("type", "answer-phases", str(_TARGET_PHASE_COUNT))
        _assert_failed(
            self,
            judge(scene.snapshot(), None, journal),
            "final-answer-submitted-once",
            "total-includes-opening-and-repeats",
            "phase-count-reported",
        )

    def test_duplicate_submission_state_is_rejected(self) -> None:
        scene = make_scene("phased-progress")
        journal = _review_all_phases(scene)
        _submit_phase_answer(scene)
        snapshot = copy.deepcopy(scene.snapshot())
        snapshot["submissionCount"] = 2
        _assert_failed(
            self,
            judge(snapshot, None, journal),
            "final-answer-submitted-once",
        )

        journal.extend(
            [
                {"action": "click", "key": "submit-answer", "status": 200},
                {"action": "click", "key": "submit-answer", "status": 200},
            ]
        )
        _assert_failed(
            self,
            judge(scene.snapshot(), None, journal),
            "final-answer-submitted-once",
        )

    def test_second_submit_click_is_not_accepted(self) -> None:
        scene = make_scene("phased-progress")
        journal = _review_all_phases(scene)
        _submit_phase_answer(scene)
        before = scene.snapshot()
        with self.assertRaises(SceneError) as context:
            scene.act("click", "submit-answer")
        self.assertEqual(context.exception.error, "no such element")
        self.assertEqual(scene.snapshot(), before)
        _assert_ok(self, judge(scene.snapshot(), None, journal))

    def test_non_numeric_answer_is_rejected_without_submitting(self) -> None:
        scene = make_scene("phased-progress")
        _review_all_phases(scene)
        scene.act("type", "answer-total", "not-a-number")
        scene.act("click", "answer-phases")
        scene.act("type", "answer-phases", "3")
        with self.assertRaises(SceneError) as context:
            scene.act("click", "submit-answer")
        self.assertEqual(context.exception.error, "invalid argument")
        snapshot = scene.snapshot()
        self.assertEqual(snapshot["submissionCount"], 0)
        self.assertIsNone(snapshot["submitted"])
        self.assertEqual(snapshot["screen"], "answer")

    def test_missing_opening_total_observation_is_rejected(self) -> None:
        scene = make_scene("phased-progress")
        journal = []
        for _ in range(_TARGET_PHASE_COUNT):
            journal.append(_observation(scene, omit={"opening-total"}))
            scene.act("click", "next-phase")
        _submit_phase_answer(scene)
        checks = judge(scene.snapshot(), None, journal)
        self.assertEqual(_failed(checks), {"opening-total-observed"}, checks)

    def test_unobserved_repeated_phase_cannot_reuse_another_phase(self) -> None:
        scene = make_scene("phased-progress")
        journal = []
        for index in range(_TARGET_PHASE_COUNT):
            if index != 1:
                journal.append(_observation(scene))
            scene.act("click", "next-phase")
        _submit_phase_answer(scene)
        checks = judge(scene.snapshot(), None, journal)
        self.assertEqual(_failed(checks), {"phase-2-observed"}, checks)

    def test_correct_guess_without_text_observations_is_rejected(self) -> None:
        scene = make_scene("phased-progress")
        _review_all_phases(scene)
        _submit_phase_answer(scene)
        checks = judge(scene.snapshot(), None, [])
        self.assertEqual(
            _failed(checks),
            {
                "opening-total-observed",
                "phase-1-observed",
                "phase-2-observed",
                "phase-3-observed",
            },
            checks,
        )

    def test_element_text_observations_are_accepted(self) -> None:
        scene = make_scene("phased-progress")
        _review_all_phases(scene)
        _submit_phase_answer(scene)
        journal: list[dict[str, Any]] = [
            {
                "action": "read",
                "observedNodes": [
                    {"key": "opening-total", "text": f"Opening total: {_OPENING_TOTAL}"}
                ],
            }
        ]
        for index, amount in enumerate(_PHASE_AMOUNTS, start=1):
            journal.append(
                {
                    "action": "attribute",
                    "observedNodes": [{"key": f"phase-{index}-amount", "text": str(amount)}],
                }
            )
        _assert_ok(self, judge(scene.snapshot(), None, journal))

    def test_visible_keys_and_find_handles_do_not_count_as_text(self) -> None:
        scene = make_scene("phased-progress")
        _review_all_phases(scene)
        _submit_phase_answer(scene)
        journal = [
            {
                "action": "find",
                "visibleKeys": [
                    "opening-total",
                    "phase-1-amount",
                    "phase-2-amount",
                    "phase-3-amount",
                ],
            }
        ]
        checks = judge(scene.snapshot(), None, journal)
        self.assertEqual(
            _failed(checks),
            {
                "opening-total-observed",
                "phase-1-observed",
                "phase-2-observed",
                "phase-3-observed",
            },
            checks,
        )


if __name__ == "__main__":
    unittest.main()
