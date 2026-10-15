"""Каталог Modrinth: моды, модпаки, ресурспаки, шейдеры."""

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout

from frontend.utils.worker import run_async
from frontend.widgets import (
    AppContext,
    Card,
    IconCache,
    Page,
    ask_text,
    badge,
    button,
    clear_layout,
    fill_instance_combo,
    format_count,
    instance_combo,
    label,
    open_url,
    show_error,
)
from shared.i18n import t

_PAGE_SIZE = 20
_TITLES = {
    "mod": ("browse.mods_title", "browse.mods_subtitle"),
    "modpack": ("browse.modpacks_title", "browse.modpacks_subtitle"),
    "resourcepack": ("browse.resourcepacks_title", "browse.resourcepacks_subtitle"),
    "shader": ("browse.shaders_title", "browse.shaders_subtitle"),
}
_SORTS = [("relevance", "browse.sort_relevance"), ("downloads", "browse.sort_downloads"),
          ("follows", "browse.sort_follows"), ("newest", "browse.sort_newest"),
          ("updated", "browse.sort_updated")]


class BrowsePage(Page):
    """Поиск и установка проектов Modrinth."""

    def __init__(self, ctx: AppContext, project_type: str):
        title_key, subtitle_key = _TITLES[project_type]
        super().__init__(ctx, t(title_key), t(subtitle_key))
        self.project_type = project_type
        self._offset = 0
        self._total = 0
        self._request_id = 0
        self._preselect: str | None = None
        self._installed: set[str] = set()

        self.search = QLineEdit()
        self.search.setPlaceholderText(t("browse.search"))
        self.search.setClearButtonEnabled(True)
        self.search.returnPressed.connect(self.new_search)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(450)
        self._debounce.timeout.connect(self.new_search)
        self.search.textEdited.connect(lambda _t: self._debounce.start())
        self.toolbar.addWidget(self.search, 1)

        self.sort = QComboBox()
        for key, title_key in _SORTS:
            self.sort.addItem(t(title_key), key)
        self.sort.setCurrentIndex(1)
        self.sort.currentIndexChanged.connect(self.new_search)
        self.toolbar.addWidget(self.sort)

        self.instance_combo = None
        if project_type != "modpack":
            self.toolbar.addWidget(label(t("browse.for_instance"), muted=True))
            self.instance_combo = instance_combo()
            self.instance_combo.currentIndexChanged.connect(self._on_instance_changed)
            self.toolbar.addWidget(self.instance_combo)
            ctx.instances_changed.connect(self._load_instances)

        self.results = QVBoxLayout()
        self.results.setSpacing(8)
        self.body.addLayout(self.results)
        self.more_btn = button(t("browse.load_more"), self._load_more)
        self.more_btn.hide()
        self.body.addWidget(self.more_btn)
        self.body.addStretch()

    # --- Данные ---------------------------------------------------------------------
    def on_show(self, first: bool) -> None:
        if self.instance_combo is not None:
            self._load_instances()
        elif first:
            self.new_search()

    def apply_params(self, params: dict) -> None:
        if params.get("instance"):
            self._preselect = params["instance"]
            if self.instance_combo is not None and self.instance_combo.count():
                self._load_instances()

    def _load_instances(self) -> None:
        def fill(instances: list[dict]) -> None:
            if self.project_type == "mod":
                instances = [i for i in instances if i["mod_loader"] != "vanilla"]
            previous = (self.instance_combo.currentData() or {}).get("name")
            keep = self._preselect or previous or self.ctx.settings.get("last_instance")
            self._preselect = None
            fill_instance_combo(self.instance_combo, instances, keep, include_empty=t("browse.any_instance"))
            current = (self.instance_combo.currentData() or {}).get("name")
            if current != previous or self.results.count() == 0:
                self._on_instance_changed()

        self.run(self.api.instances, fill)

    def _target(self) -> dict | None:
        return self.instance_combo.currentData() if self.instance_combo is not None else None

    def _on_instance_changed(self) -> None:
        target = self._target()
        self._installed = set()
        if target:
            name = target["name"]
            run_async(lambda: self.api.installed_content(name, self.project_type),
                      lambda items: self._set_installed({i["project_id"] for i in items if i["project_id"]}),
                      lambda _m: None, owner=self)
        self.new_search()

    def _set_installed(self, ids: set[str]) -> None:
        self._installed = ids
        for i in range(self.results.count()):
            widget = self.results.itemAt(i).widget()
            if isinstance(widget, ProjectCard):
                widget.set_installed(widget.project["project_id"] in ids)

    def new_search(self) -> None:
        self._offset = 0
        clear_layout(self.results)
        loading = label(t("common.loading"), "Empty")
        self.results.addWidget(loading)
        self.more_btn.hide()
        self._fetch()

    def _load_more(self) -> None:
        self._offset += _PAGE_SIZE
        self.more_btn.setEnabled(False)
        self._fetch()

    def _fetch(self) -> None:
        self._request_id += 1
        request_id = self._request_id
        target = self._target()
        game_version = target["version"] if target else None
        loader = None
        if target and self.project_type == "mod":
            loader = target["mod_loader"]
        query, index, offset = self.search.text().strip(), self.sort.currentData(), self._offset

        def done(data: dict) -> None:
            if request_id != self._request_id:
                return
            if offset == 0:
                clear_layout(self.results)
            self._total = data["total"]
            for project in data["results"]:
                card = ProjectCard(self, project)
                card.set_installed(project["project_id"] in self._installed)
                self.results.addWidget(card)
            if offset == 0 and not data["results"]:
                self.results.addWidget(label(t("common.nothing_found"), "Empty"))
            self.more_btn.setEnabled(True)
            self.more_btn.setVisible(offset + _PAGE_SIZE < self._total)

        def failed(message: str) -> None:
            if request_id != self._request_id:
                return
            clear_layout(self.results)
            self.results.addWidget(label(message, "Empty", wrap=True))
            self.more_btn.setEnabled(True)

        run_async(lambda: self.api.search(self.project_type, query, game_version, loader, index,
                                          _PAGE_SIZE, offset), done, failed, owner=self)

    # --- Установка -------------------------------------------------------------------
    def install(self, card: "ProjectCard") -> None:
        project = card.project
        if self.project_type == "modpack":
            name = ask_text(self, t("browse.install_modpack"), t("browse.instance_name"), project["title"])
            if not name:
                return
            card.set_busy(True)
            self.run(lambda: self.api.install_modpack(project["project_id"], new_name=name),
                     lambda task: self.track(task, lambda _t: (card.set_busy(False), card.set_installed(True)),
                                             lambda msg: (card.set_busy(False), show_error(self, msg))),
                     lambda msg: (card.set_busy(False), show_error(self, msg)))
            return

        target = self._target()
        if not target:
            show_error(self, t("browse.choose_instance"))
            return
        card.set_busy(True)
        instance_name = target["name"]

        def installed(task: dict) -> None:
            card.set_busy(False)
            ids = {item["project_id"] for item in (task.get("result") or [])}
            self._set_installed(self._installed | ids | {project["project_id"]})

        def failed(message: str) -> None:
            card.set_busy(False)
            show_error(self, message)

        self.run(lambda: self.api.install_content(instance_name, self.project_type, project["project_id"]),
                 lambda task: self.track(task, installed, failed), failed)


class ProjectCard(Card):
    """Карточка проекта Modrinth."""

    def __init__(self, page: BrowsePage, project: dict):
        super().__init__()
        self.page = page
        self.project = project
        icon = QLabel()
        IconCache.load_into(icon, project.get("icon_url"), 56)
        self.layout_.addWidget(icon)

        info = QVBoxLayout()
        info.setSpacing(3)
        title = QHBoxLayout()
        title.setSpacing(8)
        title.addWidget(label(project["title"], "CardTitle"))
        if project.get("author"):
            title.addWidget(label(t("browse.by", author=project["author"]), muted=True))
        title.addStretch()
        info.addLayout(title)
        description = label(project.get("description", ""), wrap=True)
        info.addWidget(description)
        meta = QHBoxLayout()
        meta.setSpacing(6)
        meta.addWidget(label(t("browse.downloads", n=format_count(project.get("downloads", 0))), muted=True))
        for category in project.get("categories", [])[:4]:
            meta.addWidget(badge(category))
        meta.addStretch()
        info.addLayout(meta)
        self.layout_.addLayout(info, 1)

        side = QVBoxLayout()
        self.install_btn = button(t("browse.install"), lambda: page.install(self), "primary")
        self.install_btn.setMinimumWidth(120)
        side.addWidget(self.install_btn)
        side.addWidget(button(t("browse.open_site"), self._open_site, "ghost"))
        side.addStretch()
        self.layout_.addLayout(side)

    def _open_site(self) -> None:
        kind = self.project.get("project_type") or self.page.project_type
        open_url(f"https://modrinth.com/{kind}/{self.project.get('slug') or self.project['project_id']}")

    def set_busy(self, busy: bool) -> None:
        self.install_btn.setEnabled(not busy)
        self.install_btn.setText(t("browse.installing") if busy else t("browse.install"))

    def set_installed(self, installed: bool) -> None:
        if installed and self.page.project_type != "modpack":
            self.install_btn.setText(t("browse.installed"))
            self.install_btn.setProperty("variant", "")
        else:
            self.install_btn.setText(t("browse.install"))
            self.install_btn.setProperty("variant", "primary")
        self.install_btn.style().unpolish(self.install_btn)
        self.install_btn.style().polish(self.install_btn)
