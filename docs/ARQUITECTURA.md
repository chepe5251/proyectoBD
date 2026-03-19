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
                         │
         ┌───────────────┼───────────────┐
         ▼               ▼               ▼
┌────────────────┐ ┌──────────────┐ ┌────────────────┐
│ Capa de        │ │ Capa de IA   │ │ Capa de Datos  │
│ Seguridad      │ │ ai_assistant │ │ database_mgr   │
│ seguridad.py   │ │              │ │                │
│                │ │ Google       │ │ PyODBC         │
│ Autenticacion  │ │ Gemini API   │ │ SQL Server     │
│ RBAC           │ │ NL -> T-SQL  │ │ biblioteca     │
└────────────────┘ └──────────────┘ └────────────────┘
         │                                   │
         └──────────── config.py ────────────┘
                  Carga de .env
```

---

## Descripcion de cada capa

### 1. Capa de Configuracion — `config.py`

Responsabilidades:
- Cargar el archivo `.env` al importarse.
- Exponer `GEMINI_KEY` y `DB_CONFIG` al resto del sistema.
- Emitir advertencia en consola si `GEMINI_API_KEY` no esta presente.

No tiene dependencias internas. Es importada por `ai_assistant.py` y `database_manager.py`.

---

### 2. Capa de IA — `ai_assistant.py`

Responsabilidades:
- Inicializar el cliente de Google Gemini con fallback entre SDK nuevo (`google-genai`) y SDK legado (`google-generativeai`).
- Mantener el contexto de dominio: tablas, vistas y procedimientos autorizados de la base `biblioteca`.
- Traducir preguntas en lenguaje natural a T-SQL ejecutable.
- Formatear resultados crudos de la base de datos en texto legible para el usuario.
- Gestionar errores de cuota (429) y modelos no disponibles (404).

Patron de diseno: Adaptador para multiples versiones del SDK de Google.

Candidatos de modelo (en orden de preferencia):
1. Valor de `GEMINI_MODEL` en `.env` (si existe).
2. `gemini-2.5-flash`
3. `gemini-flash-latest`
4. `gemini-2.5-flash-lite`
5. `gemini-flash-lite-latest`
6. `gemini-1.5-flash`

Si un modelo retorna 404, el sistema prueba automaticamente el siguiente candidato.

---

### 3. Capa de Datos — `database_manager.py`

Responsabilidades:
- Construir la cadena de conexion ODBC con las credenciales recibidas (o las del `.env` por defecto).
- Verificar la validez de una conexion (`probar_conexion`).
- Ejecutar sentencias SQL parametrizadas o sin parametros.
- Retornar filas para sentencias con resultset o confirmacion de texto para DML/DDL.

Cada llamada a `ejecutar_consulta` abre y cierra su propia conexion para simplificar el manejo de estado.

---

### 4. Capa de Seguridad — `seguridad.py`

Responsabilidades:
- Autenticar al usuario verificando correo y hash SHA-256 de contrasena contra `personas.usuarios` mediante el procedimiento `personas.autenticar_usuario`, usando un login auxiliar de solo lectura (`SQL_LOGIN_APP`).
- Seleccionar el login de SQL Server correspondiente al rol obtenido de la base de datos.
- Poblar `self.usuario_actual` con id, nombre, apellido, correo, rol y credenciales operacionales.
- Validar el SQL generado por la IA contra las restricciones del rol antes de ejecutarlo.

Dos niveles de control de acceso:
- **Nivel motor**: SQL Server aplica los permisos del login seleccionado segun rol.
- **Nivel aplicacion**: `validar_accion()` bloquea comandos destructivos segun el rol.

| Rol | Restricciones en aplicacion |
|---|---|
| usuario | Bloquea INSERT, UPDATE, DELETE, DROP, ALTER |
| operativo | Bloquea DROP, ALTER, CREATE DATABASE |
| admin | Sin restricciones adicionales en aplicacion |

---

### 5. Capa de Presentacion — `main.py`

Responsabilidades:
- Renderizar la pantalla de login (correo + contrasena) y la pantalla de chat con Tkinter.
- Orquestar el flujo completo: login → generacion SQL → normalizacion → validacion → ejecucion → formateo → display.
- Ejecutar el flujo NL->SQL->DB en un hilo secundario (`threading.Thread`) para evitar el bloqueo de la UI.
- Normalizar el SQL generado por la IA (eliminar markdown, backticks, prefijos textuales).
- Gestionar el estado de la UI durante el procesamiento (bloqueo de inputs, indicador de estado).
- Mostrar mensajes de error o advertencia en el chat sin romper el flujo.

---

## Flujo detallado de una consulta

```
[Usuario escribe pregunta]
        │
        ▼
BibliotecaApp.procesar_consulta()
        │
        ├─ Verificar cuota de IA (ai_blocked_until)
        │
        ├─ AIAssistant.interpretar_pregunta(pregunta)
        │       └─ Gemini API → T-SQL en texto plano
        │
        ├─ BibliotecaApp._normalizar_sql(sql)
        │       └─ Limpia markdown, backticks, prefijo "SQL:"
        │
        ├─ SecurityManager.validar_accion(sql)
        │       └─ Bloquea si el rol no tiene permiso
        │
        ├─ DatabaseManager.ejecutar_consulta(sql)
        │       └─ PyODBC → SQL Server → filas o confirmacion
        │
        └─ AIAssistant.formatear_respuesta_humana(pregunta, datos)
                └─ Convierte filas a texto legible → muestra en chat
```

---

## Decisiones de diseno

**Autenticacion con correo y SHA-256 via procedimiento almacenado**
La aplicacion calcula SHA-256 de la contrasena en Python y lo verifica contra `personas.usuarios` usando un login auxiliar de solo lectura (`SQL_LOGIN_APP`). El rol queda registrado en la tabla, no derivado del nombre del login. Los logins de SQL Server son internos a la aplicacion; el usuario final solo ve un campo de correo y contrasena.

**Reconexion por rol tras el login**
Una vez autenticado, la aplicacion selecciona el login de SQL Server correspondiente al rol del usuario y reconstruye `DatabaseManager` con esas credenciales. Todas las consultas posteriores se ejecutan bajo esa identidad, activando los permisos del motor de forma transparente.

**Procesamiento asincronico en la GUI**
El flujo NL->SQL->DB se ejecuta en un hilo secundario (`threading.Thread`) para no bloquear la UI de Tkinter. Todas las actualizaciones visuales se despachan al hilo principal mediante `root.after(0, callback)`.

**Fallback de modelos Gemini**
La lista de candidatos permite que la aplicacion funcione aunque un modelo especifico no este disponible para la API key usada, sin requerir intervencion del usuario.

**Normalizacion de SQL en la GUI**
La limpieza del SQL generado por la IA se centraliza en `_normalizar_sql()` dentro de `BibliotecaApp`. Esto mantiene `AIAssistant` desacoplado del formato de respuesta del modelo.
