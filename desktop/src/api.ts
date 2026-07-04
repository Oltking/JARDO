// API layer for the Jardo desktop shell.
//
// All backend traffic is proxied through the Rust side via Tauri commands
// (see src-tauri/src/lib.rs). Proxying through Rust with reqwest avoids the
// webview CORS surface entirely, per the Phase 5 brief.
import { invoke } from "@tauri-apps/api/core";

export interface HealthStatus {
  status: string;
  db: string;
  redis: string;
}

export interface ChatReply {
  reply: string;
  conversation_id: string;
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
}

export interface MemoryItem {
  id: string;
  kind: string;
  content: string;
  source: string;
}

export interface Approval {
  id: string;
  actor: string;
  action_type: string;
  target: string;
  stated_goal: string;
  severity: string;
  created_at: string;
}

export interface DecideResult {
  id: string;
  status: string;
}

// A typed error the Rust side returns for non-2xx responses. `status` mirrors
// the HTTP status code so the UI can special-case 409 (not set up) etc.
export interface ApiError {
  status: number | null;
  message: string;
}

function toApiError(e: unknown): ApiError {
  if (e && typeof e === "object" && "message" in e) {
    return e as ApiError;
  }
  return { status: null, message: String(e) };
}

export async function health(): Promise<HealthStatus> {
  return invoke<HealthStatus>("health");
}

export async function sendChat(
  message: string,
  conversationId: string | null
): Promise<ChatReply> {
  try {
    return await invoke<ChatReply>("send_chat", {
      message,
      conversationId,
    });
  } catch (e) {
    throw toApiError(e);
  }
}

export async function getApprovals(): Promise<Approval[]> {
  return invoke<Approval[]>("get_approvals");
}

export async function decideApproval(
  id: string,
  approve: boolean
): Promise<DecideResult> {
  return invoke<DecideResult>("decide_approval", { id, approve });
}

export async function getMemory(): Promise<MemoryItem[]> {
  return invoke<MemoryItem[]>("get_memory");
}

// ---- Voice (spec §8) ------------------------------------------------------

export interface VoiceInputDevice {
  index: number;
  name: string;
}

export interface VoiceStatus {
  available: boolean;
  reason?: string;
  tts_backend?: string;
  tts_voice?: string;
  input_devices?: VoiceInputDevice[];
  selected_device?: number | null;
}

export interface TranscribeResult {
  transcript: string;
  amplitude: number;
}

export async function voiceStatus(): Promise<VoiceStatus> {
  try {
    return await invoke<VoiceStatus>("voice_status");
  } catch (e) {
    throw toApiError(e);
  }
}

export async function voiceTranscribe(seconds: number): Promise<TranscribeResult> {
  try {
    return await invoke<TranscribeResult>("voice_transcribe", { seconds });
  } catch (e) {
    throw toApiError(e);
  }
}

export async function voiceSay(text: string): Promise<void> {
  try {
    await invoke("voice_say", { text });
  } catch (e) {
    throw toApiError(e);
  }
}

// Fires the kill-switch stub in Rust (logs + emits `kill-switch`). Real
// synthetic-input halting lands in Phase 7 (spec §7.3).
export async function killSwitch(source: string): Promise<void> {
  return invoke("kill_switch", { source });
}
