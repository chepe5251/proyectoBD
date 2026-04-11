# Biblioteca Inteligente — Asistente SQL con IA

Aplicacion de escritorio Windows que permite consultar y gestionar una base de datos de biblioteca mediante lenguaje natural. El usuario escribe preguntas en español; Google Gemini las convierte a T-SQL y el sistema las ejecuta sobre SQL Server mostrando los resultados en texto legible.

---

## Tabla de contenidos

1. [Descripcion general](#1-descripcion-general)
2. [Arquitectura](#2-arquitectura)
3. [Controller de consultas](#3-controller-de-consultas)
4. [Funcionalidades](#4-funcionalidades)
5. [Interfaz grafica](#5-interfaz-grafica)
6. [Estructura del repositorio](#6-estructura-del-repositorio)
7. [Base de datos](#7-base-de-datos)
8. [Seguridad y roles](#8-seguridad-y-roles)
9. [Requisitos previos](#9-requisitos-previos)
10. [Instalacion](#10-instalacion)
11. [Configuracion del archivo .env](#11-configuracion-del-archivo-env)
12. [Crear la base de datos](#12-crear-la-base-de-datos)
13. [Ejecucion](#13-ejecucion)
14. [Uso de la aplicacion](#14-uso-de-la-aplicacion)
15. [Usuarios de prueba](#15-usuarios-de-prueba)
16. [Manejo de errores](#16-manejo-de-errores)

---

## 1. Descripcion general

El proyecto implementa un asistente conversacional con las siguientes capacidades:

- **Lenguaje natural a SQL**: Google Gemini traduce preguntas en español a sentencias T-SQL ejecutables.
- **Conversacion multi-paso con memoria**: el asistente recuerda el contexto de los ultimos 10 intercambios. Puede pedir datos adicionales (`PEDIR:`), dar instrucciones sin SQL (`INSTRUCCION:`) o registrar usuarios con hash bcrypt generado en el momento (`PENDING_HASH:`).
- **Autenticacion segura**: correo y contraseña verificados contra `personas.usuarios` con hash bcrypt (rounds=12). La comparacion se realiza en Python, nunca en SQL Server.
- **Control de acceso por roles (RBAC)** en dos niveles: permisos del motor SQL Server y capa de validacion en la aplicacion.
- **Proteccion contra fuerza bruta**: bloqueo automatico de 30 segundos tras 5 intentos fallidos consecutivos por correo.
- **Panel SQL en tiempo real**: muestra la consulta generada por la IA, el modelo usado, estado de conexion y estado de ejecucion.
- **Registro de nuevos usuarios** directamente desde la aplicacion o a traves del asistente.
- **Interfaz grafica** Deep Carbon (Windows 11) con sidebar colapsable, iconografia Segoe MDL2 Assets, burbujas de chat por rol y procesamiento en hilo secundario.

---

## 2. Arquitectura

### Capas del sistema

```
+-------------------------------------------------------------+
|  PRESENTACION   main.py + features.py  (CustomTkinter)      |
|  · Login / Registro / Error config                          |
|  · Chat con burbujas (scrolledtext conservado — tags color) |
|  · Panel SQL en tiempo real (scrolledtext conservado)       |
|  · Dashboard / Busqueda / Ayuda / Admin  (CTk + Treeview)   |
|  · Sidebar NavigationView colapsable con iconos MDL2        |
|  · Ejecuta consultas en hilo secundario (nunca congela UI)  |
+----------------------+--------------------------------------+
                       | pregunta (str) + historial + timestamp cuota
                       v
+-------------------------------------------------------------+
|  CONTROLLER     chat_controller.py  (ChatController)        |
|  · Pipeline NL → IA → SQL → validacion → BD → formato      |
|  · Sin dependencias de Tkinter; testeable de forma aislada  |
|  · Devuelve ResultadoConsulta (datos puros, sin widgets)    |
+------+---------------+-----------------+--------------------+
       |               |                 |
       v               v                 v
+------------+  +---------------+  +---------------------+
| seguridad  |  | ai_assistant  |  | app_services        |
| .py        |  | .py           |  | .py                 |
| Auth bcrypt|  | Gemini NL→SQL |  | ConsultaService     |
| RBAC capa2 |  | Formateo resp |  | RegistroUsuarioSrv  |
+------------+  +-------+-------+  +---------------------+
                        | Google Gemini API
                        v
+-------------------------------------------------------------+
|  DATOS          database_manager.py  (DatabaseManager)      |
|  · PyODBC → SQL Server (login por rol)                      |
|  · Timeout de 5 s, resultados en listas de filas            |
+----------------------+--------------------------------------+
                       |
                       v
                  SQL Server
                  base de datos: biblioteca
```

### Flujo de una consulta

```
Usuario escribe pregunta
        |
        v
[1] ChatController._verificar_servicios_consulta()
        | guardia: asistente, db y seguridad inicializados
        v
[2] ChatController._verificar_cuota_ia()
        | si cuota bloqueada (429 previo) → mensaje de espera, fin
        v
[3] AIAssistant.interpretar_pregunta(pregunta, historial)
        | llama a Google Gemini con los ultimos 10 turnos de contexto
        | errores: AIQuotaExceededError (429) → bloqueo, AIServiceError → error
        v
[4] ChatController._interpretar_respuesta_ia()
        +-- PEDIR:        → el asistente pide mas datos, actualiza historial, fin
        +-- INSTRUCCION:  → respuesta conversacional sin SQL, actualiza historial, fin
        +-- PENDING_HASH: → marca pending_hash=True, elimina prefijo, continua
        +-- (SQL normal)  → continua sin cambios
        v
[5] ConsultaService.preparar_consulta()
        | normaliza: elimina markdown, backticks, prefijo SQL:
        | si pending_hash: genera hash bcrypt y construye EXEC parametrizado
        v
[6] SecurityManager.validar_accion()
        | RBAC capa 2: verifica que el SQL sea permitido para el rol
        | bloquea injection patterns (OR 1=1, --, WAITFOR DELAY, etc.)
        v
[7] ConsultaService.aplicar_limite_sql()
        | agrega TOP 100 si es SELECT sin TOP
        v
[8] DatabaseManager.ejecutar_consulta()
        | ejecuta bajo el login SQL Server del rol del usuario
        v
[9] AIAssistant.formatear_respuesta_humana()
        | convierte filas crudas en texto legible
        v
ResultadoConsulta → main.py renderiza en la UI (hilo principal)
```

---

## 3. Controller de consultas

### Que es `chat_controller.py`

`ChatController` es la capa de negocio del sistema. Separa la logica de procesamiento de consultas de la capa de presentacion (Tkinter).

**Ventajas:**
1. **Testeable sin UI**: se puede instanciar y ejecutar `procesar_consulta()` en tests unitarios o scripts sin necesidad de abrir una ventana de Tkinter.
2. **Flujo explicito**: el pipeline de 9 etapas esta nombrado y documentado como metodos privados separados.
3. **Salida estructurada**: devuelve `ResultadoConsulta`, un dataclass inmutable con todos los datos que la GUI necesita.

### Modelos de datos

| Clase | Descripcion |
|-------|-------------|
| `MensajeChat` | Unidad minima de salida: texto + autor ('Asistente', 'Tu') |
| `EntradaHistorial` | Turno conversacional para el contexto de Gemini: rol + texto |
| `ResultadoConsulta` | Resultado completo: mensajes, SQL, modelo, historial, bloqueo |

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

---

## 4. Funcionalidades

### 4.1 Chat con IA (panel principal)

Interfaz de conversacion entre el usuario y el asistente. Solo muestra mensajes del usuario y del asistente; los mensajes de sistema son silenciados para mantener el chat limpio.

- Burbujas de color diferenciadas: usuario (Violet #9D5CFF) y asistente (Slate #1E293B)
- El SQL generado se muestra en el panel lateral "Inspector SQL", no en el chat
- Procesamiento asincrono: la UI nunca se congela durante una consulta

### 4.2 Dashboard visual (seguridad por rol)

Las metricas mostradas dependen del rol del usuario autenticado. La separacion ocurre **en la base de datos**, no en Python.

**Admin / Operativo — metricas globales:**

| Tarjeta | Consulta |
|---------|----------|
| Total Libros | `SELECT COUNT(*) FROM catalogo.libros` |
| Prestamos Activos | `SELECT COUNT(*) FROM operaciones.vista_prestamos_activos` |
| Vencidos | `SELECT COUNT(*) FROM operaciones.vista_prestamos_vencidos` |
| Usuarios Registrados | `SELECT COUNT(*) FROM personas.usuarios` |

**Usuario — solo sus propios datos (parametrizado con `WHERE id_usuario = ?`):**

| Tarjeta | Consulta |
|---------|----------|
| Libros Disponibles | `SELECT COUNT(*) FROM catalogo.libros` con filtro estado |
| Mis Prestamos Activos | `WHERE id_usuario = ? AND estado = 1` |
| Mis Vencidos | `WHERE id_usuario = ? AND fecha_limite < GETDATE()` |

> Principio OWASP A01 / Least Privilege: el rol `usuario` nunca recibe datos globales que luego se filtran en Python. La consulta parametrizada con `id_usuario` garantiza que el motor SQL Server devuelva unicamente sus propias filas.

### 4.3 Busqueda directa sin IA

Cuatro modos con SQL parametrizado (sin Gemini, sin riesgo de inyeccion):

| Modo | SQL |
|------|-----|
| Por titulo | `WHERE titulo LIKE ?` |
| Por autor | `WHERE nombre_autor LIKE ? OR apellido_autor LIKE ?` |
| Por categoria | `WHERE nombre_categoria = ?` (Combobox con categorias de la BD) |
| Disponibles | Libros no prestados actualmente |

### 4.4 Panel de administracion (solo admin)

Visible unicamente para el rol `admin`. El permiso se valida dos veces: en la UI (el panel no se construye si el rol no es `admin`) y en `_cambiar_rol` antes del UPDATE.

| Funcion | Descripcion |
|---------|-------------|
| Lista de usuarios | id, nombre, apellido, correo y rol |
| Cambiar rol | Dialogo modal; valida permiso en backend antes del UPDATE |
| Logs de auditoria | Ultimas 100 consultas registradas |

### 4.5 Ayuda guiada por rol

- Instrucciones paso a paso para el chat
- Ejemplos de consulta dinamicos segun el rol (admin ve gestion, usuario ve catalogo)
- Tabla de operaciones disponibles por rol
- Los botones de ejemplo copian la consulta al chat y activan la pestana Chat

### 4.6 Auditoria de consultas

Cada consulta del asistente se registra automaticamente en `auditoria.consultas`:

| Campo | Descripcion |
|-------|-------------|
| `id_usuario` | Quien consulto |
| `pregunta` | Texto original del usuario |
| `sql_generado` | SQL enviado a la BD |
| `resultado` | `ejecutado`, `bloqueado`, `cuota_ia`, `conversacional` o `error` |
| `fecha_hora` | Timestamp |

El registro es asincrono y silente. Si la tabla no existe, la aplicacion funciona igual.

---

## 5. Interfaz grafica

### 5.1 Paleta Deep Carbon

| Token | Color | Uso |
|-------|-------|-----|
| `bg` | `#0B0E14` | Fondo principal |
| `sidebar_bg` | `#0E1119` | Fondo del sidebar |
| `panel` | `#151921` | Superficies de paneles |
| `panel_soft` | `#1A2030` | Nivel de profundidad medio |
| `card` | `#1C212E` | Tarjetas del dashboard |
| `accent` | `#9D5CFF` | Neon Violet — CTA e iconos activos |
| `accent2` | `#06B6D4` | Cyan Neon — acento alternativo |
| `body_text` | `#CBD5E1` | Texto de cuerpo |
| `muted` | `#94A3B8` | Texto secundario / iconos inactivos |
| `ok` | `#10B981` | Confirmaciones |
| `warn` | `#F59E0B` | Advertencias |
| `error` | `#F87171` | Errores |

### 5.2 Tipografia

| Fuente | Uso | Tamaño minimo |
|--------|-----|---------------|
| Segoe UI Variable Display | Titulos y cuerpo | 14px (datos), 16px (cuerpo) |
| Cascadia Code | Panel SQL / Inspector | 11pt |

### 5.3 Iconografia vectorial — Segoe MDL2 Assets

Todos los iconos son glifos de fuente (`Segoe MDL2 Assets`, incluida en Windows 10/11). **No se usan archivos de imagen** (.png, .jpg, .ico) en ninguna parte de la interfaz.

| Icono | Glifo | Uso |
|-------|-------|-----|
| `\uE700` | GlobalNavButton | Boton hamburguesa del sidebar |
| `\uE8BD` | Chat | Nav: Chat |
| `\uE9D2` | AreaChart | Nav: Dashboard |
| `\uE721` | Search | Nav: Busqueda |
| `\uE897` | Help | Nav: Ayuda |
| `\uE713` | Settings | Nav: Admin |
| `\uE72C` | Refresh | Boton Actualizar / Recargar |
| `\uE7E8` | Power | Boton logout del perfil |
| `\uE8A5` | Library | Logo en pantalla de error de config |

Los iconos de navegacion activos usan `#9D5CFF` (acento); inactivos usan `#94A3B8` (muted).

### 5.4 Sidebar NavigationView

Sidebar colapsable de 260px con animacion de 12px cada 8ms.

**Estructura:**
```
+-- Toggle (hamburguesa MDL2) + logotipo "Biblioteca"
+-- Separador
+-- Nav items (icon MDL2 + texto — dos CTkLabel independientes)
|   · Chat
|   · Dashboard
|   · Busqueda
|   · Ayuda
|   · Admin (solo rol admin)
+-- [fondo: BOTTOM]
    +-- Separador
    +-- Avatar circular 42x42px (#9D5CFF) + iniciales
    +-- Nombre (16px bold #FFFFFF) + Rol (13px #94A3B8)
    +-- Boton logout MDL2 (\uE7E8), hover → #F87171
```

Al colapsar a 64px: se ocultan los labels de texto y el perfil; solo quedan los iconos MDL2.

### 5.5 Widgets conservados en Tkinter/ttk

| Widget | Ubicacion | Razon |
|--------|-----------|-------|
| `scrolledtext.ScrolledText` | Chat y panel SQL | Unico widget con soporte de `tag_configure()` para burbujas de color |
| `tk.PanedWindow` | Divisor chat/SQL | Divisor redimensionable; CTk no tiene equivalente |
| `ttk.Treeview` | Dashboard, Busqueda, Admin | Tabla de datos eficiente; integrada con tema oscuro via `ttk.Style` |
| `ttk.Combobox` | BusquedaPanel | Selector de categorias; no hay `CTkCombobox` estable |
| `tk.Toplevel` | Dialogo cambio de rol | `CTkToplevel` presenta problemas de foco modal en Windows |

### 5.6 Boton Actualizar / Recargar

Todos los botones de recarga usan `_mk_refresh_button`:

- Fondo: azul oscuro `#1E3A8A` | Hover: `#1E40AF`
- Icono MDL2 `\uE72C` (Segoe MDL2 Assets) + texto (Segoe UI Variable)
- `corner_radius=12`, altura 38px
- Implementado como `CTkFrame` compuesto con dos `CTkLabel` separados, permitiendo fuentes independientes para icono y texto

### 5.7 Perfil de usuario (pie del sidebar)

- Datos del usuario extraidos con `_unwrap()`: soporta tanto valores escalares (str) como tuplas pyodbc de un elemento (ejemplo: `('Andres',)` → `'Andres'`)
- Rol formateado: `admin` → `Administrador`, `operativo` → `Operativo`, `usuario` → `Usuario`
- Sin prefijos "Nombre:" ni "Rol:" — el diseno es autoexplicativo

---

## 6. Estructura del repositorio

```
proyectoBD/
+-- chat_controller.py    # Controller del flujo conversacional (sin dependencias de Tkinter)
+-- features.py           # Paneles: Dashboard, Busqueda, Ayuda, Admin (CustomTkinter)
+-- main.py               # Punto de entrada, GUI y sidebar NavigationView (CustomTkinter)
+-- app_services.py       # Servicios: registro de usuarios, preparacion de consultas
+-- ai_assistant.py       # Capa IA: lenguaje natural → T-SQL via Google Gemini
+-- database_manager.py   # Capa de datos: conexion y ejecucion en SQL Server via PyODBC
+-- seguridad.py          # Autenticacion bcrypt, RBAC y proteccion contra fuerza bruta
+-- config.py             # Carga centralizada de variables de entorno (.env)
+-- database.sql          # Script completo de la BD (DDL + datos iniciales + auditoria)
+-- iniciar.vbs           # Lanzador de Windows (sin ventana de consola)
+-- requirements.txt      # Dependencias Python con versiones exactas
+-- .env.example          # Plantilla de variables de entorno (sin credenciales reales)
+-- .gitignore            # Excluye .env y .venv del repositorio
+-- README.md             # Este archivo
```

> `.env` esta en `.gitignore` y **nunca** debe subirse al repositorio. Usa `.env.example` como plantilla.

---

## 7. Base de datos

Base de datos: `biblioteca` en SQL Server. El script completo esta en [`database.sql`](database.sql).

### Schemas

| Schema | Proposito |
|--------|-----------|
| `personas` | Usuarios del sistema |
| `catalogo` | Autores, categorias y libros |
| `operaciones` | Prestamos y devoluciones |
| `auditoria` | Registro de consultas del asistente |

### Tablas principales

| Tabla | Campos clave |
|-------|-------------|
| `personas.usuarios` | `id_usuario`, `nombre_usuario`, `apellido_usuario`, `correo`, `password_hash`, `rol` |
| `catalogo.libros` | `id_libro`, `titulo`, `id_autor`, `id_categoria`, `disponible` |
| `catalogo.autores` | `id_autor`, `nombre_autor`, `apellido_autor` |
| `operaciones.prestamos` | `id_prestamo`, `id_usuario`, `id_libro`, `fecha_prestamo`, `fecha_limite`, `estado` |
| `auditoria.consultas` | `id_consulta`, `id_usuario`, `pregunta`, `sql_generado`, `resultado`, `fecha_hora` |

### Vistas

| Vista | Descripcion |
|-------|-------------|
| `operaciones.vista_prestamos_activos` | Prestamos con estado=1 y fecha_devolucion IS NULL |
| `operaciones.vista_prestamos_vencidos` | Prestamos activos con fecha_limite < GETDATE() |

### Procedimiento almacenado de autenticacion

```sql
EXEC personas.autenticar_usuario @correo = 'user@example.com'
-- Devuelve: id_usuario, nombre, apellido, correo, rol, password_hash
-- Usado unicamente por el login auxiliar SQL_LOGIN_APP (solo lectura)
```

---

## 8. Seguridad y roles

### Niveles de defensa

| Nivel | Donde | Que hace |
|-------|-------|----------|
| 1 | SQL Server | Cada login de BD tiene permisos GRANT/DENY especificos por schema |
| 2 | `seguridad.py` | RBAC en aplicacion: bloquea DDL, DML y patrones de inyeccion segun rol |
| 3 | `database_manager.py` | Consultas parametrizadas con `?`; nunca concatenacion de strings |
| 4 | `seguridad.py` | Proteccion contra fuerza bruta: bloqueo 30s tras 5 intentos fallidos |

### Roles

| Rol | SQL Server login | Permisos de aplicacion |
|-----|-----------------|----------------------|
| `admin` | `SQL_LOGIN_ADMIN` | Sin restricciones adicionales |
| `operativo` | `SQL_LOGIN_OPERATIVO` | Bloquea DDL estructural (DROP, ALTER, CREATE TABLE) |
| `usuario` | `SQL_LOGIN_USUARIO` | Solo SELECT/WITH; bloquea todo DML y DDL |

### Login auxiliar de autenticacion

El login `SQL_LOGIN_APP` solo puede ejecutar `personas.autenticar_usuario`. No puede hacer SELECT directo sobre `personas.usuarios`. Esto previene lectura masiva de hashes.

### Patrones bloqueados por RBAC (capa 2)

```
OR '1'='1   OR 1=1   ' OR '   --   /*   */   WAITFOR DELAY   XP_CMDSHELL
SHUTDOWN   DBCC   KILL   BULK INSERT   OPENROWSET   OPENDATASOURCE
```

---

## 9. Requisitos previos

| Requisito | Version | Notas |
|-----------|---------|-------|
| Python | 3.10+ | Requiere `match/case` y `|` en type hints |
| SQL Server | 2019+ | Express edition es suficiente |
| ODBC Driver for SQL Server | 17 o 18 | Instalar desde Microsoft |
| Windows | 10 / 11 | Segoe MDL2 Assets incluida; Cascadia Code recomendada |
| Google Gemini API Key | — | Cuenta gratuita en Google AI Studio |

---

## 10. Instalacion

```bash
# 1. Clonar el repositorio
git clone <url-del-repositorio>
cd proyectoBD

# 2. Crear entorno virtual
python -m venv .venv
.venv\Scripts\activate

# 3. Instalar dependencias
pip install -r requirements.txt
```

### Dependencias

```
bcrypt==4.3.0
customtkinter==5.2.2
google-genai==1.7.0
google-generativeai==0.8.6
python-dotenv==1.2.2
pyodbc==5.3.0
```

---

## 11. Configuracion del archivo .env

Crear el archivo `.env` en la raiz del proyecto (no commitear, esta en `.gitignore`):

```env
# API de Google Gemini
GEMINI_KEY=tu_clave_de_gemini_aqui

# Servidor SQL Server
SQL_SERVER=localhost\SQLEXPRESS
SQL_DATABASE=biblioteca

# Login auxiliar (solo puede ejecutar personas.autenticar_usuario)
SQL_LOGIN_APP=login_app
SQL_PASS_APP=password_app

# Logins por rol (creados en SQL Server con GRANT/DENY especificos)
SQL_LOGIN_ADMIN=login_admin
SQL_PASS_ADMIN=password_admin

SQL_LOGIN_OPERATIVO=login_operativo
SQL_PASS_OPERATIVO=password_operativo

SQL_LOGIN_USUARIO=login_usuario
SQL_PASS_USUARIO=password_usuario
```

---

## 12. Crear la base de datos

```sql
-- En SQL Server Management Studio o Azure Data Studio:
-- 1. Abrir database.sql
-- 2. Ejecutar el script completo
-- El script crea la BD, schemas, tablas, vistas, procedimientos,
--   logins, usuarios y datos de prueba.
```

---

## 13. Ejecucion

```bash
# Desde el entorno virtual activado:
python main.py

# O doble clic en iniciar.vbs (sin ventana de consola en Windows)
```

---

## 14. Uso de la aplicacion

### Login
1. Ingresar correo y contraseña
2. El sistema autentica contra `personas.usuarios` con bcrypt
3. Se construye la sesion con el login SQL Server del rol

### Chat
- Escribir preguntas en lenguaje natural en español
- El asistente recuerda los ultimos 10 mensajes (contexto multi-paso)
- El SQL generado aparece en el panel lateral "Inspector SQL"
- Solo se muestran mensajes del usuario y del asistente (interfaz limpia)

### Dashboard
- Se carga automaticamente al cambiar a la pestana
- Los datos mostrados dependen del rol (admin ve metricas globales, usuario ve sus propios prestamos)
- Boton "Actualizar" recarga todos los datos

### Busqueda
- Seleccionar el modo de busqueda (titulo, autor, categoria, disponibles)
- Ingresar el termino o seleccionar del combobox
- Los resultados se muestran en una tabla con 5 columnas

### Admin (solo rol admin)
- Pestana "Usuarios": lista todos los usuarios; boton "Cambiar Rol" abre dialogo modal
- Pestana "Logs": muestra las ultimas 100 consultas auditadas

---

## 15. Usuarios de prueba

Los siguientes usuarios se crean con el script `database.sql`:

| Correo | Contraseña | Rol |
|--------|-----------|-----|
| `admin@biblioteca.cr` | `Admin123!` | admin |
| `operativo@biblioteca.cr` | `Oper123!` | operativo |
| `usuario@biblioteca.cr` | `User123!` | usuario |

---

## 16. Manejo de errores

Todos los mensajes de error visibles al usuario se centralizan en el diccionario `MENSAJES` de `features.py`. Ningun panel muestra stack traces ni mensajes tecnicos.

| Situacion | Mensaje al usuario |
|-----------|-------------------|
| Error inesperado | "Ocurrio un error inesperado. Por favor, intenta de nuevo." |
| Sin resultados | "No se encontraron resultados para tu busqueda." |
| Sin permisos | "Tu rol no tiene permisos para esta accion." |
| Error de BD | "Ocurrio un error al obtener los datos. Intenta de nuevo." |
| Error de IA | "La IA no pudo procesar tu solicitud. Intenta de nuevo." |
| Cuota IA | "La IA esta sin cuota temporalmente. Espera unos segundos." |
| SQL bloqueado | "La consulta fue bloqueada por seguridad." |

Los errores tecnicos (traza de excepcion, SQL error) se registran en los loggers `chat_controller` y `main` para diagnostico interno.

### Logging

```python
import logging

# Activar trazas detalladas durante desarrollo:
logging.getLogger("chat_controller").setLevel(logging.DEBUG)
logging.getLogger("main").setLevel(logging.DEBUG)
```

| Nivel | Eventos |
|-------|---------|
| `INFO` | Consulta recibida, SQL ejecutado, resultado exitoso |
| `WARNING` | Cuota bloqueada, SQL rechazado por RBAC |
| `ERROR` | Errores de BD, errores de servicio IA |
| `DEBUG` | Respuesta cruda de Gemini, SQL normalizado |
