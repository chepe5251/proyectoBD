# -*- coding: utf-8 -*-
"""
Modulo: chat_controller.py
Descripcion: Controller de negocio para el flujo conversacional del asistente SQL.

Responsabilidad central:
    Orquestar el pipeline completo NL → IA → SQL → validacion → ejecucion → formato,
    devolviendo un resultado estructurado que la capa de UI (Tkinter) puede renderizar
    sin necesidad de conocer ningun detalle de negocio.

Posicion en la arquitectura:
    ┌──────────┐    pregunta     ┌──────────────────┐    ResultadoConsulta
    │  main.py │ ─────────────► │ chat_controller  │ ───────────────────►  main.py
    │  (GUI)   │                │                  │
    └──────────┘                │  Delega en:      │
                                │  · AIAssistant   │  NL → SQL via Gemini
                                │  · ConsultaServ. │  normaliza + prepara SQL
                                │  · SecurityMgr.  │  RBAC y validacion
                                │  · DatabaseMgr.  │  ejecucion en SQL Server
                                └──────────────────┘

Flujo de una consulta exitosa:
    1. verificar_servicios  → guardia: todos los servicios deben estar inicializados
    2. verificar_cuota_ia   → si la cuota de Gemini esta bloqueada, rechaza temprano
    3. consultar_asistente  → llama a Gemini con el historial de contexto
    4. interpretar_respuesta→ detecta prefijos especiales (PEDIR, INSTRUCCION, PENDING_HASH)
    5. normalizar_sql       → limpia markdown, backticks, prefijos residuales
    6. validar_permiso      → RBAC segunda capa: comprueba si el rol puede ejecutar esa sentencia
    7. aplicar_limite       → agrega TOP 100 a SELECT sin TOP para proteger rendimiento
    8. ejecutar_sql         → envia el SQL a SQL Server via DatabaseManager
    9. formatear_resultado  → Gemini convierte las filas en texto legible

Desacoplamiento:
    Este modulo NO importa ni referencia nada de Tkinter. Puede ser instanciado y
    ejecutado en tests unitarios, scripts o cualquier otra capa de presentacion.

Logging:
    Se usa el logger 'chat_controller' (nivel INFO por defecto). Para activar
    trazas detalladas en desarrollo: logging.getLogger('chat_controller').setLevel(logging.DEBUG)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from ai_assistant import AIAssistant, AIQuotaExceededError, AIServiceError
from app_services import ComandoIA, ConsultaPreparacionError, ConsultaPreparada, ConsultaService
from database_manager import DatabaseManager
from seguridad import SecurityManager

# Logger dedicado al modulo. Hereda la configuracion del logger raiz de la aplicacion.
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Modelos de datos de salida
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MensajeChat:
    """
    Unidad minima de salida conversacional lista para ser renderizada por la UI.

    Attributes:
        texto: Contenido del mensaje tal como debe mostrarse al usuario.
        autor: Identificador del emisor. Valores esperados por la GUI:
               'Tu' (usuario), 'Asistente' (IA), 'Sistema' (avisos del sistema).
    """

    texto: str
    autor: str


@dataclass(frozen=True)
class EntradaHistorial:
    """
    Registro de un turno conversacional para mantener contexto entre consultas.

    Gemini recibe estas entradas en el siguiente turno para que pueda resolver
    referencias anafóricas ('ese libro', 'el mismo usuario', etc.).

    Attributes:
        rol:   'usuario' o 'asistente'. Usado por AIAssistant al construir el prompt.
        texto: Contenido del turno. Para el asistente se guarda el SQL generado,
               no la respuesta formateada, para que Gemini tenga contexto tecnico.
    """

    rol: str
    texto: str


@dataclass(frozen=True)
class ResultadoConsulta:
    """
    Resultado estructurado del pipeline de consulta. Unico punto de salida del controller.

    La GUI decide como presentar estos datos; el controller nunca toca widgets ni
    variables de estado de Tkinter.

    Attributes:
        mensajes:        Uno o mas mensajes para mostrar en el chat. Normalmente un
                         solo mensaje del asistente, pero puede ser un error del sistema.
        historial:       Entradas nuevas a agregar al historial conversacional. Vacio si
                         la consulta fue bloqueada antes de llegar a Gemini.
        sql:             SQL generado (versión visual, sin contraseñas en claro).
                         None si la IA respondio con PEDIR/INSTRUCCION o si fallo.
        modelo:          Nombre del modelo Gemini que proceso la solicitud.
        estado_sql:      Texto corto que describe el resultado de la ejecucion SQL,
                         por ejemplo 'Ejecutado correctamente' o 'Bloqueado por permisos'.
        ai_blocked_until: Timestamp Unix hasta el cual la IA no debe ser llamada (cuota 429).
                          None si no aplica ningun bloqueo nuevo.
    """

    mensajes: tuple[MensajeChat, ...] = ()
    historial: tuple[EntradaHistorial, ...] = ()
    sql: str | None = None
    modelo: str | None = None
    estado_sql: str | None = None
    ai_blocked_until: float | None = None


# ---------------------------------------------------------------------------
# Controller principal
# ---------------------------------------------------------------------------


class ChatController:
    """
    Orquesta el pipeline completo: lenguaje natural → SQL → validacion → ejecucion.

    Recibe los servicios de dominio ya inicializados por la capa de presentacion
    (post-login) y procesa una pregunta del usuario devolviendo un ResultadoConsulta
    sin efectos secundarios sobre la UI.

    Dependencias inyectadas:
        asistente:        Capa de IA (Gemini). Puede ser None si aun no se inicializo.
        db:               Capa de datos (SQL Server). None antes del login.
        seguridad:        Autenticacion y RBAC. None antes del login.
        consulta_service: Normaliza y prepara el SQL generado por la IA.
        now_fn:           Funcion que devuelve el timestamp actual. Inyectable para tests.

    Uso tipico (desde main.py):
        controller = ChatController(asistente, db, seguridad, consulta_service)
        resultado = controller.procesar_consulta(pregunta, historial, ai_blocked_until)
        # resultado es un ResultadoConsulta listo para renderizar
    """

    def __init__(
        self,
        asistente: AIAssistant | None,
        db: DatabaseManager | None,
        seguridad: SecurityManager | None,
        consulta_service: ConsultaService,
        now_fn: Callable[[], float] = time.time,
    ):
        self.asistente = asistente
        self.db = db
        self.seguridad = seguridad
        self.consulta_service = consulta_service
        self._now_fn = now_fn

    # ------------------------------------------------------------------
    # Punto de entrada publico
    # ------------------------------------------------------------------

    def procesar_consulta(
        self,
        pregunta: str,
        historial_conversacion: Sequence[dict[str, str]] | None = None,
        ai_blocked_until: float = 0.0,
    ) -> ResultadoConsulta:
        """
        Procesa una consulta completa siguiendo el pipeline de 9 etapas.

        Cada etapa puede cortocircuitar el flujo devolviendo un ResultadoConsulta
        de error sin ejecutar las etapas siguientes. Solo si todas pasan se llega
        al formateo del resultado final.

        Args:
            pregunta:               Texto del usuario en lenguaje natural.
            historial_conversacion: Lista de dicts {'rol': str, 'texto': str} con
                                    los ultimos turnos del chat. Puede ser None.
            ai_blocked_until:       Timestamp hasta el cual la cuota de IA esta
                                    bloqueada (0.0 = sin bloqueo activo).

        Returns:
            ResultadoConsulta con mensajes, SQL y metadatos listos para la GUI.
        """
        logger.info("Procesando consulta: %.80s", pregunta)

        # Etapa 1 — Guardia: servicios criticos inicializados
        resultado = self._verificar_servicios_consulta()
        if resultado is not None:
            return resultado

        # Etapa 2 — Guardia: cuota de IA libre
        resultado = self._verificar_cuota_ia(ai_blocked_until)
        if resultado is not None:
            return resultado

        # Etapa 3 — Llamada a Gemini para traducir NL → SQL (o prefijo especial)
        comando_ia = self._consultar_asistente(pregunta, historial_conversacion or [])
        if isinstance(comando_ia, ResultadoConsulta):
            return comando_ia

        # Etapa 4 — Interpretacion: PEDIR / INSTRUCCION / PENDING_HASH / SQL normal
        comando = self._interpretar_respuesta_ia(pregunta, comando_ia)
        if isinstance(comando, ResultadoConsulta):
            return comando

        # Etapa 5 — Normalizacion: limpia markdown, backticks, prefijos residuales
        consulta = self._normalizar_sql_para_ejecucion(comando)
        if isinstance(consulta, ResultadoConsulta):
            return consulta

        # Etapa 6 — RBAC capa 2: verifica si el rol puede ejecutar esa sentencia
        resultado = self._validar_sql_segun_rol(consulta)
        if resultado is not None:
            return resultado

        # Etapa 7 — Proteccion de rendimiento: agrega TOP 100 si falta
        consulta = self._aplicar_limite_sql(consulta)

        # Etapa 8 — Ejecucion en SQL Server
        datos_crudos = self._ejecutar_consulta_segura(consulta)
        if isinstance(datos_crudos, ResultadoConsulta):
            return datos_crudos

        # Etapa 9 — Formateo: Gemini convierte filas en texto legible
        return self._formatear_resultado_consulta(pregunta, consulta, datos_crudos)

    # ------------------------------------------------------------------
    # Utilidades internas para construir salidas
    # ------------------------------------------------------------------

    @staticmethod
    def _historial_turno(pregunta: str, respuesta: str) -> tuple[EntradaHistorial, ...]:
        """
        Construye el par de entradas de historial para un turno completo.

        Args:
            pregunta:  Texto original del usuario.
            respuesta: SQL generado o prefijo de respuesta del asistente.

        Returns:
            Tupla con la entrada del usuario seguida de la del asistente.
        """
        return (
            EntradaHistorial(rol="usuario", texto=pregunta),
            EntradaHistorial(rol="asistente", texto=respuesta),
        )

    @staticmethod
    def _mensaje(texto: str, autor: str = "Sistema") -> tuple[MensajeChat, ...]:
        """
        Envuelve un texto en una tupla de MensajeChat lista para ResultadoConsulta.

        Args:
            texto:  Contenido del mensaje a mostrar.
            autor:  Identificador del emisor ('Sistema', 'Asistente', etc.).

        Returns:
            Tupla de un elemento con el MensajeChat construido.
        """
        return (MensajeChat(texto=texto, autor=autor),)

    # ------------------------------------------------------------------
    # Etapas del pipeline (privadas)
    # ------------------------------------------------------------------

    def _verificar_servicios_consulta(self) -> ResultadoConsulta | None:
        """
        Etapa 1: Verifica que los tres servicios criticos esten inicializados.

        Esta guardia protege contra llamadas antes del login exitoso. Si alguno
        falta, devuelve un error de sesion sin intentar ninguna operacion.

        Returns:
            ResultadoConsulta de error si falta algun servicio; None si todo esta listo.
        """
        if self.asistente is None or self.db is None or self.seguridad is None:
            logger.warning("Intento de consulta sin sesion inicializada.")
            return ResultadoConsulta(
                mensajes=self._mensaje("Sesion no inicializada correctamente."),
            )
        return None

    def _verificar_cuota_ia(self, ai_blocked_until: float) -> ResultadoConsulta | None:
        """
        Etapa 2: Comprueba si la cuota de Gemini esta bloqueada por un error 429 previo.

        Cuando Gemini devuelve 429, el controller almacena el timestamp de reintento.
        Esta etapa evita llamadas redundantes hasta que ese tiempo expire.

        Args:
            ai_blocked_until: Timestamp Unix del fin del bloqueo. 0.0 = sin bloqueo.

        Returns:
            ResultadoConsulta con mensaje de espera si la cuota sigue bloqueada;
            None si la cuota esta libre.
        """
        ahora = self._now_fn()
        if ahora >= ai_blocked_until:
            return None

        segundos = int(ai_blocked_until - ahora) + 1
        logger.info("Cuota IA bloqueada. Segundos restantes: %d", segundos)
        return ResultadoConsulta(
            mensajes=self._mensaje(
                f"La IA esta temporalmente sin cuota. Intenta de nuevo en {segundos} segundos."
            ),
        )

    def _consultar_asistente(
        self,
        pregunta: str,
        historial_conversacion: Sequence[dict[str, str]],
    ) -> ComandoIA | ResultadoConsulta:
        """
        Etapa 3: Llama a Gemini para traducir la pregunta a SQL (o prefijo especial).

        Maneja los dos tipos de error distinguibles de la IA:
        - AIQuotaExceededError (429): bloquea futuras llamadas y devuelve tiempo de espera.
        - AIServiceError (otros): devuelve un mensaje de error sin bloquear.

        Args:
            pregunta:               Texto del usuario.
            historial_conversacion: Contexto de los ultimos turnos del chat.

        Returns:
            ComandoIA con la respuesta cruda de Gemini, o ResultadoConsulta de error.
        """
        # La guardia de etapa 1 garantiza que asistente no es None en este punto.
        if self.asistente is None:
            raise RuntimeError("_consultar_asistente llamado sin asistente inicializado.")

        try:
            logger.debug("Llamando a Gemini con pregunta: %.80s", pregunta)
            sql_raw = self.asistente.interpretar_pregunta(pregunta, list(historial_conversacion))
            logger.debug("Respuesta IA recibida: %.120s", sql_raw)
        except AIQuotaExceededError as exc:
            # La cuota se agoto. Calculamos hasta cuando bloquear nuevas llamadas.
            retry_after = exc.retry_after_seconds or 30
            logger.warning("Cuota Gemini agotada. Reintento en %d segundos.", retry_after)
            return ResultadoConsulta(
                mensajes=self._mensaje(str(exc)),
                ai_blocked_until=self._now_fn() + retry_after,
            )
        except AIServiceError as exc:
            logger.error("Error de servicio IA: %s", exc)
            return ResultadoConsulta(
                mensajes=self._mensaje(f"Error de IA: {exc}"),
            )

        return ComandoIA(
            sql_raw=sql_raw,
            pending_hash=False,
            modelo=self.asistente.model_name,
        )

    def _interpretar_respuesta_ia(
        self,
        pregunta: str,
        comando_ia: ComandoIA,
    ) -> ComandoIA | ResultadoConsulta:
        """
        Etapa 4: Detecta prefijos especiales en la respuesta de Gemini.

        Gemini puede responder con tres tipos de salida que no son SQL ejecutable:
        - PEDIR:        La IA necesita mas datos del usuario antes de generar SQL.
        - INSTRUCCION:  Respuesta conversacional sin accion SQL (saludo, explicacion).
        - PENDING_HASH: SQL con contrasena en texto plano que debe hashearse antes de ejecutar.

        Si no hay ningun prefijo especial, la respuesta se trata como SQL directo.

        Args:
            pregunta:   Texto original del usuario (para construir el historial).
            comando_ia: Respuesta cruda de Gemini envuelta en ComandoIA.

        Returns:
            ComandoIA normalizado si es SQL, o ResultadoConsulta para respuestas
            conversacionales que no requieren ejecucion.
        """
        sql_raw = str(comando_ia.sql_raw or "")
        sql_upper = sql_raw.upper()

        # La IA pide mas informacion antes de poder generar el SQL.
        if sql_upper.startswith("PEDIR:"):
            pregunta_ia = sql_raw[6:].strip()
            logger.debug("IA solicita mas datos: %s", pregunta_ia)
            return ResultadoConsulta(
                mensajes=self._mensaje(pregunta_ia, autor="Asistente"),
                historial=self._historial_turno(pregunta, f"PEDIR: {pregunta_ia}"),
                sql=f"[Recopilando informacion]\n{pregunta_ia}",
                modelo=comando_ia.modelo,
                estado_sql="Recopilando informacion",
            )

        # La IA responde conversacionalmente sin necesidad de ejecutar SQL.
        if sql_upper.startswith("INSTRUCCION:"):
            mensaje_ia = sql_raw[12:].strip()
            logger.debug("IA devuelve instruccion conversacional.")
            return ResultadoConsulta(
                mensajes=self._mensaje(mensaje_ia, autor="Asistente"),
                historial=self._historial_turno(pregunta, f"INSTRUCCION: {mensaje_ia}"),
                sql=f"[Instruccion al usuario]\n{mensaje_ia}",
                modelo=comando_ia.modelo,
                estado_sql="Instruccion al usuario",
            )

        # La IA genero un EXEC con contrasena en texto plano que hay que hashear.
        # El prefijo se consume aqui; el flag pending_hash activa el hashing en ConsultaService.
        if sql_upper.startswith("PENDING_HASH:"):
            return ComandoIA(
                sql_raw=sql_raw[13:].strip(),
                pending_hash=True,
                modelo=comando_ia.modelo,
            )

        # Respuesta SQL normal: se devuelve sin modificaciones para normalizacion.
        return ComandoIA(
            sql_raw=sql_raw,
            pending_hash=False,
            modelo=comando_ia.modelo,
        )

    def _normalizar_sql_para_ejecucion(
        self,
        comando: ComandoIA,
    ) -> ConsultaPreparada | ResultadoConsulta:
        """
        Etapa 5: Delega en ConsultaService la limpieza y preparacion del SQL.

        ConsultaService elimina artefactos de Gemini (bloques Markdown, backticks,
        prefijo 'SQL:'), resuelve el hash pendiente si aplica, y construye la
        ConsultaPreparada con la version visual y la version ejecutable del SQL.

        Args:
            comando: ComandoIA con el SQL crudo y el flag pending_hash.

        Returns:
            ConsultaPreparada lista para validacion y ejecucion, o ResultadoConsulta
            de error si el SQL no pudo normalizarse.
        """
        try:
            consulta = self.consulta_service.preparar_consulta(comando)
            logger.debug("SQL normalizado: %.120s", consulta.sql)
            return consulta
        except ConsultaPreparacionError as exc:
            logger.warning("Error al preparar consulta: %s", exc.mensaje)
            return ResultadoConsulta(
                mensajes=self._mensaje(exc.mensaje),
                sql=exc.sql or None,
                modelo=comando.modelo if exc.sql else None,
                estado_sql=exc.estado or None,
            )

    def _validar_sql_segun_rol(self, consulta: ConsultaPreparada) -> ResultadoConsulta | None:
        """
        Etapa 6: Aplica RBAC de capa de aplicacion antes de enviar el SQL a la BD.

        SecurityManager.validar_accion() comprueba que la sentencia SQL sea
        compatible con los permisos del rol del usuario autenticado. Esta es la
        segunda capa de defensa: la primera son los permisos del login de SQL Server.

        Ademas detecta patrones tipicos de SQL injection para todos los roles.

        Args:
            consulta: ConsultaPreparada con el SQL ejecutable ya normalizado.

        Returns:
            None si el SQL esta permitido para el rol actual.
            ResultadoConsulta de bloqueo con mensaje explicativo si no esta permitido.
        """
        if self.seguridad is None:
            raise RuntimeError("_validar_sql_segun_rol llamado sin seguridad inicializada.")

        if self.seguridad.validar_accion(consulta.sql_exec):
            logger.debug("SQL validado para el rol actual.")
            return None

        # El SQL fue generado pero el rol del usuario no tiene permiso para ejecutarlo.
        logger.warning(
            "SQL bloqueado por permisos de rol. SQL: %.80s", consulta.sql
        )
        return ResultadoConsulta(
            mensajes=self._mensaje(
                f"No puedo ejecutar esa accion con tu rol actual. {self.seguridad.describir_permisos()}"
            ),
            sql=consulta.sql,
            modelo=consulta.modelo,
            estado_sql="Bloqueado por permisos de rol",
        )

    def _aplicar_limite_sql(self, consulta: ConsultaPreparada) -> ConsultaPreparada:
        """
        Etapa 7: Agrega TOP 100 a sentencias SELECT que no tienen clausula TOP.

        Protege el rendimiento de la aplicacion ante consultas que podrian traer
        tablas completas. Delegado en ConsultaService para mantener la logica centralizada.

        Args:
            consulta: ConsultaPreparada validada por RBAC.

        Returns:
            ConsultaPreparada con TOP 100 inyectado si aplica, o sin cambios si ya
            tenia TOP o si no es un SELECT.
        """
        return self.consulta_service.aplicar_limite_sql(consulta)

    def _ejecutar_consulta_segura(self, consulta: ConsultaPreparada) -> Any | ResultadoConsulta:
        """
        Etapa 8: Envia el SQL a SQL Server y recibe los resultados crudos.

        La ejecucion ocurre bajo el login del rol del usuario (login_admin,
        login_operativo o login_usuario), garantizando que los permisos del motor
        sean el primer nivel de defensa.

        Args:
            consulta: ConsultaPreparada con SQL ejecutable y parametros opcionales.

        Returns:
            Datos crudos de la BD (lista de filas o valor escalar) si la ejecucion
            tuvo exito, o ResultadoConsulta de error si DatabaseManager devolvio None.
        """
        if self.db is None:
            raise RuntimeError("_ejecutar_consulta_segura llamado sin db inicializado.")

        logger.info("Ejecutando SQL: %.120s", consulta.sql)
        datos_crudos = self.db.ejecutar_consulta(consulta.sql_exec, consulta.params)

        if datos_crudos is None:
            logger.error("Error de base de datos al ejecutar: %.120s", consulta.sql)
            return ResultadoConsulta(
                mensajes=self._mensaje("Ocurrio un error al consultar la base de datos."),
                sql=consulta.sql,
                modelo=consulta.modelo,
                estado_sql="Error en base de datos",
            )

        return datos_crudos

    def _formatear_resultado_consulta(
        self,
        pregunta: str,
        consulta: ConsultaPreparada,
        datos_crudos: Any,
    ) -> ResultadoConsulta:
        """
        Etapa 9: Convierte los datos crudos de SQL Server en una respuesta legible.

        Delega el formateo en AIAssistant.formatear_respuesta_humana(), que infiere
        el tipo de resultado (escalar, lista, tabla) y lo convierte en texto natural.
        El SQL generado se guarda en el historial para que Gemini mantenga contexto.

        Args:
            pregunta:     Texto original del usuario.
            consulta:     ConsultaPreparada ejecutada (contiene el SQL visual).
            datos_crudos: Filas o valor escalar devuelto por DatabaseManager.

        Returns:
            ResultadoConsulta final con el mensaje del asistente y el historial actualizado.
        """
        if self.asistente is None:
            raise RuntimeError("_formatear_resultado_consulta llamado sin asistente inicializado.")

        respuesta_final = self.asistente.formatear_respuesta_humana(pregunta, datos_crudos)
        logger.info("Consulta completada exitosamente.")
        return ResultadoConsulta(
            mensajes=self._mensaje(respuesta_final, autor="Asistente"),
            # El historial almacena el SQL (no la respuesta formateada) para que Gemini
            # pueda razonar sobre la estructura de datos en turnos futuros.
            historial=self._historial_turno(pregunta, consulta.sql),
            sql=consulta.sql,
            modelo=consulta.modelo,
            estado_sql="Ejecutado correctamente",
        )
