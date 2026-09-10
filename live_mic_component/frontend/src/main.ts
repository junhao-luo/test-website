import { RenderData, Streamlit } from "streamlit-component-lib";

type ComponentCommand = "start" | "stop" | string;

type SessionEventType =
  | "session_started"
  | "partial_transcript"
  | "final_transcript"
  | "session_error"
  | "session_stopped";

export type ComponentEvent = {
  type: SessionEventType;
  event_id: string;
  text: string;
  start_seconds: number | null;
  end_seconds: number | null;
  message: string | null;
};

type ErrorEventPayload = {
  type: "session_error";
  message: string;
};

type PartialTranscriptEvent = {
  type: "partial_transcript";
  event_id: string;
  text: string;
  start_seconds: null;
  end_seconds: null;
};

type FinalTranscriptEvent = {
  type: "final_transcript";
  event_id: string;
  text: string;
  start_seconds: number | null;
  end_seconds: number | null;
};

type TranscriptServerEvent = {
  type: string;
  item_id?: unknown;
  delta?: unknown;
  transcript?: unknown;
  audio_start_ms?: unknown;
  audio_end_ms?: unknown;
};

type TurnObservation = {
  startedAtMs: number;
  lastDeltaAtMs: number;
};

type TurnLedger = Record<string, TurnObservation>;

type ApproximateTimes = {
  start_seconds: number | null;
  end_seconds: number | null;
};

type SessionState = {
  command: ComponentCommand;
  clientSecret: string | null;
  status: "idle" | "connecting" | "recording" | "stopping" | "stopped" | "error";
  connection: RTCPeerConnection | null;
  dataChannel: RTCDataChannel | null;
  mediaStream: MediaStream | null;
  activeSessionId: string | null;
  ledger: TurnLedger;
  activeItemIds: Set<string>;
  partials: Record<string, string>;
  sessionStartMs: number | null;
  generation: number;
  failedGeneration: number | null;
  stopPromise: Promise<void> | null;
};

type SessionResources = {
  connection: { close(): void } | null;
  dataChannel: { close(): void } | null;
  mediaStream: { getTracks(): Array<{ stop(): void }> } | null;
};

const REALTIME_CALLS_URL = "https://api.openai.com/v1/realtime/calls";
const FRAME_HEIGHT = 44;
const DRAIN_TIMEOUT_MS = 5000;

const state: SessionState = {
  command: "idle",
  clientSecret: null,
  status: "idle",
  connection: null,
  dataChannel: null,
  mediaStream: null,
  activeSessionId: null,
  ledger: {},
  activeItemIds: new Set(),
  partials: {},
  sessionStartMs: null,
  generation: 0,
  failedGeneration: null,
  stopPromise: null,
};

let root: HTMLElement | null = null;

function renderStatus(): void {
  if (!root) {
    return;
  }
  root.textContent = `Live microphone component: ${state.status}`;
  Streamlit.setFrameHeight(FRAME_HEIGHT);
}

function monotonicSeconds(ms: number): number {
  return Math.round((ms / 1000) * 100) / 100;
}

function numberFromMilliseconds(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return null;
  }
  return monotonicSeconds(value);
}

function itemIdFrom(event: TranscriptServerEvent): string | null {
  return typeof event.item_id === "string" && event.item_id.trim() ? event.item_id : null;
}

export function approximateFinalTimes(itemId: string, ledger: TurnLedger, fallbackNowMs: number, sessionStartMs = 0): ApproximateTimes {
  const observation = ledger[itemId];
  if (!observation) {
    return { start_seconds: null, end_seconds: null };
  }

  const startMs = Math.max(0, observation.startedAtMs - sessionStartMs);
  const endMs = Math.max(startMs, observation.lastDeltaAtMs - sessionStartMs, fallbackNowMs < observation.startedAtMs ? startMs : 0);
  return {
    start_seconds: monotonicSeconds(startMs),
    end_seconds: monotonicSeconds(endMs),
  };
}

export function eventForTranscript(
  event: TranscriptServerEvent,
  approximateTimes: ApproximateTimes = { start_seconds: null, end_seconds: null },
): PartialTranscriptEvent | FinalTranscriptEvent | null {
  const eventId = itemIdFrom(event);
  if (!eventId) {
    return null;
  }

  if (event.type === "conversation.item.input_audio_transcription.delta") {
    return {
      type: "partial_transcript",
      event_id: eventId,
      text: typeof event.delta === "string" ? event.delta : "",
      start_seconds: null,
      end_seconds: null,
    };
  }

  if (event.type !== "conversation.item.input_audio_transcription.completed") {
    return null;
  }

  const explicitStart = numberFromMilliseconds(event.audio_start_ms);
  const explicitEnd = numberFromMilliseconds(event.audio_end_ms);
  const start = explicitStart ?? approximateTimes.start_seconds;
  const candidateEnd = explicitEnd ?? approximateTimes.end_seconds ?? start;
  const end = start === null || candidateEnd === null ? candidateEnd ?? start : Math.max(start, candidateEnd);

  return {
    type: "final_transcript",
    event_id: eventId,
    text: typeof event.transcript === "string" ? event.transcript : "",
    start_seconds: start,
    end_seconds: end,
  };
}

export function eventForError(error: unknown): ErrorEventPayload {
  if (error instanceof Error && error.message.trim()) {
    return { type: "session_error", message: error.message.trim() };
  }
  return { type: "session_error", message: "Unknown microphone session error" };
}

export function accumulateTranscriptDelta(
  captions: Record<string, string>,
  event: TranscriptServerEvent,
): string | null {
  const eventId = itemIdFrom(event);
  if (!eventId) {
    return null;
  }

  if (event.type === "conversation.item.input_audio_transcription.delta") {
    const delta = typeof event.delta === "string" ? event.delta : "";
    captions[eventId] = (captions[eventId] ?? "") + delta;
    return captions[eventId];
  }

  if (event.type === "conversation.item.input_audio_transcription.completed") {
    delete captions[eventId];
  }
  return null;
}

export function cleanupSessionResources(resources: SessionResources): void {
  try {
    resources.dataChannel?.close();
  } catch {
  }
  try {
    resources.connection?.close();
  } catch {
  }
  resources.mediaStream?.getTracks().forEach((track) => {
    try {
      track.stop();
    } catch {
    }
  });
}

export function isSessionGenerationCurrent(
  startGeneration: number,
  currentGeneration: number,
  command: ComponentCommand,
): boolean {
  return startGeneration === currentGeneration && command === "start";
}

export function shouldDrainSession(command: ComponentCommand, status: SessionState["status"]): boolean {
  return command === "stop" && status === "stopping";
}

type DrainableDataChannel = {
  readyState: string;
  send?(data: string): void;
  addEventListener(type: string, listener: () => void): void;
  removeEventListener(type: string, listener: () => void): void;
};

export function commitInputAudioBuffer(dataChannel: Pick<DrainableDataChannel, "readyState" | "send"> | null): boolean {
  if (!dataChannel || dataChannel.readyState !== "open" || !dataChannel.send) {
    return false;
  }
  dataChannel.send(JSON.stringify({ type: "input_audio_buffer.commit" }));
  return true;
}

export function flushOutboundEvents(
  queue: ComponentEvent[],
  setComponentValue: (value: { type: "event_batch"; events: ComponentEvent[] }) => void,
): string[] {
  if (!queue.length) {
    return [];
  }
  const events = queue.splice(0, queue.length);
  setComponentValue({ type: "event_batch", events });
  return events.map((event) => event.event_id);
}

type DrainTimers = {
  setTimeout(handler: () => void, timeoutMs: number): ReturnType<typeof setTimeout>;
  clearTimeout(timer: ReturnType<typeof setTimeout>): void;
};

const defaultDrainTimers: DrainTimers = {
  setTimeout: (handler, timeoutMs) => globalThis.setTimeout(handler, timeoutMs),
  clearTimeout: (timer) => globalThis.clearTimeout(timer),
};

export function waitForDataChannelDrain(
  dataChannel: DrainableDataChannel | null,
  activeItemIds: Set<string> = new Set(),
  timers: DrainTimers = defaultDrainTimers,
): Promise<void> {
  if (!dataChannel || dataChannel.readyState === "closed") {
    return Promise.resolve();
  }

  return new Promise((resolve, reject) => {
    let settled = false;
    const hasKnownActiveItems = activeItemIds.size > 0;
    const timer = timers.setTimeout(() => {
      finish(activeItemIds.size ? new Error("Timed out waiting for Realtime transcript completion") : undefined);
    }, DRAIN_TIMEOUT_MS);

    const finish = (error?: Error): void => {
      if (settled) {
        return;
      }
      settled = true;
      timers.clearTimeout(timer);
      dataChannel.removeEventListener("error", onError);
      dataChannel.removeEventListener("close", onClose);
      dataChannel.removeEventListener("message", onMessage);
      if (error) {
        reject(error);
      } else {
        resolve();
      }
    };

    const onError = (): void => finish(new Error("Realtime data channel failed during stop"));
    const onClose = (): void => finish(activeItemIds.size ? new Error("Realtime data channel closed during stop") : undefined);
    const onMessage = (messageEvent?: unknown): void => {
      try {
        const parsed = JSON.parse(String((messageEvent as { data?: unknown })?.data)) as TranscriptServerEvent;
        observeDrainTranscriptEvent(activeItemIds, parsed);
        if (hasKnownActiveItems && !activeItemIds.size) {
          finish();
        }
      } catch {
      }
    };
    dataChannel.addEventListener("error", onError);
    dataChannel.addEventListener("close", onClose);
    dataChannel.addEventListener("message", onMessage);
  });
}

export function observeDrainTranscriptEvent(activeItemIds: Set<string>, event: TranscriptServerEvent): void {
  if (event.type === "conversation.item.input_audio_transcription.completed") {
    const eventId = itemIdFrom(event);
    if (eventId) {
      activeItemIds.delete(eventId);
    }
  }
}

export async function finishStoppingSession(
  drain: () => Promise<void>,
  onStopped: () => void,
  onError: (error: unknown) => void,
): Promise<void> {
  try {
    await drain();
    onStopped();
  } catch (error) {
    onError(error);
  }
}

const pendingOutboundEvents: ComponentEvent[] = [];
let inFlightOutboundEventIds: string[] = [];

function acknowledgeOutboundEvents(): void {
  inFlightOutboundEventIds = [];
  flushPendingOutboundEvents();
}

function flushPendingOutboundEvents(): void {
  if (inFlightOutboundEventIds.length) {
    return;
  }
  inFlightOutboundEventIds = flushOutboundEvents(pendingOutboundEvents, (value) => Streamlit.setComponentValue(value));
}

function emitComponentEvent(event: ComponentEvent): void {
  pendingOutboundEvents.push(event);
  flushPendingOutboundEvents();
}

function safeEventId(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`;
}

function observeTranscriptEvent(event: TranscriptServerEvent): void {
  const eventId = itemIdFrom(event);
  if (!eventId) {
    return;
  }

  const nowMs = performance.now();
  const existing = state.ledger[eventId];

  if (event.type === "conversation.item.input_audio_transcription.delta") {
    state.activeItemIds.add(eventId);
    if (!existing) {
      state.ledger[eventId] = { startedAtMs: nowMs, lastDeltaAtMs: nowMs };
      return;
    }

    state.ledger[eventId] = {
      startedAtMs: existing.startedAtMs,
      lastDeltaAtMs: Math.max(existing.lastDeltaAtMs, nowMs),
    };
    return;
  }

  if (event.type === "conversation.item.input_audio_transcription.completed" && existing) {
    state.activeItemIds.delete(eventId);
    state.ledger[eventId] = {
      startedAtMs: existing.startedAtMs,
      lastDeltaAtMs: Math.max(existing.lastDeltaAtMs, nowMs),
    };
  }
}

async function startSession(clientSecret: string): Promise<void> {
  if (state.connection || state.status === "connecting" || state.status === "recording") {
    return;
  }

  const generation = state.generation + 1;
  state.generation = generation;
  state.failedGeneration = null;
  state.status = "connecting";
  state.ledger = {};
  state.partials = {};
  state.sessionStartMs = performance.now();
  renderStatus();

  let peerConnection: RTCPeerConnection | null = null;
  let mediaStream: MediaStream | null = null;
  let dataChannel: RTCDataChannel | null = null;
  const isCurrent = () => isSessionGenerationCurrent(generation, state.generation, state.command);
  const resources = (): SessionResources => ({ connection: peerConnection, dataChannel, mediaStream });

  const failSession = (error: unknown): void => {
    if (!isCurrent() || state.failedGeneration === generation) {
      return;
    }
    state.failedGeneration = generation;
    cleanupSessionResources(resources());
    state.connection = null;
    state.dataChannel = null;
    state.mediaStream = null;
    state.ledger = {};
    state.activeItemIds = new Set();
    state.partials = {};
    state.sessionStartMs = null;
    state.clientSecret = null;
    state.status = "error";
    renderStatus();
    const errorEvent = eventForError(error);
    emitComponentEvent({
      type: errorEvent.type,
      event_id: safeEventId("session-error"),
      text: "",
      start_seconds: null,
      end_seconds: null,
      message: errorEvent.message,
    });
  };

  try {
    peerConnection = new RTCPeerConnection();
    state.connection = peerConnection;
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    if (!isCurrent()) {
      cleanupSessionResources(resources());
      return;
    }

    const [track] = mediaStream.getAudioTracks();
    if (!track) {
      throw new Error("Microphone did not provide an audio track");
    }

    peerConnection.addTrack(track, mediaStream);
    state.mediaStream = mediaStream;
    dataChannel = peerConnection.createDataChannel("oai-events");
    state.dataChannel = dataChannel;
    const sessionId = safeEventId("session");

    dataChannel.addEventListener("message", (messageEvent) => {
      if (generation !== state.generation || !["start", "stopping"].includes(state.command)) {
        return;
      }
      let parsed: unknown;
      try {
        parsed = JSON.parse(String(messageEvent.data));
      } catch {
        return;
      }

      const transcriptEvent = parsed as TranscriptServerEvent;
      observeTranscriptEvent(transcriptEvent);
      const accumulatedText = accumulateTranscriptDelta(state.partials, transcriptEvent);
      const normalized = eventForTranscript(
        accumulatedText === null ? transcriptEvent : { ...transcriptEvent, delta: accumulatedText },
        itemIdFrom(transcriptEvent)
          ? approximateFinalTimes(String(transcriptEvent.item_id), state.ledger, performance.now(), state.sessionStartMs ?? 0)
          : { start_seconds: null, end_seconds: null },
      );
      if (!normalized) {
        return;
      }

      emitComponentEvent({ ...normalized, message: null });
    });

    dataChannel.addEventListener("open", () => {
      if (!isCurrent()) {
        return;
      }
      state.status = "recording";
      state.activeSessionId = sessionId;
      renderStatus();
      emitComponentEvent({
        type: "session_started",
        event_id: sessionId,
        text: "",
        start_seconds: null,
        end_seconds: null,
        message: null,
      });
    });

    dataChannel.addEventListener("error", () => {
      if (state.status !== "stopping") {
        failSession(new Error("Realtime data channel failed"));
      }
    });
    dataChannel.addEventListener("close", () => {
      if (isCurrent() && state.status !== "stopping") {
        failSession(new Error("Realtime data channel closed"));
      }
    });
    peerConnection.addEventListener("connectionstatechange", () => {
      if (isCurrent() && state.status !== "stopping" && ["failed", "closed"].includes(peerConnection?.connectionState ?? "")) {
        failSession(new Error(`Realtime peer connection ${peerConnection?.connectionState}`));
      }
    });

    if (!isCurrent()) {
      cleanupSessionResources(resources());
      return;
    }
    state.connection = peerConnection;
    state.dataChannel = dataChannel;
    state.mediaStream = mediaStream;

    const offer = await peerConnection.createOffer();
    if (!isCurrent()) {
      cleanupSessionResources(resources());
      return;
    }
    await peerConnection.setLocalDescription(offer);
    if (!isCurrent()) {
      cleanupSessionResources(resources());
      return;
    }

    const response = await fetch(REALTIME_CALLS_URL, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${clientSecret}`,
        "Content-Type": "application/sdp",
      },
      body: offer.sdp,
    });

    if (!response.ok) {
      throw new Error(`Realtime connection failed with status ${response.status}`);
    }

    const answerSdp = await response.text();
    if (!isCurrent()) {
      cleanupSessionResources(resources());
      return;
    }
    await peerConnection.setRemoteDescription({ type: "answer", sdp: answerSdp });
  } catch (error) {
    failSession(error);
  }
}

async function stopSession(): Promise<void> {
  if (state.stopPromise) {
    return state.stopPromise;
  }

  state.status = "stopping";
  renderStatus();

  state.stopPromise = (async () => {
    await finishStoppingSession(
      async () => {
        commitInputAudioBuffer(state.dataChannel);
        state.mediaStream?.getTracks().forEach((track) => {
          try {
            track.stop();
          } catch {
          }
        });
        await waitForDataChannelDrain(state.dataChannel, state.activeItemIds);
      },
      () => {
        emitComponentEvent(teardownSession("stopped"));
      },
      (error) => {
      const sessionId = state.activeSessionId ?? safeEventId("session");
      cleanupSessionResources({
        dataChannel: state.dataChannel,
        connection: state.connection,
        mediaStream: state.mediaStream,
      });
      state.connection = null;
      state.dataChannel = null;
      state.mediaStream = null;
      state.ledger = {};
      state.activeItemIds = new Set();
      state.partials = {};
      state.sessionStartMs = null;
      state.clientSecret = null;
      state.activeSessionId = null;
      state.status = "error";
      renderStatus();
      const errorEvent = eventForError(error);
      emitComponentEvent({
        type: errorEvent.type,
        event_id: sessionId,
        text: "",
        start_seconds: null,
        end_seconds: null,
        message: errorEvent.message,
      });
      },
    );
    state.stopPromise = null;
  })();

  return state.stopPromise;
}

function teardownSession(status: SessionState["status"]): ComponentEvent {
  cleanupSessionResources({
    dataChannel: state.dataChannel,
    connection: state.connection,
    mediaStream: state.mediaStream,
  });
  state.connection = null;
  state.dataChannel = null;
  state.mediaStream = null;
  state.ledger = {};
  state.activeItemIds = new Set();
  state.partials = {};
  state.sessionStartMs = null;
  state.clientSecret = null;
  state.status = status;
  const sessionId = state.activeSessionId ?? safeEventId("session");
  state.activeSessionId = null;
  renderStatus();
  return {
    type: "session_stopped",
    event_id: sessionId,
    text: "",
    start_seconds: null,
    end_seconds: null,
    message: null,
  };
}

async function reconcileCommand(command: ComponentCommand, clientSecret: string | null): Promise<void> {
  if (command === "start") {
    if (!clientSecret || !clientSecret.trim()) {
      const errorEvent = eventForError(new Error("Missing client secret"));
      state.status = "error";
      renderStatus();
      emitComponentEvent({
        type: errorEvent.type,
        event_id: safeEventId("session-error"),
        text: "",
        start_seconds: null,
        end_seconds: null,
        message: errorEvent.message,
      });
      return;
    }

    await startSession(clientSecret);
    return;
  }

  if (command === "stop" && (state.connection || state.mediaStream || state.status === "recording" || state.status === "connecting" || state.status === "stopping")) {
    await stopSession();
  }
}

function onRender(event: Event): void {
  const renderEvent = event as CustomEvent<RenderData>;
  const args = (renderEvent.detail.args ?? {}) as {
    client_secret?: string | null;
    command?: ComponentCommand;
  };

  const command = args.command ?? "idle";
  const clientSecret = typeof args.client_secret === "string" ? args.client_secret : null;

  const commandChanged = command !== state.command;
  const secretChanged = clientSecret !== state.clientSecret;
  state.command = command;
  state.clientSecret = clientSecret;

  acknowledgeOutboundEvents();

  renderStatus();

  if (commandChanged || (command === "start" && secretChanged)) {
    void reconcileCommand(command, clientSecret);
  }
}

export function bootstrap(): void {
  if (typeof document === "undefined") {
    return;
  }

  root = document.getElementById("root");
  if (!root) {
    throw new Error("Missing root element");
  }

  Streamlit.events.addEventListener(Streamlit.RENDER_EVENT, onRender as EventListener);
  Streamlit.setComponentReady();
  renderStatus();
}

bootstrap();