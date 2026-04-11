# -*- coding: utf-8 -*-
"""
Módulo: features.py
Descripción: Paneles de funcionalidades adicionales para la Biblioteca Inteligente.

Contiene cuatro paneles independientes que se integran con la navegación de
pestañas de main.py. La interfaz fue migrada a CustomTkinter para un aspecto
moderno y consistente con el tema oscuro teal.

Paneles:
    DashboardPanel  — Métricas visuales del sistema (tarjetas + tabla top libros).
    BusquedaPanel   — Búsqueda directa sin IA usando filtros clásicos.
    AyudaPanel      — Guía contextual adaptada al rol del usuario.
    AdminPanel      — Gestión de usuarios y logs de auditoría (solo admin).

Widgets migrados a CustomTkinter:
    - ctk.CTkFrame       — todos los contenedores principales
    - ctk.CTkLabel       — todas las etiquetas de texto
    - ctk.CTkButton      — todos los botones (incluido _mk_button)
    - ctk.CTkEntry       — entradas de texto en BusquedaPanel
    - ctk.CTkScrollableFrame — panel de ayuda (reemplaza Canvas + Scrollbar manual)
    - ctk.CTkRadioButton — selector de roles en diálogo de AdminPanel

Widgets conservados en Tkinter/ttk (no tienen equivalente CTk funcional):
    - ttk.Treeview    — tablas de datos; integrado visualmente con tema oscuro
    - ttk.Scrollbar   — asociado al Treeview
    - ttk.Combobox    — selector de categorías en BusquedaPanel
    - tk.Toplevel     — diálogo modal de cambio de rol en AdminPanel

Soporte de español:
    - Archivo declarado UTF-8 (primera línea)
    - Todos los textos con tildes, ñ y signos de interrogación corregidos

Dependencias:
    - customtkinter
    - tkinter / ttk  (stdlib — solo para Treeview, Combobox, Toplevel)
    - database_manager.DatabaseManager
    - seguridad.SecurityManager
    - No importa main.py ni chat_controller (desacoplado de presentación).
"""

from __future__ import annotations

import logging
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable

import customtkinter as ctk  # MIGRADO: interfaz principal a CustomTkinter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Iconografía vectorial — Segoe MDL2 Assets (built-in Windows 10 / 11)
# ---------------------------------------------------------------------------
_ICON_FONT = "Segoe MDL2 Assets"
_ICON_REFRESH = "\uE72C"   # Refresh / ArrowSync

# ---------------------------------------------------------------------------
# Mensajes de error para el usuario final
# Los mensajes técnicos van al logger; estos se muestran en la UI.
# ---------------------------------------------------------------------------
MENSAJES: dict[str, str] = {
    "sin_conexion":     "No se pudo conectar a la base de datos.",
    "sin_resultados":   "No se encontraron resultados para tu búsqueda.",
    "sin_permisos":     "Tu rol no tiene permisos para esta acción.",
    "error_bd":         "Ocurrió un error al obtener los datos. Intenta de nuevo.",
    "error_ia":         "La IA no pudo procesar tu solicitud. Intenta de nuevo.",
    "error_inesperado": "Ocurrió un error inesperado. Por favor, intenta de nuevo.",
    "cuota_ia":         "La IA está sin cuota temporalmente. Espera unos segundos.",
    "sql_bloqueado":    "La consulta fue bloqueada por seguridad.",
    "accion_ok":        "Operación completada exitosamente.",
    "campo_requerido":  "Todos los campos son obligatorios.",
    "ia_no_entendio":   "No pude interpretar tu solicitud. Intenta reformularla.",
}

# ---------------------------------------------------------------------------
# Configuración de estilo oscuro para ttk.Treeview
# CONSERVADO: ttk.Treeview no tiene equivalente en CustomTkinter.
# Se aplica el tema visual oscuro para que se integre con la paleta del proyecto.
# Se llama una sola vez al construir el primer panel que use Treeview.
# ---------------------------------------------------------------------------
_estilo_configurado = False


def _configurar_estilo_treeview(theme: dict, fonts: dict) -> None:
    """
    Aplica el tema oscuro al widget ttk.Treeview de forma global.

    Debe llamarse antes de instanciar cualquier Treeview. Idempotente:
    ejecutar más de una vez no tiene efecto secundario gracias al flag modular.

    CONSERVADO: ttk.Treeview — no tiene equivalente CTk; se integra visualmente
    al tema oscuro configurando el style "clam" manualmente.

    Args:
        theme: Diccionario de colores del tema de la aplicación.
        fonts: Diccionario de familias tipográficas de la aplicación.
    """
    global _estilo_configurado
    if _estilo_configurado:
        return
    _estilo_configurado = True

    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass  # Algunos entornos no tienen el tema "clam"; continuar con el predeterminado

    # Tabla minimalista Deep Carbon — sin bordes, solo espaciado y hover
    body_text = theme.get("body_text", "#CBD5E1")
    style.configure(
        "Dark.Treeview",
        background="#151921",
        foreground=body_text,
        fieldbackground="#151921",
        rowheight=60,
        font=(fonts["body"], 12),           # 16px Regular
        borderwidth=0,
        relief="flat",
        rowspacing=0,
    )
    style.configure(
        "Dark.Treeview.Heading",
        background=theme["panel"],
        foreground=theme["text"],
        font=(fonts["body"], 12, "bold"),    # 16px Bold
        relief="flat",
        borderwidth=0,
        padding=(8, 12),
    )
    style.map(
        "Dark.Treeview",
        background=[("selected", "#1E293B"), ("active", "#1E293B")],
        foreground=[("selected", "#FFFFFF"),  ("active", "#FFFFFF")],
    )
    style.configure(
        "Dark.Vertical.TScrollbar",
        background=theme["panel_soft"],
        troughcolor=theme["panel"],
        arrowcolor=theme["muted"],
        borderwidth=0,
    )


# ---------------------------------------------------------------------------
# Clase base compartida por todos los paneles
# MIGRADO: extiende ctk.CTkFrame en lugar de tk.Frame
# ---------------------------------------------------------------------------


class _PanelBase(ctk.CTkFrame):
    """
    Frame base para todos los paneles de funcionalidades.

    MIGRADO: extiende ctk.CTkFrame (antes tk.Frame) para integrarse con
    el árbol de widgets CTk y recibir el fondo oscuro correcto.

    Centraliza:
    - Acceso compartido a theme, fonts, db y seguridad.
    - Ejecución asíncrona: _async(fn, callback) corre fn en un hilo secundario
      y llama callback(result) en el hilo principal de Tkinter.
    - Helpers para crear widgets con estilo uniforme (_mk_label, _mk_button,
      _mk_treeview, _limpiar_tree, _mostrar_estado).
    """

    def __init__(
        self,
        parent: Any,
        theme: dict,
        fonts: dict,
        db: Any,
        seguridad: Any,
    ) -> None:
        # MIGRADO: fg_color en lugar de bg para CTkFrame
        super().__init__(parent, fg_color=theme["bg"], corner_radius=0)
        self.theme = theme
        self.fonts = fonts
        self.db = db
        self.seguridad = seguridad
        _configurar_estilo_treeview(theme, fonts)

    # ------------------------------------------------------------------
    # Ejecución asíncrona (sin cambios)
    # ------------------------------------------------------------------

    def _async(self, fn: Callable, callback: Callable) -> None:
        """
        Ejecuta fn() en un hilo secundario y llama callback(resultado) en el
        hilo principal de Tkinter mediante self.after().

        Si fn() lanza una excepción, se registra en el logger y callback
        recibe None para que el panel muestre un mensaje de error amigable.
        """
        def _run() -> None:
            try:
                result = fn()
            except Exception as exc:
                logger.error("Error en operación async [%s]: %s", self.__class__.__name__, exc)
                result = None
            self.after(0, callback, result)

        threading.Thread(target=_run, daemon=True).start()

    # ------------------------------------------------------------------
    # Helpers de creación de widgets con estilo consistente
    # MIGRADO: _mk_button ahora crea ctk.CTkButton
    # ------------------------------------------------------------------

    def _mk_button(
        self,
        parent: Any,
        texto: str,
        command: Callable,
        color: str | None = None,
        fg: str = "#FFFFFF",
    ) -> ctk.CTkButton:
        """
        Crea un botón CTkButton con el estilo del tema de la aplicación.

        MIGRADO: ctk.CTkButton en lugar de tk.Button.
        Parámetros de color mapeados: bg→fg_color, fg→text_color, hover→hover_color.
        """
        c = color or self.theme["accent"]
        hover = self.theme["accent_soft"] if c == self.theme["accent"] else self.theme["border"]
        return ctk.CTkButton(
            parent,
            text=texto,
            command=command,
            fg_color=c,
            text_color=fg,
            hover_color=hover,
            corner_radius=12,
            height=38,
            font=(self.fonts["body"], 14, "bold"),
            cursor="hand2",
        )

    def _mk_refresh_button(
        self,
        parent: Any,
        command: Callable,
        texto: str = "Actualizar",
    ) -> ctk.CTkFrame:
        """
        Crea un botón de recarga con icono vectorial MDL2 (Segoe MDL2 Assets)
        y texto, sobre fondo azul oscuro.

        Retorna el frame exterior — llama a .pack() / .grid() sobre él.
        """
        _BG      = "#1E3A8A"    # Azul oscuro
        _BG_HVR  = "#1E40AF"    # Azul hover
        _FG      = "#FFFFFF"

        frame = ctk.CTkFrame(parent, fg_color=_BG, corner_radius=12, cursor="hand2", height=38)

        icon_lbl = ctk.CTkLabel(
            frame,
            text=_ICON_REFRESH,
            font=(_ICON_FONT, 14),
            text_color=_FG,
            fg_color="transparent",
            width=20,
        )
        icon_lbl.pack(side=tk.LEFT, padx=(12, 0), pady=6)

        text_lbl = ctk.CTkLabel(
            frame,
            text=texto,
            font=(self.fonts["body"], 14, "bold"),
            text_color=_FG,
            fg_color="transparent",
        )
        text_lbl.pack(side=tk.LEFT, padx=(6, 14), pady=6)

        for w in (frame, icon_lbl, text_lbl):
            w.bind("<Button-1>", lambda _: command())
            w.bind("<Enter>",    lambda _, f=frame: f.configure(fg_color=_BG_HVR))
            w.bind("<Leave>",    lambda _, f=frame: f.configure(fg_color=_BG))

        return frame

    def _mk_treeview(
        self,
        parent: Any,
        columnas: list[tuple[str, str, int]],
    ) -> ttk.Treeview:
        """
        Crea un ttk.Treeview con tema oscuro, columnas configuradas y scrollbar.

        CONSERVADO: ttk.Treeview — no tiene equivalente en CustomTkinter.
        El widget se empaqueta automáticamente expandiéndose para llenar el parent.

        Args:
            parent:   Widget contenedor donde se empaquetará el Treeview.
            columnas: Lista de (id_columna, titulo_columna, ancho_px).

        Returns:
            El widget Treeview (sin el contenedor, que se gestiona internamente).
        """
        container = tk.Frame(parent, bg="#151921")
        container.pack(fill=tk.BOTH, expand=True)

        ids = [c[0] for c in columnas]
        tree = ttk.Treeview(
            container,
            columns=ids,
            show="headings",
            style="Dark.Treeview",
        )
        for col_id, titulo, ancho in columnas:
            tree.heading(col_id, text=titulo)
            tree.column(col_id, width=ancho, anchor="w", stretch=True)

        vsb = ttk.Scrollbar(
            container,
            orient="vertical",
            command=tree.yview,
            style="Dark.Vertical.TScrollbar",
        )
        tree.configure(yscrollcommand=vsb.set)
        # Filas: fondo uniforme #151921, impar levemente más oscuro
        # simula border-bottom: 1px solid #1E293B sin rejillas verticales.
        tree.tag_configure("fila_par",   background="#151921")
        tree.tag_configure("fila_impar", background="#111720")
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        tree.pack(fill=tk.BOTH, expand=True)
        self._configurar_hover_tree(tree)
        return tree

    def _limpiar_tree(self, tree: ttk.Treeview) -> None:
        """Elimina todas las filas del Treeview."""
        for item in tree.get_children():
            tree.delete(item)

    def _insertar_fila(self, tree: ttk.Treeview, valores: tuple, indice: int) -> None:
        """Inserta una fila limpiando artefactos de repr de tupla en valores string."""
        tag = "fila_par" if indice % 2 == 0 else "fila_impar"

        def _limpiar(v: Any) -> Any:
            if not isinstance(v, str):
                return v
            s = v.strip()
            # Elimina repr de tupla de un elemento: ('valor',) → valor
            if s.startswith("('") and s.endswith("',)"):
                return s[2:-3]
            if s.startswith('("') and s.endswith('",)'):
                return s[2:-3]
            # Elimina paréntesis y comas sobrantes
            if s.startswith("(") and s.endswith(",)"):
                return s[1:-2].strip().strip("'\"")
            # Limpieza de caracteres: (, ), ', ,  según spec
            s = s.strip("()'\"")
            s = s.rstrip(",")
            return s

        limpios = tuple(_limpiar(v) for v in valores)
        tree.insert("", tk.END, values=limpios, tags=(tag,))

    def _configurar_hover_tree(self, tree: ttk.Treeview) -> None:
        """
        Añade efecto hover al Treeview mediante tags y bindings de movimiento.

        Usa un closure dict para rastrear el ítem actualmente resaltado y
        actualiza los tags sin afectar el zebra striping existente.
        """
        # Línea de luz violeta al pasar el cursor (Deep Carbon hover)
        tree.tag_configure("hover", background="#1E293B")
        state: dict[str, str | None] = {"item": None}

        def _on_motion(event: tk.Event) -> None:  # type: ignore[type-arg]
            item = tree.identify_row(event.y)
            if item == state["item"]:
                return
            if state["item"]:
                tags = [t for t in tree.item(state["item"], "tags") if t != "hover"]
                tree.item(state["item"], tags=tags)
            if item:
                current = list(tree.item(item, "tags"))
                if "hover" not in current:
                    current.append("hover")
                tree.item(item, tags=current)
            state["item"] = item or None

        def _on_leave(_event: tk.Event) -> None:  # type: ignore[type-arg]
            if state["item"]:
                tags = [t for t in tree.item(state["item"], "tags") if t != "hover"]
                tree.item(state["item"], tags=tags)
                state["item"] = None

        tree.bind("<Motion>", _on_motion)
        tree.bind("<Leave>", _on_leave)

    def _mostrar_estado(self, label: ctk.CTkLabel, texto: str, ok: bool = True) -> None:
        """
        Actualiza un label de estado con color según si es éxito o error.

        MIGRADO: usa configure(text_color=) en lugar de config(fg=) de tk.Label.
        """
        color = self.theme["ok"] if ok else self.theme["error"]
        label.configure(text=texto, text_color=color)


# ---------------------------------------------------------------------------
# Panel 1: Dashboard de métricas (con separación estricta por rol)
# ---------------------------------------------------------------------------


class DashboardPanel(_PanelBase):
    """
    Panel de métricas del sistema con control de acceso basado en roles (RBAC).

    ── SEGURIDAD: Principio de Mínimo Privilegio ────────────────────────────
    El dashboard aplica separación real de datos según el rol del usuario
    autenticado, siguiendo el principio de mínimo privilegio (Principle of
    Least Privilege — NIST SP 800-53 AC-6):

      "Cada actor del sistema debe acceder únicamente a los recursos y datos
       estrictamente necesarios para cumplir su función, ni uno más."

    La separación opera en DOS capas independientes:

    1. CAPA DE BASE DE DATOS (backend — seguridad real):
       Para el rol 'usuario', las consultas SQL se parametrizan con el
       id_usuario del usuario autenticado (WHERE id_usuario = ?).
       Esto garantiza que los datos de otros usuarios NUNCA salgan de la BD.
       No es un filtro en Python sobre datos globales: la query misma solo
       devuelve filas del usuario en sesión.
       Se usan parámetros ? (pyodbc) para prevenir SQL Injection (OWASP A03).

    2. CAPA DE INTERFAZ (UI — claridad visual):
       Las cards y la tabla muestran únicamente las métricas correspondientes
       al rol, con textos apropiados ("Mis préstamos" vs "Préstamos globales").
       El usuario con rol 'usuario' no puede inferir la existencia de datos
       de otros usuarios porque no aparecen en ninguna parte de la interfaz.

    Este diseño mitiga OWASP A01:2021 — Broken Access Control al no depender
    exclusivamente de la UI para proteger datos sensibles.

    Roles soportados:
      - 'admin'     → métricas globales del sistema, top libros prestados.
      - 'operativo' → igual que admin (gestión de préstamos).
      - 'usuario'   → solo sus propios préstamos y conteo de libros disponibles.
    ─────────────────────────────────────────────────────────────────────────
    """

    # ── Consultas globales (admin / operativo) ────────────────────────────
    _SQL_STATS_ADMIN: list[tuple[str, str]] = [
        ("total_libros",       "SELECT COUNT(*) FROM catalogo.libros"),
        ("prestamos_activos",  "SELECT COUNT(*) FROM operaciones.vista_prestamos_activos"),
        ("prestamos_vencidos", "SELECT COUNT(*) FROM operaciones.vista_prestamos_vencidos"),
        ("total_usuarios",     "SELECT COUNT(*) FROM personas.usuarios"),
    ]

    _SQL_TOP_LIBROS_ADMIN: str = """
        SELECT TOP 5
            l.titulo,
            COUNT(p.id_libro) AS veces_prestado
        FROM operaciones.prestamos p
        JOIN catalogo.libros l ON p.id_libro = l.id_libro
        GROUP BY l.titulo
        ORDER BY veces_prestado DESC
    """

    # ── Consultas filtradas por usuario (rol 'usuario') ───────────────────
    # SEGURIDAD: todas usan el parámetro ? (id_usuario) — jamás datos globales.
    _SQL_LIBROS_DISPONIBLES: str = """
        SELECT COUNT(*) FROM catalogo.libros
        WHERE id_libro NOT IN (
            SELECT id_libro FROM operaciones.prestamos WHERE estado = 1
        )
    """
    _SQL_MIS_ACTIVOS: str = """
        SELECT COUNT(*) FROM operaciones.prestamos
        WHERE id_usuario = ? AND estado = 1
    """
    _SQL_MIS_VENCIDOS: str = """
        SELECT COUNT(*) FROM operaciones.prestamos
        WHERE id_usuario = ? AND estado = 1
          AND fecha_limite < CAST(GETDATE() AS DATE)
    """
    _SQL_MIS_PRESTAMOS: str = """
        SELECT TOP 5
            l.titulo,
            CONVERT(VARCHAR(10), p.fecha_prestamo, 103) AS fecha_prestamo,
            CONVERT(VARCHAR(10), p.fecha_limite,   103) AS fecha_limite
        FROM operaciones.prestamos p
        JOIN catalogo.libros l ON p.id_libro = l.id_libro
        WHERE p.id_usuario = ?
        ORDER BY p.fecha_prestamo DESC
    """

    # ── Click-to-chat según rol ───────────────────────────────────────────
    _CARD_CONSULTAS_ADMIN: dict[str, str] = {
        "total_libros":       "¿Cuántos libros hay registrados?",
        "prestamos_activos":  "Préstamos activos",
        "prestamos_vencidos": "Préstamos vencidos",
        "total_usuarios":     "Lista de usuarios del sistema",
    }
    _CARD_CONSULTAS_USUARIO: dict[str, str] = {
        "libros_disponibles": "¿Cuántos libros están disponibles?",
        "mis_activos":        "Mis préstamos activos",
        "mis_vencidos":       "Mis préstamos vencidos",
    }

    def __init__(
        self,
        parent: Any,
        theme: dict,
        fonts: dict,
        db: Any,
        seguridad: Any,
        on_ver_detalle: Callable | None = None,
    ) -> None:
        super().__init__(parent, theme, fonts, db, seguridad)
        # Capturar rol e ID del usuario en sesión para toda la vida del panel.
        usuario = (seguridad.usuario_actual or {}) if seguridad else {}
        self._rol: str = str(usuario.get("rol") or "usuario")
        self._id_usuario: int = int(usuario.get("id") or 0)

        self._cards: dict[str, ctk.CTkFrame] = {}
        self._tree: ttk.Treeview | None = None
        self._lbl_estado: ctk.CTkLabel | None = None
        self.on_ver_detalle = on_ver_detalle

        # Mapa de consultas chat activo según rol
        self._card_consultas: dict[str, str] = (
            self._CARD_CONSULTAS_ADMIN
            if self._rol in ("admin", "operativo")
            else self._CARD_CONSULTAS_USUARIO
        )

        self._construir()

    def _construir(self) -> None:
        """Construye el dashboard: cabecera, cards y tabla según el rol activo."""
        es_admin = self._rol in ("admin", "operativo")

        # --- Cabecera ---
        cabecera = ctk.CTkFrame(self, fg_color=self.theme["bg"], corner_radius=0)
        cabecera.pack(fill=tk.X, padx=40, pady=(32, 12))

        ctk.CTkLabel(
            cabecera,
            text="Dashboard",
            fg_color="transparent",
            text_color=self.theme["text"],
            font=(self.fonts["title"], 27, "bold"),
        ).pack(side=tk.LEFT)

        self._lbl_estado = ctk.CTkLabel(
            cabecera,
            text="",
            fg_color="transparent",
            text_color=self.theme["muted"],
            font=(self.fonts["body"], 12),
        )
        self._lbl_estado.pack(side=tk.LEFT, padx=14)

        self._mk_refresh_button(cabecera, self.cargar_datos, "Actualizar").pack(side=tk.RIGHT)

        # --- Cards: definición según rol ---
        if es_admin:
            definiciones_cards = [
                ("total_libros",       "Total Libros",         self.theme["accent"]),
                ("prestamos_activos",  "Préstamos Activos",    self.theme["ok"]),
                ("prestamos_vencidos", "Vencidos",             self.theme["warn"]),
                ("total_usuarios",     "Usuarios Registrados", "#6366f1"),
            ]
        else:
            # rol 'usuario': solo sus propios datos
            definiciones_cards = [
                ("libros_disponibles", "Libros Disponibles",      self.theme["accent"]),
                ("mis_activos",        "Mis Préstamos Activos",    self.theme["ok"]),
                ("mis_vencidos",       "Mis Vencidos",             self.theme["warn"]),
            ]

        cards_frame = ctk.CTkFrame(self, fg_color=self.theme["bg"], corner_radius=0)
        cards_frame.pack(fill=tk.X, padx=40, pady=(0, 16))

        for i, (key, titulo, color) in enumerate(definiciones_cards):
            card = self._mk_card(cards_frame, titulo, color, key)
            card.grid(row=0, column=i, padx=8, pady=4, sticky="nsew")
            cards_frame.columnconfigure(i, weight=1)
            self._cards[key] = card

        # --- Tabla: título y columnas según rol ---
        tabla_frame = ctk.CTkFrame(
            self,
            fg_color=self.theme["panel"],
            border_width=1,
            border_color=self.theme.get("glass_border", self.theme["border"]),
            corner_radius=12,
        )
        tabla_frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=(0, 40))

        if es_admin:
            tabla_titulo    = "Top 5 — Libros más prestados"
            tabla_subtitulo = "Ranking histórico por número de préstamos registrados"
            tabla_cols      = [("titulo", "Título", 500), ("veces", "Veces prestado", 140)]
        else:
            tabla_titulo    = "Mis préstamos recientes"
            tabla_subtitulo = "Últimos libros solicitados en tu cuenta"
            tabla_cols      = [
                ("titulo",   "Título",        400),
                ("prestado", "Fecha préstamo", 130),
                ("limite",   "Fecha límite",   130),
            ]

        ctk.CTkLabel(
            tabla_frame,
            text=tabla_titulo,
            fg_color="transparent",
            text_color=self.theme["text"],
            font=(self.fonts["body"], 18, "bold"),
        ).pack(anchor="w", padx=24, pady=(20, 0))

        ctk.CTkLabel(
            tabla_frame,
            text=tabla_subtitulo,
            fg_color="transparent",
            text_color=self.theme.get("body_text", "#CBD5E1"),
            font=(self.fonts["body"], 12),
        ).pack(anchor="w", padx=24, pady=(4, 12))

        self._tree = self._mk_treeview(tabla_frame, tabla_cols)

        self.cargar_datos()

    def _mk_card(self, parent: Any, titulo: str, color: str, key: str) -> ctk.CTkFrame:
        """
        Crea una tarjeta de métrica con barra de acento lateral izquierda.

        Diseño: fondo oscuro, barra de 4px a la izquierda con el color de estado.
        Al hacer clic envía la consulta asociada al chat (callback on_ver_detalle).
        """
        _bg_normal = "#1C212E"
        _bg_hover  = "#252B3A"

        card = ctk.CTkFrame(
            parent,
            fg_color=_bg_normal,
            corner_radius=24,
            width=260,
            height=160,
        )
        card.pack_propagate(False)

        ctk.CTkFrame(card, fg_color=color, width=4, corner_radius=2).pack(
            side=tk.LEFT, fill=tk.Y
        )

        content = ctk.CTkFrame(card, fg_color="transparent", corner_radius=0)
        content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 12))

        lbl_num = ctk.CTkLabel(
            content,
            text="—",
            fg_color="transparent",
            text_color=color,
            font=(self.fonts["title"], 32, "bold"),
        )
        lbl_num.pack(pady=(14, 4))

        ctk.CTkLabel(
            content,
            text=titulo,
            fg_color="transparent",
            text_color=self.theme.get("body_text", "#CBD5E1"),
            font=(self.fonts["body"], 12),
        ).pack(pady=(0, 14))

        card._lbl_num = lbl_num  # type: ignore[attr-defined]

        consulta = self._card_consultas.get(key, "")

        def _enter(_e: Any) -> None:
            card.configure(fg_color=_bg_hover)

        def _leave(_e: Any) -> None:
            card.configure(fg_color=_bg_normal)

        def _click(_e: Any) -> None:
            if consulta and self.on_ver_detalle:
                self.on_ver_detalle(consulta)

        for widget in (card, content, lbl_num):
            widget.bind("<Enter>", _enter)
            widget.bind("<Leave>", _leave)
            if consulta and self.on_ver_detalle:
                widget.bind("<Button-1>", _click)

        return card

    # ------------------------------------------------------------------
    # Carga de datos: dispatcher por rol
    # ------------------------------------------------------------------

    def cargar_datos(self) -> None:
        """Despacha la carga al método correcto según el rol del usuario en sesión."""
        if self._lbl_estado:
            self._lbl_estado.configure(text="Cargando...", text_color=self.theme["muted"])

        if self._rol in ("admin", "operativo"):
            self._cargar_dashboard_admin()
        else:
            self._cargar_dashboard_usuario()

    def _cargar_dashboard_admin(self) -> None:
        """
        Carga métricas GLOBALES del sistema (solo admin / operativo).

        Consultas sin filtro de usuario: totales de libros, préstamos y usuarios.
        """
        def _fetch() -> dict | None:
            if self.db is None:
                return None
            resultado: dict = {}
            for key, sql in self._SQL_STATS_ADMIN:
                filas = self.db.ejecutar_consulta(sql)
                resultado[key] = str(filas[0][0]) if filas and filas[0] else "?"
            resultado["top_libros"] = self.db.ejecutar_consulta(self._SQL_TOP_LIBROS_ADMIN) or []
            return resultado

        def _aplicar(datos: dict | None) -> None:
            if datos is None:
                if self._lbl_estado:
                    self._mostrar_estado(self._lbl_estado, MENSAJES["error_bd"], ok=False)
                return
            for key, card in self._cards.items():
                card._lbl_num.configure(text=datos.get(key, "?"))  # type: ignore[attr-defined]
            if "prestamos_vencidos" in self._cards:
                try:
                    n = int(datos.get("prestamos_vencidos", "0"))
                    color_v = self.theme["error"] if n > 0 else self.theme["warn"]
                    self._cards["prestamos_vencidos"]._lbl_num.configure(text_color=color_v)  # type: ignore[attr-defined]
                except (ValueError, AttributeError):
                    pass
            if self._tree:
                self._limpiar_tree(self._tree)
                for i, fila in enumerate(datos.get("top_libros", [])):
                    self._insertar_fila(self._tree, (fila[0], fila[1]), i)
            if self._lbl_estado:
                self._mostrar_estado(self._lbl_estado, "Datos actualizados", ok=True)

        self._async(_fetch, _aplicar)

    def _cargar_dashboard_usuario(self) -> None:
        """
        Carga métricas PERSONALES del usuario en sesión.

        SEGURIDAD: todas las queries filtran con WHERE id_usuario = ?
        usando el id_usuario capturado en __init__. Los datos de otros
        usuarios nunca salen de la base de datos.
        """
        uid = self._id_usuario

        def _fetch() -> dict | None:
            if self.db is None or not uid:
                return None
            resultado: dict = {}

            # Libros disponibles: sin filtro de usuario (info pública del catálogo)
            filas = self.db.ejecutar_consulta(self._SQL_LIBROS_DISPONIBLES)
            resultado["libros_disponibles"] = str(filas[0][0]) if filas and filas[0] else "?"

            # Mis préstamos activos — filtrado por id_usuario (parámetro seguro)
            filas = self.db.ejecutar_consulta(self._SQL_MIS_ACTIVOS, (uid,))
            resultado["mis_activos"] = str(filas[0][0]) if filas and filas[0] else "?"

            # Mis préstamos vencidos — filtrado por id_usuario (parámetro seguro)
            filas = self.db.ejecutar_consulta(self._SQL_MIS_VENCIDOS, (uid,))
            resultado["mis_vencidos"] = str(filas[0][0]) if filas and filas[0] else "?"

            # Tabla: últimos préstamos del usuario — filtrado por id_usuario
            resultado["mis_prestamos"] = (
                self.db.ejecutar_consulta(self._SQL_MIS_PRESTAMOS, (uid,)) or []
            )
            return resultado

        def _aplicar(datos: dict | None) -> None:
            if datos is None:
                if self._lbl_estado:
                    self._mostrar_estado(self._lbl_estado, MENSAJES["error_bd"], ok=False)
                return
            for key, card in self._cards.items():
                card._lbl_num.configure(text=datos.get(key, "?"))  # type: ignore[attr-defined]
            # Colorear mis vencidos en rojo si hay alguno
            if "mis_vencidos" in self._cards:
                try:
                    n = int(datos.get("mis_vencidos", "0"))
                    color_v = self.theme["error"] if n > 0 else self.theme["warn"]
                    self._cards["mis_vencidos"]._lbl_num.configure(text_color=color_v)  # type: ignore[attr-defined]
                except (ValueError, AttributeError):
                    pass
            if self._tree:
                self._limpiar_tree(self._tree)
                for i, fila in enumerate(datos.get("mis_prestamos", [])):
                    self._insertar_fila(self._tree, (fila[0], fila[1], fila[2]), i)
            if self._lbl_estado:
                self._mostrar_estado(self._lbl_estado, "Datos actualizados", ok=True)

        self._async(_fetch, _aplicar)


# ---------------------------------------------------------------------------
# Panel 2: Búsqueda directa sin IA
# ---------------------------------------------------------------------------


class BusquedaPanel(_PanelBase):
    """
    Panel de búsqueda con filtros clásicos, sin pasar por la IA.

    MIGRADO: botones de modo, input de búsqueda y contenedores usan CTk.
    CONSERVADO: ttk.Treeview para resultados y ttk.Combobox para categorías.

    Args:
        on_usar_en_chat: Callback opcional para enviar la pregunta al chat.
    """

    def __init__(
        self,
        parent: Any,
        theme: dict,
        fonts: dict,
        db: Any,
        seguridad: Any,
        on_usar_en_chat: Callable | None = None,
    ) -> None:
        super().__init__(parent, theme, fonts, db, seguridad)
        self._modo = tk.StringVar(value="titulo")
        self._tree: ttk.Treeview | None = None
        self._lbl_resultado: ctk.CTkLabel | None = None
        self._input_area: ctk.CTkFrame | None = None
        self._ent_actual: ctk.CTkEntry | None = None
        self._cb_categoria: ttk.Combobox | None = None
        self._categorias: list[str] = []
        self._mode_buttons: dict[str, ctk.CTkButton] = {}
        self._ent_placeholder: str = ""
        self.on_usar_en_chat = on_usar_en_chat
        self._construir()
        self._cargar_categorias()

    def _construir(self) -> None:
        """Construye la estructura visual del panel de búsqueda."""
        # --- Cabecera ---
        cabecera = ctk.CTkFrame(self, fg_color=self.theme["bg"], corner_radius=0)
        cabecera.pack(fill=tk.X, padx=40, pady=(32, 8))

        ctk.CTkLabel(
            cabecera,
            text="Búsqueda Directa",
            fg_color="transparent",
            text_color=self.theme["text"],
            font=(self.fonts["title"], 27, "bold"),   # H1: 36px
        ).pack(side=tk.LEFT)

        ctk.CTkLabel(
            cabecera,
            text="Sin IA — Filtros clásicos directos",
            fg_color="transparent",
            text_color=self.theme.get("body_text", "#CBD5E1"),
            font=(self.fonts["body"], 12),
        ).pack(side=tk.LEFT, padx=16)

        # --- Selectores de modo (botones tipo toggle — MIGRADO: CTkButton) ---
        modos_frame = ctk.CTkFrame(self, fg_color=self.theme["bg"], corner_radius=0)
        modos_frame.pack(fill=tk.X, padx=40, pady=(0, 12))

        modos = [
            ("titulo",      "Por título"),
            ("autor",       "Por autor"),
            ("categoria",   "Por categoría"),
            ("disponibles", "Disponibles"),
        ]
        for key, label in modos:
            btn = ctk.CTkButton(
                modos_frame,
                text=label,
                command=lambda k=key: self._on_modo_cambio(k),
                fg_color=self.theme["panel_soft"],
                text_color=self.theme["muted"],
                hover_color=self.theme["accent_soft"],
                corner_radius=8,
                height=34,
                font=(self.fonts["body"], 12, "bold"),
                cursor="hand2",
            )
            btn.pack(side=tk.LEFT, padx=(0, 4))
            self._mode_buttons[key] = btn
        self._actualizar_modo_botones("titulo")

        # --- Área de entrada (se reconstruye al cambiar de modo) ---
        self._input_area = ctk.CTkFrame(self, fg_color=self.theme["bg"], corner_radius=0)
        self._input_area.pack(fill=tk.X, padx=40, pady=(0, 12))
        self._construir_input_titulo()

        # --- Label de estado / resultado (MIGRADO: CTkLabel) ---
        self._lbl_resultado = ctk.CTkLabel(
            self,
            text="",
            fg_color="transparent",
            text_color=self.theme["muted"],
            font=(self.fonts["body"], 12),
        )
        self._lbl_resultado.pack(anchor="w", padx=40, pady=(0, 8))

        # --- Tabla de resultados (CONSERVADO: ttk.Treeview) ---
        tabla_frame = ctk.CTkFrame(
            self,
            fg_color=self.theme["panel"],
            border_width=1,
            border_color=self.theme.get("glass_border", self.theme["border"]),
            corner_radius=12,
        )
        tabla_frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=(0, 40))

        self._tree = self._mk_treeview(tabla_frame, [
            ("titulo",    "Título",    300),
            ("autor",     "Autor",     220),
            ("categoria", "Categoría", 140),
            ("ano",       "Año",        60),
        ])

    def _limpiar_input_area(self) -> None:
        """Destruye los widgets del área de entrada para reconstruirla."""
        if self._input_area:
            for w in self._input_area.winfo_children():
                w.destroy()
        self._ent_actual = None
        self._cb_categoria = None

    def _construir_input_titulo(self) -> None:
        """Input CTkEntry para búsqueda por título o autor, con placeholder manual."""
        assert self._input_area
        modo_actual = self._modo.get()
        placeholder = "Buscar por título..." if modo_actual == "titulo" else "Buscar por autor..."
        self._ent_placeholder = placeholder

        ent = ctk.CTkEntry(
            self._input_area,
            fg_color=self.theme["input_bg"],
            text_color=self.theme["muted"],
            border_color=self.theme["border"],
            border_width=1,
            font=(self.fonts["body"], 12),
            height=54,
            corner_radius=14,
        )
        ent.insert(0, placeholder)
        ent.pack(side=tk.LEFT, fill=tk.X, expand=True)

        def _focus_in(_e) -> None:
            if ent.get() == self._ent_placeholder:
                ent.delete(0, tk.END)
                ent.configure(text_color=self.theme["text"])
            ent.configure(border_color=self.theme["accent"], border_width=2)

        def _focus_out(_e) -> None:
            ent.configure(border_color=self.theme["border"], border_width=1)
            if not ent.get().strip():
                ent.insert(0, self._ent_placeholder)
                ent.configure(text_color=self.theme["muted"])

        ent.bind("<FocusIn>", _focus_in)
        ent.bind("<FocusOut>", _focus_out)
        ent.bind("<Return>", lambda _: self.buscar())
        ent.focus_set()
        self._ent_actual = ent
        self._mk_button(self._input_area, "Buscar", self.buscar).pack(side=tk.LEFT, padx=(8, 0))

    def _construir_input_categoria(self) -> None:
        """Combobox para seleccionar categoría. CONSERVADO: ttk.Combobox."""
        assert self._input_area
        cb = ttk.Combobox(
            self._input_area,
            state="readonly",
            font=(self.fonts["body"], 12),
            width=32,
            values=self._categorias,
        )
        if self._categorias:
            cb.current(0)
        cb.pack(side=tk.LEFT)
        self._cb_categoria = cb
        self._mk_button(self._input_area, "Buscar", self.buscar).pack(side=tk.LEFT, padx=(8, 0))

    def _construir_input_disponibles(self) -> None:
        """Sin input: solo el botón para listar disponibles."""
        assert self._input_area
        ctk.CTkLabel(
            self._input_area,
            text="Mostrará todos los libros no prestados actualmente.",
            fg_color="transparent",
            text_color=self.theme["muted"],
            font=(self.fonts["body"], 12),
        ).pack(side=tk.LEFT)
        self._mk_button(self._input_area, "Buscar disponibles", self.buscar).pack(
            side=tk.LEFT, padx=(12, 0))

    def _actualizar_modo_botones(self, modo_activo: str) -> None:
        """
        Resalta el botón del modo activo y apaga los demás.

        MIGRADO: usa configure(fg_color=, text_color=) en lugar de config(bg=, fg=).
        """
        for key, btn in self._mode_buttons.items():
            if key == modo_activo:
                btn.configure(fg_color=self.theme["accent"], text_color="#FFFFFF")
            else:
                btn.configure(fg_color=self.theme["panel_soft"], text_color=self.theme["muted"])

    def _on_modo_cambio(self, nuevo_modo: str) -> None:
        """Reconstruye el área de entrada según el modo seleccionado."""
        self._modo.set(nuevo_modo)
        self._actualizar_modo_botones(nuevo_modo)
        self._limpiar_input_area()
        if self._lbl_resultado:
            self._lbl_resultado.configure(text="")
        if self._tree:
            self._limpiar_tree(self._tree)

        if nuevo_modo in ("titulo", "autor"):
            self._construir_input_titulo()
        elif nuevo_modo == "categoria":
            self._construir_input_categoria()
        elif nuevo_modo == "disponibles":
            self._construir_input_disponibles()

    def _cargar_categorias(self) -> None:
        """Carga la lista de categorías desde la BD para el combobox."""
        def _fetch():
            if self.db is None:
                return []
            filas = self.db.ejecutar_consulta(
                "SELECT nombre_categoria FROM catalogo.categorias ORDER BY nombre_categoria"
            )
            return [f[0] for f in (filas or [])]

        def _aplicar(cats):
            self._categorias = cats or []

        self._async(_fetch, _aplicar)

    def buscar(self) -> None:
        """
        Ejecuta la búsqueda según el modo activo y actualiza la tabla de resultados.

        Las consultas son SQL parametrizado (sin construcción de cadenas con datos
        del usuario), lo que elimina el riesgo de SQL injection en este panel.
        """
        if self._lbl_resultado:
            self._lbl_resultado.configure(text="Buscando...", text_color=self.theme["muted"])
        if self._tree:
            self._limpiar_tree(self._tree)

        modo = self._modo.get()

        termino = ""
        if modo in ("titulo", "autor") and self._ent_actual:
            raw = self._ent_actual.get().strip()
            termino = "" if raw == self._ent_placeholder else raw
        elif modo == "categoria" and self._cb_categoria:
            termino = self._cb_categoria.get()

        _BASE = (
            "SELECT titulo, "
            "nombre_autor + ' ' + apellido_autor AS autor, "
            "nombre_categoria, ano_publicacion "
            "FROM catalogo.vista_libros_completa "
        )

        def _fetch():
            if self.db is None:
                return None
            if modo == "titulo":
                if not termino:
                    return "sin_termino"
                return self.db.ejecutar_consulta(
                    _BASE + "WHERE titulo LIKE ?", (f"%{termino}%",)
                )
            if modo == "autor":
                if not termino:
                    return "sin_termino"
                return self.db.ejecutar_consulta(
                    _BASE + "WHERE nombre_autor LIKE ? OR apellido_autor LIKE ?",
                    (f"%{termino}%", f"%{termino}%"),
                )
            if modo == "categoria":
                if not termino:
                    return "sin_termino"
                return self.db.ejecutar_consulta(
                    _BASE + "WHERE nombre_categoria = ?", (termino,)
                )
            if modo == "disponibles":
                return self.db.ejecutar_consulta(
                    _BASE + "WHERE id_libro NOT IN "
                    "(SELECT id_libro FROM operaciones.prestamos WHERE estado = 1)"
                )
            return None

        def _aplicar(filas) -> None:
            if not self._lbl_resultado or not self._tree:
                return
            if filas == "sin_termino":
                self._lbl_resultado.configure(
                    text="Escribe un término para buscar.",
                    text_color=self.theme["warn"],
                )
                return
            if filas is None:
                self._lbl_resultado.configure(
                    text=MENSAJES["error_bd"],
                    text_color=self.theme["error"],
                )
                return
            if not filas:
                self._lbl_resultado.configure(
                    text=MENSAJES["sin_resultados"],
                    text_color=self.theme["muted"],
                )
                return
            for i, fila in enumerate(filas):
                self._insertar_fila(self._tree, fila, i)
            self._lbl_resultado.configure(
                text=f"{len(filas)} resultado(s) encontrado(s).",
                text_color=self.theme["ok"],
            )

        self._async(_fetch, _aplicar)


# ---------------------------------------------------------------------------
# Panel 3: Ayuda guiada por rol
# ---------------------------------------------------------------------------


class AyudaPanel(_PanelBase):
    """
    Panel de ayuda contextual adaptado al rol del usuario activo.

    MIGRADO: usa CTkScrollableFrame en lugar del patrón Canvas + Scrollbar manual.
    Todos los widgets de contenido usan CTk para aspecto moderno.
    Los ejemplos se muestran como CTkButton interactivos en cuadrícula.

    Args:
        on_enviar_al_chat: Callback opcional con firma fn(pregunta: str).
    """

    _EJEMPLOS: dict[str, list[str]] = {
        "usuario": [
            "¿Cuántos libros hay registrados?",
            "Libros de tecnología",
            "Lista de autores",
            "Libros disponibles",
            'Buscar libro "1984"',
            "¿Cuáles son los préstamos vencidos?",
        ],
        "operativo": [
            "¿Cuántos libros hay registrados?",
            "Préstamos activos",
            "Préstamos vencidos",
            "Registrar préstamo para usuario 3, libro 5",
            "Devolver préstamo con ID 2",
            "Lista de autores",
        ],
        "admin": [
            "¿Cuántos libros hay registrados?",
            "Préstamos activos",
            "Registrar nuevo libro",
            "Préstamos vencidos",
            "Registrar un nuevo usuario",
            "Lista de usuarios del sistema",
        ],
    }

    _OPERACIONES: dict[str, list[tuple[str, str]]] = {
        "usuario": [
            ("Consultar catálogo",  "Busca libros por título, autor o categoría"),
            ("Ver disponibilidad",  "Consulta libros que no están prestados"),
            ("Ver estadísticas",    "Totales de libros, autores y categorías"),
            ("Buscar por autor",    "Todas las obras de un autor específico"),
        ],
        "operativo": [
            ("Gestión de préstamos", "Registrar nuevos préstamos y devoluciones"),
            ("Consultas avanzadas",  "Préstamos activos y vencidos con detalle"),
            ("Buscar usuarios",      "Encontrar usuarios por nombre o correo"),
            ("Ver catálogo",         "Información completa de todos los libros"),
        ],
        "admin": [
            ("Gestión completa",     "Acceso total al sistema"),
            ("Administrar usuarios", "Crear y gestionar cuentas, cambiar roles"),
            ("Ver logs",             "Auditoría de todas las consultas realizadas"),
            ("Estadísticas",         "Dashboard con métricas del sistema"),
        ],
    }

    _TIPS = [
        "Sé específico: 'libros de García Márquez' en vez de solo 'libros'.",
        "Usa los botones de consulta rápida para las preguntas más comunes.",
        "La pestaña Búsqueda Directa permite filtrar sin usar la IA.",
        "El panel SQL muestra exactamente la consulta que se ejecutó.",
        "'PEDIR' en la respuesta del asistente indica que necesita más datos.",
        "El asistente recuerda el contexto de los últimos 10 intercambios.",
    ]

    def __init__(
        self,
        parent: Any,
        theme: dict,
        fonts: dict,
        db: Any,
        seguridad: Any,
        on_enviar_al_chat: Callable | None = None,
    ) -> None:
        super().__init__(parent, theme, fonts, db, seguridad)
        self.on_enviar_al_chat = on_enviar_al_chat
        self._construir()

    def _construir(self) -> None:
        """
        Construye el panel de ayuda con scroll.

        MIGRADO: CTkScrollableFrame reemplaza el patrón Canvas + Scrollbar manual.
        El scroll en mouse wheel se gestiona automáticamente por CTk.
        """
        rol = (self.seguridad.usuario_actual or {}).get("rol", "usuario")

        # MIGRADO: CTkScrollableFrame — reemplaza Canvas + Scrollbar + create_window
        scroll_frame = ctk.CTkScrollableFrame(
            self,
            fg_color=self.theme["bg"],
            corner_radius=0,
            scrollbar_button_color=self.theme["border"],
            scrollbar_button_hover_color=self.theme["accent"],
        )
        scroll_frame.pack(fill=tk.BOTH, expand=True)
        contenido = scroll_frame

        px = 40

        # Título
        ctk.CTkLabel(
            contenido,
            text="Ayuda y Ejemplos",
            fg_color="transparent",
            text_color=self.theme["text"],
            font=(self.fonts["title"], 27, "bold"),   # H1: 36px
        ).pack(anchor="w", padx=px, pady=(32, 4))

        ctk.CTkLabel(
            contenido,
            text=f"Guía personalizada para tu rol: {rol.upper()}",
            fg_color="transparent",
            text_color=self.theme["muted"],
            font=(self.fonts["body"], 12),
        ).pack(anchor="w", padx=px, pady=(0, 12))

        # Sección: cómo usar el chat
        self._seccion_lista(contenido, "Cómo usar el chat", [
            "Escribe tu pregunta en el campo de texto del Chat y presiona Enter.",
            "El asistente interpreta tu pregunta, genera SQL y muestra el resultado.",
            "El SQL aparece en el panel derecho para total transparencia.",
            "El asistente puede pedir más información antes de ejecutar una acción.",
            "Usa los botones de consulta rápida para las preguntas más comunes.",
        ], px)

        # Sección: ejemplos para este rol
        ejemplos = self._EJEMPLOS.get(rol, self._EJEMPLOS["usuario"])
        self._seccion_ejemplos(contenido, "Preguntas de ejemplo para tu rol", ejemplos, px)

        # Sección: operaciones disponibles
        ops = self._OPERACIONES.get(rol, [])
        self._seccion_operaciones(contenido, "Qué puedes hacer", ops, px)

        # Sección: consejos
        self._seccion_lista(contenido, "Consejos para mejores resultados", self._TIPS, px)

        # Espacio al final
        ctk.CTkFrame(contenido, fg_color=self.theme["bg"], height=30, corner_radius=0).pack()

    def _separador(self, parent: Any, px: int) -> None:
        ctk.CTkFrame(
            parent, fg_color=self.theme["border"], height=1, corner_radius=0
        ).pack(fill=tk.X, padx=px, pady=(12, 6))

    def _titulo_seccion(self, parent: Any, texto: str, px: int) -> None:
        ctk.CTkLabel(
            parent,
            text=texto,
            fg_color="transparent",
            text_color=self.theme["text"],
            font=(self.fonts["body"], 13, "bold"),
        ).pack(anchor="w", padx=px, pady=(0, 8))

    def _seccion_lista(self, parent: Any, titulo: str, items: list[str], px: int) -> None:
        self._separador(parent, px)
        self._titulo_seccion(parent, titulo, px)
        for item in items:
            ctk.CTkLabel(
                parent,
                text=f"  •  {item}",
                fg_color="transparent",
                text_color=self.theme["muted"],
                font=(self.fonts["body"], 12),
                justify="left",
                wraplength=720,
                anchor="w",
            ).pack(anchor="w", padx=px, pady=2)

    def _seccion_ejemplos(
        self, parent: Any, titulo: str, ejemplos: list[str], px: int
    ) -> None:
        """
        Muestra ejemplos como botones CTkButton interactivos en cuadrícula.

        MIGRADO: ctk.CTkButton en lugar de tk.Button para aspecto moderno y hover.
        """
        self._separador(parent, px)
        self._titulo_seccion(parent, titulo, px)
        grid = ctk.CTkFrame(parent, fg_color=self.theme["bg"], corner_radius=0)
        grid.pack(anchor="w", padx=px, pady=(0, 8))
        for i, ejemplo in enumerate(ejemplos):
            btn = ctk.CTkButton(
                grid,
                text=ejemplo,
                command=lambda e=ejemplo: self._usar_ejemplo(e),
                fg_color=self.theme["panel_soft"],
                text_color=self.theme["text"],
                hover_color=self.theme["accent"],
                corner_radius=8,
                width=280,
                height=38,
                font=(self.fonts["body"], 12),
                cursor="hand2",
                anchor="w",
            )
            row, col = divmod(i, 2)
            btn.grid(row=row, column=col, padx=4, pady=4, sticky="w")

    def _seccion_operaciones(
        self, parent: Any, titulo: str, ops: list[tuple[str, str]], px: int
    ) -> None:
        if not ops:
            return
        self._separador(parent, px)
        self._titulo_seccion(parent, titulo, px)
        for op, desc in ops:
            row = ctk.CTkFrame(
                parent,
                fg_color=self.theme["panel_soft"],
                border_width=1,
                border_color=self.theme["border"],
                corner_radius=6,
            )
            row.pack(fill=tk.X, padx=px, pady=3)
            ctk.CTkLabel(
                row,
                text=op,
                fg_color="transparent",
                text_color=self.theme["accent"],
                font=(self.fonts["body"], 12, "bold"),
                width=200,
                anchor="w",
            ).pack(side=tk.LEFT, padx=12, pady=8)
            ctk.CTkLabel(
                row,
                text=desc,
                fg_color="transparent",
                text_color=self.theme["muted"],
                font=(self.fonts["body"], 12),
                anchor="w",
            ).pack(side=tk.LEFT, padx=4)

    def _usar_ejemplo(self, texto: str) -> None:
        """Envía el ejemplo al chat si el callback fue registrado."""
        if self.on_enviar_al_chat:
            self.on_enviar_al_chat(texto)


# ---------------------------------------------------------------------------
# Panel 4: Administración (solo admin)
# ---------------------------------------------------------------------------


class AdminPanel(_PanelBase):
    """
    Panel de administración del sistema. Solo accesible para rol 'admin'.

    Funcionalidades:
    - Pestaña Usuarios: lista todos los usuarios con id, nombre, correo y rol.
      Permite cambiar el rol de cualquier usuario vía diálogo de confirmación.
    - Pestaña Logs: muestra los últimos 100 registros de auditoria.consultas.

    MIGRADO: cabecera, botones de pestaña y contenedores usan CTk.
    CONSERVADO: ttk.Treeview para tablas de usuarios y logs.
    CONSERVADO: tk.Toplevel para el diálogo modal de cambio de rol
                (CTkToplevel no está disponible en CTk 5.x de forma estable).
    """

    _ROLES_DISPONIBLES = ["admin", "operativo", "usuario"]

    def __init__(self, parent: Any, theme: dict, fonts: dict, db: Any, seguridad: Any) -> None:
        super().__init__(parent, theme, fonts, db, seguridad)
        self._tree_usuarios: ttk.Treeview | None = None
        self._tree_logs: ttk.Treeview | None = None
        self._lbl_est_usuarios: ctk.CTkLabel | None = None
        self._lbl_est_logs: ctk.CTkLabel | None = None
        self._tab_botones: dict[str, ctk.CTkButton] = {}
        self._panel_usuarios: ctk.CTkFrame | None = None
        self._panel_logs: ctk.CTkFrame | None = None
        self._construir()

    def _construir(self) -> None:
        """Verifica permisos y construye el panel si el usuario es admin."""
        rol = (self.seguridad.usuario_actual or {}).get("rol", "")
        if rol != "admin":
            ctk.CTkLabel(
                self,
                text="Acceso restringido a administradores.",
                fg_color="transparent",
                text_color=self.theme["error"],
                font=(self.fonts["body"], 13),
            ).pack(expand=True)
            return

        # --- Cabecera ---
        cabecera = ctk.CTkFrame(self, fg_color=self.theme["bg"], corner_radius=0)
        cabecera.pack(fill=tk.X, padx=40, pady=(32, 12))

        ctk.CTkLabel(
            cabecera,
            text="Panel de Administración",
            fg_color="transparent",
            text_color=self.theme["text"],
            font=(self.fonts["title"], 27, "bold"),   # H1: 36px
        ).pack(side=tk.LEFT)

        # --- Barra de pestañas (MIGRADO: CTkButton) ---
        tab_bar = ctk.CTkFrame(self, fg_color=self.theme["bg"], corner_radius=0)
        tab_bar.pack(fill=tk.X, padx=40, pady=(0, 8))

        for key, label in [("usuarios", "Usuarios"), ("logs", "Logs de Auditoría")]:
            btn = ctk.CTkButton(
                tab_bar,
                text=label,
                command=lambda k=key: self._cambiar_tab(k),
                fg_color=self.theme["panel_soft"],
                text_color=self.theme["muted"],
                hover_color=self.theme["accent_soft"],
                corner_radius=8,
                height=36,
                font=(self.fonts["body"], 12, "bold"),
                cursor="hand2",
            )
            btn.pack(side=tk.LEFT, padx=(0, 4))
            self._tab_botones[key] = btn

        # --- Contenido de pestañas ---
        tab_content = ctk.CTkFrame(self, fg_color=self.theme["bg"], corner_radius=0)
        tab_content.pack(fill=tk.BOTH, expand=True)

        self._panel_usuarios = self._construir_tab_usuarios(tab_content)
        self._panel_logs = self._construir_tab_logs(tab_content)

        self._cambiar_tab("usuarios")

    def _cambiar_tab(self, tab: str) -> None:
        """
        Muestra la pestaña solicitada y actualiza el estilo de los botones.

        MIGRADO: usa configure(fg_color=, text_color=) en lugar de config(bg=, fg=).
        """
        if self._panel_usuarios:
            self._panel_usuarios.pack_forget()
        if self._panel_logs:
            self._panel_logs.pack_forget()

        for key, btn in self._tab_botones.items():
            if key == tab:
                btn.configure(fg_color=self.theme["accent"], text_color="#FFFFFF")
            else:
                btn.configure(fg_color=self.theme["panel_soft"], text_color=self.theme["muted"])

        if tab == "usuarios" and self._panel_usuarios:
            self._panel_usuarios.pack(fill=tk.BOTH, expand=True)
        elif tab == "logs" and self._panel_logs:
            self._panel_logs.pack(fill=tk.BOTH, expand=True)

    # ------------------------------------------------------------------
    # Pestaña Usuarios
    # ------------------------------------------------------------------

    def _construir_tab_usuarios(self, parent: Any) -> ctk.CTkFrame:
        """Construye la pestaña de gestión de usuarios."""
        frame = ctk.CTkFrame(parent, fg_color=self.theme["bg"], corner_radius=0)

        actions = ctk.CTkFrame(frame, fg_color=self.theme["bg"], corner_radius=0)
        actions.pack(fill=tk.X, padx=40, pady=(0, 12))

        self._lbl_est_usuarios = ctk.CTkLabel(
            actions,
            text="",
            fg_color="transparent",
            text_color=self.theme.get("body_text", "#CBD5E1"),
            font=(self.fonts["body"], 12),
        )
        self._lbl_est_usuarios.pack(side=tk.LEFT)

        self._mk_refresh_button(actions, self._cargar_usuarios, "Recargar").pack(
            side=tk.RIGHT, padx=(4, 0))
        self._mk_button(
            actions, "Cambiar Rol", self._cambiar_rol,
            color=self.theme["warn"], fg="#1a1a1a",
        ).pack(side=tk.RIGHT, padx=(4, 0))

        tabla_frame = ctk.CTkFrame(
            frame,
            fg_color=self.theme["panel"],
            border_width=1,
            border_color=self.theme.get("glass_border", self.theme["border"]),
            corner_radius=16,
        )
        tabla_frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=(0, 40))

        self._tree_usuarios = self._mk_treeview(tabla_frame, [
            ("id",       "ID",       50),
            ("nombre",   "Nombre",  180),
            ("apellido", "Apellido", 180),
            ("correo",   "Correo",  240),
            ("rol",      "Rol",      90),
        ])
        self._cargar_usuarios()
        return frame

    def _cargar_usuarios(self) -> None:
        """Carga la lista de usuarios desde la BD de forma asíncrona."""
        if self._lbl_est_usuarios:
            self._lbl_est_usuarios.configure(text="Cargando...", text_color=self.theme["muted"])

        def _fetch():
            if self.db is None:
                return None
            return self.db.ejecutar_consulta(
                "SELECT id_usuario, nombre_usuario, apellido_usuario, correo, rol "
                "FROM personas.usuarios ORDER BY id_usuario"
            )

        def _aplicar(filas) -> None:
            if not self._tree_usuarios or not self._lbl_est_usuarios:
                return
            self._limpiar_tree(self._tree_usuarios)
            if filas is None:
                self._mostrar_estado(self._lbl_est_usuarios, MENSAJES["error_bd"], ok=False)
                return
            for i, fila in enumerate(filas):
                self._insertar_fila(self._tree_usuarios, fila, i)
            self._lbl_est_usuarios.configure(
                text=f"{len(filas)} usuario(s)", text_color=self.theme["muted"])

        self._async(_fetch, _aplicar)

    def _cambiar_rol(self) -> None:
        """
        Abre un diálogo para cambiar el rol del usuario seleccionado en la tabla.

        CONSERVADO: usa tk.Toplevel y tk.Radiobutton para el diálogo modal.
        CTkToplevel en v5.x presenta incompatibilidades de foco en Windows;
        se optó por tk.Toplevel para garantizar estabilidad antes de presentación.
        """
        if not self._tree_usuarios:
            return
        sel = self._tree_usuarios.selection()
        if not sel:
            messagebox.showwarning("Selección requerida", "Selecciona un usuario de la lista.")
            return

        valores = self._tree_usuarios.item(sel[0])["values"]
        if not valores:
            return

        id_usuario = valores[0]
        nombre = f"{valores[1]} {valores[2]}"
        rol_actual = str(valores[4])

        # CONSERVADO: tk.Toplevel — diálogo modal estable en Windows
        dlg = tk.Toplevel(self)
        dlg.title("Cambiar Rol de Usuario")
        dlg.configure(bg=self.theme["panel"])
        dlg.geometry("380x260")
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.transient(self.winfo_toplevel())

        tk.Label(
            dlg,
            text=f"Usuario: {nombre}",
            bg=self.theme["panel"],
            fg=self.theme["text"],
            font=(self.fonts["body"], 12, "bold"),
        ).pack(pady=(20, 4))

        tk.Label(
            dlg,
            text=f"Rol actual: {rol_actual}",
            bg=self.theme["panel"],
            fg=self.theme["muted"],
            font=(self.fonts["body"], 12),
        ).pack(pady=(0, 12))

        nuevo_rol = tk.StringVar(value=rol_actual)
        for r in self._ROLES_DISPONIBLES:
            tk.Radiobutton(
                dlg,
                text=r.capitalize(),
                variable=nuevo_rol,
                value=r,
                bg=self.theme["panel"],
                fg=self.theme["text"],
                selectcolor=self.theme["panel_soft"],
                activebackground=self.theme["panel"],
                font=(self.fonts["body"], 12),
            ).pack()

        def _confirmar() -> None:
            rol_nuevo = nuevo_rol.get()
            if rol_nuevo == rol_actual:
                dlg.destroy()
                return
            if (self.seguridad.usuario_actual or {}).get("rol") != "admin":
                messagebox.showerror("Sin permisos", MENSAJES["sin_permisos"])
                dlg.destroy()
                return
            result = self.db.ejecutar_consulta(
                "UPDATE personas.usuarios SET rol = ? WHERE id_usuario = ?",
                (rol_nuevo, id_usuario),
            )
            dlg.destroy()
            if result is not None:
                logger.info("Rol de usuario %d cambiado a '%s'.", id_usuario, rol_nuevo)
                messagebox.showinfo("Éxito", f"Rol de {nombre} actualizado a '{rol_nuevo}'.")
                self._cargar_usuarios()
            else:
                messagebox.showerror("Error", MENSAJES["error_bd"])

        btn_frame = tk.Frame(dlg, bg=self.theme["panel"])
        btn_frame.pack(pady=12)

        tk.Button(
            btn_frame,
            text="Confirmar",
            command=_confirmar,
            bg=self.theme["accent"],
            fg="#FFFFFF",
            activebackground=self.theme["accent_soft"],
            relief=tk.FLAT,
            padx=12,
            pady=7,
            font=(self.fonts["body"], 12, "bold"),
            cursor="hand2",
        ).pack(side=tk.LEFT, padx=8)

        tk.Button(
            btn_frame,
            text="Cancelar",
            command=dlg.destroy,
            bg=self.theme["panel_soft"],
            fg=self.theme["muted"],
            relief=tk.FLAT,
            padx=12,
            pady=7,
            font=(self.fonts["body"], 12),
            cursor="hand2",
        ).pack(side=tk.LEFT)

    # ------------------------------------------------------------------
    # Pestaña Logs de auditoría
    # ------------------------------------------------------------------

    def _construir_tab_logs(self, parent: Any) -> ctk.CTkFrame:
        """
        Construye la pestaña de logs de auditoría.

        Si la tabla auditoria.consultas no existe (database_patch.sql no fue
        ejecutado), la carga mostrará un mensaje explicativo sin errores.
        """
        frame = ctk.CTkFrame(parent, fg_color=self.theme["bg"], corner_radius=0)

        actions = ctk.CTkFrame(frame, fg_color=self.theme["bg"], corner_radius=0)
        actions.pack(fill=tk.X, padx=40, pady=(0, 12))

        self._lbl_est_logs = ctk.CTkLabel(
            actions,
            text="",
            fg_color="transparent",
            text_color=self.theme.get("body_text", "#CBD5E1"),
            font=(self.fonts["body"], 12),
        )
        self._lbl_est_logs.pack(side=tk.LEFT)

        self._mk_refresh_button(actions, self._cargar_logs, "Recargar").pack(side=tk.RIGHT)

        tabla_frame = ctk.CTkFrame(
            frame,
            fg_color=self.theme["panel"],
            border_width=1,
            border_color=self.theme.get("glass_border", self.theme["border"]),
            corner_radius=16,
        )
        tabla_frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=(0, 40))

        self._tree_logs = self._mk_treeview(tabla_frame, [
            ("fecha",     "Fecha/Hora",  150),
            ("usuario",   "Usuario",     170),
            ("pregunta",  "Pregunta",    300),
            ("resultado", "Resultado",    90),
        ])
        self._cargar_logs()
        return frame

    def _cargar_logs(self) -> None:
        """
        Carga los últimos 100 registros de auditoria.consultas.

        Si la tabla no existe, devuelve lista vacía y muestra un mensaje
        pidiendo ejecutar database_patch.sql, sin lanzar errores a la UI.
        """
        if self._lbl_est_logs:
            self._lbl_est_logs.configure(text="Cargando...", text_color=self.theme["muted"])

        def _fetch():
            if self.db is None:
                return None
            try:
                return self.db.ejecutar_consulta(
                    "SELECT TOP 100 "
                    "CONVERT(VARCHAR(16), fecha_hora, 120), "
                    "nombre_usuario, "
                    "LEFT(pregunta, 80), "
                    "resultado "
                    "FROM auditoria.consultas "
                    "ORDER BY fecha_hora DESC"
                )
            except Exception:
                return []

        def _aplicar(filas) -> None:
            if not self._tree_logs or not self._lbl_est_logs:
                return
            self._limpiar_tree(self._tree_logs)
            if filas is None:
                self._mostrar_estado(self._lbl_est_logs, MENSAJES["error_bd"], ok=False)
                return
            if not filas:
                self._lbl_est_logs.configure(
                    text="Sin registros de auditoría aún.",
                    text_color=self.theme["muted"],
                )
                return
            for i, fila in enumerate(filas):
                self._insertar_fila(self._tree_logs, fila, i)
            self._lbl_est_logs.configure(
                text=f"{len(filas)} registro(s)", text_color=self.theme["muted"])

        self._async(_fetch, _aplicar)
