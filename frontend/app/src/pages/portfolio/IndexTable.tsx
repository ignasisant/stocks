import type { IndexRow } from "./riskLogic";

/** Each index on the book's same money: gain, return and the gap to the book. */
export function IndexTable({
  rows,
  name,
  money,
  pct,
  labels,
}: {
  rows: IndexRow[];
  name: (bench: string) => string;
  money: (value: number, signed?: boolean) => string;
  pct: (value: number) => string;
  labels: { index: string; gain: string; pct: string; versus: string; you: string };
}) {
  if (!rows.length) return null;
  return (
    <table className="pf-idx">
      <thead>
        <tr>
          <th>{labels.index}</th>
          <th>{labels.gain}</th>
          <th>{labels.pct}</th>
          <th>{labels.versus}</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.bench}>
            <th scope="row">{name(row.bench)}</th>
            <td>{money(row.gain, true)}</td>
            <td>{pct(row.pct)}</td>
            <td className={row.versus >= 0 ? "pf-up" : "pf-down"}>
              {money(row.versus, true)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
