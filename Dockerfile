# Usamos Python 3.11 completo (Debian Bookworm) para máxima compatibilidad
FROM python:3.11

# 1. Instalar dependencias del sistema
# build-essential: Para compilar librerías de Python rápidas
# ffmpeg: Para procesar audio y carátulas
RUN apt-get update && \
    apt-get install -y ffmpeg build-essential git && \
    rm -rf /var/lib/apt/lists/*

# 2. Configurar directorio de trabajo
WORKDIR /app

# 3. Copiar archivos
COPY . /app

# 4. Instalar dependencias de Python
RUN pip install --no-cache-dir -r requirements.txt

# 5. Comando de inicio
CMD ["python", "main.py"]