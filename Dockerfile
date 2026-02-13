# Usamos una imagen ligera de Python (Linux)
FROM python:3.11-slim

# 1. Instalar FFmpeg y Git en el sistema Linux de la nube
RUN apt-get update && \
    apt-get install -y ffmpeg git && \
    rm -rf /var/lib/apt/lists/*

# 2. Configurar directorio de trabajo
WORKDIR /app

# 3. Copiar archivos del proyecto
COPY . /app

# 4. Instalar dependencias de Python
RUN pip install --no-cache-dir -r requirements.txt

# 5. Comando de inicio
CMD ["python", "main.py"]