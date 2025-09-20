
import os
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import re
import aiohttp
import base64
import json
import io
from PIL import Image
import pytesseract
import numpy as np
import google.generativeai as genai

# KONFIGURACJA - TOKEN BOTA POBIERANY Z ENV!
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Brak zmiennej środowiskowej DISCORD_BOT_TOKEN! Ustaw ją w panelu Railway (Variables > New Variable).")
OCR_API_KEY = "K83214967188957"  # Np. dla Tesseract lub innego API
CHANNEL_ID = 1418694785111429200 # ID kanału gdzie wysyłane są obrazy

# Konfiguracja ról - WYPEŁNIJ SWOIMI ID RÓL!
ROLES_CONFIG = {
    
    100: 1418695425401294909,  # Rola za 100 punktów
    500: 1418695450709594382,  # Rola za 250 punktów
    1000: 1418695474940219492,  # Rola za 500 punktów
    
}

# Wartości punktowe dla każdego trybu
POINT_VALUES = {
    "normal": 1,
    "hard": 2,
    "hell": 3,
    "abyss": 4
}

intents = discord.Intents.all()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)
tree = bot.tree

# Słownik do przechowywania ostatnich clears użytkowników
user_clears = {}

async def extract_text_from_image(image_url):
    """
    Funkcja do ekstrakcji tekstu z obrazu przy użyciu Tesseract OCR z preprocessingiem, bez zmniejszania rozdzielczości.
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(image_url) as img_response:
                img_bytes = await img_response.read()
                image = Image.open(io.BytesIO(img_bytes))
                # Minimalne zmniejszenie rozdzielczości tylko dla bardzo dużych obrazów
                max_width = 2000
                if image.width > max_width:
                    ratio = max_width / float(image.width)
                    new_height = int(float(image.height) * ratio)
                    image = image.resize((max_width, new_height), Image.LANCZOS)
                # Preprocessing: konwersja do odcieni szarości
                gray = image.convert('L')
                # Zwiększenie kontrastu
                from PIL import ImageEnhance
                enhancer = ImageEnhance.Contrast(gray)
                gray = enhancer.enhance(2.0)
                # Binarizacja (thresholding)
                np_img = np.array(gray)
                np_img = np.where(np_img > 160, 255, 0).astype(np.uint8)
                processed = Image.fromarray(np_img)
                # Rozpoznanie tekstu
                custom_config = r'--oem 3 --psm 6'
                loop = asyncio.get_event_loop()
                text = await loop.run_in_executor(None, pytesseract.image_to_string, processed, 'eng', custom_config)
                return text
    except Exception as e:
        print(f"Błąd podczas przetwarzania obrazu: {e}")
        return None

async def extract_text_from_image_ocr_space(image_url):
    try:
        api_url = "https://api.ocr.space/parse/image"
        payload = {
            'url': image_url,
            'apikey': OCR_API_KEY,
            'language': 'eng',
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, data=payload) as response:
                result = await response.json()
                if result.get('IsErroredOnProcessing', False):
                    print(f"OCR.space Error: {result.get('ErrorMessage', 'Unknown error')}")
                    return None
                parsed_results = result.get('ParsedResults', [])
                if parsed_results:
                    return parsed_results[0].get('ParsedText', '')
                return None
    except Exception as e:
        print(f"Błąd podczas przetwarzania obrazu przez OCR.space: {e}")
        return None

def parse_ocr_text(text):
    """
    Parsuje tekst OCR i wyciąga informacje o clears tylko z kolumny Difficulty i Clears
    """
    clears = {"normal": 0, "hard": 0, "hell": 0, "abyss": 0}
    if not text:
        return clears
    lines = text.split('\n')
    for line in lines:
        line_lower = line.lower()
        # Szukaj linii, które zawierają nazwę poziomu trudności i co najmniej jedną liczbę
        for diff in ["normal", "hard", "hell", "abyss"]:
            if diff in line_lower:
                # Wyciągnij wszystkie liczby z linii
                numbers = re.findall(r"\d+", line_lower)
                # Jeśli są co najmniej 2 liczby, clears to ostatnia liczba
                if len(numbers) >= 2:
                    clears[diff] = int(numbers[-1])
                # Jeśli jest tylko jedna liczba, clears to ta liczba
                elif len(numbers) == 1:
                    clears[diff] = int(numbers[0])
    return clears

def calculate_total_points(clears):
    """
    Oblicza całkowitą liczbę punktów na podstawie clears
    """
    total = 0
    for difficulty, count in clears.items():
        total += count * POINT_VALUES[difficulty]
    return total

def get_role_for_points(points):
    """
    Znajduje odpowiednią rolę na podstawie punktów
    """
    thresholds = sorted(ROLES_CONFIG.keys(), reverse=True)
    for threshold in thresholds:
        if points >= threshold:
            return ROLES_CONFIG[threshold], threshold
    return None, 0

def get_next_role_threshold(points):
    """
    Znajduje następny próg roli i ile punktów brakuje
    """
    thresholds = sorted(ROLES_CONFIG.keys())
    for threshold in thresholds:
        if points < threshold:
            return threshold, threshold - points
    return None, 0

async def remove_old_point_roles(member):
    """
    Usuwa wszystkie stare role punktowe użytkownika
    """
    point_role_ids = list(ROLES_CONFIG.values())
    for role in member.roles:
        if role.id in point_role_ids:
            try:
                await member.remove_roles(role)
                print(f"Usunięto rolę {role.name} dla {member.display_name}")
            except Exception as e:
                print(f"Błąd przy usuwaniu roli {role.name}: {e}")

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    print(f'Monitoring channel ID: {CHANNEL_ID}')
    try:
        await tree.sync()
        print("Komendy slash zsynchronizowane!")
        # Dodaj globalne uprawnienia do komend
        for command in tree.get_commands():
            print(f"Slash command loaded: /{command.name}")
    except Exception as e:
        print(f"Błąd synchronizacji komend: {e}")

@bot.event
async def on_message(message):
    if message.author.bot or message.channel.id != CHANNEL_ID:
        return

    # Obsługa wklejania tekstu clears
    if not message.attachments and any(diff in message.content.lower() for diff in ["normal", "hard", "hell", "abyss"]):
        clears = parse_ocr_text(message.content)
        total_points = calculate_total_points(clears)
        user_clears[message.author.id] = {
            'clears': clears,
            'points': total_points,
            'timestamp': message.created_at
        }
        await message.channel.send(f"✅ Zaktualizowano clears z tekstu: {clears}\nŁączne punkty: {total_points}")
        await bot.process_commands(message)
        return

    if message.attachments:
        for attachment in message.attachments:
            if any(attachment.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
                print(f"Obraz znaleziony od {message.author.display_name}")
                
                try:
                    loading_msg = await message.channel.send("🔍 Przetwarzanie obrazu...")
                    
                    ocr_text = await extract_text_from_image(attachment.url)
                    clears = None
                    if ocr_text:
                        clears = parse_ocr_text(ocr_text)
                    if not clears or all(v == 0 for v in clears.values()):
                        clears = await extract_clears_gemini(attachment.url)
                    if not clears or all(v == 0 for v in clears.values()):
                        ocr_text = await extract_text_from_image_ocr_space(attachment.url)
                        if ocr_text:
                            clears = parse_ocr_text(ocr_text)
                    if not clears or all(v == 0 for v in clears.values()):
                        await loading_msg.edit(content="❌ Nie udało się odczytać obrazu. Spróbuj ponownie z wyraźniejszym obrazem.")
                        await asyncio.sleep(10)
                        await loading_msg.delete()
                        return
                    
                    total_points = calculate_total_points(clears)
                    print(f"Łączne punkty: {total_points}")
                    
                    # Zapisz clears użytkownika
                    user_clears[message.author.id] = {
                        'clears': clears,
                        'points': total_points,
                        'timestamp': message.created_at
                    }
                    
                    role_id, threshold = get_role_for_points(total_points)
                    if not role_id:
                        await loading_msg.edit(content="❌ Za mało punktów na jakąkolwiek rolę.")
                        await asyncio.sleep(10)
                        await loading_msg.delete()
                        return
                    
                    role = message.guild.get_role(role_id)
                    if not role:
                        await loading_msg.edit(content="❌ Rola nie znaleziona. Skontaktuj się z administratorem.")
                        await asyncio.sleep(10)
                        await loading_msg.delete()
                        return
                    
                    await remove_old_point_roles(message.author)
                    await message.author.add_roles(role)
                    
                    next_threshold, points_needed = get_next_role_threshold(total_points)
                    
                    success_msg = f"""
✅ **Przetworzono pomyślnie!**

📊 **Twoje clears:**
• Normal: {clears['normal']}
• Hard: {clears['hard']} 
• Hell: {clears['hell']}
• Abyss: {clears['abyss']}

🏆 **Łączne punkty:** {total_points}
🎯 **Przyznana rola:** {role.name}

⭐ **Do następnej roli brakuje:** {points_needed} punktów
"""
                    await loading_msg.edit(content=success_msg)
                    
                    await asyncio.sleep(10)
                    await message.delete()
                    await asyncio.sleep(5)
                    await loading_msg.delete()
                    
                except Exception as e:
                    print(f"Błąd przetwarzania: {e}")
                    error_msg = await message.channel.send("❌ Wystąpił błąd podczas przetwarzania obrazu.")
                    await asyncio.sleep(10)
                    await error_msg.delete()
    
    await bot.process_commands(message)

@tree.command(name="clears", description="Pokazuje twoje ostatnie clears i postęp do następnej roli")
async def clears_command(interaction: discord.Interaction):
    user_id = interaction.user.id
    
    if user_id not in user_clears:
        await interaction.response.send_message("❌ Nie znaleziono twoich ostatnich clears. Wyślij najpierw obraz na kanale.", ephemeral=True)
        return
    
    data = user_clears[user_id]
    clears = data['clears']
    total_points = data['points']
    
    next_threshold, points_needed = get_next_role_threshold(total_points)
    role_id, current_threshold = get_role_for_points(total_points)
    current_role = interaction.guild.get_role(role_id).name if role_id else "Brak roli"
    
    next_role_name = "Osiągnięto maksymalną rolę!"
    if next_threshold:
        next_role_id = ROLES_CONFIG[next_threshold]
        next_role_name = interaction.guild.get_role(next_role_id).name
    
    embed = discord.Embed(
        title=f"📊 Twoje clears - {interaction.user.display_name}",
        color=discord.Color.blue()
    )
    
    embed.add_field(name="🎮 Normal Clears", value=f"`{clears['normal']}`", inline=True)
    embed.add_field(name="⚔️ Hard Clears", value=f"`{clears['hard']}`", inline=True)
    embed.add_field(name="🔥 Hell Clears", value=f"`{clears['hell']}`", inline=True)
    embed.add_field(name="💀 Abyss Clears", value=f"`{clears['abyss']}`", inline=True)
    embed.add_field(name="🏆 Łączne punkty", value=f"`{total_points}`", inline=True)
    embed.add_field(name="🎯 Aktualna rola", value=f"`{current_role}`", inline=True)
    
    if next_threshold:
        progress_percentage = (total_points / next_threshold) * 100
        embed.add_field(
            name=f"⭐ Do następnej roli ({next_role_name})",
            value=f"**Brakuje:** `{points_needed}` punktów\n**Postęp:** `{progress_percentage:.1f}%`",
            inline=False
        )
    else:
        embed.add_field(
            name="⭐ Osiągnięto maksimum!",
            value="Gratulacje! Masz już najwyższą możliwą rolę! 🎉",
            inline=False
        )
    
    embed.set_footer(text=f"Ostatnia aktualizacja: {data['timestamp'].strftime('%Y-%m-%d %H:%M')}")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="setchannel", description="Ustawia kanał do monitorowania obrazów (tylko właściciel serwera)")
async def setchannel_command(interaction: discord.Interaction, channel: discord.TextChannel):
    if interaction.user.id != interaction.guild.owner_id:
        await interaction.response.send_message("❌ Tylko właściciel serwera może ustawić kanał monitorowania!", ephemeral=True)
        return
    global CHANNEL_ID
    CHANNEL_ID = channel.id
    await interaction.response.send_message(f"✅ Ustawiono kanał monitorowania na: {channel.mention}", ephemeral=True)

@tree.command(name="points", description="Pokazuje twoje aktualne role punktowe")
async def points_command(interaction: discord.Interaction, user: discord.Member = None):
    target_user = user or interaction.user
    point_roles = [role for role in target_user.roles if role.id in ROLES_CONFIG.values()]
    
    if point_roles:
        role_list = "\n".join([f"• {role.name}" for role in point_roles])
        await interaction.response.send_message(
            f"**{target_user.display_name}** ma następujące role punktowe:\n{role_list}",
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            f"**{target_user.display_name}** nie ma żadnych ról punktowych.",
            ephemeral=True
        )

@tree.command(name="setclears", description="Ustaw clears ręcznie (tylko dla uprawnionych)")
@app_commands.describe(normal="Clears Normal", hard="Clears Hard", hell="Clears Hell", abyss="Clears Abyss")
async def setclears_command(interaction: discord.Interaction, normal: int, hard: int, hell: int, abyss: int):
    allowed_roles = set(ROLES_CONFIG.values())
    user_roles = set(role.id for role in interaction.user.roles)
    if not allowed_roles.intersection(user_roles):
        await interaction.response.send_message("❌ Nie masz uprawnień do tej komendy.", ephemeral=True)
        return
    clears = {"normal": normal, "hard": hard, "hell": hell, "abyss": abyss}
    total_points = calculate_total_points(clears)
    user_clears[interaction.user.id] = {
        'clears': clears,
        'points': total_points,
        'timestamp': interaction.created_at
    }
    await interaction.response.send_message(f"✅ Ustawiono clears: {clears}\nŁączne punkty: {total_points}", ephemeral=True)

GEMINI_API_KEY = "AIzaSyB7-dmw7UYp1PAEvRp0cNVFV3hKIUZe2gg"

async def extract_clears_gemini(image_url):
    try:
        # Pobierz obraz jako bytes
        async with aiohttp.ClientSession() as session:
            async with session.get(image_url) as img_response:
                img_bytes = await img_response.read()
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-pro-vision")
        prompt = (
            "Na tym obrazie znajduje się tabela z czterema poziomami trudności: Normal, Hard, Hell, Abyss. "
            "Dla każdego poziomu znajdź liczbę clears (ostatnia liczba w wierszu). "
            "Zwróć wynik jako JSON: {\"normal\": liczba, \"hard\": liczba, \"hell\": liczba, \"abyss\": liczba}"
        )
        response = model.generate_content([prompt, img_bytes], stream=False)
        import json as pyjson
        import re as pyre
        match = pyre.search(r'\{.*\}', response.text)
        if match:
            return pyjson.loads(match.group(0))
        return None
    except Exception as e:
        print(f"Błąd Gemini Vision: {e}")
        return None

if __name__ == "__main__":
    bot.run(BOT_TOKEN)
