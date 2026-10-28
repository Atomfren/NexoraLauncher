# Заявка на доступ к Minecraft API (aka.ms/mce-reviewappid)

Форма на английском, отвечать тоже нужно по-английски. Заявки рассматривают раз в неделю,
ответ приходит письмом. **Повторные отправки не ускоряют рассмотрение** — об этом сказано
в самой форме.

Перед заполнением нужно зарегистрировать приложение в Azure
(см. [microsoft-login.md](microsoft-login.md)): без Application ID и Tenant ID заявку не принять.

---

## Сначала — о риске, которого не видно из формы

В условиях прямо написано:

> Applications must verify the user's game ownership and require authentication before enabling
> gameplay or access to servers or sites. Applications that bypass or disable authentication,
> ownership or license checks, or other safety features will not be approved.

У Nexora есть офлайн-вход. Формально он **не** обходит проверку: он вообще не обращается
ни к Microsoft, ни к серверам Minecraft и не выдаёт доступ к лицензионным серверам —
те проверяют лицензию сами. Но рецензент увидит на сайте слова про офлайн-аккаунт
и может решить иначе.

Поэтому:

1. **Не скрывайте офлайн-режим в заявке.** Если умолчать, а рецензент увидит его на сайте,
   отказ будет гарантирован, и повторно заходить будет тяжелее.
2. **Проверьте формулировку на сайте.** Сейчас в разделе «Вопросы» написано: «Офлайн-аккаунт
   подходит для одиночной игры и серверов без проверки лицензии». Вторая половина читается
   как обещание играть без покупки. По сути это правда — такие серверы существуют и
   принадлежат их владельцам, — но точнее будет сказать «для одиночной игры и собственных
   серверов». Менять стоит ради точности, а не ради того, чтобы спрятать.
3. **Будьте готовы к отказу.** Это не формальность: одобрение не гарантировано даже тем,
   у кого офлайн-режима нет.

Что работает в вашу пользу: вход через Microsoft у вас уже проверяет владение игрой —
если на аккаунте нет профиля Minecraft Java Edition, лаунчер отказывает и не запускает игру
(`backend/core/auth.py`, строки 333–335).

---

## Ответы по полям формы

**1. I verify that I have read and understood the EULA and all Usage Guidelines**
→ `Yes` (перед этим действительно прочитайте: <http://aka.ms/mcusageguidelines>)

**2. Contact Information (Valid email address)**
→ Почта, **на которую зарегистрирована учётная запись Azure**. Форма прямо говорит, что
контакт сверяют с Azure Portal: другой адрес затянет или завалит рассмотрение.

**3. What type of request is this?**
→ `New AppID for Approval`

**4. Application Name**
→ `NexoraLauncher`

В названии запрещены слова Mojang, Minecraft, Microsoft, Live, Xbox, Discord и Hypixel.
«NexoraLauncher» подходит. Название должно совпадать с тем, что указано в Azure.

**5. Application ID**
→ GUID из Azure: раздел приложения → Overview → Application (client) ID.

**6. Tenant ID**
→ GUID оттуда же: Directory (tenant) ID. Для новой заявки поле обязательное.

**7. Associated website or domain**
→ `https://nexoralauncher.ru`

**8. Justification** — текст ниже целиком.

**9. Any other information** — текст ниже.

---

## Поле 8: Justification

```
NexoraLauncher is a free desktop launcher for Minecraft: Java Edition on Windows,
developed by an independent author and distributed at https://nexoralauncher.ru

We request access so that players can sign in with their own Microsoft account.
The AppID is used for one purpose only: the MSAL device code flow with the
XboxLive.signin scope, followed by Xbox Live, XSTS and the Minecraft services
login. We request no other scopes and store no Microsoft credentials: the password
is entered on the Microsoft page and never reaches the launcher. Access and refresh
tokens are stored encrypted on the player's own computer.

Ownership is verified. After the Minecraft login we request the player's profile,
and if the account has no Minecraft: Java Edition profile the launcher stops with
an explicit message and refuses to start the game. We do not bypass, weaken or work
around authentication, ownership or license checks, and we do not modify game files
to that end.

What the launcher adds beyond starting the game: it reads the crash log and crash
report after a crash and explains the cause in plain language with a suggested fix,
installs mods and modpacks from Modrinth, FTB and CurseForge, and can run a local
server for the player and their friends.

For completeness: the launcher also offers an offline account, used for single
player and for servers the player runs themselves. That path never contacts
Microsoft or Minecraft services and never uses this AppID; it grants no access to
official servers, which perform their own verification. We mention it openly so the
review has the full picture.

Updates are delivered over HTTPS from our own domain, signed with an Ed25519 key and
verified by SHA-256 before installation, so a tampered build cannot be installed.
```

## Поле 9: Any other information

```
The launcher is new and currently has a small number of users. The Windows installer
is not yet signed with a code signing certificate, which we plan to add.

Happy to provide a build, source access or any further detail on request — please
write to the contact address above.
```

---

## После отправки

- Ответ приходит письмом; рассмотрение раз в неделю.
- **Не отправляйте форму повторно** — в ней прямо сказано, что это не ускоряет очередь.
- После одобрения Microsoft просит подождать до суток, прежде чем изменения вступят в силу.
- Пока одобрения нет, `api.minecraftservices.com` отвечает 403, и лаунчер показывает
  игроку ссылку на эту же форму — это уже сделано в коде.
