# Usamos la versión COMPLETA de Python (más pesada, pero 100% compatible)
FROM python:3.11

# 1. Instalar FFmpeg y Node.js directamente de los repositorios de Debian
# (Python 3.11 está basado en Debian Bookworm, que ya trae Node v18 nativo)
RUN apt-get update && \
    apt-get install -y ffmpeg nodejs git && \
    rm -rf /var/lib/apt/lists/*

# 2. Configurar directorio
WORKDIR /app

# 3. Copiar archivos
COPY . /app

# 4. Instalar librerías
RUN pip install --no-cache-dir -r requirements.txt

# 5. Instalar la última versión de yt-dlp desde GitHub (Corrección de errores diarios)
RUN pip install --force-reinstall https://github.com/yt-dlp/yt-dlp/archive/master.zip

# 6. Verificación: Imprimir versión de Node al construir (para verla en los logs)
RUN node -v

# 7. Iniciar
CMD ["python", "main.py"]