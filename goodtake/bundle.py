"""A portable guest handoff containing only approved produced assets and editable post copy."""

from __future__ import annotations

import html
import json
import zipfile

from .media import digest


def make_bundle(store, project_id):
    project = store.get(project_id)
    clips = [
        clip for clip in project["clips"] if clip["status"] == "ready" and clip.get("report", {}).get("pass")
    ]
    if not clips:
        raise ValueError("Approve at least one checked clip before creating the guest kit.")
    directory = store.directory(project_id)
    target = directory / "guest-kit.zip"
    cards, posts = [], []
    with zipfile.ZipFile(target.with_suffix(".zip.tmp"), "w", zipfile.ZIP_STORED) as archive:
        for index, clip in enumerate(clips, 1):
            work = directory / clip["render_directory"]
            if (
                not (work / "clip.mp4").is_file()
                or digest(work / "clip.mp4") != clip["report"]["output_sha256"]
            ):
                raise ValueError(
                    "An approved file changed or is missing. Export and check it again before packaging."
                )
            name = f"{index:02d}-{clip['id']}"
            archive.write(work / "clip.mp4", f"clips/{name}.mp4")
            archive.write(work / "cover.jpg", f"covers/{name}.jpg")
            cards.append(
                f'<article><video controls preload="metadata" poster="covers/{name}.jpg" '
                f'src="clips/{name}.mp4"></video><div><h2>{html.escape(clip["title"])}</h2>'
                f'<p>{html.escape(clip["takeaway"])}</p><a href="clips/{name}.mp4" download>Download clip</a>'
                f"<pre>{html.escape(clip['post'])}</pre></div></article>"
            )
            posts.append(f"{index}. {clip['title']}\n\n{clip['post']}\n")
        page = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" '
        page += (
            'content="width=device-width,initial-scale=1"><title>Your conversation, ready to share</title>'
        )
        page += "<style>body{margin:0;background:#f5f3eb;color:#233026;font:16px/1.6 system-ui}"
        page += "main{max-width:1000px;margin:auto;padding:48px 24px}h1{font-size:42px;line-height:1.1}"
        page += "article{display:grid;grid-template-columns:minmax(150px,300px) 1fr;gap:32px;padding:32px 0;"
        page += "border-top:1px solid #d3d8ca}video{width:100%;max-height:550px;background:#18261c}"
        page += "pre{white-space:pre-wrap;font:inherit}a{color:#385e3f}@media(max-width:600px){article{"
        page += "grid-template-columns:1fr}video{max-height:600px}h1{font-size:32px}}</style><main>"
        page += f"<p>{html.escape(project['brand']['show'])}</p><h1>Your conversation, ready to share.</h1>"
        page += f"<p>A few moments from the conversation with {html.escape(project['brand']['guest'])}.</p>"
        page += (
            "".join(cards)
            + '<p>Made with <a href="https://github.com/1aday/goodtake">Goodtake</a>.</p></main></html>'
        )
        archive.writestr("index.html", page)
        archive.writestr("post-copy.txt", "\n\n".join(posts))
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "show": project["brand"]["show"],
                    "clips": [
                        {
                            "title": c["title"],
                            "source_start": c["start"],
                            "source_end": c["end"],
                            "sha256": c["report"]["output_sha256"],
                        }
                        for c in clips
                    ],
                },
                indent=2,
            ),
        )
    target.with_suffix(".zip.tmp").replace(target)
    return target
