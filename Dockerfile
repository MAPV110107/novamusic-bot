FROM python:3.11

RUN apt-get update && \
    apt-get install -y ffmpeg nodejs git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . /app

RUN pip install --no-cache-dir -r requirements.txt

RUN pip install --force-reinstall https://github.com/yt-dlp/yt-dlp/archive/master.zip

CMD ["python", "main.py"]