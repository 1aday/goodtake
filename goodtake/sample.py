"""An explicitly synthetic, bundled sample. Loading it never calls an API."""

from pathlib import Path

from .media import create_project, import_transcript
from .models import Brand, ClipInput
from .store import new_id

SAMPLE = Path(__file__).parent / "sample"


def load_sample(store):
    existing = next((p for p in store.projects() if p.get("sample")), None)
    if existing:
        return existing
    project = create_project(
        store,
        SAMPLE / "conversation.mp4",
        title="Give the idea room to land",
        brand=Brand(
            show="Good conversations", guest="Goodtake sample", role="Synthetic narration · original artwork"
        ),
        sample=True,
    )
    project = import_transcript(store, project["id"], (SAMPLE / "words.json").read_text())
    clip = ClipInput(
        title="Keep the payoff in the clip",
        start=project["words"][0]["start"],
        end=project["words"][-1]["end"],
        takeaway="A complete thought deserves a complete clip.",
        reason="Bundled sample selection. It demonstrates rendering and editing, not automatic selection.",
        post="A useful clip contains a complete thought: a clear opening, a real payoff, and a natural ending.",
    )
    store.change(
        project["id"],
        lambda p: p["clips"].append(
            {
                **clip.model_dump(),
                "id": new_id(),
                "status": "draft",
                "editorial": {"method": "Bundled sample selection; not an AI selection result"},
            }
        ),
    )
    return store.get(project["id"])
