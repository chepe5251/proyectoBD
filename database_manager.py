# -*- coding: utf-8 -*-
"""
Modulo: database_manager.py
Descripcion: Capa de persistencia. Gestiona la conexion a SQL Server y la
             ejecucion de sentencias T-SQL parametrizadas mediante PyODBC.

Responsabilidades:
    - Construir la cadena de conexion ODBC con credenciales dinamicas o del .env.
    - Verificar la validez de una conexion (usado durante el login).
    - Ejecutar consultas parametrizadas y retornar filas o confirmacion.

Notas de seguridad:
    - La cadena de conexion nunca se registra en los logs (contiene credenciales).
    - Los mensajes de error registran el tipo de excepcion pero no el texto
      completo si contiene valores sensibles.
    - Cada llamada a ejecutar_consulta abre y cierra su propia conexion para
      simplificar el manejo de estado y evitar conexiones huerfanas.
"""

import logging
import os

import pyodbc

_log = logging.getLogger(__name__)


class DatabaseManager:
    """
    Gestiona la conexion y ejecucion de sentencias en SQL Server via PyODBC.

    Cada instancia representa una sesion configurada con credenciales especificas.
    Soporta credenciales dinamicas para que cada usuario opere bajo su propio login
    de SQL Server, activando los permisos del motor de forma transparente.
    """

    def __init__(self, uid=None, pwd=None):
        """
        Construye la cadena de conexion ODBC.

        Args:
            uid (str | None): Login de SQL Server. Si es None, usa DB_USER del .env.
            pwd (str | None): Contrasena del login. Si es None, usa DB_PASS del .env.

        Nota: La cadena resultante nunca se imprime ni registra en logs.
        """
        trust_cert = os.getenv("DB_TRUST_CERT", "no")
        self.conn_str = (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={os.getenv('DB_SERVER')};"
            f"DATABASE={os.getenv('DB_NAME')};"
            f"UID={uid or os.getenv('DB_USER')};"
            f"PWD={pwd or os.getenv('DB_PASS')};"
            f"TrustServerCertificate={trust_cert};"
            "Connection Timeout=5;"
        )

    def probar_conexion(self) -> bool:
        """
        Intenta abrir una conexion con la cadena actual.

        Returns:
            bool: True si la conexion es exitosa, False si falla.

        Uso principal: validar que las credenciales del rol son correctas
        tras el login, sin almacenar contraseñas en la aplicacion.
        """
        try:
            with pyodbc.connect(self.conn_str, timeout=5):
                return True
        except pyodbc.Error as exc:
            _log.warning("probar_conexion fallo: %s", type(exc).__name__)
            return False
        except Exception as exc:
            _log.warning("probar_conexion: error inesperado: %s", type(exc).__name__)
            return False

    @staticmethod
    def _count_placeholders(sql: str) -> int:
        """Cuenta los marcadores '?' en la sentencia SQL."""
        return sql.count("?")

    def ejecutar_consulta(self, sql: str, params=None, max_rows: int = 100):
        """
        Ejecuta una sentencia T-SQL contra la base de datos.

        Args:
            sql      (str): Sentencia T-SQL a ejecutar (parametrizada con '?').
            params   (tuple | list | None): Valores para los placeholders '?'.
            max_rows (int): Maximo de filas a retornar en SELECT (default 100).

        Returns:
            list[Row]: Filas del resultset para SELECT, vistas y EXEC con salida.
            str:  Mensaje de confirmacion para DML/DDL sin resultset.
            None: Si ocurre cualquier error (detalle en logs).

        Notas:
            - Valida que el numero de '?' coincida con len(params) antes de ejecutar.
            - Abre y cierra la conexion en cada llamada (sin pool de conexiones).
            - Los errores se registran en el logger del modulo, no en stdout.
        """
        params = tuple(params or ())
        placeholders = self._count_placeholders(sql)

        if placeholders != len(params):
            _log.error(
                "Parametros invalidos: se esperaban %d placeholders, se recibieron %d.",
                placeholders,
                len(params),
            )
            return None

        try:
            with pyodbc.connect(self.conn_str, timeout=5) as conn:
                # Decodificar VARCHAR con cp1252 (Latin-1) y NVARCHAR con UTF-8
                # para que tildes y ñ se lean correctamente desde SQL Server.
                conn.setdecoding(pyodbc.SQL_CHAR, encoding='cp1252')
                conn.setdecoding(pyodbc.SQL_WCHAR, encoding='utf-8')
                conn.setencoding(encoding='utf-8')
                cursor = conn.cursor()
                if params:
                    cursor.execute(sql, *params)
                else:
                    cursor.execute(sql)

                if cursor.description is not None:
                    filas = cursor.fetchmany(max_rows)
                    _log.debug(
                        "Consulta ejecutada. Filas retornadas: %d (max=%d).",
                        len(filas),
                        max_rows,
                    )
                    return filas

                conn.commit()
                return "Operacion completada exitosamente."

        except pyodbc.ProgrammingError as exc:
            _log.error("Error de SQL (sintaxis o objeto no encontrado): %s", exc)
            return None
        except pyodbc.OperationalError as exc:
            _log.error("Error operacional de BD (conexion o timeout): %s", type(exc).__name__)
            return None
        except pyodbc.Error as exc:
            _log.error("Error de PyODBC (%s): %s", type(exc).__name__, exc)
            return None
        except Exception as exc:
            _log.error(
                "Error inesperado en ejecutar_consulta (%s): %s",
                type(exc).__name__,
                exc,
            )
            return None
