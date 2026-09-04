from __future__ import annotations

from copy import copy
from typing import Optional

import discord

from redbot.core import app_commands, commands, modlog
from redbot.core.bot import Red


DURATION_PRESETS = (
    ("1 second", "1s"),
    ("10 seconds", "10s"),
    ("30 seconds", "30s"),
    ("1 minute", "1m"),
    ("5 minutes", "5m"),
    ("10 minutes", "10m"),
    ("30 minutes", "30m"),
    ("1 hour", "1h"),
    ("3 hours", "3h"),
    ("6 hours", "6h"),
    ("12 hours", "12h"),
    ("1 day", "1d"),
    ("3 days", "3d"),
    ("7 days", "7d"),
    ("14 days", "14d"),
    ("28 days", "28d"),
)


async def duration_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    needle = current.casefold().strip()
    choices: list[app_commands.Choice[str]] = []

    if current.strip():
        choices.append(
            app_commands.Choice(
                name=f"Use custom: {current.strip()}"[:100],
                value=current.strip()[:100],
            )
        )

    for label, value in DURATION_PRESETS:
        if needle and needle not in label.casefold() and needle not in value.casefold():
            continue
        if any(choice.value == value for choice in choices):
            continue
        choices.append(app_commands.Choice(name=f"{label} — {value}", value=value))
        if len(choices) >= 25:
            break

    return choices[:25]


class ModSlash(commands.Cog):
    """Slash interface for the moderation commands already configured in Red."""

    __version__ = "1.1.0"

    def __init__(self, bot: Red):
        self.bot = bot

    @staticmethod
    def _line(command: str, *parts: object) -> str:
        result = [command]
        for part in parts:
            if part is None:
                continue
            value = str(part).strip()
            if value:
                result.append(value)
        return " ".join(result)

    async def _mod_defaults(self, guild: discord.Guild) -> tuple[int, int]:
        """Return Red Mod's default delete-days and tempban duration in seconds."""
        mod_cog = self.bot.get_cog("Mod")
        config = getattr(mod_cog, "config", None)
        if config is None:
            return 0, 86400
        data = await config.guild(guild).all()
        return int(data.get("default_days", 0)), int(data.get("default_tempban_duration", 86400))

    async def _validated_user_id(
        self, interaction: discord.Interaction, raw: str
    ) -> Optional[str]:
        value = raw.strip()
        if not value.isdigit() or not 15 <= len(value) <= 22:
            await self._respond(interaction, "Укажи корректный Discord user ID.")
            return None
        return value

    @staticmethod
    async def _respond(
        interaction: discord.Interaction, message: str, *, ephemeral: bool = True
    ) -> None:
        # Wrapper diagnostics should never spill into the moderation channel.
        # Once the interaction has been acknowledged, native Red output is enough.
        if interaction.response.is_done():
            return
        await interaction.response.send_message(message, ephemeral=ephemeral)

    async def _run_legacy(self, interaction: discord.Interaction, command_line: str) -> None:
        if interaction.guild is None or interaction.channel is None:
            await self._respond(interaction, "Эта команда работает только на сервере.")
            return

        app_ctx = await commands.Context.from_interaction(interaction)
        prefixes = await self.bot.get_valid_prefixes(interaction.guild)
        if not prefixes:
            await self._respond(interaction, "Red не вернул ни одного действующего префикса.")
            return

        fake_message = copy(app_ctx.message)
        fake_message.content = f"{prefixes[0]}{command_line}"

        legacy_ctx = await self.bot.get_context(fake_message)

        # Do not attach the slash interaction to the synthetic prefix context.
        # Native Red replies should be ordinary channel messages, not webhook follow-ups.
        legacy_ctx.interaction = None

        if legacy_ctx.command is None:
            original = command_line.split(maxsplit=1)[0]
            await self._respond(
                interaction,
                f"Исходная команда `{original}` сейчас недоступна. Проверь, что нужный cog загружен.",
            )
            return

        try:
            can_run = await legacy_ctx.command.can_run(
                legacy_ctx,
                check_all_parents=True,
                change_permission_state=False,
            )
        except commands.CommandError:
            can_run = False

        if not can_run:
            await self._respond(
                interaction,
                "У тебя нет доступа к исходной Red-команде в этом канале.",
            )
            return

        # Acknowledge only after all wrapper-side checks passed. This keeps
        # permission/configuration errors private while still beating Discord's timeout.
        if not interaction.response.is_done():
            await interaction.response.send_message("Выполняю…", ephemeral=True)

        # bot.invoke preserves the original Red command parser, checks, hooks,
        # cooldowns, Permissions rules, ModLog behavior and error handling.
        await self.bot.invoke(legacy_ctx)

    # ---------- Warnings ----------

    async def _do_warn(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str,
        points: int = 1,
    ) -> None:
        await self._run_legacy(
            interaction, self._line("warn", member.id, points, reason)
        )

    @app_commands.command(name="warn", description="Warn a member using Red Warnings.", extras={"red_force_enable": True})
    @app_commands.describe(member="Member to warn", reason="Reason", points="Warning points")
    @app_commands.guild_only()
    async def warn(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str,
        points: app_commands.Range[int, 1, None] = 1,
    ) -> None:
        await self._do_warn(interaction, member, reason, points)

    @app_commands.command(name="варн", description="Выдать предупреждение через Red Warnings.", extras={"red_force_enable": True})
    @app_commands.rename(member="участник", reason="причина", points="баллы")
    @app_commands.describe(member="Кому выдать предупреждение", reason="Причина", points="Баллы")
    @app_commands.guild_only()
    async def warn_ru(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str,
        points: app_commands.Range[int, 1, None] = 1,
    ) -> None:
        await self._do_warn(interaction, member, reason, points)

    @app_commands.command(name="пред", description="Псевдоним /варн.", extras={"red_force_enable": True})
    @app_commands.rename(member="участник", reason="причина", points="баллы")
    @app_commands.guild_only()
    async def warn_pred(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str,
        points: app_commands.Range[int, 1, None] = 1,
    ) -> None:
        await self._do_warn(interaction, member, reason, points)

    async def _do_warnings(
        self, interaction: discord.Interaction, member: discord.Member
    ) -> None:
        await self._run_legacy(interaction, self._line("warnings", member.id))

    @app_commands.command(name="warnings", description="Show a member's Red warnings.", extras={"red_force_enable": True})
    @app_commands.describe(member="Member whose warnings to show")
    @app_commands.guild_only()
    async def warnings(
        self, interaction: discord.Interaction, member: discord.Member
    ) -> None:
        await self._do_warnings(interaction, member)

    @app_commands.command(name="warns", description="Alias for /warnings.", extras={"red_force_enable": True})
    @app_commands.describe(member="Member whose warnings to show")
    @app_commands.guild_only()
    async def warns(
        self, interaction: discord.Interaction, member: discord.Member
    ) -> None:
        await self._do_warnings(interaction, member)

    @app_commands.command(name="варны", description="Показать предупреждения участника.", extras={"red_force_enable": True})
    @app_commands.rename(member="участник")
    @app_commands.guild_only()
    async def warnings_ru(
        self, interaction: discord.Interaction, member: discord.Member
    ) -> None:
        await self._do_warnings(interaction, member)

    @app_commands.command(name="преды", description="Псевдоним /варны.", extras={"red_force_enable": True})
    @app_commands.rename(member="участник")
    @app_commands.guild_only()
    async def warnings_pred(
        self, interaction: discord.Interaction, member: discord.Member
    ) -> None:
        await self._do_warnings(interaction, member)

    @app_commands.command(name="warningsid", description="Show Red warnings for a user by Discord ID.", extras={"red_force_enable": True})
    @app_commands.describe(user_id="Discord user ID")
    @app_commands.guild_only()
    async def warningsid(
        self, interaction: discord.Interaction, user_id: str
    ) -> None:
        user_id = await self._validated_user_id(interaction, user_id)
        if user_id is None:
            return
        await self._run_legacy(interaction, self._line("warnings", user_id))

    @app_commands.command(name="unwarn", description="Remove a Red warning from a member.", extras={"red_force_enable": True})
    @app_commands.describe(member="Member", warn_id="Warning ID", reason="Reason")
    @app_commands.guild_only()
    async def unwarn(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        warn_id: int,
        reason: Optional[str] = None,
    ) -> None:
        await self._run_legacy(
            interaction, self._line("unwarn", member.id, warn_id, reason)
        )

    @app_commands.command(name="unwarnid", description="Remove a Red warning by user ID and warning ID.", extras={"red_force_enable": True})
    @app_commands.describe(user_id="Discord user ID", warn_id="Warning ID", reason="Reason")
    @app_commands.guild_only()
    async def unwarnid(
        self,
        interaction: discord.Interaction,
        user_id: str,
        warn_id: str,
        reason: Optional[str] = None,
    ) -> None:
        user_id = await self._validated_user_id(interaction, user_id)
        if user_id is None:
            return
        await self._run_legacy(
            interaction, self._line("unwarn", user_id, warn_id, reason)
        )

    # ---------- Mutes ----------

    async def _do_timed_member_command(
        self,
        interaction: discord.Interaction,
        command: str,
        member: discord.Member,
        duration: Optional[str],
        reason: Optional[str],
    ) -> None:
        await self._run_legacy(
            interaction, self._line(command, member.id, duration, reason)
        )

    @app_commands.command(name="mute", description="Mute a member using the Red Mutes cog.", extras={"red_force_enable": True})
    @app_commands.describe(member="Member", duration="Any Red duration, e.g. 30s, 5m, 2h, 3d", reason="Reason")
    @app_commands.autocomplete(duration=duration_autocomplete)
    @app_commands.guild_only()
    async def mute(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        duration: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> None:
        await self._do_timed_member_command(interaction, "mute", member, duration, reason)

    @app_commands.command(name="мут", description="Выдать мут через Red Mutes.", extras={"red_force_enable": True})
    @app_commands.rename(member="участник", duration="срок", reason="причина")
    @app_commands.autocomplete(duration=duration_autocomplete)
    @app_commands.guild_only()
    async def mute_ru(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        duration: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> None:
        await self._do_timed_member_command(interaction, "mute", member, duration, reason)

    @app_commands.command(name="unmute", description="Unmute a member using Red Mutes.", extras={"red_force_enable": True})
    @app_commands.describe(member="Member", reason="Reason")
    @app_commands.guild_only()
    async def unmute(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: Optional[str] = None,
    ) -> None:
        await self._run_legacy(interaction, self._line("unmute", member.id, reason))

    @app_commands.command(name="размут", description="Снять мут через Red Mutes.", extras={"red_force_enable": True})
    @app_commands.rename(member="участник", reason="причина")
    @app_commands.guild_only()
    async def unmute_ru(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: Optional[str] = None,
    ) -> None:
        await self._run_legacy(interaction, self._line("unmute", member.id, reason))

    @app_commands.command(name="timeout", description="Timeout a member using Red Mutes.", extras={"red_force_enable": True})
    @app_commands.describe(member="Member", duration="Any Red duration", reason="Reason")
    @app_commands.autocomplete(duration=duration_autocomplete)
    @app_commands.guild_only()
    async def timeout(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        duration: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> None:
        await self._do_timed_member_command(interaction, "timeout", member, duration, reason)

    @app_commands.command(name="таймаут", description="Выдать timeout через Red Mutes.", extras={"red_force_enable": True})
    @app_commands.rename(member="участник", duration="срок", reason="причина")
    @app_commands.autocomplete(duration=duration_autocomplete)
    @app_commands.guild_only()
    async def timeout_ru(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        duration: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> None:
        await self._do_timed_member_command(interaction, "timeout", member, duration, reason)

    @app_commands.command(name="activemutes", description="Show active Red mutes.", extras={"red_force_enable": True})
    @app_commands.guild_only()
    async def activemutes(self, interaction: discord.Interaction) -> None:
        await self._run_legacy(interaction, "activemutes")

    @app_commands.command(name="mutechannel", description="Mute a member in the current channel.", extras={"red_force_enable": True})
    @app_commands.describe(member="Member", duration="Any Red duration", reason="Reason")
    @app_commands.autocomplete(duration=duration_autocomplete)
    @app_commands.guild_only()
    async def mutechannel(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        duration: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> None:
        await self._do_timed_member_command(interaction, "mutechannel", member, duration, reason)

    @app_commands.command(name="unmutechannel", description="Unmute a member in the current channel.", extras={"red_force_enable": True})
    @app_commands.describe(member="Member", reason="Reason")
    @app_commands.guild_only()
    async def unmutechannel(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: Optional[str] = None,
    ) -> None:
        await self._run_legacy(interaction, self._line("unmutechannel", member.id, reason))

    @app_commands.command(name="voicemute", description="Voice-mute a member using Red Mutes.", extras={"red_force_enable": True})
    @app_commands.describe(member="Member", duration="Any Red duration", reason="Reason")
    @app_commands.autocomplete(duration=duration_autocomplete)
    @app_commands.guild_only()
    async def voicemute(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        duration: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> None:
        await self._do_timed_member_command(interaction, "voicemute", member, duration, reason)

    @app_commands.command(name="voiceunmute", description="Remove a Red voice mute from a member.", extras={"red_force_enable": True})
    @app_commands.describe(member="Member", reason="Reason")
    @app_commands.guild_only()
    async def voiceunmute(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: Optional[str] = None,
    ) -> None:
        await self._run_legacy(interaction, self._line("voiceunmute", member.id, reason))

    # ---------- Mod ----------

    async def _do_ban(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        delete_days: Optional[int],
        reason: Optional[str],
    ) -> None:
        if interaction.guild is None:
            await self._respond(interaction, "Эта команда работает только на сервере.")
            return
        if delete_days is None:
            delete_days, _ = await self._mod_defaults(interaction.guild)
        await self._run_legacy(
            interaction, self._line("ban", user.id, delete_days, reason)
        )

    @app_commands.command(name="ban", description="Ban a user using the Red Mod cog.", extras={"red_force_enable": True})
    @app_commands.describe(user="User to ban", delete_days="Days of messages to delete (0-7)", reason="Reason")
    @app_commands.guild_only()
    async def ban(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        delete_days: Optional[app_commands.Range[int, 0, 7]] = None,
        reason: Optional[str] = None,
    ) -> None:
        await self._do_ban(interaction, user, delete_days, reason)

    @app_commands.command(name="бан", description="Забанить пользователя через Red Mod.", extras={"red_force_enable": True})
    @app_commands.rename(user="пользователь", delete_days="удалить_дни", reason="причина")
    @app_commands.guild_only()
    async def ban_ru(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        delete_days: Optional[app_commands.Range[int, 0, 7]] = None,
        reason: Optional[str] = None,
    ) -> None:
        await self._do_ban(interaction, user, delete_days, reason)

    @app_commands.command(name="banid", description="Ban a user by Discord ID, including users outside the server.", extras={"red_force_enable": True})
    @app_commands.describe(user_id="Discord user ID", delete_days="Days of messages to delete (0-7)", reason="Reason")
    @app_commands.guild_only()
    async def banid(
        self,
        interaction: discord.Interaction,
        user_id: str,
        delete_days: Optional[app_commands.Range[int, 0, 7]] = None,
        reason: Optional[str] = None,
    ) -> None:
        user_id = await self._validated_user_id(interaction, user_id)
        if user_id is None or interaction.guild is None:
            return
        if delete_days is None:
            delete_days, _ = await self._mod_defaults(interaction.guild)
        await self._run_legacy(
            interaction, self._line("ban", user_id, delete_days, reason)
        )

    @app_commands.command(name="kick", description="Kick a member using the Red Mod cog.", extras={"red_force_enable": True})
    @app_commands.describe(member="Member", reason="Reason")
    @app_commands.guild_only()
    async def kick(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: Optional[str] = None,
    ) -> None:
        await self._run_legacy(interaction, self._line("kick", member.id, reason))

    @app_commands.command(name="кик", description="Кикнуть участника через Red Mod.", extras={"red_force_enable": True})
    @app_commands.rename(member="участник", reason="причина")
    @app_commands.guild_only()
    async def kick_ru(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: Optional[str] = None,
    ) -> None:
        await self._run_legacy(interaction, self._line("kick", member.id, reason))

    @app_commands.command(name="massban", description="Mass-ban user IDs using the Red Mod cog.", extras={"red_force_enable": True})
    @app_commands.describe(user_ids="Space-separated Discord user IDs", delete_days="Days of messages to delete (0-7)", reason="Reason")
    @app_commands.guild_only()
    async def massban(
        self,
        interaction: discord.Interaction,
        user_ids: str,
        delete_days: Optional[app_commands.Range[int, 0, 7]] = None,
        reason: Optional[str] = None,
    ) -> None:
        if interaction.guild is None:
            await self._respond(interaction, "Эта команда работает только на сервере.")
            return
        if delete_days is None:
            delete_days, _ = await self._mod_defaults(interaction.guild)
        await self._run_legacy(
            interaction, self._line("massban", user_ids, delete_days, reason)
        )

    @app_commands.command(name="softban", description="Soft-ban a member using the Red Mod cog.", extras={"red_force_enable": True})
    @app_commands.describe(member="Member", reason="Reason")
    @app_commands.guild_only()
    async def softban(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: Optional[str] = None,
    ) -> None:
        await self._run_legacy(interaction, self._line("softban", member.id, reason))

    @app_commands.command(name="софтбан", description="Софтбан через Red Mod.", extras={"red_force_enable": True})
    @app_commands.rename(member="участник", reason="причина")
    @app_commands.guild_only()
    async def softban_ru(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: Optional[str] = None,
    ) -> None:
        await self._run_legacy(interaction, self._line("softban", member.id, reason))

    async def _do_tempban(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        duration: Optional[str],
        delete_days: Optional[int],
        reason: Optional[str],
    ) -> None:
        if interaction.guild is None:
            await self._respond(interaction, "Эта команда работает только на сервере.")
            return
        default_days, default_duration = await self._mod_defaults(interaction.guild)
        if duration is None:
            duration = f"{default_duration}s"
        if delete_days is None:
            delete_days = default_days
        await self._run_legacy(
            interaction,
            self._line("tempban", member.id, duration, delete_days, reason),
        )

    @app_commands.command(name="tempban", description="Temporarily ban a member using Red Mod.", extras={"red_force_enable": True})
    @app_commands.describe(member="Member", duration="Any Red duration", delete_days="Days of messages to delete (0-7)", reason="Reason")
    @app_commands.autocomplete(duration=duration_autocomplete)
    @app_commands.guild_only()
    async def tempban(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        duration: Optional[str] = None,
        delete_days: Optional[app_commands.Range[int, 0, 7]] = None,
        reason: Optional[str] = None,
    ) -> None:
        await self._do_tempban(interaction, member, duration, delete_days, reason)

    @app_commands.command(name="тбан", description="Временный бан через Red Mod.", extras={"red_force_enable": True})
    @app_commands.rename(member="участник", duration="срок", delete_days="удалить_дни", reason="причина")
    @app_commands.autocomplete(duration=duration_autocomplete)
    @app_commands.guild_only()
    async def tempban_ru(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        duration: Optional[str] = None,
        delete_days: Optional[app_commands.Range[int, 0, 7]] = None,
        reason: Optional[str] = None,
    ) -> None:
        await self._do_tempban(interaction, member, duration, delete_days, reason)

    @app_commands.command(name="tempbanid", description="Temporarily ban a user by Discord ID.", extras={"red_force_enable": True})
    @app_commands.describe(user_id="Discord user ID", duration="Any Red duration; omit for the configured default", delete_days="Days of messages to delete (0-7)", reason="Reason")
    @app_commands.autocomplete(duration=duration_autocomplete)
    @app_commands.guild_only()
    async def tempbanid(
        self,
        interaction: discord.Interaction,
        user_id: str,
        duration: Optional[str] = None,
        delete_days: Optional[app_commands.Range[int, 0, 7]] = None,
        reason: Optional[str] = None,
    ) -> None:
        user_id = await self._validated_user_id(interaction, user_id)
        if user_id is None or interaction.guild is None:
            return
        default_days, default_duration = await self._mod_defaults(interaction.guild)
        if duration is None:
            duration = f"{default_duration}s"
        if delete_days is None:
            delete_days = default_days
        await self._run_legacy(
            interaction, self._line("tempban", user_id, duration, delete_days, reason)
        )

    @app_commands.command(name="unban", description="Unban a user using the Red Mod cog.", extras={"red_force_enable": True})
    @app_commands.describe(user="Discord user ID", reason="Reason")
    @app_commands.guild_only()
    async def unban(
        self,
        interaction: discord.Interaction,
        user: str,
        reason: Optional[str] = None,
    ) -> None:
        await self._run_legacy(interaction, self._line("unban", user, reason))

    @app_commands.command(name="разбан", description="Разбанить пользователя через Red Mod.", extras={"red_force_enable": True})
    @app_commands.rename(user="id_пользователя", reason="причина")
    @app_commands.guild_only()
    async def unban_ru(
        self,
        interaction: discord.Interaction,
        user: str,
        reason: Optional[str] = None,
    ) -> None:
        await self._run_legacy(interaction, self._line("unban", user, reason))

    @app_commands.command(name="names", description="Show a member's stored previous names.", extras={"red_force_enable": True})
    @app_commands.describe(member="Member")
    @app_commands.guild_only()
    async def names(
        self, interaction: discord.Interaction, member: discord.Member
    ) -> None:
        await self._run_legacy(interaction, self._line("names", member.id))

    @app_commands.command(name="rename", description="Change or clear a member's nickname.", extras={"red_force_enable": True})
    @app_commands.describe(member="Member", nickname="New nickname; leave empty to clear")
    @app_commands.guild_only()
    async def rename(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        nickname: Optional[str] = None,
    ) -> None:
        await self._run_legacy(interaction, self._line("rename", member.id, nickname))

    @app_commands.command(name="slowmode", description="Set slowmode in the current channel/thread.", extras={"red_force_enable": True})
    @app_commands.describe(duration="Any Red interval; leave empty to disable")
    @app_commands.autocomplete(duration=duration_autocomplete)
    @app_commands.guild_only()
    async def slowmode(
        self,
        interaction: discord.Interaction,
        duration: Optional[str] = None,
    ) -> None:
        await self._run_legacy(interaction, self._line("slowmode", duration))

    @app_commands.command(name="userinfo", description="Show Red user information.", extras={"red_force_enable": True})
    @app_commands.describe(member="Member; leave empty for yourself")
    @app_commands.guild_only()
    async def userinfo(
        self,
        interaction: discord.Interaction,
        member: Optional[discord.Member] = None,
    ) -> None:
        await self._run_legacy(
            interaction, self._line("userinfo", member.id if member else None)
        )

    @app_commands.command(name="voiceban", description="Voice-ban a member using Red Mod.", extras={"red_force_enable": True})
    @app_commands.describe(member="Member", reason="Reason")
    @app_commands.guild_only()
    async def voiceban(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: Optional[str] = None,
    ) -> None:
        await self._run_legacy(interaction, self._line("voiceban", member.id, reason))

    @app_commands.command(name="voicekick", description="Disconnect a member from voice using Red Mod.", extras={"red_force_enable": True})
    @app_commands.describe(member="Member", reason="Reason")
    @app_commands.guild_only()
    async def voicekick(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: Optional[str] = None,
    ) -> None:
        await self._run_legacy(interaction, self._line("voicekick", member.id, reason))

    @app_commands.command(name="voiceunban", description="Remove a Red voice ban from a member.", extras={"red_force_enable": True})
    @app_commands.describe(member="Member", reason="Reason")
    @app_commands.guild_only()
    async def voiceunban(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: Optional[str] = None,
    ) -> None:
        await self._run_legacy(interaction, self._line("voiceunban", member.id, reason))

    # ---------- ModLog ----------

    async def _do_case(self, interaction: discord.Interaction, number: int) -> None:
        await self._run_legacy(interaction, self._line("case", number))

    @app_commands.command(name="case", description="Show a Red ModLog case.", extras={"red_force_enable": True})
    @app_commands.describe(number="Case number")
    @app_commands.guild_only()
    async def case(self, interaction: discord.Interaction, number: int) -> None:
        await self._do_case(interaction, number)

    @app_commands.command(name="кейс", description="Показать кейс Red ModLog.", extras={"red_force_enable": True})
    @app_commands.rename(number="номер")
    @app_commands.guild_only()
    async def case_ru(self, interaction: discord.Interaction, number: int) -> None:
        await self._do_case(interaction, number)

    async def _do_casesfor(
        self, interaction: discord.Interaction, member: discord.Member
    ) -> None:
        await self._run_legacy(interaction, self._line("casesfor", member.id))

    @app_commands.command(name="casesfor", description="Show ModLog cases for a member.", extras={"red_force_enable": True})
    @app_commands.describe(member="Member")
    @app_commands.guild_only()
    async def casesfor(
        self, interaction: discord.Interaction, member: discord.Member
    ) -> None:
        await self._do_casesfor(interaction, member)

    @app_commands.command(name="cases", description="Alias for /casesfor.", extras={"red_force_enable": True})
    @app_commands.describe(member="Member")
    @app_commands.guild_only()
    async def cases_alias(
        self, interaction: discord.Interaction, member: discord.Member
    ) -> None:
        await self._do_casesfor(interaction, member)

    @app_commands.command(name="кейсы", description="Показать кейсы участника.", extras={"red_force_enable": True})
    @app_commands.rename(member="участник")
    @app_commands.guild_only()
    async def cases_ru(
        self, interaction: discord.Interaction, member: discord.Member
    ) -> None:
        await self._do_casesfor(interaction, member)

    @app_commands.command(name="casesid", description="Show ModLog cases for a user by Discord ID.", extras={"red_force_enable": True})
    @app_commands.describe(user_id="Discord user ID")
    @app_commands.guild_only()
    async def casesid(
        self, interaction: discord.Interaction, user_id: str
    ) -> None:
        user_id = await self._validated_user_id(interaction, user_id)
        if user_id is None:
            return
        await self._run_legacy(interaction, self._line("casesfor", user_id))

    @app_commands.command(name="listcases", description="List ModLog cases for a member.", extras={"red_force_enable": True})
    @app_commands.describe(member="Member")
    @app_commands.guild_only()
    async def listcases(
        self, interaction: discord.Interaction, member: discord.Member
    ) -> None:
        await self._run_legacy(interaction, self._line("listcases", member.id))

    @app_commands.command(name="listcasesid", description="List ModLog cases for a user by Discord ID.", extras={"red_force_enable": True})
    @app_commands.describe(user_id="Discord user ID")
    @app_commands.guild_only()
    async def listcasesid(
        self, interaction: discord.Interaction, user_id: str
    ) -> None:
        user_id = await self._validated_user_id(interaction, user_id)
        if user_id is None:
            return
        await self._run_legacy(interaction, self._line("listcases", user_id))

    @app_commands.command(name="reason", description="Change the reason on a Red ModLog case.", extras={"red_force_enable": True})
    @app_commands.describe(reason="New reason", case="Case number; omit for latest")
    @app_commands.guild_only()
    async def reason(
        self,
        interaction: discord.Interaction,
        reason: str,
        case: Optional[int] = None,
    ) -> None:
        if interaction.guild is None:
            await self._respond(interaction, "Эта команда работает только на сервере.")
            return
        if case is None:
            latest = await modlog.get_latest_case(interaction.guild, self.bot)
            if latest is None:
                await self._respond(interaction, "На сервере пока нет кейсов ModLog.")
                return
            case = latest.case_number
        await self._run_legacy(interaction, self._line("reason", case, reason))

    # ---------- Reports ----------

    async def _do_report(
        self, interaction: discord.Interaction, text: Optional[str]
    ) -> None:
        await self._run_legacy(interaction, self._line("report", text))

    @app_commands.command(name="report", description="Send a report using Red Reports.", extras={"red_force_enable": True})
    @app_commands.describe(text="Report text; leave empty for Red's interactive mode")
    @app_commands.guild_only()
    async def report(
        self,
        interaction: discord.Interaction,
        text: Optional[str] = None,
    ) -> None:
        await self._do_report(interaction, text)

    @app_commands.command(name="репорт", description="Отправить репорт через Red Reports.", extras={"red_force_enable": True})
    @app_commands.rename(text="текст")
    @app_commands.guild_only()
    async def report_ru(
        self,
        interaction: discord.Interaction,
        text: Optional[str] = None,
    ) -> None:
        await self._do_report(interaction, text)

    @app_commands.command(name="report-interact", description="Open a Red report message tunnel.", extras={"red_force_enable": True})
    @app_commands.describe(ticket="Report ticket number")
    @app_commands.guild_only()
    async def report_interact(
        self, interaction: discord.Interaction, ticket: int
    ) -> None:
        await self._run_legacy(interaction, self._line("report interact", ticket))
