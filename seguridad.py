"""
Modulo: seguridad.py
Descripcion: Autenticacion y control de acceso basado en roles (RBAC).

Responsabilidades:
    - Autenticar usuarios verificando correo y hash SHA-256 de contraseña
      contra la tabla personas.usuarios mediante el procedimiento almacenado
      personas.autenticar_usuario.
    - La conexion de autenticacion usa un login auxiliar de solo lectura
      (SQL_LOGIN_APP) que unicamente puede ejecutar dicho procedimiento.
    - Seleccionar el login de SQL Server correspondiente al rol obtenido
      y construir las credenciales para la sesion operacional.
    - Validar el SQL generado por la IA contra las restricciones del rol
      antes de enviarlo a la base de datos (segunda linea de defensa).

Roles soportados:
    - admin:      sin restricciones adicionales en aplicacion.
    - operativo:  bloquea DROP, ALTER, CREATE DATABASE.
    - usuario:    solo SELECT; bloquea todo DML de escritura y DDL.
"""

import hashlib


class SecurityManager:
    """
    Gestiona autenticacion y autorizacion basada en roles para la aplicacion
    de biblioteca.

    La autenticacion verifica correo y contraseña contra personas.usuarios
    mediante el procedimiento almacenado personas.autenticar_usuario, usando
    un login auxiliar de solo lectura. El login operacional de SQL Server se
    selecciona segun el rol registrado en la base de datos.
    """

    def __init__(self, db_manager):
        """
        Args:
            db_manager (DatabaseManager): Instancia de la capa de datos.
        """
        self.db = db_manager
        self.usuario_actual = None

    def login(self, correo, password):
        """
        Autentica al usuario verificando sus credenciales contra la BD.

        Flujo:
        1. Calcula SHA-256 (hexdigest minusculas) de la contraseña.
        2. Abre conexion temporal con SQL_LOGIN_APP (login auxiliar de solo
           lectura para autenticar).
        3. Ejecuta EXEC personas.autenticar_usuario con correo y hash.
        4. Si retorna 0 filas, las credenciales son incorrectas.
        5. Si retorna 1 fila, lee id, nombre, apellido, correo y rol.
        6. Selecciona el login de SQL Server correspondiente al rol.
        7. Puebla self.usuario_actual con todos los datos de sesion.

        Args:
            correo   (str): Correo electronico del usuario.
            password (str): Contraseña en texto plano.

        Returns:
            bool: True si la autenticacion es exitosa, False en caso contrario.
                  Ante cualquier error de conexion retorna False sin crashear.
        """
        from database_manager import DatabaseManager
        from config import (
            SQL_LOGIN_APP, SQL_PASS_APP,
            SQL_LOGIN_ADMIN, SQL_PASS_ADMIN,
            SQL_LOGIN_OPERATIVO, SQL_PASS_OPERATIVO,
            SQL_LOGIN_USUARIO, SQL_PASS_USUARIO,
        )

        password_hash = hashlib.sha256(password.encode()).hexdigest()

        # Conexion auxiliar: solo puede ejecutar personas.autenticar_usuario.
        try:
            db_app = DatabaseManager(uid=SQL_LOGIN_APP, pwd=SQL_PASS_APP)
            filas = db_app.ejecutar_consulta(
                "EXEC personas.autenticar_usuario @correo=?, @password_hash=?",
                (correo, password_hash),
            )
        except Exception as exc:
            print(f"Error inesperado en la conexion auxiliar de autenticacion: {exc}")
            return False

        if filas is None:
            print(
                "Error de autenticacion: fallo la conexion auxiliar o el procedimiento. "
                "Verificar SQL_LOGIN_APP y permisos en SQL Server."
            )
            return False

        if not filas:
            return False

        fila = filas[0]
        id_usuario, nombre, apellido, correo_db, rol = (
            fila[0], fila[1], fila[2], fila[3], fila[4]
        )

        _login_map = {
            "admin":     (SQL_LOGIN_ADMIN,     SQL_PASS_ADMIN),
            "operativo": (SQL_LOGIN_OPERATIVO, SQL_PASS_OPERATIVO),
            "usuario":   (SQL_LOGIN_USUARIO,   SQL_PASS_USUARIO),
        }
        uid, pwd = _login_map.get(rol, (SQL_LOGIN_USUARIO, SQL_PASS_USUARIO))

        self.usuario_actual = {
            "id":       id_usuario,
            "rol":      rol,
            "nombre":   nombre,
            "apellido": apellido,
            "correo":   correo_db,
            "uid":      uid,
            "pwd":      pwd,
        }
        return True

    def validar_accion(self, sql_generado):
        """
        Verifica si el SQL generado por la IA esta permitido para el rol actual.

        Args:
            sql_generado (str): Sentencia T-SQL a evaluar.

        Returns:
            bool: True si la accion esta autorizada, False si debe bloquearse.

        Este control es la segunda linea de defensa: el motor de base de datos
        aplica sus propios permisos independientemente de este metodo.
        """
        if not self.usuario_actual:
            return False

        rol = self.usuario_actual["rol"]
        sql = str(sql_generado).upper()

        if rol == "usuario":
            # Solo lectura. No permite DML de escritura ni DDL.
            if any(cmd in sql for cmd in ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER"]):
                return False
        elif rol == "operativo":
            # Permite gestion de datos, pero no cambios estructurales.
            if any(cmd in sql for cmd in ["DROP", "ALTER", "CREATE DATABASE"]):
                return False

        return True

    def describir_permisos(self):
        """
        Retorna una descripcion en texto de los permisos del usuario actual.

        Returns:
            str: Mensaje descriptivo del rol. Si no hay sesion activa,
                 retorna 'Sin sesion activa.'.
        """
        if not self.usuario_actual:
            return "Sin sesion activa."

        rol = self.usuario_actual["rol"]
        if rol == "usuario":
            return (
                "Tu rol es de consulta: puedes leer informacion, "
                "pero no modificar registros."
            )
        if rol == "operativo":
            return (
                "Tu rol operativo permite consultar y actualizar datos, "
                "sin cambios estructurales de la base."
            )
        if rol in ["admin", "administrador"]:
            return (
                "Tu rol administrador permite operaciones completas segun "
                "las politicas del sistema."
            )

        return (
            "Tus permisos dependen del rol asignado. Si una accion no esta "
            "autorizada, te lo indicare antes de ejecutarla."
        )
