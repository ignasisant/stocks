/**
 * The one `<Toaster>`, mounted by the shell (`shell/Layout.tsx`) inside
 * `.ag-shell` so it can read `--dock` and clear the phone's tab bar. Looks in
 * `toast.css`; callers use `ui/toast.ts` and never this.
 */

import { Toaster as Sonner } from "sonner";
// Sonner's own rules, as a file: its build would otherwise inject them as a
// <style> element at runtime, which the CSP refuses (see vite.sonner.ts).
import "sonner/dist/styles.css";
import "./toast.css";

// Where it sits: bottom right, lifted over the phone's tab bar (`--dock`,
// which already carries the home indicator's inset) and moved out of the open
// chat drawer's way (`--toast-right`, set in chat.css). Props, not CSS: sonner
// writes its offsets inline on the toaster, over any stylesheet.
const OFFSET = {
  right: "var(--toast-right, max(20px, env(safe-area-inset-right)))",
  bottom: "calc(var(--dock, 0px) + max(20px, env(safe-area-inset-bottom)))",
};
const MOBILE_OFFSET = {
  right: "max(16px, env(safe-area-inset-right))",
  left: "max(16px, env(safe-area-inset-left))",
  bottom: "calc(var(--dock, 0px) + max(16px, env(safe-area-inset-bottom)))",
};

export function Toaster() {
  return (
    <Sonner
      position="bottom-right"
      theme="dark"
      visibleToasts={3}
      gap={8}
      offset={OFFSET}
      mobileOffset={MOBILE_OFFSET}
      // Sonner draws its own chrome unless told not to; ours is `toast.css`.
      toastOptions={{
        unstyled: true,
        classNames: {
          toast: "ag-toast",
          title: "ag-toast-title",
          description: "ag-toast-detail",
          actionButton: "ag-toast-action",
          closeButton: "ag-toast-close",
          icon: "ag-toast-icon",
        },
      }}
    />
  );
}
