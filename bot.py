import discord
from discord.ext import commands
import requests
import io
import re
from config import ROLE_THRESHOLDS
from PIL import Image

ALLOWED_CHANNEL_ID = 1418694785111429200  # <-- Wstaw tutaj swój ID kanału

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

def calculate_points(normal, hard, hell, abyss):
    return normal*1 + hard*2 + hell*3 + abyss*4

def extract_clears(text):
    # Możliwe tłumaczenia nagłówka 'Clears'
    clears_headers = [
        'clears', 'wyczyszczenia', 'czyszczenia', 'abschlüsse', '净化', 'очистки', 'limpiezas', 'nettoyages', 'pulizie', 'limpezas',
        '通关次数', 'クリア回数', '클리어', 'số lần vượt', 'abîme', 'abgrund', 'abismo', 'abisso', 'бездна', '深渊', 'アビス', '심연', 'vực thẳm'
    ]
    # Możliwe nazwy poziomów trudności
    difficulties = {
        'normal': ['normal', 'normale', 'normalny', 'обычный', '一般', 'ノーマル', '일반', 'thường'],
        'hard': ['hard', 'difficile', 'schwer', 'difícil', 'trudny', 'сложно', '困难', 'ハード', '어려움', 'khó'],
        'hell': ['hell', 'enfer', 'hölle', 'infierno', 'inferno', 'piekło', 'ад', '地狱', 'ヘル', '지옥', 'địa ngục'],
        'abyss': ['abyss', 'abîme', 'abgrund', 'abismo', 'abisso', 'bezna', 'бездна', '深渊', 'アビス', '심연', 'vực thẳm']
    }
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    clears_col = None
    header_line = None
    # Szukamy linii z nagłówkiem kolumn
    for i, line in enumerate(lines):
        for header in clears_headers:
            if header.lower() in line.lower():
                header_line = i
                headers = [h.strip().lower() for h in line.split()]
                for idx, h in enumerate(headers):
                    if any(header.lower() == h for header in clears_headers):
                        clears_col = idx
                        break
                break
        if clears_col is not None:
            break
    if header_line is None:
        return 0, 0, 0, 0  # Nie znaleziono nagłówka
    # Szukamy liczb pod kolumną 'Clears' dla każdego poziomu trudności
    results = {k: 0 for k in difficulties}
    for i in range(header_line+1, len(lines)):
        row = lines[i].split()
        if not row:
            continue
        for key, variants in difficulties.items():
            if any(row[0].lower() == v for v in variants):
                # Jeśli liczba kolumn >= 3, bierz ostatnią liczbę (Clears)
                if len(row) >= 3:
                    num_str = row[-1]
                # Jeśli tylko 2 kolumny, bierz drugą
                elif len(row) == 2:
                    num_str = row[1]
                else:
                    num_str = '0'
                try:
                    results[key] = int(''.join(filter(str.isdigit, num_str)))
                except:
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
                    normal, hard, hell, abyss = extract_clears(text)
                    points = calculate_points(normal, hard, hell, abyss)
                    await assign_role(message.author, points, message)
                    await message.channel.send(
                        f"{message.author.mention} u have {points} points! (N:{normal}, H:{hard}, He:{hell}, A:{abyss})"
                    )
                except Exception as e:
                    await message.channel.send("Error.")
    await bot.process_commands(message)

if __name__ == "__main__":
    import os
    TOKEN = os.getenv("DISCORD_TOKEN")
    bot.run(TOKEN)
