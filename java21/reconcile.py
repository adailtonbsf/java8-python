#!/usr/bin/env python3
"""
reconcile.py — Aplica o template correto do MinIO sobre o diretório do servidor.

Executa no startup de cada servidor (antes do Java). Lê as variáveis de ambiente
injetadas pelo Pterodactyl para saber qual template e versão baixar.

Modos de overlay suportados (definidos no manifest.yml do template):
  replace        — Apaga o diretório destino e copia do template
  replace_jars   — Remove apenas os .jar do destino; preserva subpastas de dados
  merge          — Arquivos do template sobrescrevem destino; arquivos extras mantidos
  template       — Renderiza arquivo .j2 (Jinja2) com variáveis de ambiente
  copy_if_missing — Só copia se o destino não existir
  preserve       — Nunca toca (prioridade absoluta)
"""

import os
import sys
import json
import shutil
import subprocess
import tarfile
from pathlib import Path

try:
    import yaml
except ImportError:
    try:
        # Fallback: ruamel.yaml (já presente na imagem Docker)
        from ruamel.yaml import YAML as _YAML
        import types, sys as _sys
        _ryaml = _YAML()
        _ryaml.preserve_quotes = True
        yaml = types.ModuleType("yaml")
        yaml.safe_load = lambda s: _ryaml.load(s)
        _sys.modules["yaml"] = yaml
    except ImportError:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "pyyaml", "-q",
             "--break-system-packages"],
            check=True
        )
        import yaml

# ---------------------------------------------------------------------------
# Configuração via variáveis de ambiente (injetadas pelo Pterodactyl)
# ---------------------------------------------------------------------------
TEMPLATE_NAME    = os.getenv("TEMPLATE_NAME", "survival")
TARGET_VERSION   = os.getenv("TEMPLATE_VERSION", "1.0.0")
MINIO_BUCKET     = os.getenv("MINIO_BUCKET", "artifacts")
SERVER_DIR       = Path(os.getenv("SERVER_DIR", "."))
MANIFEST_FILE    = SERVER_DIR / ".deploy-manifest"
LOCK_FILE        = SERVER_DIR / ".deploy-lock"

# Variáveis disponíveis para renderização de templates .j2
TEMPLATE_VARS = {k: v for k, v in os.environ.items()}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def log(msg: str):
    print(f"[reconcile] {msg}", flush=True)


def get_current_version() -> str | None:
    if MANIFEST_FILE.exists():
        try:
            with open(MANIFEST_FILE) as f:
                return json.load(f).get("version")
        except Exception:
            return None
    return None


def write_manifest():
    with open(MANIFEST_FILE, "w") as f:
        json.dump({"template": TEMPLATE_NAME, "version": TARGET_VERSION}, f, indent=2)


def acquire_lock():
    if LOCK_FILE.exists():
        log("⚠️  Lock file encontrado — deploy anterior pode ter falhado. Prosseguindo...")
    LOCK_FILE.touch()


def release_lock():
    LOCK_FILE.unlink(missing_ok=True)


def download_artifact(dest: Path) -> Path:
    """Baixa o artefato do MinIO via rclone. Retorna o caminho do arquivo."""
    remote_path = f"minio:{MINIO_BUCKET}/{TEMPLATE_NAME}/{TEMPLATE_NAME}-{TARGET_VERSION}.tar.zst"
    log(f"📥 Baixando {remote_path} ...")

    result = subprocess.run(
        ["rclone", "copyto", remote_path, str(dest), "--progress"],
        capture_output=False
    )
    if result.returncode != 0:
        log(f"❌ Falha ao baixar artefato. Verifique:")
        log(f"   - Bucket: {MINIO_BUCKET}")
        log(f"   - Arquivo: {TEMPLATE_NAME}-{TARGET_VERSION}.tar.zst")
        log(f"   - Credenciais do MinIO nas variáveis de ambiente RCLONE_CONFIG_*")
        sys.exit(1)

    if not dest.exists():
        log(f"❌ Arquivo não encontrado após download: {dest}")
        sys.exit(1)

    log(f"✅ Download completo: {dest} ({dest.stat().st_size // 1024} KB)")
    return dest


def extract_artifact(archive: Path, extract_dir: Path):
    """Extrai o .tar.zst para um diretório temporário."""
    extract_dir.mkdir(parents=True, exist_ok=True)
    log(f"📦 Extraindo {archive.name} ...")

    # tarfile suporta zst a partir do Python 3.12; para versões anteriores, usamos zstd CLI
    try:
        import zstandard  # noqa
        has_zstd_lib = True
    except ImportError:
        has_zstd_lib = False

    if has_zstd_lib:
        import zstandard as zstd
        with open(archive, "rb") as fh:
            dctx = zstd.ZstdDecompressor()
            with dctx.stream_reader(fh) as reader:
                with tarfile.open(fileobj=reader, mode="r|") as tar:
                    tar.extractall(path=extract_dir)
    else:
        # Fallback: usa zstd + tar disponíveis no container
        result = subprocess.run(
            ["sh", "-c", f"zstd -d -c '{archive}' | tar -x -C '{extract_dir}'"],
            capture_output=False
        )
        if result.returncode != 0:
            log("❌ Falha na extração. Certifique-se que zstd está instalado na imagem.")
            sys.exit(1)

    log("✅ Extração concluída.")


def load_manifest(extract_dir: Path) -> dict:
    """Lê o manifest.yml do template extraído."""
    manifest_path = extract_dir / "manifest.yml"
    if not manifest_path.exists():
        log("⚠️  manifest.yml não encontrado no template. Usando modo 'merge' para tudo.")
        return {"files": [], "preserved": []}

    with open(manifest_path) as f:
        return yaml.safe_load(f) or {}


def is_preserved(rel_path: str, preserved_list: list[str]) -> bool:
    """Verifica se um caminho está na lista de preservados."""
    p = Path(rel_path)
    for pattern in preserved_list:
        pattern_path = Path(pattern.rstrip("/"))
        if p == pattern_path or str(p).startswith(str(pattern_path) + "/"):
            return True
    return False


def apply_replace(src_dir: Path, dest_dir: Path, preserved: list[str]):
    """Mode replace: apaga dest_dir e copia src_dir."""
    if dest_dir.exists():
        # Apaga apenas o que não está na lista de preservados
        for item in list(dest_dir.iterdir()):
            rel = item.relative_to(SERVER_DIR)
            if not is_preserved(str(rel), preserved):
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
    shutil.copytree(src_dir, dest_dir, dirs_exist_ok=True)


def apply_replace_jars(src_dir: Path, dest_dir: Path):
    """Mode replace_jars: remove só os .jar do destino, preserva subpastas."""
    if dest_dir.exists():
        for jar in dest_dir.glob("*.jar"):
            jar.unlink()
    dest_dir.mkdir(parents=True, exist_ok=True)
    for item in src_dir.iterdir():
        dest_item = dest_dir / item.name
        if item.is_file():
            shutil.copy2(item, dest_item)
        elif item.is_dir() and not dest_item.exists():
            shutil.copytree(item, dest_item)


def apply_merge(src_dir: Path, dest_dir: Path):
    """Mode merge: arquivos do template sobrescrevem; arquivos extras no destino são mantidos."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src_dir, dest_dir, dirs_exist_ok=True)


def apply_template(src_file: Path, dest_file: Path):
    """Mode template: renderiza arquivo .j2 com variáveis de ambiente."""
    try:
        from jinja2 import Environment, FileSystemLoader
        env = Environment(loader=FileSystemLoader(str(src_file.parent)))
        tmpl = env.get_template(src_file.name)
        rendered = tmpl.render(**TEMPLATE_VARS)
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        dest_file.write_text(rendered)
        log(f"   🔧 Template renderizado: {dest_file.relative_to(SERVER_DIR)}")
    except ImportError:
        log("⚠️  jinja2 não instalado. Copiando arquivo .j2 sem renderizar.")
        shutil.copy2(src_file, dest_file)


def apply_copy_if_missing(src: Path, dest: Path):
    """Mode copy_if_missing: só copia se o destino não existir."""
    if not dest.exists():
        if src.is_dir():
            shutil.copytree(src, dest)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
        log(f"   📋 Criado (não existia): {dest.relative_to(SERVER_DIR)}")
    else:
        log(f"   ⏭️  Preservado (já existe): {dest.relative_to(SERVER_DIR)}")


def apply_overlay(extract_dir: Path, manifest: dict):
    """Aplica o overlay do template sobre o diretório do servidor."""
    preserved = manifest.get("preserved", [])
    file_rules = manifest.get("files", [])

    # Se não há regras explícitas, faz merge de tudo (comportamento legado)
    if not file_rules:
        log("Sem regras de arquivo no manifest — aplicando merge completo...")
        for item in extract_dir.iterdir():
            if item.name in ("manifest.yml", ".deploy-manifest"):
                continue
            dest = SERVER_DIR / item.name
            if is_preserved(item.name, preserved):
                log(f"   🔒 Preservado: {item.name}")
                continue
            if item.is_dir():
                apply_merge(item, dest)
            else:
                shutil.copy2(item, dest)
        return

    for rule in file_rules:
        src_rel  = rule.get("path", "")
        dest_rel = rule.get("target", src_rel)
        mode     = rule.get("mode", "merge")

        src  = extract_dir / src_rel.rstrip("/")
        dest = SERVER_DIR  / dest_rel.rstrip("/")

        if not src.exists():
            log(f"   ⚠️  Origem não encontrada no template: {src_rel} — pulando")
            continue

        if is_preserved(dest_rel, preserved):
            log(f"   🔒 Preservado (lista de preservados): {dest_rel}")
            continue

        log(f"   [{mode}] {src_rel} → {dest_rel}")

        if mode == "replace":
            apply_replace(src, dest, preserved)
        elif mode == "replace_jars":
            apply_replace_jars(src, dest)
        elif mode == "merge":
            apply_merge(src, dest)
        elif mode == "template":
            # src pode ser um .j2 ou o arquivo sem extensão
            j2_src = src.with_suffix(src.suffix + ".j2") if not src.suffix == ".j2" else src
            if not j2_src.exists():
                j2_src = src
            apply_template(j2_src, dest)
        elif mode == "copy_if_missing":
            apply_copy_if_missing(src, dest)
        elif mode == "force_copy":
            if src.is_dir():
                shutil.copytree(src, dest, dirs_exist_ok=True)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
        elif mode == "preserve":
            log(f"   🔒 Preservado (modo 'preserve'): {dest_rel}")
        else:
            log(f"   ⚠️  Modo desconhecido '{mode}' — usando merge como fallback")
            apply_merge(src, dest)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def reconcile():
    current_version = get_current_version()

    if current_version == TARGET_VERSION:
        log(f"✅ Versão {current_version} já está aplicada. Iniciando servidor...")
        return

    log(f"🔄 Reconciliando: {current_version or 'nenhuma'} → {TARGET_VERSION}")
    log(f"   Template: {TEMPLATE_NAME}")

    acquire_lock()

    try:
        tmp_archive = Path(f"/tmp/{TEMPLATE_NAME}-{TARGET_VERSION}.tar.zst")
        tmp_extract = Path(f"/tmp/{TEMPLATE_NAME}-{TARGET_VERSION}-extracted")

        # Limpa extração anterior se existir
        if tmp_extract.exists():
            shutil.rmtree(tmp_extract)

        download_artifact(tmp_archive)
        extract_artifact(tmp_archive, tmp_extract)

        manifest = load_manifest(tmp_extract)
        log("📂 Aplicando overlay...")
        apply_overlay(tmp_extract, manifest)

        write_manifest()
        log(f"✨ Template {TEMPLATE_NAME}-{TARGET_VERSION} aplicado com sucesso!")

    except Exception as e:
        log(f"❌ Erro durante reconciliação: {e}")
        release_lock()
        sys.exit(1)

    finally:
        release_lock()
        # Limpa temporários
        tmp_archive.unlink(missing_ok=True)
        if tmp_extract.exists():
            shutil.rmtree(tmp_extract, ignore_errors=True)


if __name__ == "__main__":
    reconcile()
