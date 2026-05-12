FROM ghcr.io/pterodactyl/yolks:java_21

USER root

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-venv \
        python3-pip \
        rclone \
        ca-certificates \
        git \
        rsync \
        netcat-openbsd \
    && pip3 install --break-system-packages --no-cache-dir ruamel.yaml \
    && rm -rf /var/lib/apt/lists/*

# Copia o script de sincronização
COPY reconcile.py /reconcile.py
RUN chmod +x /reconcile.py

USER container
ENV USER=container HOME=/home/container
WORKDIR /home/container
