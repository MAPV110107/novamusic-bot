# Usamos Python completo
FROM python:3.11

# 1. Instalar FFmpeg, Node.js y TOR 🧅
RUN apt-get update && \
    apt-get install -y ffmpeg nodejs git tor && \
    rm -rf /var/lib/apt/lists/*

# 2. Configurar directorio
WORKDIR /app

# 3. Copiar archivos
COPY . /app

# 4. Instalar dependencias Python
RUN pip install --no-cache-dir -r requirements.txt

# 5. Instalar yt-dlp nightly
RUN pip install --force-reinstall https://github.com/yt-dlp/yt-dlp/archive/master.zip

# 6. IMPORTANTE: Configurar el comando de inicio para arrancar Tor en segundo plano
# y luego iniciar el bot.
CMD service tor start && python main.py