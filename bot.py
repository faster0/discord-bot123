from datetime import datetime, timezone, timedelta
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import discord
from discord.ext import commands, tasks

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

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
        embed.color = discord.Color.green()
        embed.add_field(
            name="Статус",
            value=f"✅ Одобрено: {interaction.user.mention}",
            inline=False,
        )

        await interaction.response.edit_message(embed=embed, view=self)

        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)

    @discord.ui.button(label="❌ Отклонить", style=discord.ButtonStyle.red)
    async def reject(
            self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        embed = interaction.message.embeds[0]
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


# --- Панель управления личным каналом ---
class PrivateVoiceControlView(discord.ui.View):
    def __init__(self, voice_channel: discord.VoiceChannel):
        super().__init__(timeout=None)
        self.voice_channel = voice_channel

    @discord.ui.button(label="🔒 Закрыть/Открыть", style=discord.ButtonStyle.secondary, emoji="🚪")
    async def toggle_lock(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user not in self.voice_channel.members:
            return await interaction.response.send_message("❌ Вы не находитесь в своем канале!", ephemeral=True)

        overwrite = self.voice_channel.overwrites_for(interaction.guild.default_role)
        if overwrite.connect is False:
            overwrite.connect = None
            await interaction.response.send_message("🔓 Канал снова открыт для всех.", ephemeral=True)
        else:
            overwrite.connect = False
            await interaction.response.send_message("🔒 Канал закрыт (никто новый не зайдет).", ephemeral=True)

        await self.voice_channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)

    @discord.ui.button(label="👥 Лимит", style=discord.ButtonStyle.primary, emoji="🔢")
    async def set_limit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user not in self.voice_channel.members:
            return await interaction.response.send_message("❌ Вы не находитесь в своем канале!", ephemeral=True)

        await interaction.response.send_modal(VoiceLimitModal(self.voice_channel))


class VoiceLimitModal(discord.ui.Modal):
    def __init__(self, channel: discord.VoiceChannel):
        super().__init__(title="Изменить лимит пользователей")
        self.channel = channel
        self.limit_input = discord.ui.TextInput(
            label="Новый лимит (0-99)", placeholder="Например: 5", max_length=2, required=True
        )
        self.add_item(self.limit_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            new_limit = int(self.limit_input.value)
            if 0 <= new_limit <= 99:
                await self.channel.edit(user_limit=new_limit)
                await interaction.response.send_message(
                    f"✅ Лимит канала изменен на: {new_limit if new_limit > 0 else 'без ограничений'}",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message("❌ Введите число от 0 до 99.", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Ошибка! Введите корректное число.", ephemeral=True)


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


@bot.event
async def on_voice_state_update(member, before, after):
    CREATOR_CHANNEL_NAME = "Создать голосовой чат"

    try:
        # Пользователь зашел в канал создания
        if after.channel and after.channel.name == CREATOR_CHANNEL_NAME:
            category = after.channel.category
            guild = member.guild

            channel_name = f"🔊 │ {member.display_name}"

            # Права для голосового канала
            voice_overwrites = {
                guild.default_role: discord.PermissionOverwrite(connect=True),
                member: discord.PermissionOverwrite(manage_channels=True, move_members=True, mute_members=True)
            }

            # 1. Создаем голосовой канал
            new_vc = await guild.create_voice_channel(
                name=channel_name,
                category=category,
                overwrites=voice_overwrites
            )

            # Ищем канал АФК в категории, чтобы поставить новую комнату ровно под него
            afk_channel = discord.utils.get(category.voice_channels, name="Афк 🛌") or next(
                (vc for vc in category.voice_channels if "афк" in vc.name.lower()), None)
            if afk_channel:
                try:
                    await new_vc.edit(position=afk_channel.position + 1)
                except Exception:
                    pass

            # 2. СРАЗУ перекидываем пользователя в его новую комнату
            await member.move_to(new_vc)

            # 3. Создаем личный текстовый чат для управления (с уникальной меткой ID в топике)
            text_overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                member: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_messages=True)
            }

            new_tc = await guild.create_text_channel(
                name=f"chat-{member.name.lower()}",
                category=category,
                overwrites=text_overwrites,
                topic=f"vc_id:{new_vc.id}"
            )

            # Отправляем панель управления в текстовый чат
            embed = discord.Embed(
                title="🎛️ Управление личным каналом",
                description=f"Привет, {member.mention}! Это твой личный текстовый чат.\nИспользуй кнопки ниже для управления голосовым каналом:",
                color=discord.Color.blue()
            )
            await new_tc.send(embed=embed, view=PrivateVoiceControlView(new_vc))

        # Автоматическое удаление пустых созданных каналов И их текстовых чатов
        if before.channel and before.channel != after.channel:
            if before.channel.name.startswith("🔊 │") and len(before.channel.members) == 0:
                try:
                    if before.channel.category:
                        for tc in before.channel.category.text_channels:
                            if tc.topic and f"vc_id:{before.channel.id}" in tc.topic:
                                await tc.delete()
                                break
                    await before.channel.delete()
                except Exception as e:
                    print(f"[Ошибка удаления каналов]: {e}")
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
async def on_ready():
    print(f"Бот {bot.user} успешно запущен!")
    if not check_contraband_reminders.is_running():
        check_contraband_reminders.start()
    if not auto_update_timers_message.is_running():
        auto_update_timers_message.start()


@bot.command()
async def создатьгс(ctx, *, channel_name: str = "Создать голосовой чат"):
    is_owner = ctx.author.id == OWNER_ID
    has_role = any(role.name in ["Админ", "Модератор"] for role in ctx.author.roles)

    if not (is_owner or has_role or ctx.author.guild_permissions.administrator):
        return await ctx.send("❌ У вас нет прав для использования этой команды!", delete_after=5)

    afk_channel = discord.utils.get(ctx.guild.voice_channels, name="Афк 🛌") or next(
        (vc for vc in ctx.guild.voice_channels if "афк" in vc.name.lower()), None)

    if not afk_channel or not afk_channel.category:
        return await ctx.send("❌ Не удалось найти голосовой канал «Афк» с привязанной категорией!", delete_after=5)

    category = afk_channel.category

    overwrites = {
        ctx.guild.default_role: discord.PermissionOverwrite(view_channel=False, connect=True, speak=False)
    }

    try:
        new_vc = await ctx.guild.create_voice_channel(name=channel_name, category=category, overwrites=overwrites)
        await new_vc.edit(position=afk_channel.position + 1)

        try:
            await ctx.message.delete()
        except Exception:
            pass

    except discord.Forbidden:
        await ctx.send("❌ У бота недостаточно прав для создания или настройки каналов!", delete_after=5)
    except Exception as e:
        await ctx.send(f"❌ Произошла ошибка: {e}", delete_after=5)


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
    TOKEN = os.getenv("DISCORD_TOKEN")
    if not TOKEN:
        raise ValueError(
            "Нет токена! Добавь DISCORD_TOKEN в Render -> Environment Variables. "
            "Локально можно создать .env или выполнить set DISCORD_TOKEN=xxx"
        )
    bot.run(TOKEN)