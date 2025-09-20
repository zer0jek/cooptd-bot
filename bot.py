import discord
from discord.ext import commands
import requests
import io
import re
import os
from config import ROLE_THRESHOLDS
from PIL import Image
# import openai  # Tymczasowo wyłączone

ALLOWED_CHANNEL_ID = 1418694785111429200  # <-- Wstaw tutaj swój ID kanału

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

def calculate_points(normal, hard, hell, abyss):
    return normal*1 + hard*2 + hell*3 + abyss*4

def extract_clears_ai(text, api_key):
    try:
        prompt = (
            "Oto tekst z tabeli gry (może być w różnych językach i z błędami OCR). "
            "Wyodrębnij liczbę 'Clears' (przechodzeń) dla poziomów: Normal, Hard, Hell, Abyss. "
            "Zwróć wynik w formacie: normal:<liczba>, hard:<liczba>, hell:<liczba>, abyss:<liczba>.\n\n"
            f"Tekst:\n{text}\n"
        )
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            api_key=api_key,
            messages=[{"role": "user", "content": prompt}]
        )
        content = response.choices[0].message.content
        import re
        normal = int(re.search(r'normal:(\d+)', content, re.I).group(1)) if re.search(r'normal:(\d+)', content, re.I) else 0
        hard = int(re.search(r'hard:(\d+)', content, re.I).group(1)) if re.search(r'hard:(\d+)', content, re.I) else 0
        hell = int(re.search(r'hell:(\d+)', content, re.I).group(1)) if re.search(r'hell:(\d+)', content, re.I) else 0
        abyss = int(re.search(r'abyss:(\d+)', content, re.I).group(1)) if re.search(r'abyss:(\d+)', content, re.I) else 0
        return normal, hard, hell, abyss
    except Exception as e:
        print(f"AI Error: {e}")
        return 0, 0, 0, 0

def extract_clears(text):
    # Tłumaczenia nagłówka 'Clears'
    clears_headers = [
        'clears', 'wyczyszczenia', 'czyszczenia', 'abschlüsse', '净化', 'очистки', 'limpiezas', 'nettoyages', 'pulizie', 'limpezas',
        '通关次数', 'クリア回数', '클리어', 'số lần vượt', '通關次數'
    ]
    # Tłumaczenia poziomów trudności
    difficulties = {
        'normal': ['normal', 'normale', 'normalny', 'обычный', '一般', 'ノーマル', '일반', 'thường'],
        'hard': ['hard', 'difficile', 'schwer', 'difícil', 'trudny', 'сложно', '困难', 'ハード', '어려움', 'khó'],
        'hell': ['hell', 'enfer', 'hölle', 'infierno', 'inferno', 'piekło', 'ад', '地狱', 'ヘル', '지옥', 'địa ngục'],
        'abyss': ['abyss', 'abîme', 'abgrund', 'abismo', 'abisso', 'bezna', 'бездна', '深渊', 'アビス', '심연', 'vực thẳm']
    }
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    header_idx = None
    # Znajdź linię z nagłówkiem
    for i, line in enumerate(lines):
        for header in clears_headers:
            if header.lower() in line.lower():
                header_idx = i
                break
        if header_idx is not None:
            break
    if header_idx is None:
        return 0, 0, 0, 0
    results = {k: 0 for k in difficulties}
    # Przeszukaj linie po nagłówku
    for line in lines[header_idx+1:]:
        for key, variants in difficulties.items():
            if any(variant in line.lower() for variant in variants):
                # Szukaj wszystkich liczb w linii
                numbers = re.findall(r'\d+', line)
                if numbers:
                    results[key] = int(numbers[-1])  # Ostatnia liczba to „Clears"
                else:
                    results[key] = 0
    return results['normal'], results['hard'], results['hell'], results['abyss']

def compress_image_to_max_size(image_bytes, max_size=1024*1024):
    img = Image.open(io.BytesIO(image_bytes))
    quality = 85
    width, height = img.size
    while True:
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=quality)
        data = buf.getvalue()
        if len(data) <= max_size or quality <= 30:
            return data
        # Zmniejsz jakość i rozmiar
        quality -= 10
        width = int(width * 0.9)
        height = int(height * 0.9)
        img = img.resize((width, height), Image.LANCZOS)

def ocr_space_file(image_bytes, api_key='K83214967188957'):
    payload = {'isOverlayRequired': False}
    files = {'file': ('image.png', image_bytes)}
    headers = {'apikey': api_key}
    response = requests.post('https://api.ocr.space/parse/image',
                             files=files,
                             data=payload,
                             headers=headers)
    result = response.json()
    if result.get('IsErroredOnProcessing'):
        error_msg = result.get('ErrorMessage', 'Unknown error')
        return '', error_msg
    if 'ParsedResults' in result:
        return result['ParsedResults'][0]['ParsedText'], None
    return '', 'No ParsedResults in response.'

async def assign_role(member, points, message=None):
    guild = member.guild
    new_role_id = None
    for threshold, role_id in reversed(ROLE_THRESHOLDS):
        if points >= threshold:
            new_role_id = role_id
            break
    if new_role_id:
        try:
            new_role = guild.get_role(new_role_id)
            # Usuń niższe rangi
            roles_to_remove = [guild.get_role(role_id) for _, role_id in ROLE_THRESHOLDS if role_id != new_role_id]
            await member.remove_roles(*filter(None, roles_to_remove))
            if new_role not in member.roles:
                await member.add_roles(new_role)
            if message:
                await message.channel.send(f"Przyznano rangę: {new_role.name}")
        except Exception as e:
            if message:
                await message.channel.send(f"Błąd przy nadawaniu rangi: {e}")
    else:
        if message:
            await message.channel.send("Nie przyznano żadnej rangi (za mało punktów lub brak odpowiedniej roli).")

@bot.event
async def on_message(message):
    if message.channel.id != ALLOWED_CHANNEL_ID:
        return
    if message.author.bot:
        return
    if message.attachments:
        for attachment in message.attachments:
            if attachment.content_type and attachment.content_type.startswith('image/'):
                img_bytes = await attachment.read()
                # Kompresja jeśli za duży
                if len(img_bytes) > 1024*1024:
                    img_bytes = compress_image_to_max_size(img_bytes)
                text, ocr_error = ocr_space_file(img_bytes, api_key='K83214967188957')
                if ocr_error:
                    await message.channel.send(f"OCR ERROR: {ocr_error}")
                else:
                    await message.channel.send("OCR OK!")
                    await message.channel.send(f"OCR TEXT:\n{text}")
                try:
                    api_key = os.getenv("OPENAI_API_KEY")
                    if not api_key:
                        await message.channel.send("Błąd: Brak klucza OpenAI API")
                        return
                    normal, hard, hell, abyss = extract_clears(text)  # Użyj starego parsera
                    points = calculate_points(normal, hard, hell, abyss)
                    await assign_role(message.author, points, message)
                    await message.channel.send(
                        f"{message.author.mention} u have {points} points! (N:{normal}, H:{hard}, He:{hell}, A:{abyss})"
                    )
                except Exception as e:
                    await message.channel.send(f"Error: {e}")
    await bot.process_commands(message)

if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_TOKEN")
    if not TOKEN:
        print("Błąd: Brak tokena Discord")
        exit(1)
    bot.run(TOKEN)
