import type { BrokerCost } from "./api";

export type FeeParts = {
  broker: string;
  commission: number;
  other: number;
  spread: number;
  total: number;
};

/** What each broker cost, split in its three parts; a spread that beat the mid adds nothing. */
export function feeParts(brokers: BrokerCost[]): FeeParts[] {
  return brokers
    .map((row) => {
      const commission = Math.max(0, row.commission);
      const other = Math.max(0, row.other_fees);
      const spread = Math.max(0, row.spread ?? 0);
      return {
        broker: row.broker,
        commission,
        other,
        spread,
        total: commission + other + spread,
      };
    })
    .sort((a, b) => b.total - a.total);
}

/** "5 per 1000 traded": the all-in cost as an amount on a round volume, or null. */
export function perThousand(costPct: number | null): number | null {
  return costPct === null || !Number.isFinite(costPct) ? null : costPct * 1000;
}
