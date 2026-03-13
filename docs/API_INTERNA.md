# Referencia de API Interna

Documentacion de todas las clases y metodos publicos del proyecto.

---

## `config.py`

### Variables exportadas

#### `GEMINI_KEY: str | None`
Clave de autenticacion para la API de Google Gemini.
Origen: variable de entorno `GEMINI_API_KEY`.

#### `DB_CONFIG: dict[str, str | None]`
Parametros de conexion a SQL Server.

| Llave | Variable de entorno | Descripcion |
|---|---|---|
| `server` | `DB_SERVER` | Host o nombre de la instancia SQL Server |
| `database` | `DB_NAME` | Nombre del catalogo (`biblioteca`) |
| `user` | `DB_USER` | Login de SQL Server por defecto |
| `pass` | `DB_PASS` | Contrasena del login por defecto |

---

## `database_manager.py`

### Clase `DatabaseManager`

Gestiona la conexion y ejecucion de sentencias en SQL Server via PyODBC.

#### `__init__(uid=None, pwd=None)`

Construye la cadena de conexion ODBC.

| Parametro | Tipo | Descripcion |
|---|---|---|
| `uid` | `str \| None` | Login de SQL Server. Si es `None`, usa `DB_USER` del `.env`. |
| `pwd` | `str \| None` | Contrasena. Si es `None`, usa `DB_PASS` del `.env`. |

---

#### `probar_conexion() -> bool`

Intenta abrir una conexion con la cadena actual.

- Retorna `True` si la conexion es exitosa.
- Retorna `False` si falla (credenciales incorrectas, servidor inaccesible, etc.).
- Uso principal: validar credenciales durante el login.

---

#### `ejecutar_consulta(sql, params=None) -> list | str | None`

Ejecuta una sentencia SQL contra la base de datos.

| Parametro | Tipo | Descripcion |
|---|---|---|
| `sql` | `str` | Sentencia T-SQL a ejecutar. |
| `params` | `tuple \| list \| None` | Valores para los placeholders `?`. |

Retorna:
- `list[Row]` si la sentencia produce un resultset (SELECT, vistas, EXEC con salida).
- `"Operacion completada exitosamente."` para DML/DDL sin resultset.
- `None` si ocurre un error (detalle impreso en consola).

> El metodo valida que la cantidad de `?` en el SQL coincida con la longitud de `params` antes de ejecutar.

---

## `seguridad.py`

### Clase `SecurityManager`

Gestiona autenticacion y autorizacion basada en roles.

#### `__init__(db_manager)`

| Parametro | Tipo | Descripcion |
|---|---|---|
| `db_manager` | `DatabaseManager` | Instancia de la capa de datos. |

Atributos de instancia:
- `self.db` — referencia al `DatabaseManager` activo.
- `self.usuario_actual` — `dict` con datos del usuario autenticado, o `None`.

---

#### `login(usuario, password) -> bool`

Autentica al usuario probando una conexion directa a SQL Server.

| Parametro | Tipo | Descripcion |
|---|---|---|
| `usuario` | `str` | Login de SQL Server (ej. `login_admin`). |
| `password` | `str` | Contrasena del login. |

Retorna `True` si la conexion tiene exito; `False` en caso contrario.

Al autenticarse, puebla `self.usuario_actual`:

```python
{
    "id":     None,            # No aplica (auth via SQL Server)
    "rol":    "admin",         # Inferido del nombre del login
    "nombre": "login_admin",   # Nombre del login
    "uid":    "login_admin",   # Para reconectar DatabaseManager
    "pwd":    "admin123",
}
```

Mapeo de login a rol:

| Login | Rol |
|---|---|
| `login_admin` | `admin` |
| `login_operativo` | `operativo` |
| `login_usuario` | `usuario` |
| Cualquier otro | `usuario` |

---

#### `validar_accion(sql_generado) -> bool`

Verifica si el SQL generado por la IA esta permitido para el rol del usuario actual.

| Parametro | Tipo | Descripcion |
|---|---|---|
| `sql_generado` | `str` | Sentencia T-SQL a evaluar. |

Retorna `True` si la accion esta permitida; `False` si debe bloquearse.

Reglas por rol:

| Rol | Comandos bloqueados |
|---|---|
| `usuario` / `cliente` | INSERT, UPDATE, DELETE, DROP, ALTER |
| `operativo` | DROP, ALTER, CREATE DATABASE |
| `admin` | Ninguno |

---

#### `describir_permisos() -> str`

Retorna una descripcion en texto de los permisos del usuario actual.
Retorna `"Sin sesion activa."` si no hay usuario autenticado.

---

## `ai_assistant.py`

### Clase `AIAssistant`

Controlador de IA para la traduccion de lenguaje natural a T-SQL.

#### `__init__()`

Raises:
- `ValueError` — si `GEMINI_API_KEY` no esta configurada en el entorno.
- `ImportError` — si ningun SDK de Google Gemini esta instalado.

Inicializa:
- El cliente Gemini (SDK nuevo o legado segun disponibilidad).
- La lista de modelos candidatos con fallback automatico.
- El contexto de dominio (`self.contexto`) con el schema de la biblioteca.

---

#### `interpretar_pregunta(pregunta_usuario: str) -> str`

Traduce una pregunta en lenguaje natural a una sentencia T-SQL.

| Parametro | Tipo | Descripcion |
|---|---|---|
| `pregunta_usuario` | `str` | Texto libre del usuario. |

Retorna la sentencia T-SQL generada (texto plano, sin markdown).

Raises:
- `AIQuotaExceededError` — si Gemini retorna 429 (cuota agotada). Incluye `retry_after_seconds`.
- `AIServiceError` — para cualquier otro error de la API.

El metodo intenta cada modelo en `self.model_candidates`. Si un modelo retorna 404, avanza al siguiente. Si todos fallan, lanza `AIServiceError`.

---

#### `formatear_respuesta_humana(pregunta_usuario, datos_db) -> str`

Convierte resultados crudos de la base de datos en texto legible.

| Parametro | Tipo | Descripcion |
|---|---|---|
| `pregunta_usuario` | `str` | Pregunta original (para inferir contexto). |
| `datos_db` | `list \| str \| None` | Resultado de `DatabaseManager.ejecutar_consulta`. |

Logica de formateo:
- `None` → mensaje de error generico.
- `str` → se retorna tal cual (confirmaciones de DML).
- Lista vacia → "No encontre resultados...".
- 1 fila, 1 columna → interpretado como escalar (COUNT, etc.).
- N filas, 1 columna → lista de valores separados por coma.
- N filas, N columnas → tabla compacta con separador `|`, limitada a 5 filas.

---

### Clase `AIServiceError(RuntimeError)`

Error generico de integracion con el servicio de Gemini.

---

### Clase `AIQuotaExceededError(AIServiceError)`

Error de cuota agotada (HTTP 429).

#### Atributos

| Atributo | Tipo | Descripcion |
|---|---|---|
| `retry_after_seconds` | `int \| None` | Segundos sugeridos antes de reintentar. `None` si no se pudo determinar. |

---

## `main.py`

### Clase `BibliotecaApp`

Controlador principal de la interfaz grafica (Tkinter).

#### `__init__(root)`

| Parametro | Tipo | Descripcion |
|---|---|---|
| `root` | `tk.Tk` | Ventana raiz de Tkinter. |

Inicializa los servicios (`DatabaseManager`, `AIAssistant`) y muestra la pantalla de login.

---

#### `pantalla_login()`

Renderiza el formulario de autenticacion con dos paneles: informativo (izquierda) y formulario (derecha).

---

#### `ejecutar_login()`

Lee las credenciales del formulario, autentica via `SecurityManager.login()` y, si tiene exito:
1. Reconstruye `self.db` con las credenciales del usuario.
2. Actualiza `self.seguridad.db` para que apunte al nuevo `DatabaseManager`.
3. Navega a `pantalla_asistente()`.

---

#### `pantalla_asistente()`

Renderiza la ventana principal de chat con: barra de estado, area de mensajes, botones de consulta rapida y campo de entrada.

---

#### `procesar_consulta()`

Flujo principal de procesamiento. Llamado al presionar Enter o el boton Enviar.

1. Verifica bloqueo de cuota de IA.
2. Llama a `AIAssistant.interpretar_pregunta()`.
3. Normaliza el SQL con `_normalizar_sql()`.
4. Valida la accion con `SecurityManager.validar_accion()`.
5. Ejecuta con `DatabaseManager.ejecutar_consulta()`.
6. Formatea y muestra el resultado.

Bloquea los controles de entrada durante el procesamiento y los restaura en el bloque `finally`.

---

#### `_normalizar_sql(sql_generado) -> str` _(estatico)_

Limpia el texto retornado por Gemini y extrae el SQL ejecutable.

Transformaciones aplicadas:
- Extrae contenido de bloques ` ```sql ... ``` `.
- Elimina el prefijo `SQL:`.
- Convierte identificadores con backticks a corchetes `[nombre]` o los elimina si son palabras clave SQL.
- Reemplaza backticks restantes por comillas simples.
- Recorta el texto desde la primera palabra clave SQL valida (SELECT, EXEC, WITH).

---

#### `mostrar_en_chat(mensaje, autor="Asistente")`

Agrega un bloque de mensaje al area de chat con formato y color segun el autor.

| Autor | Color del encabezado |
|---|---|
| Tu (usuario) | Azul (`#93c5fd`) |
| Sistema | Amarillo/naranja (`#f59e0b`) |
| Asistente | Teal (`#2dd4bf`) |
