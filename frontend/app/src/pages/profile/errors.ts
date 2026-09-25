/**
 * What a refused write says on screen.
 *
 * The API validates and answers 422 with a `detail` that names the problem, so
 * that sentence is the message — anything this page invented instead would be
 * vaguer than what the server already said. Only a request that never reached
 * it falls back to a catalog string.
 */

import { ApiError } from "../../shell/api";

export function describe(error: unknown, offline: string): string {
  return error instanceof ApiError ? error.detail : offline;
}
