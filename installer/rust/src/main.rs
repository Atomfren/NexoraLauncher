//! Установщик NexoraLauncher.
//!
//! Один и тот же exe работает в двух режимах:
//! * с пакетом в конце файла — установщик (см. `payload.rs`);
//! * без пакета (`uninstall.exe` в папке программы) или с `--uninstall` — деинсталлятор.
//!
//! Параметры: `--silent` (`/S`, `/VERYSILENT`) — без окна; `--dir <папка>`; `--no-desktop`;
//! `--launch`; для удаления `--remove-data`.

#![windows_subsystem = "windows"]

mod app;
mod art;
mod ops;
mod sys;

use std::path::{Path, PathBuf};
use std::process::{Command, ExitCode};
use std::sync::Arc;

use eframe::egui;
use nexora_setup::payload::Trailer;

use app::{App, Mode};

struct Args(Vec<String>);

impl Args {
    fn flag(&self, names: &[&str]) -> bool {
        self.0.iter().any(|a| names.iter().any(|n| a.eq_ignore_ascii_case(n)))
    }

    fn value(&self, name: &str) -> Option<String> {
        let i = self.0.iter().position(|a| a.eq_ignore_ascii_case(name))?;
        self.0.get(i + 1).cloned()
    }
}

fn main() -> ExitCode {
    let args = Args(std::env::args().skip(1).collect());
    let silent = args.flag(&["--silent", "/S", "/SILENT", "/VERYSILENT"]);
    let exe = std::env::current_exe().unwrap_or_default();
    let trailer = Trailer::read_from(&exe).ok().flatten();

    let mode = match trailer {
        Some(trailer) if !args.flag(&["--uninstall"]) => {
            let existing = sys::find_existing();
            Mode::Install { exe: exe.clone(), trailer, existing }
        }
        _ => match uninstall_target(&args, &exe) {
            Some((dir, version)) => {
                // Из папки программы себя не удалить — работаем из временной копии
                if !args.flag(&["--temp"]) && dir.join(sys::UNINSTALL_EXE).exists() && exe.starts_with(&dir) {
                    return relaunch_from_temp(&exe, &dir, silent);
                }
                Mode::Uninstall { dir, version }
            }
            None => Mode::Broken(
                "В этом файле нет данных для установки, и Nexora на компьютере не найден. Скачайте установщик заново."
                    .into(),
            ),
        },
    };
    let temp_self = args.flag(&["--temp"]).then(|| exe.clone());

    let code = if silent { run_silent(mode, &args) } else { run_gui(mode) };
    if let Some(path) = temp_self {
        sys::delete_after_exit(&path);
    }
    code
}

/// Что удалять: папка из `--app-dir`, иначе папка самого exe, иначе запись в реестре.
fn uninstall_target(args: &Args, exe: &Path) -> Option<(PathBuf, String)> {
    let existing = sys::find_existing();
    let version = existing.as_ref().map(|e| e.version.clone()).unwrap_or_default();
    if let Some(dir) = args.value("--app-dir") {
        return Some((PathBuf::from(dir), version));
    }
    if let Some(dir) = exe.parent().filter(|d| d.join(sys::APP_EXE).exists()) {
        return Some((dir.to_path_buf(), version));
    }
    existing.filter(|e| e.inno_uninstall.is_none()).map(|e| (e.dir, version))
}

fn relaunch_from_temp(exe: &Path, dir: &Path, silent: bool) -> ExitCode {
    let temp = std::env::temp_dir().join(format!("nexora-uninstall-{}.exe", std::process::id()));
    if std::fs::copy(exe, &temp).is_err() {
        return ExitCode::FAILURE;
    }
    let mut cmd = Command::new(&temp);
    cmd.arg("--uninstall").arg("--temp").arg("--app-dir").arg(dir);
    if silent {
        cmd.arg("--silent");
    }
    for extra in ["--remove-data"] {
        if std::env::args().any(|a| a.eq_ignore_ascii_case(extra)) {
            cmd.arg(extra);
        }
    }
    match cmd.spawn() {
        Ok(_) => ExitCode::SUCCESS,
        Err(_) => ExitCode::FAILURE,
    }
}

fn run_silent(mode: Mode, args: &Args) -> ExitCode {
    let progress = ops::Progress::default();
    let result = match mode {
        Mode::Install { exe, trailer, existing } => {
            let target = args
                .value("--dir")
                .map(PathBuf::from)
                .or(existing.map(|e| e.dir))
                .unwrap_or_else(sys::default_install_dir);
            let opts = ops::InstallOptions {
                target: target.clone(),
                desktop_shortcut: !args.flag(&["--no-desktop"]),
                exe,
                trailer,
            };
            ops::install(opts, &progress).and_then(|()| {
                if args.flag(&["--launch"]) { sys::launch(&target).map_err(|e| e.to_string()) } else { Ok(()) }
            })
        }
        Mode::Uninstall { dir, .. } => ops::uninstall(&dir, args.flag(&["--remove-data"]), &progress),
        Mode::Broken(e) => Err(e),
    };
    if result.is_ok() { ExitCode::SUCCESS } else { ExitCode::FAILURE }
}

fn run_gui(mode: Mode) -> ExitCode {
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_title(match mode {
                Mode::Uninstall { .. } => "Удаление Nexora",
                _ => "Установка Nexora",
            })
            .with_inner_size(app::WINDOW)
            .with_resizable(false)
            .with_maximize_button(false)
            .with_decorations(false)
            .with_transparent(true)
            .with_icon(Arc::new(art::window_icon())),
        centered: true,
        ..Default::default()
    };
    let res = eframe::run_native("nexora-setup", options, Box::new(|cc| Ok(Box::new(App::new(cc, mode)))));
    if res.is_ok() { ExitCode::SUCCESS } else { ExitCode::FAILURE }
}
