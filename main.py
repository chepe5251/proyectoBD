# -*- coding: utf-8 -*-
"""
Módulo: main.py
Descripción: Punto de entrada y capa de presentación (GUI).

Interfaz migrada a CustomTkinter para dark mode consistente y aspecto moderno.
La lógica de negocio, autenticación y consultas no fueron modificadas.

Widgets migrados a CustomTkinter:
    - Ventana principal: ctk.CTk
    - Contenedores: ctk.CTkFrame
    - Etiquetas: ctk.CTkLabel
    - Botones: ctk.CTkButton
    - Entradas de texto: ctk.CTkEntry
    - Formulario de registro con scroll: ctk.CTkScrollableFrame
    - Cuadro de variables .env: ctk.CTkTextbox

Widgets conservados en Tkinter/ttk (no tienen equivalente CTk funcional):
    - scrolledtext.ScrolledText — área de chat y panel SQL (soporte de tags de color)
    - tk.PanedWindow — divisor redimensionable chat / panel SQL
    - tk.Canvas (eliminado en registro) — reemplazado por CTkScrollableFrame
    - tk.Frame interno en PanedWindow — compatibilidad con sash geometry

Soporte de español:
    - Archivo declarado UTF-8 (primera línea)
    - Todos los textos visibles corregidos: tildes, ñ, signos de interrogación

Flujo de autenticación:
    1. El usuario ingresa su correo electrónico y contraseña.
    2. SecurityManager.login() obtiene el hash bcrypt y verifica contra personas.usuarios.
    3. Si tiene éxito, DatabaseManager se reconstruye con el login del rol del usuario.
    4. Todas las consultas posteriores se ejecutan bajo esa identidad autenticada.
"""

import logging
import os
import threading
import time
import tkinter as tk
from tkinter import messagebox, scrolledtext  # scrolledtext conservado: tags de color para el chat

import customtkinter as ctk  # MIGRADO: interfaz principal a CustomTkinter

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

# ---------------------------------------------------------------------------
# Configuración global de CustomTkinter
# ---------------------------------------------------------------------------
ctk.set_appearance_mode("dark")          # Modo oscuro global
ctk.set_default_color_theme("dark-blue") # Tema base; los colores teal se aplican por widget

# ---------------------------------------------------------------------------
# Iconografía vectorial — Segoe MDL2 Assets (incluida en Windows 10 / 11)
# Todos los iconos son glifos de fuente: sin archivos externos, sin rutas locales.
# ---------------------------------------------------------------------------
_ICON_FONT = "Segoe MDL2 Assets"
_ICONS: dict[str, str] = {
    "menu":      "\uE700",  # GlobalNavButton (☰)
    "chat":      "\uE8BD",  # Talk / Chat
    "dashboard": "\uE9D2",  # AreaChart
    "busqueda":  "\uE721",  # Search
    "ayuda":     "\uE897",  # Help
    "admin":     "\uE713",  # Settings
    "refresh":   "\uE72C",  # Refresh / ArrowSync
    "logout":    "\uE7E8",  # Power / LogOut
}

class BibliotecaApp:
    """
    Controlador principal de la interfaz gráfica de la Biblioteca Inteligente.

    Gestiona dos pantallas (login y chat) y orquesta la interacción entre
    las capas de IA, seguridad y base de datos.

    Interfaz migrada a CustomTkinter; la lógica permanece intacta.
    """

    def __init__(self, root: ctk.CTk):
        self.root = root
        self.root.title("ULATINA | Asistente de Biblioteca")
        self.root.resizable(True, True)
        self.root.minsize(860, 620)
        self.root.update_idletasks()
        w, h = 980, 700
        x = (self.root.winfo_screenwidth() // 2) - (w // 2)
        y = (self.root.winfo_screenheight() // 2) - (h // 2)
        self.root.geometry(f"{w}x{h}+{x}+{y}")

        # ──────────────────────────────────────────────────────────────
        # Paleta Deep Carbon — identidad visual completa
        # ──────────────────────────────────────────────────────────────
        self.theme = {
            "bg":           "#0B0E14",   # Fondo principal casi negro
            "sidebar_bg":   "#0E1119",   # Sidebar: capa inferior
            "panel":        "#151921",   # Superficie cards / panels
            "panel_soft":   "#1A2030",   # Nivel de profundidad medio
            "card":         "#1C212E",   # Card base (glassmorphism simulado)
            "input_bg":     "#0D1017",   # Inputs / áreas de escritura
            "text":         "#FFFFFF",   # Texto titular — blanco puro
            "body_text":    "#CBD5E1",   # Texto de cuerpo — gris claro legible
            "muted":        "#94A3B8",   # Placeholders / texto muy secundario
            "accent":       "#9D5CFF",   # Neon Violet — CTA principal
            "accent2":      "#06B6D4",   # Cyan Neón — acento alternativo
            "accent_soft":  "#6D28D9",   # Violeta oscuro — hover / fondos
            "border":       "#1E2433",   # Borde base
            "glass_border": "#312E81",   # Borde glassmorphism (violeta sutil)
            "ok":           "#10B981",   # Verde esmeralda
            "warn":         "#F59E0B",   # Ámbar
            "error":        "#F87171",   # Rojo coral — errores
        }
        # Tipografía geométrica sans-serif.
        # Inter/Montserrat deben estar instaladas; si no, el SO hace fallback.
        self.fonts = {
            "title": "Segoe UI Variable Display",   # Windows 11 nativo; fallback system sans-serif
            "body":  "Segoe UI Variable Display",   # mínimo 16px en toda la UI
            "mono":  "Cascadia Code",               # SQL panel: 14px ámbar
        }

        # MIGRADO: fg_color en lugar de bg para CTk
        self.root.configure(fg_color=self.theme["bg"])

        # Servicios.
        self.db = None
        self.asistente = None
        self.seguridad = None
        self.registro_service = RegistroUsuarioService()
        self.consulta_service = ConsultaService(self.registro_service)
        self.ai_blocked_until = 0.0
        self._ai_lock = threading.Lock()

        # Referencias a widgets (se asignan al construir cada pantalla)
        self.btn_enviar: ctk.CTkButton | None = None
        self.ent_pregunta: ctk.CTkEntry | None = None
        self.txt_chat = None          # scrolledtext.ScrolledText — conservado
        self.lbl_estado: ctk.CTkLabel | None = None
        self.txt_sql = None           # scrolledtext.ScrolledText — conservado
        self.lbl_modelo: ctk.CTkLabel | None = None
        self.lbl_sql_estado: ctk.CTkLabel | None = None
        self.lbl_conexion: ctk.CTkLabel | None = None
        self.botones_rapidos: list[ctk.CTkButton] = []

        # Navegación entre paneles (se inicializa en pantalla_asistente)
        self._paneles: dict[str, ctk.CTkFrame] = {}
        self._nav_botones: dict[str, ctk.CTkFrame] = {}   # frames de nav (compat)
        self._contenido: ctk.CTkFrame | None = None

        # Sidebar lateral colapsable
        self._sidebar: ctk.CTkFrame | None = None
        self._sidebar_expanded: bool = True
        self._sidebar_ancho_actual: int = 260
        self._sidebar_animando: bool = False
        self._active_nav_key: str = "chat"
        # Componentes de cada ítem de navegación (compound icon + text)
        self._sidebar_btns: dict[str, ctk.CTkFrame] = {}       # frames (compat)
        self._nav_frames: dict[str, ctk.CTkFrame] = {}         # contenedor clickeable
        self._nav_icon_labels: dict[str, ctk.CTkLabel] = {}    # label del icono MDL2
        self._nav_text_labels: dict[str, ctk.CTkLabel] = {}    # label del texto (ocultar al colapsar)
        self._lbl_sidebar_title: ctk.CTkLabel | None = None
        self._sidebar_profile_info: ctk.CTkFrame | None = None
        self._btn_logout: ctk.CTkButton | None = None
        self._perfil_frame: ctk.CTkFrame | None = None

        # Panel SQL colapsable
        self._sql_visible: bool = False
        self._sql_panel_frame: tk.Frame | None = None
        self._btn_toggle_sql: ctk.CTkButton | None = None

        # Entradas del formulario de registro
        self.ent_reg_nombre: ctk.CTkEntry | None = None
        self.ent_reg_apellido: ctk.CTkEntry | None = None
        self.ent_reg_correo: ctk.CTkEntry | None = None
        self.ent_reg_telefono: ctk.CTkEntry | None = None
        self.ent_reg_password: ctk.CTkEntry | None = None
        self.ent_reg_confirmar: ctk.CTkEntry | None = None

        # Entradas del formulario de login
        self.ent_correo: ctk.CTkEntry | None = None
        self.ent_pass: ctk.CTkEntry | None = None

        self.historial_conversacion = []
        self._placeholder = "Escribe tu pregunta en lenguaje natural..."

        if not config.GEMINI_KEY:
            self.pantalla_error_config()
        else:
            self.pantalla_login()

    # ------------------------------------------------------------------
    # Pantalla: Login
    # ------------------------------------------------------------------

    def pantalla_login(self):
        """Construye la pantalla de autenticación con CustomTkinter."""
        self.limpiar_pantalla()

        container = ctk.CTkFrame(self.root, fg_color=self.theme["bg"], corner_radius=0)
        container.pack(fill=tk.BOTH, expand=True)

        # Tarjeta central — ocupa casi toda la ventana
        card = ctk.CTkFrame(
            container,
            fg_color=self.theme["panel"],
            border_width=1,
            border_color=self.theme["glass_border"],
            corner_radius=16,
        )
        card.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.94, relheight=0.92)

        # ── Panel izquierdo ────────────────────────────────────────────
        info_panel = ctk.CTkFrame(card, fg_color=self.theme["accent_soft"], corner_radius=0)
        info_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Espaciador superior para centrar verticalmente el contenido
        ctk.CTkFrame(info_panel, fg_color="transparent", height=1, corner_radius=0).pack(
            fill=tk.BOTH, expand=True
        )

        ctk.CTkLabel(
            info_panel,
            text="\uE8A5",               # Segoe MDL2: "Library" glyph
            fg_color="transparent",
            text_color="#EDE9FE",
            font=(_ICON_FONT, 48),
        ).pack(anchor="w", padx=36)

        ctk.CTkLabel(
            info_panel,
            text="Biblioteca Inteligente",
            fg_color="transparent",
            text_color="#EDE9FE",
            font=(self.fonts["title"], 28, "bold"),
        ).pack(anchor="w", padx=36, pady=(14, 0))

        ctk.CTkLabel(
            info_panel,
            text="Consulta libros y gestiona tus préstamos\nde forma sencilla.",
            fg_color="transparent",
            text_color="#DDD6FE",
            font=(self.fonts["body"], 13),
            justify="left",
            wraplength=340,
        ).pack(anchor="w", padx=36, pady=(10, 28))

        bullets = [
            "Busca libros por título o autor",
            "Consulta disponibilidad en tiempo real",
            "Reserva y gestiona tus préstamos",
        ]
        for item in bullets:
            ctk.CTkLabel(
                info_panel,
                text=f"  ✓  {item}",
                fg_color="transparent",
                text_color="#C4B5FD",
                font=(self.fonts["body"], 12),
                anchor="w",
                justify="left",
            ).pack(anchor="w", padx=36, pady=5)

        # Espaciador inferior
        ctk.CTkFrame(info_panel, fg_color="transparent", height=1, corner_radius=0).pack(
            fill=tk.BOTH, expand=True
        )

        # Separador vertical
        ctk.CTkFrame(card, fg_color=self.theme["glass_border"], width=1, corner_radius=0).pack(
            side=tk.LEFT, fill=tk.Y
        )

        # ── Panel derecho: formulario ──────────────────────────────────
        form_outer = ctk.CTkFrame(card, fg_color=self.theme["panel"], corner_radius=0)
        form_outer.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Centrar verticalmente el formulario
        ctk.CTkFrame(form_outer, fg_color="transparent", height=1, corner_radius=0).pack(
            fill=tk.BOTH, expand=True
        )

        form_panel = ctk.CTkFrame(form_outer, fg_color="transparent", corner_radius=0)
        form_panel.pack(fill=tk.X, padx=44)

        ctk.CTkLabel(
            form_panel,
            text="Iniciar sesión",
            fg_color="transparent",
            text_color=self.theme["text"],
            font=(self.fonts["title"], 26, "bold"),
            anchor="w",
        ).pack(fill=tk.X, pady=(0, 4))

        ctk.CTkLabel(
            form_panel,
            text="Ingresa tus credenciales para continuar.",
            fg_color="transparent",
            text_color=self.theme["muted"],
            font=(self.fonts["body"], 12),
            anchor="w",
        ).pack(fill=tk.X, pady=(0, 24))

        ctk.CTkLabel(
            form_panel,
            text="Correo electrónico",
            fg_color="transparent",
            text_color=self.theme["accent"],
            font=(self.fonts["body"], 12, "bold"),
            anchor="w",
        ).pack(fill=tk.X)

        self.ent_correo = ctk.CTkEntry(
            form_panel,
            height=54,
            fg_color=self.theme["input_bg"],
            text_color=self.theme["text"],
            border_color=self.theme["glass_border"],
            placeholder_text="correo@ejemplo.com",
            placeholder_text_color=self.theme["muted"],
            font=(self.fonts["body"], 13),
            corner_radius=10,
        )
        self.ent_correo.pack(fill=tk.X, pady=(6, 16))

        ctk.CTkLabel(
            form_panel,
            text="Contraseña",
            fg_color="transparent",
            text_color=self.theme["accent"],
            font=(self.fonts["body"], 12, "bold"),
            anchor="w",
        ).pack(fill=tk.X)

        self.ent_pass = ctk.CTkEntry(
            form_panel,
            height=54,
            show="*",
            fg_color=self.theme["input_bg"],
            text_color=self.theme["text"],
            border_color=self.theme["glass_border"],
            placeholder_text="••••••••",
            placeholder_text_color=self.theme["muted"],
            font=(self.fonts["body"], 13),
            corner_radius=10,
        )
        self.ent_pass.pack(fill=tk.X, pady=(6, 24))

        # CTA principal — violeta con borde glow
        ctk.CTkButton(
            form_panel,
            text="Entrar al asistente",
            command=self.ejecutar_login,
            fg_color=self.theme["accent"],
            text_color="#FFFFFF",
            hover_color=self.theme["accent_soft"],
            border_width=1,
            border_color="#A78BFA",
            corner_radius=10,
            height=48,
            font=(self.fonts["body"], 13, "bold"),
            cursor="hand2",
        ).pack(fill=tk.X)

        ctk.CTkButton(
            form_panel,
            text="¿No tienes cuenta?  Regístrate",
            command=self.pantalla_registro,
            fg_color="transparent",
            text_color=self.theme["accent2"],
            hover_color=self.theme["panel_soft"],
            corner_radius=10,
            height=42,
            font=(self.fonts["body"], 12),
            cursor="hand2",
        ).pack(fill=tk.X, pady=(10, 0))

        ctk.CTkFrame(form_outer, fg_color="transparent", height=1, corner_radius=0).pack(
            fill=tk.BOTH, expand=True
        )

        self.ent_pass.bind("<Return>", lambda _e: self.ejecutar_login())
        self.ent_correo.focus_set()

    # ------------------------------------------------------------------
    # Pantalla: Error de configuración
    # ------------------------------------------------------------------

    def pantalla_error_config(self):
        """Pantalla que se muestra cuando falta GEMINI_API_KEY en el entorno."""
        self.limpiar_pantalla()

        container = ctk.CTkFrame(self.root, fg_color=self.theme["bg"], corner_radius=0)
        container.pack(fill=tk.BOTH, expand=True, padx=40, pady=40)

        card = ctk.CTkFrame(
            container,
            fg_color=self.theme["panel"],
            border_width=2,
            border_color=self.theme["error"],
            corner_radius=10,
        )
        card.pack(fill=tk.BOTH, expand=True)

        ctk.CTkLabel(
            card,
            text="Error de configuración",
            fg_color="transparent",
            text_color=self.theme["error"],
            font=(self.fonts["title"], 18, "bold"),
        ).pack(anchor="w", padx=36, pady=(36, 4))

        ctk.CTkLabel(
            card,
            text="Falta el archivo .env o la variable GEMINI_API_KEY no está definida.",
            fg_color="transparent",
            text_color=self.theme["text"],
            font=(self.fonts["body"], 12),
            wraplength=700,
            justify="left",
        ).pack(anchor="w", padx=36, pady=(6, 20))

        ctk.CTkLabel(
            card,
            text="Crea un archivo .env en la raíz del proyecto con el siguiente contenido:",
            fg_color="transparent",
            text_color=self.theme["muted"],
            font=(self.fonts["body"], 12),
        ).pack(anchor="w", padx=36, pady=(0, 8))

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
        # MIGRADO: ctk.CTkTextbox en lugar de tk.Text
        txt = ctk.CTkTextbox(
            card,
            fg_color="#000000",
            text_color="#F59E0B",
            font=(self.fonts["mono"], 11),
            height=200,
            corner_radius=10,
            state="normal",
        )
        txt.insert("end", variables)
        txt.configure(state="disabled")
        txt.pack(fill=tk.X, padx=36, pady=(0, 20))

        ctk.CTkButton(
            card,
            text="Reintentar",
            command=self.reintentar_config,
            fg_color=self.theme["accent"],
            text_color="#FFFFFF",
            hover_color=self.theme["accent_soft"],
            border_width=1,
            border_color="#A78BFA",
            corner_radius=10,
            width=140,
            height=40,
            font=(self.fonts["body"], 12, "bold"),
            cursor="hand2",
        ).pack(anchor="w", padx=36, pady=(0, 36))

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

    # ------------------------------------------------------------------
    # Lógica de autenticación (sin cambios)
    # ------------------------------------------------------------------

    def ejecutar_login(self):
        """Valida credenciales y abre el chat principal."""
        correo = self.ent_correo.get().strip()
        password = self.ent_pass.get()  # Sin strip: espacios son parte de la contraseña

        if not correo or not password:
            messagebox.showwarning("Datos requeridos", "Debes ingresar correo y contraseña.")
            return

        self.seguridad = SecurityManager(self.db)
        if self.seguridad.login(correo, password):
            info = self.seguridad.usuario_actual
            self.db = DatabaseManager(uid=info["uid"], pwd=info["pwd"])
            self.seguridad.db = self.db
            try:
                self.asistente = AIAssistant()
            except ValueError as exc:
                messagebox.showerror("Error de configuración", str(exc))
                return
            self.pantalla_asistente()
            return

        messagebox.showerror("Acceso denegado", "Credenciales incorrectas.")

    # ------------------------------------------------------------------
    # Pantalla: Registro de nuevo usuario
    # ------------------------------------------------------------------

    def pantalla_registro(self):
        """
        Pantalla completa para registrar un nuevo usuario.

        MIGRADO: El formulario con scroll usa CTkScrollableFrame en lugar
        del patrón Canvas + Scrollbar manual que existía antes.
        Esto simplifica el código y elimina los métodos de scroll localizado.
        """
        self.limpiar_pantalla()

        container = ctk.CTkFrame(self.root, fg_color=self.theme["bg"], corner_radius=0)
        container.pack(fill=tk.BOTH, expand=True, padx=30, pady=30)

        card = ctk.CTkFrame(
            container,
            fg_color=self.theme["panel"],
            border_width=1,
            border_color=self.theme["glass_border"],
            corner_radius=16,
        )
        card.pack(fill=tk.BOTH, expand=True)

        # ── Panel izquierdo: información ──────────────────────────────
        info_panel = ctk.CTkFrame(card, fg_color=self.theme["accent_soft"], corner_radius=0)
        info_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        ctk.CTkLabel(
            info_panel,
            text="Nuevo Usuario",
            fg_color="transparent",
            text_color="#EDE9FE",
            font=(self.fonts["title"], 22, "bold"),
        ).pack(anchor="w", padx=28, pady=(32, 6))

        ctk.CTkLabel(
            info_panel,
            text="Completa el formulario para registrarte\nen el sistema de biblioteca.",
            fg_color="transparent",
            text_color="#DDD6FE",
            font=(self.fonts["body"], 12),
            justify="left",
            wraplength=340,
        ).pack(anchor="w", padx=28, pady=(0, 20))

        for item in [
            "Rol asignado: usuario",
            "Acceso de solo lectura al catálogo",
            "Gestionado por el administrador",
        ]:
            ctk.CTkLabel(
                info_panel,
                text=f"  ✓  {item}",
                fg_color="transparent",
                text_color="#C4B5FD",
                font=(self.fonts["body"], 12),
                anchor="w",
            ).pack(anchor="w", padx=28, pady=2)

        # ── Panel derecho: formulario con scroll ──────────────────────
        # MIGRADO: CTkScrollableFrame reemplaza el Canvas + Scrollbar manual
        form_outer = ctk.CTkFrame(card, fg_color=self.theme["panel"], corner_radius=0)
        form_outer.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        form_panel = ctk.CTkScrollableFrame(
            form_outer,
            fg_color=self.theme["panel"],
            corner_radius=0,
            scrollbar_button_color=self.theme["border"],
            scrollbar_button_hover_color=self.theme["accent"],
        )
        form_panel.pack(fill=tk.BOTH, expand=True)

        ctk.CTkLabel(
            form_panel,
            text="Crear cuenta",
            fg_color="transparent",
            text_color=self.theme["text"],
            font=(self.fonts["title"], 20, "bold"),
        ).pack(anchor="w", padx=34, pady=(28, 0))

        ctk.CTkLabel(
            form_panel,
            text="Ingresa tus datos para registrarte.",
            fg_color="transparent",
            text_color=self.theme["muted"],
            font=(self.fonts["body"], 12),
        ).pack(anchor="w", padx=34, pady=(6, 14))

        campos_def = [
            ("ent_reg_nombre",    "Nombre",               False),
            ("ent_reg_apellido",  "Apellido",             False),
            ("ent_reg_correo",    "Correo electrónico",   False),
            ("ent_reg_telefono",  "Teléfono",             False),
            ("ent_reg_password",  "Contraseña",           True),
            ("ent_reg_confirmar", "Confirmar contraseña", True),
        ]
        for attr, label, oculto in campos_def:
            ctk.CTkLabel(
                form_panel,
                text=label,
                fg_color="transparent",
                text_color=self.theme["accent"],
                font=(self.fonts["body"], 12, "bold"),
            ).pack(anchor="w", padx=34)
            ent = ctk.CTkEntry(
                form_panel,
                width=310,
                height=38,
                show="*" if oculto else "",
                fg_color=self.theme["input_bg"],
                text_color=self.theme["text"],
                border_color=self.theme["glass_border"],
                font=(self.fonts["body"], 12),
                corner_radius=10,
            )
            ent.pack(anchor="w", padx=34, pady=(4, 10))
            setattr(self, attr, ent)

        self.ent_reg_confirmar.bind("<Return>", lambda _e: self.ejecutar_registro())

        ctk.CTkButton(
            form_panel,
            text="Crear cuenta",
            command=self.ejecutar_registro,
            fg_color=self.theme["accent"],
            text_color="#FFFFFF",
            hover_color=self.theme["accent_soft"],
            border_width=1,
            border_color="#A78BFA",
            corner_radius=10,
            width=180,
            height=42,
            font=(self.fonts["body"], 12, "bold"),
            cursor="hand2",
        ).pack(anchor="w", padx=34, pady=(10, 4))

        ctk.CTkButton(
            form_panel,
            text="← Volver al login",
            command=self.pantalla_login,
            fg_color=self.theme["panel_soft"],
            text_color=self.theme["muted"],
            hover_color=self.theme["panel"],
            border_width=1,
            border_color=self.theme["border"],
            corner_radius=10,
            width=180,
            height=34,
            font=(self.fonts["body"], 12),
            cursor="hand2",
        ).pack(anchor="w", padx=34, pady=(0, 28))

        self.ent_reg_nombre.focus_set()

    # ------------------------------------------------------------------
    # Lógica de registro (sin cambios)
    # ------------------------------------------------------------------

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
                messagebox.showerror(
                    "Error",
                    "No se pudo registrar el usuario. Es posible que el correo ya esté en uso.",
                )
            else:
                messagebox.showinfo(
                    "Registro exitoso",
                    f"Usuario {payload.nombre} registrado correctamente. Ya puedes iniciar sesión.",
                )
                self.pantalla_login()
        except Exception as e:
            messagebox.showerror("Error inesperado", str(e))

    def _leer_datos_registro_formulario(self) -> RegistroUsuarioData:
        return RegistroUsuarioData(
            nombre=self.ent_reg_nombre.get().strip() if self.ent_reg_nombre else "",
            apellido=self.ent_reg_apellido.get().strip() if self.ent_reg_apellido else "",
            correo=self.ent_reg_correo.get().strip() if self.ent_reg_correo else "",
            telefono=self.ent_reg_telefono.get().strip() if self.ent_reg_telefono else "",
            password=self.ent_reg_password.get() if self.ent_reg_password else "",
            rol="usuario",
        )

    # ------------------------------------------------------------------
    # Pantalla: Asistente principal
    # ------------------------------------------------------------------

    def pantalla_asistente(self):
        """
        Ventana principal con sidebar lateral colapsable y paneles intercambiables.

        Construye:
        1. Sidebar izquierdo (220px expandido / 64px colapsado) con navegación,
           perfil del usuario y botón de cierre de sesión.
        2. Contenedor de paneles donde cada sección muestra su Frame.
        3. El panel Chat se construye aquí; los demás se crean de forma lazy.
        """
        self.limpiar_pantalla()
        self._paneles = {}
        self._nav_botones = {}
        self._sidebar_btns = {}
        self._sidebar_expanded = True
        self._sidebar_ancho_actual = 220
        self._sidebar_animando = False
        self._sql_visible = False

        usuario = self.seguridad.usuario_actual or {}  # type: ignore[union-attr]
        rol = str(usuario.get("rol") or "usuario")

        # Contenedor raíz: sidebar izquierdo + área de contenido derecha
        main_area = tk.Frame(self.root, bg=self.theme["bg"])
        main_area.pack(fill=tk.BOTH, expand=True)

        # Sidebar
        self._sidebar = ctk.CTkFrame(
            main_area,
            fg_color=self.theme["sidebar_bg"],
            width=260,
            corner_radius=0,
        )
        self._sidebar.pack(side=tk.LEFT, fill=tk.Y)
        self._sidebar.pack_propagate(False)
        self._construir_sidebar(self._sidebar, rol)

        # Separador vertical de 1px
        tk.Frame(main_area, bg=self.theme["border"], width=1).pack(side=tk.LEFT, fill=tk.Y)

        # Área de contenido
        self._contenido = ctk.CTkFrame(main_area, fg_color=self.theme["bg"], corner_radius=0)
        self._contenido.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Panel de chat
        self._construir_panel_chat(self._contenido, rol)

        # Mostrar chat por defecto
        self._mostrar_panel_activo("chat")
        self._mostrar_bienvenida()
        if self.ent_pregunta:
            self.ent_pregunta.focus_set()

    # ------------------------------------------------------------------
    # Sidebar: construcción
    # ------------------------------------------------------------------

    def _construir_sidebar(self, sidebar: ctk.CTkFrame, rol: str) -> None:
        """
        Construye el sidebar con botón de toggle, ítems de navegación y perfil.

        El perfil se empaqueta con side=BOTTOM antes que los nav items para que
        quede anclado al pie independientemente de la altura del sidebar.
        """
        # ── Perfil en la parte inferior (BOTTOM antes que el contenido TOP) ──
        self._perfil_frame = ctk.CTkFrame(sidebar, fg_color="transparent", corner_radius=0)
        self._perfil_frame.pack(side=tk.BOTTOM, fill=tk.X)
        self._construir_sidebar_perfil(self._perfil_frame)

        # ── Toggle + logo ──────────────────────────────────────────────
        toggle_row = ctk.CTkFrame(sidebar, fg_color="transparent", corner_radius=0)
        toggle_row.pack(fill=tk.X, padx=24, pady=(32, 8))

        ctk.CTkButton(
            toggle_row,
            text=_ICONS["menu"],
            command=self._toggle_sidebar,
            fg_color="transparent",
            text_color=self.theme["muted"],
            hover_color=self.theme["panel"],
            width=36, height=36,
            corner_radius=8,
            font=(_ICON_FONT, 16),
            cursor="hand2",
        ).pack(side=tk.LEFT)

        self._lbl_sidebar_title = ctk.CTkLabel(
            toggle_row,
            text="Biblioteca",
            fg_color="transparent",
            text_color=self.theme["accent"],
            font=(self.fonts["title"], 14, "bold"),
        )
        self._lbl_sidebar_title.pack(side=tk.LEFT, padx=(10, 0))

        # Separador
        ctk.CTkFrame(
            sidebar, fg_color=self.theme["border"], height=1, corner_radius=0
        ).pack(fill=tk.X, padx=24, pady=(4, 16))

        # ── Ítems de navegación (compound: icono MDL2 + texto) ───────────
        # Cada ítem es un CTkFrame clickeable con dos CTkLabel independientes,
        # permitiendo iconos con Segoe MDL2 Assets y texto con la fuente del cuerpo.
        nav_items = [
            ("chat",      _ICONS["chat"],      "Chat"),
            ("dashboard", _ICONS["dashboard"], "Dashboard"),
            ("busqueda",  _ICONS["busqueda"],  "Búsqueda"),
            ("ayuda",     _ICONS["ayuda"],     "Ayuda"),
        ]
        if rol == "admin":
            nav_items.append(("admin", _ICONS["admin"], "Admin"))

        for key, icon_ch, label in nav_items:
            nav_frame = ctk.CTkFrame(
                sidebar,
                fg_color="transparent",
                corner_radius=12,
                height=48,
                cursor="hand2",
            )
            nav_frame.pack(fill=tk.X, padx=16, pady=(0, 4))
            nav_frame.pack_propagate(False)

            icon_lbl = ctk.CTkLabel(
                nav_frame,
                text=icon_ch,
                font=(_ICON_FONT, 16),
                text_color=self.theme["muted"],
                fg_color="transparent",
                width=36,
            )
            icon_lbl.pack(side=tk.LEFT, padx=(10, 0))

            text_lbl = ctk.CTkLabel(
                nav_frame,
                text=label,
                font=(self.fonts["body"], 14),
                text_color=self.theme["body_text"],
                fg_color="transparent",
                anchor="w",
            )
            text_lbl.pack(side=tk.LEFT, padx=(6, 0), fill=tk.X, expand=True)

            cmd = lambda k=key: self._mostrar_panel_activo(k)
            for w in (nav_frame, icon_lbl, text_lbl):
                w.bind("<Button-1>", lambda _, c=cmd: c())
                w.bind("<Enter>",    lambda _, f=nav_frame: f.configure(fg_color=self.theme["panel"]))
                w.bind("<Leave>",    lambda _, f=nav_frame, k=key: f.configure(
                    fg_color=self.theme["panel_soft"] if k == self._active_nav_key else "transparent"
                ))

            self._nav_frames[key]       = nav_frame
            self._nav_icon_labels[key]  = icon_lbl
            self._nav_text_labels[key]  = text_lbl
            self._sidebar_btns[key]     = nav_frame   # compat
            self._nav_botones[key]      = nav_frame   # compat

    def _construir_sidebar_perfil(self, frame: ctk.CTkFrame) -> None:
        """
        Construye el pie del sidebar: avatar circular con iniciales, nombre,
        rol y botón de logout alineado a la derecha.

        Aplica unwrapping defensivo sobre los valores de usuario_actual para
        tolerar tanto escalares (str) como tuplas pyodbc de un elemento.
        """
        usuario = (self.seguridad.usuario_actual or {}) if self.seguridad else {}  # type: ignore[union-attr]

        def _unwrap(v, default: str = "") -> str:
            """Extrae el escalar de una tupla/lista o devuelve la cadena directamente."""
            if isinstance(v, (tuple, list)):
                return str(v[0]).strip() if v else default
            return str(v).strip() if v is not None else default

        nombre   = _unwrap(usuario.get("nombre"),  "Usuario")
        apellido = _unwrap(usuario.get("apellido"), "")
        rol      = _unwrap(usuario.get("rol"),      "usuario")

        iniciales = (nombre[0] + (apellido[0] if apellido else "")).upper() if nombre else "?"

        _rol_display = {
            "admin":     "Administrador",
            "operativo": "Operativo",
            "usuario":   "Usuario",
        }
        rol_texto = _rol_display.get(rol, rol.capitalize())

        # ── Separador ──────────────────────────────────────────────────
        ctk.CTkFrame(frame, fg_color=self.theme["border"], height=1, corner_radius=0).pack(
            fill=tk.X, padx=24, pady=(0, 0)
        )

        # ── Fila: avatar | nombre+rol | logout ─────────────────────────
        inner = ctk.CTkFrame(frame, fg_color="transparent", corner_radius=0)
        inner.pack(fill=tk.X, padx=24, pady=(16, 24))

        # Avatar circular 42×42 — color acento, iniciales en blanco
        ctk.CTkLabel(
            inner,
            text=iniciales,
            fg_color=self.theme["accent"],      # #9D5CFF Neon Violet
            text_color="#FFFFFF",
            font=(self.fonts["title"], 15, "bold"),
            width=42, height=42,
            corner_radius=21,
        ).pack(side=tk.LEFT)

        # Nombre + rol — se ocultan al colapsar el sidebar
        self._sidebar_profile_info = ctk.CTkFrame(inner, fg_color="transparent", corner_radius=0)
        self._sidebar_profile_info.pack(side=tk.LEFT, padx=(10, 0), fill=tk.X, expand=True)

        ctk.CTkLabel(
            self._sidebar_profile_info,
            text=nombre,
            fg_color="transparent",
            text_color="#FFFFFF",
            font=(self.fonts["body"], 16, "bold"),
            anchor="w",
        ).pack(anchor="w")

        ctk.CTkLabel(
            self._sidebar_profile_info,
            text=rol_texto,
            fg_color="transparent",
            text_color=self.theme["muted"],     # #94A3B8 gris azulado
            font=(self.fonts["body"], 13),
            anchor="w",
        ).pack(anchor="w", pady=(1, 0))

        # Botón logout — icono sutil a la derecha; se torna rojo al hover
        self._btn_logout = ctk.CTkButton(
            inner,
            text=_ICONS["logout"],
            command=self._cerrar_sesion,
            fg_color="transparent",
            text_color=self.theme["muted"],
            hover_color="#2D1212",
            width=32, height=32,
            corner_radius=8,
            font=(_ICON_FONT, 16),
            cursor="hand2",
        )
        self._btn_logout.pack(side=tk.RIGHT)
        # Cambio de color del icono al pasar el cursor
        self._btn_logout.bind(
            "<Enter>",
            lambda _: self._btn_logout.configure(text_color=self.theme["error"]) if self._btn_logout else None,
        )
        self._btn_logout.bind(
            "<Leave>",
            lambda _: self._btn_logout.configure(text_color=self.theme["muted"]) if self._btn_logout else None,
        )

    # ------------------------------------------------------------------
    # Sidebar: animación y toggle
    # ------------------------------------------------------------------

    def _toggle_sidebar(self) -> None:
        """Inicia la animación para colapsar o expandir el sidebar."""
        if self._sidebar_animando:
            return
        self._sidebar_animando = True
        if self._sidebar_expanded:
            self._sidebar_expanded = False
            # Ocultar etiquetas de texto de los nav items — solo queda el icono
            for lbl in self._nav_text_labels.values():
                lbl.pack_forget()
            if self._lbl_sidebar_title:
                self._lbl_sidebar_title.configure(text="")
            if self._sidebar_profile_info:
                self._sidebar_profile_info.pack_forget()
            if self._btn_logout:
                self._btn_logout.pack_forget()
            self._animar_sidebar(64)
        else:
            self._animar_sidebar(260, on_complete=self._on_sidebar_expandido)

    def _animar_sidebar(self, target: int, on_complete=None) -> None:
        """Anima el sidebar hacia el ancho objetivo con pasos de 12px cada 8ms."""
        if self._sidebar is None:
            return
        step = 12 if target > self._sidebar_ancho_actual else -12
        self._sidebar_ancho_actual += step
        if (step > 0 and self._sidebar_ancho_actual >= target) or \
           (step < 0 and self._sidebar_ancho_actual <= target):
            self._sidebar_ancho_actual = target
            self._sidebar.configure(width=target)
            self._sidebar_animando = False
            if on_complete:
                on_complete()
        else:
            self._sidebar.configure(width=self._sidebar_ancho_actual)
            self.root.after(8, lambda: self._animar_sidebar(target, on_complete))

    def _on_sidebar_expandido(self) -> None:
        """Restaura etiquetas de texto y perfil tras la animación de expansión."""
        self._sidebar_expanded = True
        # Restaurar etiquetas de texto en cada nav item
        for lbl in self._nav_text_labels.values():
            lbl.pack(side=tk.LEFT, padx=(6, 0), fill=tk.X, expand=True)
        if self._lbl_sidebar_title:
            self._lbl_sidebar_title.configure(text="Biblioteca")
        if self._sidebar_profile_info:
            self._sidebar_profile_info.pack(side=tk.LEFT, padx=(10, 0), fill=tk.X, expand=True)
        if self._btn_logout:
            self._btn_logout.pack(side=tk.RIGHT)
        # Re-aplicar estado activo para restaurar colores de iconos
        self._actualizar_sidebar_activo(self._active_nav_key)

    def _actualizar_sidebar_activo(self, nombre: str) -> None:
        """Resalta el ítem de nav activo: fondo panel_soft + icono en acento."""
        self._active_nav_key = nombre
        for key in self._nav_frames:
            frame    = self._nav_frames[key]
            icon_lbl = self._nav_icon_labels.get(key)
            text_lbl = self._nav_text_labels.get(key)
            if key == nombre:
                frame.configure(fg_color=self.theme["panel_soft"])
                if icon_lbl:
                    icon_lbl.configure(text_color=self.theme["accent"])
                if text_lbl:
                    text_lbl.configure(text_color="#FFFFFF")
            else:
                frame.configure(fg_color="transparent")
                if icon_lbl:
                    icon_lbl.configure(text_color=self.theme["muted"])
                if text_lbl:
                    text_lbl.configure(text_color=self.theme["body_text"])

    def _cerrar_sesion(self) -> None:
        """Cierra la sesión del usuario actual y regresa a la pantalla de login."""
        if messagebox.askyesno("Cerrar sesión", "¿Estás seguro de que deseas cerrar sesión?"):
            self.db = None
            self.seguridad = None
            self.asistente = None
            self.historial_conversacion = []
            self._paneles = {}
            self._nav_botones = {}
            self._sidebar_btns = {}
            self.pantalla_login()

    # ------------------------------------------------------------------
    # Navegación entre paneles
    # ------------------------------------------------------------------

    def _mostrar_panel_activo(self, nombre: str) -> None:
        """
        Oculta todos los paneles y muestra el solicitado.

        Si el panel no fue construido aún, lo instancia de forma lazy antes
        de mostrarlo. Actualiza el estilo de los botones del sidebar.
        """
        for panel in self._paneles.values():
            panel.pack_forget()

        if nombre not in self._paneles and self._contenido:
            if nombre == "dashboard":
                p = DashboardPanel(
                    self._contenido, self.theme, self.fonts, self.db, self.seguridad,
                    on_ver_detalle=self._usar_consulta_rapida_desde_ayuda)
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

        if nombre in self._paneles:
            panel = self._paneles[nombre]
            panel.pack(fill=tk.BOTH, expand=True)
            self._fade_in_panel(panel)

        self._actualizar_sidebar_activo(nombre)

    def _fade_in_panel(self, panel) -> None:
        """300ms canvas stipple dissolve: overlay opaco → transparente → destruir."""
        panel.update_idletasks()
        overlay = tk.Canvas(
            panel,
            bg=self.theme["bg"],
            highlightthickness=0,
        )
        overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        stipples = ["gray75", "gray50", "gray25", "gray12"]

        def _step(idx: int) -> None:
            if not overlay.winfo_exists():
                return
            if idx >= len(stipples):
                overlay.destroy()
                return
            w = overlay.winfo_width() or 900
            h = overlay.winfo_height() or 700
            overlay.delete("all")
            overlay.create_rectangle(
                0, 0, w, h,
                fill=self.theme["bg"],
                stipple=stipples[idx],
                outline="",
            )
            self.root.after(75, lambda: _step(idx + 1))

        _step(0)

    def _usar_consulta_rapida_desde_ayuda(self, consulta: str) -> None:
        """
        Recibe un ejemplo de la pantalla de Ayuda o Dashboard, lo coloca en el
        input del chat y activa la sección de chat automáticamente.
        """
        self._mostrar_panel_activo("chat")
        self._usar_consulta_rapida(consulta)

    # ------------------------------------------------------------------
    # Panel de chat
    # ------------------------------------------------------------------

    def _construir_panel_chat(self, parent: ctk.CTkFrame, rol: str) -> None:
        """
        Construye el panel de chat con cabecera, área de chat y panel SQL colapsable.

        CONSERVADO: scrolledtext.ScrolledText — necesario para los tags de color del chat.
        El panel SQL inicia oculto y se muestra con el botón ⚡ SQL de la cabecera.
        """
        panel = ctk.CTkFrame(parent, fg_color=self.theme["bg"], corner_radius=0)
        self._paneles["chat"] = panel

        # ── Cabecera del chat ──────────────────────────────────────────
        chat_header = ctk.CTkFrame(panel, fg_color=self.theme["panel"], height=60, corner_radius=0)
        chat_header.pack(fill=tk.X)
        chat_header.pack_propagate(False)

        ctk.CTkLabel(
            chat_header,
            text="Chat",
            fg_color="transparent",
            text_color=self.theme["text"],
            font=(self.fonts["title"], 20, "bold"),   # ~27px ExtraBold
        ).pack(side=tk.LEFT, padx=24)

        self._btn_toggle_sql = None  # SQL panel oculto permanentemente

        self.lbl_estado = ctk.CTkLabel(
            chat_header,
            text="Listo para ayudarte",
            fg_color="transparent",
            text_color=self.theme["ok"],
            font=(self.fonts["body"], 12),
        )
        self.lbl_estado.pack(side=tk.RIGHT, padx=(0, 12))

        # ── Contenedor split ───────────────────────────────────────────
        split = tk.Frame(panel, bg=self.theme["bg"])
        split.pack(fill=tk.BOTH, expand=True, padx=24, pady=16)

        # ── Panel SQL: terminal negra ──────────────────────────────────
        # CONSERVADO: tk.Frame — contenedor para scrolledtext con bg propio
        self._sql_panel_frame = tk.Frame(
            split,
            bg="#000000",
            padx=20, pady=20,
            width=400,
        )
        self._sql_panel_frame.pack_propagate(False)
        # Inicia oculto — se muestra con _toggle_sql_panel()

        # ── Panel izquierdo: área de chat ──────────────────────────────
        left = tk.Frame(split, bg=self.theme["bg"])
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # CONSERVADO: scrolledtext.ScrolledText — soporte de tags de color para burbujas
        self.txt_chat = scrolledtext.ScrolledText(
            left,
            wrap=tk.WORD,
            bg=self.theme["panel_soft"],
            fg=self.theme["body_text"],
            insertbackground=self.theme["body_text"],
            relief=tk.FLAT,
            bd=0,
            padx=20,
            pady=20,
            font=(self.fonts["body"], 12),
        )
        self.txt_chat.pack(fill=tk.BOTH, expand=True)
        self.txt_chat.config(state="disabled")
        self._configurar_tags_chat()

        # Botones de consulta rápida (MIGRADO: CTkButton)
        tools = tk.Frame(left, bg=self.theme["bg"], pady=8)
        tools.pack(fill=tk.X)

        if rol == "admin":
            consulta_rapida = [
                "¿Cuántos libros hay registrados?",
                "Préstamos activos",
                "Registrar nuevo libro",
                "Préstamos vencidos",
            ]
        elif rol == "operativo":
            consulta_rapida = [
                "¿Cuántos libros hay registrados?",
                "Préstamos activos",
                "Préstamos vencidos",
                "Lista de autores",
            ]
        else:
            consulta_rapida = [
                "¿Cuántos libros hay registrados?",
                "Libros de tecnología",
                "Lista de autores",
                "Libros disponibles",
            ]

        self.botones_rapidos = []
        for texto in consulta_rapida:
            boton = ctk.CTkButton(
                tools,
                text=texto,
                command=lambda q=texto: self._usar_consulta_rapida(q),
                fg_color=self.theme["panel_soft"],
                text_color=self.theme["accent2"],
                hover_color=self.theme["panel"],
                border_width=1,
                border_color=self.theme["glass_border"],
                corner_radius=8,
                height=34,
                font=(self.fonts["body"], 12),
                cursor="hand2",
            )
            boton.pack(side=tk.LEFT, padx=(0, 8))
            self.botones_rapidos.append(boton)

        # Composer: entrada de texto y botón enviar
        composer = tk.Frame(left, bg=self.theme["bg"])
        composer.pack(fill=tk.X, pady=(4, 8))

        self.ent_pregunta = ctk.CTkEntry(
            composer,
            fg_color=self.theme["input_bg"],
            text_color=self.theme["body_text"],
            border_color=self.theme["glass_border"],
            border_width=1,
            font=(self.fonts["body"], 12),
            height=54,
            corner_radius=14,
        )
        self.ent_pregunta.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.ent_pregunta.bind("<Return>", lambda _e: self.procesar_consulta())
        self.ent_pregunta.bind("<FocusIn>", self._on_entry_focus_in)
        self.ent_pregunta.bind("<FocusOut>", self._on_entry_focus_out)
        self._activar_placeholder_pregunta()

        # Botón Enviar — acento violeta con borde glow (simula degradado)
        self.btn_enviar = ctk.CTkButton(
            composer,
            text="Enviar  ➤",
            command=self.procesar_consulta,
            fg_color=self.theme["accent"],
            text_color="#FFFFFF",
            hover_color=self.theme["accent_soft"],
            border_width=1,
            border_color="#A78BFA",
            corner_radius=12,
            width=120,
            height=54,
            font=(self.fonts["body"], 12, "bold"),
            cursor="hand2",
        )
        self.btn_enviar.pack(side=tk.LEFT, padx=(8, 0))

        # ── Contenido del panel SQL ────────────────────────────────────
        self._construir_contenido_sql(self._sql_panel_frame)

    def _construir_contenido_sql(self, right: tk.Frame) -> None:
        """Construye los widgets del panel SQL con estética de terminal real."""
        # Cabecera terminal
        ctk.CTkLabel(
            right,
            text="Inspector SQL",
            fg_color="transparent",
            text_color="#FFC107",
            font=(self.fonts["mono"], 14, "bold"),
            anchor="w",
        ).pack(fill=tk.X)

        self.lbl_conexion = ctk.CTkLabel(
            right,
            text="●  biblioteca",
            fg_color="transparent",
            text_color="#10B981",
            font=(self.fonts["mono"], 11),
            anchor="w",
        )
        self.lbl_conexion.pack(fill=tk.X, pady=(0, 8))

        tk.Frame(right, bg="#1A1200", height=1).pack(fill=tk.X, pady=(0, 6))

        # Terminal SQL — fondo negro puro, texto ámbar (estilo terminal real)
        self.txt_sql = scrolledtext.ScrolledText(
            right,
            wrap=tk.WORD,
            bg="#000000",
            fg="#FFC107",
            insertbackground="#FFC107",
            selectbackground="#312E81",
            selectforeground="#FFC107",
            font=(self.fonts["mono"], 11),   # 11pt ≈ 14px on 96dpi
            relief=tk.FLAT,
            bd=0,
            state="disabled",
        )
        self.txt_sql.pack(fill=tk.BOTH, expand=True, pady=(6, 8))
        self.txt_sql.config(state="normal")
        self.txt_sql.insert(
            tk.END,
            "-- Terminal SQL\n"
            "-- El SQL generado por la IA aparecerá aquí.\n"
            "-- Cada consulta reemplaza este contenido.",
        )
        self.txt_sql.config(state="disabled")

        tk.Frame(right, bg="#1A1200", height=1).pack(fill=tk.X, pady=(0, 6))

        self.lbl_modelo = ctk.CTkLabel(
            right,
            text="modelo: —",
            fg_color="transparent",
            text_color="#78716C",
            font=(self.fonts["mono"], 11),
            anchor="w",
        )
        self.lbl_modelo.pack(fill=tk.X)

        self.lbl_sql_estado = ctk.CTkLabel(
            right,
            text="",
            fg_color="transparent",
            text_color="#78716C",
            font=(self.fonts["mono"], 11),
            anchor="w",
        )
        self.lbl_sql_estado.pack(fill=tk.X)

    # ------------------------------------------------------------------
    # Toggle del panel SQL
    # ------------------------------------------------------------------

    def _toggle_sql_panel(self) -> None:
        """Muestra u oculta el panel SQL lateral del chat."""
        if self._sql_panel_frame is None:
            return
        if self._sql_visible:
            self._sql_panel_frame.pack_forget()
            self._sql_visible = False
            if self._btn_toggle_sql:
                self._btn_toggle_sql.configure(text="Inspeccionar  ▶")
        else:
            self._sql_panel_frame.pack(side=tk.RIGHT, fill=tk.Y)
            self._sql_visible = True
            if self._btn_toggle_sql:
                self._btn_toggle_sql.configure(text="Inspeccionar  ◀")

    # ------------------------------------------------------------------
    # Métodos del panel SQL (actualización a configure() para CTkLabel)
    # ------------------------------------------------------------------

    def mostrar_sql(self, sql: str, modelo: str, estado: str = "") -> None:
        """Actualiza el panel lateral con el SQL generado y el estado de la ejecución."""
        if self.txt_sql is None:
            return
        self.txt_sql.config(state="normal")
        self.txt_sql.delete("1.0", tk.END)
        self.txt_sql.insert(tk.END, sql)
        self.txt_sql.config(state="disabled")
        if self.lbl_modelo:
            self.lbl_modelo.configure(text=f"Modelo: {modelo}")
        if self.lbl_sql_estado:
            self.lbl_sql_estado.configure(text=estado)

    # ------------------------------------------------------------------
    # Configuración de tags del chat (sin cambios — scrolledtext)
    # ------------------------------------------------------------------

    def _configurar_tags_chat(self) -> None:
        if not self.txt_chat:
            return
        # Cabeceras con colores Deep Carbon
        self.txt_chat.tag_configure(
            "assistant_head",
            foreground=self.theme["accent"],       # Violeta
            font=(self.fonts["title"], 12, "bold"),
            spacing1=6,
        )
        self.txt_chat.tag_configure(
            "user_head",
            foreground=self.theme["accent2"],      # Cyan neón
            font=(self.fonts["title"], 12, "bold"),
            spacing1=6,
        )
        # Burbujas: usuario = violeta profundo, asistente = card oscura
        self.txt_chat.tag_configure(
            "burbuja_user",
            background="#9D5CFF",                  # Neon Violet — burbuja usuario
            foreground="#FFFFFF",
            lmargin1=160,                          # ~70% max-width (right-aligned)
            lmargin2=160,
            rmargin=20,
            spacing1=16,
            spacing3=16,
        )
        self.txt_chat.tag_configure(
            "burbuja_asistente",
            background="#1E293B",                  # AI bubble — slate oscuro
            foreground=self.theme["body_text"],
            lmargin1=20,                           # 20px padding left
            lmargin2=20,
            rmargin=160,                           # ~70% max-width (left-aligned)
            spacing1=16,
            spacing3=16,
        )
        self.txt_chat.tag_configure(
            "separador_msg",
            spacing1=6,
            spacing3=6,
        )

    # ------------------------------------------------------------------
    # Mensaje de bienvenida
    # ------------------------------------------------------------------

    def _mostrar_bienvenida(self) -> None:
        usuario = self.seguridad.usuario_actual or {}
        nombre = str(usuario.get("nombre") or "usuario")
        mensaje = (
            f"¡Hola, {nombre}! Soy tu asistente de biblioteca. "
            f"Puedes preguntarme sobre libros, préstamos o disponibilidad en lenguaje natural."
        )
        self.mostrar_en_chat(mensaje, autor="Asistente")

    # ------------------------------------------------------------------
    # Helpers de la UI del chat
    # ------------------------------------------------------------------

    def _usar_consulta_rapida(self, consulta: str) -> None:
        if not self.ent_pregunta:
            return
        self._desactivar_placeholder_pregunta()
        self.ent_pregunta.delete(0, tk.END)
        self.ent_pregunta.insert(0, consulta)
        self.procesar_consulta()

    def _set_estado(self, texto: str, color: str) -> None:
        """Actualiza el label de estado — usa configure() para CTkLabel."""
        if self.lbl_estado:
            self.lbl_estado.configure(text=texto, text_color=color)

    def _toggle_input(self, enabled: bool) -> None:
        """
        Habilita o deshabilita los controles de entrada del chat.

        MIGRADO: CTkEntry y CTkButton usan configure(state=) en lugar de config(state=).
        Los valores válidos son "normal" y "disabled" (mismos que Tkinter).
        """
        estado = "normal" if enabled else "disabled"
        if self.ent_pregunta:
            self.ent_pregunta.configure(state=estado)
        if self.btn_enviar:
            self.btn_enviar.configure(state=estado)
        for boton in self.botones_rapidos:
            boton.configure(state=estado)

    def _activar_placeholder_pregunta(self) -> None:
        if not self.ent_pregunta:
            return
        self.ent_pregunta.delete(0, tk.END)
        self.ent_pregunta.insert(0, self._placeholder)
        self.ent_pregunta.configure(text_color=self.theme["muted"])

    def _desactivar_placeholder_pregunta(self) -> None:
        if not self.ent_pregunta:
            return
        if self.ent_pregunta.get() == self._placeholder:
            self.ent_pregunta.delete(0, tk.END)
        self.ent_pregunta.configure(text_color=self.theme["text"])

    def _on_entry_focus_in(self, _event) -> None:
        self._desactivar_placeholder_pregunta()
        if self.ent_pregunta:
            self.ent_pregunta.configure(
                border_color=self.theme["accent"],
                border_width=2,
            )

    def _on_entry_focus_out(self, _event) -> None:
        if self.ent_pregunta:
            self.ent_pregunta.configure(
                border_color=self.theme["glass_border"],
                border_width=1,
            )
            if not self.ent_pregunta.get().strip():
                self._activar_placeholder_pregunta()

    def _validar_entrada_usuario(self) -> str | None:
        pregunta = self.ent_pregunta.get().strip() if self.ent_pregunta else ""
        if not pregunta or pregunta == self._placeholder:
            return None
        return pregunta

    # ------------------------------------------------------------------
    # Pipeline de consulta (sin cambios de lógica)
    # ------------------------------------------------------------------

    def procesar_consulta(self) -> None:
        pregunta = self._validar_entrada_usuario()
        if pregunta is None:
            return

        self.mostrar_en_chat(pregunta, autor="Tú")
        self.ent_pregunta.delete(0, tk.END)
        self._toggle_input(False)
        self._set_estado("Consultando...", self.theme["warn"])

        threading.Thread(
            target=self._procesar_consulta_async,
            args=(pregunta,),
            daemon=True,
        ).start()

    def _agregar_historial(self, rol: str, texto: str) -> None:
        self.historial_conversacion.append({"rol": rol, "texto": texto})
        if len(self.historial_conversacion) > 10:
            self.historial_conversacion = self.historial_conversacion[-10:]

    def _crear_chat_controller(self) -> ChatController:
        return ChatController(
            asistente=self.asistente,
            db=self.db,
            seguridad=self.seguridad,
            consulta_service=self.consulta_service,
        )

    def _aplicar_historial_resultado(self, resultado: ResultadoConsulta) -> None:
        for entrada in resultado.historial:
            self._agregar_historial(entrada.rol, entrada.texto)

    def _aplicar_resultado_consulta(self, resultado: ResultadoConsulta) -> None:
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

        Los detalles técnicos del error se registran en el logger; el usuario
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
            logger.error("Error inesperado en procesar_consulta_async: %s", exc)
            resultado = ResultadoConsulta(
                mensajes=(MensajeChat(MENSAJES["error_inesperado"], "Asistente"),),
            )

        self._registrar_auditoria(pregunta, resultado)
        self.root.after(0, self._aplicar_resultado_consulta, resultado)

    def _registrar_auditoria(self, pregunta: str, resultado: ResultadoConsulta) -> None:
        """
        Inserta un registro en auditoria.consultas de forma asíncrona.

        Si la tabla no existe (database_patch.sql no ejecutado), el error
        se captura silenciosamente sin afectar la experiencia del usuario.
        """
        usuario = (self.seguridad.usuario_actual or {}) if self.seguridad else {}
        id_usuario = usuario.get("id")
        nombre = f"{usuario.get('nombre', '')} {usuario.get('apellido', '')}".strip()

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
                pass

        threading.Thread(target=_insert, daemon=True).start()

    def _finalizar_consulta(self) -> None:
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

    def mostrar_en_chat(self, mensaje: str, autor: str = "Asistente") -> None:
        """
        Agrega un bloque de mensaje al área de chat con formato según el autor.

        Args:
            mensaje: Texto a mostrar.
            autor:   Identificador del emisor ('Tú', 'Asistente').
        """
        if not self.txt_chat:
            return

        texto = str(mensaje or "").strip()
        if not texto:
            return

        autor_key = str(autor or "Asistente").strip()

        # Mensajes del sistema se silencian — el chat es solo Usuario ↔ IA.
        if autor_key.lower().startswith("sistema"):
            return

        hora = time.strftime("%H:%M")

        if autor_key.lower().startswith("tú") or autor_key.lower().startswith("tu"):
            tag_head = "user_head"
            tag_body = "burbuja_user"
        else:
            tag_head = "assistant_head"
            tag_body = "burbuja_asistente"

        self.txt_chat.config(state="normal")
        self.txt_chat.insert(tk.END, f" {autor_key}  {hora}\n", tag_head)
        self.txt_chat.insert(tk.END, f" {texto} \n", tag_body)
        self.txt_chat.insert(tk.END, "\n", "separador_msg")
        self.txt_chat.config(state="disabled")
        self.txt_chat.see(tk.END)

    def limpiar_pantalla(self) -> None:
        """Destruye todos los widgets actuales para renderizar una nueva pantalla."""
        self.historial_conversacion = []
        for widget in self.root.winfo_children():
            widget.destroy()


if __name__ == "__main__":
    # MIGRADO: ctk.CTk() en lugar de tk.Tk()
    ventana = ctk.CTk()
    app = BibliotecaApp(ventana)
    ventana.mainloop()
