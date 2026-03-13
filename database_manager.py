"""
Modulo: database_manager.py
Descripcion: Capa de persistencia. Gestiona la conexion a SQL Server y la
             ejecucion de sentencias T-SQL mediante PyODBC.

Responsabilidades:
    - Construir la cadena de conexion ODBC con credenciales dinamicas o del .env.
    - Verificar la validez de una conexion (usado durante el login).
    - Ejecutar consultas parametrizadas y retornar filas o confirmacion.
"""

import os

import pyodbc
from dotenv import load_dotenv

load_dotenv()


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
        """
        self.conn_str = (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={os.getenv('DB_SERVER')};"
            f"DATABASE={os.getenv('DB_NAME')};"
            f"UID={uid or os.getenv('DB_USER')};"
            f"PWD={pwd or os.getenv('DB_PASS')};"
            "TrustServerCertificate=yes;"
        )

    def probar_conexion(self) -> bool:
        """
        Intenta abrir una conexion con la cadena actual.

        Returns:
            bool: True si la conexion es exitosa, False si falla.

        Uso principal: validar credenciales durante el proceso de login sin
        necesidad de almacenar contrasenas en la aplicacion.
        """
        try:
            with pyodbc.connect(self.conn_str):
                return True
        except Exception:
            return False

    @staticmethod
    def _count_placeholders(sql: str) -> int:
        return sql.count("?")

    def ejecutar_consulta(self, sql, params=None):
        """
        Ejecuta una sentencia T-SQL contra la base de datos.

        Args:
            sql (str): Sentencia T-SQL a ejecutar.
            params (tuple | list | None): Valores para los placeholders '?'.

        Returns:
            list[Row]: Filas del resultset para SELECT y vistas.
            str: Confirmacion de texto para DML/DDL sin resultset.
            None: Si ocurre un error (detalle impreso en consola).
        """
        params = tuple(params or ())
        placeholders = self._count_placeholders(sql)

        if placeholders != len(params):
            print(
                "Error de Base de Datos: cantidad de parametros invalida "
                f"(placeholders='?': {placeholders}, parametros: {len(params)})."
            )
            return None

        try:
            with pyodbc.connect(self.conn_str) as conn:
                cursor = conn.cursor()
                if params:
                    cursor.execute(sql, *params)
                else:
                    cursor.execute(sql)

                # Si la sentencia devuelve columnas, retornamos filas.
                if cursor.description is not None:
                    return cursor.fetchall()

                conn.commit()
                return "Operacion completada exitosamente."
        except Exception as e:
            print(f"Error de Base de Datos: {e}")
            return None
