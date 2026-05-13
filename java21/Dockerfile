FROM ghcr.io/pterodactyl/yolks:java_21

USER root

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-venv \
        python3-pip \
        rclone \
        zstd \
        ca-certificates \
        git \
        rsync \
        netcat-openbsd \
    && pip3 install --break-system-packages --no-cache-dir \
        ruamel.yaml \
        pyyaml \
        jinja2 \
        zstandard \
        minio \
    && rm -rf /var/lib/apt/lists/*

# reconcile.py vem de tools/ na raiz do repositório (build context = raiz)
COPY reconcile.py /reconcile.py
RUN chmod +x /reconcile.py

USER container
ENV USER=container HOME=/home/container
WORKDIR /home/container
