import { describe, expect, test, vi } from "vitest";

import {
  accumulateTranscriptDelta,
  approximateFinalTimes,
  commitInputAudioBuffer,
  cleanupSessionResources,
  eventForError,
  eventForTranscript,
  flushOutboundEvents,
  finishStoppingSession,
  isSessionGenerationCurrent,
  observeDrainTranscriptEvent,
  shouldDrainSession,
  waitForDataChannelDrain,
} from "./main";
import type { ComponentEvent } from "./main";

describe("accumulateTranscriptDelta", () => {
  test("builds a complete partial caption and clears it when completed", () => {
    const captions: Record<string, string> = {};

    expect(
      accumulateTranscriptDelta(captions, {
        type: "conversation.item.input_audio_transcription.delta",
        item_id: "item-1",
        delta: "矩",
      }),
    ).toBe("矩");
    expect(
      accumulateTranscriptDelta(captions, {
        type: "conversation.item.input_audio_transcription.delta",
        item_id: "item-1",
        delta: "陣",
      }),
    ).toBe("矩陣");

    expect(
      accumulateTranscriptDelta(captions, {
        type: "conversation.item.input_audio_transcription.completed",
        item_id: "item-1",
        transcript: "矩陣",
      }),
    ).toBeNull();
    expect(captions).toEqual({});
  });
});

test("cleanup closes acquired resources and stops every track", () => {
  const closeDataChannel = vi.fn();
  const closeConnection = vi.fn();
  const stopFirstTrack = vi.fn();
  const stopSecondTrack = vi.fn();

  cleanupSessionResources({
    dataChannel: { close: closeDataChannel },
    connection: { close: closeConnection },
    mediaStream: {
      getTracks: () => [{ stop: stopFirstTrack }, { stop: stopSecondTrack }],
    },
  });

  expect(closeDataChannel).toHaveBeenCalledOnce();
  expect(closeConnection).toHaveBeenCalledOnce();
  expect(stopFirstTrack).toHaveBeenCalledOnce();
  expect(stopSecondTrack).toHaveBeenCalledOnce();
});

test("commit finalizes buffered audio only while the data channel is open", () => {
  const send = vi.fn();

  expect(commitInputAudioBuffer({ readyState: "open", send })).toBe(true);
  expect(send).toHaveBeenCalledWith(JSON.stringify({ type: "input_audio_buffer.commit" }));
  expect(commitInputAudioBuffer({ readyState: "closed", send })).toBe(false);
});

test("a stop generation invalidates an in-flight start", () => {
  expect(isSessionGenerationCurrent(4, 4, "start")).toBe(true);
  expect(isSessionGenerationCurrent(4, 5, "stop")).toBe(false);
});

test("a stopping session keeps accepting queued data-channel events", () => {
  expect(shouldDrainSession("stop", "stopping")).toBe(true);
  expect(shouldDrainSession("stop", "recording")).toBe(false);
});

test("stopping waits for the final queued event before session_stopped", async () => {
  const events: string[] = [];
  let releaseDrain: (() => void) | undefined;

  const stopping = finishStoppingSession(
    () =>
      new Promise<void>((resolve) => {
        releaseDrain = resolve;
      }),
    () => events.push("session_stopped"),
    () => events.push("session_error"),
  );

  events.push("final_transcript");
  expect(events).toEqual(["final_transcript"]);

  releaseDrain?.();
  await stopping;

  expect(events).toEqual(["final_transcript", "session_stopped"]);
});

test("a bounded drain timeout rejects unresolved turns and removes its listeners", async () => {
  vi.useFakeTimers();
  try {
    const listeners = new Map<string, EventListener>();
    const dataChannel = {
      readyState: "open" as const,
      addEventListener: (type: string, listener: EventListener) => listeners.set(type, listener),
      removeEventListener: vi.fn((type: string) => listeners.delete(type)),
    };

    const drain = waitForDataChannelDrain(dataChannel, new Set(["item-1"]));
    const rejection = expect(drain).rejects.toThrow("transcript completion");
    await vi.advanceTimersByTimeAsync(5000);

    await rejection;
    expect(dataChannel.removeEventListener).toHaveBeenCalledTimes(3);
    expect(listeners).toEqual(new Map());
  } finally {
    vi.useRealTimers();
  }
});

test("a drain error emits session_error and cleanup instead of hanging", async () => {
  const events: string[] = [];
  const stopping = finishStoppingSession(
    () => Promise.reject(new Error("drain failed")),
    () => events.push("session_stopped"),
    (error) => {
      events.push(`session_error:${error instanceof Error ? error.message : "unknown"}`);
      events.push("cleanup");
    },
  );

  await stopping;

  expect(events).toEqual(["session_error:drain failed", "cleanup"]);
});

describe("eventForTranscript", () => {
  test("maps partial and completed Realtime transcript events", () => {
    expect(
      eventForTranscript({
        type: "conversation.item.input_audio_transcription.delta",
        item_id: "item-1",
        delta: "矩",
      }),
    ).toMatchObject({
      type: "partial_transcript",
      event_id: "item-1",
      text: "矩",
    });

    expect(
      eventForTranscript({
        type: "conversation.item.input_audio_transcription.completed",
        item_id: "item-1",
        transcript: "矩陣",
        audio_start_ms: 2000,
        audio_end_ms: 3500,
      }),
    ).toEqual({
      type: "final_transcript",
      event_id: "item-1",
      text: "矩陣",
      start_seconds: 2,
      end_seconds: 3.5,
    });
  });

  test("fills final timing from monotonic speech-turn observations when server timing is absent", () => {
    const times = approximateFinalTimes(
      "item-2",
      { "item-2": { startedAtMs: 1010, lastDeltaAtMs: 2780 } },
      4000,
      1000,
    );

    expect(
      eventForTranscript(
        {
          type: "conversation.item.input_audio_transcription.completed",
          item_id: "item-2",
          transcript: "線性代數",
        },
        times,
      ),
    ).toEqual({
      type: "final_transcript",
      event_id: "item-2",
      text: "線性代數",
      start_seconds: 0.01,
      end_seconds: 1.78,
    });
  });
});

test("converts browser errors to safe component events", () => {
  expect(eventForError(new Error("Permission denied"))).toEqual({
    type: "session_error",
    message: "Permission denied",
  });
});

test("keeps approximate final timing monotonic", () => {
  expect(
    approximateFinalTimes(
      "item-3",
      { "item-3": { startedAtMs: 3000, lastDeltaAtMs: 2900 } },
      2800,
      1000,
    ),
  ).toEqual({ start_seconds: 2, end_seconds: 2 });
});

test("outbound events are delivered as an ordered batch and acknowledge only the sent events", () => {
  const setComponentValue = vi.fn();
  const queue: ComponentEvent[] = [
    { type: "partial_transcript" as const, event_id: "item-1", text: "一", start_seconds: null, end_seconds: null, message: null },
    { type: "final_transcript" as const, event_id: "item-1", text: "一", start_seconds: 0, end_seconds: 1, message: null },
  ];

  const sentEvents = [...queue];
  const inFlight = flushOutboundEvents(queue, setComponentValue);

  expect(setComponentValue).toHaveBeenCalledWith({ type: "event_batch", events: sentEvents });
  expect(inFlight).toEqual(["item-1", "item-1"]);

  queue.push({ type: "session_stopped", event_id: "session-1", text: "", start_seconds: null, end_seconds: null, message: null });
  expect(queue).toHaveLength(1);
});

test("completion-aware drain resolves after every active transcript item completes", async () => {
  const listeners = new Map<string, (event?: unknown) => void>();
  const activeItems = new Set(["item-1", "item-2"]);
  const dataChannel = {
    readyState: "open" as const,
    addEventListener: (type: string, listener: (event?: unknown) => void) => listeners.set(type, listener),
    removeEventListener: vi.fn((type: string) => listeners.delete(type)),
  };

  const drain = waitForDataChannelDrain(dataChannel, activeItems);
  observeDrainTranscriptEvent(activeItems, { type: "conversation.item.input_audio_transcription.completed", item_id: "item-1" });
  listeners.get("message")?.({ data: JSON.stringify({ type: "conversation.item.input_audio_transcription.completed", item_id: "item-1" }) });
  expect(activeItems).toEqual(new Set(["item-2"]));
  expect(listeners.has("message")).toBe(true);

  observeDrainTranscriptEvent(activeItems, { type: "conversation.item.input_audio_transcription.completed", item_id: "item-2" });
  listeners.get("message")?.({ data: JSON.stringify({ type: "conversation.item.input_audio_transcription.completed", item_id: "item-2" }) });

  await expect(drain).resolves.toBeUndefined();
  expect(dataChannel.removeEventListener).toHaveBeenCalledWith("message", expect.any(Function));
});

test("a stop with no prior delta waits for queued completion during the finalization window", async () => {
  vi.useFakeTimers();
  try {
    const listeners = new Map<string, (event?: unknown) => void>();
    const dataChannel = {
      readyState: "open" as const,
      addEventListener: (type: string, listener: (event?: unknown) => void) => listeners.set(type, listener),
      removeEventListener: vi.fn((type: string) => listeners.delete(type)),
    };

    let settled = false;
    const drain = waitForDataChannelDrain(dataChannel, new Set());
    drain.then(() => {
      settled = true;
    });
    await Promise.resolve();
    expect(settled).toBe(false);

    listeners.get("message")?.({
      data: JSON.stringify({
        type: "conversation.item.input_audio_transcription.completed",
        item_id: "item-without-delta",
        transcript: "queued final",
      }),
    });
    await Promise.resolve();
    expect(settled).toBe(false);

    await vi.advanceTimersByTimeAsync(4999);
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    await expect(drain).resolves.toBeUndefined();
    expect(dataChannel.removeEventListener).toHaveBeenCalledWith("message", expect.any(Function));
  } finally {
    vi.useRealTimers();
  }
});