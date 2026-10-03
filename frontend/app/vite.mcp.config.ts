import { defineConfig, type Plugin } from "vite";

// The MCP App the connector serves (`connector/views.py`): one HTML file, its
// script and styles inside it, because a host fetches a `ui://` resource as a
// single document and the frame it draws it in can load nothing else but
// images from this site.
//
// Preact stands in for React here and only here: the view is a few pure
// components and a `createRoot`, and React's runtime would be most of the
// file. The components are typed against React like the rest of the app.

/**
 * A path next to this file, whatever directory the build is started from.
 * `URL` rather than `node:url`, whose types this app does not install.
 */
function at(relative: string): string {
  return decodeURIComponent(new URL(relative, import.meta.url).pathname);
}

/** Every emitted script and stylesheet folded into the page, then dropped. */
function inline(): Plugin {
  return {
    name: "ts-mcp-inline",
    enforce: "post",
    generateBundle(_, bundle) {
      const page = bundle["view.html"];
      if (!page || page.type !== "asset") return;
      let html = String(page.source);
      for (const [name, item] of Object.entries(bundle)) {
        const ref = new RegExp(
          `<(script|link)[^>]*(?:src|href)="[^"]*${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}"[^>]*>(?:</script>)?`,
        );
        if (item.type === "chunk") {
          // "</script" or "<!--" inside the code would end or derail the
          // element; escaped, they are the same string to the script.
          const code = item.code
            .replace(/<\/script/gi, "<\\/script")
            .replace(/<!--/g, "<\\!--");
          html = html.replace(ref, () => `<script type="module">${code}</script>`);
          delete bundle[name];
        } else if (name.endsWith(".css")) {
          html = html.replace(ref, () => `<style>${String(item.source)}</style>`);
          delete bundle[name];
        }
      }
      page.source = html;
    },
  };
}

export default defineConfig({
  root: at("./src/mcp"),
  base: "./",
  plugins: [inline()],
  resolve: {
    alias: [
      { find: /^react$/, replacement: "preact/compat" },
      { find: /^react-dom$/, replacement: "preact/compat" },
      { find: /^react-dom\/client$/, replacement: "preact/compat/client" },
      { find: /^react\/jsx-runtime$/, replacement: "preact/jsx-runtime" },
      { find: /^react\/jsx-dev-runtime$/, replacement: "preact/jsx-dev-runtime" },
    ],
  },
  build: {
    outDir: at("../../src/stocks/web/static/mcp"),
    emptyOutDir: true,
    cssCodeSplit: false,
    modulePreload: false,
    assetsInlineLimit: Number.MAX_SAFE_INTEGER,
    rollupOptions: {
      input: at("./src/mcp/view.html"),
    },
  },
});
