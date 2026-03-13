"""
Modulo: ai_assistant.py
Descripcion: Capa de Inteligencia Artificial. Traduce preguntas en lenguaje natural
             a sentencias T-SQL ejecutables usando Google Gemini, y convierte los
             resultados crudos de la base de datos en texto legible para el usuario.

Responsabilidades:
    - Inicializar el cliente de Google Gemini con soporte para SDK nuevo y legado.
    - Mantener el contexto de dominio (schema de la biblioteca) como parte del prompt.
    - Gestionar errores de cuota (429) y modelos no disponibles (404) con fallback automatico.
    - Formatear resultados de SQL Server en texto legible segun el tipo de respuesta.

Arquitectura:
    - Patron Adaptador para soportar google-genai (nuevo) y google-generativeai (legado).
    - Inyeccion de contexto de dominio (system prompt) para restringir la IA al schema
      de la base de datos biblioteca.
"""

from config import GEMINI_KEY
import os
import re
from typing import Any, Optional

# --- Gestión de Dependencias del SDK ---
# Se implementa un mecanismo de fallback para asegurar la resiliencia del sistema
# ante diferentes entornos de instalación de Google AI.
try:
    from google import genai  # SDK principal de última generación.
    from google.genai import errors as genai_errors
    _SDK = "new"
except ImportError:
    try:
        import google.generativeai as legacy_genai  # Compatibilidad con entornos legados.
        _SDK = "legacy"
    except ImportError as exc:
        raise ImportError(
            "Dependencia crítica no encontrada. Se requiere el SDK de Gemini. "
            "Ejecute: pip install google-genai o pip install google-generativeai"
        ) from exc

class AIAssistant:
    """
    Controlador de IA para la traduccion de lenguaje natural a T-SQL (NL2SQL).

    Encapsula la configuracion del modelo Gemini y el contexto de dominio de la
    biblioteca. Provee metodos para generar SQL a partir de texto libre y para
    formatear los resultados de la base de datos en respuestas legibles.
    """

    def __init__(self):
        """
        Inicializa el cliente Gemini y carga el contexto de dominio.

        Raises:
            ValueError: Si GEMINI_API_KEY no esta configurada en el entorno.
            ImportError: Si ningun SDK de Google Gemini esta instalado.
        """
        if not GEMINI_KEY:
            raise ValueError("Acceso denegado: GEMINI_API_KEY es nula o inválida en el entorno (.env).")

        # Candidatos de modelo en orden de preferencia.
        preferred_model = os.getenv("GEMINI_MODEL")
        self.model_candidates = [
            preferred_model,
            "gemini-2.5-flash",
            "gemini-flash-latest",
            "gemini-2.5-flash-lite",
            "gemini-flash-lite-latest",
            "gemini-1.5-flash",
        ]
        self.model_candidates = [m for i, m in enumerate(self.model_candidates) if m and m not in self.model_candidates[:i]]
        self.model_name: str = self.model_candidates[0]

        # Inicialización del cliente según el SDK detectado en tiempo de ejecución.
        if _SDK == "new":
            self.client = genai.Client(api_key=GEMINI_KEY)
        else:
            legacy_genai.configure(api_key=GEMINI_KEY)
            self.model = legacy_genai.GenerativeModel(self.model_name)
        
        # Definición del esquema técnico del dominio (Data Dictionary context).
        # Este prompt actúa como una restricción de integridad para la IA.
        self.contexto: str = """
        Eres un analista de datos de la base de datos de una biblioteca.

        Tablas y columnas autorizadas:
        - personas.usuarios (id_usuario, nombre_usuario, apellido_usuario, correo, telefono)
        - catalogo.autores (id_autor, nombre_autor, apellido_autor, nacionalidad)
        - catalogo.categorias (id_categoria, nombre_categoria, descripcion)
        - catalogo.libros (id_libro, titulo, ano_publicacion, id_autor, id_categoria)
        - operaciones.prestamos (id_prestamo, id_usuario, id_libro, fecha_prestamo, fecha_devolucion, estado)
          Nota: estado = 1 significa prestamo activo, estado = 0 significa devuelto.

        Vistas disponibles (preferirlas para consultas de detalle):
        - catalogo.vista_libros_completa (id_libro, titulo, ano_publicacion, nombre_autor, apellido_autor, nombre_categoria)
        - operaciones.vista_prestamos_activos (id_prestamo, nombre_usuario, apellido_usuario, titulo, fecha_prestamo)

        Procedimientos almacenados disponibles:
        - EXEC personas.registrar_usuario @nombre, @apellido, @correo, @telefono
        - EXEC operaciones.registrar_prestamo @id_usuario, @id_libro
        - EXEC operaciones.devolver_libro @id_prestamo
        - EXEC catalogo.buscar_libro @palabra

        Restricciones de Salida:
        - Genera UNICAMENTE la sentencia T-SQL pura ejecutable para SQL Server.
        - NO uses comillas invertidas (`).
        - NO uses bloques de codigo Markdown (```sql).
        - NO incluyas explicaciones ni comentarios.
        - Para filtros de texto usa comillas simples ('). Ejemplo: WHERE nombre_autor = 'Austen'.
        - Para fechas usa el formato 'YYYY-MM-DD'.
        - Usa las vistas cuando la consulta requiera datos de multiples tablas.

        """

    @staticmethod
    def _extraer_retry_seconds(detalles_error: Any) -> Optional[int]:
        """Extrae `retryDelay` de la respuesta de error de Gemini."""
        payload = detalles_error or {}
        if isinstance(payload, dict) and "error" in payload and isinstance(payload["error"], dict):
            payload = payload["error"]

        if isinstance(payload, dict):
            for detalle in payload.get("details", []):
                if not isinstance(detalle, dict):
                    continue
                if detalle.get("@type", "").endswith("RetryInfo"):
                    delay = str(detalle.get("retryDelay", "")).strip()
                    match = re.match(r"([0-9]+(?:\.[0-9]+)?)s$", delay)
                    if match:
                        return max(1, int(float(match.group(1))))

            mensaje = str(payload.get("message", ""))
            match = re.search(r"Please retry in ([0-9]+(?:\.[0-9]+)?)s", mensaje)
            if match:
                return max(1, int(float(match.group(1))))

        return None

    def interpretar_pregunta(self, pregunta_usuario: str) -> str:
        """
        Transforma una consulta en lenguaje natural en una sentencia T-SQL ejecutable.

        Args:
            pregunta_usuario (str): Entrada de texto proporcionada por el usuario final.

        Returns:
            str: Sentencia SQL sintetizada por el modelo de IA.
            
        Note:
            La calidad del SQL generado depende directamente de la claridad del prompt del usuario
            y de la estructura definida en el atributo self.contexto.
        """
        # Estructuración del prompt final (Prompt Engineering).
        prompt_final: str = f"{self.contexto}\nUsuario dice: {pregunta_usuario}\nSQL:"
        
        try:
            if _SDK == "new":
                response = None
                last_not_found = None

                for model_name in self.model_candidates:
                    try:
                        response = self.client.models.generate_content(
                            model=model_name,
                            contents=prompt_final
                        )
                        self.model_name = model_name
                        break
                    except genai_errors.APIError as model_exc:
                        is_not_found = (
                            model_exc.code == 404
                            or str(getattr(model_exc, "status", "")).upper() == "NOT_FOUND"
                        )
                        if is_not_found:
                            last_not_found = model_exc
                            continue
                        raise

                if response is None:
                    attempted = ", ".join(self.model_candidates)
                    if last_not_found:
                        raise AIServiceError(
                            f"No hay modelos disponibles para esta API key. Intentados: {attempted}."
                        ) from last_not_found
                    raise AIServiceError("No fue posible obtener respuesta del modelo.")
            else:
                response = self.model.generate_content(prompt_final)
        except Exception as exc:
            if _SDK == "new" and isinstance(exc, genai_errors.APIError):
                retry_seconds = self._extraer_retry_seconds(getattr(exc, "details", None))
                if exc.code == 429 or str(getattr(exc, "status", "")).upper() == "RESOURCE_EXHAUSTED":
                    base_msg = "Gemini sin cuota disponible (429 RESOURCE_EXHAUSTED)."
                    if retry_seconds:
                        raise AIQuotaExceededError(
                            f"{base_msg} Reintentar en {retry_seconds} segundos.",
                            retry_after_seconds=retry_seconds,
                        ) from exc
                    raise AIQuotaExceededError(
                        f"{base_msg} Revisar límites y facturación del proyecto."
                    ) from exc

                raise AIServiceError(
                    f"Error de servicio Gemini ({exc.code} {exc.status})."
                ) from exc

            raise AIServiceError(f"Error al procesar la solicitud con IA: {exc}") from exc

        # Retorno de la cadena procesada, eliminando espacios en blanco innecesarios.
        return (response.text or "").strip()

    @staticmethod
    def _inferir_entidad_desde_pregunta(pregunta_usuario: str) -> str:
        texto = str(pregunta_usuario or "").lower()
        if "libro" in texto:
            return "libros"
        if "autor" in texto:
            return "autores"
        if "usuario" in texto:
            return "usuarios"
        if "prestamo" in texto:
            return "prestamos"
        return "registros"

    @staticmethod
    def _to_texto(valor: Any) -> str:
        if valor is None:
            return "N/A"
        return str(valor)

    @staticmethod
    def _fila_a_lista(fila: Any) -> list:
        if isinstance(fila, (str, bytes)):
            return [fila]
        try:
            return list(fila)
        except TypeError:
            return [fila]

    def formatear_respuesta_humana(self, pregunta_usuario: str, datos_db: Any) -> str:
        """
        Convierte resultados crudos de SQL Server a texto claro para el usuario final.
        """
        if datos_db is None:
            return "Con gusto te ayudo, pero ahora mismo no pude obtener datos."

        if isinstance(datos_db, str):
            return datos_db

        filas = list(datos_db) if isinstance(datos_db, (list, tuple)) else [datos_db]
        if not filas:
            return "No encontre resultados para esa consulta en este momento."

        # Caso mas comun: COUNT(*) u otro escalar.
        primera_fila = filas[0]
        primera_lista = self._fila_a_lista(primera_fila)
        if len(primera_lista) == 1 and len(filas) == 1:
            valor = self._to_texto(primera_lista[0])
            entidad = self._inferir_entidad_desde_pregunta(pregunta_usuario)
            return f"Claro. Actualmente hay {valor} {entidad} registrados."

        # Una columna y varias filas: devolvemos listado legible.
        una_columna = all(len(self._fila_a_lista(f)) == 1 for f in filas)
        if una_columna:
            valores = [self._to_texto(self._fila_a_lista(f)[0]) for f in filas]
            limite = 10
            vista = ", ".join(valores[:limite])
            extra = "" if len(valores) <= limite else f" ... y {len(valores) - limite} mas."
            return f"Con gusto. Encontre {len(valores)} resultados: {vista}{extra}"

        # Tabla general: mostrar primeras filas en formato compacto.
        limite_filas = 5
        preview = []
        for fila in filas[:limite_filas]:
            columnas = self._fila_a_lista(fila)
            preview.append(" | ".join(self._to_texto(c) for c in columnas))

        cuerpo = "\n".join(f"- {linea}" for linea in preview)
        sufijo = "" if len(filas) <= limite_filas else f"\n... y {len(filas) - limite_filas} filas mas."
        return f"Con gusto. Encontre {len(filas)} registros:\n{cuerpo}{sufijo}"


class AIServiceError(RuntimeError):
    """Error controlado de integración con el servicio de IA."""


class AIQuotaExceededError(AIServiceError):
    """Error de cuota agotada (429) con tiempo sugerido de reintento."""

    def __init__(self, message: str, retry_after_seconds: Optional[int] = None):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


