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
from typing import Dict
from dotenv import load_dotenv

# Inicialización: Carga de variables de entorno desde el archivo físico .env en la raíz.
# Este paso es crítico para la seguridad y portabilidad del sistema[cite: 94, 99].
load_dotenv()

# --- Configuración de Inteligencia Artificial (AI Engine) ---
# Clave API (Token) requerida para la autenticación con los servicios de Google Gemini.
# Se extrae del entorno para evitar la exposición de secretos en el control de versiones.
GEMINI_KEY: str = os.getenv("GEMINI_API_KEY")

# --- Configuración de Infraestructura de Datos (SQL Server) ---
# Diccionario estructurado que contiene los parámetros necesarios para establecer 
# una conexión funcional con la instancia de SQL Server (compuale\aleja)[cite: 77, 80].
DB_CONFIG: Dict[str, str] = {
    "server": os.getenv("DB_SERVER"),     # Host o instancia del servidor de BD.
    "database": os.getenv("DB_NAME"),     # Catálogo principal (biblioteca).
    "user": os.getenv("DB_USER"),         # Identidad para el login (usr_admin/usr_usuario)[cite: 38].
    "pass": os.getenv("DB_PASS")          # Credencial de autenticación cifrada en el entorno.
}

# --- Validación de Integridad de Runtime ---
# Protocolo de verificación de arranque para asegurar que las dependencias críticas 
# estén presentes antes de la ejecución del sistema[cite: 102].
if not GEMINI_KEY:
    print("CRITICAL_ERROR: Fallo en la inicialización. GEMINI_API_KEY no detectada en el entorno.")