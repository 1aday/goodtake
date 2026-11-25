import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { bundle } from "@remotion/bundler";
import {
  selectComposition,
  renderMedia,
  renderStill,
} from "@remotion/renderer";

const [propsPath, output, mode = "video"] = process.argv.slice(2);
if (!propsPath || !output)
  throw new Error("Usage: node render.mjs props.json output.mp4 [video|still]");
const root = path.dirname(fileURLToPath(import.meta.url));
const props = JSON.parse(fs.readFileSync(propsPath, "utf8"));
const publicDir = path.join(path.dirname(propsPath), "media");
const progressPath = path.join(path.dirname(propsPath), "progress.json");
function progress(stage, value) {
  fs.writeFileSync(
    progressPath + ".tmp",
    JSON.stringify({ stage, progress: value }),
  );
  fs.renameSync(progressPath + ".tmp", progressPath);
}
const browserExecutable = process.env.CHROME_PATH || undefined;
progress("Preparing the video composition", 0);
const serveUrl = await bundle({
  entryPoint: path.join(root, "src/index.tsx"),
  publicDir,
  outDir: path.join(path.dirname(propsPath), "bundle"),
  onProgress: (value) =>
    progress("Preparing the video composition", (value / 100) * 0.1),
});
const composition = await selectComposition({
  serveUrl,
  id: "Goodtake",
  inputProps: props,
  browserExecutable,
});
if (mode === "still") {
  await renderStill({
    serveUrl,
    composition,
    inputProps: props,
    output,
    browserExecutable,
    frame: 0,
    imageFormat: "png",
  });
} else {
  await renderMedia({
    serveUrl,
    composition,
    inputProps: props,
    outputLocation: output,
    browserExecutable,
    codec: "h264",
    crf: 18,
    x264Preset: "veryfast",
    pixelFormat: "yuv420p",
    muted: true,
    concurrency: 2,
    offthreadVideoThreads: 2,
    offthreadVideoCacheSizeInBytes: 268435456,
    onProgress: (value) =>
      progress(
        "Rendering picture and word captions",
        0.1 + value.progress * 0.9,
      ),
  });
}
progress("Picture rendered", 1);
