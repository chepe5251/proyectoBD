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
        self.db = None       # Se construye con las credenciales del usuario tras el login.
        self.asistente = None  # Se instancia despues del login exitoso.
        self.seguridad = None
        self.ai_blocked_until = 0.0
        self._ai_lock = threading.Lock()

        self.btn_enviar = None
        self.ent_pregunta = None
        self.txt_chat = None
        self.lbl_estado = None
        self.txt_sql = None
        self.lbl_modelo = None
        self.lbl_sql_estado = None
        self.botones_rapidos = []

        self.ent_reg_nombre = None
        self.ent_reg_apellido = None
        self.ent_reg_correo = None
        self.ent_reg_telefono = None
        self.ent_reg_password = None
        self.ent_reg_confirmar = None

        from config import GEMINI_KEY
        if not GEMINI_KEY:
            self.pantalla_error_config()
        else:
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

        btn_registro = tk.Button(
            form_panel,
            text="Registrar usuario",
            command=self.pantalla_registro,
            bg=self.theme["panel_soft"],
            fg=self.theme["muted"],
            activebackground=self.theme["border"],
            activeforeground=self.theme["text"],
            relief=tk.FLAT,
            padx=14,
            pady=6,
            font=(self.fonts["body"], 9),
            cursor="hand2",
        )
        btn_registro.pack(anchor="w", pady=(8, 0))

        self.ent_pass.bind("<Return>", lambda _e: self.ejecutar_login())
        self.ent_correo.focus_set()

    def pantalla_error_config(self):
        """Pantalla que se muestra cuando falta GEMINI_API_KEY en el entorno."""
        self.limpiar_pantalla()

        container = tk.Frame(self.root, bg=self.theme["bg"])
        container.pack(fill=tk.BOTH, expand=True, padx=40, pady=40)

        card = tk.Frame(
            container,
            bg=self.theme["panel"],
            highlightthickness=2,
            highlightbackground=self.theme["error"],
            padx=36,
            pady=36,
        )
        card.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            card,
            text="Error de configuracion",
            bg=self.theme["panel"],
            fg=self.theme["error"],
            font=(self.fonts["title"], 18, "bold"),
        ).pack(anchor="w")

        tk.Label(
            card,
            text="Falta el archivo .env o la variable GEMINI_API_KEY no esta definida.",
            bg=self.theme["panel"],
            fg=self.theme["text"],
            font=(self.fonts["body"], 11),
            wraplength=700,
            justify="left",
        ).pack(anchor="w", pady=(10, 20))

        tk.Label(
            card,
            text="Crea un archivo .env en la raiz del proyecto con el siguiente contenido:",
            bg=self.theme["panel"],
            fg=self.theme["muted"],
            font=(self.fonts["body"], 10),
        ).pack(anchor="w", pady=(0, 8))

        variables = (
            "GEMINI_API_KEY=tu_clave_de_google_gemini\n"
            "DB_SERVER=nombre_de_tu_servidor\n"
            "DB_NAME=biblioteca\n"
            "SQL_LOGIN_APP=login_app\n"
            "SQL_PASS_APP=App#2026!\n"
            "SQL_LOGIN_ADMIN=login_admin\n"
            "SQL_PASS_ADMIN=Admin#2026!\n"
            "SQL_LOGIN_OPERATIVO=login_operativo\n"
            "SQL_PASS_OPERATIVO=Operativo#2026!\n"
            "SQL_LOGIN_USUARIO=login_usuario\n"
            "SQL_PASS_USUARIO=Usuario#2026!"
        )
        txt = tk.Text(
            card,
            bg=self.theme["input_bg"],
            fg="#a3e635",
            font=(self.fonts["mono"], 10),
            relief=tk.FLAT,
            bd=0,
            padx=12,
            pady=10,
            height=12,
            state="normal",
        )
        txt.insert(tk.END, variables)
        txt.config(state="disabled")
        txt.pack(fill=tk.X, pady=(0, 20))

        tk.Button(
            card,
            text="Reintentar",
            command=self.reintentar_config,
            bg=self.theme["accent"],
            fg="#042f2e",
            activebackground="#2dd4bf",
            activeforeground="#022c22",
            relief=tk.FLAT,
            padx=16,
            pady=9,
            font=(self.fonts["body"], 10, "bold"),
            cursor="hand2",
        ).pack(anchor="w")

    def reintentar_config(self):
        """Recarga variables de entorno y reintenta arrancar la app."""
        from dotenv import load_dotenv
        load_dotenv(override=True)
        import config
        import os
        config.GEMINI_KEY = os.getenv("GEMINI_API_KEY")
        if config.GEMINI_KEY:
            self.pantalla_login()
        else:
            messagebox.showerror(
                "Clave no encontrada",
                "GEMINI_API_KEY sigue sin detectarse. Verifica el archivo .env y vuelve a intentarlo.",
            )

    def ejecutar_login(self):
        """Valida credenciales y abre el chat principal."""
        correo = self.ent_correo.get().strip()
        password = self.ent_pass.get()  # Sin strip: espacios son parte de la contraseña

        if not correo or not password:
            messagebox.showwarning("Datos requeridos", "Debes ingresar correo y contrasena.")
            return

        self.seguridad = SecurityManager(self.db)
        if self.seguridad.login(correo, password):
            info = self.seguridad.usuario_actual
            self.db = DatabaseManager(uid=info["uid"], pwd=info["pwd"])
            self.seguridad.db = self.db
            try:
                self.asistente = AIAssistant()
            except ValueError as exc:
                messagebox.showerror("Error de configuracion", str(exc))
                return
            self.pantalla_asistente()
            return

        messagebox.showerror("Acceso denegado", "Credenciales incorrectas.")

    def pantalla_registro(self):
        """Pantalla completa para registrar un nuevo usuario."""
        self.limpiar_pantalla()

        container = tk.Frame(self.root, bg=self.theme["bg"])
        container.pack(fill=tk.BOTH, expand=True, padx=30, pady=30)

        card = tk.Frame(
            container,
            bg=self.theme["panel"],
            highlightthickness=1,
            highlightbackground=self.theme["border"],
        )
        card.pack(fill=tk.BOTH, expand=True)

        info_panel = tk.Frame(card, bg=self.theme["accent_soft"], padx=28, pady=32)
        info_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        tk.Label(
            info_panel,
            text="Nuevo Usuario",
            bg=self.theme["accent_soft"],
            fg="#e6fffb",
            font=(self.fonts["title"], 22, "bold"),
        ).pack(anchor="w")

        tk.Label(
            info_panel,
            text="Completa el formulario para registrarte en el sistema de biblioteca.",
            bg=self.theme["accent_soft"],
            fg="#ccfbf1",
            font=(self.fonts["body"], 11),
            justify="left",
            wraplength=340,
        ).pack(anchor="w", pady=(10, 20))

        for item in ["Rol asignado: usuario", "Acceso de solo lectura al catalogo", "Gestionado por el administrador"]:
            tk.Label(
                info_panel,
                text=f"- {item}",
                bg=self.theme["accent_soft"],
                fg="#ecfeff",
                font=(self.fonts["body"], 10),
                anchor="w",
            ).pack(anchor="w", pady=2)

        form_panel = tk.Frame(card, bg=self.theme["panel"], padx=34, pady=34)
        form_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        tk.Label(
            form_panel,
            text="Crear cuenta",
            bg=self.theme["panel"],
            fg=self.theme["text"],
            font=(self.fonts["title"], 20, "bold"),
        ).pack(anchor="w")

        tk.Label(
            form_panel,
            text="Ingresa tus datos para registrarte.",
            bg=self.theme["panel"],
            fg=self.theme["muted"],
            font=(self.fonts["body"], 10),
        ).pack(anchor="w", pady=(6, 14))

        campos_def = [
            ("ent_reg_nombre",    "Nombre",              False),
            ("ent_reg_apellido",  "Apellido",            False),
            ("ent_reg_correo",    "Correo electronico",  False),
            ("ent_reg_telefono",  "Telefono",            False),
            ("ent_reg_password",  "Contrasena",          True),
            ("ent_reg_confirmar", "Confirmar contrasena",True),
        ]
        for attr, label, oculto in campos_def:
            tk.Label(
                form_panel,
                text=label,
                bg=self.theme["panel"],
                fg=self.theme["text"],
                font=(self.fonts["body"], 10, "bold"),
            ).pack(anchor="w")
            ent = tk.Entry(
                form_panel,
                width=38,
                show="*" if oculto else "",
                bg=self.theme["input_bg"],
                fg=self.theme["text"],
                insertbackground=self.theme["text"],
                relief=tk.FLAT,
                font=(self.fonts["body"], 11),
            )
            ent.pack(anchor="w", ipady=6, pady=(4, 10))
            setattr(self, attr, ent)

        self.ent_reg_confirmar.bind("<Return>", lambda _e: self.ejecutar_registro())

        tk.Button(
            form_panel,
            text="Crear cuenta",
            command=self.ejecutar_registro,
            bg=self.theme["accent"],
            fg="#042f2e",
            activebackground="#2dd4bf",
            activeforeground="#022c22",
            relief=tk.FLAT,
            padx=14,
            pady=9,
            font=(self.fonts["body"], 10, "bold"),
            cursor="hand2",
        ).pack(anchor="w")

        tk.Button(
            form_panel,
            text="Volver al login",
            command=self.pantalla_login,
            bg=self.theme["panel_soft"],
            fg=self.theme["muted"],
            activebackground=self.theme["border"],
            activeforeground=self.theme["text"],
            relief=tk.FLAT,
            padx=14,
            pady=6,
            font=(self.fonts["body"], 9),
            cursor="hand2",
        ).pack(anchor="w", pady=(8, 0))

        self.ent_reg_nombre.focus_set()

    def ejecutar_registro(self):
        """Valida campos y registra un nuevo usuario en la BD."""
        nombre    = self.ent_reg_nombre.get().strip()
        apellido  = self.ent_reg_apellido.get().strip()
        correo    = self.ent_reg_correo.get().strip()
        telefono  = self.ent_reg_telefono.get().strip()
        password  = self.ent_reg_password.get()
        confirmar = self.ent_reg_confirmar.get()

        if not all([nombre, apellido, correo, telefono, password, confirmar]):
            messagebox.showwarning("Datos incompletos", "Todos los campos son obligatorios.")
            return
        if "@" not in correo or "." not in correo.split("@")[-1]:
            messagebox.showwarning("Correo invalido", "El correo ingresado no es valido.")
            return
        if len(telefono) < 8:
            messagebox.showwarning("Telefono invalido", "El telefono debe tener al menos 8 caracteres.")
            return
        if len(password) < 6:
            messagebox.showwarning("Contrasena corta", "La contrasena debe tener al menos 6 caracteres.")
            return
        if password != confirmar:
            messagebox.showwarning("Contrasenas distintas", "Las contrasenas no coinciden.")
            return

        try:
            import bcrypt
            from config import SQL_LOGIN_OPERATIVO, SQL_PASS_OPERATIVO

            pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()
            db_reg = DatabaseManager(uid=SQL_LOGIN_OPERATIVO, pwd=SQL_PASS_OPERATIVO)
            resultado = db_reg.ejecutar_consulta(
                "EXEC personas.registrar_usuario @nombre=?, @apellido=?, @correo=?, @telefono=?, @password_hash=?, @rol=?",
                (nombre, apellido, correo, telefono, pw_hash, "usuario"),
            )
            if resultado is None:
                messagebox.showerror("Error", "No se pudo registrar el usuario. Es posible que el correo ya este en uso.")
            else:
                messagebox.showinfo("Registro exitoso", f"Usuario {nombre} registrado correctamente. Ya puedes iniciar sesion.")
                self.pantalla_login()
        except Exception as e:
            messagebox.showerror("Error inesperado", str(e))

    def pantalla_asistente(self):
        """Ventana principal del chat con panel SQL lateral."""
        self.limpiar_pantalla()
        usuario = self.seguridad.usuario_actual or {}  # type: ignore[union-attr]
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

        paned = tk.PanedWindow(
            self.root,
            orient=tk.HORIZONTAL,
            bg=self.theme["bg"],
            sashwidth=5,
            sashrelief=tk.FLAT,
        )
        paned.pack(fill=tk.BOTH, expand=True, padx=20, pady=16)

        # ── Panel izquierdo: chat (≈65%) ──────────────────────────────
        left = tk.Frame(paned, bg=self.theme["bg"])
        paned.add(left, minsize=400)

        self.txt_chat = scrolledtext.ScrolledText(
            left,
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

        tools = tk.Frame(left, bg=self.theme["bg"], pady=10)
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

        composer = tk.Frame(left, bg=self.theme["bg"])
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

        # ── Panel derecho: SQL en tiempo real (≈35%) ──────────────────
        right = tk.Frame(paned, bg=self.theme["panel"], padx=12, pady=12)
        paned.add(right, minsize=200)

        tk.Label(
            right,
            text="SQL generado",
            bg=self.theme["panel"],
            fg=self.theme["accent"],
            font=(self.fonts["body"], 10, "bold"),
            anchor="w",
        ).pack(fill=tk.X)

        self.txt_sql = scrolledtext.ScrolledText(
            right,
            wrap=tk.WORD,
            bg=self.theme["input_bg"],
            fg="#a3e635",
            font=(self.fonts["mono"], 10),
            relief=tk.FLAT,
            bd=0,
            state="disabled",
        )
        self.txt_sql.pack(fill=tk.BOTH, expand=True, pady=(6, 8))

        tk.Frame(right, bg=self.theme["border"], height=1).pack(fill=tk.X, pady=(0, 6))

        self.lbl_modelo = tk.Label(
            right,
            text="Modelo: —",
            bg=self.theme["panel"],
            fg=self.theme["muted"],
            font=(self.fonts["body"], 9),
            anchor="w",
        )
        self.lbl_modelo.pack(fill=tk.X)

        self.lbl_sql_estado = tk.Label(
            right,
            text="",
            bg=self.theme["panel"],
            fg=self.theme["muted"],
            font=(self.fonts["body"], 9),
            anchor="w",
        )
        self.lbl_sql_estado.pack(fill=tk.X)

        # Ajustar proporción 65/35 tras renderizar
        self.root.update_idletasks()
        total = paned.winfo_width()
        if total > 10:
            paned.sash_place(0, int(total * 0.65), 0)

        self._mostrar_bienvenida()
        self.ent_pregunta.focus_set()

    def mostrar_sql(self, sql: str, modelo: str, estado: str = ""):
        """Actualiza el panel lateral con el SQL generado y el estado de la ejecucion."""
        if self.txt_sql is None:
            return
        self.txt_sql.config(state="normal")
        self.txt_sql.delete("1.0", tk.END)
        self.txt_sql.insert(tk.END, sql)
        self.txt_sql.config(state="disabled")
        if self.lbl_modelo:
            self.lbl_modelo.config(text=f"Modelo: {modelo}")
        if self.lbl_sql_estado:
            self.lbl_sql_estado.config(text=estado)

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

        if self.asistente is None or self.db is None:
            ui(self.mostrar_en_chat, "Sesion no inicializada correctamente.", "Sistema")
            return

        try:
            with self._ai_lock:
                blocked_until = self.ai_blocked_until
            ahora = time.time()
            if ahora < blocked_until:
                segundos = int(blocked_until - ahora) + 1
                ui(self.mostrar_en_chat,
                   f"La IA esta temporalmente sin cuota. Intenta de nuevo en {segundos} segundos.",
                   "Sistema")
                return

            try:
                sql = self.asistente.interpretar_pregunta(pregunta)
            except AIQuotaExceededError as exc:
                retry_after = exc.retry_after_seconds or 30
                with self._ai_lock:
                    self.ai_blocked_until = time.time() + retry_after
                ui(self.mostrar_en_chat, str(exc), "Sistema")
                return
            except AIServiceError as exc:
                ui(self.mostrar_en_chat, f"Error de IA: {exc}", "Sistema")
                return

            sql = self._normalizar_sql(sql)
            modelo = self.asistente.model_name
            if not sql:
                ui(self.mostrar_sql, "(no se genero SQL valido)", modelo, "")
                ui(self.mostrar_en_chat, "No se pudo generar una consulta valida.", "Sistema")
                return

            if "?" in sql:
                ui(self.mostrar_sql, sql, modelo, "Pendiente de validacion")
                ui(self.mostrar_en_chat,
                   "La consulta generada quedo incompleta (placeholder '?'). Intenta reformular.",
                   "Sistema")
                return

            ui(self.mostrar_sql, sql, modelo, "Pendiente de validacion")

            if not self.seguridad.validar_accion(sql):  # type: ignore[union-attr]
                ui(self.mostrar_sql, sql, modelo, "⚠ Bloqueado por permisos de rol")
                ui(self.mostrar_en_chat,
                   f"No puedo ejecutar esa accion con tu rol actual. {self.seguridad.describir_permisos()}",  # type: ignore[union-attr]
                   "Sistema")
                return

            # Limitar resultados en SELECT sin TOP para evitar traer toda la tabla.
            if re.match(r"^\s*SELECT\s+(?!TOP\s)", sql, re.IGNORECASE):
                sql = re.sub(r"(?i)^(\s*SELECT\s+)", r"\1TOP 100 ", sql, count=1)

            datos_crudos = self.db.ejecutar_consulta(sql)
            if datos_crudos is None:
                ui(self.mostrar_sql, sql, modelo, "✗ Error en base de datos")
                ui(self.mostrar_en_chat, "Ocurrio un error al consultar la base de datos.", "Sistema")
                return

            ui(self.mostrar_sql, sql, modelo, "✓ Ejecutado correctamente")
            respuesta_final = self.asistente.formatear_respuesta_humana(pregunta, datos_crudos)
            ui(self.mostrar_en_chat, respuesta_final, "Asistente")
        finally:
            ui(self._finalizar_consulta)

    def _finalizar_consulta(self):
        """Restaura el estado de la UI tras completar una consulta (siempre en hilo principal)."""
        try:
            self._toggle_input(True)
            with self._ai_lock:
                blocked_until = self.ai_blocked_until
            if time.time() < blocked_until:
                segundos = int(blocked_until - time.time()) + 1
                self._set_estado(f"En espera de cuota ({segundos}s)", self.theme["error"])
            else:
                self._set_estado("Listo para ayudarte", self.theme["ok"])
            if self.ent_pregunta:
                self.ent_pregunta.focus_set()
        except Exception:
            # Widgets destruidos por cambio de pantalla antes de que el hilo finalizara.
            pass

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
