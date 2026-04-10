"""
Módulo de Configuración Centralizada (Global Configuration Manager)
------------------------------------------------------------------
Descripción:
    Este módulo se encarga de la gestión de variables de entorno y parámetros 
    críticos del sistema. Actúa como una capa de abstracción entre el archivo 
    de configuración física (.env) y la lógica de negocio del asistente.

Seguridad:
    Implementa la carga de credenciales sensibles fuera del código fuente 
    para cumplir con los estándares de seguridad de SQL Server y Google AI.
"""

import os
from dotenv import load_dotenv

# Inicialización: Carga de variables de entorno desde el archivo físico .env en la raíz.
# Este paso es crítico para la seguridad y portabilidad del sistema[cite: 94, 99].
load_dotenv()

# --- Configuración de Inteligencia Artificial (AI Engine) ---
# Clave API (Token) requerida para la autenticación con los servicios de Google Gemini.
# Se extrae del entorno para evitar la exposición de secretos en el control de versiones.
GEMINI_KEY: str | None = os.getenv("GEMINI_API_KEY")

# --- Configuración de Infraestructura de Datos (SQL Server) ---
# DB_SERVER y DB_NAME son leídos directamente por database_manager.py via os.getenv().
# DB_USER / DB_PASS son fallbacks opcionales del DatabaseManager cuando no se provee uid/pwd.

# --- Logins de SQL Server por rol ---
# Login auxiliar de solo lectura para ejecutar personas.autenticar_usuario.
SQL_LOGIN_APP:  str = os.getenv("SQL_LOGIN_APP",  "")
SQL_PASS_APP:   str = os.getenv("SQL_PASS_APP",   "")

# Logins operacionales asignados según el rol autenticado.
SQL_LOGIN_ADMIN:      str = os.getenv("SQL_LOGIN_ADMIN",      "")
SQL_PASS_ADMIN:       str = os.getenv("SQL_PASS_ADMIN",       "")
SQL_LOGIN_OPERATIVO:  str = os.getenv("SQL_LOGIN_OPERATIVO",  "")
SQL_PASS_OPERATIVO:   str = os.getenv("SQL_PASS_OPERATIVO",   "")
SQL_LOGIN_USUARIO:    str = os.getenv("SQL_LOGIN_USUARIO",    "")
SQL_PASS_USUARIO:     str = os.getenv("SQL_PASS_USUARIO",     "")

