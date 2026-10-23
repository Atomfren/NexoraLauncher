//! Окно установщика: своя рамка, тёмная тема лаунчера (NxTheme.qml), пиксельная кирка.

use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use eframe::egui::{
    self, Align, Align2, Color32, CornerRadius, CursorIcon, FontData, FontDefinitions, FontFamily, FontId,
    Layout, Pos2, Rect, RichText, Sense, Stroke, UiBuilder, Vec2, ViewportCommand,
};
use nexora_setup::payload::Trailer;

use crate::ops::{self, InstallOptions, Progress};
use crate::{art, sys};

// Цвета тёмной темы лаунчера
const BG: Color32 = Color32::from_rgb(0x12, 0x12, 0x11);
const SURFACE1: Color32 = Color32::from_rgb(0x1b, 0x1a, 0x18);
const SURFACE2: Color32 = Color32::from_rgb(0x23, 0x22, 0x1f);
const SURFACE3: Color32 = Color32::from_rgb(0x2d, 0x2b, 0x27);
const LINE: Color32 = Color32::from_rgb(0x2f, 0x2d, 0x29);
const TEXT: Color32 = Color32::from_rgb(0xed, 0xea, 0xe4);
const MUTED: Color32 = Color32::from_rgb(0x9c, 0x97, 0x8d);
const ACCENT: Color32 = Color32::from_rgb(0xf0, 0xb2, 0x3a);
const ON_ACCENT: Color32 = Color32::from_rgb(0x1a, 0x14, 0x08);
const DANGER: Color32 = Color32::from_rgb(0xe0, 0x61, 0x4f);
const ON_DANGER: Color32 = Color32::from_rgb(0x1f, 0x0b, 0x07);
const SUCCESS: Color32 = Color32::from_rgb(0x6f, 0xbf, 0x73);

const TITLE_H: f32 = 40.0;
const SIDE_W: f32 = 230.0;
pub const WINDOW: Vec2 = Vec2::new(720.0, 460.0);

pub enum Mode {
    Install { exe: PathBuf, trailer: Trailer, existing: Option<sys::Existing> },
    Uninstall { dir: PathBuf, version: String },
    Broken(String),
}

#[derive(Clone, Copy, PartialEq)]
enum Action {
    Install,
    Uninstall,
}

enum Page {
    Welcome,
    AskClose(Action),
    Working(Action),
    Done(Action),
    Failed(String),
}

#[derive(Clone, Copy)]
enum Kind {
    Primary,
    Secondary,
    Danger,
}

pub struct App {
    mode: Mode,
    page: Page,
    path: String,
    path_error: Option<String>,
    desktop: bool,
    launch_after: bool,
    remove_data: bool,
    progress: Option<Arc<Progress>>,
    semibold: bool,
}

impl App {
    pub fn new(cc: &eframe::CreationContext<'_>, mode: Mode) -> Self {
        let semibold = setup_fonts(&cc.egui_ctx);
        setup_style(&cc.egui_ctx);
        let path = match &mode {
            Mode::Install { existing: Some(e), .. } => e.dir.clone(),
            _ => sys::default_install_dir(),
        };
        Self {
            mode,
            page: Page::Welcome,
            path: path.to_string_lossy().to_string(),
            path_error: None,
            desktop: true,
            launch_after: true,
            remove_data: false,
            progress: None,
            semibold,
        }
    }

    fn heading(&self, text: &str) -> RichText {
        let family = if self.semibold { FontFamily::Name("semibold".into()) } else { FontFamily::Proportional };
        RichText::new(text).font(FontId::new(24.0, family)).color(TEXT)
    }

    fn version(&self) -> String {
        match &self.mode {
            Mode::Install { trailer, .. } => trailer.version.clone(),
            Mode::Uninstall { version, .. } => version.clone(),
            Mode::Broken(_) => String::new(),
        }
    }

    fn busy(&self) -> bool {
        matches!(self.page, Page::Working(_))
    }

    fn start(&mut self, action: Action) {
        let progress = Arc::new(Progress::default());
        self.progress = Some(progress.clone());
        match (&self.mode, action) {
            (Mode::Install { exe, trailer, .. }, Action::Install) => {
                let opts = InstallOptions {
                    target: PathBuf::from(self.path.trim()),
                    desktop_shortcut: self.desktop,
                    exe: exe.clone(),
                    trailer: trailer.clone(),
                };
                ops::spawn(progress, move |p| ops::install(opts, p));
            }
            (Mode::Uninstall { dir, .. }, Action::Uninstall) => {
                let (dir, data) = (dir.clone(), self.remove_data);
                ops::spawn(progress, move |p| ops::uninstall(&dir, data, p));
            }
            _ => return,
        }
        self.page = Page::Working(action);
    }

    /// Проверяет, не запущен ли лаунчер, и либо спрашивает, либо сразу начинает.
    fn request(&mut self, action: Action) {
        if action == Action::Install {
            let target = PathBuf::from(self.path.trim());
            if let Err(e) = sys::check_target(&target) {
                self.path_error = Some(e);
                return;
            }
        }
        self.path_error = None;
        if sys::is_running() {
            self.page = Page::AskClose(action);
        } else {
            self.start(action);
        }
    }

    // ---------- рамка окна ----------

    fn title_bar(&mut self, ui: &mut egui::Ui, rect: Rect) {
        let ctx = ui.ctx().clone();
        let drag = ui.interact(rect, ui.scope_id().with("title"), Sense::click_and_drag());
        if drag.drag_started() {
            ctx.send_viewport_cmd(ViewportCommand::StartDrag);
        }
        let p = ui.painter();
        art::paint(p, Pos2::new(rect.left() + 14.0, rect.center().y - 10.0), 1.25);
        let title = match self.mode {
            Mode::Uninstall { .. } => "Удаление Nexora",
            _ => "Установка Nexora",
        };
        p.text(Pos2::new(rect.left() + 44.0, rect.center().y), Align2::LEFT_CENTER, title, FontId::proportional(13.0), MUTED);

        // Кнопка закрытия
        let close = Rect::from_min_size(Pos2::new(rect.right() - 46.0, rect.top()), Vec2::new(46.0, rect.height()));
        let resp = ui.interact(close, ui.scope_id().with("close"), Sense::click());
        let enabled = !self.busy();
        if resp.hovered() && enabled {
            ui.painter().rect_filled(close, CornerRadius { ne: 10, ..Default::default() }, DANGER);
            ctx.set_cursor_icon(CursorIcon::PointingHand);
        }
        let c = close.center();
        let col = if !enabled { SURFACE3 } else if resp.hovered() { ON_DANGER } else { MUTED };
        let s = 5.0;
        let stroke = Stroke::new(1.4, col);
        ui.painter().line_segment([c + Vec2::new(-s, -s), c + Vec2::new(s, s)], stroke);
        ui.painter().line_segment([c + Vec2::new(-s, s), c + Vec2::new(s, -s)], stroke);
        if resp.clicked() && enabled {
            ctx.send_viewport_cmd(ViewportCommand::Close);
        }
    }

    fn side(&self, ui: &mut egui::Ui, rect: Rect) {
        let p = ui.painter();
        p.rect_filled(rect, CornerRadius { sw: 10, ..Default::default() }, SURFACE1);
        p.line_segment([rect.right_top(), rect.right_bottom()], Stroke::new(1.0, LINE));
        let cell = 8.0;
        let art_size = cell * 16.0;
        let top = rect.top() + (rect.height() - art_size) * 0.38;
        // Мягкое свечение под киркой
        p.circle_filled(Pos2::new(rect.center().x, top + art_size * 0.5), art_size * 0.62, Color32::from_rgba_unmultiplied(0x2c, 0xc9, 0xae, 10));
        art::paint(p, Pos2::new(rect.center().x - art_size / 2.0, top), cell);
        let family = if self.semibold { FontFamily::Name("semibold".into()) } else { FontFamily::Proportional };
        p.text(Pos2::new(rect.center().x, top + art_size + 30.0), Align2::CENTER_CENTER, "Nexora", FontId::new(26.0, family), TEXT);
        let v = self.version();
        if !v.is_empty() {
            p.text(Pos2::new(rect.center().x, top + art_size + 56.0), Align2::CENTER_CENTER, format!("версия {v}"), FontId::proportional(13.0), MUTED);
        }
        p.text(Pos2::new(rect.center().x, rect.bottom() - 22.0), Align2::CENTER_CENTER, "Лаунчер Minecraft", FontId::proportional(12.0), MUTED);
    }

    // ---------- страницы ----------

    fn content(&mut self, ui: &mut egui::Ui, rect: Rect) {
        let inner = rect.shrink2(Vec2::new(36.0, 30.0));
        let footer = Rect::from_min_max(Pos2::new(inner.left(), inner.bottom() - 38.0), inner.max);
        let body = Rect::from_min_max(inner.min, Pos2::new(inner.right(), footer.top() - 12.0));

        let mut next: Option<Box<dyn FnOnce(&mut App)>> = None;
        ui.scope_builder(UiBuilder::new().max_rect(body), |ui| {
            ui.spacing_mut().item_spacing.y = 10.0;
            self.body(ui);
        });
        ui.scope_builder(UiBuilder::new().max_rect(footer).layout(Layout::right_to_left(Align::Center)), |ui| {
            ui.spacing_mut().item_spacing.x = 10.0;
            next = self.footer(ui);
        });
        if let Some(f) = next {
            f(self);
        }
    }

    fn body(&mut self, ui: &mut egui::Ui) {
        match &self.page {
            Page::Welcome => match &self.mode {
                Mode::Install { trailer, existing, .. } => {
                    let (trailer, existing) = (trailer.clone(), existing.clone());
                    self.welcome_install(ui, &trailer, existing.as_ref());
                }
                Mode::Uninstall { dir, .. } => {
                    let dir = dir.clone();
                    self.welcome_uninstall(ui, &dir);
                }
                Mode::Broken(msg) => {
                    ui.label(self.heading("Не удалось запустить"));
                    ui.label(RichText::new(msg).color(MUTED).size(14.0));
                }
            },
            Page::AskClose(_) => {
                ui.label(self.heading("Nexora сейчас запущен"));
                ui.label(
                    RichText::new("Чтобы продолжить, лаунчер нужно закрыть. Если идёт игра — сначала выйдите из неё, чтобы не потерять прогресс в мире.")
                        .color(MUTED)
                        .size(14.0),
                );
            }
            Page::Working(action) => {
                let action = *action;
                self.working(ui, action);
            }
            Page::Done(Action::Install) => {
                let updated = matches!(&self.mode, Mode::Install { existing: Some(_), .. });
                ui.label(self.heading(if updated { "Nexora обновлён" } else { "Nexora установлен" }));
                let mut text = String::from("Ярлык добавлен в меню «Пуск»");
                text += if self.desktop { " и на рабочий стол." } else { "." };
                ui.label(RichText::new(text).color(MUTED).size(14.0));
                ui.add_space(6.0);
                ui.label(RichText::new("✔  Всё готово, можно играть").color(SUCCESS).size(14.0));
            }
            Page::Done(Action::Uninstall) => {
                ui.label(self.heading("Nexora удалён"));
                let text = if self.remove_data {
                    "Лаунчер и все его данные удалены."
                } else {
                    "Лаунчер удалён. Сборки, миры и настройки остались — при повторной установке всё вернётся на место."
                };
                ui.label(RichText::new(text).color(MUTED).size(14.0));
            }
            Page::Failed(err) => {
                let err = err.clone();
                ui.label(self.heading("Не получилось"));
                ui.label(RichText::new(err).color(DANGER).size(14.0));
            }
        }
    }

    fn welcome_install(&mut self, ui: &mut egui::Ui, trailer: &Trailer, existing: Option<&sys::Existing>) {
        match existing {
            Some(e) => {
                ui.label(self.heading("Обновление Nexora"));
                let from = if e.version.is_empty() { String::new() } else { format!(" {}", e.version) };
                ui.label(
                    RichText::new(format!(
                        "Найдена установленная версия{from}. Она будет обновлена до {}. Сборки, миры и настройки останутся на месте.",
                        trailer.version
                    ))
                    .color(MUTED)
                    .size(14.0),
                );
            }
            None => {
                ui.label(self.heading("Установка Nexora"));
                ui.label(
                    RichText::new("Лаунчер Minecraft со сборками, модами и своими серверами. Установка займёт меньше минуты.")
                        .color(MUTED)
                        .size(14.0),
                );
            }
        }
        ui.add_space(8.0);
        ui.label(RichText::new("Папка установки").color(MUTED).size(12.5));
        let locked = existing.is_some();
        ui.horizontal(|ui| {
            let browse_w = 92.0;
            let edit = egui::TextEdit::singleline(&mut self.path)
                .desired_width(ui.available_width() - browse_w - 8.0)
                .margin(Vec2::new(10.0, 8.0))
                .interactive(!locked);
            if ui.add(edit).changed() {
                self.path_error = None;
            }
            if !locked && button(ui, "Обзор…", Kind::Secondary, browse_w).clicked() {
                let start = PathBuf::from(self.path.trim());
                let start = start.parent().filter(|p| p.exists()).map(PathBuf::from).unwrap_or_else(sys::default_install_dir);
                if let Some(dir) = rfd::FileDialog::new().set_title("Куда установить Nexora").set_directory(start).pick_folder() {
                    self.path = sys::normalize_choice(dir).to_string_lossy().to_string();
                    self.path_error = None;
                }
            }
        });
        if let Some(e) = &self.path_error {
            ui.label(RichText::new(e).color(DANGER).size(12.5));
        } else {
            let mb = trailer.unpacked_len as f64 / 1_048_576.0;
            let hint = if locked { "Обновление ставится в ту же папку." } else { "" };
            ui.label(RichText::new(format!("Понадобится около {mb:.0} МБ. {hint}")).color(MUTED).size(12.5));
        }
        ui.add_space(6.0);
        ui.checkbox(&mut self.desktop, RichText::new("Ярлык на рабочем столе").size(14.0));
        ui.checkbox(&mut self.launch_after, RichText::new("Запустить Nexora после установки").size(14.0));
    }

    fn welcome_uninstall(&mut self, ui: &mut egui::Ui, dir: &std::path::Path) {
        ui.label(self.heading("Удаление Nexora"));
        ui.label(RichText::new(format!("Лаунчер будет удалён из папки\n{}", dir.display())).color(MUTED).size(14.0));
        ui.add_space(8.0);
        ui.checkbox(&mut self.remove_data, RichText::new("Удалить также сборки, миры, аккаунты и настройки").size(14.0));
        if self.remove_data {
            let paths: Vec<String> = sys::data_dirs().iter().filter(|d| d.exists()).map(|d| d.display().to_string()).collect();
            if !paths.is_empty() {
                ui.label(RichText::new(paths.join("\n")).color(MUTED).size(12.5));
            }
            ui.label(RichText::new("Это нельзя отменить: миры удалятся навсегда.").color(DANGER).size(12.5));
        } else {
            ui.label(RichText::new("Данные останутся — при повторной установке всё вернётся.").color(MUTED).size(12.5));
        }
    }

    fn working(&mut self, ui: &mut egui::Ui, action: Action) {
        let Some(progress) = self.progress.clone() else { return };
        let (state, frac) = progress.snapshot();
        ui.label(self.heading(if action == Action::Install { "Устанавливаю…" } else { "Удаляю…" }));
        ui.label(RichText::new(&state.status).color(MUTED).size(14.0));
        ui.add_space(14.0);
        progress_bar(ui, frac);
        ui.label(RichText::new(format!("{:.0}%", frac * 100.0)).color(MUTED).size(12.5));

        if let Some(outcome) = state.outcome {
            self.page = match outcome {
                Ok(()) => {
                    if action == Action::Install && self.launch_after {
                        self.launch_and_close(ui.ctx());
                    }
                    Page::Done(action)
                }
                Err(e) => Page::Failed(e),
            };
        }
        ui.ctx().request_repaint_after(Duration::from_millis(40));
    }

    fn launch_and_close(&mut self, ctx: &egui::Context) {
        match sys::launch(&PathBuf::from(self.path.trim())) {
            Ok(()) => ctx.send_viewport_cmd(ViewportCommand::Close),
            Err(e) => self.page = Page::Failed(format!("Nexora установлен, но не запустился: {e}")),
        }
    }

    /// Кнопки внизу (раскладка справа налево: первая добавленная — крайняя правая).
    fn footer(&mut self, ui: &mut egui::Ui) -> Option<Box<dyn FnOnce(&mut App)>> {
        let ctx = ui.ctx().clone();
        let close = move || ctx.send_viewport_cmd(ViewportCommand::Close);
        match &self.page {
            Page::Welcome => match &self.mode {
                Mode::Install { existing, .. } => {
                    let label = if existing.is_some() { "Обновить" } else { "Установить" };
                    if button(ui, label, Kind::Primary, 140.0).clicked() {
                        return Some(Box::new(|a| a.request(Action::Install)));
                    }
                    if button(ui, "Отмена", Kind::Secondary, 110.0).clicked() {
                        close();
                    }
                }
                Mode::Uninstall { .. } => {
                    if button(ui, "Удалить", Kind::Danger, 130.0).clicked() {
                        return Some(Box::new(|a| a.request(Action::Uninstall)));
                    }
                    if button(ui, "Отмена", Kind::Secondary, 110.0).clicked() {
                        close();
                    }
                }
                Mode::Broken(_) => {
                    if button(ui, "Закрыть", Kind::Secondary, 110.0).clicked() {
                        close();
                    }
                }
            },
            Page::AskClose(action) => {
                let action = *action;
                if button(ui, "Закрыть Nexora и продолжить", Kind::Primary, 230.0).clicked() {
                    return Some(Box::new(move |a| a.start(action)));
                }
                if button(ui, "Назад", Kind::Secondary, 110.0).clicked() {
                    return Some(Box::new(|a| a.page = Page::Welcome));
                }
            }
            Page::Working(_) => {}
            Page::Done(Action::Install) => {
                if button(ui, "Запустить Nexora", Kind::Primary, 170.0).clicked() {
                    let ctx = ui.ctx().clone();
                    return Some(Box::new(move |a| a.launch_and_close(&ctx)));
                }
                if button(ui, "Закрыть", Kind::Secondary, 110.0).clicked() {
                    close();
                }
            }
            Page::Done(Action::Uninstall) => {
                if button(ui, "Закрыть", Kind::Primary, 120.0).clicked() {
                    close();
                }
            }
            Page::Failed(..) => {
                if button(ui, "Повторить", Kind::Primary, 130.0).clicked() {
                    return Some(Box::new(|a| a.page = Page::Welcome));
                }
                if button(ui, "Закрыть", Kind::Secondary, 110.0).clicked() {
                    close();
                }
            }
        }
        None
    }
}

impl eframe::App for App {
    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        let ctx = ui.ctx().clone();
        // Пока идёт работа, окно не закрываем (Alt+F4 тоже)
        if self.busy() && ctx.input(|i| i.viewport().close_requested()) {
            ctx.send_viewport_cmd(ViewportCommand::CancelClose);
        }
        let full = ui.max_rect();
        ui.painter().rect_filled(full, 10.0, BG);
        let title = Rect::from_min_size(full.min, Vec2::new(full.width(), TITLE_H));
        let side = Rect::from_min_max(Pos2::new(full.left(), title.bottom()), Pos2::new(full.left() + SIDE_W, full.bottom()));
        let main = Rect::from_min_max(Pos2::new(side.right(), title.bottom()), full.max);
        self.side(ui, side);
        ui.painter().line_segment([title.left_bottom(), title.right_bottom()], Stroke::new(1.0, LINE));
        self.content(ui, main);
        self.title_bar(ui, title);
        ui.painter().rect_stroke(full.shrink(0.5), 10.0, Stroke::new(1.0, LINE), egui::StrokeKind::Inside);
    }

    fn clear_color(&self, _visuals: &egui::Visuals) -> [f32; 4] {
        [0.0, 0.0, 0.0, 0.0]
    }
}

// ---------- виджеты ----------

fn lighten(c: Color32, t: f32) -> Color32 {
    let f = |x: u8| (x as f32 + (255.0 - x as f32) * t) as u8;
    Color32::from_rgb(f(c.r()), f(c.g()), f(c.b()))
}

fn button(ui: &mut egui::Ui, text: &str, kind: Kind, width: f32) -> egui::Response {
    let (fill, fg) = match kind {
        Kind::Primary => (ACCENT, ON_ACCENT),
        Kind::Secondary => (SURFACE2, TEXT),
        Kind::Danger => (DANGER, ON_DANGER),
    };
    let font = FontId::proportional(14.0);
    let galley = ui.painter().layout_no_wrap(text.to_owned(), font, fg);
    let size = Vec2::new(width.max(galley.size().x + 32.0), 38.0);
    let (rect, resp) = ui.allocate_exact_size(size, Sense::click());
    let fill = if resp.is_pointer_button_down_on() {
        lighten(fill, 0.04)
    } else if resp.hovered() {
        lighten(fill, 0.14)
    } else {
        fill
    };
    let p = ui.painter();
    p.rect_filled(rect, 6.0, fill);
    if matches!(kind, Kind::Secondary) {
        p.rect_stroke(rect, 6.0, Stroke::new(1.0, LINE), egui::StrokeKind::Inside);
    }
    p.galley(rect.center() - galley.size() / 2.0, galley, fg);
    resp.on_hover_cursor(CursorIcon::PointingHand)
}

fn progress_bar(ui: &mut egui::Ui, frac: f32) {
    let (rect, _) = ui.allocate_exact_size(Vec2::new(ui.available_width(), 8.0), Sense::hover());
    let p = ui.painter();
    p.rect_filled(rect, 4.0, SURFACE3);
    let w = (rect.width() * frac.clamp(0.0, 1.0)).max(8.0);
    p.rect_filled(Rect::from_min_size(rect.min, Vec2::new(w, rect.height())), 4.0, ACCENT);
}

// ---------- стиль ----------

/// Segoe UI из системы: кириллица и привычный вид Windows. Возвращает, найден ли Semibold.
fn setup_fonts(ctx: &egui::Context) -> bool {
    let fonts_dir = PathBuf::from(std::env::var_os("SystemRoot").unwrap_or_else(|| "C:\\Windows".into())).join("Fonts");
    let mut defs = FontDefinitions::default();
    let mut semibold = false;
    if let Ok(bytes) = std::fs::read(fonts_dir.join("segoeui.ttf")) {
        defs.font_data.insert("segoe".into(), Arc::new(FontData::from_owned(bytes)));
        defs.families.entry(FontFamily::Proportional).or_default().insert(0, "segoe".into());
    }
    if let Ok(bytes) = std::fs::read(fonts_dir.join("seguisb.ttf")) {
        defs.font_data.insert("segoe-sb".into(), Arc::new(FontData::from_owned(bytes)));
        let mut fam = vec!["segoe-sb".to_string()];
        fam.extend(defs.families.get(&FontFamily::Proportional).cloned().unwrap_or_default());
        defs.families.insert(FontFamily::Name("semibold".into()), fam);
        semibold = true;
    }
    // Символы вроде ✔ берём из Segoe UI Symbol, если основного шрифта не хватит
    if let Ok(bytes) = std::fs::read(fonts_dir.join("seguisym.ttf")) {
        defs.font_data.insert("segoe-sym".into(), Arc::new(FontData::from_owned(bytes)));
        defs.families.entry(FontFamily::Proportional).or_default().push("segoe-sym".into());
    }
    ctx.set_fonts(defs);
    semibold
}

fn setup_style(ctx: &egui::Context) {
    let mut v = egui::Visuals::dark();
    v.override_text_color = Some(TEXT);
    v.panel_fill = BG;
    v.window_fill = SURFACE1;
    v.extreme_bg_color = SURFACE2;
    v.text_edit_bg_color = Some(SURFACE2);
    v.selection.bg_fill = Color32::from_rgba_unmultiplied(0xf0, 0xb2, 0x3a, 90);
    v.selection.stroke = Stroke::new(1.0, ACCENT);
    v.hyperlink_color = ACCENT;
    let r = CornerRadius::same(5);
    for (w, fill) in [
        (&mut v.widgets.noninteractive, SURFACE1),
        (&mut v.widgets.inactive, SURFACE2),
        (&mut v.widgets.hovered, SURFACE3),
        (&mut v.widgets.active, SURFACE3),
        (&mut v.widgets.open, SURFACE2),
    ] {
        w.bg_fill = fill;
        w.weak_bg_fill = fill;
        w.corner_radius = r;
        w.bg_stroke = Stroke::new(1.0, LINE);
        w.expansion = 0.0;
    }
    v.widgets.noninteractive.fg_stroke = Stroke::new(1.0, TEXT);
    v.widgets.inactive.fg_stroke = Stroke::new(1.6, ACCENT); // галочка в чекбоксе
    v.widgets.hovered.fg_stroke = Stroke::new(1.6, ACCENT);
    v.widgets.active.fg_stroke = Stroke::new(1.6, ACCENT);
    v.widgets.hovered.bg_stroke = Stroke::new(1.0, ACCENT.gamma_multiply(0.6));
    v.widgets.active.bg_stroke = Stroke::new(1.0, ACCENT);
    // Обе темы одинаковые: окно всегда тёмное, как лаунчер, даже при светлой теме Windows
    ctx.all_styles_mut(|s| {
        s.visuals = v.clone();
        s.spacing.icon_width = 18.0;
        s.spacing.icon_width_inner = 10.0;
        s.spacing.icon_spacing = 10.0;
        s.spacing.button_padding = Vec2::new(12.0, 6.0);
    });
}
