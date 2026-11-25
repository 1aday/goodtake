# Third-party components and sample provenance

Goodtake's application and adaptation code is MIT licensed. This does not relicense dependencies.

- **Remotion 4.0.545:** separate Remotion License. Individuals and qualifying small organizations
  have a free license; other uses may need a Company License. Check [current terms](https://www.remotion.dev/docs/license/pricing).
  Goodtake does not include or grant a Remotion license on your behalf.
- **Bricolage Grotesque, Geist and Geist Mono:** SIL Open Font License 1.1. Fontsource packages
  supply the renderer fonts. The web app's bundled Bricolage and Geist fonts include their OFL
  texts in `goodtake/web/fonts/`.
- **FFmpeg and Chromium:** installed separately or through the container's Debian packages.
  Their licenses and optional codec builds remain their own. Goodtake invokes their programs.
- **faster-whisper and CTranslate2:** optional local recognition software; see their upstream
  MIT licenses. Downloaded Whisper weights have their own model license and live outside this repo.
- **yt-dlp:** optional YouTube acquisition software, with upstream license and third-party notices.
  Source videos and any platform permissions remain the user's responsibility.

## The bundled sample

`goodtake/sample/conversation.mp4` contains original generated microphone artwork, an audio waveform,
and explicitly synthetic narration of `script.txt`. It contains no real guest, real interview,
private customer video, or competitive product's media.

The artwork was generated with OpenAI's built-in image generator. The narrator was generated with
OpenAI's `gpt-4o-mini-tts` model, preset voice `cedar`, on November 25, 2026. Word timing was measured
with local Whisper `base.en`; the prepared selection is identified as such in the app. This is an
installation/editing/rendering fixture, not evidence of automatic editorial quality on real podcasts.

To the extent the project owns copyright in the original sample script, artwork and final sample,
those assets are also available under the project's MIT license. No rights to an underlying model,
voice identity, or third-party trademark are conveyed.

`scripts/build-sample.py` recreates the video and timings from a supplied narration WAV and the
project artwork. It makes no paid requests. The one-time sample narration generation is not a
runtime dependency of Goodtake.
