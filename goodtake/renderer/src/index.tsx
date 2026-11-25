import React from "react";
import { Composition, registerRoot } from "remotion";
import { Clip, ClipProps } from "./Clip";

const defaults: ClipProps = {
  title: "A complete idea, beautifully told",
  takeaway: "Keep the thought intact.",
  duration: 30,
  brand: {
    show: "The conversation",
    guest: "Guest",
    role: "",
    accent: "#F36B45",
    end_card: true,
  },
  style: {
    template: "editorial",
    ratio: "9:16",
    framing: "fit",
    focal_x: 0.5,
    captions: true,
  },
  words: [],
  groups: [],
  layout: {
    header: [72, 72, 936, 100],
    title: [72, 200, 936, 240],
    video: [40, 490, 1000, 890],
    captions: [65, 1430, 950, 220],
    footer: [72, 1755, 936, 60],
  },
};
function Root() {
  return (
    <Composition
      id="Goodtake"
      component={Clip}
      width={1080}
      height={1920}
      fps={30}
      durationInFrames={972}
      defaultProps={defaults}
      calculateMetadata={({ props }) => ({
        height: props.style.ratio === "4:5" ? 1350 : 1920,
        durationInFrames:
          Math.ceil(props.duration * 30) + (props.brand.end_card ? 72 : 0),
      })}
    />
  );
}
registerRoot(Root);
