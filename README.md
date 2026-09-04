# KGuard-Cogs

Мои cog'и для Red-DiscordBot 3.5.x.

Сейчас в репозитории:

- `tempvoice` — временные голосовые каналы;
- `modslash` — удобный slash-интерфейс поверх уже настроенной модерации Red.

## ModSlash

`modslash` не создаёт отдельную систему наказаний. Slash-команда преобразуется в вызов соответствующей обычной команды Red, поэтому сохраняются существующие:

- права и правила из Permissions;
- проверки ролей и иерархии;
- Warnings;
- Mutes;
- ModLog и номера cases;
- настройки Mod, Mutes, Warnings и Reports.

Если исходная Red-команда запрещена конкретному модератору, её slash-версия тоже не выполнится.

### Команды

Основные slash-команды:

- Warnings: `/warn`, `/warnings`, `/warns`, `/unwarn`;
- Mutes: `/mute`, `/unmute`, `/timeout`, `/activemutes`, `/mutechannel`, `/unmutechannel`, `/voicemute`, `/voiceunmute`;
- Mod: `/ban`, `/unban`, `/tempban`, `/kick`, `/massban`, `/softban`, `/voiceban`, `/voicekick`, `/voiceunban`, `/rename`, `/names`, `/userinfo`, `/slowmode`;
- ModLog: `/case`, `/casesfor`, `/cases`, `/listcases`, `/reason`;
- Reports: `/report`, `/report-interact`.

Русские псевдонимы для часто используемых команд:

`/варн`, `/пред`, `/варны`, `/преды`, `/мут`, `/размут`, `/таймаут`, `/бан`, `/разбан`, `/тбан`, `/кик`, `/софтбан`, `/кейс`, `/кейсы`, `/репорт`.

`cleanup`, `clear` и `purge` намеренно не добавлены.

### Срок наказания

Поля `duration` / `срок` не ограничены фиксированным списком. Можно вводить значения, которые понимает Red, например:

`1s`, `30s`, `1m`, `15m`, `1h`, `12h`, `1d`, `3d`, `1 week`.

Discord дополнительно показывает autocomplete с частыми вариантами, но можно вписать свой срок вручную.

### Установка ModSlash

Если репозиторий KGuard-Cogs уже подключён:

```text
[p]cog install KGuard-Cogs modslash
[p]load modslash
[p]slash enablecog ModSlash
[p]slash sync
```

Если репозиторий ещё не подключён:

```text
[p]load downloader
[p]repo add KGuard-Cogs https://github.com/neuropolimer/KGuard-Cogs
[p]cog install KGuard-Cogs modslash
[p]load modslash
[p]slash enablecog ModSlash
[p]slash sync
```

После обновлений:

```text
[p]cog update modslash
[p]reload modslash
[p]slash sync
```

## TempVoice

Пользователь заходит в канал-генератор, cog создаёт для него временный голосовой канал и переносит туда. Когда канал пустеет, он удаляется.

Поддерживаются несколько генераторов, собственные шаблоны имён, восстановление после перезапуска Red и передача владельца другому участнику. Владелец временного канала может менять название и лимит, закрывать или скрывать канал, разрешать доступ отдельным людям и отключать участников.

### Установка TempVoice

```text
[p]load downloader
[p]repo add KGuard-Cogs https://github.com/neuropolimer/KGuard-Cogs
[p]cog install KGuard-Cogs tempvoice
[p]load tempvoice
```

Проверить текущую настройку:

```text
[p]tempvoiceset list
```

### Настройка генераторов

```text
[p]tempvoiceset add <creator_channel> <category> <template>
[p]tempvoiceset remove <creator_channel>
[p]tempvoiceset template <creator_channel> <template>
```

В шаблоне должен быть `{nick}`. Каналы и категории можно передавать упоминанием или ID.

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
