# Arquitectura Tecnica

## Objetivo

Describir la arquitectura del asistente de biblioteca: sus capas, responsabilidades, flujo de datos y decisiones de diseno.

---

## Capas del sistema

El sistema sigue una arquitectura de capas con separacion clara de responsabilidades:

```
┌──────────────────────────────────────────────────────┐
│  Capa de Presentacion  —  main.py                    │
│  GUI Tkinter. Orquesta el flujo completo.            │
└────────────────────────┬─────────────────────────────┘
                         │ delega
                         ▼
              ┌──────────────────────────────┐
              │ Servicios de Aplicacion      │
              │ app_services.py              │
              │ Registro + preparacion SQL   │
              └───────────────┬──────────────┘
                              │
         ┌────────────────────┼────────────────────┐
         ▼                    ▼                    ▼
┌────────────────┐  ┌──────────────┐   ┌────────────────┐
│ Capa de        │  │ Capa de IA   │   │ Capa de Datos  │
│ Seguridad      │  │ ai_assistant │   │ database_mgr   │
│ seguridad.py   │  │              │   │                │
│                │  │ Google       │   │ PyODBC         │
│ Autenticacion  │  │ Gemini API   │   │ SQL Server     │
│ RBAC           │  │ NL -> T-SQL  │   │ biblioteca     │
└────────────────┘  └──────────────┘   └────────────────┘
         │                                      │
         └────────────── config.py ─────────────┘
                    Carga de .env
```

---

## Descripcion de cada capa

### 1. Capa de Configuracion — `config.py`

Responsabilidades:
- Cargar el archivo `.env` al importarse (via `python-dotenv`).
- Exponer `GEMINI_KEY` y los logins de SQL Server al resto del sistema.
- Emitir advertencias de log (`logging.WARNING`) si alguna variable critica esta ausente o vacia.

No tiene dependencias internas. Es importada por `ai_assistant.py`, `seguridad.py` y `main.py`.

---

### 2. Capa de IA — `ai_assistant.py`

Responsabilidades:
- Inicializar el cliente de Google Gemini con fallback entre SDK nuevo (`google-genai`) y SDK legado (`google-generativeai`).
- Mantener el contexto de dominio: tablas, vistas y procedimientos autorizados de la base `biblioteca`.
- Mantener el historial conversacional para dar contexto a cada pregunta (ultimos 10 turnos).
- Traducir preguntas en lenguaje natural a T-SQL ejecutable, o retornar prefijos especiales:
  - `PEDIR:` cuando necesita datos adicionales del usuario.
  - `INSTRUCCION:` cuando la respuesta no requiere SQL.
  - `PENDING_HASH:` cuando el SQL incluye una contrasena en texto plano que debe ser hasheada con bcrypt antes de ejecutar.
- Formatear resultados crudos de la base de datos en texto legible para el usuario.
- Gestionar errores de cuota (429) y modelos no disponibles (404) con fallback automatico.

Patron de diseno: Adaptador para multiples versiones del SDK de Google.

Candidatos de modelo (en orden de preferencia, definidos en `__init__`):
1. Valor de `GEMINI_MODEL` en `.env` (si existe y no es duplicado).
2. `gemini-2.5-flash`
3. `gemini-2.5-pro`
4. `gemini-2.0-flash`
5. `gemini-2.0-flash-lite`

Si un modelo retorna 404, el sistema prueba automaticamente el siguiente candidato.

---

### 3. Capa de Datos — `database_manager.py`

Responsabilidades:
- Construir la cadena de conexion ODBC con las credenciales recibidas (o las del `.env` por defecto).
- Verificar la validez de una conexion (`probar_conexion`).
- Ejecutar sentencias SQL parametrizadas o sin parametros.
- Retornar filas para sentencias con resultset o confirmacion de texto para DML/DDL.
- Registrar errores con `logging` sin exponer datos sensibles de la cadena de conexion.

Cada llamada a `ejecutar_consulta` abre y cierra su propia conexion para simplificar el manejo de estado.

---

### 4. Capa de Seguridad — `seguridad.py`

Responsabilidades:
- Autenticar al usuario: obtiene el hash bcrypt almacenado en `personas.usuarios` por correo
  (via `personas.autenticar_usuario` con el login auxiliar `SQL_LOGIN_APP`) y verifica la
  contrasena con `bcrypt.checkpw()` en Python. Nunca se transmite ni almacena la contrasena en claro.
- Proteger contra fuerza bruta: bloqueo automatico de 30 segundos tras 5 intentos fallidos
  consecutivos por correo (estado compartido a nivel de clase con `threading.Lock`).
- Seleccionar el login de SQL Server correspondiente al rol obtenido de la base de datos.
- Poblar `self.usuario_actual` con id, nombre, apellido, correo, rol y credenciales operacionales.
- Validar el SQL generado por la IA contra las restricciones del rol antes de ejecutarlo (segunda capa de defensa).

Dos niveles de control de acceso:
- **Nivel motor**: SQL Server aplica los permisos del login seleccionado segun rol.
- **Nivel aplicacion**: `validar_accion()` bloquea comandos segun el rol.

| Rol | Restricciones en aplicacion |
|-----|----------------------------|
| `usuario` | Solo acepta SQL que comience con SELECT o WITH. Bloquea: INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE, MERGE, GRANT, REVOKE, EXEC, EXECUTE, BACKUP, RESTORE |
| `operativo` | Bloquea: DROP, ALTER, CREATE DATABASE, CREATE TABLE, CREATE SCHEMA, TRUNCATE, GRANT, REVOKE, BACKUP, RESTORE |
| `admin` | Sin restricciones adicionales en la aplicacion (SQL Server aplica los suyos) |

Para **todos** los roles se bloquea adicionalmente:
- Sentencias con multiples instrucciones separadas por `;` (con contenido real tras el punto y coma)
- Patrones de SQL injection: `OR '1'='1'`, `OR 1=1`, `' OR '`, `--`, `/*`, `*/`, `WAITFOR DELAY`, `XP_CMDSHELL`
- Comandos siempre peligrosos: `SHUTDOWN`, `DBCC`, `XACT`, `KILL`, `BULK INSERT`, `OPENROWSET`, `OPENDATASOURCE`, `EXEC XP_`, `EXECUTE XP_`

---

### 5. Capa de Presentacion — `main.py`

Responsabilidades:
- Renderizar pantallas de login, registro y chat con Tkinter (tema oscuro, teal accent).
- Orquestar el flujo completo: login → NL → validacion prefijo IA → normalizacion SQL →
  RBAC → ejecucion → formateo → display.
- Compartir la misma validacion de registro, hashing bcrypt y construccion del `EXEC personas.registrar_usuario`
  entre el formulario de alta y el flujo conversacional `PENDING_HASH:`.
- Mantener el historial conversacional (`self.historial_conversacion`, max 10 entradas) y
  pasarlo a `interpretar_pregunta` en cada consulta.
- Interceptar respuestas especiales de la IA antes de normalizar el SQL:
  - `PEDIR:` → muestra pregunta en el chat, actualiza historial, espera siguiente turno.
  - `INSTRUCCION:` → muestra mensaje en el chat, actualiza historial.
  - `PENDING_HASH:` → detecta registros de usuario, genera hash bcrypt y reutiliza la misma
    construccion parametrizada del alta; en otros casos sustituye el `@password_hash` antes de ejecutar.
- Ejecutar el flujo NL->SQL->DB en un hilo secundario (`threading.Thread`) delegando cuota,
  IA, comandos especiales, preparacion SQL, validacion, ejecucion y respuesta a helpers privados.
- Normalizar el SQL generado por la IA (eliminar markdown, backticks, prefijos textuales).
- Gestionar el estado de la UI durante el procesamiento (bloqueo de inputs, indicador de estado).
- Mostrar mensajes en el chat con estilo de burbuja segun el autor (usuario, asistente, sistema).

---

### 6. Servicios de Aplicacion — `app_services.py`

Responsabilidades:
- Centralizar la validacion, hashing bcrypt y construccion del `EXEC personas.registrar_usuario`.
- Reutilizar la misma logica de registro desde el formulario GUI y desde `PENDING_HASH:`.
- Normalizar la respuesta SQL de la IA, ocultar `@password_hash` en el SQL visible y construir consultas preparadas.
- Aplicar `TOP 100` sobre `SELECT` sin limite como paso reutilizable y testeable fuera de Tkinter.

Esto reduce el acoplamiento de `main.py` con reglas de negocio y deja a la GUI como orquestadora.

---

### Controller Conversacional — `chat_controller.py`

Responsabilidades:
- Orquestar el flujo completo NL -> SQL -> validacion -> ejecucion sin depender de Tkinter.
- Consultar Gemini y traducir errores de cuota o servicio a resultados estructurados.
- Interpretar prefijos especiales `PEDIR:`, `INSTRUCCION:` y `PENDING_HASH:`.
- Delegar preparacion SQL a `ConsultaService`, validar RBAC con `SecurityManager` y ejecutar con `DatabaseManager`.
- Entregar a la GUI un `ResultadoConsulta` con mensajes, SQL visible, estado e historial.

Esta capa reduce el acoplamiento entre `BibliotecaApp` y la logica de negocio del chat.

---

## Flujo detallado de una consulta

```
[Usuario escribe pregunta]
        │
        ▼
BibliotecaApp.procesar_consulta()
        │
        ├─ Verificar cuota de IA (ai_blocked_until + threading.Lock)
        │
        ├─ AIAssistant.interpretar_pregunta(pregunta, historial)
        │       └─ Gemini API — con contexto de dominio + historial
        │           retorna: SQL | PEDIR:... | INSTRUCCION:... | PENDING_HASH:...
        │
        ├─ ¿Respuesta es PEDIR:?
        │       └─ Mostrar pregunta en chat, actualizar historial → FIN del turno
        │
        ├─ ¿Respuesta es INSTRUCCION:?
        │       └─ Mostrar mensaje en chat, actualizar historial → FIN del turno
        │
        ├─ ¿Respuesta es PENDING_HASH:?
        │       └─ Si es `personas.registrar_usuario`, reutilizar helper de registro
        │          para validar datos, generar hash bcrypt y construir EXEC parametrizado
        │          Si no, hashear `@password_hash` antes de continuar
        │
        ├─ BibliotecaApp._normalizar_sql(sql)
        │       └─ Limpia markdown, backticks, prefijo "SQL:"
        │
        ├─ SecurityManager.validar_accion(sql)
        │       └─ Bloquea si el rol no tiene permiso → FIN del turno
        │
        ├─ Inyectar TOP 100 en SELECT sin TOP (evita full table scan en respuesta)
        │
        ├─ DatabaseManager.ejecutar_consulta(sql)
        │       └─ PyODBC → SQL Server (bajo login del rol) → filas o confirmacion
        │
        ├─ AIAssistant.formatear_respuesta_humana(pregunta, datos)
        │       └─ Convierte filas a texto legible
        │
        └─ Actualizar historial (pregunta + SQL), recortar a 10 entradas
                └─ Mostrar respuesta en chat
```

---

## Decisiones de diseno

**Autenticacion con bcrypt via procedimiento almacenado**
La aplicacion obtiene el hash bcrypt del usuario desde `personas.usuarios` (via `personas.autenticar_usuario`
usando el login auxiliar de solo lectura `SQL_LOGIN_APP`) y verifica la contrasena con `bcrypt.checkpw()`
en Python. El hash nunca se recalcula en SQL Server. El rol queda registrado en la tabla, no derivado del
nombre del login. Los logins de SQL Server son internos a la aplicacion; el usuario final solo ingresa correo y contrasena.

**Proteccion contra fuerza bruta**
`SecurityManager` mantiene un diccionario de clase `_failed_attempts` protegido con `threading.Lock`.
Tras 5 intentos fallidos por correo, el acceso se bloquea 30 segundos. El correo no se registra en logs
de bloqueo para proteger la privacidad del usuario.

**Reconexion por rol tras el login**
Una vez autenticado, la aplicacion selecciona el login de SQL Server correspondiente al rol del usuario y
reconstruye `DatabaseManager` con esas credenciales. Todas las consultas posteriores se ejecutan bajo esa
identidad, activando los permisos del motor de forma transparente.

**Memoria conversacional**
`main.py` mantiene `historial_conversacion` (lista de dicts `{rol, texto}`). Se pasa a
`interpretar_pregunta()` en cada turno. El historial se recorta a los ultimos 10 intercambios y se
reinicia al cambiar de pantalla. Esto permite al asistente recolectar datos en varios pasos antes de
ejecutar una operacion.

**Procesamiento asincronico en la GUI**
El flujo NL->SQL->DB se ejecuta en un hilo secundario (`threading.Thread`, daemon=True) para no bloquear
la UI de Tkinter. Todas las actualizaciones visuales se despachan al hilo principal mediante
`root.after(0, callback)`.

**Fallback de modelos Gemini**
La lista de candidatos permite que la aplicacion funcione aunque un modelo especifico no este disponible
para la API key usada, sin requerir intervencion del usuario.

**Normalizacion de SQL fuera de la GUI**
La limpieza del SQL generado por la IA se concentra en `ConsultaService`, mientras
`ChatController` coordina su uso dentro del flujo conversacional.
Esto mantiene `AIAssistant` desacoplado del formato de respuesta del modelo y a
`BibliotecaApp` enfocada en la presentacion.

**Doble SDK de Google Gemini**
Se mantiene soporte para `google-genai` (SDK nuevo, preferido) y `google-generativeai` (SDK legado,
fallback). Esto garantiza compatibilidad con entornos donde solo uno de los dos esta disponible. La
deteccion es automatica en tiempo de importacion.
