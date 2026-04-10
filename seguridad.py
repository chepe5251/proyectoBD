"""
Modulo: seguridad.py
Descripcion: Autenticacion y control de acceso basado en roles (RBAC).

Responsabilidades:
    - Autenticar usuarios verificando correo y hash bcrypt de la contraseña
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
    - operativo:  bloquea DDL y comandos destructivos globales.
    - usuario:    solo SELECT/WITH; bloquea todo DML de escritura y DDL.
"""

import threading
import time

import bcrypt


# ---------------------------------------------------------------------------
# Constantes de proteccion contra fuerza bruta
# ---------------------------------------------------------------------------
_MAX_INTENTOS = 5          # Intentos fallidos antes de bloquear
_LOCKOUT_SEGUNDOS = 30     # Segundos de bloqueo tras superar el limite


class SecurityManager:
    """
    Gestiona autenticacion y autorizacion basada en roles para la aplicacion
    de biblioteca.

    La autenticacion obtiene el hash bcrypt desde la BD por correo y lo
    verifica en Python. El login operacional de SQL Server se selecciona
    segun el rol registrado en la base de datos.
    """

    # Estado de intentos fallidos compartido entre instancias (nivel de clase).
    _failed_attempts: dict = {}   # {correo: (count, lockout_until)}
    _attempts_lock = threading.Lock()

    def __init__(self, db_manager):
        """
        Args:
            db_manager (DatabaseManager): Instancia de la capa de datos.
        """
        self.db = db_manager
        self.usuario_actual = None

    # ------------------------------------------------------------------
    # Helpers de fuerza bruta
    # ------------------------------------------------------------------

    @classmethod
    def _registrar_fallo(cls, correo: str) -> None:
        with cls._attempts_lock:
            count, lockout_until = cls._failed_attempts.get(correo, (0, 0))
            count += 1
            if count >= _MAX_INTENTOS:
                lockout_until = time.time() + _LOCKOUT_SEGUNDOS
                count = 0   # Reiniciar contador para que el siguiente ciclo funcione
            cls._failed_attempts[correo] = (count, lockout_until)

    @classmethod
    def _esta_bloqueado(cls, correo: str) -> tuple[bool, int]:
        """
        Returns:
            (bloqueado, segundos_restantes)
        """
        with cls._attempts_lock:
            _count, lockout_until = cls._failed_attempts.get(correo, (0, 0))
            if time.time() < lockout_until:
                return True, int(lockout_until - time.time()) + 1
        return False, 0

    @classmethod
    def _limpiar_intentos(cls, correo: str) -> None:
        with cls._attempts_lock:
            cls._failed_attempts.pop(correo, None)

    # ------------------------------------------------------------------
    # Autenticacion
    # ------------------------------------------------------------------

    def login(self, correo, password):
        """
        Autentica al usuario verificando sus credenciales contra la BD.

        Flujo:
        1. Verifica si el correo esta bloqueado por fuerza bruta.
        2. Abre conexion temporal con SQL_LOGIN_APP (login auxiliar de solo
           lectura para autenticar).
        3. Ejecuta EXEC personas.autenticar_usuario @correo=? y obtiene el
           hash bcrypt almacenado junto con los datos del usuario.
        4. Verifica la contraseña con bcrypt.checkpw en Python.
        5. Si la verificacion falla, registra el intento fallido.
        6. Si es exitosa, selecciona el login de SQL Server por rol y
           puebla self.usuario_actual.

        Args:
            correo   (str): Correo electronico del usuario.
            password (str): Contraseña en texto plano (sin strip previo).

        Returns:
            bool: True si la autenticacion es exitosa, False en caso contrario.
        """
        from database_manager import DatabaseManager
        from config import (
            SQL_LOGIN_APP, SQL_PASS_APP,
            SQL_LOGIN_ADMIN, SQL_PASS_ADMIN,
            SQL_LOGIN_OPERATIVO, SQL_PASS_OPERATIVO,
            SQL_LOGIN_USUARIO, SQL_PASS_USUARIO,
        )

        # --- Proteccion fuerza bruta ---
        bloqueado, segundos = self._esta_bloqueado(correo)
        if bloqueado:
            print(f"Login bloqueado por {segundos}s para: {correo}")
            return False

        # --- Conexion auxiliar: solo puede ejecutar personas.autenticar_usuario ---
        try:
            db_app = DatabaseManager(uid=SQL_LOGIN_APP, pwd=SQL_PASS_APP)
            filas = db_app.ejecutar_consulta(
                "EXEC personas.autenticar_usuario @correo=?",
                (correo,),
                max_rows=1,
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
            self._registrar_fallo(correo)
            return False

        fila = filas[0]
        id_usuario, nombre, apellido, correo_db, rol, stored_hash = (
            fila[0], fila[1], fila[2], fila[3], fila[4], fila[5]
        )

        # --- Verificacion bcrypt en Python ---
        try:
            hash_bytes = stored_hash.encode() if isinstance(stored_hash, str) else stored_hash
            if not bcrypt.checkpw(password.encode(), hash_bytes):
                self._registrar_fallo(correo)
                return False
        except Exception:
            self._registrar_fallo(correo)
            return False

        # --- Login exitoso: limpiar intentos y construir sesion ---
        self._limpiar_intentos(correo)

        # Normalizar rol para consistencia interna
        rol_normalizado = "admin" if rol in ("admin", "administrador") else rol

        _login_map = {
            "admin":     (SQL_LOGIN_ADMIN,     SQL_PASS_ADMIN),
            "operativo": (SQL_LOGIN_OPERATIVO, SQL_PASS_OPERATIVO),
            "usuario":   (SQL_LOGIN_USUARIO,   SQL_PASS_USUARIO),
        }
        uid, pwd = _login_map.get(rol_normalizado, (SQL_LOGIN_USUARIO, SQL_PASS_USUARIO))

        self.usuario_actual = {
            "id":       id_usuario,
            "rol":      rol_normalizado,
            "nombre":   nombre,
            "apellido": apellido,
            "correo":   correo_db,
            "uid":      uid,
            "pwd":      pwd,
        }
        return True

    # ------------------------------------------------------------------
    # RBAC
    # ------------------------------------------------------------------

    # Comandos siempre bloqueados para todos los roles excepto admin.
    _SIEMPRE_BLOQUEADO = {
        "SHUTDOWN", "DBCC", "XACT", "KILL", "BULK INSERT",
        "OPENROWSET", "OPENDATASOURCE", "EXEC XP_", "EXECUTE XP_",
    }

    # Comandos bloqueados para rol 'usuario' (solo lectura).
    _BLOQUEADO_USUARIO = {
        "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
        "TRUNCATE", "MERGE", "GRANT", "REVOKE", "EXEC", "EXECUTE",
        "BACKUP", "RESTORE",
    }

    # Comandos bloqueados para rol 'operativo' (gestion sin DDL).
    _BLOQUEADO_OPERATIVO = {
        "DROP", "ALTER", "CREATE DATABASE", "CREATE TABLE", "CREATE SCHEMA",
        "TRUNCATE", "GRANT", "REVOKE", "BACKUP", "RESTORE",
    }

    def validar_accion(self, sql_generado):
        """
        Verifica si el SQL generado por la IA esta permitido para el rol actual.

        Ademas de la lista de comandos bloqueados, valida que la sentencia
        comience con una palabra clave reconocida segun el rol.

        Args:
            sql_generado (str): Sentencia T-SQL a evaluar.

        Returns:
            bool: True si la accion esta autorizada, False si debe bloquearse.
        """
        if not self.usuario_actual:
            return False

        rol = self.usuario_actual["rol"]
        sql_upper = str(sql_generado).upper().strip()

        # Rechazar SQL vacio o multi-sentencia (punto y coma separador).
        if not sql_upper:
            return False
        if self._tiene_multiples_sentencias(sql_upper):
            return False

        # Rechazar patrones clasicos de SQL injection en texto del SQL generado.
        _PATRONES_SQLI = ("OR '1'='1", "OR 1=1", "' OR '", "--", "/*", "*/", "WAITFOR DELAY", "XP_CMDSHELL")
        for patron in _PATRONES_SQLI:
            if patron in sql_upper:
                return False

        # Admin: sin restricciones adicionales en aplicacion (SQL Server aplica las suyas).
        if rol == "admin":
            return True

        # Comandos siempre peligrosos (todos los roles no-admin).
        for cmd in self._SIEMPRE_BLOQUEADO:
            if cmd in sql_upper:
                return False

        if rol == "usuario":
            # Solo lectura: debe comenzar con SELECT o WITH.
            if not (sql_upper.startswith("SELECT") or sql_upper.startswith("WITH")):
                return False
            for cmd in self._BLOQUEADO_USUARIO:
                if cmd in sql_upper:
                    return False

        elif rol == "operativo":
            # Gestion de datos sin DDL estructural.
            for cmd in self._BLOQUEADO_OPERATIVO:
                if cmd in sql_upper:
                    return False

        return True

    @staticmethod
    def _tiene_multiples_sentencias(sql_upper: str) -> bool:
        """
        Detecta si el SQL contiene mas de una sentencia separada por ';'.
        Ignora ';' dentro de literales de cadena simples.
        Ignora ';' al final del string (trailing semicolon permitido).
        """
        sql = sql_upper.strip()
        en_cadena = False
        for i, char in enumerate(sql):
            if char == "'":
                en_cadena = not en_cadena
            elif char == ";" and not en_cadena:
                # Solo rechazar si hay contenido real despues del punto y coma
                if sql[i + 1:].strip():
                    return True
        return False

    # ------------------------------------------------------------------
    # Descripcion de permisos
    # ------------------------------------------------------------------

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
        if rol == "admin":
            return (
                "Tu rol administrador permite operaciones completas segun "
                "las politicas del sistema."
            )

        return (
            "Tus permisos dependen del rol asignado. Si una accion no esta "
            "autorizada, te lo indicare antes de ejecutarla."
        )
