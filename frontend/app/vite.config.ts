import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

// `server.py` inlines `ds_vars_css()` in place of the <!--AG-TOKENS--> marker
// before the document goes out; `npm run dev` serves index.html untouched, so
// without this the page paints with every `--ag-*` undefined. Same tokens, same
// source — read over the API the dev server already proxies.
function devTokens(): Plugin {
  return {
    name: "ag-dev-tokens",
    apply: "serve",
    async transformIndexHtml(html) {
      try {
        const response = await fetch("http://localhost:8501/api/v1/design/tokens");
        const { tokens } = (await response.json()) as {
          tokens: Record<string, string>;
        };
        const body = Object.entries(tokens)
          .map(([name, value]) => `  --ag-${name}: ${value};`)
          .join("\n");
        return html.replace("<!--AG-TOKENS-->", `<style>:root {\n${body}\n}</style>`);
      } catch {
        // The app is not up yet: the page still loads, unstyled, and a reload
        // once it is running picks the tokens up.
        return html;
      }
    },
  };
}

// The build lands inside the Python
// package so a source deploy, the wheel and a plain checkout all serve the
// page without anyone needing Node. That means the bundle is committed — see
// frontend/README.md for why, and `npm run build` is the only thing that
// should ever change it.
export default defineConfig({
  plugins: [react(), devTokens()],
  base: "/next-assets/",
  build: {
    outDir: "../../src/stocks/web/static/app",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        // One chunk per page, so opening Home does not download the tax
        // engine's tables. The shell is the entry and is always paid for.
        entryFileNames: "app.js",
        // `[name]` is the module that produced the chunk, which is the page's
        // own entry file — see shell/pages.ts for why those are named after
        // their page and not all called `Page`.
        chunkFileNames: "[name].js",
        assetFileNames: "[name][extname]",
      },
    },
  },
  server: {
    // `/app/static/` is the logo mirror: the API hands a ticker's logo back as
    // a path relative to the app document (see web/logos.py), which resolves
    // against this dev server rather than the one holding the mirror — every
    // ticker cell drew a broken image until this proxied too.
    // `/auth` is the app's own sign-in (web/oidc.py). It has to be proxied or
    // the shell's sign-in link 404s against this dev server — and the round
    // trip has to *finish* on 8501, because that is the redirect URI Google
    // has registered. The cookie it sets is host-only and cookies ignore the
    // port, so coming back here afterwards arrives signed in.
    proxy: {
      "/api": "http://localhost:8501",
      "/app": "http://localhost:8501",
      "/auth": "http://localhost:8501",
    },
    // The rail's brand mark is imported from `src/stocks/web/assets/` — the
    // one the Streamlit app and the landing already draw, rather than a copy
    // in this app that would be the same logo only until somebody changed one
    // of them. It sits outside this app's root, and a dev server will not read
    // a file it has not been told it may; the repo root is that permission.
    fs: { allow: ["../.."] },
  },
});
