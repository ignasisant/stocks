/**
 * The MCP App's entry: read the config the server wrote in, shake hands with
 * the host, and draw whatever tool result it sends.
 *
 * Built apart from the app (`vite.mcp.config.ts`) with Preact standing in
 * for React, into one HTML file the connector serves as `ui://topstocks/view`.
 */

import { createRoot } from "react-dom/client";
import { Bridge, type HostContext, type ToolResult } from "./bridge";
import { View } from "./View";
import { applyTheme, language, readConfig, translator } from "./words";
import type { Words } from "./types";
import "./view.css";

const config = readConfig(document);
const shipped = Object.keys(config.strings);
const root = createRoot(document.getElementById("root") as HTMLElement);

let context: HostContext = {};
let result: ToolResult | null = null;

const bridge = new Bridge(window.parent, {
  context(next) {
    context = { ...context, ...next };
    applyTheme(document.documentElement, context);
    draw();
  },
  result(next) {
    result = next;
    draw();
  },
});

function draw() {
  const lang = language(context.locale ?? navigator.language, shipped);
  document.documentElement.lang = lang;
  const words: Words = {
    t: translator(config.strings[lang] ?? {}),
    locale: context.locale || navigator.language || lang,
    open: (path) => bridge.open(`${config.origin}${path}`),
  };
  root.render(<View result={result} words={words} />);
}

window.addEventListener("message", (event) => bridge.receive(event));
draw();
bridge.autosize();
bridge.start().catch(() => undefined);
