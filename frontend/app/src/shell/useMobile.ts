import { useEffect, useState } from "react";

/**
 * Is this a phone?
 *
 * 640px, the breakpoint the ticker page's stylesheet uses, measured on the shell's
 * `ag-main` column rather than the viewport: an open chat drawer narrows the
 * page without touching the window, and the page has to go phone-shaped with
 * it. A hook rather than a container query because the phone layout is not a
 * restyle of the desktop one: it drops two range pills, defaults to the line
 * chart, thins the axis and transposes two tables — decisions that have to
 * reach the data, not only the box model. Without a shell around it (a test,
 * the server) the viewport decides.
 */

const PHONE_PX = 640;
const PHONE = `(max-width: ${PHONE_PX}px)`;

function column(): HTMLElement | null {
  return typeof document === "undefined" ? null : document.querySelector(".ag-main");
}

export function phoneNow(): boolean {
  const main = column();
  const width = main?.getBoundingClientRect().width ?? 0;
  if (width > 0) return width <= PHONE_PX;
  return typeof matchMedia === "function" && matchMedia(PHONE).matches;
}

export function useMobile(): boolean {
  const [mobile, setMobile] = useState(phoneNow);
  useEffect(() => {
    const update = () => setMobile(phoneNow());
    update();
    const main = column();
    if (main && typeof ResizeObserver !== "undefined") {
      const seen = new ResizeObserver(update);
      seen.observe(main);
      return () => seen.disconnect();
    }
    if (typeof matchMedia !== "function") return;
    const query = matchMedia(PHONE);
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  return mobile;
}
