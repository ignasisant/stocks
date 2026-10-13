/**
 * One name in focus across the whole page.
 *
 * The map, the plan and the tables draw the same names three ways, and a
 * reader pointing at one of them wants to find it in the others: rest the
 * pointer on a dot, and its row in the plan and in the table lights while the
 * rest of each list fades; rest it on a row, and its dot rings and shows its
 * tooltip. Nothing moves or reflows — fading reads as a filter without
 * shoving the list from under the pointer.
 *
 * `from` is the section the pointer is in. That section keeps its own hover
 * look (a row wash, the dot's tooltip) and is not faded around the pointer;
 * only the others are. Entering and leaving are settled over a few frames so
 * a pointer crossing a dense table does not flicker every list on the page.
 */

import {
  type ReactNode,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

export type Source = "map" | "plan" | "held" | "outside";

export type Focus = { ticker: string; from: Source } | null;

type Store = {
  focus: Focus;
  /** Point at a name, or at nothing; settles before it lands. */
  point: (next: Focus) => void;
};

const NOBODY: Store = { focus: null, point: () => {} };

const Context = createContext<Store>(NOBODY);

/** How long the pointer rests before a new name takes focus, in ms. */
const SETTLE = 70;

export function FocusProvider({ children }: { children: ReactNode }) {
  const [focus, setFocus] = useState<Focus>(null);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const point = useCallback((next: Focus) => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      setFocus((now) =>
        now?.ticker === next?.ticker && now?.from === next?.from ? now : next,
      );
    }, SETTLE);
  }, []);
  const store = useMemo(() => ({ focus, point }), [focus, point]);
  return <Context.Provider value={store}>{children}</Context.Provider>;
}

export function useFocus(): Store {
  return useContext(Context);
}

/**
 * What one list needs to draw the focus: whether a name is the one pointed
 * at, and whether the rest of this list should fade — only when the pointer
 * is in another section and the name it points at is one of this list's.
 */
export function useListFocus(
  from: Source,
  tickers: string[],
): {
  on: (ticker: string) => boolean;
  fading: boolean;
  /** Pointer and keyboard handlers for a row of this list. */
  bind: (ticker: string) => {
    onPointerEnter: (event: { pointerType: string }) => void;
    onPointerLeave: (event: { pointerType: string }) => void;
    onFocus: () => void;
    onBlur: () => void;
  };
} {
  const { focus, point } = useFocus();
  const here = focus !== null && tickers.includes(focus.ticker);
  return {
    on: (ticker) => focus?.ticker === ticker,
    fading: here && focus?.from !== from,
    bind: (ticker) => ({
      // A finger has no hover: a tap is a press, not a point.
      onPointerEnter: (event) =>
        event.pointerType !== "touch" && point({ ticker, from }),
      onPointerLeave: (event) => event.pointerType !== "touch" && point(null),
      onFocus: () => point({ ticker, from }),
      onBlur: () => point(null),
    }),
  };
}
