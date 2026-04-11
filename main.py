# -*- coding: utf-8 -*-
"""
Modulo: main.py
Descripcion: Punto de entrada y capa de presentacion (GUI) construida con Tkinter.
             Implementa la pantalla de login y la pantalla de chat del asistente.

Responsabilidades:
    - Renderizar la interfaz grafica con tema oscuro (teal accent).
    - Coordinar el flujo visual: login -> chat -> renderizado de resultados.
    - Delegar el negocio conversacional a un controller y servicios auxiliares.
    - Gestionar el estado de la UI (bloqueo de inputs, indicador de estado, cuota de IA).

Flujo de autenticacion:
    1. El usuario ingresa su correo electronico y contrasena.
    2. SecurityManager.login() obtiene el hash bcrypt almacenado y verifica
       contra personas.usuarios via el login auxiliar SQL_LOGIN_APP.
    3. Si tiene exito, DatabaseManager se reconstruye con el login de SQL Server
       correspondiente al rol del usuario (admin / operativo / usuario).
    4. Todas las consultas posteriores se ejecutan bajo esa identidad autenticada.
"""

import logging
import os
import threading
import time
import tkinter as tk
from tkinter import messagebox, scrolledtext

from dotenv import load_dotenv

import config
from app_services import (
    ConsultaService,
    RegistroUsuarioData,
    RegistroUsuarioService,
)
from ai_assistant import AIAssistant
from chat_controller import ChatController, MensajeChat, ResultadoConsulta
from config import SQL_LOGIN_OPERATIVO, SQL_PASS_OPERATIVO
from database_manager import DatabaseManager
from features import AdminPanel, AyudaPanel, BusquedaPanel, DashboardPanel, MENSAJES
from seguridad import SecurityManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BibliotecaApp:
    """
    Controlador principal de la interfaz grafica de la Biblioteca Inteligente.

    Gestiona dos pantallas (login y chat) y orquesta la interaccion entre
    las capas de IA, seguridad y base de datos.
    """

    def __init__(self, root):
        self.root = root
        self.root.title("ULATINA | Asistente de Biblioteca")
        self.root.resizable(True, True)
        self.root.minsize(860, 620)
        self.root.update_idletasks()
        w, h = 980, 700
        x = (self.root.winfo_screenwidth() // 2) - (w // 2)
        y = (self.root.winfo_screenheight() // 2) - (h // 2)
        self.root.geometry(f"{w}x{h}+{x}+{y}")

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
        self.registro_service = RegistroUsuarioService()
        self.consulta_service = ConsultaService(self.registro_service)
        self.ai_blocked_until = 0.0
        self._ai_lock = threading.Lock()

        self.btn_enviar = None
        self.ent_pregunta = None
        self.txt_chat = None
        self.lbl_estado = None
        self.txt_sql = None
        self.lbl_modelo = None
        self.lbl_sql_estado = None
        self.lbl_conexion = None
        self.botones_rapidos = []

        # Navegacion entre paneles (se inicializa en pantalla_asistente)
        self._paneles: dict[str, tk.Frame] = {}
        self._nav_botones: dict[str, tk.Button] = {}
        self._contenido: tk.Frame | None = None

        self.ent_reg_nombre = None
        self.ent_reg_apellido = None
        self.ent_reg_correo = None
        self.ent_reg_telefono = None
        self.ent_reg_password = None
        self.ent_reg_confirmar = None

        self.historial_conversacion = []
        self._placeholder = "Escribí tu pregunta en lenguaje natural..."
        self._scroll_canvas_activo = None

        if not config.GEMINI_KEY:
            self.pantalla_error_config()
        else:
            self.pantalla_login()

    def pantalla_login(self):
        """Construye pantalla de autenticacion."""
        self.limpiar_pantalla()

        container = tk.Frame(self.root, bg=self.theme["bg"])
        container.pack(fill=tk.BOTH, expand=True)

        card = tk.Frame(
            container,
            bg=self.theme["panel"],
            highlightthickness=1,
            highlightbackground=self.theme["border"],
        )
        card.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.88, relheight=0.82)

        info_panel = tk.Frame(card, bg=self.theme["accent_soft"], padx=28, pady=32)
        info_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        tk.Label(
            info_panel,
            text="📚",
            bg=self.theme["accent_soft"],
            fg="#e6fffb",
            font=(self.fonts["body"], 42),
        ).pack(anchor="w", pady=(0, 12))

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

        separador = tk.Frame(card, bg=self.theme["border"], width=2)
        separador.pack(side=tk.LEFT, fill=tk.Y, pady=20)

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
            fg=self.theme["accent"],
            font=(self.fonts["body"], 10, "bold"),
        ).pack(anchor="w")
        _box_correo = tk.Frame(
            form_panel,
            bg=self.theme["input_bg"],
            highlightthickness=1,
            highlightbackground=self.theme["border"],
        )
        _box_correo.pack(anchor="w", pady=(6, 14))
        self.ent_correo = tk.Entry(
            _box_correo,
            width=38,
            bg=self.theme["input_bg"],
            fg=self.theme["text"],
            insertbackground=self.theme["text"],
            relief=tk.FLAT,
            bd=0,
            font=(self.fonts["body"], 11),
        )
        self.ent_correo.pack(fill=tk.X, padx=8, ipady=7)

        tk.Label(
            form_panel,
            text="Contrasena",
            bg=self.theme["panel"],
            fg=self.theme["accent"],
            font=(self.fonts["body"], 10, "bold"),
        ).pack(anchor="w")
        _box_pass = tk.Frame(
            form_panel,
            bg=self.theme["input_bg"],
            highlightthickness=1,
            highlightbackground=self.theme["border"],
        )
        _box_pass.pack(anchor="w", pady=(6, 20))
        self.ent_pass = tk.Entry(
            _box_pass,
            width=38,
            show="*",
            bg=self.theme["input_bg"],
            fg=self.theme["text"],
            insertbackground=self.theme["text"],
            relief=tk.FLAT,
            bd=0,
            font=(self.fonts["body"], 11),
        )
        self.ent_pass.pack(fill=tk.X, padx=8, ipady=7)

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
            bg="#1d4ed8",
            fg="#dbeafe",
            activebackground="#1e40af",
            activeforeground="#eff6ff",
            relief=tk.FLAT,
            padx=14,
            pady=7,
            font=(self.fonts["body"], 9, "bold"),
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
        load_dotenv(override=True)
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

        # Panel derecho con Canvas scrollable para el formulario
        form_outer = tk.Frame(card, bg=self.theme["panel"])
        form_outer.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(form_outer, bg=self.theme["panel"], highlightthickness=0)
        scrollbar = tk.Scrollbar(form_outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        form_panel = tk.Frame(canvas, bg=self.theme["panel"], padx=34, pady=34)
        frame_id = canvas.create_window((0, 0), window=form_panel, anchor="nw")

        def _on_frame_configure(_e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        form_panel.bind("<Configure>", _on_frame_configure)
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(frame_id, width=e.width))

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
                fg=self.theme["accent"],
                font=(self.fonts["body"], 10, "bold"),
            ).pack(anchor="w")
            _box = tk.Frame(
                form_panel,
                bg=self.theme["input_bg"],
                highlightthickness=1,
                highlightbackground=self.theme["border"],
            )
            _box.pack(anchor="w", pady=(4, 10))
            ent = tk.Entry(
                _box,
                width=38,
                show="*" if oculto else "",
                bg=self.theme["input_bg"],
                fg=self.theme["text"],
                insertbackground=self.theme["text"],
                relief=tk.FLAT,
                bd=0,
                font=(self.fonts["body"], 11),
            )
            ent.pack(fill=tk.X, padx=8, ipady=6)
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
            text="← Volver al login",
            command=self.pantalla_login,
            bg=self.theme["panel_soft"],
            fg=self.theme["muted"],
            activebackground=self.theme["border"],
            activeforeground=self.theme["text"],
            relief=tk.FLAT,
            padx=14,
            pady=7,
            font=(self.fonts["body"], 9),
            cursor="hand2",
        ).pack(anchor="w", pady=(8, 0))

        self._configurar_scroll_localizado(canvas, form_panel)
        self.ent_reg_nombre.focus_set()

    def ejecutar_registro(self):
        """Valida campos y registra un nuevo usuario en la BD."""
        datos = self._leer_datos_registro_formulario()
        validacion = self.registro_service.validar(
            datos,
            confirmar=self.ent_reg_confirmar.get() if self.ent_reg_confirmar else "",
        )
        if validacion:
            titulo, mensaje = validacion
            messagebox.showwarning(titulo, mensaje)
            return

        try:
            payload = self.registro_service.construir_payload(datos)
            db_reg = DatabaseManager(uid=SQL_LOGIN_OPERATIVO, pwd=SQL_PASS_OPERATIVO)
            resultado = self.registro_service.ejecutar_registro(db_reg, payload)
            if resultado is None:
                messagebox.showerror("Error", "No se pudo registrar el usuario. Es posible que el correo ya este en uso.")
            else:
                messagebox.showinfo(
                    "Registro exitoso",
                    f"Usuario {payload.nombre} registrado correctamente. Ya puedes iniciar sesion.",
                )
                self.pantalla_login()
        except Exception as e:
            messagebox.showerror("Error inesperado", str(e))

    def _activar_scroll_canvas(self, canvas):
        self._scroll_canvas_activo = canvas
        if canvas.winfo_exists():
            canvas.focus_set()

    def _desactivar_scroll_canvas(self, _event=None):
        self._scroll_canvas_activo = None

    def _configurar_scroll_localizado(self, canvas, root_widget):
        def _bind_widget(widget):
            widget.bind("<Enter>", lambda _e, c=canvas: self._activar_scroll_canvas(c), add="+")
            widget.bind("<Leave>", self._desactivar_scroll_canvas, add="+")
            widget.bind("<MouseWheel>", self._on_mousewheel_canvas, add="+")
            for child in widget.winfo_children():
                _bind_widget(child)

        _bind_widget(canvas)
        _bind_widget(root_widget)
        canvas.bind("<Destroy>", self._desactivar_scroll_canvas, add="+")

    def _on_mousewheel_canvas(self, event):
        canvas = self._scroll_canvas_activo
        if canvas is None or not canvas.winfo_exists():
            self._desactivar_scroll_canvas()
            return
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _leer_datos_registro_formulario(self):
        return RegistroUsuarioData(
            nombre=self.ent_reg_nombre.get().strip() if self.ent_reg_nombre else "",
            apellido=self.ent_reg_apellido.get().strip() if self.ent_reg_apellido else "",
            correo=self.ent_reg_correo.get().strip() if self.ent_reg_correo else "",
            telefono=self.ent_reg_telefono.get().strip() if self.ent_reg_telefono else "",
            password=self.ent_reg_password.get() if self.ent_reg_password else "",
            rol="usuario",
        )

    def pantalla_asistente(self):
        """
        Ventana principal con barra de navegacion y paneles intercambiables.

        Construye:
        1. Cabecera global (titulo, chip de rol, indicador de estado).
        2. Barra de navegacion con pestanas: Chat, Dashboard, Busqueda,
           Ayuda y Admin (solo si rol=admin).
        3. Contenedor de paneles donde cada pestana muestra su Frame.
        4. El panel Chat (con el PanedWindow existente) se construye aqui;
           los demas se crean al primera vez que el usuario los activa (lazy).
        """
        self.limpiar_pantalla()
        self._paneles = {}
        self._nav_botones = {}

        usuario = self.seguridad.usuario_actual or {}  # type: ignore[union-attr]
        rol_upper = str(usuario.get("rol") or "sin rol").upper()
        rol = str(usuario.get("rol") or "usuario")

        # --- Cabecera global ---
        top = tk.Frame(self.root, bg=self.theme["panel"], padx=20, pady=14)
        top.pack(fill=tk.X)

        tk.Label(
            top, text="📚",
            bg=self.theme["panel"], fg=self.theme["accent"],
            font=(self.fonts["body"], 20),
        ).pack(side=tk.LEFT, padx=(0, 10))

        tk.Label(
            top, text="Asistente de Biblioteca",
            bg=self.theme["panel"], fg=self.theme["text"],
            font=(self.fonts["title"], 16, "bold"),
        ).pack(side=tk.LEFT)

        tk.Label(
            top, text=f"ROL: {rol_upper}",
            bg="#0f766e", fg="#ecfeff",
            padx=10, pady=4,
            font=(self.fonts["body"], 9, "bold"),
        ).pack(side=tk.RIGHT, padx=(8, 0))

        self.lbl_estado = tk.Label(
            top, text="Listo para ayudarte",
            bg=self.theme["panel"], fg=self.theme["ok"],
            font=(self.fonts["body"], 9),
        )
        self.lbl_estado.pack(side=tk.RIGHT)

        # --- Separador de acento ---
        tk.Frame(self.root, bg=self.theme["accent"], height=2).pack(fill=tk.X)

        # --- Barra de navegacion ---
        nav_bar = tk.Frame(
            self.root, bg=self.theme["panel_soft"], padx=14, pady=5)
        nav_bar.pack(fill=tk.X)
        self._construir_nav_barra(nav_bar, rol)

        # --- Contenedor de paneles (fill restante) ---
        self._contenido = tk.Frame(self.root, bg=self.theme["bg"])
        self._contenido.pack(fill=tk.BOTH, expand=True)

        # --- Construir el panel de chat (contiene el PanedWindow existente) ---
        self._construir_panel_chat(self._contenido, rol)

        # --- Mostrar chat por defecto ---
        self._mostrar_panel_activo("chat")
        self._mostrar_bienvenida()
        if self.ent_pregunta:
            self.ent_pregunta.focus_set()

    # ------------------------------------------------------------------
    # Navegacion entre paneles
    # ------------------------------------------------------------------

    def _construir_nav_barra(self, nav_frame: tk.Frame, rol: str) -> None:
        """
        Crea los botones de navegacion segun el rol del usuario.

        El panel Admin solo aparece para rol 'admin'. El resto de pestanas
        son visibles para todos los roles.

        Args:
            nav_frame: Frame padre donde se empaquetan los botones.
            rol:       Rol del usuario autenticado ('admin', 'operativo', 'usuario').
        """
        tabs = [
            ("chat",      "💬 Chat"),
            ("dashboard", "📊 Dashboard"),
            ("busqueda",  "🔍 Busqueda"),
            ("ayuda",     "💡 Ayuda"),
        ]
        if rol == "admin":
            tabs.append(("admin", "⚙ Admin"))

        for key, label in tabs:
            btn = tk.Button(
                nav_frame, text=label,
                command=lambda k=key: self._mostrar_panel_activo(k),
                bg=self.theme["panel_soft"], fg=self.theme["muted"],
                activebackground=self.theme["accent"], activeforeground="#042f2e",
                relief=tk.FLAT, padx=14, pady=6,
                font=(self.fonts["body"], 9, "bold"),
                cursor="hand2",
            )
            btn.pack(side=tk.LEFT, padx=(0, 2))
            self._nav_botones[key] = btn

    def _mostrar_panel_activo(self, nombre: str) -> None:
        """
        Oculta todos los paneles y muestra el solicitado.

        Si el panel no fue construido aun, lo instancia de forma lazy antes
        de mostrarlo. Actualiza el estilo de los botones de navegacion.

        Args:
            nombre: Identificador del panel ('chat', 'dashboard', 'busqueda',
                    'ayuda', 'admin').
        """
        # Ocultar todos los paneles activos
        for panel in self._paneles.values():
            panel.pack_forget()

        # Construir el panel si aun no existe (lazy instantiation)
        if nombre not in self._paneles and self._contenido:
            if nombre == "dashboard":
                p = DashboardPanel(
                    self._contenido, self.theme, self.fonts, self.db, self.seguridad)
            elif nombre == "busqueda":
                p = BusquedaPanel(
                    self._contenido, self.theme, self.fonts, self.db, self.seguridad,
                    on_usar_en_chat=self._usar_consulta_rapida)
            elif nombre == "ayuda":
                p = AyudaPanel(
                    self._contenido, self.theme, self.fonts, self.db, self.seguridad,
                    on_enviar_al_chat=self._usar_consulta_rapida_desde_ayuda)
            elif nombre == "admin":
                p = AdminPanel(
                    self._contenido, self.theme, self.fonts, self.db, self.seguridad)
            else:
                return
            self._paneles[nombre] = p

        # Mostrar el panel solicitado
        if nombre in self._paneles:
            self._paneles[nombre].pack(fill=tk.BOTH, expand=True)

        # Actualizar estilo de los botones de navegacion
        for key, btn in self._nav_botones.items():
            if key == nombre:
                btn.config(bg=self.theme["accent"], fg="#042f2e")
            else:
                btn.config(bg=self.theme["panel_soft"], fg=self.theme["muted"])

    def _usar_consulta_rapida_desde_ayuda(self, consulta: str) -> None:
        """
        Recibe un ejemplo de la pantalla de Ayuda, lo coloca en el input del chat
        y activa la pestana de chat automaticamente.
        """
        self._mostrar_panel_activo("chat")
        self._usar_consulta_rapida(consulta)

    # ------------------------------------------------------------------
    # Panel de chat (extraido de pantalla_asistente para claridad)
    # ------------------------------------------------------------------

    def _construir_panel_chat(self, parent: tk.Widget, rol: str) -> None:
        """
        Construye el panel de chat con el PanedWindow izquierdo/derecho.

        Contiene exactamente el mismo contenido que el antiguo metodo
        pantalla_asistente, ahora empaquetado en un Frame independiente
        para que pueda convivir con los demas paneles de la barra de navegacion.

        Args:
            parent: Frame contenedor donde se empaquetara el panel.
            rol:    Rol del usuario para definir los botones de consulta rapida.
        """
        panel = tk.Frame(parent, bg=self.theme["bg"])
        self._paneles["chat"] = panel

        paned = tk.PanedWindow(
            panel,
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

        if rol == "admin":
            consulta_rapida = [
                "Cuántos libros hay registrados?",
                "Préstamos activos",
                "Registrar nuevo libro",
                "Préstamos vencidos",
            ]
        elif rol == "operativo":
            consulta_rapida = [
                "Cuántos libros hay registrados?",
                "Préstamos activos",
                "Préstamos vencidos",
                "Lista de autores",
            ]
        else:
            consulta_rapida = [
                "Cuántos libros hay registrados?",
                "Libros de tecnología",
                "Lista de autores",
                "Libros disponibles",
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
        composer.pack(fill=tk.X, pady=(8, 8))

        input_box = tk.Frame(
            composer,
            bg=self.theme["input_bg"],
            highlightthickness=2,
            highlightbackground=self.theme["accent"],
            padx=6,
        )
        input_box.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.ent_pregunta = tk.Entry(
            input_box,
            bg=self.theme["input_bg"],
            fg=self.theme["muted"],
            insertbackground=self.theme["text"],
            relief=tk.FLAT,
            bd=0,
            font=(self.fonts["body"], 11),
        )
        self.ent_pregunta.pack(fill=tk.X, padx=10, ipady=12)
        self.ent_pregunta.bind("<Return>", lambda _e: self.procesar_consulta())
        self.ent_pregunta.bind("<FocusIn>", self._on_entry_focus_in)
        self.ent_pregunta.bind("<FocusOut>", self._on_entry_focus_out)
        self._activar_placeholder_pregunta()

        self.btn_enviar = tk.Button(
            composer,
            text="Enviar ➤",
            command=self.procesar_consulta,
            bg=self.theme["accent"],
            fg="#042f2e",
            activebackground="#2dd4bf",
            activeforeground="#022c22",
            relief=tk.FLAT,
            padx=20,
            pady=12,
            font=(self.fonts["body"], 10, "bold"),
            cursor="hand2",
        )
        self.btn_enviar.pack(side=tk.LEFT, padx=(8, 0))

        # ── Panel derecho: SQL en tiempo real (≈35%) ──────────────────
        right = tk.Frame(paned, bg=self.theme["panel"], padx=12, pady=12)
        paned.add(right, minsize=200)

        tk.Label(
            right,
            text="⚡ SQL generado",
            bg=self.theme["panel"],
            fg=self.theme["accent"],
            font=(self.fonts["body"], 11, "bold"),
            anchor="w",
        ).pack(fill=tk.X)

        self.lbl_conexion = tk.Label(
            right,
            text="● Conectado a biblioteca",
            bg=self.theme["panel"],
            fg=self.theme["ok"],
            font=(self.fonts["body"], 8),
            anchor="w",
        )
        self.lbl_conexion.pack(fill=tk.X, pady=(0, 8))

        tk.Frame(right, bg=self.theme["border"], height=1).pack(fill=tk.X, pady=(0, 6))

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
        self.txt_sql.config(state="normal")
        self.txt_sql.insert(tk.END, "-- Aquí aparecerá el SQL generado por la IA.\n-- Cada consulta reemplaza este contenido.")
        self.txt_sql.config(state="disabled")

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

        # Ajustar proporcion 65/35 tras renderizar
        self.root.update_idletasks()
        total = paned.winfo_width()
        if total > 10:
            paned.sash_place(0, int(total * 0.65), 0)

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
        if not self.txt_chat:
            return
        self.txt_chat.tag_configure(
            "assistant_head",
            foreground="#2dd4bf",
            font=(self.fonts["title"], 10, "bold"),
            spacing1=6,
        )
        self.txt_chat.tag_configure(
            "user_head",
            foreground="#93c5fd",
            font=(self.fonts["title"], 10, "bold"),
            spacing1=6,
        )
        self.txt_chat.tag_configure(
            "system_head",
            foreground="#f59e0b",
            font=(self.fonts["title"], 10, "bold"),
            spacing1=6,
        )
        self.txt_chat.tag_configure(
            "burbuja_user",
            background="#1d4ed8",
            foreground="#dbeafe",
            lmargin1=200,
            lmargin2=200,
            rmargin=12,
            spacing1=4,
            spacing3=4,
        )
        self.txt_chat.tag_configure(
            "burbuja_asistente",
            background="#1f2937",
            foreground=self.theme["text"],
            lmargin1=12,
            lmargin2=12,
            rmargin=200,
            spacing1=4,
            spacing3=4,
        )
        self.txt_chat.tag_configure(
            "burbuja_sistema",
            background="#292524",
            foreground="#fde68a",
            lmargin1=40,
            lmargin2=40,
            rmargin=40,
            spacing1=4,
            spacing3=4,
        )
        self.txt_chat.tag_configure(
            "separador_msg",
            spacing1=6,
            spacing3=6,
        )

    def _mostrar_bienvenida(self):
        usuario = self.seguridad.usuario_actual or {}
        nombre = str(usuario.get("nombre") or "usuario")
        rol = str(usuario.get("rol") or "usuario")
        _desc = {
            "admin":     "Acceso total: catálogo, préstamos, usuarios y auditoría.",
            "operativo": "Gestión de préstamos y consultas avanzadas.",
            "usuario":   "Consultas de catálogo y disponibilidad.",
        }
        desc = _desc.get(rol, self.seguridad.describir_permisos())
        mensaje = (
            f"¡Hola, {nombre}!  Rol: {rol.upper()}\n"
            f"{desc}\n\n"
            f"Ejemplos de consultas:\n"
            f"  • ¿Cuántos libros hay registrados?\n"
            f"  • Préstamos vencidos\n"
            f"  • Libros disponibles de tecnología\n"
            f"  • Registrar devolución del libro X"
        )
        self.mostrar_en_chat(mensaje, autor="Sistema")

    def _usar_consulta_rapida(self, consulta):
        if not self.ent_pregunta:
            return
        self._desactivar_placeholder_pregunta()
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

    def _activar_placeholder_pregunta(self):
        if not self.ent_pregunta:
            return
        self.ent_pregunta.delete(0, tk.END)
        self.ent_pregunta.insert(0, self._placeholder)
        self.ent_pregunta.config(fg=self.theme["muted"])

    def _desactivar_placeholder_pregunta(self):
        if not self.ent_pregunta:
            return
        if self.ent_pregunta.get() == self._placeholder:
            self.ent_pregunta.delete(0, tk.END)
        self.ent_pregunta.config(fg=self.theme["text"])

    def _on_entry_focus_in(self, _event):
        self._desactivar_placeholder_pregunta()

    def _on_entry_focus_out(self, _event):
        if self.ent_pregunta and not self.ent_pregunta.get().strip():
            self._activar_placeholder_pregunta()

    def _validar_entrada_usuario(self):
        pregunta = self.ent_pregunta.get().strip() if self.ent_pregunta else ""
        if not pregunta or pregunta == self._placeholder:
            return None
        return pregunta

    def procesar_consulta(self):
        pregunta = self._validar_entrada_usuario()
        if pregunta is None:
            return

        self.mostrar_en_chat(pregunta, autor="Tu")
        self.ent_pregunta.delete(0, tk.END)
        self._toggle_input(False)
        self._set_estado("Consultando...", self.theme["warn"])

        threading.Thread(
            target=self._procesar_consulta_async,
            args=(pregunta,),
            daemon=True,
        ).start()

    def _agregar_historial(self, rol, texto):
        self.historial_conversacion.append({"rol": rol, "texto": texto})
        if len(self.historial_conversacion) > 10:
            self.historial_conversacion = self.historial_conversacion[-10:]

    def _crear_chat_controller(self):
        return ChatController(
            asistente=self.asistente,
            db=self.db,
            seguridad=self.seguridad,
            consulta_service=self.consulta_service,
        )

    def _aplicar_historial_resultado(self, resultado: ResultadoConsulta):
        for entrada in resultado.historial:
            self._agregar_historial(entrada.rol, entrada.texto)

    def _aplicar_resultado_consulta(self, resultado: ResultadoConsulta):
        try:
            if resultado.ai_blocked_until is not None:
                with self._ai_lock:
                    self.ai_blocked_until = resultado.ai_blocked_until

            self._aplicar_historial_resultado(resultado)

            if resultado.sql is not None:
                self.mostrar_sql(
                    resultado.sql,
                    resultado.modelo or "-",
                    resultado.estado_sql or "",
                )

            for mensaje in resultado.mensajes:
                self.mostrar_en_chat(mensaje.texto, mensaje.autor)
        except Exception:
            # Widgets destruidos por cambio de pantalla antes de aplicar el resultado.
            pass
        finally:
            self._finalizar_consulta()

    def _procesar_consulta_async(self, pregunta: str) -> None:
        """
        Ejecuta el controller en un hilo secundario y delega el render a Tkinter.

        Los detalles tecnicos del error se registran en el logger; el usuario
        ve solo un mensaje amigable que no expone detalles internos.
        """
        with self._ai_lock:
            blocked_until = self.ai_blocked_until

        controller = self._crear_chat_controller()
        try:
            resultado = controller.procesar_consulta(
                pregunta=pregunta,
                historial_conversacion=list(self.historial_conversacion),
                ai_blocked_until=blocked_until,
            )
        except Exception as exc:
            # Loguear el error tecnico sin mostrarlo al usuario
            logger.error("Error inesperado en procesar_consulta_async: %s", exc)
            resultado = ResultadoConsulta(
                mensajes=(MensajeChat(MENSAJES["error_inesperado"], "Sistema"),),
            )

        # Registrar la consulta en la tabla de auditoria (no bloqueante)
        self._registrar_auditoria(pregunta, resultado)

        self.root.after(0, self._aplicar_resultado_consulta, resultado)

    def _registrar_auditoria(self, pregunta: str, resultado: ResultadoConsulta) -> None:
        """
        Inserta un registro en auditoria.consultas de forma asincrona.

        Si la tabla no existe (database_patch.sql no ejecutado), el error
        se captura silenciosamente sin afectar la experiencia del usuario.

        Args:
            pregunta:  Texto original del usuario.
            resultado: ResultadoConsulta con sql, estado y posible bloqueo.
        """
        usuario = (self.seguridad.usuario_actual or {}) if self.seguridad else {}
        id_usuario = usuario.get("id")
        nombre = f"{usuario.get('nombre', '')} {usuario.get('apellido', '')}".strip()

        # Determinar estado legible para la auditoria
        estado_sql = resultado.estado_sql or ""
        if "correctamente" in estado_sql.lower():
            estado = "ejecutado"
        elif "bloqueado" in estado_sql.lower():
            estado = "bloqueado"
        elif resultado.ai_blocked_until:
            estado = "cuota_ia"
        elif resultado.sql is None and resultado.historial:
            estado = "conversacional"
        else:
            estado = "error"

        sql_log = resultado.sql or ""

        def _insert() -> None:
            if self.db is None:
                return
            try:
                self.db.ejecutar_consulta(
                    "INSERT INTO auditoria.consultas "
                    "(id_usuario, nombre_usuario, pregunta, sql_generado, resultado) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (id_usuario, nombre or "desconocido",
                     pregunta[:4000], sql_log[:4000], estado),
                )
            except Exception:
                # La tabla de auditoria es opcional; no propagar el error
                pass

        threading.Thread(target=_insert, daemon=True).start()

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
            tag_head = "user_head"
            tag_body = "burbuja_user"
        elif autor_key.lower().startswith("sistema"):
            tag_head = "system_head"
            tag_body = "burbuja_sistema"
        else:
            tag_head = "assistant_head"
            tag_body = "burbuja_asistente"

        self.txt_chat.config(state="normal")
        self.txt_chat.insert(tk.END, f" {autor_key}  {hora}\n", tag_head)
        self.txt_chat.insert(tk.END, f" {texto} \n", tag_body)
        self.txt_chat.insert(tk.END, "\n", "separador_msg")
        self.txt_chat.config(state="disabled")
        self.txt_chat.see(tk.END)

    def limpiar_pantalla(self):
        self.historial_conversacion = []
        self._desactivar_scroll_canvas()
        for widget in self.root.winfo_children():
            widget.destroy()


if __name__ == "__main__":
    ventana = tk.Tk()
    app = BibliotecaApp(ventana)
    ventana.mainloop()
