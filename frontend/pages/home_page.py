"""Главная страница: быстрый запуск и последние инстансы."""

from PyQt6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout

from frontend.components import InstanceCard, launch_instance, loader_title
from frontend.widgets import AppContext, Page, button, clear_layout, label, set_variant
from shared.i18n import t

_RECENT = 5


class HomePage(Page):
    """Приветствие, кнопка «Играть» для последнего инстанса, список последних."""

    def __init__(self, ctx: AppContext):
        super().__init__(ctx, t("home.title"))
        self._last: dict | None = None
        self._account: dict | None = None

        self.hero = QFrame()
        self.hero.setObjectName("Hero")
        hero_layout = QHBoxLayout(self.hero)
        hero_layout.setContentsMargins(24, 22, 24, 22)
        text = QVBoxLayout()
        self.greeting = label("", "PageTitle")
        self.hero_info = label("", muted=True, wrap=True)
        text.addWidget(self.greeting)
        text.addWidget(self.hero_info)
        hero_layout.addLayout(text, 1)
        self.hero_btn = button(t("home.play"), self._hero_action, "play")
        self.hero_btn.setMinimumSize(170, 46)
        self.hero_btn.setStyleSheet("font-size: 15px;")
        hero_layout.addWidget(self.hero_btn)
        self.body.addWidget(self.hero)

        quick = QHBoxLayout()
        quick.addWidget(button(t("home.new_instance"),
                               lambda: ctx.navigate.emit("instances", {"create": True})))
        quick.addWidget(button(t("home.browse_mods"), lambda: ctx.navigate.emit("mods", {})))
        quick.addWidget(button(t("home.browse_modpacks"), lambda: ctx.navigate.emit("modpacks", {})))
        quick.addStretch()
        self.body.addLayout(quick)

        self.body.addWidget(label(t("home.recent"), "SectionTitle"))
        self.recent = QVBoxLayout()
        self.recent.setSpacing(8)
        self.body.addLayout(self.recent)
        self.body.addStretch()

        ctx.instances_changed.connect(self.reload)
        ctx.accounts_changed.connect(self.reload)

    def on_show(self, first: bool) -> None:
        self.reload()

    def reload(self) -> None:
        def fetch():
            return self.api.accounts(), self.api.instances(), self.api.settings()

        self.run(fetch, self._render)

    def _render(self, data) -> None:
        accounts, instances, settings = data
        account = next((a for a in accounts if a["active"]), None)
        self.greeting.setText(t("home.greeting", name=account["username"]) if account else t("home.welcome"))

        by_recent = sorted(instances, key=lambda i: i.get("last_played") or i.get("created_at", ""),
                           reverse=True)
        last_name = settings.get("last_instance")
        self._last = next((i for i in instances if i["name"] == last_name), None) or \
            (by_recent[0] if by_recent else None)

        if not account:
            self.hero_info.setText(t("home.no_account"))
            self.hero_btn.setText(t("home.add_account"))
            set_variant(self.hero_btn, "primary")
        elif not self._last:
            self.hero_info.setText(t("home.no_instances"))
            self.hero_btn.setText(t("home.create_first"))
            set_variant(self.hero_btn, "primary")
        else:
            last = self._last
            self.hero_info.setText(t("home.last_instance", name=last["name"],
                                     loader=loader_title(last), version=last["version"]))
            running = bool(last.get("running_pid"))
            self.hero_btn.setText(t("instance.running") if running else t("home.play"))
            self.hero_btn.setEnabled(not running)
            set_variant(self.hero_btn, "play")
        self._account = account

        clear_layout(self.recent)
        if not instances:
            self.recent.addWidget(label(t("instances.empty"), "Empty"))
        for instance in by_recent[:_RECENT]:
            self.recent.addWidget(InstanceCard(self.ctx, instance, compact=True))

    def _hero_action(self) -> None:
        if not self._account:
            self.ctx.navigate.emit("accounts", {})
        elif not self._last:
            self.ctx.navigate.emit("instances", {"create": True})
        else:
            self.hero_btn.setEnabled(False)
            self.hero_btn.setText(t("instance.launching"))
            launch_instance(self.ctx, self, self._last["name"], lambda _ok: self.reload())
