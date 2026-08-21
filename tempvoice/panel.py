import logging
from typing import Optional

import discord
from redbot.core import commands
from redbot.core.bot import Red

from .tempvoice import TempVoice


log = logging.getLogger("red.neuropolimer.tempvoice.panel")


class RoomNameModal(discord.ui.Modal, title="Переименовать комнату"):
    name = discord.ui.TextInput(
        label="Новое название",
        placeholder="Название голосового канала",
        min_length=1,
        max_length=100,
    )

    def __init__(self, panel: "TempVoicePanel", current_name: str):
        super().__init__(timeout=180)
        self.panel = panel
        self.name.default = current_name[:100]

    async def on_submit(self, interaction: discord.Interaction) -> None:
        channel = await self.panel.get_owned_room(interaction)
        if channel is None:
            return
        if not await self.panel.require_bot_permissions(
            interaction, channel, manage_channels=True
        ):
            return

        new_name = str(self.name).strip()
        if not new_name:
            await self.panel.reply(interaction, "Название не может быть пустым.")
            return

        try:
            await channel.edit(
                name=new_name,
                reason=f"TempVoice panel rename by {interaction.user} ({interaction.user.id})",
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            await self.panel.api_error(interaction, "переименовать комнату", exc)
            return

        await self.panel.reply(
            interaction,
            f"Комната переименована в **{discord.utils.escape_markdown(new_name)}**.",
        )


class RoomLimitModal(discord.ui.Modal, title="Лимит участников"):
    limit = discord.ui.TextInput(
        label="Лимит от 0 до 99",
        placeholder="0 — без ограничения",
        min_length=1,
        max_length=2,
    )

    def __init__(self, panel: "TempVoicePanel", current_limit: int):
        super().__init__(timeout=180)
        self.panel = panel
        self.limit.default = str(current_limit)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        channel = await self.panel.get_owned_room(interaction)
        if channel is None:
            return

        try:
            value = int(str(self.limit).strip())
        except ValueError:
            await self.panel.reply(interaction, "Введи целое число от 0 до 99.")
            return

        if not 0 <= value <= 99:
            await self.panel.reply(interaction, "Лимит должен быть от 0 до 99.")
            return

        if not await self.panel.require_bot_permissions(
            interaction, channel, manage_channels=True
        ):
            return

        try:
            await channel.edit(
                user_limit=value,
                reason=f"TempVoice panel limit by {interaction.user} ({interaction.user.id})",
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            await self.panel.api_error(interaction, "изменить лимит комнаты", exc)
            return

        if value == 0:
            await self.panel.reply(interaction, "Лимит участников отключён.")
        else:
            await self.panel.reply(interaction, f"Лимит установлен: **{value}**.")


class MemberActionSelect(discord.ui.UserSelect):
    def __init__(self, panel: "TempVoicePanel", action: str):
        labels = {
            "permit": "Кому разрешить вход?",
            "reject": "Кому запретить вход?",
            "kick": "Кого отключить?",
        }
        super().__init__(placeholder=labels[action], min_values=1, max_values=1)
        self.panel = panel
        self.action = action

    async def callback(self, interaction: discord.Interaction) -> None:
        selected = self.values[0]
        if isinstance(selected, discord.Member):
            member: Optional[discord.Member] = selected
        elif interaction.guild is not None:
            member = interaction.guild.get_member(selected.id)
        else:
            member = None

        if member is None:
            await self.panel.reply(
                interaction, "Не удалось найти выбранного участника на сервере."
            )
            return

        if self.action == "permit":
            await self.panel.permit(interaction, member)
        elif self.action == "reject":
            await self.panel.reject(interaction, member)
        else:
            await self.panel.kick(interaction, member)


class MemberActionView(discord.ui.View):
    def __init__(self, panel: "TempVoicePanel", action: str, requester_id: int):
        super().__init__(timeout=60)
        self.requester_id = requester_id
        self.add_item(MemberActionSelect(panel, action))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.requester_id:
            return True
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "Это меню открыто другим пользователем.", ephemeral=True
            )
        return False


class RoomControlsView(discord.ui.View):
    def __init__(self, panel: "TempVoicePanel"):
        super().__init__(timeout=None)
        self.panel = panel

    async def _selector(self, interaction: discord.Interaction, action: str) -> None:
        channel = await self.panel.get_owned_room(interaction)
        if channel is None:
            return

        labels = {
            "permit": "Выбери участника, которому нужно разрешить вход.",
            "reject": "Выбери участника, которому нужно запретить вход.",
            "kick": "Выбери участника, которого нужно отключить от комнаты.",
        }
        await interaction.response.send_message(
            labels[action],
            view=MemberActionView(self.panel, action, interaction.user.id),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Название",
        emoji="✏️",
        style=discord.ButtonStyle.secondary,
        custom_id="kguard_tempvoice:rename:v1",
        row=0,
    )
    async def rename(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        channel = await self.panel.get_owned_room(interaction)
        if channel is None:
            return
        await interaction.response.send_modal(RoomNameModal(self.panel, channel.name))

    @discord.ui.button(
        label="Лимит",
        emoji="👥",
        style=discord.ButtonStyle.secondary,
        custom_id="kguard_tempvoice:limit:v1",
        row=0,
    )
    async def limit(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        channel = await self.panel.get_owned_room(interaction)
        if channel is None:
            return
        await interaction.response.send_modal(
            RoomLimitModal(self.panel, channel.user_limit or 0)
        )

    @discord.ui.button(
        label="Закрыть",
        emoji="🔒",
        style=discord.ButtonStyle.danger,
        custom_id="kguard_tempvoice:lock:v1",
        row=0,
    )
    async def lock(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.panel.set_everyone_permission(
            interaction,
            permission="connect",
            value=False,
            success="Комната закрыта для @everyone.",
            action="закрыть комнату",
        )

    @discord.ui.button(
        label="Открыть",
        emoji="🔓",
        style=discord.ButtonStyle.success,
        custom_id="kguard_tempvoice:unlock:v1",
        row=0,
    )
    async def unlock(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        channel = await self.panel.get_owned_room(interaction)
        if channel is None:
            return
        base = self.panel.category_permission(channel, "connect")
        await self.panel.set_everyone_permission(
            interaction,
            permission="connect",
            value=base,
            success="Право подключения @everyone восстановлено по настройкам категории.",
            action="открыть комнату",
            channel=channel,
        )

    @discord.ui.button(
        label="Скрыть",
        emoji="🙈",
        style=discord.ButtonStyle.danger,
        custom_id="kguard_tempvoice:hide:v1",
        row=0,
    )
    async def hide(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.panel.set_everyone_permission(
            interaction,
            permission="view_channel",
            value=False,
            success="Комната скрыта от @everyone.",
            action="скрыть комнату",
        )

    @discord.ui.button(
        label="Показать",
        emoji="👁️",
        style=discord.ButtonStyle.success,
        custom_id="kguard_tempvoice:show:v1",
        row=1,
    )
    async def show(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        channel = await self.panel.get_owned_room(interaction)
        if channel is None:
            return
        base = self.panel.category_permission(channel, "view_channel")
        await self.panel.set_everyone_permission(
            interaction,
            permission="view_channel",
            value=base,
            success="Видимость @everyone восстановлена по настройкам категории.",
            action="показать комнату",
            channel=channel,
        )

    @discord.ui.button(
        label="Разрешить",
        emoji="✅",
        style=discord.ButtonStyle.primary,
        custom_id="kguard_tempvoice:permit:v1",
        row=1,
    )
    async def permit_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self._selector(interaction, "permit")

    @discord.ui.button(
        label="Запретить",
        emoji="⛔",
        style=discord.ButtonStyle.secondary,
        custom_id="kguard_tempvoice:reject:v1",
        row=1,
    )
    async def reject_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self._selector(interaction, "reject")

    @discord.ui.button(
        label="Кик",
        emoji="👢",
        style=discord.ButtonStyle.secondary,
        custom_id="kguard_tempvoice:kick:v1",
        row=1,
    )
    async def kick_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self._selector(interaction, "kick")


class TempVoicePanel(commands.Cog):
    """Кнопочная панель управления для TempVoice."""

    __author__ = "neuropolimer"
    __version__ = "1.0.0"

    def __init__(self, bot: Red):
        self.bot = bot
        self._persistent_view: Optional[RoomControlsView] = None
        self._welcomed_rooms = set()

    @property
    def tempvoice(self) -> Optional[TempVoice]:
        cog = self.bot.get_cog("TempVoice")
        return cog if isinstance(cog, TempVoice) else None

    async def cog_load(self) -> None:
        self._persistent_view = RoomControlsView(self)
        self.bot.add_view(self._persistent_view)

    def cog_unload(self) -> None:
        if self._persistent_view is None:
            return
        remove_view = getattr(self.bot, "remove_view", None)
        if remove_view is not None:
            try:
                remove_view(self._persistent_view)
            except Exception:
                log.debug("Не удалось удалить persistent TempVoice view", exc_info=True)

    @staticmethod
    async def reply(interaction: discord.Interaction, content: str) -> None:
        if interaction.response.is_done():
            await interaction.followup.send(content, ephemeral=True)
        else:
            await interaction.response.send_message(content, ephemeral=True)

    async def get_owned_room(
        self, interaction: discord.Interaction
    ) -> Optional[discord.VoiceChannel]:
        base = self.tempvoice
        guild = interaction.guild
        channel = interaction.channel
        member = interaction.user

        if (
            base is None
            or guild is None
            or not isinstance(channel, discord.VoiceChannel)
            or not isinstance(member, discord.Member)
        ):
            await self.reply(
                interaction, "Эта панель работает только в временном голосовом канале."
            )
            return None

        room = base._rooms[guild.id].get(channel.id)
        if room is None:
            await self.reply(
                interaction, "Этот канал больше не является временной комнатой."
            )
            return None

        if int(room.get("owner_id", 0)) != member.id:
            await self.reply(
                interaction, "Этими кнопками может пользоваться только текущий владелец комнаты."
            )
            return None

        voice_channel = getattr(member.voice, "channel", None)
        if voice_channel is None or voice_channel.id != channel.id:
            await self.reply(
                interaction, "Для управления сначала зайди в эту голосовую комнату."
            )
            return None

        return channel

    async def require_bot_permissions(
        self,
        interaction: discord.Interaction,
        channel: discord.VoiceChannel,
        **required: bool,
    ) -> bool:
        me = channel.guild.me
        if me is None:
            await self.reply(interaction, "Не удалось определить участника-бота.")
            return False

        permissions = channel.permissions_for(me)
        labels = {
            "manage_channels": "Управлять каналами",
            "move_members": "Перемещать участников",
            "send_messages": "Отправлять сообщения",
            "embed_links": "Встраивать ссылки",
        }
        missing = [
            labels.get(name, name)
            for name, needed in required.items()
            if needed and not getattr(permissions, name, False)
        ]
        if missing:
            await self.reply(
                interaction, "Боту не хватает прав: " + ", ".join(missing) + "."
            )
            return False
        return True

    async def api_error(
        self, interaction: discord.Interaction, action: str, exc: Exception
    ) -> None:
        if isinstance(exc, discord.Forbidden):
            await self.reply(
                interaction,
                f"Discord запретил {action}. Проверь права и позицию роли KGuard.",
            )
        else:
            await self.reply(
                interaction, f"Discord API не смог {action}. Попробуй ещё раз."
            )

    @staticmethod
    def category_permission(
        channel: discord.VoiceChannel, permission: str
    ) -> Optional[bool]:
        if channel.category is None:
            return None
        overwrite = channel.category.overwrites_for(channel.guild.default_role)
        return getattr(overwrite, permission)

    async def set_everyone_permission(
        self,
        interaction: discord.Interaction,
        *,
        permission: str,
        value: Optional[bool],
        success: str,
        action: str,
        channel: Optional[discord.VoiceChannel] = None,
    ) -> None:
        if channel is None:
            channel = await self.get_owned_room(interaction)
            if channel is None:
                return
        else:
            checked = await self.get_owned_room(interaction)
            if checked is None or checked.id != channel.id:
                return

        if not await self.require_bot_permissions(
            interaction, channel, manage_channels=True
        ):
            return

        everyone = channel.guild.default_role
        overwrite = channel.overwrites_for(everyone)
        setattr(overwrite, permission, value)

        try:
            await channel.set_permissions(
                everyone,
                overwrite=None if overwrite.is_empty() else overwrite,
                reason=f"TempVoice panel {action} by {interaction.user} ({interaction.user.id})",
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            await self.api_error(interaction, action, exc)
            return

        await self.reply(interaction, success)

    async def permit(
        self, interaction: discord.Interaction, member: discord.Member
    ) -> None:
        channel = await self.get_owned_room(interaction)
        if channel is None:
            return

        if not await self.require_bot_permissions(
            interaction, channel, manage_channels=True
        ):
            return

        overwrite = channel.overwrites_for(member)
        overwrite.view_channel = True
        overwrite.connect = True

        try:
            await channel.set_permissions(
                member,
                overwrite=overwrite,
                reason=f"TempVoice panel permit by {interaction.user} ({interaction.user.id})",
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            await self.api_error(interaction, "разрешить участнику вход", exc)
            return

        await self.reply(
            interaction, f"{member.mention} теперь может видеть комнату и подключаться."
        )

    async def reject(
        self, interaction: discord.Interaction, member: discord.Member
    ) -> None:
        channel = await self.get_owned_room(interaction)
        if channel is None:
            return

        if self.bot.user is not None and member.id == self.bot.user.id:
            await self.reply(interaction, "Нельзя заблокировать самого KGuard.")
            return
        if member.id == interaction.user.id:
            await self.reply(interaction, "Нельзя заблокировать самого себя.")
            return

        is_inside = getattr(member.voice, "channel", None) == channel
        if not await self.require_bot_permissions(
            interaction,
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
                reason=f"TempVoice panel reject by {interaction.user} ({interaction.user.id})",
            )
            if is_inside:
                await member.move_to(
                    None,
                    reason=f"TempVoice panel reject by {interaction.user} ({interaction.user.id})",
                )
        except (discord.Forbidden, discord.HTTPException) as exc:
            await self.api_error(interaction, "запретить участнику вход", exc)
            return

        await self.reply(
            interaction, f"{member.mention} больше не может подключаться к комнате."
        )

    async def kick(
        self, interaction: discord.Interaction, member: discord.Member
    ) -> None:
        channel = await self.get_owned_room(interaction)
        if channel is None:
            return

        if self.bot.user is not None and member.id == self.bot.user.id:
            await self.reply(interaction, "Нельзя отключить самого KGuard.")
            return
        if member.id == interaction.user.id:
            await self.reply(interaction, "Нельзя отключить самого себя этой кнопкой.")
            return
        if getattr(member.voice, "channel", None) != channel:
            await self.reply(
                interaction, "Этот участник сейчас не находится в твоей комнате."
            )
            return

        if not await self.require_bot_permissions(
            interaction, channel, move_members=True
        ):
            return

        try:
            await member.move_to(
                None,
                reason=f"TempVoice panel kick by {interaction.user} ({interaction.user.id})",
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            await self.api_error(interaction, "отключить участника", exc)
            return

        await self.reply(
            interaction,
            f"{member.mention} отключён без запрета на повторный вход.",
        )

    async def _prefix_for(self, guild: discord.Guild) -> str:
        try:
            prefixes = await self.bot.get_valid_prefixes(guild)
        except Exception:
            return "!"

        for prefix in prefixes:
            if not prefix.startswith("<@"):
                return prefix
        return prefixes[0] if prefixes else "!"

    async def send_panel(
        self, channel: discord.VoiceChannel, owner: discord.Member
    ) -> None:
        me = channel.guild.me
        if me is None:
            return

        permissions = channel.permissions_for(me)
        if not permissions.send_messages:
            log.warning(
                "Не удалось отправить панель TempVoice в %s: нет Send Messages",
                channel.id,
            )
            return

        prefix = await self._prefix_for(channel.guild)
        help_command = f"{prefix}help vc"

        content = (
            f"{owner.mention}, твоя временная голосовая комната готова.\n"
            f"Все настройки доступны кнопками ниже.\n"
            f"Полный список текстовых команд: `{help_command}`"
        )

        kwargs = {"view": self._persistent_view or RoomControlsView(self)}
        if permissions.embed_links:
            embed = discord.Embed(
                title="🔊 Управление голосовой комнатой",
                description=(
                    f"{owner.mention}, комната готова. Настраивай её кнопками ниже."
                ),
            )
            embed.add_field(
                name="Все команды",
                value=f"Введи `{help_command}`, чтобы открыть полный список команд `vc`.",
                inline=False,
            )
            embed.add_field(
                name="Доступ",
                value="Панель работает только для текущего владельца комнаты.",
                inline=False,
            )
            kwargs["embed"] = embed
        else:
            kwargs["content"] = content

        try:
            await channel.send(**kwargs)
        except (discord.Forbidden, discord.HTTPException):
            log.exception(
                "Не удалось отправить приветственную панель TempVoice в канал %s",
                channel.id,
            )

    @commands.Cog.listener("on_voice_state_update")
    async def tempvoice_panel_listener(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if member.bot:
            return

        base = self.tempvoice
        before_channel = before.channel
        after_channel = after.channel

        if (
            base is None
            or not isinstance(before_channel, discord.VoiceChannel)
            or not isinstance(after_channel, discord.VoiceChannel)
        ):
            return

        if before_channel.id not in base._generators[member.guild.id]:
            return

        room = base._rooms[member.guild.id].get(after_channel.id)
        if room is None or int(room.get("owner_id", 0)) != member.id:
            return

        if after_channel.id in self._welcomed_rooms:
            return

        age = (discord.utils.utcnow() - after_channel.created_at).total_seconds()
        if age > 30:
            return

        self._welcomed_rooms.add(after_channel.id)
        await self.send_panel(after_channel, member)

    @commands.Cog.listener("on_guild_channel_delete")
    async def tempvoice_panel_channel_delete(
        self, channel: discord.abc.GuildChannel
    ) -> None:
        self._welcomed_rooms.discard(channel.id)
