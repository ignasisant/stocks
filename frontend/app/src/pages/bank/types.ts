/** The shapes `/api/v1/bank` answers with. Mirrors `schemas/`. */

type BankAccount = {
  uid: string;
  name: string;
  masked_id: string;
  currency: string;
  product: string;
  /** Null until the account has been read once, and null again when the
      bank's own figure would not parse — never a zero standing in for one. */
  balance: number | null;
  balance_currency: string;
  fetched_at: string | null;
};

export type BankConnection = {
  session_id: string;
  name: string;
  country: string;
  valid_until: string;
  connected_at: string;
  expired: boolean;
  accounts: BankAccount[];
};

export type BankState = {
  available: boolean;
  /** "" when this host cannot offer one: banks only redirect to https. */
  redirect_url: string;
  connections: BankConnection[];
  /** The reader's reporting currency, which the next two figures use. */
  currency: string;
  /** All read balances at today's rate; null when none, or one can't convert. */
  cash_value: number | null;
  /** The book's market value; null when nothing priced. */
  book_value: number | null;
};

export type BankChoice = { name: string; country: string; logo: string | null };

export type BankAuth = { url: string; bank: string; state: string };
