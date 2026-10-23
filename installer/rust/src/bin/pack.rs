//! Упаковщик: берёт собранный `nexora-setup.exe`, ставит ему иконку и манифест,
//! затем приклеивает папку лаунчера (tar.xz) и хвост с описанием пакета.
//!
//! nexora-pack --app <dist\NexoraLauncher> --version 1.5.0 [--stub <exe>] [--icon <ico>] [--out <exe>] [--preset 0-9]

use std::fs;
use std::io::{self, BufWriter, Seek, Write};
use std::num::NonZeroU64;
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Instant;

use editpe::Image;
use lzma_rust2::{XzOptions, XzWriterMt};
use nexora_setup::payload::Trailer;

const MANIFEST: &str = r#"<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <assemblyIdentity type="win32" name="Atomfren.Nexora.Setup" version="1.0.0.0"/>
  <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3">
    <security><requestedPrivileges><requestedExecutionLevel level="asInvoker" uiAccess="false"/></requestedPrivileges></security>
  </trustInfo>
  <compatibility xmlns="urn:schemas-microsoft-com:compatibility.v1">
    <application><supportedOS Id="{8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a}"/></application>
  </compatibility>
  <application xmlns="urn:schemas-microsoft-com:asm.v3">
    <windowsSettings>
      <dpiAware xmlns="http://schemas.microsoft.com/SMI/2005/WindowsSettings">true/pm</dpiAware>
      <dpiAwareness xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">PerMonitorV2</dpiAwareness>
      <activeCodePage xmlns="http://schemas.microsoft.com/SMI/2019/WindowsSettings">UTF-8</activeCodePage>
    </windowsSettings>
  </application>
  <dependency><dependentAssembly>
    <assemblyIdentity type="win32" name="Microsoft.Windows.Common-Controls" version="6.0.0.0"
      processorArchitecture="*" publicKeyToken="6595b64144ccf1df" language="*"/>
  </dependentAssembly></dependency>
</assembly>
"#;

struct Args {
    app: PathBuf,
    version: String,
    stub: PathBuf,
    icon: Option<PathBuf>,
    out: Option<PathBuf>,
    preset: u32,
}

fn parse_args() -> Result<Args, String> {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let mut a = Args {
        app: PathBuf::new(),
        version: String::new(),
        stub: root.join("target/release/nexora-setup.exe"),
        icon: Some(root.join("assets/icon/icon.ico")),
        out: None,
        preset: 9,
    };
    let mut it = std::env::args().skip(1);
    while let Some(key) = it.next() {
        let mut val = || it.next().ok_or(format!("после {key} нужно значение"));
        match key.as_str() {
            "--app" => a.app = val()?.into(),
            "--version" => a.version = val()?,
            "--stub" => a.stub = val()?.into(),
            "--icon" => a.icon = Some(val()?.into()),
            "--no-icon" => a.icon = None,
            "--out" => a.out = Some(val()?.into()),
            "--preset" => a.preset = val()?.parse().map_err(|_| "--preset: число 0–9")?,
            "-h" | "--help" => return Err(String::new()),
            other => return Err(format!("неизвестный параметр {other}")),
        }
    }
    if a.app.as_os_str().is_empty() || a.version.is_empty() {
        return Err("нужны --app и --version".into());
    }
    Ok(a)
}

/// Все файлы папки (рекурсивно, в стабильном порядке) с путями относительно корня.
fn collect(root: &Path) -> io::Result<Vec<(PathBuf, String)>> {
    let mut out = Vec::new();
    let mut stack = vec![root.to_path_buf()];
    while let Some(dir) = stack.pop() {
        let mut entries: Vec<_> = fs::read_dir(&dir)?.collect::<Result<_, _>>()?;
        entries.sort_by_key(|e| e.file_name());
        for e in entries {
            let path = e.path();
            if e.file_type()?.is_dir() {
                stack.push(path);
            } else {
                let rel = path.strip_prefix(root).unwrap().to_string_lossy().replace('\\', "/");
                out.push((path, rel));
            }
        }
    }
    out.sort_by(|a, b| a.1.cmp(&b.1));
    Ok(out)
}

/// Пишет в поток и считает байты (размер tar до сжатия).
struct CountingWriter<W> {
    inner: W,
    count: Arc<AtomicU64>,
}

impl<W: Write> Write for CountingWriter<W> {
    fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
        let n = self.inner.write(buf)?;
        self.count.fetch_add(n as u64, Ordering::Relaxed);
        Ok(n)
    }
    fn flush(&mut self) -> io::Result<()> {
        self.inner.flush()
    }
}

fn run(a: Args) -> Result<PathBuf, String> {
    let exe_name = "NexoraLauncher.exe";
    if !a.app.join(exe_name).is_file() {
        return Err(format!("в {} нет {exe_name} — сначала соберите лаунчер", a.app.display()));
    }
    let out = a.out.clone().unwrap_or_else(|| {
        Path::new(env!("CARGO_MANIFEST_DIR")).join(format!("dist/NexoraLauncher-{}-setup.exe", a.version))
    });
    if let Some(dir) = out.parent() {
        fs::create_dir_all(dir).map_err(|e| format!("{}: {e}", dir.display()))?;
    }

    // 1. Заглушка с иконкой и манифестом
    let stub = fs::read(&a.stub).map_err(|e| format!("{}: {e} (соберите: cargo build --release)", a.stub.display()))?;
    let mut image = Image::parse(stub).map_err(|e| format!("не разобрать exe: {e:?}"))?;
    let mut res = image.resource_directory().cloned().unwrap_or_default();
    if let Some(icon) = &a.icon {
        res.set_main_icon_file(&icon.to_string_lossy()).map_err(|e| format!("иконка: {e:?}"))?;
    }
    res.set_manifest(MANIFEST).map_err(|e| format!("манифест: {e:?}"))?;
    image.set_resource_directory(res).map_err(|e| format!("ресурсы: {e:?}"))?;
    image.write_file(&out).map_err(|e| format!("{}: {e:?}", out.display()))?;
    let stub_len = fs::metadata(&out).map_err(|e| e.to_string())?.len();

    // 2. Пакет: tar -> xz, дописываем после заглушки
    let files = collect(&a.app).map_err(|e| format!("{}: {e}", a.app.display()))?;
    let total: u64 = files.iter().map(|(p, _)| fs::metadata(p).map_or(0, |m| m.len())).sum();
    println!("Упаковываю {} файлов, {:.1} МБ…", files.len(), total as f64 / 1048576.0);

    let mut file = fs::OpenOptions::new().append(true).open(&out).map_err(|e| e.to_string())?;
    file.seek(io::SeekFrom::End(0)).map_err(|e| e.to_string())?;
    let mut opts = XzOptions::with_preset(a.preset);
    // Блоки по 64 МБ: сжимаются параллельно и так же параллельно распаковываются
    opts.set_block_size(NonZeroU64::new(64 << 20));
    let workers = std::thread::available_parallelism().map_or(2, |n| n.get().min(4)) as u32;
    let xz = XzWriterMt::new(BufWriter::with_capacity(1 << 20, file), opts, workers).map_err(|e| e.to_string())?;
    let unpacked = Arc::new(AtomicU64::new(0));
    let mut tar = tar::Builder::new(CountingWriter { inner: xz, count: unpacked.clone() });
    tar.mode(tar::HeaderMode::Deterministic);
    tar.follow_symlinks(false);
    let started = Instant::now();
    for (i, (path, rel)) in files.iter().enumerate() {
        tar.append_path_with_name(path, rel).map_err(|e| format!("{rel}: {e}"))?;
        if i % 500 == 0 {
            print!("\r  {}/{}", i, files.len());
            io::stdout().flush().ok();
        }
    }
    let counting = tar.into_inner().map_err(|e| e.to_string())?;
    let mut buffered = counting.inner.finish().map_err(|e| e.to_string())?;
    buffered.flush().map_err(|e| e.to_string())?;
    let mut file = buffered.into_inner().map_err(|e| e.to_string())?;
    let payload_len = file.stream_position().map_err(|e| e.to_string())? - stub_len;

    // 3. Хвост
    let trailer = Trailer {
        stub_len,
        payload_len,
        unpacked_len: unpacked.load(Ordering::Relaxed),
        file_count: files.len() as u64,
        version: a.version.clone(),
    };
    file.write_all(&trailer.to_bytes()).map_err(|e| e.to_string())?;
    drop(file);

    let check = Trailer::read_from(&out).map_err(|e| e.to_string())?;
    if check.as_ref() != Some(&trailer) {
        return Err("проверка хвоста не прошла".into());
    }
    println!(
        "\r  готово за {:.0} с: заглушка {:.1} МБ + пакет {:.1} МБ",
        started.elapsed().as_secs_f64(),
        stub_len as f64 / 1048576.0,
        payload_len as f64 / 1048576.0
    );
    Ok(out)
}

fn main() -> ExitCode {
    match parse_args().and_then(run) {
        Ok(out) => {
            println!("Установщик: {}", out.display());
            ExitCode::SUCCESS
        }
        Err(e) => {
            if !e.is_empty() {
                eprintln!("Ошибка: {e}");
            }
            eprintln!("Использование: nexora-pack --app <папка лаунчера> --version X.Y.Z [--stub exe] [--icon ico] [--out exe] [--preset 0-9]");
            ExitCode::FAILURE
        }
    }
}

