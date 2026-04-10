"""
Modulo: config.py
Descripcion: Configuracion centralizada del sistema. Carga variables de entorno
             desde .env y las expone al resto del proyecto. Emite advertencias
             de log si faltan credenciales criticas al arrancar.

Seguridad:
    Las credenciales (API keys, passwords de SQL Server) se cargan desde el
    archivo .env, que nunca debe subirse al repositorio. Este modulo NO expone
    valores sensibles en logs: solo registra si una variable esta ausente.
"""

import logging
import os

from dotenv import load_dotenv

# Cargar .env antes de cualquier acceso a os.getenv().
load_dotenv()

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Inteligencia Artificial — Google Gemini
# ---------------------------------------------------------------------------
GEMINI_KEY: str | None = os.getenv("GEMINI_API_KEY")

# ---------------------------------------------------------------------------
# Logins de SQL Server por rol
# ---------------------------------------------------------------------------
# Login auxiliar: solo puede ejecutar personas.autenticar_usuario.
SQL_LOGIN_APP:  str = os.getenv("SQL_LOGIN_APP",  "")
SQL_PASS_APP:   str = os.getenv("SQL_PASS_APP",   "")

# Logins operacionales (la app los selecciona automaticamente segun el rol).
SQL_LOGIN_ADMIN:     str = os.getenv("SQL_LOGIN_ADMIN",     "")
SQL_PASS_ADMIN:      str = os.getenv("SQL_PASS_ADMIN",      "")
SQL_LOGIN_OPERATIVO: str = os.getenv("SQL_LOGIN_OPERATIVO", "")
SQL_PASS_OPERATIVO:  str = os.getenv("SQL_PASS_OPERATIVO",  "")
SQL_LOGIN_USUARIO:   str = os.getenv("SQL_LOGIN_USUARIO",   "")
SQL_PASS_USUARIO:    str = os.getenv("SQL_PASS_USUARIO",    "")

# ---------------------------------------------------------------------------
# Validacion de variables criticas (advertencias, no sys.exit)
# La GUI muestra pantalla de error si GEMINI_KEY falta; para las credenciales
# de BD el error se manifiesta en el primer intento de conexion.
# ---------------------------------------------------------------------------
_VARS_CRITICAS = {
    "GEMINI_API_KEY":        GEMINI_KEY,
    "SQL_LOGIN_APP":         SQL_LOGIN_APP,
    "SQL_PASS_APP":          SQL_PASS_APP,
    "SQL_LOGIN_ADMIN":       SQL_LOGIN_ADMIN,
    "SQL_PASS_ADMIN":        SQL_PASS_ADMIN,
    "SQL_LOGIN_OPERATIVO":   SQL_LOGIN_OPERATIVO,
    "SQL_PASS_OPERATIVO":    SQL_PASS_OPERATIVO,
    "SQL_LOGIN_USUARIO":     SQL_LOGIN_USUARIO,
    "SQL_PASS_USUARIO":      SQL_PASS_USUARIO,
}
for _nombre, _valor in _VARS_CRITICAS.items():
    if not _valor:
        _log.warning("Variable de entorno ausente o vacia: %s", _nombre)
