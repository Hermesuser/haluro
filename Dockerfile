# syntax=docker/dockerfile:1
# Haluro — Laboratorio Analógico Digital
# Imagen de desarrollo y pruebas: solo backend (sin GUI nativa).
# Para ejecutar la app de escritorio completa, use los instaladores nativos
# (macOS .app / Windows .exe) empaquetados con PyInstaller.

FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HALURO_DATA_DIR=/data/haluro \
    HALURO_USE_SYSTEM_APPDATA=1

WORKDIR /app

# Dependencias del sistema para rawpy (LibRaw), Pillow y Flask
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libraw-dev \
        libjpeg-dev \
        zlib1g-dev \
        libtiff-dev \
        liblcms2-dev \
        libwebp-dev \
        libopenjp2-7-dev \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Dependencias de Python
COPY requirements.txt requirements-build.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && pip install -r requirements-build.txt

# Código de la aplicación
COPY . . .

# Puerto de la API local (loopback only)
EXPOSE 5050

# Directorio de datos persistente
VOLUME ["/data/haluro"]

# Salud: la API responde en /api/health
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -sf http://127.0.0.1:5050/api/health || exit 1

CMD ["python", "app.py"]
