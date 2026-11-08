/**
 * How often the app asks again while something is being made on the server.
 *
 * One table instead of a constant per screen, so "how patient is this app" has
 * one answer to read and to change. Every poll runs one request at a time: the
 * next is scheduled when the last has answered, never on a bare interval that
 * could stack requests on a slow host.
 */

export const POLL_MS = {
  /** The personal Today card being written: a few seconds of model time. */
  card: 1500,
  /** The corner banner reading the server's job progress. */
  progress: 2000,
  /** A sector rescan: tens of seconds of Yahoo, so a patient ask. */
  scan: 3000,
  /** The thread list while another thread is answering. */
  threads: 5000,
  /** The market read a session behind, while a newer one is built. */
  market: 20_000,
} as const;
