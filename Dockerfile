# Usamos una imagen ligera de Python
FROM python:3.11-slim

# 1. Configurar e instalar dependencias del sistema + Node.js OFICIAL (v20)
RUN apt-get update && \
    apt-get install -y curl gnupg && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs ffmpeg git && \
    rm -rf /var/lib/apt/lists/*

# 2. Configurar directorio de trabajo
WORKDIR /app

# 3. Copiar archivos del proyecto
COPY . /app

# 4. Instalar dependencias de Python
RUN pip install --no-cache-dir -r requirements.txt

# 5. Forzar actualización de yt-dlp a la versión de desarrollo (Nightly)
# Esto es vital porque YouTube cambia sus códigos cada semana
RUN pip install --force-reinstall https://github.com/yt-dlp/yt-dlp/archive/master.zip

# 6. Comando de inicio
CMD ["python", "main.py"]