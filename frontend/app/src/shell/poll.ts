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
  /**
   * Home's day while a held name trades: the server reads its shared quote
   * board, a minute old at most, so asking faster shows nothing newer.
   */
  movers: 60_000,
  /**
   * Home's day while nothing held trades: only to notice an open (Madrid at
   * 09:00, New York at 15:30) on a page left up since before it.
   */
  moversIdle: 300_000,
} as const;
