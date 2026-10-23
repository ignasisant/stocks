/**
 * The toast wrapper: what a caller gets for each shape, and that none of it
 * needs sonner imported at the call site.
 *
 * Sonner is mocked: the question is what the wrapper asks of it (how long,
 * whether it can be closed, which button), not sonner's own drawing.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const calls = vi.hoisted(() => ({
  success: vi.fn(),
  warning: vi.fn(),
  error: vi.fn(),
  loading: vi.fn(),
  promise: vi.fn(),
  dismiss: vi.fn(),
  base: vi.fn(),
}));

vi.mock("sonner", () => {
  const fn = Object.assign(calls.base, {
    success: calls.success,
    warning: calls.warning,
    error: calls.error,
    loading: calls.loading,
    promise: calls.promise,
    dismiss: calls.dismiss,
  });
  return { toast: fn };
});

import { DURATION, prefersReducedMotion, toast } from "./toast";

beforeEach(() => vi.clearAllMocks());
afterEach(() => vi.unstubAllGlobals());

describe("a fading toast", () => {
  it("lasts longer the worse the news, and has no close button", () => {
    toast.ok("Saved");
    toast.warn("Slow");
    toast.bad("Failed");
    expect(calls.success.mock.calls[0]![1]).toMatchObject({
      duration: DURATION.ok,
      closeButton: false,
    });
    expect(calls.warning.mock.calls[0]![1].duration).toBe(DURATION.warn);
    expect(calls.error.mock.calls[0]![1].duration).toBe(DURATION.bad);
    expect(DURATION.ok).toBeLessThan(DURATION.bad);
  });

  it("waits longer when it carries a button, and hands the press on", () => {
    const onClick = vi.fn();
    toast.ok("Hidden", { action: { label: "Undo", onClick } });
    const options = calls.success.mock.calls[0]![1];
    expect(options.duration).toBe(DURATION.action);
    expect(options.action.label).toBe("Undo");
    options.action.onClick();
    expect(onClick).toHaveBeenCalledOnce();
  });
});

describe("a persistent toast", () => {
  it("never fades and can be closed by hand", () => {
    toast.stay("Read me to the end");
    expect(calls.base).toHaveBeenCalledWith(
      "Read me to the end",
      expect.objectContaining({ duration: Infinity, closeButton: true }),
    );
  });

  it("keeps a loading toast up until it is replaced", () => {
    toast.busy("Working", { id: "job" });
    expect(calls.loading).toHaveBeenCalledWith("Working", {
      id: "job",
      duration: Infinity,
    });
  });
});

describe("a promise toast", () => {
  it("turns loading into its outcome and returns the work untouched", async () => {
    const work = Promise.resolve(3);
    const back = toast.promise(work, {
      loading: "Saving",
      success: (n) => `Saved ${n}`,
      error: "Failed",
    });
    expect(back).toBe(work);
    const words = calls.promise.mock.calls[0]![1];
    expect(words.loading).toBe("Saving");
    expect(words.success(3)).toEqual({ message: "Saved 3", duration: DURATION.ok });
    expect(words.error(new Error("x"))).toEqual({
      message: "Failed",
      duration: DURATION.bad,
    });
  });
});

describe("reduced motion", () => {
  it("is read from the system setting", () => {
    vi.stubGlobal("window", { matchMedia: () => ({ matches: true }) });
    expect(prefersReducedMotion()).toBe(true);
    vi.stubGlobal("window", { matchMedia: () => ({ matches: false }) });
    expect(prefersReducedMotion()).toBe(false);
  });

  it("is false where there is no window", () => {
    vi.stubGlobal("window", undefined);
    expect(prefersReducedMotion()).toBe(false);
  });
});
