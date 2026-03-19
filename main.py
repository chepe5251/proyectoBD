"""
Modulo: main.py
Descripcion: Punto de entrada y capa de presentacion (GUI) construida con Tkinter.
             Implementa la pantalla de login y la pantalla de chat del asistente.

Responsabilidades:
    - Renderizar la interfaz grafica con tema oscuro (teal accent).
    - Orquestar el flujo completo: login -> NL -> SQL -> validacion -> ejecucion -> display.
    - Normalizar el SQL generado por la IA antes de ejecutarlo.
    - Gestionar el estado de la UI (bloqueo de inputs, indicador de estado, cuota de IA).

Flujo de autenticacion:
    1. El usuario ingresa su correo electronico y contrasena.
    2. SecurityManager.login() calcula SHA-256 de la contrasena y verifica
       contra personas.usuarios via el login auxiliar SQL_LOGIN_APP.
    3. Si tiene exito, DatabaseManager se reconstruye con el login de SQL Server
       correspondiente al rol del usuario (admin / operativo / usuario).
    4. Todas las consultas posteriores se ejecutan bajo esa identidad autenticada.
"""

import re
import threading
import time
import tkinter as tk
from tkinter import messagebox, scrolledtext

from ai_assistant import AIAssistant, AIQuotaExceededError, AIServiceError
from database_manager import DatabaseManager
from seguridad import SecurityManager


class BibliotecaApp:
    """
    Controlador principal de la interfaz grafica de la Biblioteca Inteligente.

    Gestiona dos pantallas (login y chat) y orquesta la interaccion entre
    las capas de IA, seguridad y base de datos.
    """

    def __init__(self, root):
        self.root = root
        self.root.title("ULATINA | Asistente de Biblioteca")
        self.root.geometry("980x700")
        self.root.minsize(860, 620)

        self.theme = {
            "bg": "#0f172a",
            "panel": "#111827",
            "panel_soft": "#1f2937",
            "input_bg": "#0b1220",
            "text": "#e5e7eb",
            "muted": "#9ca3af",
            "accent": "#14b8a6",
            "accent_soft": "#0f766e",
            "border": "#334155",
            "ok": "#22c55e",
            "warn": "#f59e0b",
            "error": "#ef4444",
        }
        self.fonts = {
            "title": "Bahnschrift",
            "body": "Segoe UI",
            "mono": "Consolas",
        }

        self.root.configure(bg=self.theme["bg"])

        # Servicios.
        self.db = None  # Se construye con las credenciales del usuario tras el login.
        self.asistente = AIAssistant()
        self.seguridad = None
        self.ai_blocked_until = 0.0

        self.btn_enviar = None
        self.ent_pregunta = None
        self.txt_chat = None
        self.lbl_estado = None
        self.botones_rapidos = []

        self.pantalla_login()

    def pantalla_login(self):
        """Construye pantalla de autenticacion."""
        self.limpiar_pantalla()

        container = tk.Frame(self.root, bg=self.theme["bg"])
        container.pack(fill=tk.BOTH, expand=True, padx=30, pady=30)

        card = tk.Frame(
            container,
            bg=self.theme["panel"],
            highlightthickness=1,
            highlightbackground=self.theme["border"],
            padx=0,
            pady=0,
        )
        card.pack(fill=tk.BOTH, expand=True)

        info_panel = tk.Frame(card, bg=self.theme["accent_soft"], padx=28, pady=32)
        info_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        tk.Label(
            info_panel,
            text="Biblioteca Inteligente",
            bg=self.theme["accent_soft"],
            fg="#e6fffb",
            font=(self.fonts["title"], 22, "bold"),
        ).pack(anchor="w")

        tk.Label(
            info_panel,
            text="Consulta catalogo, prestamos y usuarios con lenguaje natural.",
            bg=self.theme["accent_soft"],
            fg="#ccfbf1",
            font=(self.fonts["body"], 11),
            justify="left",
            wraplength=340,
        ).pack(anchor="w", pady=(10, 20))

        bullets = [
            "Control por permisos segun rol",
            "Consultas y operaciones seguras",
            "Respuestas claras, estilo bibliotecario",
        ]
        for item in bullets:
            tk.Label(
                info_panel,
                text=f"- {item}",
                bg=self.theme["accent_soft"],
                fg="#ecfeff",
                font=(self.fonts["body"], 10),
                anchor="w",
                justify="left",
            ).pack(anchor="w", pady=2)

        form_panel = tk.Frame(card, bg=self.theme["panel"], padx=34, pady=34)
        form_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        tk.Label(
            form_panel,
            text="Iniciar sesion",
            bg=self.theme["panel"],
            fg=self.theme["text"],
            font=(self.fonts["title"], 20, "bold"),
        ).pack(anchor="w")

        tk.Label(
            form_panel,
            text="Ingresa tus credenciales para abrir el asistente.",
            bg=self.theme["panel"],
            fg=self.theme["muted"],
            font=(self.fonts["body"], 10),
        ).pack(anchor="w", pady=(6, 18))

        tk.Label(
            form_panel,
            text="Correo electronico",
            bg=self.theme["panel"],
            fg=self.theme["text"],
            font=(self.fonts["body"], 10, "bold"),
        ).pack(anchor="w")
        self.ent_correo = tk.Entry(
            form_panel,
            width=38,
            bg=self.theme["input_bg"],
            fg=self.theme["text"],
            insertbackground=self.theme["text"],
            relief=tk.FLAT,
            font=(self.fonts["body"], 11),
        )
        self.ent_correo.pack(anchor="w", ipady=7, pady=(6, 14))

        tk.Label(
            form_panel,
            text="Contrasena",
            bg=self.theme["panel"],
            fg=self.theme["text"],
            font=(self.fonts["body"], 10, "bold"),
        ).pack(anchor="w")
        self.ent_pass = tk.Entry(
            form_panel,
            width=38,
            show="*",
            bg=self.theme["input_bg"],
            fg=self.theme["text"],
            insertbackground=self.theme["text"],
            relief=tk.FLAT,
            font=(self.fonts["body"], 11),
        )
        self.ent_pass.pack(anchor="w", ipady=7, pady=(6, 20))

        btn_login = tk.Button(
            form_panel,
            text="Entrar al asistente",
            command=self.ejecutar_login,
            bg=self.theme["accent"],
            fg="#042f2e",
            activebackground="#2dd4bf",
            activeforeground="#022c22",
            relief=tk.FLAT,
            padx=14,
            pady=9,
            font=(self.fonts["body"], 10, "bold"),
            cursor="hand2",
        )
        btn_login.pack(anchor="w")

        self.ent_pass.bind("<Return>", lambda _e: self.ejecutar_login())
        self.ent_correo.focus_set()

    def ejecutar_login(self):
        """Valida credenciales y abre el chat principal."""
        correo = self.ent_correo.get().strip()
        password = self.ent_pass.get().strip()

        if not correo or not password:
            messagebox.showwarning("Datos requeridos", "Debes ingresar correo y contrasena.")
            return

        self.seguridad = SecurityManager(self.db)
        if self.seguridad.login(correo, password):
            info = self.seguridad.usuario_actual
            self.db = DatabaseManager(uid=info["uid"], pwd=info["pwd"])
            self.seguridad.db = self.db
            self.pantalla_asistente()
            return

        messagebox.showerror("Acceso denegado", "Credenciales incorrectas.")

    def pantalla_asistente(self):
        """Ventana principal del chat."""
        self.limpiar_pantalla()
        usuario = self.seguridad.usuario_actual or {}
        rol = str(usuario.get("rol") or "sin rol").upper()

        top = tk.Frame(self.root, bg=self.theme["panel"], padx=20, pady=14)
        top.pack(fill=tk.X)

        tk.Label(
            top,
            text="Asistente de Biblioteca",
            bg=self.theme["panel"],
            fg=self.theme["text"],
            font=(self.fonts["title"], 18, "bold"),
        ).pack(side=tk.LEFT)

        chip = tk.Label(
            top,
            text=f"ROL: {rol}",
            bg="#0f766e",
            fg="#ecfeff",
            padx=10,
            pady=4,
            font=(self.fonts["body"], 9, "bold"),
        )
        chip.pack(side=tk.RIGHT, padx=(8, 0))

        self.lbl_estado = tk.Label(
            top,
            text="Listo para ayudarte",
            bg=self.theme["panel"],
            fg=self.theme["ok"],
            font=(self.fonts["body"], 9),
        )
        self.lbl_estado.pack(side=tk.RIGHT)

        body = tk.Frame(self.root, bg=self.theme["bg"], padx=20, pady=16)
        body.pack(fill=tk.BOTH, expand=True)

        self.txt_chat = scrolledtext.ScrolledText(
            body,
            wrap=tk.WORD,
            bg=self.theme["panel_soft"],
            fg=self.theme["text"],
            insertbackground=self.theme["text"],
            relief=tk.FLAT,
            bd=0,
            padx=14,
            pady=14,
            font=(self.fonts["body"], 11),
        )
        self.txt_chat.pack(fill=tk.BOTH, expand=True)
        self.txt_chat.config(state="disabled")
        self._configurar_tags_chat()

        tools = tk.Frame(body, bg=self.theme["bg"], pady=10)
        tools.pack(fill=tk.X)

        consulta_rapida = [
            "Cuantos libros hay registrados?",
            "Muestrame los libros populares",
            "Lista de autores registrados",
        ]
        self.botones_rapidos = []
        for texto in consulta_rapida:
            boton = tk.Button(
                tools,
                text=texto,
                command=lambda q=texto: self._usar_consulta_rapida(q),
                bg="#1d4ed8",
                fg="#dbeafe",
                activebackground="#1e40af",
                activeforeground="#eff6ff",
                relief=tk.FLAT,
                padx=10,
                pady=6,
                font=(self.fonts["body"], 9),
                cursor="hand2",
            )
            boton.pack(side=tk.LEFT, padx=(0, 8))
            self.botones_rapidos.append(boton)

        composer = tk.Frame(body, bg=self.theme["bg"])
        composer.pack(fill=tk.X, pady=(2, 0))

        input_box = tk.Frame(
            composer,
            bg=self.theme["input_bg"],
            highlightthickness=1,
            highlightbackground=self.theme["border"],
        )
        input_box.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.ent_pregunta = tk.Entry(
            input_box,
            bg=self.theme["input_bg"],
            fg=self.theme["text"],
            insertbackground=self.theme["text"],
            relief=tk.FLAT,
            bd=0,
            font=(self.fonts["body"], 11),
        )
        self.ent_pregunta.pack(fill=tk.X, padx=10, ipady=9)
        self.ent_pregunta.bind("<Return>", lambda _e: self.procesar_consulta())

        self.btn_enviar = tk.Button(
            composer,
            text="Enviar",
            command=self.procesar_consulta,
            bg=self.theme["accent"],
            fg="#042f2e",
            activebackground="#2dd4bf",
            activeforeground="#022c22",
            relief=tk.FLAT,
            padx=16,
            pady=9,
            font=(self.fonts["body"], 10, "bold"),
            cursor="hand2",
        )
        self.btn_enviar.pack(side=tk.LEFT, padx=(8, 0))

        self._mostrar_bienvenida()
        self.ent_pregunta.focus_set()

    def _configurar_tags_chat(self):
        self.txt_chat.tag_configure(
            "assistant_head",
            foreground="#2dd4bf",
            font=(self.fonts["title"], 10, "bold"),
            spacing1=6,
        )
        self.txt_chat.tag_configure(
            "assistant_body",
            foreground=self.theme["text"],
            lmargin1=12,
            lmargin2=12,
            spacing3=10,
        )
        self.txt_chat.tag_configure(
            "user_head",
            foreground="#93c5fd",
            font=(self.fonts["title"], 10, "bold"),
            spacing1=6,
        )
        self.txt_chat.tag_configure(
            "user_body",
            foreground="#dbeafe",
            lmargin1=12,
            lmargin2=12,
            spacing3=10,
        )
        self.txt_chat.tag_configure(
            "system_head",
            foreground="#f59e0b",
            font=(self.fonts["title"], 10, "bold"),
            spacing1=6,
        )
        self.txt_chat.tag_configure(
            "system_body",
            foreground="#fde68a",
            lmargin1=12,
            lmargin2=12,
            spacing3=10,
        )

    def _mostrar_bienvenida(self):
        usuario = self.seguridad.usuario_actual or {}
        nombre = str(usuario.get("nombre") or "usuario")
        permisos = self.seguridad.describir_permisos()

        self.mostrar_en_chat(
            f"Bienvenido/a {nombre}. Soy tu bibliotecario virtual y estoy listo para ayudarte.",
            autor="Sistema",
        )
        self.mostrar_en_chat(
            f"{permisos} Puedes escribirme en lenguaje natural.",
            autor="Sistema",
        )
        self.mostrar_en_chat(
            "Ejemplos: 'cuantos libros hay', 'libros populares', 'estado del usuario aleja@correo.com'.",
            autor="Sistema",
        )

    def _usar_consulta_rapida(self, consulta):
        self.ent_pregunta.delete(0, tk.END)
        self.ent_pregunta.insert(0, consulta)
        self.procesar_consulta()

    def _set_estado(self, texto, color):
        if self.lbl_estado:
            self.lbl_estado.config(text=texto, fg=color)

    def _toggle_input(self, enabled):
        estado = tk.NORMAL if enabled else tk.DISABLED
        if self.ent_pregunta:
            self.ent_pregunta.config(state=estado)
        if self.btn_enviar:
            self.btn_enviar.config(state=estado)
        for boton in self.botones_rapidos:
            boton.config(state=estado)

    @staticmethod
    def _normalizar_sql(sql_generado):
        """
        Limpia el texto retornado por Gemini y extrae el SQL ejecutable.

        Transformaciones aplicadas (en orden):
        1. Extrae contenido de bloques ```sql ... ```.
        2. Elimina el prefijo 'SQL:'.
        3. Convierte identificadores con backticks a corchetes [nombre],
           o los elimina si son palabras clave SQL.
        4. Reemplaza backticks restantes por comillas simples.
        5. Recorta el texto desde la primera palabra clave valida
           (SELECT, EXEC o WITH).

        Args:
            sql_generado (str): Texto crudo retornado por la IA.

        Returns:
            str: Sentencia T-SQL lista para ejecutar, o cadena vacia si
                 no se encontro SQL valido.
        """
        sql = str(sql_generado or "").strip()
        if not sql:
            return ""

        bloque = re.search(r"```(?:sql)?\s*(.*?)```", sql, flags=re.IGNORECASE | re.DOTALL)
        if bloque:
            sql = bloque.group(1).strip()

        if sql.upper().startswith("SQL:"):
            sql = sql[4:].strip()

        sql_keywords = {
            "SELECT", "FROM", "WHERE", "EXEC", "WITH", "ORDER", "BY", "GROUP",
            "HAVING", "TOP", "AS", "JOIN", "LEFT", "RIGHT", "INNER", "OUTER",
            "ON", "AND", "OR", "INSERT", "UPDATE", "DELETE", "INTO", "VALUES",
        }

        def _replace_backtick_identifier(match):
            token = match.group(1)
            if token.upper() in sql_keywords:
                return token
            return f"[{token}]"

        sql = re.sub(r"`([A-Za-z_][A-Za-z0-9_]*)`", _replace_backtick_identifier, sql)
        if "`" in sql:
            sql = sql.replace("`", "'")

        sql_upper = sql.upper()
        posiciones = [sql_upper.find(k) for k in ("SELECT", "EXEC", "WITH")]
        posiciones_validas = [p for p in posiciones if p >= 0]
        if posiciones_validas:
            sql = sql[min(posiciones_validas):].strip()

        return sql

    def procesar_consulta(self):
        pregunta = self.ent_pregunta.get().strip() if self.ent_pregunta else ""
        if not pregunta:
            return

        self.mostrar_en_chat(pregunta, autor="Tu")
        self.ent_pregunta.delete(0, tk.END)
        self._toggle_input(False)
        self._set_estado("Consultando...", self.theme["warn"])

        threading.Thread(
            target=self._procesar_en_hilo,
            args=(pregunta,),
            daemon=True,
        ).start()

    def _procesar_en_hilo(self, pregunta):
        """Ejecuta el flujo NL->SQL->DB en un hilo secundario para no congelar la GUI."""

        def ui(fn, *args):
            self.root.after(0, fn, *args)

        try:
            ahora = time.time()
            if ahora < self.ai_blocked_until:
                segundos = int(self.ai_blocked_until - ahora) + 1
                ui(self.mostrar_en_chat,
                   f"La IA esta temporalmente sin cuota. Intenta de nuevo en {segundos} segundos.",
                   "Sistema")
                return

            try:
                sql = self.asistente.interpretar_pregunta(pregunta)
            except AIQuotaExceededError as exc:
                retry_after = exc.retry_after_seconds or 30
                self.ai_blocked_until = time.time() + retry_after
                ui(self.mostrar_en_chat, str(exc), "Sistema")
                return
            except AIServiceError as exc:
                ui(self.mostrar_en_chat, f"Error de IA: {exc}", "Sistema")
                return

            sql = self._normalizar_sql(sql)
            if not sql:
                ui(self.mostrar_en_chat, "No se pudo generar una consulta valida.", "Sistema")
                return

            if "?" in sql:
                ui(self.mostrar_en_chat,
                   "La consulta generada quedo incompleta (placeholder '?'). Intenta reformular.",
                   "Sistema")
                return

            if not self.seguridad.validar_accion(sql):
                ui(self.mostrar_en_chat,
                   f"No puedo ejecutar esa accion con tu rol actual. {self.seguridad.describir_permisos()}",
                   "Sistema")
                return

            datos_crudos = self.db.ejecutar_consulta(sql)
            if datos_crudos is None:
                ui(self.mostrar_en_chat, "Ocurrio un error al consultar la base de datos.", "Sistema")
                return

            respuesta_final = self.asistente.formatear_respuesta_humana(pregunta, datos_crudos)
            ui(self.mostrar_en_chat, respuesta_final, "Asistente")
        finally:
            ui(self._finalizar_consulta)

    def _finalizar_consulta(self):
        """Restaura el estado de la UI tras completar una consulta (siempre en hilo principal)."""
        self._toggle_input(True)
        if time.time() < self.ai_blocked_until:
            segundos = int(self.ai_blocked_until - time.time()) + 1
            self._set_estado(f"En espera de cuota ({segundos}s)", self.theme["error"])
        else:
            self._set_estado("Listo para ayudarte", self.theme["ok"])
        if self.ent_pregunta:
            self.ent_pregunta.focus_set()

    def mostrar_en_chat(self, mensaje, autor="Asistente"):
        """
        Agrega un bloque de mensaje al area de chat con formato segun el autor.

        Args:
            mensaje (str): Texto a mostrar.
            autor (str): Identificador del emisor. Valores reconocidos:
                         'Tu' (usuario), 'Sistema' (avisos), 'Asistente' (IA).
        """
        if not self.txt_chat:
            return

        texto = str(mensaje or "").strip()
        if not texto:
            return

        autor_key = str(autor or "Asistente").strip()
        hora = time.strftime("%H:%M")

        if autor_key.lower().startswith("tu"):
            tag_head, tag_body = "user_head", "user_body"
        elif autor_key.lower().startswith("sistema"):
            tag_head, tag_body = "system_head", "system_body"
        else:
            tag_head, tag_body = "assistant_head", "assistant_body"

        self.txt_chat.config(state="normal")
        self.txt_chat.insert(tk.END, f"{autor_key}  {hora}\n", tag_head)
        self.txt_chat.insert(tk.END, f"{texto}\n\n", tag_body)
        self.txt_chat.config(state="disabled")
        self.txt_chat.see(tk.END)

    def limpiar_pantalla(self):
        for widget in self.root.winfo_children():
            widget.destroy()


if __name__ == "__main__":
    ventana = tk.Tk()
    app = BibliotecaApp(ventana)
    ventana.mainloop()
