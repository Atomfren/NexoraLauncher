"""Страница миров: выбор инстанса + управление сохранениями."""

from frontend.panels import WorldsPanel
from frontend.widgets import AppContext, Page, fill_instance_combo, instance_combo, label
from shared.i18n import t


class WorldsPage(Page):
    def __init__(self, ctx: AppContext):
        super().__init__(ctx, t("worlds.title"), t("worlds.subtitle"), scroll=False)
        self.toolbar.addWidget(label(t("browse.for_instance"), muted=True))
        self.combo = instance_combo()
        self.combo.currentIndexChanged.connect(lambda _i: self.panel.set_instance(self.combo.currentData()))
        self.toolbar.addWidget(self.combo)
        self.toolbar.addStretch()
        self.panel = WorldsPanel(ctx)
        self.panel.layout().setContentsMargins(0, 0, 0, 0)
        self.body.addWidget(self.panel, 1)
        ctx.instances_changed.connect(self._load)

    def on_show(self, first: bool) -> None:
        self._load()

    def _load(self) -> None:
        def fill(instances: list[dict]) -> None:
            keep = (self.combo.currentData() or {}).get("name") or self.ctx.settings.get("last_instance")
            fill_instance_combo(self.combo, instances, keep)
            self.panel.set_instance(self.combo.currentData())

        self.run(self.api.instances, fill)
