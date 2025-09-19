import discord
from discord.ext import commands
import pytesseract
from PIL import Image
import io
import re
from config import ROLE_THRESHOLDS

ALLOWED_CHANNEL_ID = 123456789012345678  # <-- Wstaw tutaj swój ID kanału

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

def calculate_points(normal, hard, hell, abyss):
    return normal*1 + hard*2 + hell*3 + abyss*4

def extract_clears(text):
    normal = int(re.search(r'Normal\s+\d+\s+(\d+)', text).group(1))
    hard = int(re.search(r'Hard\s+\d+\s+(\d+)', text).group(1))
    hell = int(re.search(r'Hell\s+\d+\s+(\d+)', text).group(1))
    abyss = int(re.search(r'Abyss\s+\d+\s+(\d+)', text).group(1))
    return normal, hard, hell, abyss

async def assign_role(member, points):
    guild = member.guild
    new_role_id = None
    for threshold, role_id in reversed(ROLE_THRESHOLDS):
        if points >= threshold:
            new_role_id = role_id
            break
    if new_role_id:
        new_role = guild.get_role(new_role_id)
        # Usuń niższe rangi
        roles_to_remove = [guild.get_role(role_id) for _, role_id in ROLE_THRESHOLDS if role_id != new_role_id]
        await member.remove_roles(*filter(None, roles_to_remove))
        if new_role not in member.roles:
            await member.add_roles(new_role)

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
                img = Image.open(io.BytesIO(img_bytes))
                text = pytesseract.image_to_string(img, lang='eng')
                try:
                    normal, hard, hell, abyss = extract_clears(text)
                    points = calculate_points(normal, hard, hell, abyss)
                    await assign_role(message.author, points)
                    await message.channel.send(
                        f"{message.author.mention} u have {points} points! (N:{normal}, H:{hard}, He:{hell}, A:{abyss})"
                    )
                except Exception as e:
                    await message.channel.send("Error.")
    await bot.process_commands(message)

if __name__ == "__main__":
    import os
    TOKEN = os.getenv("DISCORD_TOKEN") or "MTQxODY5MTc4NDU2MDc0MjYxMQ.Gkrtnf.V1DJEfduKU9-MGYQ4AedgnCpprD58EaHn50Gpw"
    bot.run(TOKEN)
