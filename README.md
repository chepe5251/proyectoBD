# Biblioteca Inteligente — Asistente SQL con IA

Aplicacion de escritorio que permite consultar y gestionar una base de datos de biblioteca mediante lenguaje natural. El usuario escribe preguntas en español; Google Gemini las convierte a T-SQL y el sistema las ejecuta sobre SQL Server mostrando los resultados en texto legible.

---

## Tabla de contenidos

1. [Descripcion general](#1-descripcion-general)
2. [Arquitectura](#2-arquitectura)
3. [Estructura del repositorio](#3-estructura-del-repositorio)
4. [Base de datos](#4-base-de-datos)
5. [Seguridad y roles](#5-seguridad-y-roles)
6. [Requisitos previos](#6-requisitos-previos)
7. [Instalacion](#7-instalacion)
8. [Configuracion del archivo .env](#8-configuracion-del-archivo-env)
9. [Crear la base de datos](#9-crear-la-base-de-datos)
10. [Ejecucion](#10-ejecucion)
11. [Uso de la aplicacion](#11-uso-de-la-aplicacion)
12. [Usuarios de prueba](#12-usuarios-de-prueba)
13. [Manejo de errores](#13-manejo-de-errores)

---

## 1. Descripcion general

El proyecto implementa un asistente conversacional con las siguientes capacidades:

- **Lenguaje natural a SQL**: Google Gemini traduce preguntas en español a sentencias T-SQL ejecutables.
- **Autenticacion segura**: correo y contraseña verificados contra `personas.usuarios` con hash bcrypt (rounds=12). La comparacion se realiza en Python, nunca en SQL Server.
- **Control de acceso por roles (RBAC)** en dos niveles: permisos del motor SQL Server y capa de validacion en la aplicacion.
- **Proteccion contra fuerza bruta**: bloqueo automatico de 30 segundos tras 5 intentos fallidos consecutivos por correo.
- **Panel SQL en tiempo real**: muestra la consulta generada por la IA, el modelo usado y el estado de ejecucion.
- **Registro de nuevos usuarios** directamente desde la aplicacion.
- **Interfaz grafica** oscura construida con Tkinter, procesamiento en hilo secundario (la ventana nunca se congela).

---

## 2. Arquitectura

```
Usuario
  │
  ▼
┌────────────────────────────────────────────────────┐
│  main.py — GUI Tkinter (BibliotecaApp)             │
│  · Pantalla de login / registro / error config     │
│  · Chat (panel izquierdo 65%)                      │
│  · Panel SQL en tiempo real (panel derecho 35%)    │
└──────────┬─────────────────────────────────────────┘
           │ orquesta
   ┌───────┼────────────┐
   ▼       ▼            ▼
seguridad  ai_assistant  database_manager
   │           │               │
   │    Google Gemini API    PyODBC
   │                            │
   └──────── SQL Server ────────┘
                biblioteca
```

### Flujo de una consulta

```
[Usuario escribe pregunta]
        │
        ▼
AIAssistant.interpretar_pregunta()   ← llama a Google Gemini
        │ devuelve texto con SQL
        ▼
BibliotecaApp._normalizar_sql()      ← limpia markdown, backticks, prefijos
        │ devuelve T-SQL limpio
        ▼
mostrar_sql()                        ← actualiza panel derecho con SQL generado
        │
        ▼
SecurityManager.validar_accion()     ← verifica permisos del rol (RBAC capa 2)
        │ si bloqueado → muestra mensaje y termina
        ▼
Inyectar TOP 100 si SELECT sin TOP   ← evita traer tablas completas
        │
        ▼
DatabaseManager.ejecutar_consulta()  ← ejecuta en SQL Server bajo login del rol
        │ devuelve filas (max 100)
        ▼
AIAssistant.formatear_respuesta_humana()  ← convierte filas en texto legible
        │
        ▼
[Se muestra resultado en el chat]
```

---

## 3. Estructura del repositorio

```
proyectoBD/
├── main.py               # Punto de entrada y GUI completa (Tkinter)
├── ai_assistant.py       # Capa de IA: lenguaje natural → T-SQL via Google Gemini
├── database_manager.py   # Capa de datos: conexion y ejecucion en SQL Server
├── seguridad.py          # Autenticacion bcrypt, RBAC y proteccion fuerza bruta
├── config.py             # Carga centralizada de variables de entorno (.env)
├── database.sql          # Script completo de la base de datos (DDL + datos iniciales)
├── iniciar.vbs           # Lanzador de Windows (sin ventana de consola)
├── requirements.txt      # Dependencias Python con versiones exactas
├── .env                  # Variables de entorno con credenciales (NO versionar)
├── .gitignore            # Excluye .env y .venv del repositorio
├── docs/
│   ├── ARQUITECTURA.md   # Detalle tecnico de la arquitectura
│   └── API_INTERNA.md    # Referencia de clases y metodos publicos
└── README.md             # Este archivo
```

> `.env` esta en `.gitignore` y **nunca** debe subirse al repositorio.

---

## 4. Base de datos

Base de datos: `biblioteca` en SQL Server. El script completo esta en [`database.sql`](database.sql).

### Schemas

| Schema | Proposito |
|--------|-----------|
| `personas` | Usuarios del sistema |
| `catalogo` | Autores, categorias y libros |
| `operaciones` | Prestamos y devoluciones |

### Tablas

#### `personas.usuarios`
Almacena los usuarios que pueden iniciar sesion en la aplicacion.

| Columna | Tipo | Descripcion |
|---------|------|-------------|
| `id_usuario` | INT IDENTITY PK | Identificador unico |
| `nombre_usuario` | VARCHAR(100) | Nombre |
| `apellido_usuario` | VARCHAR(100) | Apellido |
| `correo` | VARCHAR(150) UNIQUE | Correo electronico (usado para login) |
| `telefono` | VARCHAR(20) | Telefono (min. 8 caracteres) |
| `password_hash` | VARCHAR(72) | Hash bcrypt de la contraseña |
| `rol` | VARCHAR(20) | Rol del usuario: `admin`, `operativo` o `usuario` |

#### `catalogo.autores`
| Columna | Tipo | Descripcion |
|---------|------|-------------|
| `id_autor` | INT IDENTITY PK | Identificador unico |
| `nombre_autor` | VARCHAR(100) | Nombre del autor |
| `apellido_autor` | VARCHAR(100) | Apellido del autor |
| `nacionalidad` | VARCHAR(100) | Pais de origen |

#### `catalogo.categorias`
| Columna | Tipo | Descripcion |
|---------|------|-------------|
| `id_categoria` | INT IDENTITY PK | Identificador unico |
| `nombre_categoria` | VARCHAR(100) | Nombre de la categoria |
| `descripcion` | VARCHAR(200) | Descripcion de la categoria |

#### `catalogo.libros`
| Columna | Tipo | Descripcion |
|---------|------|-------------|
| `id_libro` | INT IDENTITY PK | Identificador unico |
| `titulo` | VARCHAR(200) | Titulo del libro |
| `ano_publicacion` | INT | Año de publicacion (1500 - año actual) |
| `id_autor` | INT FK | Referencia a `catalogo.autores` |
| `id_categoria` | INT FK | Referencia a `catalogo.categorias` |

#### `operaciones.prestamos`
| Columna | Tipo | Descripcion |
|---------|------|-------------|
| `id_prestamo` | INT IDENTITY PK | Identificador unico |
| `id_usuario` | INT FK | Usuario que solicito el prestamo |
| `id_libro` | INT FK | Libro prestado |
| `fecha_prestamo` | DATE | Fecha en que se realizo el prestamo |
| `fecha_limite` | DATE | Fecha maxima de devolucion (`fecha_prestamo` + dias configurados) |
| `fecha_devolucion` | DATE | Fecha real de devolucion (NULL si aun no devuelto) |
| `estado` | BIT | `1` = prestamo activo, `0` = devuelto |

### Vistas

| Vista | Descripcion |
|-------|-------------|
| `catalogo.vista_libros_completa` | Libro con nombre completo del autor y nombre de la categoria |
| `operaciones.vista_prestamos_activos` | Prestamos activos con nombre del usuario, titulo y fecha limite |
| `operaciones.vista_prestamos_vencidos` | Prestamos activos cuya fecha limite ya paso, con dias de retraso |

### Procedimientos almacenados

| Procedimiento | Parametros | Descripcion |
|---------------|------------|-------------|
| `personas.autenticar_usuario` | `@correo` | Retorna datos del usuario por correo. La app compara el hash bcrypt en Python. |
| `personas.registrar_usuario` | `@nombre, @apellido, @correo, @telefono, @password_hash, @rol` | Inserta un nuevo usuario. El hash bcrypt se genera en Python antes de llamar. |
| `operaciones.registrar_prestamo` | `@id_usuario, @id_libro, @dias_prestamo=15` | Registra un nuevo prestamo. `fecha_limite` se calcula automaticamente. |
| `operaciones.devolver_libro` | `@id_prestamo` | Marca el prestamo como devuelto y registra la fecha. |
| `catalogo.buscar_libro` | `@palabra` | Busca libros cuyo titulo contenga la palabra clave. |

### Indices

| Indice | Tabla | Columna | Para que sirve |
|--------|-------|---------|----------------|
| `IX_BusquedaTitulo` | `catalogo.libros` | `titulo` | Acelera busquedas por titulo (LIKE) desde el asistente IA |
| `IX_BuscarPrestamoUsuario` | `operaciones.prestamos` | `id_usuario` | Acelera consultas de historial y prestamos activos por usuario |
| `IX_LoginCorreo` | `personas.usuarios` | `correo` | Acelera el login (WHERE correo = ?) en cada autenticacion |

---

## 5. Seguridad y roles

### Flujo de autenticacion

```
[Usuario ingresa correo + contraseña]
        │
        ▼
¿Correo bloqueado por fuerza bruta?  → SI: acceso denegado (muestra segundos restantes)
        │ NO
        ▼
Conexion con login_app (solo puede ejecutar personas.autenticar_usuario)
        │
        ▼
EXEC personas.autenticar_usuario @correo=?
        │ devuelve: id, nombre, apellido, correo, rol, password_hash
        │ si 0 filas → registrar intento fallido → acceso denegado
        ▼
bcrypt.checkpw(contraseña_ingresada, hash_almacenado)
        │ si no coincide → registrar intento fallido → acceso denegado
        ▼
5 intentos fallidos → bloqueo de 30 segundos por correo
        │ si coincide → limpiar intentos fallidos
        ▼
Seleccionar login de SQL Server segun rol del usuario
        │
        ▼
[Sesion abierta con DatabaseManager usando el login del rol]
```

### Logins internos de SQL Server

El usuario final **nunca ve ni ingresa** estas credenciales. La aplicacion las usa internamente:

| Login | Proposito | Permisos |
|-------|-----------|---------|
| `login_app` | Autenticacion inicial | Solo EXECUTE en `personas.autenticar_usuario` |
| `login_admin` | Sesion de administrador | SELECT, INSERT, UPDATE, DELETE en todos los schemas |
| `login_operativo` | Sesion operativa | SELECT, INSERT, UPDATE en personas; SELECT/INSERT/UPDATE/DELETE en catalogo y operaciones |
| `login_usuario` | Sesion de lectura | Solo SELECT en catalogo y operaciones |

### RBAC en la aplicacion (segunda capa de defensa)

`SecurityManager.validar_accion()` verifica el SQL antes de enviarlo al motor:

| Rol | Regla adicional | Comandos bloqueados |
|-----|-----------------|---------------------|
| `usuario` | Debe iniciar con SELECT o WITH | INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE, MERGE, GRANT, REVOKE, EXEC, BACKUP, RESTORE |
| `operativo` | Sin restriccion de tipo | DROP, ALTER, CREATE DATABASE/TABLE/SCHEMA, TRUNCATE, GRANT, REVOKE, BACKUP, RESTORE |
| `admin` | Sin restricciones en la app | — (SQL Server aplica sus propios permisos) |

Ademas, para **todos los roles** se bloquean:
- Sentencias con multiples instrucciones separadas por `;`
- Patrones de SQL injection: `OR '1'='1'`, `OR 1=1`, `--`, `/*`, `WAITFOR DELAY`, `XP_CMDSHELL`

---

## 6. Requisitos previos

- **Python 3.11** o superior
- **SQL Server** (cualquier edicion, incluyendo Express) con la base de datos `biblioteca` creada
- **ODBC Driver 17 for SQL Server** instalado en el sistema
  - Descargar en: [Microsoft ODBC Driver for SQL Server](https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server)
- **Clave de API de Google Gemini**
  - Obtener en: [Google AI Studio](https://aistudio.google.com/app/apikey)

---

## 7. Instalacion

```bash
# 1. Clonar el repositorio
git clone https://github.com/chepe5251/proyectoBD.git
cd proyectoBD

# 2. Crear entorno virtual
python -m venv .venv

# 3. Activar el entorno virtual
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# Windows CMD:
.venv\Scripts\activate.bat

# 4. Instalar dependencias
pip install -r requirements.txt
```

Dependencias instaladas (versiones exactas):

| Paquete | Version | Para que se usa |
|---------|---------|-----------------|
| `bcrypt` | 4.3.0 | Hash seguro de contraseñas |
| `google-genai` | 1.7.0 | SDK principal de Google Gemini |
| `google-generativeai` | 0.8.6 | SDK alternativo (fallback) |
| `python-dotenv` | 1.2.2 | Carga de variables de entorno desde `.env` |
| `pyodbc` | 5.3.0 | Conexion a SQL Server via ODBC |

---

## 8. Configuracion del archivo .env

Crear un archivo llamado `.env` en la raiz del proyecto (al mismo nivel que `main.py`). Este archivo **nunca debe subirse al repositorio**.

```env
# Clave de Google Gemini (obtener en aistudio.google.com)
GEMINI_API_KEY=tu_clave_de_gemini_aqui

# SQL Server: nombre del servidor o instancia
# Ejemplos: localhost, DESKTOP-ABC\SQLEXPRESS, 192.168.1.10
DB_SERVER=nombre_del_servidor
DB_NAME=biblioteca

# Certificado TLS: "yes" para desarrollo local, "no" en produccion con cert valido
DB_TRUST_CERT=yes

# Login auxiliar: solo puede llamar personas.autenticar_usuario
SQL_LOGIN_APP=login_app
SQL_PASS_APP=App#2026!

# Logins por rol (la app los selecciona automaticamente segun el rol del usuario)
SQL_LOGIN_ADMIN=login_admin
SQL_PASS_ADMIN=Admin#2026!
SQL_LOGIN_OPERATIVO=login_operativo
SQL_PASS_OPERATIVO=Operativo#2026!
SQL_LOGIN_USUARIO=login_usuario
SQL_PASS_USUARIO=Usuario#2026!
```

> Si la aplicacion detecta que falta `GEMINI_API_KEY` al iniciar, muestra una pantalla de error con instrucciones y un boton para reintentar sin necesidad de reiniciar el programa.

---

## 9. Crear la base de datos

Abrir **SQL Server Management Studio**, conectarse al servidor y ejecutar el script completo:

```
Archivo > Abrir > Archivo... > seleccionar database.sql > Ejecutar (F5)
```

El script crea automaticamente:
- La base de datos `biblioteca`
- Los tres schemas (`personas`, `catalogo`, `operaciones`)
- Todas las tablas con sus constraints y foreign keys
- Los logins, usuarios y roles de SQL Server
- Los permisos para cada rol
- Los indices de rendimiento
- Los procedimientos almacenados
- Las vistas
- 10 usuarios, 6 autores, 5 categorias, 18 libros y 5 prestamos de ejemplo

> **Nota**: Si ya existe una base de datos `biblioteca`, el script fallara en el primer `CREATE DATABASE`. En ese caso ejecutar primero:
> ```sql
> USE master;
> ALTER DATABASE biblioteca SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
> DROP DATABASE biblioteca;
> ```

---

## 10. Ejecucion

### Opcion A — Doble clic (recomendado en Windows)

Hacer doble clic en `iniciar.vbs`. Este lanzador:
1. Verifica que existe `main.py` en la carpeta
2. Verifica que existe el archivo `.env`
3. Verifica que Python esta instalado en el PATH
4. Lanza la aplicacion **sin ventana de consola negra** de fondo

### Opcion B — Desde la terminal

```bash
# Activar el entorno virtual primero
.venv\Scripts\Activate.ps1

# Ejecutar la aplicacion
python main.py
```

---

## 11. Uso de la aplicacion

### Pantalla de login

Ingresar el **correo electronico** y la **contraseña** del usuario registrado en `personas.usuarios`:

```
Correo:    andres.morales@outlook.com
Contraseña: admin2026
```

- Si las credenciales son incorrectas se muestra un mensaje de error.
- Tras 5 intentos fallidos el correo queda bloqueado 30 segundos.
- El boton **"Registrar usuario"** abre el formulario de registro.

### Pantalla de registro

Completar: nombre, apellido, correo, telefono, contraseña y confirmacion. El sistema:
- Valida que el correo tenga formato valido.
- Exige minimo 8 caracteres en el telefono y 6 en la contraseña.
- Verifica que las contraseñas coincidan.
- Genera el hash bcrypt y llama a `personas.registrar_usuario`.
- El rol asignado es siempre `usuario` (solo lectura).

### Pantalla del asistente

**Panel izquierdo — Chat:**

Escribir preguntas en lenguaje natural y presionar Enter o el boton "Enviar":

```
¿Cuantos libros hay registrados?
Mostrar los prestamos activos
Libros de Gabriel Garcia Marquez
Libros de categoria Tecnologia
¿Que prestamos estan vencidos?
Buscar libro "1984"
```

Los tres botones de consulta rapida envian preguntas predefinidas.

**Panel derecho — SQL generado:**

Muestra en tiempo real:
- La sentencia T-SQL que la IA genero para responder la pregunta.
- El modelo de Gemini que proceso la solicitud.
- El estado: `Pendiente de validacion`, `⚠ Bloqueado por permisos de rol`, `✓ Ejecutado correctamente` o `✗ Error en base de datos`.

---

## 12. Usuarios de prueba

Estos usuarios se insertan automaticamente al ejecutar `database.sql`:

| Nombre | Correo | Contraseña | Rol |
|--------|--------|------------|-----|
| Andres Morales | andres.morales@outlook.com | admin2026 | admin |
| Carlos Mendez | carlos.mendez@gmail.com | carlos2026 | operativo |
| Daniel Vargas | daniel.vargas@outlook.com | daniel2026 | operativo |
| Ana Rodriguez | ana.rodriguez@gmail.com | ana2026 | usuario |
| Laura Sanchez | laura.sanchez@outlook.com | laura2026 | usuario |
| Jose Fernandez | jose.fernandez@outlook.com | jose2026 | usuario |
| Maria Lopez | maria.lopez@gmail.com | maria2026 | usuario |
| Sofia Herrera | sofia.herrera@gmail.com | sofia2026 | usuario |
| Luis Gomez | luis.gomez@gmail.com | luis2026 | usuario |
| Valeria Castro | valeria.castro@gmail.com | valeria2026 | usuario |

---

## 13. Manejo de errores

| Situacion | Comportamiento |
|-----------|----------------|
| Falta `GEMINI_API_KEY` en `.env` | Muestra pantalla de error con instrucciones y boton "Reintentar" |
| Correo o contraseña incorrectos | Mensaje de error en el login, sin revelar cual campo fallo |
| 5 intentos fallidos consecutivos | Bloqueo del correo por 30 segundos |
| Login auxiliar inaccesible | Error en consola, acceso denegado sin crashear |
| Cuota de Gemini agotada (429) | Mensaje con segundos de espera, input bloqueado temporalmente |
| Modelo de Gemini no disponible (404) | Fallback automatico al siguiente modelo en la lista de candidatos |
| SQL con placeholder `?` incompleto | Mensaje pidiendo reformular la pregunta |
| Accion bloqueada por RBAC | Mensaje explicando los permisos del rol; SQL visible en panel derecho |
| SQL con patron de injection (`--`, `OR 1=1`) | Bloqueado por `validar_accion()` antes de ejecutar |
| Error de base de datos | Mensaje en el chat; detalle tecnico en consola |
| Consulta retorna muchas filas | Limitado automaticamente a 100 filas (`SELECT TOP 100`) |
| Servidor SQL Server sin respuesta | Timeout de conexion de 5 segundos (no bloquea la UI) |
