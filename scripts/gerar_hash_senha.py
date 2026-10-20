"""Gera hash administrativo PBKDF2 e imprime apenas o hash."""
import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from webapp.security import hash_password

password = getpass.getpass("Nova senha OPPES (12 caracteres ou mais): ")
confirmation = getpass.getpass("Confirme a senha: ")
if password != confirmation:
    raise SystemExit("As senhas não coincidem.")
print(hash_password(password))
