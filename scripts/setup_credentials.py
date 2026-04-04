#!/usr/bin/env python3
"""
Interactive script to store per-user credentials in the encrypted credential store.

Usage:
    python scripts/setup_credentials.py
"""

import sys
import getpass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.credential_store import set_credential, get_credential, list_services


def main():
    print("=" * 52)
    print("  MyHealthAssistant — Configuração de Credenciais")
    print("=" * 52)
    print()

    user_id = input("User ID (ID do Telegram ou username): ").strip()
    if not user_id:
        print("ERRO: User ID não pode estar vazio.")
        sys.exit(1)

    print()
    print("Serviços disponíveis: tanita, garmin")
    service = input("Serviço a configurar: ").strip().lower()
    if service not in ("tanita", "garmin"):
        print(f"ERRO: Serviço '{service}' não reconhecido.")
        sys.exit(1)

    # Check if credentials already exist
    existing = get_credential(user_id, service)
    if existing:
        print(f"\n⚠️  Já existem credenciais para user={user_id!r} / service={service!r}.")
        overwrite = input("Substituir? (s/N): ").strip().lower()
        if overwrite != "s":
            print("Cancelado.")
            sys.exit(0)

    print()
    username = input("Email / Username: ").strip()
    password = getpass.getpass("Password (não aparece no ecrã): ")

    if not username or not password:
        print("ERRO: Email e password não podem estar vazios.")
        sys.exit(1)

    set_credential(user_id, service, username, password)

    print()
    print(f"✅  Credenciais guardadas para user={user_id!r} / service={service!r}.")
    print()

    # Show all stored services for this user
    services = list_services(user_id)
    print(f"Serviços configurados para o utilizador {user_id!r}: {', '.join(services)}")
    print()


if __name__ == "__main__":
    main()
