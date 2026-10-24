import { act, renderHook } from "@testing-library/react";
import { toast } from "sonner";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useTimers } from "./timers";

vi.mock("sonner", () => ({ toast: { success: vi.fn() } }));

const started: number[] = [];

class FakeAudioContext {
  state = "running";
  currentTime = 0;
  destination = {};
  resume = vi.fn();
  createOscillator() {
    return {
      frequency: { value: 0 },
      connect: (node: unknown) => node,
      start: (at: number) => started.push(at),
      stop: vi.fn(),
    };
  }
  createGain() {
    return {
      gain: { setValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn() },
      connect: (node: unknown) => node,
    };
  }
}

beforeEach(() => {
  vi.useFakeTimers();
  started.length = 0;
  vi.stubGlobal("AudioContext", FakeAudioContext);
  vi.stubGlobal("navigator", { ...navigator, vibrate: vi.fn() });
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("useTimers", () => {
  it("chimes, buzzes and says so when a timer finishes", () => {
    const { result } = renderHook(() => useTimers());

    act(() => result.current.toggle("t1", { label: "Simmer", seconds: 2 }));
    act(() => vi.advanceTimersByTime(1000));
    expect(started).toEqual([]);
    act(() => vi.advanceTimersByTime(1500));

    expect(started).toHaveLength(3); // three beeps
    expect(navigator.vibrate).toHaveBeenCalled();
    expect(toast.success).toHaveBeenCalledWith("Timer done: Simmer");
    expect(result.current.state("t1", { label: "Simmer", seconds: 2 }).left).toBe(0);
  });
});
