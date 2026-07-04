// JARVIS desktop shell — Rust core (Phase 5).
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
    std::env::var("JARVIS_CORE_URL").unwrap_or_else(|_| "http://127.0.0.1:8000".to_string())
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
    reqwest::Client::builder()
        .build()
        .map_err(ApiError::transport)
}

/// Deserialize a successful JSON response, mapping non-2xx to a status-bearing
/// `ApiError` so the frontend can react (e.g. show the "run jarvis setup" banner
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
    eprintln!("[JARVIS] KILL-SWITCH engaged (source: {source})");
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
    let show_i = MenuItem::with_id(app, "show", "Show JARVIS", true, None::<&str>)?;
    let hide_i = MenuItem::with_id(app, "hide", "Hide window", true, None::<&str>)?;
    let kill_i = MenuItem::with_id(
        app,
        "kill_switch",
        "Kill switch (halt synthetic input)",
        true,
        None::<&str>,
    )?;
    let sep = PredefinedMenuItem::separator(app)?;
    let quit_i = MenuItem::with_id(app, "quit", "Quit JARVIS", true, None::<&str>)?;

    let menu = Menu::with_items(app, &[&show_i, &hide_i, &sep, &kill_i, &sep, &quit_i])?;

    TrayIconBuilder::with_id("jarvis-tray")
        .icon(app.default_window_icon().unwrap().clone())
        .tooltip("JARVIS")
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
            get_memory,
            get_approvals,
            decide_approval,
            kill_switch
        ])
        .run(tauri::generate_context!())
        .expect("error while running JARVIS desktop app");
}
