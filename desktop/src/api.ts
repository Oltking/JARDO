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

// ---- Providers (spec §5) — paste a Fireworks or AMD key; Jardo uses it. ----

export interface ProviderStatus {
  name: string;
  label: string;
  has_key: boolean;
  base_url: string;
  ready: boolean;
}

export interface ProvidersInfo {
  providers: ProviderStatus[];
  active: string[];
}

export async function getProviders(): Promise<ProvidersInfo> {
  try {
    return await invoke<ProvidersInfo>("get_providers");
  } catch (e) {
    throw toApiError(e);
  }
}

export async function setProvider(
  name: string,
  apiKey: string | null,
  baseUrl: string | null
): Promise<ProvidersInfo> {
  try {
    return await invoke<ProvidersInfo>("set_provider", { name, apiKey, baseUrl });
  } catch (e) {
    throw toApiError(e);
  }
}

// ---- Identity + Projects (spec §1, §4.5) ----------------------------------

export interface Identity {
  name: string | null;
  pronoun_style: string | null;
}

export async function getIdentity(): Promise<Identity> {
  return invoke<Identity>("get_identity");
}

export async function setIdentity(
  name: string | null,
  pronounStyle: string | null
): Promise<Identity> {
  try {
    return await invoke<Identity>("set_identity", { name, pronounStyle });
  } catch (e) {
    throw toApiError(e);
  }
}

export interface WhereAmI {
  needs_folder?: boolean;
  found?: boolean;
  name?: string;
  path?: string;
  goal?: string | null;
  last_focus?: string | null;
  last_active?: string | null;
  done?: string[];
  current?: string[];
  attention?: string[];
  branch?: string | null;
  from_agent_memory?: boolean;
  spoken?: string;
}

export async function whereAmI(path: string | null): Promise<WhereAmI> {
  try {
    return await invoke<WhereAmI>("where_am_i", { path });
  } catch (e) {
    throw toApiError(e);
  }
}

export async function chooseProject(): Promise<{ path: string }> {
  try {
    return await invoke<{ path: string }>("choose_project");
  } catch (e) {
    throw toApiError(e);
  }
}

export interface ProjectsInfo {
  root: string | null;
  folders: { name: string; path: string; is_git: boolean }[];
  tracked: { name: string; path: string; goal: string | null; last_opened_at: string }[];
}

export async function getProjects(): Promise<ProjectsInfo> {
  return invoke<ProjectsInfo>("get_projects");
}

export async function getProjectsRoot(): Promise<{ root: string | null }> {
  return invoke<{ root: string | null }>("get_projects_root");
}

export async function setProjectsRoot(
  path: string | null
): Promise<{ root: string }> {
  try {
    return await invoke<{ root: string }>("set_projects_root", { path });
  } catch (e) {
    throw toApiError(e);
  }
}

// ---- Terminal supervision (spec §4.3) -------------------------------------

export interface TickResult {
  watching: boolean;
  readable?: boolean;
  prompt?: boolean;
  answered?: boolean;
  approved?: boolean;
  pressed?: boolean;
  needs_accessibility?: boolean;
  already?: boolean;
  action?: string;
  reason?: string;
  answer?: string;
  tail?: string;
  detail?: string;
}

export async function terminalSupervise(
  goal: string,
  agent: string
): Promise<{ watching: boolean; goal: string; agent: string }> {
  try {
    return await invoke("terminal_supervise", { goal, agent });
  } catch (e) {
    throw toApiError(e);
  }
}

export async function terminalTick(): Promise<TickResult> {
  try {
    return await invoke<TickResult>("terminal_tick");
  } catch (e) {
    throw toApiError(e);
  }
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
  heard: boolean; // false = no speech within the listen timeout (silence)
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

export async function voiceWake(timeout: number): Promise<{ detected: boolean }> {
  try {
    return await invoke<{ detected: boolean }>("voice_wake", { timeout });
  } catch (e) {
    throw toApiError(e);
  }
}

export interface Briefing {
  greeting: string;
  updates: string[];
  has_updates: boolean;
  active_objective: string | null;
  prompt: string;
  spoken: string;
  owner: boolean;
}

export async function getBriefing(): Promise<Briefing> {
  try {
    return await invoke<Briefing>("briefing");
  } catch (e) {
    throw toApiError(e);
  }
}

export async function setObjective(objective: string): Promise<void> {
  try {
    await invoke("set_objective", { objective });
  } catch (e) {
    throw toApiError(e);
  }
}

// ---- Conversational build front-door -------------------------------------

export interface IntakeResponse {
  session_id: string;
  reply: string;
  ready: boolean;
  brief: string | null;
  agent: string;
  what: string;
}

export interface BuildRunResponse {
  agent: string;
  model: string | null;
  executed: boolean;
  visible: boolean;
  workspace: { path: string; created: boolean; spec_file?: string | null };
  note: string;
  warnings: string[];
  output: string;
}

export async function buildIntake(
  message: string,
  sessionId: string | null
): Promise<IntakeResponse> {
  try {
    return await invoke<IntakeResponse>("build_intake", { message, sessionId });
  } catch (e) {
    throw toApiError(e);
  }
}

export async function buildRun(
  sessionId: string,
  directory: string,
  run: boolean
): Promise<BuildRunResponse> {
  try {
    return await invoke<BuildRunResponse>("build_run", { sessionId, directory, run });
  } catch (e) {
    throw toApiError(e);
  }
}

export interface Report {
  id: string;
  period: string;
  body: string;
  stats: Record<string, number | string>;
  created_at: string;
}

export async function listReports(): Promise<Report[]> {
  return invoke<Report[]>("list_reports");
}

export async function generateReport(period: string): Promise<Report> {
  try {
    return await invoke<Report>("generate_report", { period });
  } catch (e) {
    throw toApiError(e);
  }
}

// ---- Coding environments + agent decisions (Agents tab) -------------------

export interface CodingInventory {
  editors: Record<string, string>;
  terminals: string[];
  shells: Record<string, string>;
  agents: Record<string, string>;
  clis: Record<string, string>;
}

export interface AgentDecision {
  ts: string;
  actor: string;
  event: string; // "prompt.answered" | "action.review"
  detail: Record<string, unknown>;
}

export async function codingTools(): Promise<CodingInventory> {
  return invoke<CodingInventory>("coding_tools");
}

export async function codingDecisions(): Promise<AgentDecision[]> {
  return invoke<AgentDecision[]>("coding_decisions");
}

// Fires the kill-switch stub in Rust (logs + emits `kill-switch`). Real
// synthetic-input halting lands in Phase 7 (spec §7.3).
export async function killSwitch(source: string): Promise<void> {
  return invoke("kill_switch", { source });
}
