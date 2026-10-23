/**
 * The one `<Toaster>`, mounted by the shell (`shell/Layout.tsx`) inside
 * `.ag-shell` so it can read `--dock` and clear the phone's tab bar. Looks in
 * `toast.css`; callers use `ui/toast.ts` and never this.
 */

import { Toaster as Sonner } from "sonner";
import "./toast.css";

export function Toaster() {
  return (
    <Sonner
      position="bottom-right"
      theme="dark"
      visibleToasts={3}
      gap={8}
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
