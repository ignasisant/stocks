import { Component, type ReactNode } from "react";

/**
 * What a screen shows when it threw while rendering, instead of a blank page.
 *
 * React unmounts the whole tree under a render error that nothing catches, so
 * one bad row on one tab used to leave a reader with an empty white window and
 * no way out but the reload button they might not think of. This catches it at
 * the page (the rail and the search box stay, so the reader can go elsewhere)
 * and, outside everything, at the root. The report itself is the root's job
 * (`onCaughtError` in `main.tsx`), not this component's.
 *
 * `resetKey` is the screen: moving to another one tries again, which is also
 * what clears a failure that belonged to one ticker or one tab.
 */
export class Crash extends Component<
  { resetKey?: string; fallback: ReactNode; children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidUpdate(previous: { resetKey?: string }) {
    if (this.state.failed && previous.resetKey !== this.props.resetKey) {
      this.setState({ failed: false });
    }
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

/** The fallback's body: what happened, and the one thing that fixes most of it. */
export function Broken({ text, action }: { text: string; action: string }) {
  return (
    <div className="ag-wall" role="alert">
      <p>{text}</p>
      <button className="ag-btn" onClick={() => window.location.reload()}>
        {action}
      </button>
    </div>
  );
}
