// Jardo desktop shell — Rust core (Phase 5).
//
// Responsibilities:
//   * Proxy the frontend's backend traffic to the core at 127.0.0.1:8000 via
//     reqwest so the webview never touches CORS (Tauri commands below).
//   * System tray with show/hide, a kill-switch stub, and quit (system-tray.md).
//   * Global kill-switch hotkey plugin init (plugin-global-shortcut.md); the
//     shortcut itself is registered from the frontend and calls `kill_switch`.
//
// Real synthetic-input halting is Phase 7 (spec §7.3); the kill switch here logs
// and broadcasts a `kill-switch` event so every surface (tray, hotkey, header)
// shares one code path.

use serde::{Deserialize, Serialize};
use tauri::{
    menu::{Menu, MenuItem, PredefinedMenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Emitter, Manager,
};

/// Base URL of the core. Overridable for tests / non-default deployments.
fn core_base() -> String {
    std::env::var("JARDO_CORE_URL").unwrap_or_else(|_| "http://127.0.0.1:8000".to_string())
}

/// Read the shared API token (written by the core to ~/.jardo/api_token).
fn api_token() -> Option<String> {
    let home = std::env::var("HOME")
        .or_else(|_| std::env::var("USERPROFILE"))
        .ok()?;
    std::fs::read_to_string(std::path::Path::new(&home).join(".jardo").join("api_token"))
        .ok()
        .map(|s| s.trim().to_string())
}

/// Error surfaced to the frontend. `status` mirrors the HTTP status code so the
/// UI can special-case 409 (not set up), 429 (budget), 502 (model), etc.
#[derive(Debug, Serialize)]
struct ApiError {
    status: Option<u16>,
    message: String,
}

impl ApiError {
    fn transport(e: impl std::fmt::Display) -> Self {
        ApiError {
            status: None,
            message: format!("Could not reach the core: {e}"),
        }
    }
}

fn client() -> Result<reqwest::Client, ApiError> {
    let mut headers = reqwest::header::HeaderMap::new();
    if let Some(token) = api_token() {
        if let Ok(value) = format!("Bearer {token}").parse() {
            headers.insert(reqwest::header::AUTHORIZATION, value);
        }
    }
    reqwest::Client::builder()
        .default_headers(headers)
        .build()
        .map_err(ApiError::transport)
}

/// Deserialize a successful JSON response, mapping non-2xx to a status-bearing
/// `ApiError` so the frontend can react (e.g. show the "run jardo setup" banner
/// on 409).
async fn parse_json<T: for<'de> Deserialize<'de>>(
    resp: reqwest::Response,
) -> Result<T, ApiError> {
    let status = resp.status();
    if status.is_success() {
        resp.json::<T>().await.map_err(|e| ApiError {
            status: Some(status.as_u16()),
            message: format!("Malformed response from core: {e}"),
        })
    } else {
        let body = resp.text().await.unwrap_or_default();
        Err(ApiError {
            status: Some(status.as_u16()),
            message: if body.is_empty() {
                format!("Core returned HTTP {status}")
            } else {
                body
            },
        })
    }
}

// ---------------------------------------------------------------------------
// Data contracts (mirror the backend contract in the Phase 5 brief).
// ---------------------------------------------------------------------------

#[derive(Serialize, Deserialize)]
struct HealthStatus {
    status: String,
    db: String,
    redis: String,
}

#[derive(Serialize)]
struct ChatRequest<'a> {
    message: &'a str,
    conversation_id: Option<String>,
}

#[derive(Serialize, Deserialize)]
struct ChatReply {
    reply: String,
    conversation_id: String,
    model: String,
    prompt_tokens: u32,
    completion_tokens: u32,
}

#[derive(Serialize, Deserialize)]
struct MemoryItem {
    id: String,
    kind: String,
    content: String,
    source: String,
}

#[derive(Serialize, Deserialize)]
struct Approval {
    id: String,
    actor: String,
    action_type: String,
    target: String,
    stated_goal: String,
    severity: String,
    created_at: String,
}

#[derive(Serialize)]
struct DecideRequest {
    approve: bool,
}

#[derive(Serialize, Deserialize)]
struct DecideResult {
    id: String,
    status: String,
}

// Voice (spec §8). The core drives the local mic/STT/TTS; these just proxy.
#[derive(Serialize)]
struct SayRequest<'a> {
    text: &'a str,
}

#[derive(Serialize)]
struct TranscribeRequest {
    seconds: f32,
}

#[derive(Serialize, Deserialize)]
struct TranscribeResult {
    transcript: String,
    amplitude: f32,
    #[serde(default)]
    heard: bool,
}

#[derive(Serialize, Deserialize)]
struct SayResult {
    spoken: bool,
}

// ---------------------------------------------------------------------------
// Tauri commands — the frontend calls these via `invoke(...)`.
// ---------------------------------------------------------------------------

#[tauri::command]
async fn health() -> Result<HealthStatus, ApiError> {
    let resp = client()?
        .get(format!("{}/healthz", core_base()))
        .send()
        .await
        .map_err(ApiError::transport)?;
    parse_json(resp).await
}

#[tauri::command]
async fn send_chat(
    message: String,
    conversation_id: Option<String>,
) -> Result<ChatReply, ApiError> {
    let body = ChatRequest {
        message: &message,
        conversation_id,
    };
    let resp = client()?
        .post(format!("{}/chat", core_base()))
        .json(&body)
        .send()
        .await
        .map_err(ApiError::transport)?;
    parse_json(resp).await
}

#[tauri::command]
async fn get_providers() -> Result<serde_json::Value, ApiError> {
    let resp = client()?
        .get(format!("{}/settings/providers", core_base()))
        .send()
        .await
        .map_err(ApiError::transport)?;
    parse_json(resp).await
}

#[tauri::command]
async fn set_provider(
    name: String,
    api_key: Option<String>,
    base_url: Option<String>,
) -> Result<serde_json::Value, ApiError> {
    let resp = client()?
        .post(format!("{}/settings/providers/{}", core_base(), name))
        .json(&serde_json::json!({ "api_key": api_key, "base_url": base_url }))
        .send()
        .await
        .map_err(ApiError::transport)?;
    parse_json(resp).await
}

#[tauri::command]
async fn get_identity() -> Result<serde_json::Value, ApiError> {
    let resp = client()?
        .get(format!("{}/settings/identity", core_base()))
        .send().await.map_err(ApiError::transport)?;
    parse_json(resp).await
}

#[tauri::command]
async fn set_identity(
    name: Option<String>,
    pronoun_style: Option<String>,
) -> Result<serde_json::Value, ApiError> {
    let resp = client()?
        .post(format!("{}/settings/identity", core_base()))
        .json(&serde_json::json!({ "name": name, "pronoun_style": pronoun_style }))
        .send().await.map_err(ApiError::transport)?;
    parse_json(resp).await
}

#[tauri::command]
async fn get_projects() -> Result<serde_json::Value, ApiError> {
    let resp = client()?
        .get(format!("{}/projects", core_base()))
        .send().await.map_err(ApiError::transport)?;
    parse_json(resp).await
}

#[tauri::command]
async fn get_projects_root() -> Result<serde_json::Value, ApiError> {
    let resp = client()?
        .get(format!("{}/settings/projects-root", core_base()))
        .send().await.map_err(ApiError::transport)?;
    parse_json(resp).await
}

#[tauri::command]
async fn set_projects_root(path: Option<String>) -> Result<serde_json::Value, ApiError> {
    let resp = client()?
        .post(format!("{}/settings/projects-root", core_base()))
        .json(&serde_json::json!({ "path": path }))
        .timeout(std::time::Duration::from_secs(180))
        .send().await.map_err(ApiError::transport)?;
    parse_json(resp).await
}

#[tauri::command]
async fn choose_project() -> Result<serde_json::Value, ApiError> {
    let resp = client()?
        .post(format!("{}/projects/choose", core_base()))
        .timeout(std::time::Duration::from_secs(180))
        .send().await.map_err(ApiError::transport)?;
    parse_json(resp).await
}

#[tauri::command]
async fn where_am_i(path: Option<String>) -> Result<serde_json::Value, ApiError> {
    let resp = client()?
        .post(format!("{}/projects/whereami", core_base()))
        .json(&serde_json::json!({ "path": path }))
        .timeout(std::time::Duration::from_secs(60))
        .send().await.map_err(ApiError::transport)?;
    parse_json(resp).await
}

#[tauri::command]
async fn terminal_supervise(
    goal: String,
    agent: String,
) -> Result<serde_json::Value, ApiError> {
    let resp = client()?
        .post(format!("{}/terminal/supervise", core_base()))
        .json(&serde_json::json!({ "goal": goal, "agent": agent }))
        .send()
        .await
        .map_err(ApiError::transport)?;
    parse_json(resp).await
}

#[tauri::command]
async fn terminal_tick() -> Result<serde_json::Value, ApiError> {
    let resp = client()?
        .post(format!("{}/terminal/tick", core_base()))
        .timeout(std::time::Duration::from_secs(30))
        .send()
        .await
        .map_err(ApiError::transport)?;
    parse_json(resp).await
}

#[tauri::command]
async fn get_memory() -> Result<Vec<MemoryItem>, ApiError> {
    let resp = client()?
        .get(format!("{}/memory", core_base()))
        .send()
        .await
        .map_err(ApiError::transport)?;
    parse_json(resp).await
}

#[tauri::command]
async fn get_approvals() -> Result<Vec<Approval>, ApiError> {
    let resp = client()?
        .get(format!("{}/approvals", core_base()))
        .send()
        .await
        .map_err(ApiError::transport)?;
    parse_json(resp).await
}

#[tauri::command]
async fn decide_approval(id: String, approve: bool) -> Result<DecideResult, ApiError> {
    let resp = client()?
        .post(format!("{}/approvals/{}/decide", core_base(), id))
        .json(&DecideRequest { approve })
        .send()
        .await
        .map_err(ApiError::transport)?;
    parse_json(resp).await
}

/// One turn of the conversational build interview.
#[tauri::command]
async fn build_intake(
    message: String,
    session_id: Option<String>,
) -> Result<serde_json::Value, ApiError> {
    let resp = client()?
        .post(format!("{}/build/intake", core_base()))
        .json(&serde_json::json!({ "message": message, "session_id": session_id }))
        .timeout(std::time::Duration::from_secs(180))
        .send()
        .await
        .map_err(ApiError::transport)?;
    parse_json(resp).await
}

/// Write the brief and conduct the agent (run=true actually launches it).
#[tauri::command]
async fn build_run(
    session_id: String,
    directory: String,
    run: bool,
) -> Result<serde_json::Value, ApiError> {
    let resp = client()?
        .post(format!("{}/build/run", core_base()))
        .json(&serde_json::json!({
            "session_id": session_id, "directory": directory, "run": run
        }))
        .timeout(std::time::Duration::from_secs(1800))
        .send()
        .await
        .map_err(ApiError::transport)?;
    parse_json(resp).await
}

/// Reports inbox: recent hourly/daily/weekly rollups (§4.4).
#[tauri::command]
async fn list_reports() -> Result<serde_json::Value, ApiError> {
    let resp = client()?
        .get(format!("{}/reports", core_base()))
        .send()
        .await
        .map_err(ApiError::transport)?;
    parse_json(resp).await
}

/// Generate a fresh report for a period (hourly|daily|weekly).
#[tauri::command]
async fn generate_report(period: String) -> Result<serde_json::Value, ApiError> {
    let resp = client()?
        .post(format!("{}/reports/generate", core_base()))
        .json(&serde_json::json!({ "period": period }))
        .send()
        .await
        .map_err(ApiError::transport)?;
    parse_json(resp).await
}

/// Launch briefing: greeting + updates + the day's-objective prompt (§4.5).
#[tauri::command]
async fn briefing() -> Result<serde_json::Value, ApiError> {
    let resp = client()?
        .get(format!("{}/briefing", core_base()))
        .send()
        .await
        .map_err(ApiError::transport)?;
    parse_json(resp).await
}

/// Set the day's objective; Jardo supervises agents against it (§4.3).
#[tauri::command]
async fn set_objective(objective: String) -> Result<serde_json::Value, ApiError> {
    let resp = client()?
        .post(format!("{}/supervision", core_base()))
        .json(&serde_json::json!({ "objective": objective }))
        .send()
        .await
        .map_err(ApiError::transport)?;
    parse_json(resp).await
}

/// Detected coding environments (editors/terminals/shells/agents) for the
/// Agents tab. Flexible JSON — the shape is a nested inventory.
#[tauri::command]
async fn coding_tools() -> Result<serde_json::Value, ApiError> {
    let resp = client()?
        .get(format!("{}/coding/tools", core_base()))
        .send()
        .await
        .map_err(ApiError::transport)?;
    parse_json(resp).await
}

/// Recent agent-prompt decisions + action reviews (audit log) for the Agents tab.
#[tauri::command]
async fn coding_decisions() -> Result<serde_json::Value, ApiError> {
    let resp = client()?
        .get(format!("{}/coding/decisions", core_base()))
        .send()
        .await
        .map_err(ApiError::transport)?;
    parse_json(resp).await
}

/// Voice status (spec §8): deps available, mic devices, selected device, TTS
/// backend. Returned as a flexible JSON value since the device list is nested.
#[tauri::command]
async fn voice_status() -> Result<serde_json::Value, ApiError> {
    let resp = client()?
        .get(format!("{}/voice/status", core_base()))
        .send()
        .await
        .map_err(ApiError::transport)?;
    parse_json(resp).await
}

/// Tap-to-talk: record `seconds` from the mic and transcribe locally (§8).
#[tauri::command]
async fn voice_transcribe(seconds: f32) -> Result<TranscribeResult, ApiError> {
    let resp = client()?
        .post(format!("{}/voice/transcribe", core_base()))
        .json(&TranscribeRequest { seconds })
        // STT + recording take a few seconds; give it generous headroom.
        .timeout(std::time::Duration::from_secs(120))
        .send()
        .await
        .map_err(ApiError::transport)?;
    parse_json(resp).await
}

/// Block until the wake word ("hey Jardo") is heard or timeout (§8).
#[tauri::command]
async fn voice_wake(timeout: f32) -> Result<serde_json::Value, ApiError> {
    let resp = client()?
        .post(format!("{}/voice/wake", core_base()))
        .json(&serde_json::json!({ "timeout": timeout }))
        .timeout(std::time::Duration::from_secs((timeout as u64) + 15))
        .send()
        .await
        .map_err(ApiError::transport)?;
    parse_json(resp).await
}

/// Speak text in Jardo's voice (§8).
#[tauri::command]
async fn voice_say(text: String) -> Result<SayResult, ApiError> {
    let resp = client()?
        .post(format!("{}/voice/say", core_base()))
        .json(&SayRequest { text: &text })
        .timeout(std::time::Duration::from_secs(60))
        .send()
        .await
        .map_err(ApiError::transport)?;
    parse_json(resp).await
}

/// Kill-switch stub (spec §7.3). Logs and broadcasts the `kill-switch` event so
/// the whole app reacts. Real synthetic-input halting arrives in Phase 7.
#[tauri::command]
fn kill_switch(app: AppHandle, source: String) -> Result<(), String> {
    fire_kill_switch(&app, &source);
    Ok(())
}

fn fire_kill_switch(app: &AppHandle, source: &str) {
    // Phase 7 will additionally call enigo/OS APIs to halt synthetic input.
    log::warn!("KILL-SWITCH engaged (source: {source}) — halting synthetic input (stub)");
    eprintln!("[Jardo] KILL-SWITCH engaged (source: {source})");
    let _ = app.emit("kill-switch", serde_json::json!({ "source": source }));
}

// ---------------------------------------------------------------------------
// Window helpers + tray.
// ---------------------------------------------------------------------------

fn show_main(app: &AppHandle) {
    if let Some(win) = app.get_webview_window("main") {
        let _ = win.unminimize();
        let _ = win.show();
        let _ = win.set_focus();
    }
}

fn hide_main(app: &AppHandle) {
    if let Some(win) = app.get_webview_window("main") {
        let _ = win.hide();
    }
}

/// Build the tray icon + menu (system-tray.md). Menu items:
///   show / hide window, kill-switch stub, quit.
fn build_tray(app: &AppHandle) -> tauri::Result<()> {
    let show_i = MenuItem::with_id(app, "show", "Show Jardo", true, None::<&str>)?;
    let hide_i = MenuItem::with_id(app, "hide", "Hide window", true, None::<&str>)?;
    let kill_i = MenuItem::with_id(
        app,
        "kill_switch",
        "Kill switch (halt synthetic input)",
        true,
        None::<&str>,
    )?;
    let sep = PredefinedMenuItem::separator(app)?;
    let quit_i = MenuItem::with_id(app, "quit", "Quit Jardo", true, None::<&str>)?;

    let menu = Menu::with_items(app, &[&show_i, &hide_i, &sep, &kill_i, &sep, &quit_i])?;

    TrayIconBuilder::with_id("jardo-tray")
        .icon(app.default_window_icon().unwrap().clone())
        .tooltip("Jardo")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "show" => show_main(app),
            "hide" => hide_main(app),
            "kill_switch" => fire_kill_switch(app, "tray-menu"),
            "quit" => app.exit(0),
            other => log::debug!("unhandled tray menu item {other:?}"),
        })
        // Left-click the tray icon to toggle the main window into view.
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                show_main(tray.app_handle());
            }
        })
        .build(app)?;
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(
            // Global-shortcut plugin init (plugin-global-shortcut.md). The
            // kill-switch hotkey itself is registered from the frontend, which
            // calls the `kill_switch` command — keeping tray + hotkey unified.
            tauri_plugin_global_shortcut::Builder::new().build(),
        )
        .setup(|app| {
            let handle = app.handle();
            #[cfg(desktop)]
            build_tray(handle)?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            health,
            send_chat,
            get_providers,
            set_provider,
            get_identity,
            set_identity,
            get_projects,
            get_projects_root,
            set_projects_root,
            choose_project,
            where_am_i,
            terminal_supervise,
            terminal_tick,
            get_memory,
            get_approvals,
            decide_approval,
            voice_status,
            voice_transcribe,
            voice_wake,
            voice_say,
            briefing,
            set_objective,
            build_intake,
            build_run,
            list_reports,
            generate_report,
            coding_tools,
            coding_decisions,
            kill_switch
        ])
        .run(tauri::generate_context!())
        .expect("error while running Jardo desktop app");
}
