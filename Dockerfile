FROM python:3.12-slim

# Instalacja Tesseract i zależności
RUN apt-get update && \
    apt-get install -y tesseract-ocr libtesseract-dev libleptonica-dev && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Ustaw katalog roboczy
WORKDIR /app

# Skopiuj pliki projektu
COPY . .

# Instalacja zależności Pythona
RUN pip install --no-cache-dir -r requirements.txt

# Uruchom bota
CMD ["python", "bot.py"]
