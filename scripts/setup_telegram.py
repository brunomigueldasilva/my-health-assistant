#!/usr/bin/env python3
"""
Guarda o token do bot Telegram no credential store encriptado.

Este script deve ser executado UMA VEZ antes de iniciar o assistente pela
primeira vez. O token é encriptado com Fernet (AES-128-CBC + HMAC) e
guardado na base de dados SQLite — nunca em texto simples.

Uso:
    python scripts/setup_telegram.py

Pré-requisito: SECRET_KEY deve estar definido no .env.
Para gerar a chave (caso ainda não exista):
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

import sys
import getpass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.credential_store import get_telegram_token, set_telegram_token


def main():
    print("=" * 54)
    print("  MyHealthAssistant — Configuração do Token Telegram")
    print("=" * 54)
    print()
    print("Obtém o token no @BotFather do Telegram:")
    print("  1. Abre o Telegram e fala com @BotFather")
    print("  2. Envia /newbot (ou /mybots para um bot existente)")
    print("  3. Copia o token no formato  123456:ABC-DEF...")
    print()

    existing = get_telegram_token()
    if existing:
        preview = existing[:10] + "..." if len(existing) > 10 else existing
        print(f"⚠️  Já existe um token configurado: {preview}")
        overwrite = input("Substituir? (s/N): ").strip().lower()
        if overwrite != "s":
            print("Cancelado. Token existente mantido.")
            sys.exit(0)
        print()

    token = getpass.getpass("Token do bot (não aparece no ecrã): ").strip()

    if not token:
        print("ERRO: O token não pode estar vazio.")
        sys.exit(1)

    # Basic format check: "1234567890:AABBCCDDEEFFaabbccddeeff-1234567890"
    if ":" not in token or len(token) < 20:
        print("AVISO: O token não tem o formato esperado (123456:ABC...).")
        confirm = input("Continuar mesmo assim? (s/N): ").strip().lower()
        if confirm != "s":
            print("Cancelado.")
            sys.exit(1)

    set_telegram_token(token)

    preview = token[:10] + "..." if len(token) > 10 else token
    print()
    print(f"✅  Token guardado com segurança no credential store ({preview})")
    print()
    print("Próximos passos:")
    print("  python main.py                              # inicia o assistente")
    print("  /start no Telegram                          # cria o teu perfil")
    print()
    print("Serviços opcionais (configura depois de criar o perfil):")
    print("  python scripts/setup_credentials.py         # Tanita")
    print("  python scripts/garmin_browser_auth.py --user <id>  # Garmin")
    print()


if __name__ == "__main__":
    main()
