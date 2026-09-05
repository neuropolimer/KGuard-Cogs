import asyncio
import logging
from collections import defaultdict
from typing import Any, Dict, Iterable, Optional

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red

log = logging.getLogger("red.neuropolimer.muteguard")

# Intentionally excludes view_channel/read_messages and read_message_history.
# The cog must never grant access to a channel/category and should leave
# message history exactly as it was before the mute.
COMMUNICATION_DENIES = (
    "send_messages",
    "send_tts_messages",
    "embed_links",
    "attach_files",
    "add_reactions",
    "mention_everyone",
    "use_external_emojis",
    "use_external_stickers",
    "send_messages_in_threads",
    "create_public_threads",
    "create_private_threads",
    "manage_threads",
    "use_application_commands",
    "send_voice_messages",
    "send_polls",
    "connect",
    "speak",
    "stream",
    "use_voice_activation",
    "priority_speaker",
    "request_to_speak",
    "use_soundboard",
    "use_external_sounds",
    "use_embedded_activities",
    # Prevent common channel-level escape hatches while muted.
    "manage_channels",
    "manage_roles",
    "manage_webhooks",
    "manage_messages",
    "move_members",
    "mute_members",
    "deafen_members",
)

# Newer discord.py releases may expose additional communication-related flags.
OPTIONAL_DENIES = (
    "use_external_apps",
    "set_voice_channel_status",
    "send_scheduled_messages",
)

# Fields denied by older MuteGuard versions but no longer part of the mute.
# They are restored from the saved snapshot during migration.
RETIRED_DENIES = (
    "read_message_history",
)


class MuteGuard(commands.Cog):
    """Hardens a role-based Red mute with per-member channel overwrites."""

    __author__ = "neuropolimer"
    __version__ = "1.0.1"

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(
            self,
            identifier=602451496302871118,
            force_registration=True,
        )
        self.config.register_guild(mute_role_id=0)
        self.config.register_member(overrides={})

        self._mute_roles: Dict[int, int] = {}
        self._member_locks: Dict[tuple[int, int], asyncio.Lock] = defaultdict(asyncio.Lock)
        self._ready_task: Optional[asyncio.Task] = None

        valid_flags = set(discord.Permissions.VALID_FLAGS)
        self._deny_fields = tuple(
            name
            for name in (*COMMUNICATION_DENIES, *OPTIONAL_DENIES)
            if name in valid_flags
        )
        self._retired_fields = tuple(
            name for name in RETIRED_DENIES if name in valid_flags
        )
        self._restorable_fields = set((*self._deny_fields, *self._retired_fields))

    async def cog_load(self) -> None:
        all_guilds = await self.config.all_guilds()
        self._mute_roles = {
            int(guild_id): int(data.get("mute_role_id", 0) or 0)
            for guild_id, data in all_guilds.items()
        }
        self._ready_task = asyncio.create_task(self._initialize_after_ready())

    def cog_unload(self) -> None:
        if self._ready_task is not None:
            self._ready_task.cancel()

    async def _initialize_after_ready(self) -> None:
        try:
            waiter = getattr(self.bot, "wait_until_red_ready", self.bot.wait_until_ready)
            await waiter()
            for guild in self.bot.guilds:
                await self._reconcile_guild(guild)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("MuteGuard failed during startup reconciliation")

    def _mute_role_id(self, guild: discord.Guild) -> int:
        return self._mute_roles.get(guild.id, 0)

    def _has_mute_role(self, member: discord.Member) -> bool:
        role_id = self._mute_role_id(member.guild)
        return bool(role_id and any(role.id == role_id for role in member.roles))

    @staticmethod
    def _is_permission_root(channel: discord.abc.GuildChannel) -> bool:
        # Applying to a category preserves sync for its children.
        if isinstance(channel, discord.CategoryChannel):
            return True
        category = getattr(channel, "category", None)
        if category is None:
            return True
        return not bool(getattr(channel, "permissions_synced", False))

    def _candidate_channels(
        self,
        guild: discord.Guild,
        tracked: Dict[str, Dict[str, Any]],
    ) -> Iterable[discord.abc.GuildChannel]:
        tracked_ids = {int(cid) for cid in tracked if str(cid).isdigit()}
        seen = set()

        for channel in guild.channels:
            if self._is_permission_root(channel) or channel.id in tracked_ids:
                if channel.id not in seen:
                    seen.add(channel.id)
                    yield channel

    async def _restore_retired_fields(
        self,
        member: discord.Member,
        channel: discord.abc.GuildChannel,
        snapshots: Dict[str, Dict[str, Any]],
    ) -> bool:
        """Restore fields that older MuteGuard versions used to deny."""
        channel_key = str(channel.id)
        fields = dict(snapshots.get(channel_key, {}))
        retired = {
            field: fields[field]
            for field in self._retired_fields
            if field in fields
        }
        if not retired:
            return False

        overwrite = channel.overwrites_for(member)
        changed = False

        for field, original in retired.items():
            # Restore only if our old deny is still present. If an admin or
            # another cog changed it meanwhile, preserve that newer value.
            if getattr(overwrite, field) is False:
                setattr(overwrite, field, original)
                changed = True
            fields.pop(field, None)

        if changed:
            try:
                await channel.set_permissions(
                    member,
                    overwrite=None if overwrite.is_empty() else overwrite,
                    reason=(
                        f"MuteGuard: migrate retired mute permissions for "
                        f"{member} ({member.id})"
                    ),
                )
            except discord.Forbidden:
                log.warning(
                    "MuteGuard cannot migrate overwrite in channel %s for member %s",
                    channel.id,
                    member.id,
                )
                return False
            except discord.HTTPException:
                log.exception(
                    "MuteGuard migration failed in channel %s for member %s",
                    channel.id,
                    member.id,
                )
                return False

        if fields:
            snapshots[channel_key] = fields
        else:
            snapshots.pop(channel_key, None)
        return True

    async def _set_channel_overlay(
        self,
        member: discord.Member,
        channel: discord.abc.GuildChannel,
        snapshots: Dict[str, Dict[str, Any]],
    ) -> bool:
        channel_key = str(channel.id)
        tracked = channel_key in snapshots

        # Do not create a member overwrite in areas the member cannot already see.
        # Existing tracked entries are still maintained even if the member later loses access.
        if not tracked and not channel.permissions_for(member).view_channel:
            return False

        overwrite = channel.overwrites_for(member)
        previous_values = dict(snapshots.get(channel_key, {}))
        next_values = dict(previous_values)
        changed = False

        for field in self._deny_fields:
            current = getattr(overwrite, field)

            if current is False:
                continue

            # If the field was changed by an admin/another cog while the mute is active,
            # remember that new underlying value and keep our False overlay on top.
            next_values[field] = current
            setattr(overwrite, field, False)
            changed = True

        if not changed:
            return False

        try:
            await channel.set_permissions(
                member,
                overwrite=None if overwrite.is_empty() else overwrite,
                reason=f"MuteGuard: enforce mute overlay for {member} ({member.id})",
            )
        except discord.Forbidden:
            log.warning(
                "MuteGuard cannot edit overwrite in channel %s for member %s",
                channel.id,
                member.id,
            )
            return False
        except discord.HTTPException:
            log.exception(
                "MuteGuard Discord API failure in channel %s for member %s",
                channel.id,
                member.id,
            )
            return False

        snapshots[channel_key] = next_values
        return True

    async def _apply_member(self, member: discord.Member) -> None:
        lock = self._member_locks[(member.guild.id, member.id)]
        async with lock:
            snapshots = await self.config.member(member).overrides()
            dirty = False

            # Migrate old snapshots first so users muted before v1.0.1 regain
            # their previous Read Message History setting immediately.
            for channel in self._candidate_channels(member.guild, snapshots):
                if await self._restore_retired_fields(member, channel, snapshots):
                    dirty = True

            for channel in self._candidate_channels(member.guild, snapshots):
                if await self._set_channel_overlay(member, channel, snapshots):
                    dirty = True

            if dirty:
                await self.config.member(member).overrides.set(snapshots)

            await self._disconnect_if_needed(member)

    async def _disconnect_if_needed(self, member: discord.Member) -> None:
        voice = member.voice
        if voice is None or voice.channel is None:
            return

        me = member.guild.me
        if me is None:
            return

        if not voice.channel.permissions_for(me).move_members:
            log.warning(
                "MuteGuard cannot disconnect member %s from channel %s: missing Move Members",
                member.id,
                voice.channel.id,
            )
            return

        try:
            await member.move_to(
                None,
                reason=f"MuteGuard: disconnect muted member {member} ({member.id})",
            )
        except discord.Forbidden:
            log.warning("MuteGuard was denied while disconnecting member %s", member.id)
        except discord.HTTPException:
            log.exception("MuteGuard failed to disconnect member %s", member.id)

    async def _restore_member(self, member: discord.Member) -> None:
        lock = self._member_locks[(member.guild.id, member.id)]
        async with lock:
            snapshots = await self.config.member(member).overrides()
            if not snapshots:
                return

            remaining: Dict[str, Dict[str, Any]] = {}

            for channel_key, fields in snapshots.items():
                try:
                    channel_id = int(channel_key)
                except (TypeError, ValueError):
                    continue

                channel = member.guild.get_channel(channel_id)
                if channel is None:
                    continue

                overwrite = channel.overwrites_for(member)
                changed = False

                for field, original in fields.items():
                    if field not in self._restorable_fields:
                        continue

                    # Only undo our overlay. If something else changed the field away
                    # from False, keep that newer value.
                    if getattr(overwrite, field) is False:
                        setattr(overwrite, field, original)
                        changed = True

                if not changed:
                    continue

                try:
                    await channel.set_permissions(
                        member,
                        overwrite=None if overwrite.is_empty() else overwrite,
                        reason=f"MuteGuard: restore permissions for {member} ({member.id})",
                    )
                except (discord.Forbidden, discord.HTTPException):
                    log.exception(
                        "MuteGuard failed to restore channel %s for member %s",
                        channel.id,
                        member.id,
                    )
                    remaining[channel_key] = fields

            await self.config.member(member).overrides.set(remaining)

    async def _drop_channel_snapshot(
        self, guild: discord.Guild, channel_id: int
    ) -> None:
        """Forget direct overlay state after an admin explicitly re-syncs a channel."""
        all_members = await self.config.all_members(guild)
        key = str(channel_id)

        for member_id, data in all_members.items():
            overrides = dict(data.get("overrides", {}))
            if key not in overrides:
                continue

            member = guild.get_member(int(member_id))
            if member is None:
                continue

            overrides.pop(key, None)
            await self.config.member(member).overrides.set(overrides)

    async def _reconcile_guild(self, guild: discord.Guild) -> None:
        role_id = self._mute_role_id(guild)
        role = guild.get_role(role_id) if role_id else None

        # First restore stale overlays from members who are not currently muted.
        all_members = await self.config.all_members(guild)
        for member_id, data in all_members.items():
            if not data.get("overrides"):
                continue
            member = guild.get_member(int(member_id))
            if member is None:
                continue
            if role is None or role not in member.roles:
                await self._restore_member(member)

        if role is None:
            return

        for member in role.members:
            if not member.bot:
                await self._apply_member(member)

    async def _reconcile_muted_members(self, guild: discord.Guild) -> None:
        role_id = self._mute_role_id(guild)
        role = guild.get_role(role_id) if role_id else None
        if role is None:
            return

        for member in role.members:
            if not member.bot:
                await self._apply_member(member)

    @commands.Cog.listener()
    async def on_member_update(
        self,
        before: discord.Member,
        after: discord.Member,
    ) -> None:
        if before.guild.id != after.guild.id:
            return

        role_id = self._mute_role_id(after.guild)
        if not role_id:
            return

        before_ids = {role.id for role in before.roles}
        after_ids = {role.id for role in after.roles}
        had_mute = role_id in before_ids
        has_mute = role_id in after_ids

        if not had_mute and has_mute:
            await self._apply_member(after)
        elif had_mute and not has_mute:
            await self._restore_member(after)
        elif has_mute and before_ids != after_ids:
            # A new access role may make additional categories visible.
            await self._apply_member(after)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if self._has_mute_role(member):
            await self._apply_member(member)
        else:
            # Clean up a stale overlay if the user left while muted and later rejoined.
            await self._restore_member(member)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel) -> None:
        await self._reconcile_muted_members(channel.guild)

    @commands.Cog.listener()
    async def on_guild_channel_update(
        self,
        before: discord.abc.GuildChannel,
        after: discord.abc.GuildChannel,
    ) -> None:
        if (
            not isinstance(after, discord.CategoryChannel)
            and not getattr(before, "permissions_synced", False)
            and getattr(after, "permissions_synced", False)
        ):
            # "Sync permissions" is an explicit admin action. Do not resurrect
            # the old direct channel overwrite after the sync.
            await self._drop_channel_snapshot(after.guild, after.id)

        await self._reconcile_muted_members(after.guild)

    @commands.Cog.listener()
    async def on_guild_role_update(
        self,
        before: discord.Role,
        after: discord.Role,
    ) -> None:
        # Base role permission changes can expose previously hidden areas.
        await self._reconcile_muted_members(after.guild)

    @commands.group(name="muteguardset", invoke_without_command=True)
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def muteguardset(self, ctx: commands.Context) -> None:
        """Настройки MuteGuard."""
        await ctx.send_help()

    @muteguardset.command(name="role")
    async def muteguardset_role(
        self,
        ctx: commands.Context,
        role: discord.Role,
    ) -> None:
        """Указать роль-заглушку, которую выдаёт штатный Mutes."""
        guild = ctx.guild
        if guild is None:
            return

        if role.is_default():
            await ctx.send("Нельзя использовать `@everyone` как роль заглушки.")
            return
        if role.managed:
            await ctx.send("Нельзя использовать интеграционную/управляемую Discord роль.")
            return

        await self._reconcile_guild(guild)

        await self.config.guild(guild).mute_role_id.set(role.id)
        self._mute_roles[guild.id] = role.id

        await self._reconcile_guild(guild)

        warnings = []
        me = guild.me
        if me is not None:
            if not me.guild_permissions.manage_roles and not me.guild_permissions.administrator:
                warnings.append("у бота нет права `Управлять ролями`")
            if role >= me.top_role and not me.guild_permissions.administrator:
                warnings.append("роль заглушки находится не ниже роли бота")
            if not me.guild_permissions.move_members and not me.guild_permissions.administrator:
                warnings.append("у бота нет права `Перемещать участников` для отключения из голосового")

        suffix = ""
        if warnings:
            suffix = "\n\nПредупреждение: " + "; ".join(warnings) + "."

        await ctx.send(
            f"MuteGuard привязан к роли {role.mention}. "
            "Он никогда не выставляет `Просмотр канала = разрешить`; "
            "скрытые категории от этого не открываются."
            + suffix
        )

    @muteguardset.command(name="status")
    async def muteguardset_status(self, ctx: commands.Context) -> None:
        """Показать текущую роль и состояние MuteGuard."""
        guild = ctx.guild
        if guild is None:
            return

        role_id = self._mute_role_id(guild)
        role = guild.get_role(role_id) if role_id else None
        muted_count = len([m for m in role.members if not m.bot]) if role else 0

        if role is None:
            await ctx.send("MuteGuard не настроен: роль заглушки не указана.")
            return

        admin_bypass = [
            m.mention
            for m in role.members
            if not m.bot and (m.id == guild.owner_id or m.guild_permissions.administrator)
        ]

        text = (
            f"Роль: {role.mention}\n"
            f"Сейчас с заглушкой: {muted_count}\n"
            f"Запрещаемых полей: {len(self._deny_fields)}\n"
            "`Просмотр канала` и `Историю сообщений` cog не изменяет."
        )
        if admin_bypass:
            text += (
                "\n\n⚠️ Владелец сервера и участники с `Администратор` "
                "обходят канальные запреты Discord: "
                + ", ".join(admin_bypass[:10])
            )

        await ctx.send(text)

    @muteguardset.command(name="sync")
    async def muteguardset_sync(self, ctx: commands.Context) -> None:
        """Повторно сверить активные заглушки и восстановить лишние overlays."""
        guild = ctx.guild
        if guild is None:
            return

        await self._reconcile_guild(guild)
        await ctx.send("MuteGuard пересинхронизирован.")

    @muteguardset.command(name="disable")
    async def muteguardset_disable(self, ctx: commands.Context) -> None:
        """Снять overlays MuteGuard и отключить привязку роли."""
        guild = ctx.guild
        if guild is None:
            return

        all_members = await self.config.all_members(guild)
        failures = 0

        for member_id, data in all_members.items():
            if not data.get("overrides"):
                continue
            member = guild.get_member(int(member_id))
            if member is None:
                continue
            await self._restore_member(member)
            if await self.config.member(member).overrides():
                failures += 1

        if failures:
            await ctx.send(
                f"Не удалось полностью восстановить права у {failures} участника(ов). "
                "Привязка роли оставлена включённой; исправь права бота и повтори команду."
            )
            return

        await self.config.guild(guild).mute_role_id.set(0)
        self._mute_roles[guild.id] = 0
        await ctx.send("MuteGuard отключён, сохранённые overlays восстановлены.")
