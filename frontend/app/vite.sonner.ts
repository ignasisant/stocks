import type { Plugin } from "vite";

// Sonner's ESM build injects its stylesheet at module load: it appends a
// <style> element to <head>. The page's CSP (`web/csp.py`) allows only hashed
// inline styles, so that element is refused and the toasts draw unstyled.
// This drops the call at build time; `ui/Toaster.tsx` imports
// `sonner/dist/styles.css` instead, which ships in the bundled stylesheet
// served from 'self'. A sonner upgrade that changes the shape of the call
// fails the build here (and `ui/sonner-csp.test.ts`) rather than shipping a
// toast that breaks under the policy.
const CALL = /^__insertCSS\((?:"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|`[^`]*`)\);?$/m;

export function stripSonnerInjection(code: string): string {
  if (!CALL.test(code)) {
    throw new Error(
      "sonner no longer calls __insertCSS(...) the way vite.sonner.ts expects; " +
        "check that it still does not inject a <style> at runtime.",
    );
  }
  const out = code.replace(CALL, "");
  if (/__insertCSS\(["'`]/.test(out)) {
    throw new Error("sonner still injects CSS at runtime after the transform.");
  }
  return out;
}

export function sonnerNoRuntimeCss(): Plugin {
  return {
    name: "ag-sonner-no-runtime-css",
    enforce: "pre",
    transform(code, id) {
      if (!/node_modules\/sonner\/dist\/index\.m?js$/.test(id)) return;
      return { code: stripSonnerInjection(code), map: null };
    },
  };
}
