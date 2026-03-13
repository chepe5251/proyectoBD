"""
Modulo: seguridad.py
Descripcion: Autenticacion y control de acceso basado en roles (RBAC).

Responsabilidades:
    - Autenticar usuarios probando su conexion directa a SQL Server.
      No se almacenan contrasenas en la aplicacion.
    - Inferir el rol del usuario a partir del nombre de su login de SQL Server.
    - Validar el SQL generado por la IA contra las restricciones del rol
      antes de enviarlo a la base de datos (segunda linea de defensa).

Roles soportados:
    - login_admin     -> admin:     sin restricciones adicionales en aplicacion.
    - login_operativo -> operativo: bloquea DROP, ALTER, CREATE DATABASE.
    - login_usuario   -> usuario:   solo SELECT; bloquea todo DML de escritura y DDL.
"""


class SecurityManager:
    """
    Gestiona autenticacion y autorizacion basada en roles para la aplicacion
    de biblioteca.

    La autenticacion se delega a SQL Server: si las credenciales son validas
    para abrir una conexion, el usuario queda autenticado. El rol se infiere
    del nombre del login, y los permisos del motor aplican automaticamente
    sobre todas las consultas posteriores.
    """

    def __init__(self, db_manager):
        """
        Args:
            db_manager (DatabaseManager): Instancia de la capa de datos.
        """
        self.db = db_manager
        self.usuario_actual = None

    def login(self, usuario, password):
        """
        Autentica al usuario probando una conexion directa a SQL Server.

        Args:
            usuario (str): Login de SQL Server (ej. 'login_admin').
            password (str): Contrasena del login.

        Returns:
            bool: True si la conexion es exitosa y el usuario queda autenticado.
                  False si las credenciales son incorrectas o el servidor es
                  inaccesible.

        Al autenticarse correctamente, puebla self.usuario_actual con id, rol,
        nombre y credenciales (uid/pwd) para que la capa de presentacion pueda
        reconectar DatabaseManager bajo la identidad del usuario.
        """
        from database_manager import DatabaseManager

        db_test = DatabaseManager(uid=usuario, pwd=password)
        if not db_test.probar_conexion():
            return False

        _rol_map = {
            "login_admin": "admin",
            "login_operativo": "operativo",
            "login_usuario": "usuario",
        }
        rol = _rol_map.get(usuario.lower(), "usuario")

        self.usuario_actual = {
            "id": None,
            "rol": rol,
            "nombre": usuario,
            "uid": usuario,
            "pwd": password,
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

        if rol in ["usuario", "cliente"]:
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
        if rol in ["usuario", "cliente"]:
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
