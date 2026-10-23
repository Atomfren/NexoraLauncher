//! Формат установщика: `[exe-заглушка][tar.xz с файлами лаунчера][хвост 72 байта]`.
//!
//! Заглушка — это сам установщик без данных. Её же (первые `stub_len` байт) кладём в папку
//! программы как `uninstall.exe`: без пакета exe работает деинсталлятором.

use std::fs::File;
use std::io::{self, Read, Seek, SeekFrom};
use std::path::Path;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};

use lzma_rust2::XzReaderMt;

pub const MAGIC: &[u8; 8] = b"NXSETUP1";
pub const TRAILER_LEN: u64 = 72;
const VERSION_LEN: usize = 32;

/// Хвост в самом конце файла установщика.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Trailer {
    /// Размер exe-заглушки (с ресурсами), с которого начинается пакет.
    pub stub_len: u64,
    /// Размер сжатого пакета.
    pub payload_len: u64,
    /// Размер распакованного tar-потока — для прогресса.
    pub unpacked_len: u64,
    pub file_count: u64,
    /// Версия лаунчера внутри пакета.
    pub version: String,
}

impl Trailer {
    pub fn to_bytes(&self) -> [u8; TRAILER_LEN as usize] {
        let mut out = [0u8; TRAILER_LEN as usize];
        out[..8].copy_from_slice(MAGIC);
        out[8..16].copy_from_slice(&self.stub_len.to_le_bytes());
        out[16..24].copy_from_slice(&self.payload_len.to_le_bytes());
        out[24..32].copy_from_slice(&self.unpacked_len.to_le_bytes());
        out[32..40].copy_from_slice(&self.file_count.to_le_bytes());
        let v = self.version.as_bytes();
        let n = v.len().min(VERSION_LEN);
        out[40..40 + n].copy_from_slice(&v[..n]);
        out
    }

    pub fn from_bytes(b: &[u8; TRAILER_LEN as usize]) -> Option<Self> {
        if &b[..8] != MAGIC {
            return None;
        }
        let u = |i: usize| u64::from_le_bytes(b[i..i + 8].try_into().unwrap());
        let raw = &b[40..40 + VERSION_LEN];
        let end = raw.iter().position(|&c| c == 0).unwrap_or(VERSION_LEN);
        Some(Self {
            stub_len: u(8),
            payload_len: u(16),
            unpacked_len: u(24),
            file_count: u(32),
            version: String::from_utf8_lossy(&raw[..end]).into_owned(),
        })
    }

    /// Читает хвост файла. `None` — пакета нет (это деинсталлятор) или он повреждён.
    pub fn read_from(path: &Path) -> io::Result<Option<Self>> {
        let mut f = File::open(path)?;
        let len = f.metadata()?.len();
        if len < TRAILER_LEN {
            return Ok(None);
        }
        f.seek(SeekFrom::End(-(TRAILER_LEN as i64)))?;
        let mut buf = [0u8; TRAILER_LEN as usize];
        f.read_exact(&mut buf)?;
        Ok(Self::from_bytes(&buf)
            .filter(|t| t.stub_len.checked_add(t.payload_len).and_then(|n| n.checked_add(TRAILER_LEN)) == Some(len)))
    }
}

/// Окно `[start, start+len)` внутри файла как самостоятельный поток.
pub struct Section<R> {
    inner: R,
    start: u64,
    len: u64,
    pos: u64,
}

impl<R: Read + Seek> Section<R> {
    pub fn new(mut inner: R, start: u64, len: u64) -> io::Result<Self> {
        inner.seek(SeekFrom::Start(start))?;
        Ok(Self { inner, start, len, pos: 0 })
    }
}

impl<R: Read + Seek> Read for Section<R> {
    fn read(&mut self, buf: &mut [u8]) -> io::Result<usize> {
        let left = self.len - self.pos;
        if left == 0 {
            return Ok(0);
        }
        let n = buf.len().min(left as usize);
        let got = self.inner.read(&mut buf[..n])?;
        self.pos += got as u64;
        Ok(got)
    }
}

impl<R: Read + Seek> Seek for Section<R> {
    fn seek(&mut self, to: SeekFrom) -> io::Result<u64> {
        let target = match to {
            SeekFrom::Start(n) => n as i128,
            SeekFrom::End(n) => self.len as i128 + n as i128,
            SeekFrom::Current(n) => self.pos as i128 + n as i128,
        };
        if target < 0 || target > self.len as i128 {
            return Err(io::Error::new(io::ErrorKind::InvalidInput, "seek за пределы пакета"));
        }
        self.pos = target as u64;
        self.inner.seek(SeekFrom::Start(self.start + self.pos))?;
        Ok(self.pos)
    }
}

/// Считает прочитанные байты — по счётчику интерфейс рисует прогресс.
pub struct Counting<R> {
    inner: R,
    counter: Arc<AtomicU64>,
}

impl<R> Counting<R> {
    pub fn new(inner: R, counter: Arc<AtomicU64>) -> Self {
        Self { inner, counter }
    }
}

impl<R: Read> Read for Counting<R> {
    fn read(&mut self, buf: &mut [u8]) -> io::Result<usize> {
        let n = self.inner.read(buf)?;
        self.counter.fetch_add(n as u64, Ordering::Relaxed);
        Ok(n)
    }
}

/// Распакованный tar-поток из установщика.
pub fn open(exe: &Path, t: &Trailer) -> io::Result<impl Read> {
    let section = Section::new(File::open(exe)?, t.stub_len, t.payload_len)?;
    let workers = std::thread::available_parallelism().map_or(2, |n| n.get().min(8)) as u32;
    XzReaderMt::new(section, false, workers)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn trailer_roundtrip() {
        let t = Trailer { stub_len: 10, payload_len: 20, unpacked_len: 30, file_count: 4, version: "1.5.0".into() };
        assert_eq!(Trailer::from_bytes(&t.to_bytes()), Some(t));
    }

    #[test]
    fn section_reads_only_window() {
        let data = io::Cursor::new(b"0123456789".to_vec());
        let mut s = Section::new(data, 3, 4).unwrap();
        let mut out = String::new();
        s.read_to_string(&mut out).unwrap();
        assert_eq!(out, "3456");
        s.seek(SeekFrom::Start(1)).unwrap();
        out.clear();
        s.read_to_string(&mut out).unwrap();
        assert_eq!(out, "456");
    }
}
