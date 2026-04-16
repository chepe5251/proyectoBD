# Referencia de API Interna

Documentacion de todas las clases y metodos publicos del proyecto.

---

## `config.py`

### Variables exportadas

#### `GEMINI_KEY: str | None`
Clave de autenticacion para la API de Google Gemini.
Origen: variable de entorno `GEMINI_API_KEY`.

> Si esta variable esta ausente o vacia, `config.py` emite una advertencia de log
> y la GUI muestra una pantalla de error al iniciar.

#### Variables de logins de SQL Server

Todas son `str`. Valor por defecto: cadena vacia `""` (no `None`).

| Variable | Descripcion |
|---|---|
| `SQL_LOGIN_APP` / `SQL_PASS_APP` | Login auxiliar; unicamente puede ejecutar `personas.autenticar_usuario` |
| `SQL_LOGIN_ADMIN` / `SQL_PASS_ADMIN` | Login para rol `admin` — acceso completo |
| `SQL_LOGIN_OPERATIVO` / `SQL_PASS_OPERATIVO` | Login para rol `operativo` — SELECT/INSERT/UPDATE/DELETE sin DDL |
| `SQL_LOGIN_USUARIO` / `SQL_PASS_USUARIO` | Login para rol `usuario` — solo SELECT en catalogo y operaciones |

> `DB_SERVER` y `DB_NAME` son leidas directamente por `database_manager.py` via `os.getenv()`.
> No se exportan desde `config.py`.

---

## `database_manager.py`

### Clase `DatabaseManager`

Gestiona la conexion y ejecucion de sentencias en SQL Server via PyODBC.

#### `__init__(uid=None, pwd=None)`

Construye la cadena de conexion ODBC. La cadena resultante nunca se registra en logs.

| Parametro | Tipo | Descripcion |
|---|---|---|
| `uid` | `str \| None` | Login de SQL Server. Si es `None`, usa `DB_USER` del `.env`. |
| `pwd` | `str \| None` | Contrasena. Si es `None`, usa `DB_PASS` del `.env`. |

---

#### `probar_conexion() -> bool`

Intenta abrir una conexion con la cadena actual.

- Retorna `True` si la conexion es exitosa.
- Retorna `False` y registra warning en log si falla (credenciales incorrectas, servidor inaccesible, timeout).
- Uso principal: validar credenciales del rol tras el login.

---

#### `ejecutar_consulta(sql, params=None, max_rows=100) -> list | str | None`

Ejecuta una sentencia T-SQL contra la base de datos.

| Parametro | Tipo | Descripcion |
|---|---|---|
| `sql` | `str` | Sentencia T-SQL a ejecutar. |
| `params` | `tuple \| list \| None` | Valores para los placeholders `?`. |
| `max_rows` | `int` | Maximo de filas a retornar (default 100). |

Retorna:
- `list[Row]` si la sentencia produce un resultset (SELECT, vistas, EXEC con salida).
- `"Operacion completada exitosamente."` para DML/DDL sin resultset.
- `None` si ocurre un error (detalle registrado en el logger del modulo, no en stdout).

> Valida que la cantidad de `?` en el SQL coincida con `len(params)` antes de ejecutar.
> Clasifica los errores en `ProgrammingError`, `OperationalError` y errores genericos de PyODBC.

---

## `seguridad.py`

### Clase `SecurityManager`

Gestiona autenticacion con bcrypt, proteccion contra fuerza bruta y autorizacion RBAC.

#### `__init__(db_manager)`

| Parametro | Tipo | Descripcion |
|---|---|---|
| `db_manager` | `DatabaseManager` | Instancia de la capa de datos (puede ser `None` en el momento del login). |

Atributos de instancia:
- `self.db` — referencia al `DatabaseManager` activo.
- `self.usuario_actual` — `dict` con datos del usuario autenticado, o `None`.

Atributos de clase (compartidos entre instancias):
- `_failed_attempts: dict` — `{correo: (count, lockout_until)}`. Protegido con `threading.Lock`.

---

#### `login(correo, password) -> bool`

Autentica al usuario usando bcrypt. La contrasena nunca se transmite ni almacena en texto plano.

| Parametro | Tipo | Descripcion |
|---|---|---|
| `correo` | `str` | Correo electronico del usuario. |
| `password` | `str` | Contrasena en texto plano (sin strip previo; los espacios son validos). |

Flujo interno:
1. Verifica si el correo esta bloqueado por fuerza bruta (`_esta_bloqueado()`). Si esta bloqueado, retorna `False`.
2. Abre conexion temporal con `SQL_LOGIN_APP` / `SQL_PASS_APP`.
3. Ejecuta `EXEC personas.autenticar_usuario @correo=?` — retorna los datos del usuario incluyendo el `password_hash` almacenado.
4. Si retorna 0 filas → registrar intento fallido → `return False`.
5. Verifica la contrasena con `bcrypt.checkpw(password.encode(), hash_bytes)` en Python.
6. Si no coincide → registrar intento fallido → `return False`.
7. Si coincide → limpiar intentos fallidos, normalizar rol, seleccionar login por rol.
8. Puebla `self.usuario_actual` y retorna `True`.

Ante cualquier error de conexion retorna `False` con registro en log, sin crashear.

Al autenticarse, puebla `self.usuario_actual`:

```python
{
    "id":       1,                # id_usuario de personas.usuarios
    "rol":      "admin",          # rol normalizado ('admin', 'operativo', 'usuario')
    "nombre":   "Alejandro",      # nombre_usuario
    "apellido": "Lopez",          # apellido_usuario
    "correo":   "aleja@mail.com", # correo de la BD
    "uid":      "login_admin",    # login de SQL Server para el rol
    "pwd":      "Admin#2026!",    # contrasena del login de SQL Server
}
```

Mapeo de rol a login de SQL Server:

| Rol | Login seleccionado |
|---|---|
| `admin` o `administrador` | `SQL_LOGIN_ADMIN` |
| `operativo` | `SQL_LOGIN_OPERATIVO` |
| `usuario` | `SQL_LOGIN_USUARIO` |
| Cualquier otro | `SQL_LOGIN_USUARIO` (fallback seguro) |

---

#### `validar_accion(sql_generado) -> bool`

Verifica si el SQL generado por la IA esta permitido para el rol del usuario actual.

| Parametro | Tipo | Descripcion |
|---|---|---|
| `sql_generado` | `str` | Sentencia T-SQL a evaluar. |

Retorna `True` si la accion esta permitida; `False` si debe bloquearse.

**Bloqueado para todos los roles:**

| Condicion | Razon |
|-----------|-------|
| SQL vacio | No hay nada que ejecutar |
| Multiples sentencias separadas por `;` con contenido real | Previene ejecucion encadenada |
| Patrones de SQLi: `OR '1'='1'`, `OR 1=1`, `' OR '`, `--`, `/*`, `*/`, `WAITFOR DELAY`, `XP_CMDSHELL` | Inyeccion SQL clasica |
| Comandos peligrosos: `SHUTDOWN`, `DBCC`, `XACT`, `KILL`, `BULK INSERT`, `OPENROWSET`, `OPENDATASOURCE`, `EXEC XP_`, `EXECUTE XP_` | Riesgo de sistema |

**Bloqueado por rol:**

| Rol | Regla adicional | Comandos extra bloqueados |
|-----|-----------------|--------------------------|
| `usuario` | SQL debe comenzar con SELECT o WITH | INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE, MERGE, GRANT, REVOKE, EXEC, EXECUTE, BACKUP, RESTORE |
| `operativo` | Sin restriccion de inicio | DROP, ALTER, CREATE DATABASE, CREATE TABLE, CREATE SCHEMA, TRUNCATE, GRANT, REVOKE, BACKUP, RESTORE |
| `admin` | Sin restricciones adicionales en la app | — |

---

#### `describir_permisos() -> str`

Retorna una descripcion en texto de los permisos del usuario actual.
Retorna `"Sin sesion activa."` si no hay usuario autenticado.

---

## `ai_assistant.py`

### Clase `AIAssistant`

Controlador de IA para la traduccion de lenguaje natural a T-SQL con memoria conversacional.

#### `__init__()`

Raises:
- `ValueError` — si `GEMINI_API_KEY` no esta configurada en el entorno.
- `ImportError` — si ningun SDK de Google Gemini esta instalado.

Inicializa:
- El cliente Gemini usando `google-genai` como SDK principal. Si en el entorno existe `google-generativeai`, puede usarse como fallback legado.
- La lista de modelos candidatos con fallback automatico.
- El contexto de dominio (`self.contexto`) con el schema completo de la biblioteca.

---

#### `interpretar_pregunta(pregunta_usuario: str, historial: list = None) -> str`

Traduce una pregunta en lenguaje natural a una respuesta T-SQL o prefijo especial.

| Parametro | Tipo | Descripcion |
|---|---|---|
| `pregunta_usuario` | `str` | Texto libre del usuario. |
| `historial` | `list \| None` | Lista de dicts `{"rol": "usuario"\|"asistente", "texto": str}`. Ultimos turnos de la conversacion. |

Retorna uno de los siguientes formatos:

| Formato de retorno | Descripcion |
|---|---|
| Sentencia T-SQL | Consulta o comando SQL ejecutable directamente |
| `PEDIR: <pregunta>` | La IA necesita mas datos del usuario antes de generar el SQL |
| `INSTRUCCION: <mensaje>` | La IA responde con texto sin necesidad de ejecutar SQL |
| `PENDING_HASH: <EXEC ...>` | EXEC con contrasena en texto plano que debe hashearse con bcrypt antes de ejecutar |

Raises:
- `AIQuotaExceededError` — si Gemini retorna 429 (cuota agotada). Incluye `retry_after_seconds`.
- `AIServiceError` — para cualquier otro error de la API.

El metodo intenta cada modelo en `self.model_candidates`. Si un modelo retorna 404, avanza al siguiente. Si todos fallan, lanza `AIServiceError`.

---

#### `formatear_respuesta_humana(pregunta_usuario, datos_db) -> str`

Convierte resultados crudos de la base de datos en texto legible para el usuario final.

| Parametro | Tipo | Descripcion |
|---|---|---|
| `pregunta_usuario` | `str` | Pregunta original (para inferir la entidad y contexto). |
| `datos_db` | `list \| str \| None` | Resultado de `DatabaseManager.ejecutar_consulta`. |

Logica de formateo:
- `None` → mensaje de error generico.
- `str` → se retorna tal cual (confirmaciones de DML como "Operacion completada exitosamente.").
- Lista vacia → "No encontre resultados...".
- 1 fila, 1 columna → interpretado como escalar (COUNT, SUM, etc.) con contexto de entidad inferido.
- N filas, 1 columna → lista de valores separados por coma (maximo 10, con sufijo "y N mas").
- N filas, N columnas → tabla compacta con separador ` · ` y prefijo `—`, limitada a 5 filas.

---

### Clase `AIServiceError(RuntimeError)`

Error generico de integracion con el servicio de Gemini.

---

### Clase `AIQuotaExceededError(AIServiceError)`

Error de cuota agotada (HTTP 429).

#### Atributos

| Atributo | Tipo | Descripcion |
|---|---|---|
| `retry_after_seconds` | `int \| None` | Segundos sugeridos antes de reintentar. `None` si no se pudo determinar desde la respuesta de la API. |

---

## `app_services.py`

### Clase `RegistroUsuarioService`

Centraliza la validacion del formulario de registro, la generacion del hash bcrypt y la construccion
del `EXEC personas.registrar_usuario` reutilizado por GUI y por `PENDING_HASH:`.

### Clase `ConsultaService`

Convierte una respuesta de IA en una `ConsultaPreparada` reutilizable fuera de Tkinter.

Responsabilidades principales:
- Normalizar SQL generado por Gemini.
- Resolver `PENDING_HASH:` sin duplicar la logica de registro.
- Enmascarar `@password_hash` en el SQL visible.
- Aplicar `TOP 100` a `SELECT` sin limite.

---

## `chat_controller.py`

### Clase `ChatController`

Controller de negocio del flujo conversacional. No depende de Tkinter ni de callbacks de UI.

Responsabilidades principales:
- Resolver cuota de IA y traducir errores del asistente a resultados estructurados.
- Interpretar `PEDIR:`, `INSTRUCCION:` y `PENDING_HASH:`.
- Delegar preparacion SQL a `ConsultaService`.
- Validar permisos con `SecurityManager` y ejecutar con `DatabaseManager`.
- Devolver un `ResultadoConsulta` con mensajes, SQL visible, estado e historial.

### Dataclasses

- `MensajeChat`: mensaje listo para renderizar en la GUI.
- `EntradaHistorial`: entrada de memoria conversacional para el siguiente turno.
- `ResultadoConsulta`: salida estructurada del controller.

---

## `main.py`

### Clase `BibliotecaApp`

Controlador principal de la interfaz grafica (Tkinter). Orquesta todas las capas.

#### `__init__(root)`

| Parametro | Tipo | Descripcion |
|---|---|---|
| `root` | `tk.Tk` | Ventana raiz de Tkinter. |

Inicializa el tema visual, los atributos de servicio (`self.db`, `self.asistente`, `self.seguridad`),
el historial conversacional (`self.historial_conversacion = []`) y el texto placeholder del campo de entrada.
Si `GEMINI_KEY` esta ausente, muestra `pantalla_error_config()`; si no, muestra `pantalla_login()`.

---

#### `pantalla_login()`

Renderiza el formulario de autenticacion: panel informativo (izquierda) con emoji 📚, separador
vertical, y formulario (derecha) con campos de correo y contrasena con bordes visibles.
La card queda centrada en la ventana con `place(relx=0.5, rely=0.5, anchor="center")`.

---

#### `pantalla_registro()`

Renderiza el formulario de registro de usuario nuevo con Canvas scrollable.
El scroll de rueda se activa solo mientras el cursor esta sobre el canvas, evitando bindings globales residuales.
Asigna rol `usuario` por defecto. La validacion, el hashing bcrypt y la construccion del `EXEC personas.registrar_usuario`
se comparten con el flujo conversacional `PENDING_HASH:`.

---

#### `pantalla_asistente()`

Renderiza la ventana principal de chat:
- Panel izquierdo (≈65%): area de mensajes con burbujas, botones de consulta rapida segun rol, campo de entrada con placeholder.
- Panel derecho (≈35%): SQL generado en tiempo real, modelo activo, estado de conexion, estado de ejecucion.
- Separador horizontal de 2px en color accent bajo la barra superior.

---

#### `procesar_consulta()`

Punto de entrada del flujo de consulta. Llamado al presionar Enter o el boton "Enviar ➤".
Verifica que el campo no tenga el placeholder antes de procesar.
Deshabilita los controles de entrada y lanza `_procesar_consulta_async()` en un hilo secundario.

---

#### `_procesar_consulta_async(pregunta)`

Puente asincronico entre Tkinter y `ChatController`.

1. Toma un snapshot de `historial_conversacion` y `ai_blocked_until`.
2. Invoca `ChatController.procesar_consulta(...)` fuera del hilo principal.
3. Reinyecta el `ResultadoConsulta` a Tkinter con `root.after(0, ...)`.
4. Delega la actualizacion visual a `_aplicar_resultado_consulta()` y el cierre de estado a `_finalizar_consulta()`.

---

#### `_finalizar_consulta()`

Restaura el estado de la UI tras completar una consulta (siempre en hilo principal).
Habilita controles, actualiza el indicador de estado y devuelve el foco al campo de entrada.

---

#### `mostrar_sql(sql, modelo, estado="")`

Actualiza el panel lateral derecho con el SQL generado, el modelo activo y el estado de ejecucion.

---

#### `mostrar_en_chat(mensaje, autor="Asistente")`

Agrega un mensaje al area de chat con estilo de burbuja segun el autor.

| Autor | Tag de burbuja | Color de fondo |
|---|---|---|
| `Tu` (usuario) | `burbuja_user` | Azul `#1d4ed8`, alineada a la derecha |
| `Sistema` | `burbuja_sistema` | Gris `#292524`, centrada con margenes |
| `Asistente` | `burbuja_asistente` | Oscuro `#1f2937`, alineada a la izquierda |

#### `_on_entry_focus_in(_event)` / `_on_entry_focus_out(_event)`

Gestionan el comportamiento del placeholder en el campo de pregunta.
Al recibir foco, limpian el placeholder y restauran el color del texto.
Al perder foco con el campo vacio, reinsertan el placeholder en color muted.
