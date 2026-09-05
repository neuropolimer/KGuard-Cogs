# KGuard-Cogs

Мои cog'и для Red-DiscordBot 3.5.x.

Сейчас в репозитории:

- `tempvoice` — временные голосовые каналы;
- `modslash` — slash-интерфейс поверх уже настроенной модерации Red;
- `muteguard` — персональные ограничения поверх ролевого мута Red без выдачи доступа к скрытым каналам.

## ModSlash

`modslash` не создаёт отдельную систему наказаний. Slash-команда передаётся соответствующей обычной команде Red, поэтому сохраняются:

- правила из Permissions;
- проверки ролей и иерархии;
- Warnings и Mutes;
- ModLog и номера case'ов;
- настройки Mod, Mutes, Warnings и Reports.

Если исходная Red-команда запрещена модератору, slash-версия тоже не выполнится.

### Команды

Основные slash-команды:

- Warnings: `/warn`, `/warnings`, `/warns`, `/unwarn`, `/warningsid`, `/unwarnid`;
- Mutes: `/mute`, `/unmute`, `/timeout`, `/activemutes`, `/mutechannel`, `/unmutechannel`, `/voicemute`, `/voiceunmute`;
- Mod: `/ban`, `/banid`, `/unban`, `/tempban`, `/tempbanid`, `/kick`, `/massban`, `/softban`, `/voiceban`, `/voicekick`, `/voiceunban`, `/rename`, `/names`, `/userinfo`, `/slowmode`;
- ModLog: `/case`, `/casesfor`, `/cases`, `/casesid`, `/listcases`, `/listcasesid`, `/reason`. `/cases`, `/кейсы` и `/casesid` открывают историю через выпадающий список;
- Reports: `/report`, `/report-interact`.

Русские псевдонимы для часто используемых команд:

`/варн`, `/пред`, `/варны`, `/преды`, `/мут`, `/размут`, `/таймаут`, `/бан`, `/разбан`, `/тбан`, `/кик`, `/софтбан`, `/кейс`, `/кейсы`, `/репорт`.

`cleanup`, `clear` и `purge` намеренно не добавлены.

Команды с суффиксом `id` нужны для случаев, когда пользователя уже нельзя выбрать через Discord-пикер — например, он вышел с сервера.

### История через /cases

`/cases` и `/кейсы` показывают последний case и нативный Discord dropdown `Выбрать case…`. В списке видно номер, тип, дату и начало причины. Если case'ов больше 25, появляется отдельный dropdown для выбора страницы истории. `/casesfor` оставлен как штатный вариант Red с его стандартной пагинацией.

### Срок наказания

Поля `duration` / `срок` свободные. Можно вводить значения, которые понимает Red, например:

`1s`, `30s`, `1m`, `15m`, `1h`, `12h`, `1d`, `3d`, `1 week`.

Discord показывает autocomplete с частыми вариантами, но ввод не ограничен списком. Если срок `tempban` не указан, используется текущий default Red.

### Установка ModSlash

Если репозиторий KGuard-Cogs уже подключён:

```text
[p]load downloader
[p]repo update
[p]cog install KGuard-Cogs modslash
[p]load modslash
[p]slash sync
```

Если репозиторий ещё не подключён:

```text
[p]load downloader
[p]repo add KGuard-Cogs https://github.com/neuropolimer/KGuard-Cogs
[p]cog install KGuard-Cogs modslash
[p]load modslash
[p]slash sync
```

Application-команды `modslash` помечены как обязательные самим cog, поэтому `slash enablecog` не требуется.

После обновления `modslash`:

```text
[p]cog update modslash
[p]reload modslash
[p]slash sync
```

## TempVoice

Пользователь заходит в канал-генератор, cog создаёт временный голосовой канал и переносит туда. Когда в комнате не остаётся обычных пользователей, канал удаляется.

Поддерживаются несколько генераторов, шаблоны имён, восстановление после перезапуска и передача владельца. Владелец может менять название и лимит, закрывать/скрывать комнату, разрешать доступ и отключать участников.

Владелец всегда получает явные `View Channel` + `Connect`, поэтому после `lock` или `hide` он не запирает самого себя. При передаче владельца этот доступ переносится новому владельцу.

### Установка TempVoice

```text
[p]load downloader
[p]repo add KGuard-Cogs https://github.com/neuropolimer/KGuard-Cogs
[p]cog install KGuard-Cogs tempvoice
[p]load tempvoice
```

Проверить настройку:

```text
[p]tempvoiceset list
```

### Настройка генераторов

```text
[p]tempvoiceset add <creator_channel> <category> <template>
[p]tempvoiceset remove <creator_channel>
[p]tempvoiceset template <creator_channel> <template>
```

В шаблоне должен быть `{nick}`.

### Команды временного канала

| Команда | Что делает |
|---|---|
| `[p]vc rename <название>` | Переименовать канал |
| `[p]vc limit <0-99>` | Задать лимит пользователей |
| `[p]vc lock` / `[p]vc unlock` | Закрыть или открыть подключение |
| `[p]vc hide` / `[p]vc show` | Скрыть или показать канал |
| `[p]vc permit @user` | Разрешить пользователю вход |
| `[p]vc reject @user` | Запретить вход и отключить пользователя |
| `[p]vc kick @user` | Отключить пользователя без постоянного запрета |

Для работы боту нужны `View Channel`, `Connect`, `Manage Channels` и `Move Members`.

### Обновление TempVoice

```text
[p]cog update tempvoice
[p]reload tempvoice
```


## MuteGuard

`muteguard` работает поверх штатного `Mutes`. Само наказание, срок, ModLog и снятие мута остаются у Red; cog реагирует на появление/снятие настроенной роли-заглушки.

При активной заглушке cog запрещает участнику отправку сообщений и TTS, вложения/эмбеды, реакции, создание и использование веток, application-команды, голосовые сообщения и опросы, подключение и разговор в голосовых, видео/стрим, soundboard и активности. `Read Message History` / `История сообщений` MuteGuard не изменяет: пользователь продолжает читать старые сообщения там, где это право у него уже было.

`View Channel` / `Просмотр канала` MuteGuard намеренно никогда не выставляет ни в `Allow`, ни в `Deny`. То же самое относится к `Read Message History`: cog не выдаёт его принудительно и не запрещает. Новый member overwrite создаётся только для категорий/каналов, которые участник уже мог видеть. Поэтому роль-заглушка не открывает закрытые категории. Если во время мута участнику добавят новую роль доступа или изменят права категории, MuteGuard пересчитает доступ и наложит ограничения там, где доступ появился.

Для синхронизированных каналов ограничения ставятся на категорию, чтобы не ломать permission sync. Для несинхронизированных каналов и TempVoice-комнат используется персональный overwrite самого канала.

Перед изменением MuteGuard сохраняет только затронутые поля существующего member overwrite. При снятии заглушки он восстанавливает их и не удаляет посторонние разрешения, созданные вручную или другими cog'ами. Если другой cog меняет те же поля во время мута, MuteGuard запоминает новое базовое значение и продолжает держать поверх него запрет до unmute.

Если участник уже находится в голосовом канале в момент мута, MuteGuard отключает его от канала. Для этого боту нужно `Move Members`.

Владелец сервера и участники с правом `Administrator` обходят канальные permission overwrites Discord, поэтому такой мут на них не действует.

### Установка MuteGuard

Если KGuard-Cogs уже подключён:

```text
[p]load downloader
[p]repo update
[p]cog install KGuard-Cogs muteguard
[p]load muteguard
```

Укажи MuteGuard ту же роль, которую использует штатный Mutes:

```text
[p]muteset role <роль или ID>
[p]muteguardset role <роль или ID>
```

Проверка и ручная пересинхронизация:

```text
[p]muteguardset status
[p]muteguardset sync
```

Отключить MuteGuard с восстановлением сохранённых overwrites:

```text
[p]muteguardset disable
```

Для работы нужны `Manage Roles` (выдача роли и изменение permission overwrites) и `Move Members` для немедленного отключения уже сидящего в голосовом пользователя.
