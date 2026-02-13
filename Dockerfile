FROM python:3.11-slim

# 1. Instalar FFmpeg, Git, Node.js y Curl
RUN apt-get update && \
    apt-get install -y ffmpeg git nodejs curl && \
    rm -rf /var/lib/apt/lists/*

# 2. Configurar directorio
WORKDIR /app

# 3. Copiar archivos
COPY . /app

# 4. Instalar dependencias
RUN pip install --no-cache-dir -r requirements.txt

# 5. TRUCO DE INGENIERO: Forzar actualización a la versión "Nightly" de yt-dlp
# Esto arregla el error de "Signature solving" que ves en los logs
RUN pip install --force-reinstall https://github.com/yt-dlp/yt-dlp/archive/master.zip

# 6. Comando de inicio
CMD ["python", "main.py"]