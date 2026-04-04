#!/usr/bin/env python3
"""
Guarda credenciais de serviços externos no credential store encriptado.

Serviços suportados:
  telegram  — token do bot (obtido no @BotFather)
  tanita    — conta MyTanita (email + password)
  garmin    — ver nota abaixo

Nota Garmin: as credenciais Garmin não são guardadas aqui porque o Garmin
Connect bloqueia o login programático. Em vez disso usa autenticação OAuth
via browser:
  python scripts/garmin_browser_auth.py --user <user_id>

Uso:
    python scripts/setup_credentials.py
"""

import sys
import getpass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.credential_store import (
    set_credential,
    get_credential,
    list_services,
    set_telegram_token,
    get_telegram_token,
)

_SERVICES = ("telegram", "tanita")


def _setup_telegram():
    existing = get_telegram_token()
    if existing:
        preview = existing[:10] + "..." if len(existing) > 10 else existing
        print(f"\n⚠️  Já existe um token Telegram configurado: {preview}")
        overwrite = input("Substituir? (s/N): ").strip().lower()
        if overwrite != "s":
            print("Cancelado.")
            return

    print()
    print("Obtém o token no @BotFather do Telegram:")
    print("  /newbot  para criar um novo bot")
    print("  /mybots  para ver bots existentes")
    print()
    token = getpass.getpass("Token do bot (não aparece no ecrã): ").strip()
    if not token:
        print("ERRO: O token não pode estar vazio.")
        return

    set_telegram_token(token)
    preview = token[:10] + "..."
    print(f"\n✅  Token Telegram guardado ({preview})")


def _setup_tanita(user_id: str):
    existing = get_credential(user_id, "tanita")
    if existing:
        print(f"\n⚠️  Já existem credenciais Tanita para o utilizador {user_id!r}.")
        overwrite = input("Substituir? (s/N): ").strip().lower()
        if overwrite != "s":
            print("Cancelado.")
            return

    print()
    username = input("Email MyTanita: ").strip()
    password = getpass.getpass("Password (não aparece no ecrã): ")
    if not username or not password:
        print("ERRO: Email e password não podem estar vazios.")
        return

    set_credential(user_id, "tanita", username, password)
    print(f"\n✅  Credenciais Tanita guardadas para o utilizador {user_id!r}.")


def main():
    print("=" * 54)
    print("  MyHealthAssistant — Configuração de Credenciais")
    print("=" * 54)
    print()
    print("Serviços disponíveis:")
    print("  telegram  — token do bot (necessário antes de iniciar)")
    print("  tanita    — conta MyTanita (sincronização de composição corporal)")
    print("  garmin    — usa garmin_browser_auth.py (autenticação OAuth)")
    print()

    service = input("Serviço a configurar: ").strip().lower()
    if service not in _SERVICES:
        print(f"ERRO: Serviço '{service}' não reconhecido.")
        print(f"Opções: {', '.join(_SERVICES)}")
        sys.exit(1)

    if service == "telegram":
        _setup_telegram()
    else:
        user_id = input("\nUser ID (ID numérico do Telegram ou username): ").strip()
        if not user_id:
            print("ERRO: User ID não pode estar vazio.")
            sys.exit(1)
        _setup_tanita(user_id)

        print()
        services = list_services(user_id)
        print(f"Serviços configurados para {user_id!r}: {', '.join(services)}")

    print()


if __name__ == "__main__":
    main()
