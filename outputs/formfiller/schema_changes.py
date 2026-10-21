"""Reconcile reviewed answers by unique question title, never by position."""
from copy import deepcopy

from .browser import BrowserError, answer_plan


def reconcile(form, observed, day):
    try:
        return _reconcile(form, observed, day)
    except (KeyError, TypeError, ValueError, AttributeError):
        raise BrowserError("SCHEMA_REVIEW_REQUIRED") from None


def _reconcile(form, observed, day):
    if observed == form["schema"]:
        return form, False
    prior = form["schema"]["questions"]
    current = observed.get("questions", [])
    titles = [q["title"] for q in prior]
    new_titles = [q["title"] for q in current]
    if (not current or len(set(titles)) != len(titles) or len(set(new_titles)) != len(new_titles)):
        raise BrowserError("SCHEMA_REVIEW_REQUIRED")
    by_title = {q["title"]: (q, a) for q, a in zip(prior, form["answers"])}
    answers = []
    for question in current:
        match = by_title.get(question["title"])
        if match is None:
            if question.get("required"):
                raise BrowserError("SCHEMA_REVIEW_REQUIRED")
            answers.append({"kind": "skip"})
            continue
        old, answer = match
        answer = deepcopy(answer)
        if old != question:
            # Only option additions/removals are reconciled automatically. Changes
            # to labels on text/date inputs, requiredness, or control types need review.
            if old.get("required") != question.get("required"):
                raise BrowserError("SCHEMA_REVIEW_REQUIRED")
            kind = answer.get("kind")
            control_kind = "checkbox" if kind == "checkbox" else "radio"
            if kind not in ("radio", "checkbox", "matrix") or any(
                    c.get("kind") != control_kind for c in old["controls"] + question["controls"]):
                raise BrowserError("SCHEMA_REVIEW_REQUIRED")
            old_controls = {c["label"]: c for c in old["controls"]}
            new_controls = {c["label"]: c for c in question["controls"]}
            if len(old_controls) != len(old["controls"]) or len(new_controls) != len(question["controls"]):
                raise BrowserError("SCHEMA_REVIEW_REQUIRED")
            if any(old_controls[label] != new_controls[label] for label in old_controls.keys() & new_controls.keys()):
                raise BrowserError("SCHEMA_REVIEW_REQUIRED")
            answer["values"] = [value for value in answer.get("values", []) if value in new_controls]
            if not answer["values"]:
                if question.get("required"):
                    raise BrowserError("SCHEMA_REVIEW_REQUIRED")
                answer = {"kind": "skip"}
        answers.append(answer)
    result = {**form, "schema": observed, "answers": answers}
    answer_plan(result, day)  # Required matrices must still have every row answered.
    return result, True
