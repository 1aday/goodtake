import React, { useEffect, useMemo, useState } from "react";
import {
  AbsoluteFill,
  OffthreadVideo,
  Freeze,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  spring,
  delayRender,
  continueRender,
  cancelRender,
} from "remotion";
import "@fontsource-variable/bricolage-grotesque";
import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";

type Word = { text: string; start: number; end: number; speaker: string };
type Rect = [number, number, number, number];
export type ClipProps = {
  title: string;
  takeaway: string;
  duration: number;
  words: Word[];
  groups: Word[][];
  brand: {
    show: string;
    guest: string;
    role: string;
    accent: string;
    end_card: boolean;
  };
  style: {
    template: "editorial" | "paper" | "focus";
    ratio: "9:16" | "4:5";
    framing: "fit" | "fill";
    focal_x: number;
    captions: boolean;
  };
  layout: {
    header: Rect;
    title: Rect;
    video: Rect;
    captions: Rect;
    footer: Rect;
  };
};
const DISPLAY = '"Bricolage Grotesque Variable"';
const SANS = '"Geist Variable"';
const MONO = '"Geist Mono Variable"';
const position = ([left, top, width, height]: Rect): React.CSSProperties => ({
  position: "absolute",
  left,
  top,
  width,
  height,
});

function fitted(
  text: string,
  width: number,
  height: number,
  maxSize: number,
  family = DISPLAY,
  maxLines = 3,
) {
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d")!;
  for (let size = maxSize; size >= 24; size -= 2) {
    ctx.font = `800 ${size}px ${family}`;
    const lines: string[] = [];
    let line = "";
    let tooWide = false;
    for (const word of text.split(/\s+/)) {
      if (ctx.measureText(word).width > width) tooWide = true;
      const next = line ? line + " " + word : word;
      if (line && ctx.measureText(next).width > width) {
        lines.push(line);
        line = word;
      } else line = next;
    }
    if (line) lines.push(line);
    if (
      !tooWide &&
      lines.length <= maxLines &&
      lines.length * size * 1.08 <= height
    )
      return { lines, size };
  }
  throw new Error(
    "Text does not fit this layout. Shorten the title or takeaway.",
  );
}

export function Clip(p: ClipProps) {
  const frame = useCurrentFrame(),
    { fps, height } = useVideoConfig(),
    time = frame / fps;
  const [fontHandle] = useState(() => delayRender("Loading bundled typefaces"));
  const [fontsReady, setFontsReady] = useState(false);
  useEffect(() => {
    Promise.all([
      document.fonts.load(`800 96px ${DISPLAY}`),
      document.fonts.load(`600 40px ${SANS}`),
      document.fonts.load(`400 26px ${MONO}`),
    ])
      .then(() => {
        setFontsReady(true);
        continueRender(fontHandle);
      })
      .catch(cancelRender);
  }, [fontHandle]);
  const paper = p.style.template === "paper",
    focus = p.style.template === "focus",
    vertical = height === 1920;
  const colors = {
    bg: paper ? "#F1EEE6" : "#101310",
    fg: paper ? "#20261E" : "#F5F1E7",
    muted: paper ? "#686D60" : "#A5AA9D",
    accent: p.brand.accent,
  };
  const title = useMemo(
    () =>
      fontsReady
        ? fitted(
            p.title,
            p.layout.title[2],
            p.layout.title[3],
            vertical ? 102 : 82,
          )
        : null,
    [fontsReady, p.title, p.layout.title, vertical],
  );
  const group = [...p.groups]
    .reverse()
    .find(
      (g) => time >= g[0].start - 0.025 && time <= g[g.length - 1].end + 0.13,
    );
  const caption = useMemo(
    () =>
      fontsReady && group
        ? fitted(
            group.map((w) => w.text).join(" "),
            p.layout.captions[2] - 32,
            p.layout.captions[3],
            vertical ? 96 : 82,
            DISPLAY,
            2,
          )
        : null,
    [fontsReady, group, p.layout, vertical],
  );
  const ending = p.brand.end_card && frame >= Math.ceil(p.duration * fps);
  const fade = interpolate(
    frame,
    [Math.ceil(p.duration * fps), Math.ceil(p.duration * fps) + 9],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );
  const takeaway = useMemo(
    () =>
      fontsReady
        ? fitted(p.takeaway || p.title, 900, height * 0.35, vertical ? 100 : 86)
        : null,
    [fontsReady, p.takeaway, p.title, height, vertical],
  );
  const videoFrame = Math.min(
    frame,
    Math.max(0, Math.ceil(p.duration * fps) - 1),
  );
  const captionPop = group
    ? spring({
        frame: Math.max(0, frame - Math.floor(group[0].start * fps)),
        fps,
        config: { damping: 28, stiffness: 400 },
      })
    : 1;
  return (
    <AbsoluteFill
      style={{ background: colors.bg, color: colors.fg, fontFamily: SANS }}
    >
      <div
        style={{
          ...position(p.layout.video),
          overflow: "hidden",
          borderRadius: paper ? 0 : 18,
          background: paper ? "#E1E2D9" : "#20251E",
        }}
      >
        <Freeze frame={videoFrame}>
          <OffthreadVideo
            src={staticFile("source.mp4")}
            muted
            style={{
              width: "100%",
              height: "100%",
              objectFit: p.style.framing === "fill" ? "cover" : "contain",
              objectPosition: `${p.style.focal_x * 100}% 50%`,
            }}
          />
        </Freeze>
        {!focus && (
          <div
            style={{
              position: "absolute",
              left: 26,
              bottom: 24,
              padding: "12px 18px",
              background: "rgba(12,18,13,.86)",
              color: "#FAF7EE",
              maxWidth: 900,
            }}
          >
            <div style={{ fontSize: vertical ? 30 : 27, fontWeight: 600 }}>
              {p.brand.guest}
            </div>
            {p.brand.role && (
              <div
                style={{
                  fontSize: vertical ? 23 : 20,
                  opacity: 0.8,
                  marginTop: 4,
                }}
              >
                {p.brand.role}
              </div>
            )}
          </div>
        )}
        {!focus && (
          <div
            style={{
              position: "absolute",
              bottom: 0,
              left: 0,
              width: `${Math.min(1, time / p.duration) * 100}%`,
              height: 4,
              background: colors.accent,
            }}
          />
        )}
      </div>
      <div
        style={{
          ...position(p.layout.header),
          display: "flex",
          justifyContent: "space-between",
          alignItems: "start",
          ...(focus
            ? {
                background: "rgba(12,18,13,.88)",
                padding: "15px 22px",
                boxSizing: "border-box",
              }
            : {}),
        }}
      >
        <div
          style={{
            fontFamily: SANS,
            fontSize: vertical ? 32 : 27,
            fontWeight: 600,
            letterSpacing: -0.5,
            maxWidth: 760,
            lineHeight: 1.2,
            color: focus ? "#FAF7EE" : colors.fg,
          }}
        >
          {p.brand.show}
        </div>
        <div
          style={{
            fontFamily: MONO,
            fontSize: 22,
            color: colors.accent,
            letterSpacing: 1.2,
          }}
        >
          {paper ? "01 /" : "EXCERPT"}
        </div>
      </div>
      {title && (
        <div
          style={{
            ...position(p.layout.title),
            fontFamily: DISPLAY,
            fontWeight: 800,
            fontSize: title.size,
            lineHeight: 1.08,
            letterSpacing: -title.size * 0.025,
            ...(focus
              ? {
                  background: "rgba(12,18,13,.88)",
                  padding: "15px 22px",
                  boxSizing: "border-box",
                  color: "#FAF7EE",
                }
              : {}),
          }}
        >
          {title.lines.map((line, i) => (
            <div key={i}>{line}</div>
          ))}
          {paper && (
            <div
              style={{
                width: 108,
                height: 7,
                background: colors.accent,
                marginTop: 24,
              }}
            />
          )}
        </div>
      )}
      {p.style.captions && group && caption && (
        <div
          style={{
            ...position(p.layout.captions),
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            textAlign: "center",
          }}
        >
          <div
            style={{
              fontFamily: DISPLAY,
              fontWeight: 800,
              fontSize: caption.size,
              lineHeight: 1.08,
              letterSpacing: -caption.size * 0.025,
              transform: `scale(${0.97 + 0.03 * captionPop})`,
              ...(focus
                ? {
                    background: "rgba(12,18,13,.92)",
                    padding: "15px 24px",
                    borderRadius: 12,
                    color: "#FAF7EE",
                  }
                : {}),
            }}
          >
            {group.map((word, i) => {
              const current =
                time >= word.start - 0.025 && time <= word.end + 0.04;
              return (
                <span
                  key={i}
                  style={{
                    color: current
                      ? colors.accent
                      : focus
                        ? "#FAF7EE"
                        : colors.fg,
                  }}
                >
                  {word.text}
                  {i < group.length - 1 ? " " : ""}
                </span>
              );
            })}
          </div>
        </div>
      )}
      <div
        style={{
          ...position(p.layout.footer),
          fontFamily: MONO,
          fontSize: vertical ? 23 : 20,
          letterSpacing: 1,
          color: colors.muted,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <span>THE FULL CONVERSATION IS WORTH IT.</span>
        <span style={{ color: colors.accent }}>↗</span>
      </div>
      {ending && takeaway && (
        <AbsoluteFill
          style={{
            background: colors.bg,
            opacity: fade,
            padding: "90px",
            justifyContent: "center",
            boxSizing: "border-box",
          }}
        >
          <div
            style={{
              fontFamily: MONO,
              fontSize: 26,
              color: colors.accent,
              letterSpacing: 3,
              marginBottom: 48,
            }}
          >
            TAKE THIS WITH YOU
          </div>
          <div
            style={{
              fontFamily: DISPLAY,
              fontSize: takeaway.size,
              fontWeight: 800,
              lineHeight: 1.08,
              letterSpacing: -takeaway.size * 0.025,
            }}
          >
            {takeaway.lines.map((line, i) => (
              <div key={i}>{line}</div>
            ))}
          </div>
          <div
            style={{
              height: 6,
              width: 100,
              background: colors.accent,
              margin: "60px 0 36px",
            }}
          />
          <div style={{ fontFamily: SANS, fontWeight: 600, fontSize: 40 }}>
            {p.brand.show}
          </div>
          <div
            style={{
              fontFamily: SANS,
              fontSize: 28,
              color: colors.muted,
              marginTop: 14,
            }}
          >
            Watch the full conversation
          </div>
        </AbsoluteFill>
      )}
    </AbsoluteFill>
  );
}
