/**
 * What an `?url` import is, to TypeScript.
 *
 * Vite ships these declarations in `vite/client`, but that whole file also
 * redeclares `import.meta.env` and every asset extension the bundler knows —
 * a lot of surface for the one thing this app imports as a file. The brand
 * mark comes in as a URL string; that is the entire contract.
 */
declare module "*.svg?url" {
  const src: string;
  export default src;
}
