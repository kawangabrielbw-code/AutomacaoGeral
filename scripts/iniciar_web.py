"""Inicia a interface protegida; a escuta de rede sempre exige HTTPS."""
from __future__ import annotations

import argparse
import os
import ssl
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def validate_tls_files(cert_path: str, key_path: str) -> tuple[Path, Path]:
    cert = Path(cert_path).expanduser().resolve()
    key = Path(key_path).expanduser().resolve()
    project_root = ROOT.resolve()
    if cert == key or project_root in cert.parents or project_root in key.parents:
        raise ValueError("Certificado e chave devem ser arquivos distintos, guardados fora do projeto.")
    if not cert.is_file() or not key.is_file():
        raise ValueError("Configure OPPES_TLS_CERT e OPPES_TLS_KEY com arquivos TLS existentes.")
    try:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile=str(cert), keyfile=str(key))
    except (OSError, ssl.SSLError, ValueError) as exc:
        raise ValueError("Certificado/chave TLS inválidos ou incompatíveis.") from exc
    return cert, key


def main(argv: Optional[list[str]] = None) -> int:
    # Os coletores e o histórico legado usam caminhos relativos ao projeto.
    # Normalize o diretório mesmo quando o launcher for chamado de outra pasta.
    os.chdir(ROOT)
    parser = argparse.ArgumentParser(description="Inicia a interface web OPPES.")
    parser.add_argument("--rede", action="store_true", help="Escuta em 0.0.0.0 com TLS obrigatório.")
    args = parser.parse_args(argv)
    from webapp.security import valid_hash
    if not valid_hash(os.environ.get("OPPES_ADMIN_PASSWORD_HASH", "")):
        parser.error("Defina OPPES_ADMIN_PASSWORD_HASH com o hash PBKDF2 gerado por scripts/gerar_hash_senha.py.")
    if len(os.environ.get("OPPES_SESSION_SECRET", "")) < 40:
        parser.error("Defina OPPES_SESSION_SECRET com pelo menos 40 caracteres aleatórios.")
    import uvicorn
    options = {"app": "webapp.main:app", "port": 8000, "log_level": "info", "workers": 1,
               "access_log": True, "reload": False}
    if args.rede:
        try:
            cert, key = validate_tls_files(os.environ.get("OPPES_TLS_CERT", ""),
                                           os.environ.get("OPPES_TLS_KEY", ""))
        except ValueError as exc:
            parser.error(str(exc))
        options.update({"host": "0.0.0.0", "ssl_certfile": str(cert), "ssl_keyfile": str(key)})
        print("Servidor HTTPS escutando em 0.0.0.0:8000; no navegador use https://IP-DO-SERVIDOR:8000")
    else:
        options["host"] = "127.0.0.1"
        print("Servidor local em http://127.0.0.1:8000 (somente este computador).")
    uvicorn.run(**options)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
