# Biblioteca Inteligente — Asistente SQL con IA

Aplicacion de escritorio que permite consultar y gestionar una base de datos de biblioteca mediante lenguaje natural. El usuario escribe preguntas en español; la IA las convierte a T-SQL y el sistema las ejecuta sobre SQL Server mostrando los resultados de forma legible.

---

## Tabla de contenidos

1. [Descripcion general](#1-descripcion-general)
2. [Arquitectura](#2-arquitectura)
3. [Estructura del repositorio](#3-estructura-del-repositorio)
4. [Schema de la base de datos](#4-schema-de-la-base-de-datos)
5. [Seguridad y roles](#5-seguridad-y-roles)
6. [Requisitos](#6-requisitos)
7. [Instalacion](#7-instalacion)
8. [Configuracion](#8-configuracion)
9. [Ejecucion](#9-ejecucion)
10. [Uso de la aplicacion](#10-uso-de-la-aplicacion)
11. [Manejo de errores](#11-manejo-de-errores)

---

## 1. Descripcion general

El proyecto implementa un asistente conversacional con las siguientes capacidades:

- Traduccion de lenguaje natural a T-SQL usando Google Gemini.
- Autenticacion con correo y contrasena verificados contra `personas.usuarios` via SHA-256 y procedimiento almacenado.
- Control de acceso basado en roles (RBAC) en dos niveles: motor de SQL Server y capa de aplicacion.
- Interfaz grafica oscura construida con Tkinter con procesamiento en hilo secundario (sin bloqueo de UI).
- Formateo de resultados en texto legible para el usuario final.

---

## 2. Arquitectura

```
Usuario
  │
  ▼
┌─────────────────────────────────────────┐
│  main.py  —  GUI Tkinter (BibliotecaApp) │
│  · Pantalla de login                     │
│  · Pantalla de chat                      │
└────────────┬────────────────────────────┘
             │ orquesta
    ┌────────┼────────────┐
    ▼        ▼            ▼
seguridad  ai_assistant  database_manager
    │          │              │
    │   Google Gemini API   PyODBC
    │                         │
    └──────── SQL Server ──────┘
                 biblioteca
```

**Flujo de una consulta:**

1. El usuario escribe una pregunta en lenguaje natural.
2. `AIAssistant.interpretar_pregunta()` llama a Gemini y obtiene T-SQL.
3. `BibliotecaApp._normalizar_sql()` limpia el texto (quita markdown, backticks, etc.).
4. `SecurityManager.validar_accion()` verifica que el SQL sea permitido para el rol del usuario.
5. `DatabaseManager.ejecutar_consulta()` ejecuta el SQL en SQL Server bajo las credenciales del usuario.
6. `AIAssistant.formatear_respuesta_humana()` convierte las filas en texto legible.
7. El resultado se muestra en el chat.

---

## 3. Estructura del repositorio

```
proyectoBD/
├── main.py               # Punto de entrada y GUI completa (Tkinter)
├── ai_assistant.py       # Capa de IA: NL -> T-SQL via Google Gemini
├── database_manager.py   # Capa de datos: conexion y ejecucion en SQL Server
├── seguridad.py          # Autenticacion y autorizacion RBAC
├── config.py             # Carga centralizada de variables de entorno
├── requirements.txt      # Dependencias Python
├── .env                  # Variables de entorno (no versionar)
├── docs/
│   ├── ARQUITECTURA.md   # Detalle tecnico de la arquitectura
│   └── API_INTERNA.md    # Referencia de clases y metodos publicos
└── README.md             # Este archivo
```

---

## 4. Schema de la base de datos

Base de datos: `biblioteca` en SQL Server.

### Tablas

| Tabla | Columnas principales |
|---|---|
| `personas.usuarios` | id_usuario, nombre_usuario, apellido_usuario, correo, telefono, password_hash, rol |
| `catalogo.autores` | id_autor, nombre_autor, apellido_autor, nacionalidad |
| `catalogo.categorias` | id_categoria, nombre_categoria, descripcion |
| `catalogo.libros` | id_libro, titulo, ano_publicacion, id_autor, id_categoria |
| `operaciones.prestamos` | id_prestamo, id_usuario, id_libro, fecha_prestamo, fecha_devolucion, estado |

> `estado` en prestamos: `1` = prestamo activo, `0` = devuelto.

### Vistas

| Vista | Descripcion |
|---|---|
| `catalogo.vista_libros_completa` | Libro con nombre de autor y categoria |
| `operaciones.vista_prestamos_activos` | Prestamos pendientes de devolucion |

### Procedimientos almacenados

| Procedimiento | Parametros |
|---|---|
| `personas.autenticar_usuario` | @correo, @password_hash — retorna fila con id, nombre, apellido, correo, rol |
| `personas.registrar_usuario` | @nombre, @apellido, @correo, @telefono |
| `operaciones.registrar_prestamo` | @id_usuario, @id_libro |
| `operaciones.devolver_libro` | @id_prestamo |
| `catalogo.buscar_libro` | @palabra |

---

## 5. Seguridad y roles

### Flujo de autenticacion

1. El usuario ingresa **correo electronico** y **contrasena** en la GUI.
2. La app calcula `hashlib.sha256(password.encode()).hexdigest()` (64 caracteres hex, minusculas).
3. Abre una conexion temporal con el login auxiliar `SQL_LOGIN_APP` (permisos minimos: solo puede ejecutar `personas.autenticar_usuario`).
4. Ejecuta `EXEC personas.autenticar_usuario @correo=?, @password_hash=?`.
5. Si retorna 0 filas → acceso denegado.
6. Si retorna 1 fila → lee `id_usuario`, `nombre_usuario`, `apellido_usuario`, `correo` y `rol`.
7. Selecciona el login de SQL Server correspondiente al rol y reconstruye `DatabaseManager` con esas credenciales.

### Roles y logins internos

| Rol en BD | Login de SQL Server | Permisos en el motor |
|-----------|--------------------|--------------------|
| `admin` | `login_admin` | SELECT, INSERT, UPDATE, DELETE en todos los esquemas |
| `operativo` | `login_operativo` | SELECT, INSERT, UPDATE en personas/catalogo/operaciones |
| `usuario` | `login_usuario` | Solo SELECT en catalogo y vista de prestamos activos |

Los logins de SQL Server son **internos**: el usuario final nunca los ve ni los ingresa.

### Segunda linea de defensa — capa de aplicacion

`seguridad.py` bloquea comandos antes de enviarlos al motor:

| Rol | Comandos bloqueados en aplicacion |
|-----|----------------------------------|
| `usuario` | INSERT, UPDATE, DELETE, DROP, ALTER |
| `operativo` | DROP, ALTER, CREATE DATABASE |
| `admin` | Ninguno |

---

## 6. Requisitos

- Python 3.11 o superior.
- SQL Server con la base de datos `biblioteca` creada y poblada.
- ODBC Driver 17 for SQL Server instalado en el sistema.
- Clave de API de Google Gemini.

---

## 7. Instalacion

```bash
# Crear entorno virtual
python -m venv .venv

# Activar (Windows PowerShell)
.venv\Scripts\Activate.ps1

# Instalar dependencias
pip install -r requirements.txt
```

Dependencias declaradas en `requirements.txt`:

```
google-genai
google-generativeai
python-dotenv
pyodbc
```

---

## 8. Configuracion

Crear un archivo `.env` en la raiz del proyecto con el siguiente contenido:

```env
# Google Gemini
GEMINI_API_KEY=tu_clave_de_gemini

# Conexion base SQL Server (servidor e instancia)
DB_SERVER=nombre_del_servidor
DB_NAME=biblioteca

# Login auxiliar — solo ejecuta personas.autenticar_usuario
SQL_LOGIN_APP=login_app
SQL_PASS_APP=AppPass#2026!

# Logins operacionales por rol (la app los selecciona tras autenticar)
SQL_LOGIN_ADMIN=login_admin
SQL_PASS_ADMIN=Admin#2026!
SQL_LOGIN_OPERATIVO=login_operativo
SQL_PASS_OPERATIVO=Operativo#2026!
SQL_LOGIN_USUARIO=login_usuario
SQL_PASS_USUARIO=Usuario#2026!
```

> Las credenciales de los logins de SQL Server **nunca** se ingresan en la GUI. Solo el correo y la contrasena del usuario de la biblioteca son visibles en la pantalla de login.

---

## 9. Ejecucion

```bash
python main.py
```

---

## 10. Uso de la aplicacion

### Login

Ingresar el correo electronico y la contrasena del usuario registrado en `personas.usuarios`:

```
Correo electronico: aleja@mail.com
Contrasena:         tu_contrasena
```

El sistema verifica las credenciales contra la base de datos via SHA-256 y selecciona automaticamente el login de SQL Server correspondiente al rol del usuario.

### Chat

Escribir preguntas en lenguaje natural. Ejemplos:

```
¿Cuantos libros hay registrados?
Mostrar los prestamos activos
Libros de Gabriel Garcia Marquez
¿Que libros hay de categoria Tecnologia?
Registrar prestamo para el usuario 3 del libro 5
```

Los botones de consulta rapida en la barra inferior envian preguntas predefinidas directamente.

---

## 11. Manejo de errores

| Situacion | Comportamiento |
|---|---|
| Correo o contrasena incorrectos | Mensaje de error en el login, sin acceso |
| Login auxiliar `SQL_LOGIN_APP` inaccesible | Error en consola, acceso denegado sin crashear |
| Cuota de Gemini agotada (429) | Mensaje con tiempo de espera, input bloqueado temporalmente |
| Modelo de Gemini no disponible (404) | Fallback automatico al siguiente candidato en la lista |
| Import de `google-genai` lento/colgado | Fallback automatico a `google-generativeai` (legacy SDK) |
| SQL con placeholder `?` sin valor | Mensaje indicando reformular la pregunta |
| Accion no permitida por el rol | Mensaje explicando los permisos del rol actual |
| Error de base de datos | Mensaje en el chat, detalle en consola |
