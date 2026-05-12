#!/usr/bin/env python3
import os
import subprocess
import json
import sys
from pathlib import Path

# Configurações via variáveis de ambiente do Pterodactyl
TEMPLATE_NAME = os.getenv("TEMPLATE_NAME", "survival")
TARGET_VERSION = os.getenv("TEMPLATE_VERSION", "1.0.0")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "artifacts")
MANIFEST_FILE = Path(".deploy-manifest")

def get_current_version():
    if MANIFEST_FILE.exists():
        try:
            with open(MANIFEST_FILE, "r") as f:
                data = json.load(f)
                return data.get("version")
        except:
            return None
    return None

def reconcile():
    current_version = get_current_version()
    
    if current_version == TARGET_VERSION:
        print(f"✅ Versão {current_version} já está atualizada. Iniciando...")
        return

    print(f"🔄 Atualizando de {current_version} para {TARGET_VERSION}...")
    
    artifact_path = f"minio/{MINIO_BUCKET}/{TEMPLATE_NAME}/{TEMPLATE_NAME}-{TARGET_VERSION}.tar.gz"
    local_archive = Path(f"/tmp/template.tar.gz")

    # 1. Download via rclone (usando config via env vars)
    print(f"📥 Baixando artefato: {artifact_path}")
    try:
        subprocess.run(["rclone", "copy", artifact_path, "/tmp/", "--progress"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Erro ao baixar artefato: {e}")
        sys.exit(1)

    # 2. Extração (Overlay)
    print("📂 Aplicando overlay...")
    try:
        # Extrai o conteúdo sobre o diretório atual
        # Em um script real, implementaríamos os modos 'replace'/'merge' aqui
        subprocess.run(["tar", "-xzf", str(local_archive), "-C", "."], check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Erro na extração: {e}")
        sys.exit(1)

    # 3. Atualiza manifesto local
    with open(MANIFEST_FILE, "w") as f:
        json.dump({"template": TEMPLATE_NAME, "version": TARGET_VERSION}, f)
    
    print(f"✨ Atualização para v{TARGET_VERSION} concluída com sucesso!")

if __name__ == "__main__":
    reconcile()
