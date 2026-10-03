/**
 * The view's side of MCP Apps: JSON-RPC over `postMessage` with the host.
 *
 * Hand-written rather than `@modelcontextprotocol/ext-apps`, whose `App`
 * brings zod and the MCP client along — several times this whole view, for a
 * conversation that is five messages long:
 *
 * - `ui/initialize` (request) → the host's context: theme, locale, styles;
 * - `ui/notifications/initialized` once that has arrived;
 * - `ui/notifications/tool-result` from the host: what to draw;
 * - `ui/notifications/host-context-changed`: a theme or locale flipped;
 * - `ui/notifications/size-changed` to the host as the content grows, and
 *   `ui/open-link` to send the reader back to TopStocks.
 *
 * Anything else the host asks is answered with an empty result, so a request
 * this view does not know (`ui/resource-teardown`, `ping`) never hangs the
 * host waiting. Messages from any window but the host are ignored.
 */

export const PROTOCOL_VERSION = "2026-01-26";

export type HostContext = {
  theme?: "light" | "dark";
  locale?: string;
  styles?: { variables?: Record<string, string | undefined> };
};

export type ToolResult = {
  content?: { type: string; text?: string }[];
  structuredContent?: Record<string, unknown>;
  isError?: boolean;
};

type Message = {
  jsonrpc?: string;
  id?: number | string;
  method?: string;
  params?: unknown;
  result?: unknown;
  error?: { message?: string };
};

type Port = { postMessage(message: unknown, targetOrigin: string): void };

export type Handlers = {
  context(context: HostContext): void;
  result(result: ToolResult): void;
};

export class Bridge {
  private next = 1;
  private readonly waiting = new Map<
    number | string,
    { resolve(value: unknown): void; reject(error: Error): void }
  >();

  constructor(
    private readonly host: Port,
    private readonly on: Handlers,
  ) {}

  /** One `message` event; anything not from the host is not for us. */
  receive(event: Pick<MessageEvent, "data" | "source">): void {
    if (event.source !== (this.host as unknown)) return;
    const message = event.data as Message | null;
    if (!message || typeof message !== "object" || message.jsonrpc !== "2.0") return;

    if (message.method === undefined) {
      if (message.id === undefined) return;
      const pending = this.waiting.get(message.id);
      if (!pending) return;
      this.waiting.delete(message.id);
      if (message.error) pending.reject(new Error(message.error.message ?? "refused"));
      else pending.resolve(message.result);
      return;
    }

    if (message.method === "ui/notifications/tool-result") {
      this.on.result((message.params ?? {}) as ToolResult);
    } else if (message.method === "ui/notifications/host-context-changed") {
      this.on.context((message.params ?? {}) as HostContext);
    }
    if (message.id !== undefined) {
      this.host.postMessage({ jsonrpc: "2.0", id: message.id, result: {} }, "*");
    }
  }

  request(method: string, params: unknown): Promise<unknown> {
    const id = this.next++;
    return new Promise((resolve, reject) => {
      this.waiting.set(id, { resolve, reject });
      this.host.postMessage({ jsonrpc: "2.0", id, method, params }, "*");
    });
  }

  notify(method: string, params: unknown): void {
    this.host.postMessage({ jsonrpc: "2.0", method, params }, "*");
  }

  /** The handshake: ask for the host's context, then say we are ready. */
  async start(): Promise<void> {
    const answer = (await this.request("ui/initialize", {
      protocolVersion: PROTOCOL_VERSION,
      appInfo: { name: "TopStocks", version: "1" },
      appCapabilities: {},
    })) as { hostContext?: HostContext } | undefined;
    this.on.context(answer?.hostContext ?? {});
    this.notify("ui/notifications/initialized", {});
  }

  /** Back to TopStocks. A host that refuses leaves the reader where they are. */
  open(url: string): void {
    this.request("ui/open-link", { url }).catch(() => undefined);
  }

  /** Tell the host how tall the content is, whenever that changes. */
  autosize(): () => void {
    let queued = false;
    let width = 0;
    let height = 0;
    const measure = () => {
      if (queued) return;
      queued = true;
      requestAnimationFrame(() => {
        queued = false;
        const root = document.documentElement;
        const kept = root.style.height;
        root.style.height = "max-content";
        const h = Math.ceil(root.getBoundingClientRect().height);
        root.style.height = kept;
        const w = Math.ceil(window.innerWidth);
        if (w === width && h === height) return;
        width = w;
        height = h;
        this.notify("ui/notifications/size-changed", { width: w, height: h });
      });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(document.documentElement);
    observer.observe(document.body);
    return () => observer.disconnect();
  }
}
