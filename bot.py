from datetime import datetime, timezone, timedelta
import json
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
import discord
from discord.ext import commands, tasks

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Хранилище корзин и подписок
bot.user_carts = {}
reminder_subscribers = set()
last_timer_message_id = None

# Часовой пояс МСК (UTC+3)
MSK = timezone(timedelta(hours=3))

# Вставьте ваш цифровой ID сюда (можно переопределить через переменную OWNER_ID в Render):
OWNER_ID = int(os.getenv("OWNER_ID", "736990837254258838"))

ALL_DATA = {
    "Дары Моря": {
        "🐟 Красноперка (ДМ-1)": {"price": 1.4},
        "🐟 Плотва (ДМ-1)": {"price": 1.3},
        "🐟 Лещ (ДМ-1)": {"price": 1.0},
        "🐠 Серебряный карась (ДМ-2)": {"price": 1.15},
        "🐟 Коричневый сом (ДМ-2)": {"price": 1.10},
        "🐟 Вобла (ДМ-2)": {"price": 1.0},
        "🐟 Речной окунь (ДМ-3)": {"price": 0.90},
        "🐠 Радужная форель (ДМ-3)": {"price": 0.85},
        "🐟 Обыкновенная щука (ДМ-3)": {"price": 0.85},
        "🐟 Сазан (ДМ-4)": {"price": 0.85},
        "🐟 Сом обыкновенный (ДМ-4)": {"price": 0.8},
        "🐟 Зеркальный карп (ДМ-4)": {"price": 0.8},
        "🐟 Жерех (ДМ-5)": {"price": 1.0},
        "🐟 Судак обыкновенный (ДМ-5)": {"price": 1.0},
        "🐟 Прибрежный басс (ДМ-6)": {"price": 0.90},
        "🐟 Альбула (ДМ-6)": {"price": 0.95},
        "🐟 Снук обыкновенный (ДМ-6)": {"price": 0.85},
        "🐟 Барракуда (ДМ-7)": {"price": 0.90},
        "🐟 Круглый трахинот (ДМ-7)": {"price": 0.85},
        "🐟 Полосатый лаврак (ДМ-7)": {"price": 0.95},
        "🐟 Красный горбыль (ДМ-8)": {"price": 0.90},
        "🐟 Марлин (ДМ-8)": {"price": 0.95},
        "🐟 Тёмный горбыль (ДМ-8)": {"price": 0.85},
    },
    "Металлургия": {
        "⛏️ Железная руда": {"price": 64},
        "⛏️ Серебряная руда": {"price": 120},
        "⛏️ Медная руда": {"price": 210},
        "⛏️ Золотая руда": {"price": 420},
    },
    "Поезд": {
        "📦 Коробка с поезда": {"price": 865}
    },
    "Ателье": {
        "👕 Закрытие Ателье": {"price": 1250}
    },
    "Активация контракта": {
        "⚡ Металлургия": {"price": 12000},
        "⚡ Поезд": {"price": 8000},
        "⚡ Ателье": {"price": 6000},
    },
}


# --- Вспомогательные функции для тайников ---
def get_cache_timestamps():
    now = datetime.now(MSK)
    current_hour = now.hour
    current_minute = now.minute

    if 30 <= current_minute < 45:
        end_time = now.replace(minute=45, second=0, microsecond=0)
        return int(end_time.timestamp()), True
    else:
        if current_minute >= 45:
            target_hour = current_hour + 1
            target_minute = 30
            day_offset = 0
            if target_hour >= 24:
                target_hour = 0
                day_offset = 1
        else:
            target_hour = current_hour
            target_minute = 30
            day_offset = 0

        start_time = (
                now.replace(
                    hour=target_hour, minute=target_minute, second=0, microsecond=0
                )
                + timedelta(days=day_offset)
        )
        return int(start_time.timestamp()), False


class WebStyleCacheView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="🔔 Уведомление в ЛС", style=discord.ButtonStyle.success, row=0
    )
    async def toggle_reminder(
            self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        user_id = interaction.user.id
        if user_id in reminder_subscribers:
            reminder_subscribers.remove(user_id)
            button.label = "🔔 Уведомление в ЛС"
            button.style = discord.ButtonStyle.success
            await interaction.response.edit_message(view=self)
            await interaction.followup.send(
                "❌ Вы отписались от уведомлений в ЛС.", ephemeral=True
            )
        else:
            reminder_subscribers.add(user_id)
            button.label = "🔕 Уведомления включены"
            button.style = discord.ButtonStyle.secondary
            await interaction.response.edit_message(view=self)
            await interaction.followup.send(
                "✅ Вы подписались на уведомления о контрабанде в ЛС!",
                ephemeral=True,
            )


def generate_timers_embed_and_view():
    supply_ts, supply_active = get_cache_timestamps()

    if supply_active:
        supply_status = f"🟢 Активна (закончится <t:{supply_ts}:R>)"
    else:
        supply_status = f"⏳ Будет активна <t:{supply_ts}:R>"

    embed = discord.Embed(
        title="🚨 Мониторинг поставок контрабанды",
        description="Актуальное расписание и таймер поставок в реальном времени.",
        color=discord.Color.from_rgb(20, 20, 20),
    )

    embed.add_field(
        name="📦 Поставка контрабанды",
        value=(
            f"**Статус:** {supply_status}\n\n"
            "⏰ **График работы:** каждый час с `:30` по `:45` минут\n"
            "(с 01:30 до 23:30)"
        ),
        inline=False,
    )

    embed.set_footer(text="Majestic RP • Мониторинг поставок")
    return embed, WebStyleCacheView()


# Фоновая задача уведомлений
@tasks.loop(minutes=1, reconnect=True)
async def check_contraband_reminders():
    try:
        timestamp, is_active = get_cache_timestamps()
        current_ts = int(datetime.now(MSK).timestamp())
        time_left = timestamp - current_ts

        if not is_active and 290 <= time_left <= 310:
            for user_id in reminder_subscribers:
                try:
                    user = await bot.fetch_user(user_id)
                    await user.send(
                        "⚠️ **Внимание!** Поставка контрабанды будет активна через 5 минут!"
                    )
                except Exception as e:
                    print(
                        f"Не удалось отправить ЛС пользователю {user_id}: {e}"
                    )
    except Exception as e:
        print(f"[Ошибка фоновой задачи уведомлений]: {e}")


@check_contraband_reminders.before_loop
async def before_check_reminders():
    await bot.wait_until_ready()


# Фоновая задача автообновления таймеров
@tasks.loop(seconds=30)
async def auto_update_timers_message():
    global last_timer_message_id
    if not last_timer_message_id:
        return

    for guild in bot.guilds:
        for channel in guild.text_channels:
            try:
                msg = await channel.fetch_message(last_timer_message_id)
                if msg:
                    embed, view = generate_timers_embed_and_view()
                    await msg.edit(embed=embed, view=view)
                    return
            except discord.NotFound:
                continue
            except Exception as e:
                print(f"Ошибка автообновления тайников: {e}")


# --- Кнопки Принять/Отклонить ---
class ReportManagementView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        allowed_roles = ["Админ", "Модератор"]
        has_role = any(
            role.name in allowed_roles for role in interaction.user.roles
        )

        if (
                interaction.user.id == OWNER_ID
                or has_role
                or interaction.user.guild_permissions.administrator
        ):
            return True

        await interaction.response.send_message(
            "❌ У вас нет прав для управления отчетами!", ephemeral=True
        )
        return False

    @discord.ui.button(label="✅ Принять", style=discord.ButtonStyle.green)
    async def accept(
            self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        embed = interaction.message.embeds[0]
        # защита от двойного начисления (после рестарта кнопки снова активны)
        for f in embed.fields:
            if f.name == "Статус":
                return await interaction.response.send_message("⚠️ Этот отчёт уже обработан.", ephemeral=True)

        # --- начисляем баллы за контракт ---
        import re as _re
        worker_id = None
        worker_mention = "?"
        for f in embed.fields:
            if f.name == "Сотрудник":
                worker_mention = f.value
                m = _re.search(r"(\d{5,})", f.value)
                if m:
                    worker_id = m.group(1)
                break
        item_lines = []
        for f in embed.fields:
            if f.name == "Элементы":
                item_lines = (f.value or "").split("\n")
                break
        awarded = 0
        details = ""
        if worker_id and item_lines:
            awarded, details = calc_contract_points(item_lines)
            if awarded > 0:
                try:
                    adb = load_activity()
                    if worker_id not in adb:
                        # пробуем взять ник с сервера
                        nick = worker_mention
                        try:
                            mem = interaction.guild.get_member(int(worker_id))
                            if mem:
                                nick = mem.display_name
                        except Exception:
                            pass
                        adb[worker_id] = {"nick": nick, "static": "", "discord_id": int(worker_id),
                                          "seconds": 0, "manual_hours": 0.0, "manual_points": 0,
                                          "contract_points": 0, "history": []}
                    adb[worker_id].setdefault("contract_points", 0)
                    adb[worker_id]["contract_points"] = int(adb[worker_id]["contract_points"]) + awarded
                    adb[worker_id].setdefault("history", []).append(
                        f"{datetime.now(MSK).strftime('%d.%m %H:%M')} — контракт +{awarded} от {interaction.user.mention}"
                    )
                    save_activity(adb)
                except Exception as e:
                    print(f"[award contract points err]: {e}")
                    awarded = 0

        embed.color = discord.Color.green()
        embed.add_field(
            name="Статус",
            value=f"✅ Одобрено: {interaction.user.mention}",
            inline=False,
        )
        if awarded > 0:
            total_now = 0
            try:
                total_now = entry_points(load_activity().get(worker_id, {}))
            except Exception:
                pass
            roman, _cname = get_contract(total_now)
            embed.add_field(
                name="⭐ Баллы",
                value=f"+{awarded} баллов {worker_mention} (всего **{total_now}**, контракт **{roman}** — {fmt_progress(total_now)})",
                inline=False,
            )
        elif worker_id:
            embed.add_field(name="⭐ Баллы", value="0 баллов (не recognised предметы?)", inline=False)

        await interaction.response.edit_message(embed=embed, view=self)

        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)

    @discord.ui.button(label="❌ Отклонить", style=discord.ButtonStyle.red)
    async def reject(
            self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        embed = interaction.message.embeds[0]
        for f in embed.fields:
            if f.name == "Статус":
                return await interaction.response.send_message("⚠️ Этот отчёт уже обработан.", ephemeral=True)
        embed.color = discord.Color.red()
        embed.add_field(
            name="Статус",
            value=f"❌ Отклонено: {interaction.user.mention}",
            inline=False,
        )

        await interaction.response.edit_message(embed=embed, view=self)

        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)


# --- Модальное окно ввода количества ---
class BatchQuantityModal(discord.ui.Modal):

    def __init__(self, selected_items):
        super().__init__(title="Введите количество")
        self.selected_items = selected_items
        self.inputs = {}
        for item in selected_items:
            text_input = discord.ui.TextInput(
                label=item[:45], placeholder="Количество", required=True
            )
            self.add_item(text_input)
            self.inputs[item] = text_input

    async def on_submit(self, interaction: discord.Interaction):
        uid = interaction.user.id
        if uid not in bot.user_carts:
            bot.user_carts[uid] = {"items": [], "total": 0}

        report_data = []
        total_sum = 0
        for item, text_input in self.inputs.items():
            try:
                qty = int(text_input.value)
                price = 0
                for cat in ALL_DATA.values():
                    if item in cat:
                        price = cat[item]["price"]
                        break

                total_sum += qty * price
                report_data.append(
                    f"{item} — {qty} шт. (Сумма: {round(qty * price, 2)})"
                )
            except ValueError:
                return await interaction.response.send_message(
                    f"Ошибка в числе для {item}!", ephemeral=True
                )

        bot.user_carts[uid]["items"] = report_data
        bot.user_carts[uid]["total"] = round(total_sum, 2)
        await interaction.response.send_message(
            "✅ Данные приняты! Теперь отправьте скриншот в чат.", ephemeral=True
        )


# --- Приватные голосовые: владелец + меню (другие не могут управлять) ---
# vc_id -> owner_id, vc_id -> view (чтобы обновлять владельца при передаче)
temp_voice_owners: dict = {}
temp_voice_views: dict = {}


def get_temp_vc(guild: discord.Guild, vc_id: int):
    vc = guild.get_channel(vc_id)
    if isinstance(vc, discord.VoiceChannel):
        return vc
    return None


def find_control_text(guild: discord.Guild, vc_id: int):
    for tc in guild.text_channels:
        try:
            if tc.topic and f"vc_id:{vc_id}" in tc.topic:
                return tc
        except Exception:
            continue
    return None


def build_room_embed(member: discord.Member, vc: discord.VoiceChannel):
    return discord.Embed(
        title="🎛️ Управление твоей комнатой",
        description=(
            f"Привет, {member.mention}! Это твоя личная комната: {vc.mention}\n\n"
            "🔒 **Закрыть/Открыть** — пускать ли новых людей\n"
            "👁 **Скрыть/Показать** — виден ли канал в списке\n"
            "✏️ **Название** — переименовать комнату\n"
            "👥 **Лимит** — слоты (0 = без лимита)\n"
            "🔇 **Мут всех** — заглушить/разглушить гостей\n"
            "👢 **Кик** — выгнать человека из комнаты\n"
            "👑 **Передать** — отдать комнату другому\n"
            "🗑 **Удалить** — удалить комнату\n\n"
            "⚠️ *Кнопки работают только у владельца комнаты.*"
        ),
        color=discord.Color.blue(),
    )


class PrivateVoiceControlView(discord.ui.View):
    """Меню комнаты. Жмут все, но управлять может ТОЛЬКО владелец."""

    def __init__(self, voice_channel_id: int, owner_id: int):
        super().__init__(timeout=None)
        self.vc_id = voice_channel_id
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "❌ Это не твоя комната! Управлять ею может только владелец.",
                ephemeral=True,
            )
            return False
        vc = get_temp_vc(interaction.guild, self.vc_id)
        if vc is None:
            await interaction.response.send_message(
                "❌ Комната уже удалена.", ephemeral=True
            )
            return False
        return True

    # --- Ряд 1: доступ ---
    @discord.ui.button(label="Закрыть", style=discord.ButtonStyle.secondary, emoji="🔒", row=0, custom_id="room_lock")
    async def toggle_lock(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = get_temp_vc(interaction.guild, self.vc_id)
        ow = vc.overwrites_for(interaction.guild.default_role)
        if ow.connect is False:
            ow.connect = None
            button.label = "Закрыть"
            button.emoji = "🔒"
            msg = "🔓 Комната открыта — заходить могут все."
        else:
            ow.connect = False
            button.label = "Открыть"
            button.emoji = "🔓"
            msg = "🔒 Комната закрыта — новые люди зайти не смогут."
        await vc.set_permissions(interaction.guild.default_role, overwrite=ow)
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="Скрыть", style=discord.ButtonStyle.secondary, emoji="👁", row=0, custom_id="room_hide")
    async def toggle_hide(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = get_temp_vc(interaction.guild, self.vc_id)
        ow = vc.overwrites_for(interaction.guild.default_role)
        if ow.view_channel is False:
            ow.view_channel = None
            button.label = "Скрыть"
            msg = "👁 Комната снова видна всем."
        else:
            ow.view_channel = False
            button.label = "Показать"
            msg = "🙈 Комната скрыта из списка для всех остальных."
        await vc.set_permissions(interaction.guild.default_role, overwrite=ow)
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(msg, ephemeral=True)

    # --- Ряд 1: название/лимит ---
    @discord.ui.button(label="Название", style=discord.ButtonStyle.primary, emoji="✏️", row=0, custom_id="room_rename")
    async def rename_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VoiceRenameModal(self.vc_id))

    @discord.ui.button(label="Лимит", style=discord.ButtonStyle.primary, emoji="👥", row=0, custom_id="room_limit")
    async def limit_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VoiceLimitModal(self.vc_id))

    # --- Ряд 2: модерация ---
    @discord.ui.button(label="Мут всех", style=discord.ButtonStyle.danger, emoji="🔇", row=1, custom_id="room_mute")
    async def mute_all(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = get_temp_vc(interaction.guild, self.vc_id)
        guests = [m for m in vc.members if m.id != self.owner_id]
        if not guests:
            return await interaction.response.send_message("❌ В комнате нет гостей.", ephemeral=True)
        # если хоть один не замучен — мутим всех, иначе размучиваем
        need_mute = any(not m.voice.mute for m in guests if m.voice)
        for m in guests:
            try:
                await m.edit(mute=need_mute)
            except Exception:
                continue
        await interaction.response.send_message(
            "🔇 Все гости заглушены." if need_mute else "🔊 Все гости разглушены.",
            ephemeral=True,
        )

    @discord.ui.button(label="Кик", style=discord.ButtonStyle.danger, emoji="👢", row=1, custom_id="room_kick")
    async def kick_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = get_temp_vc(interaction.guild, self.vc_id)
        targets = [m for m in vc.members if m.id != self.owner_id]
        if not targets:
            return await interaction.response.send_message("❌ Некого кикать — ты один в комнате.", ephemeral=True)
        await interaction.response.send_message(
            "Выбери, кого выгнать из голосового (отключит от канала):",
            view=KickSelectView(self.vc_id, self.owner_id, list(vc.members)),
            ephemeral=True,
        )

    @discord.ui.button(label="Передать", style=discord.ButtonStyle.success, emoji="👑", row=1, custom_id="room_transfer")
    async def transfer_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = get_temp_vc(interaction.guild, self.vc_id)
        targets = [m for m in vc.members if m.id != self.owner_id]
        if not targets:
            return await interaction.response.send_message("❌ Некому передать — ты один в комнате.", ephemeral=True)
        await interaction.response.send_message(
            "Выбери нового владельца комнаты:",
            view=TransferSelectView(self.vc_id, self.owner_id, list(vc.members)),
            ephemeral=True,
        )

    @discord.ui.button(label="Удалить", style=discord.ButtonStyle.danger, emoji="🗑", row=1, custom_id="room_delete")
    async def delete_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = get_temp_vc(interaction.guild, self.vc_id)
        await interaction.response.send_message("🗑 Удаляю твою комнату...", ephemeral=True)
        try:
            tc = find_control_text(interaction.guild, self.vc_id)
            # выгоняем всех, потом удаляем
            for m in list(vc.members):
                try:
                    await m.move_to(None)
                except Exception:
                    pass
            if tc:
                try:
                    await tc.delete()
                except Exception:
                    pass
            await vc.delete()
        except Exception as e:
            await interaction.followup.send(f"❌ Ошибка: {e}", ephemeral=True)
        finally:
            temp_voice_owners.pop(self.vc_id, None)
            temp_voice_views.pop(self.vc_id, None)


class VoiceRenameModal(discord.ui.Modal):
    def __init__(self, vc_id: int):
        super().__init__(title="Новое название комнаты")
        self.vc_id = vc_id
        self.name_input = discord.ui.TextInput(
            label="Название (до 100 символов)",
            placeholder="Например: Чилим 🎧",
            max_length=100,
            required=True,
        )
        self.add_item(self.name_input)

    async def on_submit(self, interaction: discord.Interaction):
        # двойная проверка владельца (модалку можно вызвать только из меню владельца)
        view = temp_voice_views.get(self.vc_id)
        if view and interaction.user.id != view.owner_id:
            return await interaction.response.send_message("❌ Это не твоя комната!", ephemeral=True)
        vc = get_temp_vc(interaction.guild, self.vc_id)
        if vc is None:
            return await interaction.response.send_message("❌ Комната уже удалена.", ephemeral=True)
        try:
            await vc.edit(name=self.name_input.value.strip()[:100])
            await interaction.response.send_message(f"✅ Новое название: **{vc.name}**", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ У бота нет прав менять название.", ephemeral=True)


class VoiceLimitModal(discord.ui.Modal):
    def __init__(self, vc_id: int):
        super().__init__(title="Лимит комнаты")
        self.vc_id = vc_id
        self.limit_input = discord.ui.TextInput(
            label="Новый лимит (0-99, 0 = без лимита)",
            placeholder="Например: 5",
            max_length=2,
            required=True,
        )
        self.add_item(self.limit_input)

    async def on_submit(self, interaction: discord.Interaction):
        view = temp_voice_views.get(self.vc_id)
        if view and interaction.user.id != view.owner_id:
            return await interaction.response.send_message("❌ Это не твоя комната!", ephemeral=True)
        vc = get_temp_vc(interaction.guild, self.vc_id)
        if vc is None:
            return await interaction.response.send_message("❌ Комната уже удалена.", ephemeral=True)
        try:
            new_limit = int(self.limit_input.value.strip())
            if 0 <= new_limit <= 99:
                await vc.edit(user_limit=new_limit)
                await interaction.response.send_message(
                    f"✅ Лимит: **{new_limit if new_limit > 0 else 'без ограничений'}**",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message("❌ Введи число от 0 до 99.", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Введи корректное число.", ephemeral=True)


def _member_options(members, owner_id):
    opts = []
    for m in members:
        if m.id == owner_id:
            continue
        label = (m.display_name or m.name)[:100] or "Пользователь"
        try:
            desc = f"@{m.name}"[:100]
        except Exception:
            desc = None
        opts.append(discord.SelectOption(label=label, value=str(m.id), description=desc))
        if len(opts) >= 25:
            break
    if not opts:
        opts = [discord.SelectOption(label="В комнате никого нет", value="0")]
    return opts


class KickSelectView(discord.ui.View):
    def __init__(self, vc_id: int, owner_id: int, members: list):
        super().__init__(timeout=60)
        self.vc_id = vc_id
        self.owner_id = owner_id
        self.select = discord.ui.Select(
            placeholder="Выбери человека для кика...",
            min_values=1,
            max_values=1,
            options=_member_options(members, owner_id),
        )
        self.select.callback = self.on_select
        self.add_item(self.select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Это не твоя комната!", ephemeral=True)
            return False
        return True

    async def on_select(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("❌ Это не твоя комната!", ephemeral=True)
        target_id = int(self.select.values[0])
        if target_id == 0:
            return await interaction.response.send_message("❌ Некого кикать.", ephemeral=True)
        member = interaction.guild.get_member(target_id)
        vc = get_temp_vc(interaction.guild, self.vc_id)
        if member is None or vc is None:
            return await interaction.response.send_message("❌ Человек уже вышел.", ephemeral=True)
        try:
            await member.move_to(None)
            await interaction.response.send_message(f"👢 {member.mention} выгнан из комнаты.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ У бота нет прав (нужно «Перемещать участников»).", ephemeral=True)


class TransferSelectView(discord.ui.View):
    def __init__(self, vc_id: int, owner_id: int, members: list):
        super().__init__(timeout=60)
        self.vc_id = vc_id
        self.owner_id = owner_id
        self.select = discord.ui.Select(
            placeholder="Выбери нового владельца...",
            min_values=1,
            max_values=1,
            options=_member_options(members, owner_id),
        )
        self.select.callback = self.on_select
        self.add_item(self.select)
        self._filled = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Это не твоя комната!", ephemeral=True)
            return False
        return True

    async def on_select(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("❌ Это не твоя комната!", ephemeral=True)
        new_id = int(self.select.values[0])
        new_owner = interaction.guild.get_member(new_id)
        vc = get_temp_vc(interaction.guild, self.vc_id)
        if new_owner is None or vc is None:
            return await interaction.response.send_message("❌ Человек уже вышел.", ephemeral=True)
        old_owner = interaction.guild.get_member(self.owner_id)
        try:
            # права на голосовой
            await vc.set_permissions(new_owner, manage_channels=True, move_members=True, mute_members=True, connect=True)
            if old_owner:
                await vc.set_permissions(old_owner, manage_channels=None, move_members=None, mute_members=None)
            # права на текстовый чат управления
            tc = find_control_text(interaction.guild, self.vc_id)
            if tc:
                await tc.set_permissions(new_owner, read_messages=True, send_messages=True, manage_messages=True)
                if old_owner:
                    await tc.set_permissions(old_owner, read_messages=False, send_messages=False)
            temp_voice_owners[self.vc_id] = new_id
            room_view = temp_voice_views.get(self.vc_id)
            if room_view:
                room_view.owner_id = new_id
            self.owner_id = new_id
            await interaction.response.send_message(f"👑 Теперь владелец комнаты — {new_owner.mention}!", ephemeral=True)
            if tc:
                try:
                    await tc.send(f"👑 Новый владелец комнаты — {new_owner.mention}!")
                except Exception:
                    pass
        except discord.Forbidden:
            await interaction.response.send_message("❌ У бота нет прав для передачи.", ephemeral=True)


# --- Меню выбора товаров и кнопка прайса / статистики ---
class ContractView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.select(
        placeholder="Выберите категорию...",
        options=[discord.SelectOption(label=c, value=c) for c in ALL_DATA.keys()],
    )
    async def select_cat(
            self, interaction: discord.Interaction, select: discord.ui.Select
    ):
        cat = select.values[0]
        view = discord.ui.View()

        select_items = discord.ui.Select(
            placeholder="Выберите элементы",
            min_values=1,
            max_values=len(ALL_DATA[cat]),
            options=[
                discord.SelectOption(label=item) for item in ALL_DATA[cat].keys()
            ],
        )

        async def items_callback(i: discord.Interaction):
            if cat == "Активация контракта":
                uid = i.user.id
                if uid not in bot.user_carts:
                    bot.user_carts[uid] = {"items": [], "total": 0}

                report_data = []
                total_sum = 0
                for item in select_items.values:
                    price = ALL_DATA[cat][item]["price"]
                    total_sum += price
                    report_data.append(f"{item} — 1 шт. (Сумма: {round(price, 2)})")

                bot.user_carts[uid]["items"] = report_data
                bot.user_carts[uid]["total"] = round(total_sum, 2)

                await i.response.send_message(
                    "✅ Активация выбрана! Теперь отправьте скриншот в чат.", ephemeral=True
                )
            else:
                await i.response.send_modal(
                    BatchQuantityModal(select_items.values)
                )

        select_items.callback = items_callback
        view.add_item(select_items)

        class BackButton(discord.ui.Button):

            def __init__(self):
                super().__init__(
                    label="⬅️ Назад", style=discord.ButtonStyle.danger
                )

            async def callback(self, i: discord.Interaction):
                await i.response.edit_message(
                    content="Выберите категорию контракта:", view=ContractView()
                )

        view.add_item(BackButton())

        await interaction.response.send_message(
            content=f"Категория: **{cat}**. Выберите элементы:",
            view=view,
            ephemeral=True,
        )

    @discord.ui.button(
        label="Прайс-лист", style=discord.ButtonStyle.primary, emoji="📜", row=1
    )
    async def show_prices(
            self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        embed = discord.Embed(
            title="📜 Актуальные цены на контракты", color=discord.Color.blue()
        )

        for cat_name, items in ALL_DATA.items():
            items_text = "\n".join(
                [f"{name} — **{data['price']}**" for name, data in items.items()]
            )
            embed.add_field(
                name=f"📁 {cat_name}", value=items_text, inline=False
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(
        label="Статистика", style=discord.ButtonStyle.secondary, emoji="📊", row=1
    )
    async def show_stats_button(
            self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.defer(ephemeral=True)

        stats = {}
        channels_to_check = ["заявки-отчеты", "активация-контракта"]

        for ch_name in channels_to_check:
            chan = discord.utils.get(interaction.guild.text_channels, name=ch_name)
            if not chan:
                continue

            async for msg in chan.history(limit=200):
                if msg.embeds:
                    embed = msg.embeds[0]
                    employee_name = None
                    total_earned = 0.0

                    for field in embed.fields:
                        if field.name == "Сотрудник":
                            employee_name = field.value
                        elif "ИТОГО К ВЫПЛАТЕ" in field.name.upper():
                            try:
                                clean_val = field.value.replace("*", "").replace(" ", "").replace(",", ".")
                                total_earned = float(clean_val)
                            except ValueError:
                                pass

                    if employee_name:
                        if employee_name not in stats:
                            stats[employee_name] = {"count": 0, "total_earned": 0.0}

                        stats[employee_name]["count"] += 1
                        stats[employee_name]["total_earned"] += total_earned

        if not stats:
            return await interaction.followup.send(
                "📊 В каналах отчетов пока нет записей.", ephemeral=True
            )

        sorted_stats = sorted(stats.items(), key=lambda x: x[1]["count"], reverse=True)

        embed = discord.Embed(
            title="📊 Статистика выполнения контрактов",
            description="Автоматический подсчет по всем отчетам в каналах:",
            color=discord.Color.blue()
        )

        desc_lines = []
        for i, (emp, data) in enumerate(sorted_stats[:10], start=1):
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"**{i}.**"
            desc_lines.append(
                f"{medal} {emp} — Отчетов: `{data['count']}` | Заработано: `{round(data['total_earned'], 2)}`"
            )

        embed.add_field(name="🏆 Топ сотрудников", value="\n".join(desc_lines), inline=False)
        embed.set_footer(
            text=f"Запросил: {interaction.user.display_name}",
            icon_url=interaction.user.avatar.url if interaction.user.avatar else None
        )

        await interaction.followup.send(embed=embed, ephemeral=True)


async def create_private_room(member: discord.Member, category: discord.CategoryChannel):
    """Создаёт личную голосовую + текстовый чат с меню. Возвращает (vc, tc)."""
    guild = member.guild
    channel_name = f"🔊 │ {member.display_name}"

    voice_overwrites = {
        guild.default_role: discord.PermissionOverwrite(connect=True, view_channel=True),
        member: discord.PermissionOverwrite(
            manage_channels=True, move_members=True, mute_members=True, connect=True
        ),
    }

    new_vc = await guild.create_voice_channel(
        name=channel_name,
        category=category,
        overwrites=voice_overwrites,
    )

    # ставим комнату под АФК, если есть
    try:
        afk_channel = discord.utils.get(category.voice_channels, name="Афк 🛌") or next(
            (vc for vc in category.voice_channels if "афк" in vc.name.lower()), None
        )
        if afk_channel:
            await new_vc.edit(position=afk_channel.position + 1)
    except Exception:
        pass

    text_overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        member: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_messages=True),
    }
    # ник может содержать запрещённые символы — чистим для имени канала
    safe_name = "".join(c.lower() if (c.isalnum() or c in "-_") else "-" for c in member.name)[:90] or str(member.id)

    new_tc = await guild.create_text_channel(
        name=f"чат-{safe_name}",
        category=category,
        overwrites=text_overwrites,
        topic=f"vc_id:{new_vc.id} owner_id:{member.id}",
    )

    room_view = PrivateVoiceControlView(new_vc.id, member.id)
    temp_voice_owners[new_vc.id] = member.id
    temp_voice_views[new_vc.id] = room_view

    await new_tc.send(embed=build_room_embed(member, new_vc), view=room_view)
    return new_vc, new_tc


@bot.event
async def on_voice_state_update(member, before, after):
    CREATOR_CHANNEL_NAMES = {"Создать голосовой чат", "➕ Создать комнату", "➕ создать комнату"}

    # учёт активности для баллов (всегда, даже если это канал-создатель)
    try:
        if not member.bot:
            track_voice_activity(member, before, after)
    except Exception as e:
        print(f"[activity track err]: {e}")

    try:
        # 1) Зашёл в канал-создатель -> выдаём личную комнату
        if after.channel and after.channel.name in CREATOR_CHANNEL_NAMES:
            category = after.channel.category
            if category is None:
                return
            guild = member.guild
            # защита от дублей: если у него уже есть живая комната — просто переносим туда
            for vc_id, owner_id in list(temp_voice_owners.items()):
                if owner_id == member.id:
                    vc = get_temp_vc(guild, vc_id)
                    if vc is not None:
                        try:
                            await member.move_to(vc)
                        except Exception:
                            pass
                        return
            try:
                new_vc, _ = await create_private_room(member, category)
            except discord.Forbidden:
                return
            try:
                await member.move_to(new_vc)
            except Exception as e:
                print(f"[Не удалось переместить {member}]: {e}")

        # 2) Вышел из комнаты
        if before.channel and before.channel != after.channel:
            vc_id = before.channel.id
            if vc_id in temp_voice_owners:
                # обновлённый список участников берём заново с сервера
                guild = member.guild
                vc = get_temp_vc(guild, vc_id)
                if vc is None:
                    temp_voice_owners.pop(vc_id, None)
                    temp_voice_views.pop(vc_id, None)
                    return
                if len(vc.members) == 0:
                    # пустая — удаляем голос + текст
                    try:
                        tc = find_control_text(guild, vc_id)
                        if tc:
                            try:
                                await tc.delete()
                            except Exception:
                                pass
                        await vc.delete()
                    except Exception as e:
                        print(f"[Ошибка удаления каналов]: {e}")
                    finally:
                        temp_voice_owners.pop(vc_id, None)
                        temp_voice_views.pop(vc_id, None)
                else:
                    # владелец вышел, а гости остались — передаём комнату старшему по времени
                    if temp_voice_owners.get(vc_id) == member.id:
                        new_owner = vc.members[0]
                        temp_voice_owners[vc_id] = new_owner.id
                        room_view = temp_voice_views.get(vc_id)
                        if room_view:
                            room_view.owner_id = new_owner.id
                        try:
                            await vc.set_permissions(
                                new_owner,
                                manage_channels=True, move_members=True, mute_members=True, connect=True,
                            )
                            tc = find_control_text(guild, vc_id)
                            if tc:
                                await tc.set_permissions(
                                    new_owner, read_messages=True, send_messages=True, manage_messages=True
                                )
                                try:
                                    await tc.send(f"👑 Владелец вышел. Новый владелец комнаты — {new_owner.mention}!")
                                except Exception:
                                    pass
                        except Exception as e:
                            print(f"[Ошибка передачи комнаты]: {e}")
    except Exception as e:
        print(f"[Ошибка в авто-комнатах]: {e}")


# --- Логика отправки отчета ---
@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    uid = message.author.id

    if uid in bot.user_carts and message.attachments:
        data = bot.user_carts[uid]

        is_activation = False
        for item_str in data["items"]:
            item_name = item_str.split(" — ")[0]
            if item_name in ALL_DATA.get("Активация контракта", {}):
                is_activation = True
                break

        channel_name = (
            "активация-контракта" if is_activation else "заявки-отчеты"
        )
        chan = discord.utils.get(message.guild.text_channels, name=channel_name)

        if chan:
            files = [await att.to_file() for att in message.attachments]

            embed_title = (
                "⚡ Заявка на активацию контракта"
                if is_activation
                else "📋 Новый отчет"
            )
            embed = discord.Embed(
                title=embed_title, color=discord.Color.gold()
            )
            embed.add_field(
                name="Сотрудник", value=message.author.mention, inline=False
            )
            embed.add_field(
                name="Элементы", value="\n".join(data["items"]), inline=False
            )
            embed.add_field(
                name="ИТОГО К ВЫПЛАТЕ", value=f"**{data['total']}**", inline=False
            )

            embed.set_image(url=f"attachment://{files[0].filename}")

            await chan.send(embed=embed, files=files, view=ReportManagementView())

            await message.delete()
            await message.channel.send(
                "✅ Отчет со всеми скриншотами успешно отправлен!", delete_after=5
            )

            del bot.user_carts[uid]
        else:
            await message.channel.send(
                f"❌ Ошибка: Канал `{channel_name}` не найден на сервере!",
                delete_after=5,
            )

    await bot.process_commands(message)


@bot.event
async def on_command_error(ctx, error):
    # чтобы "не работает" было видно — показываем ошибку текстом
    try:
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"❌ Не хватает аргумента: `{error.param.name}`")
        elif isinstance(error, commands.BadArgument):
            await ctx.send(f"❌ Не понял аргумент. Пример: `!анкета #анкеты-база`")
        elif isinstance(error, commands.CommandNotFound):
            pass
        else:
            await ctx.send(f"❌ Ошибка команды: `{error}`")
            print(f"[command error {ctx.command}]: {error}")
    except Exception as e:
        print(f"[on_command_error fail]: {e}")


@bot.command(name="пинг")
async def ping_cmd(ctx):
    """Проверка что бот жив. Работает для всех, без прав."""
    await ctx.send(f"🏓 Понг! Я на связи. Твои роли: {', '.join(r.name for r in ctx.author.roles)}")


@bot.event
async def on_ready():
    print(f"Бот {bot.user} успешно запущен!")
    # persistent-кнопки анкеты (чтобы работали после рестарта)
    try:
        bot.add_view(AnketaPanelView())
        bot.add_view(AnketaManageView(static=""))
    except Exception as e:
        print(f"[add_view anketa]: {e}")
    if not check_contraband_reminders.is_running():
        check_contraband_reminders.start()
    if not auto_update_timers_message.is_running():
        auto_update_timers_message.start()
    # доски активности
    if not update_activity_boards.is_running():
        update_activity_boards.start()
    # подхватываем тех, кто уже сидит в войсе на момент рестарта
    try:
        now_ts = datetime.now(MSK).timestamp()
        for guild in bot.guilds:
            for vc in guild.voice_channels:
                for m in vc.members:
                    if m.bot:
                        continue
                    uid = str(m.id)
                    if uid not in voice_join_ts:
                        voice_join_ts[uid] = now_ts
                    ensure_activity_entry(uid, m.display_name)
    except Exception as e:
        print(f"[init voice activity]: {e}")


@bot.command(name="создатьгс")
async def создатьгс(ctx, *, channel_name: str = "Создать голосовой чат"):
    """Команда для админов: создаёт голосовой хаб «Зайди -> получишь свою комнату с меню».

    Как работает:
    1. Админ пишет !создатьгс (бот ставит хаб возле канала «Афк»)
    2. Игрок заходит в «Создать голосовой чат» -> бот создаёт ему комнату «🔊 │ Ник»
       + личный текст-чат с кнопками управления
    3. Кнопки жмёт только владелец комнаты, другие получают «Это не твоя комната!»
    """
    is_owner = ctx.author.id == OWNER_ID
    has_role = any(role.name in ["Админ", "Модератор"] for role in ctx.author.roles)

    if not (is_owner or has_role or ctx.author.guild_permissions.administrator):
        return await ctx.send("❌ У вас нет прав для использования этой команды!", delete_after=5)

    afk_channel = discord.utils.get(ctx.guild.voice_channels, name="Афк 🛌") or next(
        (vc for vc in ctx.guild.voice_channels if "афк" in vc.name.lower()), None)

    if not afk_channel or not afk_channel.category:
        return await ctx.send("❌ Не удалось найти голосовой канал «Афк» с привязанной категорией!", delete_after=5)

    category = afk_channel.category

    # хаб должен быть ВИДЕН всем — иначе никто в него не зайдёт
    overwrites = {
        ctx.guild.default_role: discord.PermissionOverwrite(view_channel=True, connect=True, speak=False)
    }

    try:
        exists = discord.utils.get(ctx.guild.voice_channels, name=channel_name)
        if exists:
            return await ctx.send(f"⚠️ Канал **{channel_name}** уже существует!", delete_after=5)
        new_vc = await ctx.guild.create_voice_channel(name=channel_name, category=category, overwrites=overwrites)
        await new_vc.edit(position=afk_channel.position + 1)

        await ctx.send(
            f"✅ Голосовой хаб создан: **{new_vc.mention}**\n"
            f"Зайди в него — бот выдаст тебе личную комнату с меню управления.",
            delete_after=15,
        )
        try:
            await ctx.message.delete()
        except Exception:
            pass

    except discord.Forbidden:
        await ctx.send("❌ У бота недостаточно прав! Дай ему «Управлять каналами» и «Перемещать участников».", delete_after=10)
    except Exception as e:
        await ctx.send(f"❌ Произошла ошибка: {e}", delete_after=5)


@bot.command(name="войс")
async def войс(ctx):
    """Показать твоё личное меню управления комнатой (только для владельца)."""
    # 1) ищем комнату, где ты владелец
    my_vc_id = None
    for vc_id, owner_id in temp_voice_owners.items():
        if owner_id == ctx.author.id:
            vc = get_temp_vc(ctx.guild, vc_id)
            if vc is not None:
                my_vc_id = vc_id
                break
    # 2) fallback: ты сидишь в комнате «🔊 │ ...» — проверяем, твоя ли она
    if my_vc_id is None and ctx.author.voice and ctx.author.voice.channel:
        vc = ctx.author.voice.channel
        if vc.id in temp_voice_owners and temp_voice_owners[vc.id] == ctx.author.id:
            my_vc_id = vc.id

    if my_vc_id is None:
        return await ctx.send(
            "❌ У тебя нет своей комнаты. Зайди в канал **«Создать голосовой чат»** — бот выдаст тебе комнату.",
            delete_after=10,
        )

    vc = get_temp_vc(ctx.guild, my_vc_id)
    view = temp_voice_views.get(my_vc_id)
    if view is None:
        view = PrivateVoiceControlView(my_vc_id, ctx.author.id)
        temp_voice_views[my_vc_id] = view
    await ctx.send(embed=build_room_embed(ctx.author, vc), view=view, delete_after=120)


@bot.command()
async def панель(ctx):
    is_owner = ctx.author.id == OWNER_ID
    has_role = any(
        role.name in ["Админ", "Модератор"] for role in ctx.author.roles
    )

    if (
            is_owner
            or has_role
            or ctx.author.guild_permissions.administrator
    ):
        await ctx.send("Выберите категорию контракта:", view=ContractView())
    else:
        await ctx.send(
            "❌ У вас нет прав для использования этой команды!", delete_after=5
        )


@bot.command()
async def выдатьроль(ctx, *, role_name: str):
    if ctx.author.id != OWNER_ID:
        return await ctx.send(
            "❌ У вас нет прав для выполнения этой команды!", delete_after=5
        )

    role = discord.utils.get(ctx.guild.roles, name=role_name)
    if not role:
        return await ctx.send(
            f"❌ Роль с названием **{role_name}** не найдена на сервере!",
            delete_after=5,
        )

    try:
        await ctx.author.add_roles(role)
        await ctx.send(
            f"✅ Роль **{role.name}** успешно выдана вам!", delete_after=5
        )
    except discord.Forbidden:
        await ctx.send(
            "❌ У бота недостаточно прав! Убедитесь, что роль бота в списке участников находится ВЫШЕ выдаваемой роли, и у бота есть право «Управление ролями».",
            delete_after=10,
        )


@bot.command()
async def тайники(ctx):
    global last_timer_message_id
    embed, view = generate_timers_embed_and_view()
    msg = await ctx.send(embed=embed, view=view)
    last_timer_message_id = msg.id


# --- База семьи по статикам (досье / выговоры / ЧС) ---
# На Bothost данные лежат в /app/data и surviving рестарт, локально - рядом с bot.py.
DATA_DIR = Path("/app/data") if Path("/app/data").exists() else Path(__file__).parent
FAMILY_DB_PATH = DATA_DIR / "family.json"
ANKETA_DB_PATH = DATA_DIR / "ankety.json"
ACTIVITY_DB_PATH = DATA_DIR / "activity.json"
ACTIVITY_META_PATH = DATA_DIR / "activity_meta.json"

# ===== НАСТРОЙКИ ПОД ТЕБЯ (меняй тут) =====
# Куда отправлять заполненные анкеты (ищем канал по совпадению имени, без учёта эмодзи/регистра)
ANKETA_TARGET_NAMES = ["анкеты", "досье", "заявки", "база"]  # например найдёт "📑・анкеты" или "заявки-досье"
# Каналы для досок активности (твои названия впиши сюда, поиск тоже по совпадению)
ACTIVITY_CHANNEL_NAMES = ["активность-сотрудников", "активность"]  # канал 📊・активность-сотрудников
CONTRACTS_CHANNEL_NAMES = ["контракты", "контракт"]  # канал 📑・контракты
# Курс и пороги
VOICE_SECONDS_PER_POINT = 3 * 3600  # 1 балл за 3 часа в войсе
POINTS_PER_HOUR = 1 / 3  # для совместимости (1 балл / 3 часа)
# (порог баллов, название, награда)
CONTRACT_LEVELS = [
    (50, "Контракт I", "повышение"),
    (100, "Контракт II", "повышение"),
    (150, "Контракт III", "повышение"),
    (250, "Контракт IV", "повышение"),
]
ACTIVE_MIN_HOURS = 4  # от скольки часов сотрудник считается 🟢 Активным
AUTO_BOARDS_ENABLED = False  # авто-рассылка досок в каналы ВЫКЛ — только по командам !активность / !контракты / !обновить-доски
# --- Баллы за контракты (начисляются автоматом при ✅ Принять) ---
# смысл: за каждую сданную единицу даём столько баллов
# пример: 750 железной руды * 0.06 = 45 баллов
CONTRACT_RATES_PATH = DATA_DIR / "contract_rates.json"
DEFAULT_CONTRACT_RATES = {
    "Дары Моря": 0.2,        # 100 рыб = 20 баллов
    "Металлургия": 0.06,     # 750 руды = 45 баллов
    "Поезд": 12.0,           # 1 коробка = 12 баллов
    "Ателье": 18.0,          # 1 закрытие = 18 баллов
    "Активация контракта": 25.0,  # базовая за активацию
    # точечно для активаций (если надо разные):
    "Активация:⚡ Металлургия": 30.0,
    "Активация:⚡ Поезд": 25.0,
    "Активация:⚡ Ателье": 20.0,
}
# =========================================


def load_contract_rates():
    try:
        if CONTRACT_RATES_PATH.exists():
            data = json.loads(CONTRACT_RATES_PATH.read_text(encoding="utf-8"))
            # подмешиваем дефолты чтобы новые категории не терялись
            merged = dict(DEFAULT_CONTRACT_RATES)
            merged.update(data)
            return merged
    except Exception as e:
        print(f"[Ошибка чтения contract_rates.json]: {e}")
    return dict(DEFAULT_CONTRACT_RATES)


def save_contract_rates(data):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        CONTRACT_RATES_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[Ошибка записи contract_rates.json]: {e}")


def get_rate_for_item(item_name: str, category: str) -> float:
    rates = load_contract_rates()
    if category == "Активация контракта":
        return float(rates.get(f"Активация:{item_name}", rates.get("Активация контракта", 25.0)))
    return float(rates.get(category, 0))


def find_category_for_item(item_name: str):
    for cat, items in ALL_DATA.items():
        if item_name in items:
            return cat
    return None


def calc_contract_points(item_lines: list) -> tuple:
    """Считает баллы по строкам 'Предмет — N шт. (Сумма: ...)'.
    Возвращает (total_points:int, details:str)."""
    total = 0.0
    det = []
    for line in item_lines:
        try:
            if " — " not in line:
                continue
            item_part, rest = line.split(" — ", 1)
            item_part = item_part.strip()
            qty = int(rest.strip().split()[0])
            cat = find_category_for_item(item_part)
            if not cat:
                continue
            rate = get_rate_for_item(item_part, cat)
            pts = qty * rate
            total += pts
            det.append(f"{item_part} x{qty} = {round(pts,1)}")
        except Exception:
            continue
    return int(round(total)), "; ".join(det)


def load_family():
    try:
        if FAMILY_DB_PATH.exists():
            return json.loads(FAMILY_DB_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[Ошибка чтения family.json]: {e}")
    return {}


def save_family(data):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        FAMILY_DB_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[Ошибка записи family.json]: {e}")


def is_officer(ctx):
    if ctx.author.id == OWNER_ID or ctx.author.guild_permissions.administrator:
        return True
    return any(r.name in ["Админ", "Модератор"] for r in ctx.author.roles)


@bot.command(name="добавить")
async def добавить(ctx, статик: str, nick: str = "Не указан", member: discord.Member = None, *, rank: str = "Новичок"):
    if not is_officer(ctx):
        return await ctx.send("❌ Только для Админ/Модератор.", delete_after=5)
    db = load_family()
    if статик in db and not db[статик].get("blacklist", False):
        return await ctx.send(f"⚠️ Статик `{статик}` уже в базе. Смотри `!досье {статик}`", delete_after=10)
    db[статик] = {
        "nick": nick,
        "discord_id": member.id if member else None,
        "discord_mention": member.mention if member else "—",
        "rank": rank,
        "warnings": [],
        "blacklist": False,
        "blacklist_reason": "",
        "added_by": ctx.author.mention,
        "added_at": datetime.now(MSK).strftime("%d.%m.%Y"),
    }
    save_family(db)
    await ctx.send(f"✅ Добавлен `{nick}` | статик `{статик}` | ранг `{rank}`")


@bot.command(name="досье")
async def досье(ctx, статик: str):
    db = load_family()
    if статик not in db:
        return await ctx.send(f"❌ Статик `{статик}` не найден. Добавь через `!добавить {статик} Ник_RP`", delete_after=10)
    d = db[статик]
    color = discord.Color.red() if d.get("blacklist") else discord.Color.blue()
    e = discord.Embed(title=f"📁 Досье: {d.get('nick')} | {статик}", color=color)
    e.add_field(name="Discord", value=d.get("discord_mention", "—"), inline=True)
    e.add_field(name="Ранг", value=d.get("rank", "—"), inline=True)
    e.add_field(name="Добавлен", value=f"{d.get('added_at','—')} ({d.get('added_by','—')})", inline=False)
    warns = d.get("warnings", [])
    e.add_field(name=f"⚠️ Выговоры ({len(warns)})", value="\n".join(f"{i+1}. {w}" for i, w in enumerate(warns[-5:])) or "Нет", inline=False)
    if d.get("blacklist"):
        e.add_field(name="⛔ В ЧС", value=d.get("blacklist_reason", "да"), inline=False)
    else:
        e.add_field(name="Статус", value="✅ Активен", inline=False)
    await ctx.send(embed=e)


@bot.command(name="выговор")
async def выговор(ctx, статик: str, *, причина: str):
    if not is_officer(ctx):
        return await ctx.send("❌ Только для Админ/Модератор.", delete_after=5)
    db = load_family()
    if статик not in db:
        return await ctx.send(f"❌ Статик `{статик}` не найден.", delete_after=5)
    db[статик].setdefault("warnings", []).append(f"{datetime.now(MSK).strftime('%d.%m')} — {причина} ({ctx.author.mention})")
    save_family(db)
    await ctx.send(f"⚠️ Выговор записан `{db[статик]['nick']}` ({статик}). Всего: {len(db[статик]['warnings'])}")


@bot.command(name="ранг")
async def ранг(ctx, статик: str, *, новый_ранг: str):
    if not is_officer(ctx):
        return await ctx.send("❌ Только для Админ/Модератор.", delete_after=5)
    db = load_family()
    if статик not in db:
        return await ctx.send(f"❌ Статик `{статик}` не найден.", delete_after=5)
    db[статик]["rank"] = новый_ранг
    save_family(db)
    await ctx.send(f"✅ `{db[статик]['nick']}` ({статик}) теперь `{новый_ранг}`")


@bot.command(name="чс")
async def чс(ctx, статик: str, *, причина: str = "без причины"):
    if not is_officer(ctx):
        return await ctx.send("❌ Только для Админ/Модератор.", delete_after=5)
    db = load_family()
    if статик not in db:
        db[статик] = {"nick": "Неизвестен", "discord_mention": "—", "rank": "—", "warnings": [], "added_by": ctx.author.mention, "added_at": datetime.now(MSK).strftime("%d.%m.%Y")}
    db[статик]["blacklist"] = True
    db[статик]["blacklist_reason"] = f"{причина} ({ctx.author.mention})"
    save_family(db)
    await ctx.send(f"⛔ Статик `{статик}` внесён в ЧС.")


@bot.command(name="снятьчс")
async def снятьчс(ctx, статик: str):
    if not is_officer(ctx):
        return await ctx.send("❌ Только для Админ/Модератор.", delete_after=5)
    db = load_family()
    if статик not in db:
        return await ctx.send(f"❌ Статик `{статик}` не найден.", delete_after=5)
    db[статик]["blacklist"] = False
    db[статик]["blacklist_reason"] = ""
    save_family(db)
    await ctx.send(f"✅ Статик `{статик}` убран из ЧС.")


@bot.command(name="состав")
async def состав(ctx):
    db = load_family()
    if not db:
        return await ctx.send("📋 База пуста. Добавь через `!добавить статик Ник`", delete_after=10)
    lines = []
    for s, d in sorted(db.items()):
        mark = "⛔" if d.get("blacklist") else "✅"
        lines.append(f"{mark} `{s}` — {d.get('nick')} | {d.get('rank')} | выг: {len(d.get('warnings', []))}")
    e = discord.Embed(title=f"📋 Состав семьи ({len(db)})", description="\n".join(lines[:30]), color=discord.Color.blue())
    if len(lines) > 30:
        e.set_footer(text=f"Показаны первые 30 из {len(lines)}")
    await ctx.send(embed=e)


# ============================================================
# --- АНКЕТЫ: база Имя/Фамилия/Телефон/Карта через кнопку ---
# ============================================================
def load_ankety():
    try:
        if ANKETA_DB_PATH.exists():
            return json.loads(ANKETA_DB_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[Ошибка чтения ankety.json]: {e}")
    return {}


def save_ankety(data):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        ANKETA_DB_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[Ошибка записи ankety.json]: {e}")


def find_channel_fuzzy(guild: discord.Guild, names: list):
    """Ищет текстовый канал по вхождению имени (игнорирует эмодзи/регистр/‐/_)."""
    import re

    def norm(s: str):
        s = s.lower()
        s = re.sub(r"[^a-zа-я0-9]+", "", s)
        return s

    norm_targets = [norm(n) for n in names]
    for ch in guild.text_channels:
        nc = norm(ch.name)
        for t in norm_targets:
            if t and t in nc:
                return ch
    return None


class AnketaModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Анкета сотрудника")
        self.static_input = discord.ui.TextInput(label="Статик", placeholder="Например: 12345", max_length=20, required=True)
        self.name_input = discord.ui.TextInput(label="Имя", placeholder="Например: Иван", max_length=50, required=True)
        self.surname_input = discord.ui.TextInput(label="Фамилия", placeholder="Например: Петров", max_length=50, required=True)
        self.phone_input = discord.ui.TextInput(label="Телефон", placeholder="Например: 79998887766", max_length=30, required=True)
        self.card_input = discord.ui.TextInput(label="Карта", placeholder="Номер карты / банка", max_length=50, required=True)
        self.add_item(self.static_input)
        self.add_item(self.name_input)
        self.add_item(self.surname_input)
        self.add_item(self.phone_input)
        self.add_item(self.card_input)

    async def on_submit(self, interaction: discord.Interaction):
        static = self.static_input.value.strip()
        first = self.name_input.value.strip()
        last = self.surname_input.value.strip()
        phone = self.phone_input.value.strip()
        card = self.card_input.value.strip()

        db = load_ankety()
        db[static] = {
            "static": static,
            "first_name": first,
            "last_name": last,
            "phone": phone,
            "card": card,
            "discord_id": interaction.user.id,
            "discord_mention": interaction.user.mention,
            "nick": interaction.user.display_name,
            "status": "на рассмотрении",
            "created_at": datetime.now(MSK).strftime("%d.%m.%Y %H:%M"),
        }
        save_ankety(db)

        # подтягиваем часы/баллы если уже есть активность
        ensure_activity_entry(str(interaction.user.id), interaction.user.display_name, static)

        target = get_anketa_target(interaction.guild)
        embed = discord.Embed(title="📝 Новая анкета", color=discord.Color.gold())
        embed.add_field(name="Статик", value=f"`{static}`", inline=True)
        embed.add_field(name="Discord", value=interaction.user.mention, inline=True)
        embed.add_field(name="Имя", value=first, inline=True)
        embed.add_field(name="Фамилия", value=last, inline=True)
        embed.add_field(name="Телефон", value=f"`{phone}`", inline=False)
        embed.add_field(name="Карта", value=f"`{card}`", inline=False)
        embed.set_footer(text=f"Заполнено: {db[static]['created_at']}")

        if target:
            await target.send(embed=embed)
            await interaction.response.send_message(
                f"✅ Анкета отправлена в канал {target.mention}! Ожидай проверки.", ephemeral=True
            )
        else:
            # если канал не найден — показываем админам прямо тут + подсказка
            await interaction.response.send_message(
                "✅ Анкета сохранена в базу, но канал для анкет не найден!\n"
                f"Создай канал со словом из списка {ANKETA_TARGET_NAMES} или поменяй ANKETA_TARGET_NAMES в bot.py",
                ephemeral=True,
            )
            try:
                await interaction.followup.send(embed=embed, ephemeral=True)
            except Exception:
                pass


class AnketaPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📝 Заполнить анкету", style=discord.ButtonStyle.primary, custom_id="anketa_open")
    async def open_anketa(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AnketaModal())


class AnketaManageView(discord.ui.View):
    def __init__(self, static: str):
        super().__init__(timeout=None)
        self.static = static

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == OWNER_ID or interaction.user.guild_permissions.administrator:
            return True
        if any(r.name in ["Админ", "Модератор"] for r in getattr(interaction.user, "roles", [])):
            return True
        await interaction.response.send_message("❌ Только для Админ/Модератор.", ephemeral=True)
        return False

    @discord.ui.button(label="✅ Принять", style=discord.ButtonStyle.green, custom_id="anketa_accept")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        static = self.static
        # если custom_id общий — пробуем достать статик из эмбеда
        if not static and interaction.message.embeds:
            for f in interaction.message.embeds[0].fields:
                if f.name == "Статик":
                    static = f.value.replace("`", "").strip()
                    break
        adb = load_ankety()
        if static in adb:
            adb[static]["status"] = f"✅ Принято ({interaction.user.mention})"
            save_ankety(adb)
            # автоматически добавляем в family.json чтобы !досье работало
            fdb = load_family()
            a = adb[static]
            if static not in fdb:
                fdb[static] = {
                    "nick": a.get("nick", f"{a.get('first_name','')} {a.get('last_name','')}"),
                    "discord_id": a.get("discord_id"),
                    "discord_mention": a.get("discord_mention", "—"),
                    "rank": "Новичок",
                    "warnings": [],
                    "blacklist": False,
                    "blacklist_reason": "",
                    "added_by": interaction.user.mention,
                    "added_at": datetime.now(MSK).strftime("%d.%m.%Y"),
                    "first_name": a.get("first_name", ""),
                    "last_name": a.get("last_name", ""),
                    "phone": a.get("phone", ""),
                    "card": a.get("card", ""),
                }
                save_family(fdb)
            else:
                fdb[static]["first_name"] = a.get("first_name", "")
                fdb[static]["last_name"] = a.get("last_name", "")
                fdb[static]["phone"] = a.get("phone", "")
                fdb[static]["card"] = a.get("card", "")
                save_family(fdb)
        embed = interaction.message.embeds[0] if interaction.message.embeds else None
        if embed:
            embed.color = discord.Color.green()
            embed.add_field(name="Статус", value=f"✅ Принято: {interaction.user.mention}", inline=False)
            await interaction.response.edit_message(embed=embed, view=None)
        else:
            await interaction.response.send_message(f"✅ Анкета `{static}` принята.", ephemeral=True)

    @discord.ui.button(label="❌ Отклонить", style=discord.ButtonStyle.red, custom_id="anketa_reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        static = self.static
        if not static and interaction.message.embeds:
            for f in interaction.message.embeds[0].fields:
                if f.name == "Статик":
                    static = f.value.replace("`", "").strip()
                    break
        adb = load_ankety()
        if static in adb:
            adb[static]["status"] = f"❌ Отклонено ({interaction.user.mention})"
            save_ankety(adb)
        embed = interaction.message.embeds[0] if interaction.message.embeds else None
        if embed:
            embed.color = discord.Color.red()
            embed.add_field(name="Статус", value=f"❌ Отклонено: {interaction.user.mention}", inline=False)
            await interaction.response.edit_message(embed=embed, view=None)
        else:
            await interaction.response.send_message(f"❌ Анкета `{static}` отклонена.", ephemeral=True)


@bot.command(name="анкета")
async def anketa_panel(ctx, target: discord.TextChannel = None):
    """Поставить кнопку-базу. Пример: !анкета #анкеты-база"""
    if not is_officer(ctx):
        roles = ", ".join(r.name for r in ctx.author.roles)
        return await ctx.send(
            f"❌ Только для Админ/Модератор.\nТвой ID: `{ctx.author.id}` (OWNER_ID в коде: `{OWNER_ID}`)\nТвои роли: {roles}\nДай себе роль **Админ** или поменяй OWNER_ID."
        )
    # если указали канал — запоминаем как "другой чат куда летят данные"
    if target is not None:
        meta = load_activity_meta()
        meta[f"{ctx.guild.id}_anketa_channel"] = target.id
        save_activity_meta(meta)
    dest = target or get_anketa_target(ctx.guild)
    dest_text = dest.mention if dest else f"не найден (создай канал со словом {ANKETA_TARGET_NAMES} или укажи: `!анкета #канал`)"
    e = discord.Embed(
        title="📝 База данных сотрудников",
        description=(
            "Нажми кнопку ниже и заполни:\n"
            "• **Статик**\n• **Имя**\n• **Фамилия**\n• **Телефон**\n• **Карта**\n\n"
            f"Данные сохранятся в базу и отправятся в чат: {dest_text}"
        ),
        color=discord.Color.blue(),
    )
    await ctx.send(embed=e, view=AnketaPanelView())
    # пример как это будет выглядеть в другом чате
    await ctx.send(embed=build_anketa_example_embed(dest.mention if dest else "—"))


@bot.command(name="анкета-куда")
async def anketa_where(ctx, target: discord.TextChannel):
    """Сменить чат для анкет без пересоздания кнопки. Пример: !анкета-куда #анкеты-база"""
    if not is_officer(ctx):
        return await ctx.send("❌ Только для Админ/Модератор.", delete_after=5)
    meta = load_activity_meta()
    meta[f"{ctx.guild.id}_anketa_channel"] = target.id
    save_activity_meta(meta)
    await ctx.send(f"✅ Теперь анкеты летят в {target.mention}")
    await ctx.send(embed=build_anketa_example_embed(target.mention))


@bot.command(name="анкеты")
async def ankety_list(ctx):
    if not is_officer(ctx):
        return await ctx.send("❌ Только для Админ/Модератор.", delete_after=5)
    db = load_ankety()
    if not db:
        return await ctx.send("📋 Анкет пока нет.", delete_after=10)
    lines = []
    for i, (s, a) in enumerate(sorted(db.items()), start=1):
        lines.append(
            f"**{i}.** `{s}` — {a.get('first_name','?')} {a.get('last_name','?')} | ☎ `{a.get('phone','—')}` | 💳 `{a.get('card','—')}` | {a.get('discord_mention','—')} | {a.get('status','—')}"
        )
    view = SimplePagesView(f"📋 Анкеты ({len(lines)})", lines, per_page=10)
    await ctx.send(embed=view.make_embed(), view=view)


@bot.command(name="найти-анкету")
async def anketa_find(ctx, static: str):
    if not is_officer(ctx):
        return await ctx.send("❌ Только для Админ/Модератор.", delete_after=5)
    db = load_ankety()
    if static not in db:
        return await ctx.send(f"❌ Анкета со статиком `{static}` не найдена.", delete_after=10)
    a = db[static]
    e = discord.Embed(title=f"📁 Анкета: {a.get('first_name')} {a.get('last_name')} | {static}", color=discord.Color.blue())
    e.add_field(name="Discord", value=a.get("discord_mention", "—"), inline=True)
    e.add_field(name="Статус", value=a.get("status", "—"), inline=True)
    e.add_field(name="Имя", value=a.get("first_name", "—"), inline=True)
    e.add_field(name="Фамилия", value=a.get("last_name", "—"), inline=True)
    e.add_field(name="Телефон", value=f"`{a.get('phone','—')}`", inline=False)
    e.add_field(name="Карта", value=f"`{a.get('card','—')}`", inline=False)
    await ctx.send(embed=e)


# ============================================================
# --- АКТИВНОСТЬ / БАЛЛЫ / КОНТРАКТЫ ---
# ============================================================
voice_join_ts: dict = {}


def load_activity():
    try:
        if ACTIVITY_DB_PATH.exists():
            return json.loads(ACTIVITY_DB_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[Ошибка чтения activity.json]: {e}")
    return {}


def save_activity(data):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        ACTIVITY_DB_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[Ошибка записи activity.json]: {e}")


def load_activity_meta():
    try:
        if ACTIVITY_META_PATH.exists():
            return json.loads(ACTIVITY_META_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def save_activity_meta(data):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        ACTIVITY_META_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[Ошибка записи activity_meta.json]: {e}")


def ensure_activity_entry(discord_id: str, nick: str = "?", static: str = ""):
    db = load_activity()
    if discord_id not in db:
        db[discord_id] = {
            "nick": nick, "static": static, "discord_id": int(discord_id) if discord_id.isdigit() else None,
            "seconds": 0, "manual_hours": 0.0, "manual_points": 0, "contract_points": 0, "history": [],
        }
        save_activity(db)
    else:
        upd = False
        if nick and db[discord_id].get("nick") != nick:
            db[discord_id]["nick"] = nick
            upd = True
        if static and not db[discord_id].get("static"):
            db[discord_id]["static"] = static
            upd = True
        if upd:
            save_activity(db)
    return db.get(discord_id)


def entry_hours(entry: dict) -> float:
    return round(entry.get("seconds", 0) / 3600 + float(entry.get("manual_hours", 0)), 2)


def entry_voice_points(entry: dict) -> int:
    """Баллы только за войс: 1 балл за каждые 3 часа (точно, без ошибок округления)."""
    try:
        total_sec = int(entry.get("seconds", 0)) + int(float(entry.get("manual_hours", 0)) * 3600)
    except Exception:
        total_sec = int(entry.get("seconds", 0))
    return total_sec // VOICE_SECONDS_PER_POINT


def entry_points(entry: dict) -> int:
    return entry_voice_points(entry) + int(entry.get("manual_points", 0)) + int(entry.get("contract_points", 0))


def get_contract(points: int):
    """Возвращает (римская цифра или '—', полное название)."""
    cur_roman, cur_name = "—", "—"
    for need, name, _reward in sorted(CONTRACT_LEVELS):
        if points >= need:
            parts = name.split(maxsplit=1)
            cur_roman = parts[1] if len(parts) > 1 else name
            cur_name = name
    return cur_roman, cur_name


def get_next_contract(points: int):
    """Возвращает (название, надо, не_хватает) до следующего контракта. Если MAX — (None, None, 0)."""
    for need, name, _reward in sorted(CONTRACT_LEVELS):
        if points < need:
            return name, need, need - points
    return None, None, 0


def fmt_progress(points: int) -> str:
    nxt, need, miss = get_next_contract(points)
    if nxt is None:
        return "MAX 🏆"
    return f"до {nxt}: надо {need}, не хватает {miss}"


def find_activity_key(db: dict, ident: str):
    s = ident.strip()
    # по discord mention <@123> / id
    digits = "".join(c for c in s if c.isdigit())
    if digits and digits in db:
        return digits
    for k, v in db.items():
        if str(v.get("discord_id")) == digits and digits:
            return k
    # по статику
    if s in db:
        return s
    for k, v in db.items():
        if str(v.get("static", "")).lower() == s.lower():
            return k
        if str(v.get("nick", "")).lower() == s.lower():
            return k
    # частичное по нику
    for k, v in db.items():
        if s.lower() in str(v.get("nick", "")).lower():
            return k
    return None


def build_activity_embed():
    db = load_activity()
    rows = []
    for k, v in db.items():
        h = entry_hours(v)
        p = entry_points(v)
        roman, _name = get_contract(p)
        rows.append((v.get("nick", "?"), h, p, roman, v))
    rows.sort(key=lambda x: x[2], reverse=True)

    active = [r for r in rows if r[1] >= ACTIVE_MIN_HOURS]
    inactive = [r for r in rows if r[1] < ACTIVE_MIN_HOURS]

    e = discord.Embed(
        title="📊 АКТИВНОСТЬ ГС",
        description="╔════════════════════════════╗\n       📊 АКТИВНОСТЬ ГС\n╚════════════════════════════╝",
        color=discord.Color.green(),
    )
    if active:
        txt = "\n".join(f"{i+1}. {n} — {h} ч. — {p} баллов — {fmt_progress(p)}" for i, (n, h, p, _r, _v) in enumerate(active[:15]))
        e.add_field(name="🟢 АКТИВНЫЕ", value=txt, inline=False)
    else:
        e.add_field(name="🟢 АКТИВНЫЕ", value="Пока никого", inline=False)
    if inactive:
        txt2 = "\n".join(f"{i+1}. {n} — {h} ч. — {p} баллов — {fmt_progress(p)}" for i, (n, h, p, _r, _v) in enumerate(inactive[:15]))
        e.add_field(name="🔴 НЕАКТИВНЫЕ", value=txt2, inline=False)
    else:
        e.add_field(name="🔴 НЕАКТИВНЫЕ", value="—", inline=False)

    e.add_field(name="━━━━━━━━━━━━━━━━━━━━━━", value="📈 **СИСТЕМА ПОВЫШЕНИЙ**", inline=False)
    medals = ["🥉", "🥈", "🥇", "🏆"]
    for i, (need, name, reward) in enumerate(sorted(CONTRACT_LEVELS)):
        med = medals[i] if i < len(medals) else "•"
        e.add_field(name=f"{med} {name}", value=f"Требование: {need} баллов\nНаграда: {reward}", inline=True)
    e.set_footer(text=f"3 часа в войсе = 1 балл • Обновлено {datetime.now(MSK).strftime('%d.%m %H:%M')}")
    return e


def build_contracts_embed():
    db = load_activity()
    rows = []
    for k, v in db.items():
        h = entry_hours(v)
        p = entry_points(v)
        roman, _name = get_contract(p)
        status = "🟢 Активен" if h >= ACTIVE_MIN_HOURS else "🔴 Неактивен"
        rows.append((v.get("nick", "?"), h, p, roman, status))
    rows.sort(key=lambda x: x[2], reverse=True)

    e = discord.Embed(title="📑・контракты", description="Игрок • Часы • Баллы • Контракт • Надо / Не хватает • Статус", color=discord.Color.blue())
    if not rows:
        e.add_field(name="Таблица", value="Пока пусто. Зайдите в войс — часы начнут капать.", inline=False)
    else:
        lines = []
        for n, h, p, roman, st in rows[:15]:
            nxt, need, miss = get_next_contract(p)
            if nxt is None:
                prog = "MAX"
            else:
                prog = f"надо {need}, не хватает {miss}"
            lines.append(f"**{n}** | {h} ч. | {p} | {roman} | {prog} | {st}")
        e.add_field(name=f"Всего: {len(rows)}", value="\n".join(lines), inline=False)
    e.set_footer(text=f"Контракты: {' / '.join(f'{n}={need}' for need, n, _r in sorted(CONTRACT_LEVELS))}")
    return e


def get_anketa_target(guild: discord.Guild):
    """Куда слать анкеты: сначала явный выбор (!анкета #канал), потом поиск по имени."""
    try:
        meta = load_activity_meta()
        cid = meta.get(f"{guild.id}_anketa_channel")
        if cid:
            ch = guild.get_channel(int(cid))
            if isinstance(ch, discord.TextChannel):
                return ch
    except Exception:
        pass
    return find_channel_fuzzy(guild, ANKETA_TARGET_NAMES)


def build_anketa_example_embed(target_mention: str = "—"):
    e = discord.Embed(title="📝 Новая анкета (ПРИМЕР)", description="Так будет выглядеть запись в другом чате.", color=discord.Color.gold())
    e.add_field(name="Статик", value="`12345`", inline=True)
    e.add_field(name="Discord", value="@Nick_Name", inline=True)
    e.add_field(name="Имя", value="Иван", inline=True)
    e.add_field(name="Фамилия", value="Петров", inline=True)
    e.add_field(name="Телефон", value="`79998887766`", inline=False)
    e.add_field(name="Карта", value="`2200 0000 0000 0000`", inline=False)
    e.set_footer(text=f"Пойдёт в канал: {target_mention}")
    return e


def build_activity_rows(guild: discord.Guild):
    """Полный список: кто сколько был в войсе + кто вообще не заходил. Сортировка: сначала по часам."""
    db = load_activity()
    now_ts = datetime.now(MSK).timestamp()
    rows = []
    seen_ids = set()
    for m in guild.members:
        if m.bot:
            continue
        uid = str(m.id)
        seen_ids.add(uid)
        entry = db.get(uid, {})
        base_sec = int(entry.get("seconds", 0))
        # живая сессия: человек прямо сейчас в войсе — добавляем к показу
        if uid in voice_join_ts:
            try:
                base_sec += max(0, int(now_ts - voice_join_ts[uid]))
            except Exception:
                pass
        hours = round(base_sec / 3600 + float(entry.get("manual_hours", 0)), 2)
        # баллы считаем от тех же живых часов
        tmp = dict(entry)
        tmp["seconds"] = base_sec
        points = entry_points(tmp) if entry else 0
        roman, _n = get_contract(points)
        in_voice = m.voice is not None and m.voice.channel is not None
        was = hours > 0 or points > 0 or in_voice or (uid in db)
        # был ли хоть раз: если есть запись с секундами/часами/баллами — был
        ever = (base_sec >= 60) or float(entry.get("manual_hours", 0)) > 0 or int(entry.get("manual_points", 0)) != 0 or int(entry.get("contract_points", 0)) != 0 or in_voice
        rows.append({
            "display": m.display_name, "mention": m.mention, "id": uid,
            "hours": hours, "points": points, "roman": roman,
            "was": ever, "in_voice": in_voice,
        })
    # те кто вышел с сервера но есть в базе — тоже показываем в конце блока "был"
    for uid, entry in db.items():
        if uid in seen_ids:
            continue
        base_sec = int(entry.get("seconds", 0))
        hours = round(base_sec / 3600 + float(entry.get("manual_hours", 0)), 2)
        points = entry_points(entry)
        roman, _n = get_contract(points)
        rows.append({
            "display": entry.get("nick", f"id:{uid}"), "mention": entry.get("nick", f"id:{uid}"), "id": uid,
            "hours": hours, "points": points, "roman": roman,
            "was": True, "in_voice": False, "left": True,
        })
    # сортировка: был (по часам вниз) -> не заходил (по нику)
    was_rows = sorted([r for r in rows if r["was"]], key=lambda x: (-x["hours"], -x["points"], x["display"].lower()))
    never_rows = sorted([r for r in rows if not r["was"]], key=lambda x: x["display"].lower())
    return was_rows + never_rows


class ActivityPagesView(discord.ui.View):
    """Листалка активности: 10 человек на странице, стрелки ◀ ▶."""

    def __init__(self, guild: discord.Guild, per_page: int = 10):
        super().__init__(timeout=180)
        self.guild_id = guild.id
        self.per_page = per_page
        self.page = 0
        self.refresh_rows(guild)

    def refresh_rows(self, guild: discord.Guild):
        self.rows = build_activity_rows(guild)
        self.total_pages = max(1, (len(self.rows) + self.per_page - 1) // self.per_page)
        self.page = max(0, min(self.page, self.total_pages - 1))

    def make_embed(self) -> discord.Embed:
        start = self.page * self.per_page
        chunk = self.rows[start:start + self.per_page]
        was_count = sum(1 for r in self.rows if r["was"])
        never_count = len(self.rows) - was_count
        e = discord.Embed(
            title=f"📊 Активность войсов — стр. {self.page + 1}/{self.total_pages}",
            description=f"Был: **{was_count}** • Не заходил: **{never_count}** • Всего: **{len(self.rows)}**",
            color=discord.Color.green(),
        )
        if not chunk:
            e.add_field(name="Список", value="Пока пусто.", inline=False)
        else:
            lines = []
            for i, r in enumerate(chunk, start=start + 1):
                voice_mark = " 🎙️" if r.get("in_voice") else ""
                left_mark = " (вышел)" if r.get("left") else ""
                if r["was"]:
                    lines.append(
                        f"**{i}.** {r['display']}{left_mark}{voice_mark} — **{r['hours']} ч.** — **{r['points']}** баллов — {r['roman']} — {fmt_progress(r['points'])}"
                    )
                else:
                    lines.append(f"**{i}.** {r['display']} — 0 ч. — 🔴 не заходил")
            # режем по лимиту Discord (1024 на field)
            text = "\n".join(lines)
            if len(text) > 1000:
                text = text[:1000] + "…"
            e.add_field(name=f"👥 Люди ({start + 1}–{start + len(chunk)})", value=text, inline=False)
        e.add_field(name="━━━━━━━━━━━━━━━", value="📈 I=50 • II=100 • III=150 • IV=250", inline=False)
        e.set_footer(text=f"10 на странице • Листай стрелками • {datetime.now(MSK).strftime('%d.%m %H:%M')}")
        return e

    async def _update(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is not None and guild.id == self.guild_id:
            self.refresh_rows(guild)
        await interaction.response.edit_message(embed=self.make_embed(), view=self)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
        else:
            self.page = self.total_pages - 1
        await self._update(interaction)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page < self.total_pages - 1:
            self.page += 1
        else:
            self.page = 0
        await self._update(interaction)


class SimplePagesView(discord.ui.View):
    """Универсальная листалка по 10 строк: для !анкеты и !контракты."""

    def __init__(self, title: str, lines: list, per_page: int = 10):
        super().__init__(timeout=180)
        self.title = title
        self.lines = lines
        self.per_page = per_page
        self.page = 0
        self.total_pages = max(1, (len(lines) + per_page - 1) // per_page)

    def make_embed(self) -> discord.Embed:
        start = self.page * self.per_page
        chunk = self.lines[start:start + self.per_page]
        e = discord.Embed(title=f"{self.title} — стр. {self.page + 1}/{self.total_pages}", color=discord.Color.blue())
        text = "\n".join(chunk) if chunk else "Пока пусто."
        if len(text) > 4000:
            text = text[:4000] + "…"
        # Discord description лимит 4096 — ок, lines по 10 шт влезут
        e.description = text
        e.set_footer(text="10 на странице • Листай стрелками ◀ ▶")
        return e

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = self.total_pages - 1 if self.page <= 0 else self.page - 1
        await interaction.response.edit_message(embed=self.make_embed(), view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = 0 if self.page >= self.total_pages - 1 else self.page + 1
        await interaction.response.edit_message(embed=self.make_embed(), view=self)


def track_voice_activity(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    try:
        if before.channel == after.channel:
            return
        now = datetime.now(MSK).timestamp()
        uid = str(member.id)
        # вышел / перешёл — закрываем сессию
        if before.channel is not None and uid in voice_join_ts:
            delta = int(now - voice_join_ts.pop(uid, now))
            if delta < 0:
                delta = 0
            if delta > 12 * 3600:  # защита от висяков после рестарта
                delta = 0
            if delta >= 60:  # меньше минуты не считаем
                db = load_activity()
                if uid not in db:
                    db[uid] = {"nick": member.display_name, "static": "", "discord_id": member.id,
                               "seconds": 0, "manual_hours": 0.0, "manual_points": 0, "contract_points": 0, "history": []}
                db[uid]["seconds"] = int(db[uid].get("seconds", 0)) + delta
                db[uid]["nick"] = member.display_name
                save_activity(db)
        # зашёл / перешёл — открываем сессию
        if after.channel is not None:
            voice_join_ts[uid] = now
            ensure_activity_entry(uid, member.display_name)
    except Exception as ex:
        print(f"[track_voice_activity ошибка]: {ex}")


@tasks.loop(minutes=10)
async def update_activity_boards():
    try:
        # авто-доски выключены по умолчанию — шлём только вручную или если включили !автодоски вкл
        meta = load_activity_meta()
        auto_on = meta.get("auto_boards", AUTO_BOARDS_ENABLED)
        if not auto_on:
            return
        for guild in bot.guilds:
            ch_act = find_channel_fuzzy(guild, ACTIVITY_CHANNEL_NAMES)
            if ch_act:
                try:
                    msg = None
                    mid = meta.get(f"{guild.id}_activity")
                    if mid:
                        try:
                            msg = await ch_act.fetch_message(mid)
                        except Exception:
                            msg = None
                    if msg:
                        await msg.edit(embed=build_activity_embed())
                    else:
                        # ищем последнее сообщение бота
                        async for m in ch_act.history(limit=20):
                            if m.author == bot.user and m.embeds:
                                msg = m
                                break
                        if msg:
                            await msg.edit(embed=build_activity_embed())
                            meta[f"{guild.id}_activity"] = msg.id
                        else:
                            msg = await ch_act.send(embed=build_activity_embed())
                            meta[f"{guild.id}_activity"] = msg.id
                except Exception as ex:
                    print(f"[board activity err]: {ex}")
            ch_con = find_channel_fuzzy(guild, CONTRACTS_CHANNEL_NAMES)
            if ch_con:
                try:
                    msg = None
                    mid = meta.get(f"{guild.id}_contracts")
                    if mid:
                        try:
                            msg = await ch_con.fetch_message(mid)
                        except Exception:
                            msg = None
                    if msg:
                        await msg.edit(embed=build_contracts_embed())
                    else:
                        async for m in ch_con.history(limit=20):
                            if m.author == bot.user and m.embeds:
                                msg = m
                                break
                        if msg:
                            await msg.edit(embed=build_contracts_embed())
                            meta[f"{guild.id}_contracts"] = msg.id
                        else:
                            msg = await ch_con.send(embed=build_contracts_embed())
                            meta[f"{guild.id}_contracts"] = msg.id
                except Exception as ex:
                    print(f"[board contracts err]: {ex}")
        save_activity_meta(meta)
    except Exception as ex:
        print(f"[update_activity_boards]: {ex}")


@update_activity_boards.before_loop
async def before_activity_boards():
    await bot.wait_until_ready()


@bot.command(name="баллы")
async def add_points(ctx, ident: str, amount: int, *, причина: str = ""):
    """!баллы <статик/@юзер/ник> <+10 или -5> [причина] — ручное начисление."""
    if not is_officer(ctx):
        return await ctx.send("❌ Только для Админ/Модератор.", delete_after=5)
    db = load_activity()
    key = find_activity_key(db, ident)
    # если человека ещё нет в активности — создаём по @упоминанию
    if not key:
        try:
            member = await commands.MemberConverter().convert(ctx, ident)
            key = str(member.id)
            db[key] = {"nick": member.display_name, "static": "", "discord_id": member.id,
                       "seconds": 0, "manual_hours": 0.0, "manual_points": 0, "contract_points": 0, "history": []}
        except Exception:
            return await ctx.send(f"❌ Не нашёл `{ident}`. Он должен хоть раз зайти в войс или заполнить анкету.", delete_after=10)
    db[key]["manual_points"] = int(db[key].get("manual_points", 0)) + amount
    db[key].setdefault("history", []).append(
        f"{datetime.now(MSK).strftime('%d.%m %H:%M')} — {'+' if amount>=0 else ''}{amount} от {ctx.author.mention} {f'({причина})' if причина else ''}"
    )
    save_activity(db)
    total = entry_points(db[key])
    roman, cname = get_contract(total)
    await ctx.send(
        f"✅ {db[key].get('nick')} — {'+' if amount>=0 else ''}{amount} баллов (всего **{total}**, контракт **{roman}** — {fmt_progress(total)})"
    )


@bot.command(name="часы")
async def add_hours(ctx, ident: str, hours: float):
    """!часы <статик/@юзер/ник> <число> — добавить часов вручную."""
    if not is_officer(ctx):
        return await ctx.send("❌ Только для Админ/Модератор.", delete_after=5)
    db = load_activity()
    key = find_activity_key(db, ident)
    if not key:
        return await ctx.send(f"❌ Не нашёл `{ident}`.", delete_after=10)
    db[key]["manual_hours"] = round(float(db[key].get("manual_hours", 0)) + hours, 2)
    save_activity(db)
    await ctx.send(f"✅ {db[key].get('nick')} — +{hours} ч. (всего **{entry_hours(db[key])} ч.**, баллов **{entry_points(db[key])}**)")


@bot.command(name="привязать")
async def link_static(ctx, ident: str, static: str):
    """!привязать <@юзер/ник> <статик> — привязать войс-статистику к статике."""
    if not is_officer(ctx):
        return await ctx.send("❌ Только для Админ/Модератор.", delete_after=5)
    db = load_activity()
    key = find_activity_key(db, ident)
    if not key:
        return await ctx.send(f"❌ Не нашёл `{ident}`.", delete_after=10)
    db[key]["static"] = static
    save_activity(db)
    await ctx.send(f"✅ {db[key].get('nick')} теперь привязан к статике `{static}`")


@bot.command(name="активность")
async def show_activity(ctx):
    """Кто сколько был в войсе + кто не заходил. 10 на странице, листать ◀ ▶."""
    view = ActivityPagesView(ctx.guild, per_page=10)
    await ctx.send(embed=view.make_embed(), view=view)


@bot.command(name="контракты")
async def show_contracts(ctx):
    db = load_activity()
    lines = []
    rows = []
    for k, v in db.items():
        h = entry_hours(v)
        p = entry_points(v)
        roman, _n = get_contract(p)
        rows.append((v.get("nick", "?"), h, p, roman))
    rows.sort(key=lambda x: x[2], reverse=True)
    for i, (n, h, p, roman) in enumerate(rows, start=1):
        lines.append(f"**{i}.** {n} | {h} ч. | {p} | {roman} | {fmt_progress(p)}")
    if not lines:
        lines = ["Пока пусто. Зайдите в войс — часы начнут капать."]
    view = SimplePagesView(f"📑 Контракты ({len(rows)})", lines, per_page=10)
    await ctx.send(embed=view.make_embed(), view=view)


@bot.command(name="стата")
async def my_stats(ctx, member: discord.Member = None):
    """Своя статистика: !стата (себе) или !стата @юзер. Работает для всех."""
    target = member or ctx.author
    # смотреть чужую могут все? да — это мотивация. Если надо только себе — убери проверку ниже.
    db = load_activity()
    uid = str(target.id)
    entry = db.get(uid)
    now_ts = datetime.now(MSK).timestamp()
    if entry:
        base_sec = int(entry.get("seconds", 0))
        if uid in voice_join_ts:
            try:
                base_sec += max(0, int(now_ts - voice_join_ts[uid]))
            except Exception:
                pass
        tmp = dict(entry)
        tmp["seconds"] = base_sec
        hours = round(base_sec / 3600 + float(entry.get("manual_hours", 0)), 2)
        voice_pts = entry_voice_points(tmp)
        manual_pts = int(entry.get("manual_points", 0))
        contract_pts = int(entry.get("contract_points", 0))
        total = voice_pts + manual_pts + contract_pts
        static = entry.get("static") or "—"
        hist = entry.get("history", [])[-5:]
    else:
        hours, voice_pts, manual_pts, contract_pts, total, static, hist = 0, 0, 0, 0, 0, "—", []
    roman, cname = get_contract(total)
    # место в топе
    ranked = sorted((entry_points(v) for v in db.values()), reverse=True)
    place = next((i + 1 for i, p in enumerate(ranked) if total >= p), len(ranked) + 1) if ranked else 1
    in_voice = target.voice is not None and target.voice.channel is not None
    e = discord.Embed(title=f"📊 Статистика: {target.display_name}", color=discord.Color.green())
    e.add_field(name="⏱ Часы в войсе", value=f"**{hours} ч.** (3 ч. = 1 балл){' 🎙️ сейчас в войсе' if in_voice else ''}", inline=False)
    e.add_field(name="⭐ Баллы", value=f"Всего **{total}** (войс {voice_pts} + контракты {contract_pts} + вручную {manual_pts})", inline=False)
    e.add_field(name="📜 Контракт", value=f"**{roman}** ({cname})", inline=True)
    e.add_field(name="🎯 Дальше", value=fmt_progress(total), inline=True)
    e.add_field(name="🏆 Место в топе", value=f"**{place}** из {max(len(ranked), 1)}", inline=True)
    e.add_field(name="🔑 Статик", value=f"`{static}`", inline=True)
    e.add_field(name="🕘 История", value="\n".join(hist) or "Пока пусто", inline=False)
    e.set_footer(text=f"Запросил {ctx.author.display_name} • {datetime.now(MSK).strftime('%d.%m %H:%M')}")
    await ctx.send(embed=e)


@bot.command(name="обновить-доски")
async def refresh_boards(ctx):
    """Создать/обновить сообщения в каналах активности и контрактов."""
    if not is_officer(ctx):
        return await ctx.send("❌ Только для Админ/Модератор.", delete_after=5)
    meta = load_activity_meta()
    ch_act = find_channel_fuzzy(ctx.guild, ACTIVITY_CHANNEL_NAMES)
    ch_con = find_channel_fuzzy(ctx.guild, CONTRACTS_CHANNEL_NAMES)
    if not ch_act and not ch_con:
        return await ctx.send(
            f"❌ Не нашёл каналы. Создай каналы со словами {ACTIVITY_CHANNEL_NAMES} и {CONTRACTS_CHANNEL_NAMES} "
            f"или поменяй списки в bot.py (ACTIVITY_CHANNEL_NAMES / CONTRACTS_CHANNEL_NAMES).",
            delete_after=15,
        )
    if ch_act:
        msg = await ch_act.send(embed=build_activity_embed())
        meta[f"{ctx.guild.id}_activity"] = msg.id
    if ch_con:
        msg2 = await ch_con.send(embed=build_contracts_embed())
        meta[f"{ctx.guild.id}_contracts"] = msg2.id
    save_activity_meta(meta)
    await ctx.send(f"✅ Доски обновлены: {ch_act.mention if ch_act else '—'} {ch_con.mention if ch_con else '—'}")


@bot.command(name="автодоски")
async def auto_boards(ctx, режим: str = ""):
    """!автодоски вкл / выкл — авто-рассылка досок в каналы (по умолчанию ВЫКЛ)."""
    if not is_officer(ctx):
        return await ctx.send("❌ Только для Админ/Модератор.", delete_after=5)
    meta = load_activity_meta()
    r = режим.lower().strip()
    if r in ("вкл", "on", "1", "да"):
        meta["auto_boards"] = True
        save_activity_meta(meta)
        return await ctx.send("✅ Авто-доски ВКЛ — бот будет сам обновлять каналы каждые 10 мин.")
    if r in ("выкл", "off", "0", "нет"):
        meta["auto_boards"] = False
        save_activity_meta(meta)
        return await ctx.send("✅ Авто-доски ВЫКЛ — бот больше сам ничего слать не будет. Только по `!активность` / `!контракты` / `!обновить-доски`.")
    cur = meta.get("auto_boards", AUTO_BOARDS_ENABLED)
    await ctx.send(f"ℹ️ Сейчас: **{'ВКЛ' if cur else 'ВЫКЛ'}**. Включить: `!автодоски вкл`, выключить: `!автодоски выкл`")


@bot.command(name="убрать-доски")
async def clear_boards(ctx):
    """Удалить сообщения досок бота из каналов активности/контрактов."""
    if not is_officer(ctx):
        return await ctx.send("❌ Только для Админ/Модератор.", delete_after=5)
    meta = load_activity_meta()
    removed = 0
    for key in (f"{ctx.guild.id}_activity", f"{ctx.guild.id}_contracts"):
        mid = meta.pop(key, None)
        if mid:
            for ch in ctx.guild.text_channels:
                try:
                    msg = await ch.fetch_message(mid)
                    if msg and msg.author == bot.user:
                        await msg.delete()
                        removed += 1
                        break
                except Exception:
                    continue
    # подчищаем последние сообщения бота в этих каналах
    for names in (ACTIVITY_CHANNEL_NAMES, CONTRACTS_CHANNEL_NAMES):
        ch = find_channel_fuzzy(ctx.guild, names)
        if ch:
            try:
                async for m in ch.history(limit=10):
                    if m.author == bot.user and m.embeds:
                        try:
                            await m.delete()
                            removed += 1
                        except Exception:
                            pass
                        break
            except Exception:
                pass
    save_activity_meta(meta)
    # и сразу выключаем авто-рассылку чтобы не прислал заново
    meta = load_activity_meta()
    meta["auto_boards"] = False
    save_activity_meta(meta)
    await ctx.send(f"✅ Убрал сообщений: {removed}. Авто-доски теперь ВЫКЛ.")


@bot.command(name="сброс-сезона")
async def reset_season(ctx):
    """Обнулить часы и баллы всем (начать сезон заново)."""
    if ctx.author.id != OWNER_ID and not ctx.author.guild_permissions.administrator:
        return await ctx.send("❌ Только для владельца/администратора.", delete_after=5)
    save_activity({})
    voice_join_ts.clear()
    # сразу перерегистрируем тех кто сейчас в войсе
    for vc in ctx.guild.voice_channels:
        for m in vc.members:
            if not m.bot:
                ensure_activity_entry(str(m.id), m.display_name)
                voice_join_ts[str(m.id)] = datetime.now(MSK).timestamp()
    await ctx.send("✅ Сезон сброшен: часы и баллы обнулены.")


@bot.command(name="ставки")
async def show_rates(ctx):
    """Показать сколько баллов даётся за контракты."""
    rates = load_contract_rates()
    e = discord.Embed(title="💰 Баллы за контракты", description="Начисляются автоматом при ✅ Принять", color=discord.Color.gold())
    e.add_field(name="🐟 Дары Моря", value=f"`{rates.get('Дары Моря')}` за 1 шт.\n100 рыб = {int(100*float(rates.get('Дары Моря',0)))} баллов", inline=True)
    e.add_field(name="⛏️ Металлургия", value=f"`{rates.get('Металлургия')}` за 1 руду\n750 руды = {int(750*float(rates.get('Металлургия',0)))} баллов", inline=True)
    e.add_field(name="📦 Поезд", value=f"`{rates.get('Поезд')}` за коробку", inline=True)
    e.add_field(name="👕 Ателье", value=f"`{rates.get('Ателье')}` за закрытие", inline=True)
    e.add_field(name="⚡ Активация", value=f"база `{rates.get('Активация контракта')}`\nМеталлургия: `{rates.get('Активация:⚡ Металлургия')}`\nПоезд: `{rates.get('Активация:⚡ Поезд')}`\nАтелье: `{rates.get('Активация:⚡ Ателье')}`", inline=False)
    e.set_footer(text='Менять: !ставка "Дары Моря" 0.3  |  !ставка Металлургия 0.08')
    await ctx.send(embed=e)


@bot.command(name="ставка")
async def set_rate(ctx, категория: str, значение: float):
    """!ставка <категория> <число> — поменять курс. Пример: !ставка Металлургия 0.08"""
    if not is_officer(ctx):
        return await ctx.send("❌ Только для Админ/Модератор.", delete_after=5)
    rates = load_contract_rates()
    # ищем ключ без учёта регистра
    found = None
    for k in list(rates.keys()) + list(ALL_DATA.keys()):
        if k.lower() == категория.lower():
            found = k
            break
    key = found or категория
    rates[key] = float(значение)
    save_contract_rates(rates)
    await ctx.send(f"✅ Ставка `{key}` теперь `{значение}`. Проверь `!ставки`")


# --- Keep-alive для бесплатного Render (Web Service) ---
# Render Free умеет держать только Web Service (Worker - платный).
# Render требует, чтобы сервис слушал порт $PORT, иначе он не запустится.
# Поэтому поднимаем tiny HTTP-сервер в фоне, а бот работает как обычно.
class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("Bot is alive".encode("utf-8"))

    def log_message(self, format, *args):
        # чтобы не спамить в логи при каждом пинге UptimeRobot
        return


def start_keep_alive():
    port = int(os.getenv("PORT", "10000"))
    server = HTTPServer(("0.0.0.0", port), KeepAliveHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"Keep-alive server запущен на порту {port}")


if __name__ == "__main__":
    start_keep_alive()
    # Bothost даёт токен в DISCORD_BOT_TOKEN (или BOT_TOKEN), Render - в DISCORD_TOKEN.
    # Поддерживаем все варианты, чтобы работало везде.
    TOKEN = (
        os.getenv("DISCORD_BOT_TOKEN")
        or os.getenv("DISCORD_TOKEN")
        or os.getenv("BOT_TOKEN")
    )
    if not TOKEN:
        raise ValueError(
            "Нет токена! Добавь DISCORD_TOKEN в Render -> Environment Variables, "
            "а на Bothost укажи токен в поле Bot Token (он придёт как DISCORD_BOT_TOKEN). "
            "Локально можно создать .env или выполнить set DISCORD_TOKEN=xxx"
        )
    bot.run(TOKEN)