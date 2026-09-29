FROM python:3.11-slim

# LibreOffice Writer converts .doc / .rtf / .odt to .docx on upload
RUN apt-get update && apt-get install -y --no-install-recommends libreoffice-writer default-jre-headless \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# bake the embedding model into the image so the server never needs the network for search
ENV CARDWIZARD_MODEL_CACHE=/srv/model_cache
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/srv/model_cache')"

COPY app app
COPY static static

ENV CARDWIZARD_DATA=/data
VOLUME /data
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
