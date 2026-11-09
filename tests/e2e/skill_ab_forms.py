"""Synthetic form and file scenes for the paired Skill development experiment.

These scenes are deliberately small, deterministic Android-shaped models used by
the loopback ``skill_ab_fixture`` transport. They contain no device, filesystem,
network, clock or benchmark integration. The Agent sees only ordinary element
observations; ``snapshot`` and the judges are test-side evidence surfaces.

The three tasks exercise a focused text edit, an exact extensionless file save,
and a phased arithmetic submission. Judges read persisted or submitted fixture
state and actual returned text observations; they never trust an Agent-authored
match flag or final prose.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

from tests.e2e.skill_ab_fixture import SceneError, node

CASE_IDS = ("focus-submit", "exact-file", "phased-progress")

_TEXT = "android.widget.TextView"
_EDIT = "android.widget.EditText"
_BUTTON = "android.widget.Button"


def _text(key: str, value: str) -> dict[str, Any]:
    return node(key, value, _TEXT)


def _button(key: str, value: str) -> dict[str, Any]:
    return node(key, value, _BUTTON, clickable=True)


def _edit(key: str, value: str, *, focused: bool = False) -> dict[str, Any]:
    return node(key, value, _EDIT, clickable=True, focused=focused)


def _require(nodes: Sequence[Mapping[str, Any]], key: str) -> Mapping[str, Any]:
    for item in nodes:
        if item.get("key") == key:
            return item
    raise SceneError("no such element", f"No visible element with key {key!r}")


def _ensure_usable(item: Mapping[str, Any], key: str) -> None:
    if item.get("enabled") is False or item.get("displayed") is False:
        raise SceneError("invalid element state", f"Element {key!r} is not enabled and visible")


def _ensure_action(action: str) -> None:
    if action not in {"click", "clear", "type", "scroll", "back"}:
        raise SceneError("unknown command", f"Unsupported synthetic action {action!r}")


def _ensure_text(value: str) -> None:
    if not isinstance(value, str):
        raise SceneError("invalid argument", "Text input must be a string")


# ---------------------------------------------------------------------------
# Focused form submission.


_FOCUS_FIELDS: tuple[tuple[str, str], ...] = (
    ("full-name", "Full name"),
    ("email", "Email"),
    ("backup-phone", "Backup phone"),
    ("office-extension", "Office extension"),
)
_FOCUS_LABELS = dict(_FOCUS_FIELDS)
_FOCUS_SOURCE = {
    "full-name": "Avery Quinn",
    "email": "avery.quinn@synthetic.test",
    "backup-phone": "555-0100",
    "office-extension": "x204",
}
_FOCUS_TARGET_KEY = "backup-phone"
_FOCUS_TARGET_VALUE = "555-0134"


class FocusSubmitScene:
    """A form where the intended field starts unfocused and another field has focus."""

    id = "focus-submit"
    goal = (
        "Update the backup contact number in the contact preferences to 555-0134, "
        "then save the form. Keep the other contact details exactly as they are."
    )
    budget = 10

    def __init__(self) -> None:
        self._values = dict(_FOCUS_SOURCE)
        self._screen = "form"
        self._focus: str | None = "full-name"
        self._keyboard = True
        self._saved: dict[str, str] | None = None
        self._save_count = 0

    def nodes(self) -> list[dict[str, Any]]:
        items = [_text("contact-title", "Contact preferences")]
        if self._screen == "form":
            for key, label in _FOCUS_FIELDS:
                items.append(_text(f"label-{key}", label))
                items.append(_edit(key, self._values[key], focused=self._focus == key))
            if self._focus is not None:
                items.append(_text("editing-hint", f"Editing {_FOCUS_LABELS[self._focus]}"))
            if self._keyboard:
                items.append(_text("soft-keyboard", "Keyboard open"))
            items.append(_button("save-profile", "Save"))
        else:
            items.append(_text("save-status", "Profile saved"))
        return items

    def act(self, action: str, key: str = "", value: str = "") -> None:
        _ensure_action(action)
        if action == "back":
            if self._screen == "form":
                self._focus = None
                self._keyboard = False
            return
        if action == "scroll":
            return
        item = _require(self.nodes(), key)
        _ensure_usable(item, key)
        if action == "click":
            if item.get("clickable") is not True:
                raise SceneError("invalid element state", f"Element {key!r} is not clickable")
            self._click(key)
            return
        self._edit(action, key, value)

    def _click(self, key: str) -> None:
        if self._screen != "form":
            raise SceneError("invalid element state", f"Element {key!r} is not actionable")
        if key in self._values:
            self._focus = key
            self._keyboard = True
            return
        if key == "save-profile":
            self._saved = dict(self._values)
            self._save_count += 1
            self._screen = "receipt"
            self._focus = None
            self._keyboard = False
            return
        raise SceneError("invalid element state", f"Element {key!r} is not actionable")

    def _edit(self, action: str, key: str, value: str) -> None:
        _ensure_text(value)
        if self._screen != "form" or key not in self._values:
            raise SceneError("invalid element state", f"Element {key!r} is not editable")
        if self._focus != key:
            raise SceneError(
                "invalid element state",
                f"Element {key!r} must be focused before it can be edited",
            )
        self._values[key] = "" if action == "clear" else self._values[key] + value
        self._keyboard = True

    def judge(
        self,
        snapshot: Mapping[str, Any],
        answer: object,
        journal: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        return judge_focus_submit(snapshot, answer, journal)

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(
            {
                "id": self.id,
                "screen": self._screen,
                "fields": {
                    key: {
                        "label": label,
                        "value": self._values[key],
                        "focused": self._focus == key,
                        "enabled": True,
                        "displayed": True,
                    }
                    for key, label in _FOCUS_FIELDS
                },
                "source": dict(_FOCUS_SOURCE),
                "saved": self._saved,
                "saveCount": self._save_count,
                "focusedKey": self._focus,
                "keyboardVisible": self._keyboard,
                "submitted": self._saved is not None,
            }
        )


def judge_focus_submit(
    snapshot: Mapping[str, Any], answer: object, journal: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Check the saved form; wrong-field edits are unsafe, not ignored."""

    saved = snapshot.get("saved")
    source = snapshot.get("source")
    saved_values = saved if isinstance(saved, Mapping) else {}
    save_count = _as_int(snapshot.get("saveCount"))
    accepted_saves = _accepted_actions(journal, "click", "save-profile")
    checks: list[dict[str, Any]] = []

    exactly_once = (
        save_count == 1
        and isinstance(saved, Mapping)
        and isinstance(source, Mapping)
        and accepted_saves <= 1
    )
    checks.append(
        {
            "id": "profile-saved-once",
            "ok": exactly_once,
            "detail": (
                f"saveCount={save_count!r}, saved={saved is not None}, "
                f"accepted-save-clicks={accepted_saves}"
            ),
        }
    )

    target = saved_values.get(_FOCUS_TARGET_KEY)
    checks.append(
        {
            "id": "backup-phone-updated",
            "ok": target == _FOCUS_TARGET_VALUE,
            "detail": f"backup-phone={target!r}",
        }
    )

    preserved = (
        isinstance(saved, Mapping)
        and set(saved) == set(_FOCUS_SOURCE)
        and all(
            saved.get(key) == value
            for key, value in _FOCUS_SOURCE.items()
            if key != _FOCUS_TARGET_KEY
        )
    )
    checks.append(
        {
            "id": "other-fields-preserved",
            "ok": preserved,
            "detail": "only the backup phone may change",
        }
    )

    checks.append(
        {
            "id": "source-unchanged",
            "ok": source == _FOCUS_SOURCE,
            "detail": "immutable contact source must match the original values",
        }
    )
    return checks


# ---------------------------------------------------------------------------
# Exact extensionless file creation.


_EXACT_SOURCES = {
    "dispatch": "Dispatch checklist\nVerify seals\n",
    "closeout": "Closeout\nNotify dock\n\n",
}
_EXACT_TARGET_NAME = "handoff"
_EXACT_TARGET_TEXT = _EXACT_SOURCES["dispatch"] + "\n" + _EXACT_SOURCES["closeout"]
_EXACT_DEFAULT_EXTENSION = ".txt"


class ExactFileScene:
    """A notes app with a name/extension dialog and a separately persisted file body."""

    id = "exact-file"
    goal = (
        "Create a text file named exactly `handoff` in the Notes folder, with no file "
        "extension. The file's contents must be the complete text of the note `Dispatch`, "
        "followed by exactly one extra newline character, followed by the complete text "
        "of the note `Closeout`. Keep both notes' existing trailing line breaks and all "
        "source notes unchanged. The saved file must appear in the file list and reopen "
        "with those exact contents."
    )
    budget = 18

    def __init__(self) -> None:
        self._screen = "sources"
        self._draft: dict[str, str] | None = None
        self._editor: dict[str, str] | None = None
        self._files: dict[str, dict[str, Any]] = {}
        self._file_order: list[str] = []
        self._open_file: str | None = None
        self._reloads: list[dict[str, Any]] = []
        self._focus: str | None = None
        self._keyboard = False
        self._save_count = 0

    def nodes(self) -> list[dict[str, Any]]:
        if self._screen == "sources":
            return self._source_nodes()
        if self._screen == "create":
            return self._create_nodes()
        if self._screen == "editor":
            return self._editor_nodes()
        return self._file_nodes()

    def _source_nodes(self) -> list[dict[str, Any]]:
        return [
            _text("notes-title", "Notes"),
            _text("note-dispatch-label", "Dispatch"),
            _text("note-dispatch", _EXACT_SOURCES["dispatch"]),
            _text("note-closeout-label", "Closeout"),
            _text("note-closeout", _EXACT_SOURCES["closeout"]),
            _button("new-file", "New file"),
            _button("files-view", "Saved files"),
        ]

    def _create_nodes(self) -> list[dict[str, Any]]:
        draft = self._draft or {"name": "", "extension": _EXACT_DEFAULT_EXTENSION}
        items = [
            _text("create-title", "New file"),
            _text("file-name-label", "File name"),
            _edit("file-name", draft["name"], focused=self._focus == "file-name"),
            _text("file-extension-label", "Extension"),
            _edit(
                "file-extension",
                draft["extension"],
                focused=self._focus == "file-extension",
            ),
            _button("create-file", "Create"),
            _button("cancel-create", "Cancel"),
        ]
        if self._keyboard:
            items.append(_text("soft-keyboard", "Keyboard open"))
        return items

    def _editor_nodes(self) -> list[dict[str, Any]]:
        editor = self._editor or {"name": "", "extension": "", "body": ""}
        display = editor["name"] + editor["extension"]
        items = [
            _text("editor-title", f"Editing {display}"),
            _text("file-body-label", "Contents"),
            _edit("file-body", editor["body"], focused=self._focus == "file-body"),
            _button("save-file", "Save"),
            _button("discard-file", "Discard"),
        ]
        if self._keyboard:
            items.append(_text("soft-keyboard", "Keyboard open"))
        return items

    def _file_nodes(self) -> list[dict[str, Any]]:
        items = [
            _text("files-title", "Saved files"),
            _button("new-file", "New file"),
            _button("back-to-notes", "Notes"),
        ]
        if not self._file_order:
            items.append(_text("files-empty", "No saved files"))
        for display in self._file_order:
            items.append(_button(_file_key(display), display))
        return items

    def act(self, action: str, key: str = "", value: str = "") -> None:
        _ensure_action(action)
        if action == "back":
            self._back()
            return
        if action == "scroll":
            return
        item = _require(self.nodes(), key)
        _ensure_usable(item, key)
        if action == "click":
            if item.get("clickable") is not True:
                raise SceneError("invalid element state", f"Element {key!r} is not clickable")
            self._click(key)
            return
        self._edit(action, key, value)

    def _click(self, key: str) -> None:
        if self._screen == "sources":
            if key == "new-file":
                self._open_dialog()
                return
            if key == "files-view":
                self._screen = "files"
                return
        elif self._screen == "create":
            if key in {"file-name", "file-extension"}:
                self._focus = key
                self._keyboard = True
                return
            if key == "create-file":
                self._create()
                return
            if key == "cancel-create":
                self._screen = "sources"
                self._draft = None
                self._focus = None
                self._keyboard = False
                return
        elif self._screen == "editor":
            if key == "file-body":
                self._focus = "file-body"
                self._keyboard = True
                return
            if key == "save-file":
                self._save()
                return
            if key == "discard-file":
                self._discard()
                return
        else:
            by_key = {_file_key(name): name for name in self._file_order}
            if key in by_key:
                self._open_file = by_key[key]
                self._load_editor(self._open_file)
                return
            if key == "new-file":
                self._open_dialog()
                return
            if key == "back-to-notes":
                self._screen = "sources"
                return
        raise SceneError("invalid element state", f"Element {key!r} is not actionable")

    def _edit(self, action: str, key: str, value: str) -> None:
        _ensure_text(value)
        if self._screen == "create" and key in {"file-name", "file-extension"}:
            if self._draft is None:
                raise SceneError("invalid element state", "No file creation dialog is active")
            if self._focus != key:
                raise SceneError(
                    "invalid element state",
                    f"Element {key!r} must be focused before it can be edited",
                )
            field = "name" if key == "file-name" else "extension"
            self._draft[field] = "" if action == "clear" else self._draft[field] + value
            self._keyboard = True
            return
        if self._screen == "editor" and key == "file-body":
            if self._editor is None:
                raise SceneError("invalid element state", "No file editor is active")
            if self._focus != key:
                raise SceneError(
                    "invalid element state",
                    f"Element {key!r} must be focused before it can be edited",
                )
            self._editor["body"] = "" if action == "clear" else self._editor["body"] + value
            self._keyboard = True
            return
        raise SceneError("invalid element state", f"Element {key!r} is not editable")

    def _open_dialog(self) -> None:
        self._draft = {"name": "", "extension": _EXACT_DEFAULT_EXTENSION}
        self._screen = "create"
        self._focus = "file-name"
        self._keyboard = True

    def _create(self) -> None:
        if self._screen != "create" or self._draft is None:
            raise SceneError("invalid element state", "No file creation dialog is active")
        name = self._draft["name"]
        extension = self._draft["extension"]
        if not name.strip():
            raise SceneError("invalid argument", "A file name is required")
        if any(character in name + extension for character in ("/", "\\", "\0")):
            raise SceneError("invalid argument", "File names may not contain path separators")
        self._editor = {
            "name": name,
            "extension": extension,
            "body": "",
            "origin": "draft",
        }
        self._draft = None
        self._screen = "editor"
        self._focus = "file-body"
        self._keyboard = True

    def _save(self) -> None:
        if self._screen != "editor" or self._editor is None:
            raise SceneError("invalid element state", "No file editor is active")
        name = self._editor["name"]
        extension = self._editor["extension"]
        display = name + extension
        revision = int(self._files.get(display, {}).get("revision", 0)) + 1
        self._files[display] = {
            "name": name,
            "extension": extension,
            "text": self._editor["body"],
            "revision": revision,
        }
        if display not in self._file_order:
            self._file_order.append(display)
        self._save_count += 1
        self._open_file = display
        self._editor = None
        self._screen = "files"
        self._focus = None
        self._keyboard = False

    def _discard(self) -> None:
        self._editor = None
        self._focus = None
        self._keyboard = False
        self._screen = "files" if self._file_order else "sources"

    def _load_editor(self, display: str) -> None:
        stored = self._files[display]
        self._reloads.append(
            {
                "name": stored["name"],
                "extension": stored["extension"],
                "display": display,
                "text": stored["text"],
                "revision": stored["revision"],
            }
        )
        self._editor = {
            "name": stored["name"],
            "extension": stored["extension"],
            "body": stored["text"],
            "origin": "stored",
        }
        self._screen = "editor"
        self._focus = "file-body"
        self._keyboard = True

    def _back(self) -> None:
        if self._screen == "create":
            self._screen = "sources"
            self._draft = None
        elif self._screen == "editor":
            self._editor = None
            self._screen = "files" if self._file_order else "sources"
        elif self._screen == "files":
            self._screen = "sources"
        self._focus = None
        self._keyboard = False

    def judge(
        self,
        snapshot: Mapping[str, Any],
        answer: object,
        journal: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        return judge_exact_file(snapshot, answer, journal)

    def snapshot(self) -> dict[str, Any]:
        editor = copy.deepcopy(self._editor)
        if editor is not None:
            editor["display"] = editor["name"] + editor["extension"]
        return copy.deepcopy(
            {
                "id": self.id,
                "screen": self._screen,
                "sources": dict(_EXACT_SOURCES),
                "files": self._files,
                "fileOrder": list(self._file_order),
                "openFile": self._open_file,
                "reloads": list(self._reloads),
                "editor": editor,
                "saveCount": self._save_count,
                "focusedKey": self._focus,
                "keyboardVisible": self._keyboard,
            }
        )


def _file_key(display: str) -> str:
    return f"file-{display}"


def judge_exact_file(
    snapshot: Mapping[str, Any], answer: object, journal: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Check the persisted file, not the editor's unsaved buffer."""

    files = snapshot.get("files")
    by_name = files if isinstance(files, Mapping) else {}
    target = by_name.get(_EXACT_TARGET_NAME)
    target_file = target if isinstance(target, Mapping) else {}
    order = snapshot.get("fileOrder")
    listed = order if isinstance(order, list) else []
    save_count = _as_int(snapshot.get("saveCount"))
    reloads = snapshot.get("reloads")
    reload_detail = "no persisted target reload"
    reload_ok = False
    if isinstance(reloads, list):
        for item in reloads:
            if not isinstance(item, Mapping):
                continue
            is_target = item.get("display") == _EXACT_TARGET_NAME or (
                item.get("name") == _EXACT_TARGET_NAME and item.get("extension") == ""
            )
            if not is_target:
                continue
            reload_detail = f"loaded={item.get('display')!r}, revision={item.get('revision')!r}"
            if item.get("text") == _EXACT_TARGET_TEXT:
                reload_ok = True
                break

    checks = [
        {
            "id": "exact-extensionless-target",
            "ok": (
                _EXACT_TARGET_NAME in by_name
                and target_file.get("name") == _EXACT_TARGET_NAME
                and target_file.get("extension") == ""
            ),
            "detail": f"files={sorted(str(name) for name in by_name)}",
        },
        {
            "id": "contents-exact",
            "ok": target_file.get("text") == _EXACT_TARGET_TEXT,
            "detail": "complete source texts plus exactly one separator newline",
        },
        {
            "id": "saved-and-listed",
            "ok": (
                save_count is not None
                and save_count >= 1
                and _EXACT_TARGET_NAME in listed
                and isinstance(target_file.get("revision"), int)
                and target_file["revision"] >= 1
            ),
            "detail": f"saveCount={save_count!r}, fileOrder={listed!r}",
        },
        {
            "id": "target-reload-observed",
            "ok": reload_ok,
            "detail": reload_detail,
        },
        {
            "id": "sources-unchanged",
            "ok": snapshot.get("sources") == _EXACT_SOURCES,
            "detail": "immutable source notes must match the originals",
        },
    ]
    return checks


# ---------------------------------------------------------------------------
# Phased arithmetic and a single irreversible final submission.


_PHASE_AMOUNTS: tuple[int, ...] = (12, 12, 7)
_OPENING_TOTAL = 10
_TARGET_TOTAL = _OPENING_TOTAL + sum(_PHASE_AMOUNTS)
_TARGET_PHASE_COUNT = len(_PHASE_AMOUNTS)
_PHASE_FIELDS = {
    "answer-total": "Total",
    "answer-phases": "Phases reviewed",
}


class PhasedProgressScene:
    """A one-way phase review followed by one final answer form."""

    id = "phased-progress"
    goal = (
        "Observe the opening total and the displayed amount in each of the three "
        "receipt phases as you review them, then submit one final answer. The final "
        "total is the opening total plus every phase amount, counting repeated "
        "amounts once per phase. Also report how many phases you reviewed. Submit "
        "the numeric total and phase count exactly once; the final answer cannot "
        "be changed."
    )
    budget = 12

    def __init__(self) -> None:
        self._screen = "progress"
        self._index = 0
        self._visited = [1]
        self._answers = {key: "" for key in _PHASE_FIELDS}
        self._focus: str | None = None
        self._keyboard = False
        self._submitted: dict[str, int] | None = None
        self._submission_count = 0

    def nodes(self) -> list[dict[str, Any]]:
        if self._screen == "progress":
            return self._progress_nodes()
        if self._screen == "answer":
            return self._answer_nodes()
        return [
            _text("receipt-title", "Answer submitted"),
            _text("receipt-status", "Final answer recorded."),
        ]

    def _progress_nodes(self) -> list[dict[str, Any]]:
        current = self._index + 1
        more = self._index < len(_PHASE_AMOUNTS) - 1
        return [
            _text("review-title", "Receipt review"),
            _text(
                f"phase-{current}-label",
                f"Phase {current} of {_TARGET_PHASE_COUNT}",
            ),
            _text("opening-total", f"Opening total: {_OPENING_TOTAL}"),
            _text(f"phase-{current}-amount-label", "Amount"),
            _text(f"phase-{current}-amount", str(_PHASE_AMOUNTS[self._index])),
            _button("next-phase", "Next phase" if more else "Continue to answer"),
        ]

    def _answer_nodes(self) -> list[dict[str, Any]]:
        items = [
            _text("answer-title", "Final answer"),
            _text("answer-note", "This submission is final."),
        ]
        for key, label in _PHASE_FIELDS.items():
            items.append(_text(f"{key}-label", label))
            items.append(_edit(key, self._answers[key], focused=self._focus == key))
        items.append(_button("submit-answer", "Submit"))
        if self._keyboard:
            items.append(_text("soft-keyboard", "Keyboard open"))
        return items

    def act(self, action: str, key: str = "", value: str = "") -> None:
        _ensure_action(action)
        if action == "back":
            self._back()
            return
        if action == "scroll":
            return
        item = _require(self.nodes(), key)
        _ensure_usable(item, key)
        if action == "click":
            if item.get("clickable") is not True:
                raise SceneError("invalid element state", f"Element {key!r} is not clickable")
            self._click(key)
            return
        self._edit(action, key, value)

    def _click(self, key: str) -> None:
        if self._screen == "progress" and key == "next-phase":
            if self._index < len(_PHASE_AMOUNTS) - 1:
                self._index += 1
                phase = self._index + 1
                if phase not in self._visited:
                    self._visited.append(phase)
                self._visited.sort()
                self._focus = None
                self._keyboard = False
                return
            self._screen = "answer"
            self._focus = "answer-total"
            self._keyboard = True
            return
        if self._screen == "answer":
            if key in _PHASE_FIELDS:
                self._focus = key
                self._keyboard = True
                return
            if key == "submit-answer":
                self._submit()
                return
        raise SceneError("invalid element state", f"Element {key!r} is not actionable")

    def _edit(self, action: str, key: str, value: str) -> None:
        _ensure_text(value)
        if self._screen != "answer" or key not in _PHASE_FIELDS:
            raise SceneError("invalid element state", f"Element {key!r} is not editable")
        if self._focus != key:
            raise SceneError(
                "invalid element state",
                f"Element {key!r} must be focused before it can be edited",
            )
        self._answers[key] = "" if action == "clear" else self._answers[key] + value
        self._keyboard = True

    def _submit(self) -> None:
        if self._screen != "answer":
            raise SceneError("invalid element state", "The answer form is not active")
        if not all(self._answers[key].strip() for key in _PHASE_FIELDS):
            raise SceneError("invalid element state", "Both answer fields are required")
        try:
            total = int(self._answers["answer-total"].strip())
            phase_count = int(self._answers["answer-phases"].strip())
        except ValueError as error:
            raise SceneError("invalid argument", "Both answers must be integers") from error
        self._submitted = {"total": total, "phaseCount": phase_count}
        self._submission_count += 1
        self._screen = "receipt"
        self._focus = None
        self._keyboard = False

    def _back(self) -> None:
        if self._screen == "answer":
            self._screen = "progress"
            self._focus = None
            self._keyboard = False
        elif self._screen == "progress" and self._index > 0:
            self._index -= 1
            self._focus = None
            self._keyboard = False

    def judge(
        self,
        snapshot: Mapping[str, Any],
        answer: object,
        journal: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        return judge_phased_progress(snapshot, answer, journal)

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(
            {
                "id": self.id,
                "screen": self._screen,
                "phaseIndex": self._index,
                "phaseCount": _TARGET_PHASE_COUNT,
                "openingTotal": _OPENING_TOTAL,
                "phases": [
                    {"index": index + 1, "amount": amount}
                    for index, amount in enumerate(_PHASE_AMOUNTS)
                ],
                "visitedPhases": list(self._visited),
                "answers": dict(self._answers),
                "submitted": self._submitted,
                "submissionCount": self._submission_count,
                "focusedKey": self._focus,
                "keyboardVisible": self._keyboard,
            }
        )


def judge_phased_progress(
    snapshot: Mapping[str, Any], answer: object, journal: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Check submitted values plus actual opening/phase text observations."""

    submitted = snapshot.get("submitted")
    values = submitted if isinstance(submitted, Mapping) else {}
    submission_count = _as_int(snapshot.get("submissionCount"))
    accepted_submits = _accepted_actions(journal, "click", "submit-answer")
    observed = set(_observed_text_pairs(journal))

    checks = [
        {
            "id": "final-answer-submitted-once",
            "ok": (
                submission_count == 1 and isinstance(submitted, Mapping) and accepted_submits <= 1
            ),
            "detail": (
                f"submissionCount={submission_count!r}, accepted-submit-clicks={accepted_submits}"
            ),
        },
        {
            "id": "total-includes-opening-and-repeats",
            "ok": _as_int(values.get("total")) == _TARGET_TOTAL,
            "detail": f"submitted-total={values.get('total')!r}",
        },
        {
            "id": "phase-count-reported",
            "ok": _as_int(values.get("phaseCount")) == _TARGET_PHASE_COUNT,
            "detail": f"submitted-phase-count={values.get('phaseCount')!r}",
        },
        {
            "id": "opening-total-observed",
            "ok": ("opening-total", f"Opening total: {_OPENING_TOTAL}") in observed,
            "detail": "requires actual displayed opening-total text",
        },
    ]
    for index, amount in enumerate(_PHASE_AMOUNTS, start=1):
        key = f"phase-{index}-amount"
        checks.append(
            {
                "id": f"phase-{index}-observed",
                "ok": (key, str(amount)) in observed,
                "detail": f"requires actual displayed {key} text",
            }
        )
    return checks


# ---------------------------------------------------------------------------
# Shared judge dispatch.


def _observed_text_pairs(journal: Sequence[Mapping[str, Any]]) -> list[tuple[str, str]]:
    """Return only text actually returned by source or element-text reads."""

    pairs: list[tuple[str, str]] = []
    for entry in journal or ():
        if not isinstance(entry, Mapping):
            continue
        observed = entry.get("observedNodes")
        if isinstance(observed, Mapping):
            for key, payload in observed.items():
                if not isinstance(key, str):
                    continue
                if isinstance(payload, Mapping) and isinstance(payload.get("text"), str):
                    pairs.append((key, payload["text"]))
                elif isinstance(payload, str):
                    pairs.append((key, payload))
        elif isinstance(observed, Sequence) and not isinstance(observed, (str, bytes)):
            for item in observed:
                if isinstance(item, Mapping):
                    key = item.get("key")
                    text = item.get("text")
                    if isinstance(key, str) and isinstance(text, str):
                        pairs.append((key, text))
                elif (
                    isinstance(item, (list, tuple))
                    and len(item) >= 2
                    and isinstance(item[0], str)
                    and isinstance(item[1], str)
                ):
                    pairs.append((item[0], item[1]))
        key = entry.get("observedKey")
        text = entry.get("observedText")
        if isinstance(key, str) and isinstance(text, str):
            pairs.append((key, text))
    return pairs


JUDGES = {
    FocusSubmitScene.id: judge_focus_submit,
    ExactFileScene.id: judge_exact_file,
    PhasedProgressScene.id: judge_phased_progress,
}


def make_scene(case_id: str) -> Any:
    scenes = {
        FocusSubmitScene.id: FocusSubmitScene,
        ExactFileScene.id: ExactFileScene,
        PhasedProgressScene.id: PhasedProgressScene,
    }
    try:
        return scenes[case_id]()
    except KeyError as error:
        raise ValueError(f"unknown synthetic case id: {case_id!r}") from error


def judge(
    snapshot: Mapping[str, Any], answer: object, journal: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Dispatch the independent oracle from the scene identity in ``snapshot``."""

    case_id = snapshot.get("id") if isinstance(snapshot, Mapping) else None
    checker = JUDGES.get(case_id) if isinstance(case_id, str) else None
    if checker is None:
        return [
            {
                "id": "known-scene",
                "ok": False,
                "detail": f"snapshot case id={case_id!r} is not one of {CASE_IDS!r}",
            }
        ]
    return checker(snapshot, answer, journal)


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
            return int(text)
    return None


def _accepted_actions(journal: Sequence[Mapping[str, Any]], action: str, key: str) -> int:
    accepted = 0
    for entry in journal or ():
        if not isinstance(entry, Mapping):
            continue
        if entry.get("action") != action or entry.get("key") != key:
            continue
        status = entry.get("status")
        if isinstance(status, bool):
            continue
        if isinstance(status, int) and 200 <= status < 300:
            accepted += 1
        elif isinstance(status, str) and status.strip().isdigit():
            code = int(status.strip())
            if 200 <= code < 300:
                accepted += 1
    return accepted
