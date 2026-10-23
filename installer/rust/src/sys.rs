//! Всё, что связано с Windows: пути, реестр «Приложения», ярлыки, процессы.

use std::fs;
use std::io;
use std::os::windows::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::thread::sleep;
use std::time::{Duration, Instant};

use winreg::RegKey;
use winreg::enums::{HKEY_CURRENT_USER, KEY_READ, KEY_WRITE};

pub const APP_TITLE: &str = "Nexora";
pub const APP_DIR_NAME: &str = "NexoraLauncher";
pub const APP_EXE: &str = "NexoraLauncher.exe";
pub const UNINSTALL_EXE: &str = "uninstall.exe";
pub const PUBLISHER: &str = "Atomfren";
pub const URL: &str = "https://github.com/Atomfren/NexoraLauncher";
/// Каталог данных лаунчера (shared/version.py: APP_ID).
const DATA_ID: &str = "nexoralauncher";

const UNINSTALL_ROOT: &str = r"Software\Microsoft\Windows\CurrentVersion\Uninstall";
const OUR_KEY: &str = "NexoraLauncher";
/// Ключ, который оставляет старый установщик на Inno Setup (AppId из installer/nexora.iss).
const INNO_KEY: &str = "{6E1C2A7B-4F3D-4C8E-9B2A-1D5E7F9A3C42}_is1";

const CREATE_NO_WINDOW: u32 = 0x0800_0000;

fn system32(exe: &str) -> PathBuf {
    let root = std::env::var_os("SystemRoot").unwrap_or_else(|| "C:\\Windows".into());
    Path::new(&root).join("System32").join(exe)
}

fn hidden(exe: impl AsRef<std::ffi::OsStr>) -> Command {
    let mut c = Command::new(exe);
    c.creation_flags(CREATE_NO_WINDOW).stdin(Stdio::null());
    c
}

// ---------- пути ----------

pub fn default_install_dir() -> PathBuf {
    dirs::data_local_dir().unwrap_or_else(|| "C:\\".into()).join("Programs").join(APP_DIR_NAME)
}

/// Папки с данными пользователя: сборки и миры, настройки.
pub fn data_dirs() -> Vec<PathBuf> {
    [dirs::data_local_dir(), dirs::data_dir()].into_iter().flatten().map(|d| d.join(DATA_ID)).collect()
}

fn start_menu_dir() -> Option<PathBuf> {
    dirs::data_dir().map(|d| d.join(r"Microsoft\Windows\Start Menu\Programs"))
}

pub fn start_menu_shortcut() -> Option<PathBuf> {
    start_menu_dir().map(|d| d.join(format!("{APP_TITLE}.lnk")))
}

pub fn desktop_shortcut() -> Option<PathBuf> {
    dirs::desktop_dir().map(|d| d.join(format!("{APP_TITLE}.lnk")))
}

/// Папку, выбранную в диалоге, превращаем в `<папка>\NexoraLauncher`, если это не она сама.
pub fn normalize_choice(dir: PathBuf) -> PathBuf {
    let named = dir.file_name().is_some_and(|n| n.to_string_lossy().eq_ignore_ascii_case(APP_DIR_NAME));
    if named || dir.join(APP_EXE).exists() { dir } else { dir.join(APP_DIR_NAME) }
}

/// Нельзя ставить в корень диска, профиль, системные папки или в чужую непустую папку:
/// при обновлении содержимое папки программы заменяется целиком.
pub fn check_target(dir: &Path) -> Result<(), String> {
    if !dir.is_absolute() {
        return Err("Укажите полный путь к папке.".into());
    }
    if dir.components().count() < 3 {
        return Err("Нельзя ставить в корень диска — выберите вложенную папку.".into());
    }
    let forbidden = [
        dirs::home_dir(),
        dirs::data_local_dir(),
        dirs::data_dir(),
        dirs::desktop_dir(),
        dirs::document_dir(),
        dirs::download_dir(),
        std::env::var_os("ProgramFiles").map(PathBuf::from),
        std::env::var_os("SystemRoot").map(PathBuf::from),
    ];
    if forbidden.iter().flatten().any(|f| same_path(f, dir)) {
        return Err("Эта папка служебная — выберите отдельную папку для Nexora.".into());
    }
    if data_dirs().iter().any(|d| same_path(d, dir) || dir.starts_with(d)) {
        return Err("Это папка с данными лаунчера — выберите другую.".into());
    }
    if dir.is_file() {
        return Err("По этому пути лежит файл, а не папка.".into());
    }
    if dir.is_dir() && !dir.join(APP_EXE).exists() && !dir.join(UNINSTALL_EXE).exists() {
        let busy = fs::read_dir(dir).map(|mut r| r.next().is_some()).unwrap_or(true);
        if busy {
            return Err("В папке уже есть другие файлы. Выберите пустую папку или папку с Nexora.".into());
        }
    }
    Ok(())
}

fn same_path(a: &Path, b: &Path) -> bool {
    let norm = |p: &Path| p.to_string_lossy().trim_end_matches(['\\', '/']).to_lowercase();
    norm(a) == norm(b)
}

pub fn dir_size(dir: &Path) -> u64 {
    let Ok(rd) = fs::read_dir(dir) else { return 0 };
    rd.flatten()
        .map(|e| match e.file_type() {
            Ok(t) if t.is_dir() => dir_size(&e.path()),
            _ => e.metadata().map_or(0, |m| m.len()),
        })
        .sum()
}

// ---------- установленная версия ----------

#[derive(Debug, Clone)]
pub struct Existing {
    pub dir: PathBuf,
    pub version: String,
    /// Команда деинсталляции старого Inno-установщика, если стоит он.
    pub inno_uninstall: Option<String>,
}

fn uninstall_key(name: &str, access: u32) -> io::Result<RegKey> {
    RegKey::predef(HKEY_CURRENT_USER).open_subkey_with_flags(format!(r"{UNINSTALL_ROOT}\{name}"), access)
}

pub fn find_existing() -> Option<Existing> {
    if let Ok(k) = uninstall_key(OUR_KEY, KEY_READ) {
        let dir: String = k.get_value("InstallLocation").unwrap_or_default();
        if !dir.is_empty() {
            return Some(Existing {
                dir: PathBuf::from(dir),
                version: k.get_value("DisplayVersion").unwrap_or_default(),
                inno_uninstall: None,
            });
        }
    }
    if let Ok(k) = uninstall_key(INNO_KEY, KEY_READ) {
        let dir: String =
            k.get_value("InstallLocation").or_else(|_| k.get_value("Inno Setup: App Path")).unwrap_or_default();
        if !dir.is_empty() {
            return Some(Existing {
                dir: PathBuf::from(dir.trim_end_matches('\\')),
                version: k.get_value("DisplayVersion").unwrap_or_default(),
                inno_uninstall: k.get_value("UninstallString").ok(),
            });
        }
    }
    // Файлы на месте, а записи в реестре нет (её удалили вручную) — всё равно обновляем эту папку
    let dir = default_install_dir();
    dir.join(APP_EXE).is_file().then(|| Existing { dir, version: String::new(), inno_uninstall: None })
}

/// Папка «Пуск → Nexora» от Inno Setup: убираем её ярлыки, если деинсталлятор Inno их не убрал.
pub fn remove_legacy_shortcuts() {
    let Some(group) = start_menu_dir().map(|d| d.join(APP_TITLE)) else { return };
    let Ok(entries) = fs::read_dir(&group) else { return };
    for e in entries.flatten() {
        if e.path().extension().is_some_and(|x| x.eq_ignore_ascii_case("lnk")) {
            let _ = fs::remove_file(e.path());
        }
    }
    let _ = fs::remove_dir(&group);
}

/// Тихо удаляет версию, поставленную Inno Setup (данные пользователя он не трогает),
/// и ждёт, пока её запись исчезнет из реестра: деинсталлятор Inno перезапускает себя из %TEMP%.
pub fn run_inno_uninstall(cmd: &str) -> Result<(), String> {
    let exe = cmd.trim().trim_matches('"');
    let exe = exe.split("\" ").next().unwrap_or(exe).trim_matches('"');
    if !Path::new(exe).exists() {
        // Деинсталлятора уже нет — убираем осиротевшую запись
        let _ = RegKey::predef(HKEY_CURRENT_USER).delete_subkey_all(format!(r"{UNINSTALL_ROOT}\{INNO_KEY}"));
        return Ok(());
    }
    let status = hidden(exe)
        .args(["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"])
        .status()
        .map_err(|e| format!("Не удалось запустить удаление старой версии: {e}"))?;
    if !status.success() {
        return Err(format!("Удаление старой версии завершилось с кодом {:?}", status.code()));
    }
    let deadline = Instant::now() + Duration::from_secs(120);
    while uninstall_key(INNO_KEY, KEY_READ).is_ok() {
        if Instant::now() > deadline {
            return Err("Старая версия удаляется слишком долго. Попробуйте ещё раз.".into());
        }
        sleep(Duration::from_millis(300));
    }
    Ok(())
}

pub fn write_registry(dir: &Path, version: &str, size_bytes: u64) -> io::Result<()> {
    let (k, _) = RegKey::predef(HKEY_CURRENT_USER).create_subkey(format!(r"{UNINSTALL_ROOT}\{OUR_KEY}"))?;
    let d = dir.to_string_lossy().to_string();
    let uninstaller = dir.join(UNINSTALL_EXE).to_string_lossy().to_string();
    k.set_value("DisplayName", &APP_TITLE)?;
    k.set_value("DisplayVersion", &version)?;
    k.set_value("Publisher", &PUBLISHER)?;
    k.set_value("DisplayIcon", &dir.join(APP_EXE).to_string_lossy().to_string())?;
    k.set_value("InstallLocation", &d)?;
    k.set_value("UninstallString", &format!("\"{uninstaller}\""))?;
    k.set_value("QuietUninstallString", &format!("\"{uninstaller}\" --silent"))?;
    k.set_value("URLInfoAbout", &URL)?;
    k.set_value("HelpLink", &format!("{URL}/issues"))?;
    k.set_value("InstallDate", &today())?;
    k.set_value("EstimatedSize", &((size_bytes / 1024) as u32))?;
    k.set_value("NoModify", &1u32)?;
    k.set_value("NoRepair", &1u32)?;
    Ok(())
}

pub fn remove_registry() {
    let root = RegKey::predef(HKEY_CURRENT_USER);
    if let Ok(k) = root.open_subkey_with_flags(UNINSTALL_ROOT, KEY_WRITE) {
        let _ = k.delete_subkey_all(OUR_KEY);
    }
}

/// Дата для реестра в виде ГГГГММДД (без внешних зависимостей).
fn today() -> String {
    let days = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0, |d| d.as_secs() / 86_400) as i64;
    // Алгоритм Говарда Хиннанта: дни с 1970-01-01 -> гражданская дата
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = yoe + era * 400 + i64::from(m <= 2);
    format!("{y:04}{m:02}{d:02}")
}

// ---------- ярлыки ----------

pub fn create_shortcut(lnk: &Path, dir: &Path) -> Result<(), String> {
    let target = dir.join(APP_EXE);
    let mut sl = mslnk::ShellLink::new(&target).map_err(|e| format!("ярлык: {e}"))?;
    sl.set_working_dir(Some(dir.to_string_lossy().to_string()));
    sl.set_icon_location(Some(target.to_string_lossy().to_string()));
    sl.set_name(Some("Лаунчер Minecraft".into()));
    if let Some(parent) = lnk.parent() {
        fs::create_dir_all(parent).map_err(|e| format!("{}: {e}", parent.display()))?;
    }
    sl.create_lnk(lnk).map_err(|e| format!("{}: {e}", lnk.display()))
}

pub fn remove_shortcuts() {
    for lnk in [start_menu_shortcut(), desktop_shortcut()].into_iter().flatten() {
        let _ = fs::remove_file(lnk);
    }
}

// ---------- процессы ----------

pub fn is_running() -> bool {
    hidden(system32("tasklist.exe"))
        .args(["/FI", &format!("IMAGENAME eq {APP_EXE}"), "/NH", "/FO", "CSV"])
        .output()
        .map(|o| String::from_utf8_lossy(&o.stdout).to_lowercase().contains(&APP_EXE.to_lowercase()))
        .unwrap_or(false)
}

/// Закрывает лаунчер и ждёт, пока процессы действительно завершатся.
pub fn close_running() -> Result<(), String> {
    let _ = hidden(system32("taskkill.exe")).args(["/IM", APP_EXE, "/T", "/F"]).output();
    let deadline = Instant::now() + Duration::from_secs(10);
    while is_running() {
        if Instant::now() > deadline {
            return Err("Не удалось закрыть Nexora. Закройте лаунчер вручную и повторите.".into());
        }
        sleep(Duration::from_millis(250));
    }
    Ok(())
}

pub fn launch(dir: &Path) -> io::Result<()> {
    Command::new(dir.join(APP_EXE)).current_dir(dir).spawn().map(|_| ())
}

/// Удаляет файл после выхода текущего процесса (временная копия деинсталлятора).
pub fn delete_after_exit(path: &Path) {
    let cmd = format!("ping -n 3 127.0.0.1 >nul & del /f /q \"{}\"", path.display());
    let _ = hidden(system32("cmd.exe")).raw_arg("/c").raw_arg(&cmd).spawn();
}

/// Удаление папки с повторами: антивирус или проводник могут ненадолго держать файлы.
pub fn remove_dir_retry(dir: &Path) -> io::Result<()> {
    let mut last = Ok(());
    for _ in 0..20 {
        match fs::remove_dir_all(dir) {
            Ok(()) => return Ok(()),
            Err(e) if e.kind() == io::ErrorKind::NotFound => return Ok(()),
            Err(e) => last = Err(e),
        }
        sleep(Duration::from_millis(250));
    }
    last
}

pub fn rename_retry(from: &Path, to: &Path) -> io::Result<()> {
    let mut last = Ok(());
    for _ in 0..20 {
        match fs::rename(from, to) {
            Ok(()) => return Ok(()),
            Err(e) => last = Err(e),
        }
        sleep(Duration::from_millis(250));
    }
    last
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn date_format() {
        let d = today();
        assert_eq!(d.len(), 8);
        assert!(d.starts_with("20"));
    }

    #[test]
    fn choice_gets_app_folder() {
        assert_eq!(normalize_choice(PathBuf::from(r"D:\Games")), PathBuf::from(r"D:\Games\NexoraLauncher"));
        assert_eq!(normalize_choice(PathBuf::from(r"D:\Games\NexoraLauncher")), PathBuf::from(r"D:\Games\NexoraLauncher"));
    }

    #[test]
    fn refuses_drive_root_and_profile() {
        assert!(check_target(Path::new(r"C:\")).is_err());
        if let Some(home) = dirs::home_dir() {
            assert!(check_target(&home).is_err());
        }
    }
}
