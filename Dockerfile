FROM ghcr.io/ptero-eggs/yolks:java_8

USER root

RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 python3-venv python3-distutils python3-pip && \
    rm -rf /var/lib/apt/lists/*

USER container
ENV USER=container HOME=/home/container
WORKDIR /home/container
