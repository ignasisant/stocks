import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { Broken, Crash } from "./shell/Crash";
import { listen, report } from "./shell/errors";
import { watchInstall } from "./shell/install";
import { watchVitals } from "./shell/vitals";
import "./styles.css";

listen();
watchVitals();
watchInstall();

// Outside the catalog, which is fetched by the tree that just failed: the two
// languages the app speaks, chosen by the browser's own.
const spanish = navigator.language?.toLowerCase().startsWith("es");

createRoot(document.getElementById("root")!, {
  // A render error caught by a `Crash` boundary, and one nothing caught. Both
  // reported with the component stack, which only these hooks are given.
  onCaughtError: (error, info) => {
    console.error(error);
    report("render", error, info.componentStack ?? "");
  },
  onUncaughtError: (error, info) => {
    console.error(error);
    report("render", error, info.componentStack ?? "");
  },
}).render(
  <StrictMode>
    <Crash
      fallback={
        <Broken
          text={
            spanish
              ? "Algo ha fallado al mostrar la app."
              : "Something broke showing the app."
          }
          action={spanish ? "Recargar" : "Reload"}
        />
      }
    >
      <App />
    </Crash>
  </StrictMode>,
);
