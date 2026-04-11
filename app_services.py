"""
Servicios de aplicacion para la capa de presentacion.

Este modulo encapsula logica no visual que antes vivia en main.py:
    - validacion y registro de usuarios
    - preparacion de SQL para ejecucion
    - resolucion de registros via PENDING_HASH
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import bcrypt

from database_manager import DatabaseManager


@dataclass(frozen=True)
class RegistroUsuarioData:
    nombre: str = ""
    apellido: str = ""
    correo: str = ""
    telefono: str = ""
    password: str = ""
    rol: str = "usuario"


@dataclass(frozen=True)
class RegistroUsuarioPayload:
    nombre: str
    apellido: str
    correo: str
    telefono: str
    password_hash: str
    rol: str


@dataclass(frozen=True)
class ComandoIA:
    sql_raw: str
    pending_hash: bool
    modelo: str


@dataclass(frozen=True)
class ConsultaPreparada:
    sql: str
    sql_exec: str
    params: tuple
    modelo: str


class ConsultaPreparacionError(ValueError):
    """Error de negocio al convertir la respuesta de IA en una consulta ejecutable."""

    def __init__(self, mensaje: str, sql: str = "", estado: str = ""):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.sql = sql
        self.estado = estado


class RegistroUsuarioService:
    """Centraliza la validacion, hashing y construccion del registro de usuarios."""

    PROC_REGISTRO_USUARIO = "personas.registrar_usuario"
    PARAM_ORDER = (
        "nombre",
        "apellido",
        "correo",
        "telefono",
        "password_hash",
        "rol",
    )

    @staticmethod
    def validar(datos: RegistroUsuarioData, confirmar: str | None = None) -> tuple[str, str] | None:
        if not all([datos.nombre, datos.apellido, datos.correo, datos.telefono, datos.password]):
            return "Datos incompletos", "Todos los campos son obligatorios."
        if "@" not in datos.correo or "." not in datos.correo.split("@")[-1]:
            return "Correo invalido", "El correo ingresado no es valido."
        if len(datos.telefono) < 8:
            return "Telefono invalido", "El telefono debe tener al menos 8 caracteres."
        if len(datos.password) < 6:
            return "Contrasena corta", "La contrasena debe tener al menos 6 caracteres."
        if confirmar is not None and datos.password != confirmar:
            return "Contrasenas distintas", "Las contrasenas no coinciden."
        return None

    @staticmethod
    def generar_password_hash(password: str) -> str:
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()

    @staticmethod
    def _literal_sql(valor: str) -> str:
        return "'" + str(valor).replace("'", "''") + "'"

    @classmethod
    def _construir_sql_registro(cls, value_factory) -> str:
        argumentos = [f"@{param}={value_factory(param)}" for param in cls.PARAM_ORDER]
        return f"EXEC {cls.PROC_REGISTRO_USUARIO} " + ", ".join(argumentos)

    def construir_payload(self, datos: RegistroUsuarioData) -> RegistroUsuarioPayload:
        return RegistroUsuarioPayload(
            nombre=datos.nombre.strip(),
            apellido=datos.apellido.strip(),
            correo=datos.correo.strip(),
            telefono=datos.telefono.strip(),
            password_hash=self.generar_password_hash(datos.password),
            rol=datos.rol.strip().lower() or "usuario",
        )

    def parametros(self, payload: RegistroUsuarioPayload) -> tuple:
        return tuple(getattr(payload, param) for param in self.PARAM_ORDER)

    def sql_parametrizado(self) -> str:
        return self._construir_sql_registro(lambda _param: "?")

    def sql_visual(self, payload: RegistroUsuarioPayload) -> str:
        return self._construir_sql_registro(
            lambda param: self._literal_sql("[bcrypt generado]")
            if param == "password_hash"
            else self._literal_sql(getattr(payload, param))
        )

    def ejecutar_registro(self, db_manager: DatabaseManager, payload: RegistroUsuarioPayload):
        return db_manager.ejecutar_consulta(self.sql_parametrizado(), self.parametros(payload))

    @staticmethod
    def extraer_desde_sql(sql: str) -> RegistroUsuarioData | None:
        match_proc = re.match(
            r"^\s*EXEC(?:UTE)?\s+personas\.registrar_usuario\b",
            sql,
            re.IGNORECASE,
        )
        if not match_proc:
            return None

        patron = re.compile(
            r"@(\w+)\s*=\s*(N?'(?:''|[^'])*'|[^,]+?)(?=\s*,\s*@|\s*$)",
            re.IGNORECASE,
        )
        parametros = {}
        for match in patron.finditer(sql[match_proc.end():]):
            nombre = match.group(1).lower()
            valor_raw = match.group(2).strip()
            if valor_raw.upper() == "NULL":
                valor = ""
            elif valor_raw.startswith("N'") and valor_raw.endswith("'"):
                valor = valor_raw[2:-1].replace("''", "'")
            elif valor_raw.startswith("'") and valor_raw.endswith("'"):
                valor = valor_raw[1:-1].replace("''", "'")
            else:
                valor = valor_raw
            parametros[nombre] = valor

        if not parametros:
            return None

        return RegistroUsuarioData(
            nombre=parametros.get("nombre", ""),
            apellido=parametros.get("apellido", ""),
            correo=parametros.get("correo", ""),
            telefono=parametros.get("telefono", ""),
            password=parametros.get("password_hash", ""),
            rol=parametros.get("rol", "usuario"),
        )


class ConsultaService:
    """Convierte respuestas de IA en consultas preparadas y seguras para ejecutar."""

    def __init__(self, registro_service: RegistroUsuarioService):
        self.registro_service = registro_service

    @staticmethod
    def ocultar_password_hash(sql: str) -> str:
        return re.sub(
            r"(@password_hash\s*=\s*')([^']*)(')",
            r"\1[bcrypt generado]\3",
            sql,
            flags=re.IGNORECASE,
        )

    @staticmethod
    def normalizar_sql(sql_generado: str) -> str:
        sql = str(sql_generado or "").strip()
        if not sql:
            return ""

        bloque = re.search(r"```(?:sql)?\s*(.*?)```", sql, flags=re.IGNORECASE | re.DOTALL)
        if bloque:
            sql = bloque.group(1).strip()

        if sql.upper().startswith("SQL:"):
            sql = sql[4:].strip()

        sql_keywords = {
            "SELECT", "FROM", "WHERE", "EXEC", "WITH", "ORDER", "BY", "GROUP",
            "HAVING", "TOP", "AS", "JOIN", "LEFT", "RIGHT", "INNER", "OUTER",
            "ON", "AND", "OR", "INSERT", "UPDATE", "DELETE", "INTO", "VALUES",
        }

        def replace_backtick_identifier(match):
            token = match.group(1)
            if token.upper() in sql_keywords:
                return token
            return f"[{token}]"

        sql = re.sub(r"`([A-Za-z_][A-Za-z0-9_]*)`", replace_backtick_identifier, sql)
        if "`" in sql:
            sql = sql.replace("`", "'")

        sql_upper = sql.upper()
        posiciones = [sql_upper.find(keyword) for keyword in ("SELECT", "EXEC", "WITH")]
        posiciones_validas = [pos for pos in posiciones if pos >= 0]
        if posiciones_validas:
            sql = sql[min(posiciones_validas):].strip()

        return sql

    def _aplicar_hash_pendiente(self, sql: str) -> str | None:
        match_pw = re.search(r"@password_hash\s*=\s*'([^']*)'", sql, re.IGNORECASE)
        if not match_pw:
            return None

        raw_password = match_pw.group(1)
        pw_hash = self.registro_service.generar_password_hash(raw_password)
        return sql[:match_pw.start(1)] + pw_hash + sql[match_pw.end(1):]

    def resolver_registro_pendiente(self, sql: str, modelo: str) -> ConsultaPreparada | str:
        datos_registro = self.registro_service.extraer_desde_sql(sql)
        if datos_registro is not None:
            validacion = self.registro_service.validar(datos_registro)
            if validacion:
                raise ConsultaPreparacionError(
                    validacion[1],
                    sql=self.ocultar_password_hash(sql),
                    estado="Registro invalido",
                )

            payload = self.registro_service.construir_payload(datos_registro)
            return ConsultaPreparada(
                sql=self.registro_service.sql_visual(payload),
                sql_exec=self.registro_service.sql_parametrizado(),
                params=self.registro_service.parametros(payload),
                modelo=modelo,
            )

        sql_con_hash = self._aplicar_hash_pendiente(sql)
        if not sql_con_hash:
            raise ConsultaPreparacionError(
                "La instruccion de registro no contiene un @password_hash valido.",
                sql=self.ocultar_password_hash(sql),
                estado="Registro invalido",
            )
        return sql_con_hash

    def preparar_consulta(self, comando: ComandoIA) -> ConsultaPreparada:
        sql = self.normalizar_sql(comando.sql_raw)
        if not sql:
            raise ConsultaPreparacionError(
                "No se pudo generar una consulta valida.",
                sql="(no se genero SQL valido)",
            )

        if comando.pending_hash:
            preparada = self.resolver_registro_pendiente(sql, comando.modelo)
            if isinstance(preparada, ConsultaPreparada):
                return preparada
            sql = preparada

        sql_visual = self.ocultar_password_hash(sql)
        if "?" in sql_visual:
            raise ConsultaPreparacionError(
                "La consulta generada quedo incompleta (placeholder '?'). Intenta reformular.",
                sql=sql_visual,
                estado="Pendiente de validacion",
            )

        return ConsultaPreparada(
            sql=sql_visual,
            sql_exec=sql,
            params=(),
            modelo=comando.modelo,
        )

    @staticmethod
    def aplicar_limite_sql(consulta: ConsultaPreparada) -> ConsultaPreparada:
        if not re.match(r"^\s*SELECT\s+(?!TOP\s)", consulta.sql_exec, re.IGNORECASE):
            return consulta

        sql_exec = re.sub(r"(?i)^(\s*SELECT\s+)", r"\1TOP 100 ", consulta.sql_exec, count=1)
        sql = re.sub(r"(?i)^(\s*SELECT\s+)", r"\1TOP 100 ", consulta.sql, count=1)
        return ConsultaPreparada(
            sql=sql,
            sql_exec=sql_exec,
            params=consulta.params,
            modelo=consulta.modelo,
        )
