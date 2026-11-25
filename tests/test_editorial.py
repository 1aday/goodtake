import copy

import pytest

from goodtake.editorial import excerpt, review_candidates, select, verified_blockers


def choice(a=0, b=30, title="A complete first thought"):
    return {
        "start_word": a,
        "end_word": b,
        "title": title,
        "takeaway": "Keep the thought intact.",
        "reason": "It contains a complete idea.",
        "post": "Original speech, complete idea.",
    }


def test_review_requires_evidence_inside_this_numbered_excerpt():
    excerpts = [{"clip": 1, "actual_selected_text": "This thought is complete."}]
    with pytest.raises(ValueError, match="outside"):
        verified_blockers(
            {"blockers": [{"clip": 1, "code": "incomplete_ending", "evidence": "What happens next?"}]},
            excerpts,
        )
    with pytest.raises(ValueError, match="outside"):
        verified_blockers(
            {"blockers": [{"clip": 2, "code": "missing_payoff", "evidence": "thought"}]}, excerpts
        )


def test_optional_pacing_notes_never_block_an_export():
    rejected, issues, notes = review_candidates(
        lambda *args: {"blockers": [], "notes": ["For polish: tighten the hook."]},
        [{"clip": 1, "actual_selected_text": "A complete idea."}],
        [],
    )
    assert not rejected and not issues and notes


def test_invalid_reviewer_gets_one_bounded_evidence_repair():
    calls = []

    def provider(*args):
        calls.append(copy.deepcopy(args[1]))
        return {
            "blockers": [
                {"clip": 1, "code": "missing_payoff", "evidence": "not in this excerpt", "reason": "bad"}
            ],
            "notes": [],
        }

    with pytest.raises(RuntimeError, match="source evidence"):
        review_candidates(provider, [{"clip": 1, "actual_selected_text": "A complete idea."}], [])
    assert len(calls) == 2
    assert "correction" in calls[1]


def test_real_selection_loop_preserves_an_approved_range_and_copy(store, project):
    settings = store.settings()
    settings.clips_per_episode = 2
    store.save_settings(settings)
    stages = []

    def provider(instructions, payload, schema, stage):
        stages.append(stage)
        if stage == "selection":
            if stages.count("selection") == 1:
                return {"clips": [choice(), choice(60, 90, "The second complete thought")]}
            return {
                "clips": [
                    choice(120, 150, "Do not replace the approved thought"),
                    choice(180, 210, "A better second thought"),
                ]
            }
        if stages.count("editorial_review") == 1:
            return {
                "blockers": [
                    {"clip": 2, "code": "missing_payoff", "evidence": "word60", "reason": "No payoff"}
                ],
                "notes": [],
            }
        assert [c["clip"] for c in payload["clips_to_review"]] == [2]
        assert payload["already_approved"][0]["title"] == "A complete first thought"
        return {"blockers": [], "notes": []}

    select(store, project["id"], call=provider)
    clips = store.get(project["id"])["clips"]
    assert len(clips) == 2
    assert clips[0]["title"] == "A complete first thought" and clips[0]["start"] == 0
    assert clips[1]["start"] == 180


def test_accepted_work_survives_a_later_provider_failure(store, project):
    def provider(instructions, payload, schema, stage):
        if stage == "selection" and not payload["already_approved"]:
            return {"clips": [choice(), choice(60, 90), choice(120, 150)]}
        if stage == "selection":
            raise RuntimeError("Provider unavailable")
        return {
            "blockers": [
                {"clip": n, "code": "missing_payoff", "evidence": f"word{a}", "reason": "bad"}
                for n, a in [(2, 60), (3, 120)]
            ],
            "notes": [],
        }

    with pytest.raises(RuntimeError, match="unavailable"):
        select(store, project["id"], call=provider)
    saved = store.get(project["id"])["clips"]
    assert len(saved) == 1 and saved[0]["start"] == 0


def test_retries_do_not_select_existing_ranges(store, project, clip):
    settings = store.settings()
    settings.clips_per_episode = 2
    store.save_settings(settings)
    count = 0

    def provider(instructions, payload, schema, stage):
        nonlocal count
        if stage == "selection":
            count += 1
            return {"clips": [choice() if count == 1 else choice(90, 120)]}
        return {"blockers": [], "notes": []}

    select(store, project["id"], call=provider)
    assert len(store.get(project["id"])["clips"]) == 2
    assert store.get(project["id"])["clips"][1]["start"] == 90


def test_word_padding_is_continuous_and_stays_inside_source(project):
    start, end, words = excerpt({"start": 20, "end": 50.6}, project["words"], 300)
    assert start <= 20 and end >= 50.6
    assert words[0]["text"] == "word20." and words[-1]["text"] == "word50."
    assert all(word["start"] >= 0 for word in words)


def test_empty_or_overlong_excerpt_is_rejected(project):
    with pytest.raises(ValueError):
        excerpt({"start": 10.7, "end": 10.9}, project["words"], 300)
    with pytest.raises(ValueError):
        excerpt({"start": 0, "end": 250}, project["words"], 300)
