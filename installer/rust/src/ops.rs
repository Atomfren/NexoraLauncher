//! Установка и удаление. Работают в отдельном потоке и сообщают прогресс через [`Progress`].

use std::fs;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};

use nexora_setup::payload::{self, Counting, Trailer};

use crate::sys;

/// Общее состояние «рабочий поток ↔ окно».
#[derive(Default)]
pub struct Progress {
    /// Байты, уже распакованные из пакета, — для плавной полосы во время копирования.
    pub bytes: Arc<AtomicU64>,
    state: Mutex<State>,
}

#[derive(Default, Clone)]
pub struct State {
    pub status: String,
    /// Отрезок общей полосы, который занимает текущий шаг.
    pub lo: f32,
    pub hi: f32,
    /// Сколько байт ждём на этом шаге (0 — шаг без счётчика).
    pub total: u64,
    pub outcome: Option<Result<(), String>>,
}

impl Progress {
    fn step(&self, status: &str, lo: f32, hi: f32, total: u64) {
        self.bytes.store(0, Ordering::Relaxed);
        let mut s = self.state.lock().unwrap();
        s.status = status.into();
        s.lo = lo;
        s.hi = hi;
        s.total = total;
    }

    fn finish(&self, outcome: Result<(), String>) {
        let mut s = self.state.lock().unwrap();
        if outcome.is_ok() {
            s.lo = 1.0;
            s.hi = 1.0;
        }
        s.outcome = Some(outcome);
    }

    pub fn snapshot(&self) -> (State, f32) {
        let s = self.state.lock().unwrap().clone();
        let part = if s.total > 0 {
            (self.bytes.load(Ordering::Relaxed) as f64 / s.total as f64).min(1.0) as f32
        } else {
            0.0
        };
        let frac = s.lo + (s.hi - s.lo) * part;
        (s, frac)
    }
}

pub struct InstallOptions {
    pub target: PathBuf,
    pub desktop_shortcut: bool,
    pub exe: PathBuf,
    pub trailer: Trailer,
}

/// Запускает работу в фоне; панике тоже не даём потеряться — она станет ошибкой.
pub fn spawn<F>(progress: Arc<Progress>, job: F)
where
    F: FnOnce(&Progress) -> Result<(), String> + Send + std::panic::UnwindSafe + 'static,
{
    std::thread::spawn(move || {
        let p = progress.clone();
        let res = std::panic::catch_unwind(move || job(&p))
            .unwrap_or_else(|_| Err("Внутренняя ошибка установщика.".into()));
        progress.finish(res);
    });
}

fn sibling(dir: &Path, suffix: &str) -> PathBuf {
    let name = dir.file_name().map_or_else(|| "app".into(), |n| n.to_string_lossy().to_string());
    dir.with_file_name(format!("{name}.{suffix}"))
}

pub fn install(o: InstallOptions, p: &Progress) -> Result<(), String> {
    sys::check_target(&o.target)?;

    if sys::is_running() {
        p.step("Закрываю Nexora…", 0.0, 0.02, 0);
        sys::close_running()?;
    }

    // Старая версия на Inno Setup: удаляем её деинсталлятором, данные пользователя остаются
    if let Some(cmd) = sys::find_existing().and_then(|e| e.inno_uninstall) {
        p.step("Удаляю предыдущую версию…", 0.02, 0.08, 0);
        sys::run_inno_uninstall(&cmd)?;
    }

    // 1. Распаковка во временную папку рядом с целевой
    let staging = sibling(&o.target, "~nxnew");
    sys::remove_dir_retry(&staging).map_err(|e| format!("{}: {e}", staging.display()))?;
    fs::create_dir_all(&staging).map_err(|e| format!("Не удалось создать папку {}: {e}", staging.display()))?;
    p.step("Распаковываю файлы…", 0.08, 0.9, o.trailer.unpacked_len);
    let result = extract(&o, &staging, p);
    if let Err(e) = result {
        let _ = sys::remove_dir_retry(&staging);
        return Err(e);
    }

    // 2. Подмена папки программы целиком: старые файлы обновления не остаются
    p.step("Заменяю файлы…", 0.9, 0.94, 0);
    let old = sibling(&o.target, "~nxold");
    sys::remove_dir_retry(&old).map_err(|e| format!("{}: {e}", old.display()))?;
    if o.target.exists() {
        sys::rename_retry(&o.target, &old).map_err(|e| {
            let _ = sys::remove_dir_retry(&staging);
            format!("Папка {} занята другой программой ({e}). Закройте её и повторите.", o.target.display())
        })?;
    }
    if let Err(e) = sys::rename_retry(&staging, &o.target) {
        if old.exists() {
            let _ = fs::rename(&old, &o.target);
        }
        return Err(format!("Не удалось переместить файлы в {}: {e}", o.target.display()));
    }
    let _ = sys::remove_dir_retry(&old);

    // 3. Деинсталлятор = этот же exe без пакета
    p.step("Регистрирую в системе…", 0.94, 1.0, 0);
    write_uninstaller(&o.exe, o.trailer.stub_len, &o.target.join(sys::UNINSTALL_EXE))?;

    // 4. Ярлыки и запись в «Приложения»
    sys::remove_legacy_shortcuts();
    if let Some(lnk) = sys::start_menu_shortcut() {
        sys::create_shortcut(&lnk, &o.target)?;
    }
    if let Some(lnk) = sys::desktop_shortcut() {
        if o.desktop_shortcut {
            sys::create_shortcut(&lnk, &o.target)?;
        } else {
            let _ = fs::remove_file(lnk);
        }
    }
    sys::write_registry(&o.target, &o.trailer.version, sys::dir_size(&o.target))
        .map_err(|e| format!("Не удалось записать данные в реестр: {e}"))?;
    Ok(())
}

fn extract(o: &InstallOptions, staging: &Path, p: &Progress) -> Result<(), String> {
    let corrupt = |e: std::io::Error| format!("Установщик повреждён или скачан не полностью ({e}). Скачайте его заново.");
    let stream = payload::open(&o.exe, &o.trailer).map_err(corrupt)?;
    let mut archive = tar::Archive::new(Counting::new(stream, p.bytes.clone()));
    archive.set_overwrite(true);
    archive.set_preserve_mtime(true);
    let mut files = 0u64;
    for entry in archive.entries().map_err(corrupt)? {
        let mut entry = entry.map_err(corrupt)?;
        let path = entry.path().map_err(corrupt)?.to_path_buf();
        let ok = entry
            .unpack_in(staging)
            .map_err(|e| format!("Не удалось записать {}: {e}", path.display()))?;
        if !ok {
            return Err(format!("Подозрительный путь в пакете: {}", path.display()));
        }
        files += 1;
    }
    // Дочитываем хвост потока, чтобы xz проверил контрольную сумму последнего блока
    let mut rest = archive.into_inner();
    std::io::copy(&mut rest, &mut std::io::sink()).map_err(corrupt)?;
    if files != o.trailer.file_count || !staging.join(sys::APP_EXE).is_file() {
        return Err(format!(
            "Распаковано {files} файлов из {} — установщик повреждён. Скачайте его заново.",
            o.trailer.file_count
        ));
    }
    Ok(())
}

fn write_uninstaller(exe: &Path, stub_len: u64, dest: &Path) -> Result<(), String> {
    let err = |e: std::io::Error| format!("Не удалось создать {}: {e}", dest.display());
    let mut src = fs::File::open(exe).map_err(err)?.take(stub_len);
    let mut out = fs::File::create(dest).map_err(err)?;
    std::io::copy(&mut src, &mut out).map_err(err)?;
    out.flush().map_err(err)
}

pub fn uninstall(dir: &Path, remove_data: bool, p: &Progress) -> Result<(), String> {
    if sys::is_running() {
        p.step("Закрываю Nexora…", 0.0, 0.1, 0);
        sys::close_running()?;
    }
    p.step("Удаляю ярлыки…", 0.1, 0.2, 0);
    sys::remove_shortcuts();

    p.step("Удаляю файлы программы…", 0.2, if remove_data { 0.6 } else { 0.95 }, 0);
    // Папку удаляем целиком, только если это действительно папка Nexora
    if dir.join(sys::APP_EXE).exists() || dir.join(sys::UNINSTALL_EXE).exists() {
        sys::remove_dir_retry(dir).map_err(|e| format!("Не удалось удалить {}: {e}", dir.display()))?;
    }

    if remove_data {
        p.step("Удаляю сборки, миры и настройки…", 0.6, 0.95, 0);
        for d in sys::data_dirs() {
            sys::remove_dir_retry(&d).map_err(|e| format!("Не удалось удалить {}: {e}", d.display()))?;
        }
    }
    p.step("Готово", 0.95, 1.0, 0);
    sys::remove_registry();
    Ok(())
}
