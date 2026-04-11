# Biblioteca Inteligente — Asistente SQL con IA

Aplicacion de escritorio que permite consultar y gestionar una base de datos de biblioteca mediante lenguaje natural. El usuario escribe preguntas en español; Google Gemini las convierte a T-SQL y el sistema las ejecuta sobre SQL Server mostrando los resultados en texto legible.

---

## Tabla de contenidos

1. [Descripcion general](#1-descripcion-general)
2. [Arquitectura](#2-arquitectura)
3. [Controller de consultas](#3-controller-de-consultas)
4. [Nuevas funcionalidades](#4-nuevas-funcionalidades)
5. [Estructura del repositorio](#5-estructura-del-repositorio)
6. [Base de datos](#6-base-de-datos)
7. [Seguridad y roles](#7-seguridad-y-roles)
8. [Requisitos previos](#8-requisitos-previos)
9. [Instalacion](#9-instalacion)
10. [Configuracion del archivo .env](#10-configuracion-del-archivo-env)
11. [Crear la base de datos](#11-crear-la-base-de-datos)
12. [Ejecucion](#12-ejecucion)
13. [Uso de la aplicacion](#13-uso-de-la-aplicacion)
14. [Usuarios de prueba](#14-usuarios-de-prueba)
15. [Manejo de errores](#15-manejo-de-errores)

---

## 1. Descripcion general

El proyecto implementa un asistente conversacional con las siguientes capacidades:

- **Lenguaje natural a SQL**: Google Gemini traduce preguntas en español a sentencias T-SQL ejecutables.
- **Conversacion multi-paso con memoria**: el asistente recuerda el contexto de los ultimos 10 intercambios. Puede pedir datos adicionales (`PEDIR:`), dar instrucciones sin SQL (`INSTRUCCION:`) o registrar usuarios con hash bcrypt generado en el momento (`PENDING_HASH:`).
- **Autenticacion segura**: correo y contraseña verificados contra `personas.usuarios` con hash bcrypt (rounds=12). La comparacion se realiza en Python, nunca en SQL Server.
- **Control de acceso por roles (RBAC)** en dos niveles: permisos del motor SQL Server y capa de validacion en la aplicacion.
- **Proteccion contra fuerza bruta**: bloqueo automatico de 30 segundos tras 5 intentos fallidos consecutivos por correo.
- **Panel SQL en tiempo real**: muestra la consulta generada por la IA, el modelo usado, estado de conexion y estado de ejecucion.
- **Registro de nuevos usuarios** directamente desde la aplicacion o a traves del asistente, compartiendo la misma validacion, hashing bcrypt y construccion del `EXEC`.
- **Interfaz grafica** oscura con tema teal, burbujas de mensaje por rol, botones de consulta rapida dinamicos segun el rol del usuario y procesamiento en hilo secundario (la ventana nunca se congela).

---

## 2. Arquitectura

### Capas del sistema

```
┌─────────────────────────────────────────────────────────────┐
│  PRESENTACION   main.py  (BibliotecaApp — Tkinter)          │
│  · Pantalla de login / registro / error config              │
│  · Chat con burbujas (panel 65%)                            │
│  · Panel SQL en tiempo real (panel 35%)                     │
│  · Ejecuta consultas en hilo secundario (nunca congela UI)  │
└──────────────────────┬──────────────────────────────────────┘
                       │ pregunta (str) + historial + timestamp cuota
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  CONTROLLER     chat_controller.py  (ChatController)        │
│  · Pipeline NL → IA → SQL → validacion → BD → formato      │
│  · Sin dependencias de Tkinter; testeable de forma aislada  │
│  · Devuelve ResultadoConsulta (datos puros, sin widgets)    │
└──────┬──────────────┬─────────────────┬─────────────────────┘
       │              │                 │
       ▼              ▼                 ▼
┌────────────┐  ┌───────────────┐  ┌──────────────────────┐
│ seguridad  │  │ ai_assistant  │  │  app_services        │
│ .py        │  │ .py           │  │  .py                 │
│ Auth bcrypt│  │ Gemini NL→SQL │  │  ConsultaService     │
│ RBAC capa2 │  │ Formateo resp │  │  RegistroUsuarioSrv  │
└────────────┘  └───────┬───────┘  └──────────────────────┘
                        │ Google Gemini API
                        ▼
┌─────────────────────────────────────────────────────────────┐
│  DATOS          database_manager.py  (DatabaseManager)      │
│  · PyODBC → SQL Server (login por rol)                      │
│  · Timeout de 5 s, resultados en listas de filas            │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
                  SQL Server
                  base de datos: biblioteca
```

### Flujo de una consulta

```
Usuario escribe pregunta
        │
        ▼
[1] ChatController._verificar_servicios_consulta()
        │ guardia: asistente, db y seguridad inicializados
        ▼
[2] ChatController._verificar_cuota_ia()
        │ si cuota bloqueada (429 previo) → mensaje de espera, fin
        ▼
[3] AIAssistant.interpretar_pregunta(pregunta, historial)
        │ llama a Google Gemini con los ultimos 10 turnos de contexto
        │ errores: AIQuotaExceededError (429) → bloqueo, AIServiceError → error
        ▼
[4] ChatController._interpretar_respuesta_ia()
        ├── PEDIR:        → el asistente pide mas datos, actualiza historial, fin
        ├── INSTRUCCION:  → respuesta conversacional sin SQL, actualiza historial, fin
        ├── PENDING_HASH: → marca pending_hash=True, elimina prefijo, continua
        └── (SQL normal)  → continua sin cambios
        ▼
[5] ConsultaService.preparar_consulta()
        │ normaliza: elimina markdown, backticks, prefijo SQL:
        │ si pending_hash: genera hash bcrypt y construye EXEC parametrizado
        │ si queda placeholder '?': error con mensaje al usuario
        ▼
[6] SecurityManager.validar_accion()
        │ RBAC capa 2: verifica que el SQL sea permitido para el rol
        │ bloquea injection patterns (OR 1=1, --, WAITFOR DELAY, etc.)
        │ si bloqueado → mensaje con permisos del rol, fin
        ▼
[7] ConsultaService.aplicar_limite_sql()
        │ agrega TOP 100 si es SELECT sin TOP (protege rendimiento)
        ▼
[8] DatabaseManager.ejecutar_consulta()
        │ ejecuta bajo el login SQL Server del rol del usuario
        │ si devuelve None → mensaje de error de BD, fin
        ▼
[9] AIAssistant.formatear_respuesta_humana()
        │ convierte filas crudas en texto legible segun tipo de resultado
        ▼
ResultadoConsulta → main.py renderiza en la UI
```

---

## 3. Controller de consultas

### Que es `chat_controller.py`

`ChatController` es la capa de negocio del sistema. Separa la logica de procesamiento
de consultas de la capa de presentacion (Tkinter), lo que tiene tres ventajas concretas:

1. **Testeable sin UI**: se puede instanciar y ejecutar `procesar_consulta()` en tests
   unitarios o scripts sin necesidad de abrir una ventana de Tkinter.
2. **Flujo explicito**: el pipeline de 9 etapas esta nombrado y documentado como metodos
   privados separados, en lugar de vivir en un unico metodo largo.
3. **Salida estructurada**: devuelve `ResultadoConsulta`, un dataclass inmutable con todos
   los datos que la GUI necesita; el controller nunca toca widgets ni variables de estado
   de Tkinter.

### Modelos de datos del controller

| Clase | Descripcion |
|-------|-------------|
| `MensajeChat` | Unidad minima de salida: texto + autor ('Asistente', 'Sistema', 'Tu') |
| `EntradaHistorial` | Turno conversacional para el contexto de Gemini: rol + texto |
| `ResultadoConsulta` | Resultado completo del pipeline: mensajes, SQL, modelo, historial, bloqueo |

### Las 9 etapas del pipeline

| Etapa | Metodo | Que hace |
|-------|--------|----------|
| 1 | `_verificar_servicios_consulta` | Guardia: servicios criticos inicializados |
| 2 | `_verificar_cuota_ia` | Rechaza temprano si la cuota de Gemini esta bloqueada |
| 3 | `_consultar_asistente` | Llama a Gemini; maneja errores 429 y otros |
| 4 | `_interpretar_respuesta_ia` | Detecta prefijos PEDIR / INSTRUCCION / PENDING_HASH |
| 5 | `_normalizar_sql_para_ejecucion` | Limpia artefactos de Gemini; resuelve hash bcrypt |
| 6 | `_validar_sql_segun_rol` | RBAC capa 2; bloquea injection patterns |
| 7 | `_aplicar_limite_sql` | Agrega TOP 100 a SELECT sin TOP |
| 8 | `_ejecutar_consulta_segura` | Envia SQL a SQL Server; captura errores de BD |
| 9 | `_formatear_resultado_consulta` | Convierte filas en texto legible via Gemini |

### Ejemplo de flujo real

**Pregunta del usuario:** `¿Cuantos libros hay registrados?`

**SQL generado por Gemini:**
```sql
SELECT COUNT(*) FROM catalogo.libros
```

**Despues de aplicar TOP 100** (no aplica: es COUNT, no SELECT de filas):
```sql
SELECT COUNT(*) FROM catalogo.libros
```

**Resultado de SQL Server:** `[(18,)]`

**Respuesta formateada:** `Claro. Actualmente hay 18 libros registrados.`

---

**Pregunta del usuario:** `Mostrar prestamos vencidos`

**SQL generado por Gemini:**
```sql
SELECT TOP 100 id_prestamo, nombre_usuario, apellido_usuario, titulo,
       fecha_limite, dias_vencido
FROM operaciones.vista_prestamos_vencidos
```

**Respuesta formateada:**
```
Encontre 2 resultado(s):
— 3 · Daniel Vargas · Cien años de soledad · 2026-03-01 · 41
— 5 · Maria Lopez  · El Quijote · 2026-02-15 · 55
```

### Logging

El controller usa el logger `chat_controller`. Para activar trazas en desarrollo:

```python
import logging
logging.getLogger("chat_controller").setLevel(logging.DEBUG)
```

Los eventos registrados incluyen:
- `INFO`: consulta recibida, SQL ejecutado, resultado exitoso
- `WARNING`: cuota bloqueada, SQL rechazado por RBAC
- `ERROR`: errores de base de datos, errores de servicio IA
- `DEBUG`: respuesta cruda de Gemini, SQL normalizado

---

## 4. Nuevas funcionalidades

A partir de la version 2.0 la aplicacion incluye cinco funcionalidades adicionales
integradas en una barra de navegacion entre pestanas visible tras el login.

### 4.1 Panel de administracion (solo admin)

Accesible desde la pestana **⚙ Admin**, visible unicamente para el rol `admin`.

| Funcion | Descripcion |
|---------|-------------|
| Lista de usuarios | Muestra id, nombre, apellido, correo y rol de todos los usuarios |
| Cambiar rol | Dialogo modal para asignar un nuevo rol; valida permiso en backend antes del UPDATE |
| Logs de auditoria | Ultimas 100 consultas registradas (requiere ejecutar `database_patch.sql`) |

El permiso de administrador se valida **dos veces**: en la UI (no se construye el panel si
el rol no es `admin`) y en el metodo `_cambiar_rol` antes de ejecutar el UPDATE, previniendo
escalada de privilegios si se manipula el estado de la aplicacion.

### 4.2 Dashboard visual

Pestana **📊 Dashboard**, accesible para todos los roles.

| Tarjeta | Consulta |
|---------|----------|
| Total Libros | `SELECT COUNT(*) FROM catalogo.libros` |
| Prestamos Activos | `SELECT COUNT(*) FROM operaciones.vista_prestamos_activos` |
| Prestamos Vencidos | `SELECT COUNT(*) FROM operaciones.vista_prestamos_vencidos` |
| Usuarios | `SELECT COUNT(*) FROM personas.usuarios` |

Incluye ademas una tabla con los **5 libros mas prestados** del historial.
Los datos se cargan de forma asincrona (sin bloquear la UI) y pueden actualizarse
con el boton **⟳ Actualizar**.

### 4.3 Busqueda directa sin IA

Pestana **🔍 Busqueda**, accesible para todos los roles.

Ofrece cuatro modos de busqueda directa con SQL parametrizado (sin Gemini):

| Modo | Descripcion | Input |
|------|-------------|-------|
| Por titulo | `WHERE titulo LIKE ?` | Campo de texto |
| Por autor | `WHERE nombre_autor LIKE ? OR apellido_autor LIKE ?` | Campo de texto |
| Por categoria | `WHERE nombre_categoria = ?` | Combobox con categorias |
| Disponibles | Libros no prestados actualmente | Solo boton |

Cada modo reconstruye el area de input dinamicamente. Las consultas son parametrizadas,
eliminando el riesgo de SQL injection en esta funcionalidad.

### 4.4 Ayuda guiada

Pestana **💡 Ayuda**, accesible para todos los roles.

Contiene:
- **Como usar el chat**: instrucciones paso a paso.
- **Ejemplos para tu rol**: botones con preguntas tipicas del rol actual. Al hacer clic,
  el texto se copia al chat y se activa la pestana Chat automaticamente.
- **Que puedes hacer**: tabla de operaciones disponibles segun el rol.
- **Consejos**: recomendaciones para obtener mejores respuestas de la IA.

Los ejemplos son dinamicos: un `admin` ve preguntas de gestion; un `usuario` ve preguntas
de consulta de catalogo.

### 4.5 Manejo de errores amigable

Todos los mensajes de error visibles al usuario se centralizan en el diccionario
`MENSAJES` de `features.py`. Ningun panel muestra stack traces ni mensajes tecnicos.

| Situacion | Mensaje al usuario |
|-----------|-------------------|
| Error inesperado | "Ocurrio un error inesperado. Por favor, intenta de nuevo." |
| Sin resultados | "No se encontraron resultados para tu busqueda." |
| Sin permisos | "Tu rol no tiene permisos para esta accion." |
| Error de BD | "Ocurrio un error al obtener los datos. Intenta de nuevo." |
| Error de IA | "La IA no pudo procesar tu solicitud. Intenta de nuevo." |
| Cuota IA | "La IA esta sin cuota temporalmente. Espera unos segundos." |
| SQL bloqueado | "La consulta fue bloqueada por seguridad." |

Los errores tecnicos (traza de excepcion, SQL error) se registran en el logger
`chat_controller` o `main` para diagnostico interno, sin exponerse al usuario.

### 4.6 Auditoria de consultas (opcional)

Cada consulta del asistente se registra automaticamente en `auditoria.consultas`
(incluida en `database.sql`) con:

- `id_usuario` y `nombre_usuario`
- `pregunta` (texto original del usuario)
- `sql_generado` (SQL visual, sin passwords en claro)
- `resultado`: `ejecutado`, `bloqueado`, `cuota_ia`, `conversacional` o `error`
- `fecha_hora`

El registro es asincrono y silente: si la tabla no existe (base de datos antigua
sin regenerar), la aplicacion funciona igual sin mostrar ningun error.

---

## 5. Estructura del repositorio

```
proyectoBD/
├── chat_controller.py    # Controller del flujo conversacional sin dependencias de Tkinter
├── features.py           # Paneles adicionales: Dashboard, Busqueda, Ayuda, Admin
├── main.py               # Punto de entrada y GUI completa (Tkinter)
├── app_services.py       # Servicios de aplicacion para registro y preparacion de consultas
├── ai_assistant.py       # Capa de IA: lenguaje natural → T-SQL via Google Gemini
├── database_manager.py   # Capa de datos: conexion y ejecucion en SQL Server
├── seguridad.py          # Autenticacion bcrypt, RBAC y proteccion fuerza bruta
├── config.py             # Carga centralizada de variables de entorno (.env)
├── database.sql          # Script completo de la base de datos (DDL + datos iniciales + auditoria)
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

## 6. Base de datos

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

## 7. Seguridad y roles

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

## 8. Requisitos previos

- **Python 3.11** o superior
- **SQL Server** (cualquier edicion, incluyendo Express) con la base de datos `biblioteca` creada
- **ODBC Driver 17 for SQL Server** instalado en el sistema
  - Descargar en: [Microsoft ODBC Driver for SQL Server](https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server)
- **Clave de API de Google Gemini**
  - Obtener en: [Google AI Studio](https://aistudio.google.com/app/apikey)

---

## 9. Instalacion

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

## 10. Configuracion del archivo .env

Crear un archivo llamado `.env` en la raiz del proyecto (al mismo nivel que `main.py`). Este archivo **nunca debe subirse al repositorio**.

```env
# Clave de Google Gemini (obtener en aistudio.google.com)
GEMINI_API_KEY=tu_clave_de_gemini_aqui

# Modelo de Gemini a usar (opcional, si se omite usa gemini-2.5-flash por defecto)
# Opciones: gemini-2.5-flash, gemini-2.5-pro, gemini-2.0-flash, etc.
GEMINI_MODEL=gemini-2.5-flash

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

## 11. Crear la base de datos

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

## 12. Ejecucion

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

## 13. Uso de la aplicacion

### Pantalla de login

La card se muestra centrada en la ventana. Ingresar el **correo electronico** y la **contraseña** del usuario registrado en `personas.usuarios`:

```
Correo:    andres.morales@outlook.com
Contraseña: admin2026
```

- Si las credenciales son incorrectas se muestra un mensaje de error.
- Tras 5 intentos fallidos el correo queda bloqueado 30 segundos.
- El boton **"Registrar usuario"** abre el formulario de registro.

### Pantalla de registro

Formulario con scroll activado solo mientras el cursor esta sobre el canvas. Completar: nombre, apellido, correo, telefono, contraseña y confirmacion. El sistema:
- Valida que el correo tenga formato valido.
- Exige minimo 8 caracteres en el telefono y 6 en la contraseña.
- Verifica que las contraseñas coincidan.
- Genera el hash bcrypt y reutiliza la misma construccion parametrizada de `personas.registrar_usuario` que usa el registro via chat.
- El rol asignado es siempre `usuario` (solo lectura).

### Pantalla del asistente

**Panel izquierdo — Chat:**

Escribir preguntas en lenguaje natural y presionar Enter o el boton **"Enviar ➤"**. Los mensajes se muestran en burbujas con estilo diferente segun el autor (usuario, asistente, sistema).

El asistente mantiene el contexto de los ultimos 10 intercambios. Puede:
- Pedir datos que faltan antes de ejecutar una accion (`PEDIR:`).
- Dar una explicacion o instruccion sin ejecutar SQL (`INSTRUCCION:`).
- Registrar usuarios a traves del chat generando el hash bcrypt automaticamente.

```
¿Cuantos libros hay registrados?
Mostrar los prestamos activos
Libros de Gabriel Garcia Marquez
Libros de categoria Tecnologia
¿Que prestamos estan vencidos?
Buscar libro "1984"
Registrar un nuevo usuario
```

Los botones de consulta rapida son **dinamicos segun el rol** del usuario logueado:

| Rol | Botones |
|-----|---------|
| `admin` | Cuantos libros hay, Prestamos activos, Registrar nuevo libro, Prestamos vencidos |
| `operativo` | Cuantos libros hay, Prestamos activos, Prestamos vencidos, Lista de autores |
| `usuario` | Cuantos libros hay, Libros de tecnologia, Lista de autores, Libros disponibles |

**Panel derecho — SQL generado:**

Muestra en tiempo real:
- La sentencia T-SQL que la IA genero para responder la pregunta.
- Estado de conexion a la base de datos.
- El modelo de Gemini que proceso la solicitud.
- El estado de ejecucion: `Pendiente de validacion`, `Recopilando informacion`, `⚠ Bloqueado por permisos de rol`, `✓ Ejecutado correctamente` o `✗ Error en base de datos`.

---

## 14. Usuarios de prueba

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

## 15. Manejo de errores

Todos los mensajes visibles al usuario son amigables y no exponen detalles tecnicos.
Los detalles internos (stack traces, mensajes de excepcion) van al logger del modulo.
Los mensajes de usuario se centralizan en el dict `MENSAJES` de `features.py`.

| Situacion | Mensaje al usuario | Registro interno |
|-----------|--------------------|-----------------|
| Falta `GEMINI_API_KEY` | Pantalla de error con instrucciones y boton Reintentar | — |
| Correo o contraseña incorrectos | "Credenciales incorrectas." (sin revelar que campo fallo) | — |
| 5 intentos fallidos consecutivos | Bloqueo del correo por 30 segundos | `_log.warning` en seguridad.py |
| Cuota de Gemini agotada (429) | "La IA esta sin cuota temporalmente. Espera N segundos." | `logger.warning` en chat_controller |
| Modelo de Gemini no disponible (404) | Fallback automatico; sin mensaje al usuario si hay candidato disponible | `logger.warning` |
| Error de servicio IA (otro) | "La IA no pudo procesar tu solicitud. Intenta de nuevo." | `logger.error` |
| Error inesperado en la consulta | "Ocurrio un error inesperado. Por favor, intenta de nuevo." | `logger.error` en main.py |
| Accion bloqueada por RBAC | "Tu rol no tiene permisos para esta accion." + descripcion del rol | `logger.warning` |
| SQL con patron de injection | Bloqueado por `validar_accion()`; mismo mensaje de permisos | `logger.warning` |
| SQL con placeholder `?` incompleto | Mensaje pidiendo reformular la pregunta | — |
| IA pide mas datos (`PEDIR:`) | Pregunta de seguimiento del asistente | historial actualizado |
| IA da instruccion sin SQL (`INSTRUCCION:`) | Mensaje del asistente sin ejecutar SQL | historial actualizado |
| Error de base de datos | "Ocurrio un error al obtener los datos. Intenta de nuevo." | `_log.error` en database_manager |
| Sin resultados en busqueda directa | "No se encontraron resultados para tu busqueda." | — |
| Tabla auditoria no existe | Panel Logs muestra "Sin registros. Regenera la BD." | excepcion capturada silenciosamente |
| Consulta retorna muchas filas | Limitado automaticamente a TOP 100 | — |
| Servidor SQL Server sin respuesta | Timeout de 5 segundos; "Error al obtener los datos." | `_log.error` en database_manager |
