FROM ghcr.io/ptero-eggs/yolks:java_8

USER root

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-venv \
        python3-distutils \
        python3-pip \
        rclone \
        zstd \
        ca-certificates \
        git \
        rsync \
        netcat-openbsd \
    && pip3 install --no-cache-dir \
        ruamel.yaml \
        pyyaml \
        jinja2 \
        zstandard \
        minio \
    && rm -rf /var/lib/apt/lists/*

RUN id -u container >/dev/null 2>&1 || \
    useradd -m -d /home/container -s /bin/bash container

COPY reconcile.py /reconcile.py
RUN chmod +x /reconcile.py

USER container
ENV USER=container HOME=/home/container
WORKDIR /home/container
