# KGuard-Cogs

Мои cog'и для Red-DiscordBot 3.5.x. Сейчас здесь лежит `tempvoice` — управление временными голосовыми каналами.

## TempVoice

Пользователь заходит в канал-генератор, cog создаёт для него временный голосовой канал и переносит туда. Когда канал пустеет, он удаляется.

Поддерживаются несколько генераторов, собственные шаблоны имён, восстановление после перезапуска Red и передача владельца другому участнику. Владелец временного канала может менять название и лимит, закрывать или скрывать канал, разрешать доступ отдельным людям и отключать участников.

## Установка

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

## Настройка генераторов

```text
[p]tempvoiceset add <creator_channel> <category> <template>
[p]tempvoiceset remove <creator_channel>
[p]tempvoiceset template <creator_channel> <template>
```

В шаблоне должен быть `{nick}`. Каналы и категории можно передавать упоминанием или ID.

## Команды временного канала

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

## Обновление

```text
[p]cog update tempvoice
[p]reload tempvoice
```
