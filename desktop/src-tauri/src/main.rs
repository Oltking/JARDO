// Prevents an additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

// start-project-structure.md: keep main.rs a thin shim; real logic is in lib.rs
// so desktop and mobile share one entry point.
fn main() {
    jarvis_desktop_lib::run()
}
