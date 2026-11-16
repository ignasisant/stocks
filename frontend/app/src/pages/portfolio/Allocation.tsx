import { useState } from "react";
import type { Slice } from "./charts";
import { Segmented } from "./ui";

type Split = { key: string; title: string; slices: Slice[] };

/** One allocation at a time: a stacked bar and the list under it. */
export function AllocationBars({
  splits,
  format,
  money,
  colors,
}: {
  splits: Split[];
  format: (fraction: number) => string;
  money: (value: number) => string;
  colors: (names: string[]) => Record<string, string>;
}) {
  const [key, setKey] = useState(splits[0]?.key ?? "");
  const split = splits.find((s) => s.key === key) ?? splits[0];
  if (!split) return null;
  const paint = colors(split.slices.map((s) => s.label));
  return (
    <div className="pf-alloc">
      <Segmented
        label={split.title}
        options={splits.map((s) => s.key)}
        value={split.key}
        onChange={setKey}
        format={(k) => splits.find((s) => s.key === k)?.title ?? k}
      />
      <div className="pf-stack" role="img" aria-label={split.title}>
        {split.slices.map((slice) => (
          <i
            key={slice.label}
            style={{ flexGrow: slice.weight, background: paint[slice.label] }}
          />
        ))}
      </div>
      <ul className="pf-alloc-list">
        {split.slices.map((slice) => (
          <li key={slice.label}>
            <span className="pf-swatch" style={{ background: paint[slice.label] }} />
            <span className="pf-alloc-name">{slice.label}</span>
            <span className="pf-alloc-val">
              {slice.value == null ? "" : money(slice.value)}
            </span>
            <b>{format(slice.weight)}</b>
          </li>
        ))}
      </ul>
    </div>
  );
}
