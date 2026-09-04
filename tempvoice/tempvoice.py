import asyncio
import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box, pagify


log = logging.getLogger("red.neuropolimer.tempvoice")


DEFAULT_GENERATORS: Dict[int, Dict[str, Any]] = {
    1540378275438665739: {
        "category_id": 1540377033794912397,
        "template": "🔊 Канал {nick}",
    },
    1540379320076337253: {
        "category_id": 1540357744618508289,
        "template": "🔊 Канал {nick}",
    },
}


class TempVoice(commands.Cog):
    """Временные голосовые комнаты с управлением владельцем."""

    __author__ = "neuropolimer"
    __version__ = "1.1.0"

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(
            self,
            identifier=1540378275438665739,
            force_registration=True,
        )
        self.config.register_guild(
            generators={},
            rooms={},
            defaults_seeded=False,
        )

        self._generators: Dict[int, Dict[int, Dict[str, Any]]] = defaultdict(dict)
        self._rooms: Dict[int, Dict[int, Dict[str, int]]] = defaultdict(dict)
        self._guild_locks: Dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._member_locks: Dict[Tuple[int, int], asyncio.Lock] = defaultdict(asyncio.Lock)
        self._channel_locks: Dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._ready_task: Optional[asyncio.Task] = None

    async def cog_load(self) -> None:
        """Загрузить Config в быстрый кэш и запустить восстановление после готовности Red."""
        all_guilds = await self.config.all_guilds()
        for guild_id, data in all_guilds.items():
            gid = int(guild_id)
            self._generators[gid] = self._decode_generators(data.get("generators", {}))
            self._rooms[gid] = self._decode_rooms(data.get("rooms", {}))

        self._ready_task = asyncio.create_task(self._initialize_after_ready())

    def cog_unload(self) -> None:
        if self._ready_task is not None:
            self._ready_task.cancel()

    @staticmethod
    def _decode_generators(data: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
        decoded: Dict[int, Dict[str, Any]] = {}
        for creator_id, settings in data.items():
            try:
                decoded[int(creator_id)] = {
                    "category_id": int(settings["category_id"]),
                    "template": str(settings["template"]),
                }
            except (KeyError, TypeError, ValueError):
                log.warning("Пропущена повреждённая запись генератора %r", creator_id)
        return decoded

    @staticmethod
    def _decode_rooms(data: Dict[str, Any]) -> Dict[int, Dict[str, int]]:
        decoded: Dict[int, Dict[str, int]] = {}
        for channel_id, room in data.items():
            try:
                decoded[int(channel_id)] = {
                    "owner_id": int(room.get("owner_id", 0)),
                    "creator_id": int(room["creator_id"]),
                }
            except (KeyError, TypeError, ValueError):
                log.warning("Пропущена повреждённая запись временной комнаты %r", channel_id)
        return decoded

    async def _initialize_after_ready(self) -> None:
        try:
            waiter = getattr(self.bot, "wait_until_red_ready", self.bot.wait_until_ready)
            await waiter()
            for guild in self.bot.guilds:
                await self._seed_default_generators(guild)
                await self._restore_guild_rooms(guild)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Ошибка при восстановлении TempVoice после запуска Red")

    async def _seed_default_generators(self, guild: discord.Guild) -> None:
        guild_config = self.config.guild(guild)
        if await guild_config.defaults_seeded():
            return

        matches: Dict[int, Dict[str, Any]] = {}
        for creator_id, settings in DEFAULT_GENERATORS.items():
            creator = guild.get_channel(creator_id)
            category = guild.get_channel(settings["category_id"])
            if isinstance(creator, discord.VoiceChannel) and isinstance(
                category, discord.CategoryChannel
            ):
                matches[creator_id] = dict(settings)

        if not matches:
            return

        async with self._guild_locks[guild.id]:
            generators = self._generators[guild.id]
            changed = False
            for creator_id, settings in matches.items():
                if creator_id not in generators:
                    generators[creator_id] = settings
                    changed = True
            if changed:
                await self._save_generators_locked(guild.id)

            # Если один из объектов временно отсутствует, повторим проверку после следующего запуска.
            if len(matches) == len(DEFAULT_GENERATORS):
                await guild_config.defaults_seeded.set(True)

    async def _restore_guild_rooms(self, guild: discord.Guild) -> None:
        for channel_id in list(self._rooms[guild.id]):
            channel = guild.get_channel(channel_id)
            if not isinstance(channel, discord.VoiceChannel):
                async with self._guild_locks[guild.id]:
                    self._rooms[guild.id].pop(channel_id, None)
                    await self._save_rooms_locked(guild.id)
                continue
            await self._reconcile_room(channel)

    async def _save_generators_locked(self, guild_id: int) -> None:
        payload = {str(key): value for key, value in self._generators[guild_id].items()}
        await self.config.guild_from_id(guild_id).generators.set(payload)

    async def _save_rooms_locked(self, guild_id: int) -> None:
        payload = {str(key): value for key, value in self._rooms[guild_id].items()}
        await self.config.guild_from_id(guild_id).rooms.set(payload)

    @staticmethod
    def _next_owner(
        channel: discord.VoiceChannel, excluded_id: int = 0
    ) -> Optional[discord.Member]:
        return next(
            (member for member in channel.members if not member.bot and member.id != excluded_id),
            None,
        )

    async def _set_owner_channel_access(
        self,
        channel: discord.VoiceChannel,
        member: discord.Member,
        *,
        enabled: bool,
    ) -> None:
        """Grant/revoke the explicit owner access managed by TempVoice.

        Owners must keep View Channel + Connect even when they lock or hide the
        room from @everyone. When ownership moves, these two owner-specific
        overrides are moved with it while unrelated member overrides are kept.
        """
        me = channel.guild.me
        if me is None or not channel.permissions_for(me).manage_channels:
            log.warning(
                "Cannot update TempVoice owner overwrite in channel %s: missing Manage Channels",
                channel.id,
            )
            return

        overwrite = channel.overwrites_for(member)
        target = True if enabled else None
        if overwrite.view_channel is target and overwrite.connect is target:
            return

        overwrite.view_channel = target
        overwrite.connect = target
        try:
            await channel.set_permissions(
                member,
                overwrite=None if overwrite.is_empty() else overwrite,
                reason=(
                    "TempVoice: grant owner room access"
                    if enabled
                    else "TempVoice: remove previous owner room access"
                ),
            )
        except discord.Forbidden:
            log.warning(
                "Discord denied owner overwrite update for channel %s and member %s",
                channel.id,
                member.id,
            )
        except discord.HTTPException:
            log.exception(
                "Discord API failed owner overwrite update for channel %s and member %s",
                channel.id,
                member.id,
            )

    async def _move_owner_channel_access(
        self,
        channel: discord.VoiceChannel,
        old_owner_id: int,
        new_owner: Optional[discord.Member],
    ) -> None:
        old_owner = channel.guild.get_member(old_owner_id) if old_owner_id else None
        if old_owner is not None and (new_owner is None or old_owner.id != new_owner.id):
            await self._set_owner_channel_access(channel, old_owner, enabled=False)
        if new_owner is not None:
            await self._set_owner_channel_access(channel, new_owner, enabled=True)

    async def _reconcile_room(self, channel: discord.VoiceChannel) -> None:
        """Удалить комнату без людей или восстановить/передать владельца."""
        async with self._channel_locks[channel.id]:
            room = self._rooms[channel.guild.id].get(channel.id)
            if room is None:
                return

            human_members = [member for member in channel.members if not member.bot]
            if not human_members:
                await self._delete_tracked_room(
                    channel, reason="Во временной комнате не осталось пользователей"
                )
                return

            owner_id = int(room.get("owner_id", 0))
            owner = next((member for member in human_members if member.id == owner_id), None)
            if owner is not None:
                # Also migrates rooms created by older TempVoice versions where
                # the owner did not yet have an explicit View/Connect allow.
                await self._set_owner_channel_access(channel, owner, enabled=True)
                return

            new_owner = self._next_owner(channel)
            new_owner_id = new_owner.id if new_owner is not None else 0
            async with self._guild_locks[channel.guild.id]:
                current = self._rooms[channel.guild.id].get(channel.id)
                if current is None:
                    return
                old_owner_id = int(current.get("owner_id", 0))
                current["owner_id"] = new_owner_id
                await self._save_rooms_locked(channel.guild.id)

            await self._move_owner_channel_access(channel, old_owner_id, new_owner)

    async def _delete_tracked_room(self, channel: discord.VoiceChannel, *, reason: str) -> None:
        """Удалить канал только если его ID всё ещё находится в реестре TempVoice."""
        guild_id = channel.guild.id
        if channel.id not in self._rooms[guild_id]:
            return

        try:
            await channel.delete(reason=reason)
        except discord.NotFound:
            pass
        except discord.Forbidden:
            log.warning("Нет права Manage Channels для удаления временного канала %s", channel.id)
            return
        except discord.HTTPException:
            log.exception("Discord API не позволил удалить временный канал %s", channel.id)
            return

        async with self._guild_locks[guild_id]:
            self._rooms[guild_id].pop(channel.id, None)
            await self._save_rooms_locked(guild_id)

    @staticmethod
    def _render_room_name(template: str, member: discord.Member) -> str:
        try:
            rendered = template.format(nick=member.display_name).strip()
        except (KeyError, ValueError, IndexError) as exc:
            raise ValueError("Шаблон содержит неподдерживаемое поле") from exc
        if not rendered:
            rendered = f"🔊 Канал {member.display_name}"
        return rendered[:100]

    @staticmethod
    def _validate_template(template: str) -> Optional[str]:
        template = template.strip()
        if not template:
            return "Шаблон не может быть пустым."
        if "{nick}" not in template:
            return "Шаблон должен содержать поле `{nick}`."
        try:
            rendered = template.format(nick="Ник")
        except (KeyError, ValueError, IndexError):
            return "Разрешено только поле `{nick}`; проверь фигурные скобки."
        if not rendered.strip():
            return "После подстановки ника шаблон не должен быть пустым."
        return None

    async def _handle_generator_join(
        self, member: discord.Member, creator: discord.VoiceChannel
    ) -> None:
        member_lock = self._member_locks[(member.guild.id, member.id)]
        async with member_lock:
            current = getattr(member.voice, "channel", None)
            if current is None or current.id != creator.id:
                return

            guild = member.guild
            target: Optional[discord.VoiceChannel] = None

            async with self._guild_locks[guild.id]:
                settings = self._generators[guild.id].get(creator.id)
                if settings is None:
                    return

                stale_room_ids: List[int] = []
                for room_id, room in self._rooms[guild.id].items():
                    if room.get("owner_id") != member.id:
                        continue
                    existing = guild.get_channel(room_id)
                    if isinstance(existing, discord.VoiceChannel):
                        target = existing
                        break
                    stale_room_ids.append(room_id)

                for room_id in stale_room_ids:
                    self._rooms[guild.id].pop(room_id, None)
                if stale_room_ids:
                    await self._save_rooms_locked(guild.id)

                if target is None:
                    category = guild.get_channel(int(settings["category_id"]))
                    if not isinstance(category, discord.CategoryChannel):
                        log.warning(
                            "Категория %s для генератора %s не найдена",
                            settings["category_id"],
                            creator.id,
                        )
                        return

                    me = guild.me
                    if me is None:
                        return
                    missing = []
                    if not category.permissions_for(me).manage_channels:
                        missing.append("Manage Channels")
                    if not creator.permissions_for(me).move_members:
                        missing.append("Move Members")
                    if missing:
                        log.warning(
                            "Нельзя создать TempVoice-канал в guild %s: не хватает %s",
                            guild.id,
                            ", ".join(missing),
                        )
                        return

                    try:
                        name = self._render_room_name(str(settings["template"]), member)
                        overwrites = dict(category.overwrites)
                        owner_overwrite = overwrites.get(member, discord.PermissionOverwrite())
                        owner_overwrite.view_channel = True
                        owner_overwrite.connect = True
                        overwrites[member] = owner_overwrite
                        target = await guild.create_voice_channel(
                            name,
                            category=category,
                            overwrites=overwrites,
                            reason=f"TempVoice: комнату создал {member} ({member.id})",
                        )
                    except ValueError:
                        log.exception("Повреждён шаблон генератора %s", creator.id)
                        return
                    except discord.Forbidden:
                        log.warning("Discord запретил создать канал для генератора %s", creator.id)
                        return
                    except discord.HTTPException:
                        log.exception("Ошибка Discord API при создании временного канала")
                        return

                    self._rooms[guild.id][target.id] = {
                        "owner_id": member.id,
                        "creator_id": creator.id,
                    }
                    await self._save_rooms_locked(guild.id)

            if target is None:
                return

            current = getattr(member.voice, "channel", None)
            if current is None or current.id != creator.id:
                if not target.members:
                    async with self._channel_locks[target.id]:
                        await self._delete_tracked_room(
                            target, reason="Создатель покинул генератор до перемещения"
                        )
                return

            try:
                await member.move_to(target, reason="TempVoice: перенос в личную комнату")
            except discord.Forbidden:
                log.warning("Нет права Move Members для перемещения пользователя %s", member.id)
            except discord.HTTPException:
                log.exception("Ошибка Discord API при перемещении пользователя %s", member.id)
            else:
                return

            if not target.members:
                async with self._channel_locks[target.id]:
                    await self._delete_tracked_room(
                        target, reason="Не удалось переместить создателя временной комнаты"
                    )

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        before_channel = before.channel
        after_channel = after.channel
        changed_channel = getattr(before_channel, "id", None) != getattr(after_channel, "id", None)

        if not changed_channel:
            return

        # Сначала освободить/передать прежнюю комнату. Иначе владелец, вошедший
        # в генератор, всё ещё выглядел бы владельцем старой комнаты и был бы
        # ошибочно перемещён обратно вместо создания новой.
        if (
            isinstance(before_channel, discord.VoiceChannel)
            and before_channel.id in self._rooms[member.guild.id]
        ):
            await self._reconcile_room(before_channel)

        if (
            not member.bot
            and isinstance(after_channel, discord.VoiceChannel)
            and after_channel.id in self._generators[member.guild.id]
        ):
            await self._handle_generator_join(member, after_channel)

        if (
            isinstance(after_channel, discord.VoiceChannel)
            and after_channel.id in self._rooms[member.guild.id]
        ):
            await self._reconcile_room(after_channel)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        guild_id = channel.guild.id
        async with self._guild_locks[guild_id]:
            changed_rooms = self._rooms[guild_id].pop(channel.id, None) is not None
            changed_generators = self._generators[guild_id].pop(channel.id, None) is not None
            if changed_rooms:
                await self._save_rooms_locked(guild_id)
            if changed_generators:
                await self._save_generators_locked(guild_id)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        await self._seed_default_generators(guild)

    async def red_delete_data_for_user(self, *, requester: str, user_id: int) -> None:
        """Удалить сохранённые ссылки на пользователя по запросу Red."""
        for guild_id, rooms in list(self._rooms.items()):
            changed = False
            async with self._guild_locks[guild_id]:
                guild = self.bot.get_guild(guild_id)
                for channel_id, room in rooms.items():
                    if room.get("owner_id") != user_id:
                        continue
                    channel = guild.get_channel(channel_id) if guild is not None else None
                    if isinstance(channel, discord.VoiceChannel):
                        replacement = self._next_owner(channel, excluded_id=user_id)
                        room["owner_id"] = replacement.id if replacement is not None else 0
                        old_owner = channel.guild.get_member(user_id)
                        if old_owner is not None:
                            await self._set_owner_channel_access(
                                channel, old_owner, enabled=False
                            )
                        if replacement is not None:
                            await self._set_owner_channel_access(
                                channel, replacement, enabled=True
                            )
                    else:
                        room["owner_id"] = 0
                    changed = True
                if changed:
                    await self._save_rooms_locked(guild_id)

    async def _owned_room_or_reply(self, ctx: commands.Context) -> Optional[discord.VoiceChannel]:
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            await ctx.send("Эта команда доступна только на сервере.")
            return None
        channel = getattr(ctx.author.voice, "channel", None)
        if not isinstance(channel, discord.VoiceChannel):
            await ctx.send("Сначала зайди в свою временную голосовую комнату.")
            return None
        room = self._rooms[ctx.guild.id].get(channel.id)
        if room is None:
            await ctx.send("Текущий канал не является временной комнатой TempVoice.")
            return None
        if room.get("owner_id") != ctx.author.id:
            await ctx.send("Управлять этой комнатой может только её текущий владелец.")
            return None
        return channel

    @staticmethod
    async def _require_bot_permissions(
        ctx: commands.Context,
        channel: discord.VoiceChannel,
        **required: bool,
    ) -> bool:
        me = channel.guild.me
        if me is None:
            await ctx.send("Не удалось определить участника-бота на сервере.")
            return False
        permissions = channel.permissions_for(me)
        labels = {
            "manage_channels": "Manage Channels (Управлять каналами)",
            "move_members": "Move Members (Перемещать участников)",
        }
        missing = [
            labels.get(name, name)
            for name, needed in required.items()
            if needed and not getattr(permissions, name, False)
        ]
        if missing:
            await ctx.send("Боту не хватает прав: " + ", ".join(missing) + ".")
            return False
        return True

    @staticmethod
    async def _send_api_error(ctx: commands.Context, action: str, exc: Exception) -> None:
        if isinstance(exc, discord.Forbidden):
            await ctx.send(f"Discord запретил {action}. Проверь права и позицию роли бота.")
        else:
            await ctx.send(f"Discord API не смог {action}. Попробуй ещё раз позже.")

    @commands.group(invoke_without_command=True)
    @commands.guild_only()
    async def vc(self, ctx: commands.Context) -> None:
        """Управление своей временной голосовой комнатой."""
        await ctx.send_help()

    @vc.command(name="rename")
    async def vc_rename(self, ctx: commands.Context, *, name: str) -> None:
        """Переименовать свою комнату."""
        channel = await self._owned_room_or_reply(ctx)
        if channel is None:
            return
        name = name.strip()
        if not 1 <= len(name) <= 100:
            await ctx.send("Название должно содержать от 1 до 100 символов.")
            return
        if not await self._require_bot_permissions(ctx, channel, manage_channels=True):
            return
        try:
            await channel.edit(
                name=name, reason=f"TempVoice rename by {ctx.author} ({ctx.author.id})"
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            await self._send_api_error(ctx, "переименовать комнату", exc)
            return
        await ctx.send(f"Комната переименована в **{discord.utils.escape_markdown(name)}**.")

    @vc.command(name="limit")
    async def vc_limit(self, ctx: commands.Context, limit: int) -> None:
        """Установить лимит 0–99; 0 отключает ограничение."""
        channel = await self._owned_room_or_reply(ctx)
        if channel is None:
            return
        if not 0 <= limit <= 99:
            await ctx.send("Лимит должен быть целым числом от 0 до 99.")
            return
        if not await self._require_bot_permissions(ctx, channel, manage_channels=True):
            return
        try:
            await channel.edit(
                user_limit=limit,
                reason=f"TempVoice limit by {ctx.author} ({ctx.author.id})",
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            await self._send_api_error(ctx, "изменить лимит комнаты", exc)
            return
        await ctx.send("Лимит отключён." if limit == 0 else f"Лимит установлен: **{limit}**.")

    async def _set_everyone_permission(
        self,
        ctx: commands.Context,
        channel: discord.VoiceChannel,
        permission: str,
        value: Optional[bool],
        action: str,
    ) -> bool:
        if not await self._require_bot_permissions(ctx, channel, manage_channels=True):
            return False
        everyone = channel.guild.default_role
        overwrite = channel.overwrites_for(everyone)
        setattr(overwrite, permission, value)
        try:
            await channel.set_permissions(
                everyone,
                overwrite=None if overwrite.is_empty() else overwrite,
                reason=f"TempVoice {action} by {ctx.author} ({ctx.author.id})",
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            await self._send_api_error(ctx, action, exc)
            return False
        return True

    @staticmethod
    def _category_permission(channel: discord.VoiceChannel, permission: str) -> Optional[bool]:
        category = channel.category
        if category is None:
            return None
        overwrite = category.overwrites_for(channel.guild.default_role)
        return getattr(overwrite, permission)

    @vc.command(name="lock")
    async def vc_lock(self, ctx: commands.Context) -> None:
        """Запретить @everyone подключаться."""
        channel = await self._owned_room_or_reply(ctx)
        if channel is None:
            return
        if await self._set_everyone_permission(ctx, channel, "connect", False, "закрыть комнату"):
            await ctx.send("Комната закрыта для @everyone.")

    @vc.command(name="unlock")
    async def vc_unlock(self, ctx: commands.Context) -> None:
        """Вернуть право Connect из базовых прав категории."""
        channel = await self._owned_room_or_reply(ctx)
        if channel is None:
            return
        base = self._category_permission(channel, "connect")
        if await self._set_everyone_permission(ctx, channel, "connect", base, "открыть комнату"):
            await ctx.send("Право подключения @everyone восстановлено по настройкам категории.")

    @vc.command(name="hide")
    async def vc_hide(self, ctx: commands.Context) -> None:
        """Скрыть комнату от @everyone."""
        channel = await self._owned_room_or_reply(ctx)
        if channel is None:
            return
        if await self._set_everyone_permission(
            ctx, channel, "view_channel", False, "скрыть комнату"
        ):
            await ctx.send("Комната скрыта от @everyone.")

    @vc.command(name="show")
    async def vc_show(self, ctx: commands.Context) -> None:
        """Вернуть View Channel из базовых прав категории."""
        channel = await self._owned_room_or_reply(ctx)
        if channel is None:
            return
        base = self._category_permission(channel, "view_channel")
        if await self._set_everyone_permission(
            ctx, channel, "view_channel", base, "показать комнату"
        ):
            await ctx.send("Видимость @everyone восстановлена по настройкам категории.")

    @vc.command(name="permit")
    async def vc_permit(self, ctx: commands.Context, member: discord.Member) -> None:
        """Явно разрешить участнику видеть комнату и подключаться."""
        channel = await self._owned_room_or_reply(ctx)
        if channel is None:
            return
        if not await self._require_bot_permissions(ctx, channel, manage_channels=True):
            return
        overwrite = channel.overwrites_for(member)
        overwrite.view_channel = True
        overwrite.connect = True
        try:
            await channel.set_permissions(
                member,
                overwrite=overwrite,
                reason=f"TempVoice permit by {ctx.author} ({ctx.author.id})",
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            await self._send_api_error(ctx, "разрешить участнику вход", exc)
            return
        await ctx.send(f"{member.mention} теперь может видеть комнату и подключаться.")

    @vc.command(name="reject")
    async def vc_reject(self, ctx: commands.Context, member: discord.Member) -> None:
        """Запретить участнику подключаться и отключить его, если он внутри."""
        channel = await self._owned_room_or_reply(ctx)
        if channel is None:
            return
        if member.id == self.bot.user.id:
            await ctx.send("Нельзя блокировать самого бота.")
            return
        if member.id == ctx.author.id:
            await ctx.send("Нельзя заблокировать самого себя.")
            return
        is_inside = getattr(member.voice, "channel", None) == channel
        if not await self._require_bot_permissions(
            ctx,
            channel,
            manage_channels=True,
            move_members=is_inside,
        ):
            return

        overwrite = channel.overwrites_for(member)
        overwrite.connect = False
        try:
            await channel.set_permissions(
                member,
                overwrite=overwrite,
                reason=f"TempVoice reject by {ctx.author} ({ctx.author.id})",
            )
            if is_inside:
                await member.move_to(
                    None, reason=f"TempVoice reject by {ctx.author} ({ctx.author.id})"
                )
        except (discord.Forbidden, discord.HTTPException) as exc:
            await self._send_api_error(ctx, "запретить участнику вход", exc)
            return
        await ctx.send(f"{member.mention} больше не может подключаться к комнате.")

    @vc.command(name="kick")
    async def vc_kick(self, ctx: commands.Context, member: discord.Member) -> None:
        """Отключить участника без постоянного запрета."""
        channel = await self._owned_room_or_reply(ctx)
        if channel is None:
            return
        if member.id == self.bot.user.id:
            await ctx.send("Нельзя отключить самого бота.")
            return
        if member.id == ctx.author.id:
            await ctx.send("Нельзя отключить самого себя этой командой.")
            return
        if getattr(member.voice, "channel", None) != channel:
            await ctx.send("Этот участник сейчас не находится в твоей комнате.")
            return
        if not await self._require_bot_permissions(ctx, channel, move_members=True):
            return
        try:
            await member.move_to(None, reason=f"TempVoice kick by {ctx.author} ({ctx.author.id})")
        except (discord.Forbidden, discord.HTTPException) as exc:
            await self._send_api_error(ctx, "отключить участника", exc)
            return
        await ctx.send(f"{member.mention} отключён от комнаты без запрета на повторный вход.")

    @commands.group(invoke_without_command=True)
    @commands.guild_only()
    @commands.admin_or_permissions(administrator=True)
    async def tempvoiceset(self, ctx: commands.Context) -> None:
        """Настройка генераторов временных голосовых комнат."""
        await ctx.send_help()

    @tempvoiceset.command(name="list")
    async def tempvoiceset_list(self, ctx: commands.Context) -> None:
        """Показать настроенные генераторы."""
        generators = self._generators[ctx.guild.id]
        if not generators:
            await ctx.send("На этом сервере нет настроенных генераторов.")
            return
        lines = []
        for creator_id, settings in sorted(generators.items()):
            creator = ctx.guild.get_channel(creator_id)
            category = ctx.guild.get_channel(int(settings["category_id"]))
            creator_name = creator.name if creator is not None else "удалён/не найден"
            category_name = category.name if category is not None else "удалена/не найдена"
            lines.append(
                f"Creator: {creator_name} ({creator_id})\n"
                f"Category: {category_name} ({settings['category_id']})\n"
                f"Template: {settings['template']}"
            )
        for page in pagify("\n\n".join(lines), page_length=1900):
            await ctx.send(box(page))

    @tempvoiceset.command(name="add")
    async def tempvoiceset_add(
        self,
        ctx: commands.Context,
        creator_channel: discord.VoiceChannel,
        category: discord.CategoryChannel,
        *,
        template: str,
    ) -> None:
        """Добавить генератор: creator, category и шаблон с {nick}."""
        error = self._validate_template(template)
        if error is not None:
            await ctx.send(error)
            return
        async with self._guild_locks[ctx.guild.id]:
            if creator_channel.id in self._generators[ctx.guild.id]:
                await ctx.send("Этот голосовой канал уже настроен как генератор.")
                return
            self._generators[ctx.guild.id][creator_channel.id] = {
                "category_id": category.id,
                "template": template.strip(),
            }
            await self._save_generators_locked(ctx.guild.id)
        await ctx.send(
            f"Генератор **{creator_channel.name}** добавлен; категория: **{category.name}**."
        )

    @tempvoiceset.command(name="remove")
    async def tempvoiceset_remove(
        self, ctx: commands.Context, creator_channel: discord.VoiceChannel
    ) -> None:
        """Удалить генератор. Уже созданные комнаты останутся под управлением cog."""
        async with self._guild_locks[ctx.guild.id]:
            removed = self._generators[ctx.guild.id].pop(creator_channel.id, None)
            if removed is None:
                await ctx.send("Этот канал не настроен как генератор.")
                return
            await self._save_generators_locked(ctx.guild.id)
        await ctx.send(f"Генератор **{creator_channel.name}** удалён из настроек.")

    @tempvoiceset.command(name="template")
    async def tempvoiceset_template(
        self,
        ctx: commands.Context,
        creator_channel: discord.VoiceChannel,
        *,
        template: str,
    ) -> None:
        """Изменить шаблон генератора; шаблон должен содержать {nick}."""
        error = self._validate_template(template)
        if error is not None:
            await ctx.send(error)
            return
        async with self._guild_locks[ctx.guild.id]:
            settings = self._generators[ctx.guild.id].get(creator_channel.id)
            if settings is None:
                await ctx.send("Этот канал не настроен как генератор.")
                return
            settings["template"] = template.strip()
            await self._save_generators_locked(ctx.guild.id)
        await ctx.send(f"Новый шаблон: `{discord.utils.escape_markdown(template.strip())}`")
