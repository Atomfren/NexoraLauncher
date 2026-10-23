//! Пиксельная кирка — та же сетка, что в NexoraLauncher-1.5.0/scripts/make_icon.py.

use eframe::egui::{self, Color32, Pos2, Rect, Vec2};

const GRID: [&str; 16] = [
    "....OOOOOOO.....",
    "...OWWLLLMMOO...",
    "....OLMMMDDDDO..",
    ".....OOOOOObMDO.",
    ".........OyBMDO.",
    "........ObBOMMO.",
    ".......OyBOOMMO.",
    "......ObBO.ODMO.",
    ".....OyBO..ODLO.",
    "....ObBO...ODLO.",
    "...OyBO.....OWO.",
    "..ObBO.......O..",
    ".OyBO...........",
    "ObBO............",
    ".OO.............",
    "................",
];

fn color(c: u8) -> Option<Color32> {
    Some(match c {
        b'O' => Color32::from_rgb(0x0a, 0x33, 0x2d),
        b'D' => Color32::from_rgb(0x16, 0x8f, 0x7c),
        b'M' => Color32::from_rgb(0x2c, 0xc9, 0xae),
        b'L' => Color32::from_rgb(0x6f, 0xf0, 0xd8),
        b'W' => Color32::from_rgb(0xc9, 0xff, 0xf4),
        b'B' => Color32::from_rgb(0x3a, 0x27, 0x10),
        b'b' => Color32::from_rgb(0x66, 0x46, 0x20),
        b'y' => Color32::from_rgb(0x94, 0x6a, 0x30),
        _ => return None,
    })
}

/// Рисует кирку с левым верхним углом в `origin`, клетка — `cell` точек.
pub fn paint(painter: &egui::Painter, origin: Pos2, cell: f32) {
    for (r, row) in GRID.iter().enumerate() {
        for (c, ch) in row.bytes().enumerate() {
            if let Some(col) = color(ch) {
                let min = origin + Vec2::new(c as f32 * cell, r as f32 * cell);
                // +0.5 закрывает щели между клетками при дробном масштабе
                painter.rect_filled(Rect::from_min_size(min, Vec2::splat(cell + 0.5)), 0.0, col);
            }
        }
    }
}

/// Иконка окна (панель задач) — 32x32 RGBA.
pub fn window_icon() -> egui::IconData {
    let size = 32usize;
    let scale = size / 16;
    let mut rgba = vec![0u8; size * size * 4];
    for y in 0..size {
        for x in 0..size {
            if let Some(c) = color(GRID[y / scale].as_bytes()[x / scale]) {
                let i = (y * size + x) * 4;
                rgba[i..i + 4].copy_from_slice(&[c.r(), c.g(), c.b(), 255]);
            }
        }
    }
    egui::IconData { rgba, width: size as u32, height: size as u32 }
}
