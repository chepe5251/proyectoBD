# -*- coding: utf-8 -*-
"""
Modulo: features.py
Descripcion: Paneles de funcionalidades adicionales para la Biblioteca Inteligente.

Contiene cuatro paneles independientes de Tkinter que se integran con la
navegacion de pestanas de main.py:

    DashboardPanel  — Metricas visuales del sistema (tarjetas + tabla top libros).
    BusquedaPanel   — Busqueda directa sin IA usando filtros clasicos.
    AyudaPanel      — Guia contextual adaptada al rol del usuario.
    AdminPanel      — Gestion de usuarios y logs de auditoria (solo admin).

Cada panel extiende _PanelBase, que provee:
    - Acceso al theme, fonts, db y seguridad de la sesion actual.
    - Ejecucion asincrona de consultas SQL (nunca bloquea la UI).
    - Utilidades para crear widgets con estilo consistente con el tema oscuro.
    - Tabla ttk.Treeview con estilo oscuro configurado una sola vez por sesion.

Mensajes de error:
    El dict MENSAJES centraliza todos los textos de error para el usuario final.
    Ningun panel muestra mensajes tecnicos (stack traces, SQL errors). Los errores
    tecnicos se registran en el logger del modulo para diagnostico interno.

Dependencias:
    - tkinter / ttk  (stdlib)
    - database_manager.DatabaseManager
    - seguridad.SecurityManager
    - No importa main.py ni chat_controller (desacoplado de presentacion).
"""

from __future__ import annotations

import logging
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Mensajes de error para el usuario final
# Los mensajes tecnicos van al logger; estos se muestran en la UI.
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
# Configuracion de estilo oscuro para ttk.Treeview
# Se llama una sola vez al construir el primer panel que use Treeview.
# ---------------------------------------------------------------------------
_estilo_configurado = False


def _configurar_estilo_treeview(theme: dict, fonts: dict) -> None:
    """
    Aplica el tema oscuro al widget ttk.Treeview de forma global.

    Debe llamarse antes de instanciar cualquier Treeview. Idempotente:
    ejecutar mas de una vez no tiene efecto secundario gracias al flag modular.

    Args:
        theme: Diccionario de colores del tema de la aplicacion.
        fonts: Diccionario de familias tipograficas de la aplicacion.
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

    style.configure(
        "Dark.Treeview",
        background=theme["panel_soft"],
        foreground=theme["text"],
        fieldbackground=theme["panel_soft"],
        rowheight=26,
        font=(fonts["body"], 10),
    )
    style.configure(
        "Dark.Treeview.Heading",
        background=theme["panel"],
        foreground=theme["accent"],
        font=(fonts["body"], 9, "bold"),
        relief="flat",
    )
    style.map(
        "Dark.Treeview",
        background=[("selected", theme["accent"])],
        foreground=[("selected", "#042f2e")],
    )
    style.configure(
        "Dark.Vertical.TScrollbar",
        background=theme["panel_soft"],
        troughcolor=theme["panel"],
        arrowcolor=theme["muted"],
    )


# ---------------------------------------------------------------------------
# Clase base compartida por todos los paneles
# ---------------------------------------------------------------------------


class _PanelBase(tk.Frame):
    """
    Frame base para todos los paneles de funcionalidades.

    Centraliza:
    - Acceso compartido a theme, fonts, db y seguridad.
    - Ejecucion asincrona: _async(fn, callback) corre fn en un hilo secundario
      y llama callback(result) en el hilo principal de Tkinter.
    - Helpers para crear widgets con estilo uniforme (_mk_label, _mk_button,
      _mk_treeview, _limpiar_tree, _mostrar_estado).
    """

    def __init__(
        self,
        parent: tk.Widget,
        theme: dict,
        fonts: dict,
        db: Any,
        seguridad: Any,
    ) -> None:
        super().__init__(parent, bg=theme["bg"])
        self.theme = theme
        self.fonts = fonts
        self.db = db
        self.seguridad = seguridad
        _configurar_estilo_treeview(theme, fonts)

    # ------------------------------------------------------------------
    # Ejecucion asincrona
    # ------------------------------------------------------------------

    def _async(self, fn: Callable, callback: Callable) -> None:
        """
        Ejecuta fn() en un hilo secundario y llama callback(resultado) en el
        hilo principal de Tkinter mediante self.after().

        Si fn() lanza una excepcion, se registra en el logger y callback
        recibe None para que el panel muestre un mensaje de error amigable.

        Args:
            fn:       Callable sin argumentos que realiza el trabajo pesado (ej: consulta SQL).
            callback: Callable(resultado) que actualiza la UI con el resultado.
        """
        def _run() -> None:
            try:
                result = fn()
            except Exception as exc:
                logger.error("Error en operacion async [%s]: %s", self.__class__.__name__, exc)
                result = None
            self.after(0, callback, result)

        threading.Thread(target=_run, daemon=True).start()

    # ------------------------------------------------------------------
    # Helpers de creacion de widgets con estilo consistente
    # ------------------------------------------------------------------

    def _mk_button(
        self,
        parent: tk.Widget,
        texto: str,
        command: Callable,
        color: str | None = None,
        fg: str = "#042f2e",
    ) -> tk.Button:
        """Crea un boton con el estilo del tema de la aplicacion."""
        c = color or self.theme["accent"]
        return tk.Button(
            parent,
            text=texto,
            command=command,
            bg=c,
            fg=fg,
            activebackground="#2dd4bf",
            activeforeground="#022c22",
            relief=tk.FLAT,
            padx=12,
            pady=7,
            font=(self.fonts["body"], 9, "bold"),
            cursor="hand2",
        )

    def _mk_treeview(
        self,
        parent: tk.Widget,
        columnas: list[tuple[str, str, int]],
    ) -> ttk.Treeview:
        """
        Crea un ttk.Treeview con tema oscuro, columnas configuradas y scrollbar.

        El widget se empaqueta automaticamente expandiendose para llenar el parent.

        Args:
            parent:   Widget contenedor donde se empaquetara el Treeview.
            columnas: Lista de (id_columna, titulo_columna, ancho_px).

        Returns:
            El widget Treeview (sin el contenedor, que se gestiona internamente).
        """
        container = tk.Frame(parent, bg=self.theme["bg"])
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
        # Zebra striping: filas pares ligeramente más claras
        tree.tag_configure("fila_par",   background=self.theme["panel_soft"])
        tree.tag_configure("fila_impar", background="#162032")
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        tree.pack(fill=tk.BOTH, expand=True)
        return tree

    def _limpiar_tree(self, tree: ttk.Treeview) -> None:
        """Elimina todas las filas del Treeview."""
        for item in tree.get_children():
            tree.delete(item)

    def _insertar_fila(self, tree: ttk.Treeview, valores: tuple, indice: int) -> None:
        """Inserta una fila con zebra striping (filas alternas en tonos distintos)."""
        tag = "fila_par" if indice % 2 == 0 else "fila_impar"
        tree.insert("", tk.END, values=valores, tags=(tag,))

    def _mostrar_estado(self, label: tk.Label, texto: str, ok: bool = True) -> None:
        """Actualiza un label de estado con color segun si es exito o error."""
        color = self.theme["ok"] if ok else self.theme["error"]
        label.config(text=texto, fg=color)


# ---------------------------------------------------------------------------
# Panel 1: Dashboard de metricas
# ---------------------------------------------------------------------------


class DashboardPanel(_PanelBase):
    """
    Panel de metricas visuales del sistema.

    Muestra cuatro tarjetas con conteos clave (libros, prestamos activos,
    prestamos vencidos, usuarios) y una tabla con los 5 libros mas prestados.
    Los datos se cargan de forma asincrona al construirse el panel y con
    el boton 'Actualizar'.

    Accesible para todos los roles: solo muestra datos agregados.
    """

    # Consultas para cada tarjeta. El rol del login de SQL Server aplica sus
    # propios permisos; si una tabla no es accesible devolvera None.
    _SQL_STATS: list[tuple[str, str]] = [
        ("total_libros",      "SELECT COUNT(*) FROM catalogo.libros"),
        ("prestamos_activos", "SELECT COUNT(*) FROM operaciones.vista_prestamos_activos"),
        ("prestamos_vencidos","SELECT COUNT(*) FROM operaciones.vista_prestamos_vencidos"),
        ("total_usuarios",    "SELECT COUNT(*) FROM personas.usuarios"),
    ]

    _SQL_TOP_LIBROS = """
        SELECT TOP 5
            l.titulo,
            COUNT(p.id_libro) AS veces_prestado
        FROM operaciones.prestamos p
        JOIN catalogo.libros l ON p.id_libro = l.id_libro
        GROUP BY l.titulo
        ORDER BY veces_prestado DESC
    """

    def __init__(self, parent: tk.Widget, theme: dict, fonts: dict, db: Any, seguridad: Any) -> None:
        super().__init__(parent, theme, fonts, db, seguridad)
        self._cards: dict[str, tk.Frame] = {}
        self._tree: ttk.Treeview | None = None
        self._lbl_estado: tk.Label | None = None
        self._construir()

    def _construir(self) -> None:
        """Construye la estructura visual del dashboard."""
        # --- Cabecera ---
        cabecera = tk.Frame(self, bg=self.theme["bg"], pady=16, padx=20)
        cabecera.pack(fill=tk.X)

        tk.Label(
            cabecera, text="📊 Dashboard",
            bg=self.theme["bg"], fg=self.theme["accent"],
            font=(self.fonts["title"], 16, "bold"),
        ).pack(side=tk.LEFT)

        self._lbl_estado = tk.Label(
            cabecera, text="",
            bg=self.theme["bg"], fg=self.theme["muted"],
            font=(self.fonts["body"], 9),
        )
        self._lbl_estado.pack(side=tk.LEFT, padx=14)

        self._mk_button(cabecera, "⟳ Actualizar", self.cargar_datos).pack(side=tk.RIGHT)

        # --- Tarjetas de metricas ---
        cards_frame = tk.Frame(self, bg=self.theme["bg"], padx=20, pady=8)
        cards_frame.pack(fill=tk.X)

        definiciones_cards = [
            ("total_libros",      "📚  Total Libros",      self.theme["accent"]),
            ("prestamos_activos", "📋  Prestamos Activos", self.theme["ok"]),
            ("prestamos_vencidos","⚠   Vencidos",          self.theme["warn"]),
            ("total_usuarios",    "👥  Usuarios",           "#6366f1"),
        ]
        for i, (key, titulo, color) in enumerate(definiciones_cards):
            card = self._mk_card(cards_frame, titulo, color)
            card.grid(row=0, column=i, padx=8, pady=4, sticky="nsew")
            cards_frame.columnconfigure(i, weight=1)
            self._cards[key] = card

        # --- Tabla de libros mas prestados ---
        tabla_frame = tk.Frame(
            self, bg=self.theme["panel"],
            padx=20, pady=16,
            highlightthickness=1,
            highlightbackground=self.theme["border"],
        )
        tabla_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 20))

        tk.Label(
            tabla_frame, text="Top 5 — Libros más prestados",
            bg=self.theme["panel"], fg=self.theme["accent"],
            font=(self.fonts["body"], 11, "bold"),
        ).pack(anchor="w", pady=(0, 2))
        tk.Label(
            tabla_frame, text="Ranking histórico por número de préstamos registrados",
            bg=self.theme["panel"], fg=self.theme["muted"],
            font=(self.fonts["body"], 9),
        ).pack(anchor="w", pady=(0, 8))

        self._tree = self._mk_treeview(tabla_frame, [
            ("titulo", "Titulo",         500),
            ("veces",  "Veces prestado", 140),
        ])

        self.cargar_datos()

    def _mk_card(self, parent: tk.Widget, titulo: str, color: str) -> tk.Frame:
        """
        Crea una tarjeta visual de metrica con numero grande y etiqueta.

        El Label del numero se accede via card._lbl_num para actualizarlo
        cuando llegan los datos de la BD.
        """
        card = tk.Frame(
            parent,
            bg=self.theme["panel_soft"],
            highlightthickness=2,
            highlightbackground=color,
            padx=16, pady=14,
        )
        lbl_num = tk.Label(
            card, text="—",
            bg=self.theme["panel_soft"], fg=color,
            font=(self.fonts["title"], 30, "bold"),
        )
        lbl_num.pack()
        tk.Label(
            card, text=titulo,
            bg=self.theme["panel_soft"], fg=self.theme["muted"],
            font=(self.fonts["body"], 9),
        ).pack(pady=(4, 0))
        card._lbl_num = lbl_num  # type: ignore[attr-defined]
        return card

    def cargar_datos(self) -> None:
        """
        Carga todas las metricas del dashboard desde la BD de forma asincrona.

        Actualiza las tarjetas y la tabla cuando los datos llegan. Si ocurre
        un error, muestra un mensaje de estado sin lanzar excepciones.
        """
        if self._lbl_estado:
            self._lbl_estado.config(text="Cargando...", fg=self.theme["muted"])

        def _fetch() -> dict | None:
            if self.db is None:
                return None
            resultado: dict = {}
            for key, sql in self._SQL_STATS:
                filas = self.db.ejecutar_consulta(sql)
                resultado[key] = str(filas[0][0]) if filas and filas[0] else "?"
            resultado["top_libros"] = self.db.ejecutar_consulta(self._SQL_TOP_LIBROS) or []
            return resultado

        def _aplicar(datos: dict | None) -> None:
            if datos is None:
                if self._lbl_estado:
                    self._mostrar_estado(self._lbl_estado, MENSAJES["error_bd"], ok=False)
                return
            for key, card in self._cards.items():
                card._lbl_num.config(text=datos.get(key, "?"))  # type: ignore[attr-defined]
            # Colorear vencidos en rojo si hay alguno, amarillo si hay cero
            if "prestamos_vencidos" in self._cards:
                try:
                    n = int(datos.get("prestamos_vencidos", "0"))
                    color_v = self.theme["error"] if n > 0 else self.theme["warn"]
                    self._cards["prestamos_vencidos"]._lbl_num.config(fg=color_v)  # type: ignore[attr-defined]
                    self._cards["prestamos_vencidos"].config(highlightbackground=color_v)
                except (ValueError, AttributeError):
                    pass
            if self._tree:
                self._limpiar_tree(self._tree)
                for i, fila in enumerate(datos.get("top_libros", [])):
                    self._insertar_fila(self._tree, (fila[0], fila[1]), i)
            if self._lbl_estado:
                self._mostrar_estado(self._lbl_estado, "Datos actualizados", ok=True)

        self._async(_fetch, _aplicar)


# ---------------------------------------------------------------------------
# Panel 2: Busqueda directa sin IA
# ---------------------------------------------------------------------------


class BusquedaPanel(_PanelBase):
    """
    Panel de busqueda con filtros clasicos, sin pasar por la IA.

    Permite buscar libros por titulo, por autor, filtrar por categoria
    o ver solo los libros disponibles (no prestados actualmente).
    Las consultas son SQL parametrizado directo, sin Gemini.

    Compatible con todos los roles; el login de SQL Server aplica permisos.

    Args:
        on_usar_en_chat: Callback opcional. Si se proporciona, aparece un boton
                         en la barra de resultados para enviar la pregunta al chat.
    """

    def __init__(
        self,
        parent: tk.Widget,
        theme: dict,
        fonts: dict,
        db: Any,
        seguridad: Any,
        on_usar_en_chat: Callable | None = None,
    ) -> None:
        super().__init__(parent, theme, fonts, db, seguridad)
        self._modo = tk.StringVar(value="titulo")
        self._tree: ttk.Treeview | None = None
        self._lbl_resultado: tk.Label | None = None
        self._input_area: tk.Frame | None = None
        self._ent_actual: tk.Entry | None = None
        self._cb_categoria: ttk.Combobox | None = None
        self._categorias: list[str] = []
        self._mode_buttons: dict[str, tk.Button] = {}
        self._ent_placeholder: str = ""
        self.on_usar_en_chat = on_usar_en_chat
        self._construir()
        self._cargar_categorias()

    def _construir(self) -> None:
        """Construye la estructura visual del panel de busqueda."""
        # --- Cabecera ---
        cabecera = tk.Frame(self, bg=self.theme["bg"], pady=16, padx=20)
        cabecera.pack(fill=tk.X)
        tk.Label(
            cabecera, text="🔍 Busqueda Directa",
            bg=self.theme["bg"], fg=self.theme["accent"],
            font=(self.fonts["title"], 16, "bold"),
        ).pack(side=tk.LEFT)
        tk.Label(
            cabecera, text="Sin IA — Filtros clásicos directos",
            bg=self.theme["bg"], fg=self.theme["muted"],
            font=(self.fonts["body"], 9),
        ).pack(side=tk.LEFT, padx=12)

        # --- Selectores de modo (botones tipo toggle) ---
        modos_frame = tk.Frame(self, bg=self.theme["bg"], padx=20, pady=6)
        modos_frame.pack(fill=tk.X)
        modos = [
            ("titulo",      "Por título"),
            ("autor",       "Por autor"),
            ("categoria",   "Por categoría"),
            ("disponibles", "Disponibles"),
        ]
        for key, label in modos:
            btn = tk.Button(
                modos_frame, text=label,
                command=lambda k=key: self._on_modo_cambio(k),
                bg=self.theme["panel_soft"], fg=self.theme["muted"],
                activebackground=self.theme["accent_soft"], activeforeground="#ecfeff",
                relief=tk.FLAT, padx=12, pady=5,
                font=(self.fonts["body"], 9, "bold"),
                cursor="hand2",
            )
            btn.pack(side=tk.LEFT, padx=(0, 4))
            self._mode_buttons[key] = btn
        self._actualizar_modo_botones("titulo")

        # --- Area de entrada (se reconstruye al cambiar de modo) ---
        self._input_area = tk.Frame(self, bg=self.theme["bg"], padx=20, pady=8)
        self._input_area.pack(fill=tk.X)
        self._construir_input_titulo()

        # --- Estado / resultado ---
        self._lbl_resultado = tk.Label(
            self, text="",
            bg=self.theme["bg"], fg=self.theme["muted"],
            font=(self.fonts["body"], 9),
        )
        self._lbl_resultado.pack(anchor="w", padx=20, pady=(0, 4))

        # --- Tabla de resultados ---
        tabla_frame = tk.Frame(
            self, bg=self.theme["panel"], padx=16, pady=12,
            highlightthickness=1, highlightbackground=self.theme["border"],
        )
        tabla_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 20))

        self._tree = self._mk_treeview(tabla_frame, [
            ("titulo",    "Titulo",    300),
            ("autor",     "Autor",     220),
            ("categoria", "Categoria", 140),
            ("ano",       "Año",        60),
        ])

    def _limpiar_input_area(self) -> None:
        """Destruye los widgets del area de entrada para reconstruirla."""
        if self._input_area:
            for w in self._input_area.winfo_children():
                w.destroy()
        self._ent_actual = None
        self._cb_categoria = None

    def _construir_input_titulo(self) -> None:
        """Input de texto para búsqueda por título o autor, con placeholder."""
        assert self._input_area
        modo_actual = self._modo.get()
        placeholder = "Buscar por título..." if modo_actual == "titulo" else "Buscar por autor..."
        self._ent_placeholder = placeholder

        box = tk.Frame(
            self._input_area, bg=self.theme["input_bg"],
            highlightthickness=1, highlightbackground=self.theme["border"],
        )
        box.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ent = tk.Entry(
            box, bg=self.theme["input_bg"], fg=self.theme["muted"],
            insertbackground=self.theme["text"],
            relief=tk.FLAT, bd=0, font=(self.fonts["body"], 11),
        )
        ent.insert(0, placeholder)
        ent.pack(fill=tk.X, padx=10, ipady=10)

        def _focus_in(_e):
            if ent.get() == self._ent_placeholder:
                ent.delete(0, tk.END)
                ent.config(fg=self.theme["text"])

        def _focus_out(_e):
            if not ent.get().strip():
                ent.insert(0, self._ent_placeholder)
                ent.config(fg=self.theme["muted"])

        ent.bind("<FocusIn>", _focus_in)
        ent.bind("<FocusOut>", _focus_out)
        ent.bind("<Return>", lambda _: self.buscar())
        ent.focus_set()
        self._ent_actual = ent
        self._mk_button(self._input_area, "Buscar", self.buscar).pack(
            side=tk.LEFT, padx=(8, 0))

    def _construir_input_categoria(self) -> None:
        """Combobox para seleccionar categoria."""
        assert self._input_area
        cb = ttk.Combobox(
            self._input_area,
            state="readonly",
            font=(self.fonts["body"], 10),
            width=32,
            values=self._categorias,
        )
        if self._categorias:
            cb.current(0)
        cb.pack(side=tk.LEFT)
        self._cb_categoria = cb
        self._mk_button(self._input_area, "Buscar", self.buscar).pack(
            side=tk.LEFT, padx=(8, 0))

    def _construir_input_disponibles(self) -> None:
        """Sin input: solo el boton para listar disponibles."""
        assert self._input_area
        tk.Label(
            self._input_area,
            text="Mostrará todos los libros no prestados actualmente.",
            bg=self.theme["bg"], fg=self.theme["muted"],
            font=(self.fonts["body"], 10),
        ).pack(side=tk.LEFT)
        self._mk_button(self._input_area, "Buscar disponibles", self.buscar).pack(
            side=tk.LEFT, padx=(12, 0))

    def _actualizar_modo_botones(self, modo_activo: str) -> None:
        """Resalta el botón del modo activo y apaga los demás."""
        for key, btn in self._mode_buttons.items():
            if key == modo_activo:
                btn.config(bg=self.theme["accent"], fg="#042f2e")
            else:
                btn.config(bg=self.theme["panel_soft"], fg=self.theme["muted"])

    def _on_modo_cambio(self, nuevo_modo: str) -> None:
        """Reconstruye el area de entrada segun el modo seleccionado."""
        self._modo.set(nuevo_modo)
        self._actualizar_modo_botones(nuevo_modo)
        self._limpiar_input_area()
        if self._lbl_resultado:
            self._lbl_resultado.config(text="")
        if self._tree:
            self._limpiar_tree(self._tree)

        if nuevo_modo in ("titulo", "autor"):
            self._construir_input_titulo()
        elif nuevo_modo == "categoria":
            self._construir_input_categoria()
        elif nuevo_modo == "disponibles":
            self._construir_input_disponibles()

    def _cargar_categorias(self) -> None:
        """Carga la lista de categorias desde la BD para el combobox."""
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
        Ejecuta la busqueda segun el modo activo y actualiza la tabla de resultados.

        Las consultas son SQL parametrizado (sin construccion de cadenas con datos
        del usuario), lo que elimina el riesgo de SQL injection en este panel.
        """
        if self._lbl_resultado:
            self._lbl_resultado.config(text="Buscando...", fg=self.theme["muted"])
        if self._tree:
            self._limpiar_tree(self._tree)

        modo = self._modo.get()

        # Capturar el termino ANTES del hilo para no acceder a widgets desde otro hilo
        termino = ""
        if modo in ("titulo", "autor") and self._ent_actual:
            raw = self._ent_actual.get().strip()
            # Ignorar si el campo tiene el placeholder (texto de ayuda vacío)
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
                self._lbl_resultado.config(
                    text="Escribe un término para buscar.", fg=self.theme["warn"])
                return
            if filas is None:
                self._lbl_resultado.config(
                    text=MENSAJES["error_bd"], fg=self.theme["error"])
                return
            if not filas:
                self._lbl_resultado.config(
                    text=MENSAJES["sin_resultados"], fg=self.theme["muted"])
                return
            for i, fila in enumerate(filas):
                self._insertar_fila(self._tree, fila, i)
            self._lbl_resultado.config(
                text=f"{len(filas)} resultado(s) encontrado(s).",
                fg=self.theme["ok"],
            )

        self._async(_fetch, _aplicar)


# ---------------------------------------------------------------------------
# Panel 3: Ayuda guiada por rol
# ---------------------------------------------------------------------------


class AyudaPanel(_PanelBase):
    """
    Panel de ayuda contextual adaptado al rol del usuario activo.

    Contiene:
    - Como usar el chat de lenguaje natural.
    - Ejemplos de preguntas especificos para el rol.
    - Operaciones disponibles segun el rol.
    - Consejos para obtener mejores resultados.

    Los botones de ejemplo invocan on_enviar_al_chat (si se provee) para
    enviar la pregunta directamente al campo de entrada del chat.

    Args:
        on_enviar_al_chat: Callback opcional con firma fn(pregunta: str).
    """

    _EJEMPLOS: dict[str, list[str]] = {
        "usuario": [
            "Cuantos libros hay registrados?",
            "Libros de tecnologia",
            "Lista de autores",
            "Libros disponibles",
            'Buscar libro "1984"',
            "Cuales son los prestamos vencidos?",
        ],
        "operativo": [
            "Cuantos libros hay registrados?",
            "Prestamos activos",
            "Prestamos vencidos",
            "Registrar prestamo para usuario 3, libro 5",
            "Devolver prestamo con ID 2",
            "Lista de autores",
        ],
        "admin": [
            "Cuantos libros hay registrados?",
            "Prestamos activos",
            "Registrar nuevo libro",
            "Prestamos vencidos",
            "Registrar un nuevo usuario",
            "Lista de usuarios del sistema",
        ],
    }

    _OPERACIONES: dict[str, list[tuple[str, str]]] = {
        "usuario": [
            ("Consultar catalogo",  "Busca libros por titulo, autor o categoria"),
            ("Ver disponibilidad",  "Consulta libros que no estan prestados"),
            ("Ver estadisticas",    "Totales de libros, autores y categorias"),
            ("Buscar por autor",    "Todas las obras de un autor especifico"),
        ],
        "operativo": [
            ("Gestion de prestamos", "Registrar nuevos prestamos y devoluciones"),
            ("Consultas avanzadas",  "Prestamos activos y vencidos con detalle"),
            ("Buscar usuarios",      "Encontrar usuarios por nombre o correo"),
            ("Ver catalogo",         "Informacion completa de todos los libros"),
        ],
        "admin": [
            ("Gestion completa",     "Acceso total al sistema"),
            ("Administrar usuarios", "Crear y gestionar cuentas, cambiar roles"),
            ("Ver logs",             "Auditoria de todas las consultas realizadas"),
            ("Estadisticas",         "Dashboard con metricas del sistema"),
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
        parent: tk.Widget,
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
        """Construye el panel de ayuda con scroll."""
        rol = (self.seguridad.usuario_actual or {}).get("rol", "usuario")

        # Canvas con scroll para todo el contenido
        canvas = tk.Canvas(self, bg=self.theme["bg"], highlightthickness=0)
        vsb = ttk.Scrollbar(self, orient="vertical", command=canvas.yview,
                            style="Dark.Vertical.TScrollbar")
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(fill=tk.BOTH, expand=True)

        contenido = tk.Frame(canvas, bg=self.theme["bg"])
        frame_id = canvas.create_window((0, 0), window=contenido, anchor="nw")

        contenido.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
            lambda e: canvas.itemconfig(frame_id, width=e.width))
        canvas.bind("<MouseWheel>",
            lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))

        px = 24

        # Titulo
        tk.Label(
            contenido, text="💡 Ayuda y Ejemplos",
            bg=self.theme["bg"], fg=self.theme["accent"],
            font=(self.fonts["title"], 16, "bold"),
        ).pack(anchor="w", padx=px, pady=(20, 2))
        tk.Label(
            contenido, text=f"Guia personalizada para tu rol: {rol.upper()}",
            bg=self.theme["bg"], fg=self.theme["muted"],
            font=(self.fonts["body"], 10),
        ).pack(anchor="w", padx=px, pady=(0, 12))

        # Seccion: como usar el chat
        self._seccion_lista(contenido, "Cómo usar el chat", [
            "Escribe tu pregunta en el campo de texto del Chat y presiona Enter.",
            "El asistente interpreta tu pregunta, genera SQL y muestra el resultado.",
            "El SQL aparece en el panel derecho para total transparencia.",
            "El asistente puede pedir más información antes de ejecutar una acción.",
            "Usa los botones de consulta rápida para las preguntas más comunes.",
        ], px)

        # Seccion: ejemplos para este rol
        ejemplos = self._EJEMPLOS.get(rol, self._EJEMPLOS["usuario"])
        self._seccion_ejemplos(contenido, "Preguntas de ejemplo para tu rol", ejemplos, px)

        # Seccion: operaciones disponibles
        ops = self._OPERACIONES.get(rol, [])
        self._seccion_operaciones(contenido, "Que puedes hacer", ops, px)

        # Seccion: consejos
        self._seccion_lista(contenido, "Consejos para mejores resultados", self._TIPS, px)

        # Espacio al final
        tk.Frame(contenido, bg=self.theme["bg"], height=30).pack()

    def _separador(self, parent: tk.Widget, px: int) -> None:
        tk.Frame(parent, bg=self.theme["border"], height=1).pack(
            fill=tk.X, padx=px, pady=(12, 6))

    def _titulo_seccion(self, parent: tk.Widget, texto: str, px: int) -> None:
        tk.Label(
            parent, text=texto,
            bg=self.theme["bg"], fg=self.theme["text"],
            font=(self.fonts["body"], 11, "bold"),
        ).pack(anchor="w", padx=px, pady=(0, 8))

    def _seccion_lista(self, parent: tk.Widget, titulo: str, items: list[str], px: int) -> None:
        self._separador(parent, px)
        self._titulo_seccion(parent, titulo, px)
        for item in items:
            tk.Label(
                parent, text=f"  •  {item}",
                bg=self.theme["bg"], fg=self.theme["muted"],
                font=(self.fonts["body"], 10),
                justify="left", wraplength=720, anchor="w",
            ).pack(anchor="w", padx=px, pady=2)

    def _seccion_ejemplos(
        self, parent: tk.Widget, titulo: str, ejemplos: list[str], px: int
    ) -> None:
        self._separador(parent, px)
        self._titulo_seccion(parent, titulo, px)
        grid = tk.Frame(parent, bg=self.theme["bg"])
        grid.pack(anchor="w", padx=px, pady=(0, 8))
        for i, ejemplo in enumerate(ejemplos):
            btn = tk.Button(
                grid, text=ejemplo,
                command=lambda e=ejemplo: self._usar_ejemplo(e),
                bg=self.theme["panel_soft"], fg=self.theme["text"],
                activebackground=self.theme["accent"], activeforeground="#042f2e",
                relief=tk.FLAT, padx=12, pady=6,
                font=(self.fonts["body"], 9),
                cursor="hand2", anchor="w", justify="left", wraplength=340,
            )
            row, col = divmod(i, 2)
            btn.grid(row=row, column=col, padx=4, pady=4, sticky="w")

    def _seccion_operaciones(
        self, parent: tk.Widget, titulo: str, ops: list[tuple[str, str]], px: int
    ) -> None:
        if not ops:
            return
        self._separador(parent, px)
        self._titulo_seccion(parent, titulo, px)
        for op, desc in ops:
            row = tk.Frame(
                parent, bg=self.theme["panel_soft"],
                highlightthickness=1, highlightbackground=self.theme["border"],
            )
            row.pack(fill=tk.X, padx=px, pady=3)
            tk.Label(
                row, text=op, bg=self.theme["panel_soft"], fg=self.theme["accent"],
                font=(self.fonts["body"], 10, "bold"), width=24, anchor="w",
            ).pack(side=tk.LEFT, padx=12, pady=8)
            tk.Label(
                row, text=desc, bg=self.theme["panel_soft"], fg=self.theme["muted"],
                font=(self.fonts["body"], 10),
            ).pack(side=tk.LEFT, padx=4)

    def _usar_ejemplo(self, texto: str) -> None:
        """Envia el ejemplo al chat si el callback fue registrado."""
        if self.on_enviar_al_chat:
            self.on_enviar_al_chat(texto)


# ---------------------------------------------------------------------------
# Panel 4: Administracion (solo admin)
# ---------------------------------------------------------------------------


class AdminPanel(_PanelBase):
    """
    Panel de administracion del sistema. Solo accesible para rol 'admin'.

    Funcionalidades:
    - Pestana Usuarios: lista todos los usuarios con id, nombre, correo y rol.
      Permite cambiar el rol de cualquier usuario via dialogo de confirmacion.
      Valida el permiso 'admin' tanto en la UI como antes de ejecutar el UPDATE.
    - Pestana Logs: muestra los ultimos 100 registros de auditoria.consultas.
      Si la tabla no existe (database_patch.sql no ejecutado), muestra un
      mensaje explicativo sin lanzar errores.

    El rol se verifica al construir el panel: si no es 'admin', se muestra
    solo un mensaje de acceso restringido, sin construir ninguna funcionalidad.
    """

    _ROLES_DISPONIBLES = ["admin", "operativo", "usuario"]

    def __init__(self, parent: tk.Widget, theme: dict, fonts: dict, db: Any, seguridad: Any) -> None:
        super().__init__(parent, theme, fonts, db, seguridad)
        self._tree_usuarios: ttk.Treeview | None = None
        self._tree_logs: ttk.Treeview | None = None
        self._lbl_est_usuarios: tk.Label | None = None
        self._lbl_est_logs: tk.Label | None = None
        self._tab_botones: dict[str, tk.Button] = {}
        self._panel_usuarios: tk.Frame | None = None
        self._panel_logs: tk.Frame | None = None
        self._construir()

    def _construir(self) -> None:
        """Verifica permisos y construye el panel si el usuario es admin."""
        rol = (self.seguridad.usuario_actual or {}).get("rol", "")
        if rol != "admin":
            # Mostrar solo un mensaje de acceso restringido, sin funcionalidad
            tk.Label(
                self,
                text="⛔  Acceso restringido a administradores.",
                bg=self.theme["bg"], fg=self.theme["error"],
                font=(self.fonts["body"], 13),
            ).pack(expand=True)
            return

        # --- Cabecera ---
        cabecera = tk.Frame(self, bg=self.theme["bg"], pady=16, padx=20)
        cabecera.pack(fill=tk.X)
        tk.Label(
            cabecera, text="⚙  Panel de Administración",
            bg=self.theme["bg"], fg=self.theme["accent"],
            font=(self.fonts["title"], 16, "bold"),
        ).pack(side=tk.LEFT)

        # --- Barra de pestanas ---
        tab_bar = tk.Frame(self, bg=self.theme["bg"], padx=20, pady=2)
        tab_bar.pack(fill=tk.X)
        for key, label in [("usuarios", "👥  Usuarios"), ("logs", "📋  Logs de Auditoria")]:
            btn = tk.Button(
                tab_bar, text=label,
                command=lambda k=key: self._cambiar_tab(k),
                bg=self.theme["panel_soft"], fg=self.theme["muted"],
                relief=tk.FLAT, padx=14, pady=7,
                font=(self.fonts["body"], 9, "bold"), cursor="hand2",
            )
            btn.pack(side=tk.LEFT, padx=(0, 4))
            self._tab_botones[key] = btn

        # --- Contenido de pestanas ---
        tab_content = tk.Frame(self, bg=self.theme["bg"])
        tab_content.pack(fill=tk.BOTH, expand=True)

        self._panel_usuarios = self._construir_tab_usuarios(tab_content)
        self._panel_logs = self._construir_tab_logs(tab_content)

        # Activar pestana de usuarios por defecto
        self._cambiar_tab("usuarios")

    def _cambiar_tab(self, tab: str) -> None:
        """Muestra la pestana solicitada y actualiza el estilo de los botones."""
        if self._panel_usuarios:
            self._panel_usuarios.pack_forget()
        if self._panel_logs:
            self._panel_logs.pack_forget()

        for key, btn in self._tab_botones.items():
            if key == tab:
                btn.config(bg=self.theme["accent"], fg="#042f2e")
            else:
                btn.config(bg=self.theme["panel_soft"], fg=self.theme["muted"])

        if tab == "usuarios" and self._panel_usuarios:
            self._panel_usuarios.pack(fill=tk.BOTH, expand=True)
        elif tab == "logs" and self._panel_logs:
            self._panel_logs.pack(fill=tk.BOTH, expand=True)

    # ------------------------------------------------------------------
    # Pestana Usuarios
    # ------------------------------------------------------------------

    def _construir_tab_usuarios(self, parent: tk.Widget) -> tk.Frame:
        """Construye la pestana de gestion de usuarios."""
        frame = tk.Frame(parent, bg=self.theme["bg"])

        # Barra de acciones
        actions = tk.Frame(frame, bg=self.theme["bg"], padx=20, pady=8)
        actions.pack(fill=tk.X)

        self._lbl_est_usuarios = tk.Label(
            actions, text="",
            bg=self.theme["bg"], fg=self.theme["muted"],
            font=(self.fonts["body"], 9),
        )
        self._lbl_est_usuarios.pack(side=tk.LEFT)

        self._mk_button(actions, "⟳ Recargar", self._cargar_usuarios).pack(
            side=tk.RIGHT, padx=(4, 0))
        self._mk_button(
            actions, "Cambiar Rol", self._cambiar_rol, color=self.theme["warn"], fg="#1a1a1a"
        ).pack(side=tk.RIGHT, padx=(4, 0))

        # Tabla
        tabla_frame = tk.Frame(
            frame, bg=self.theme["panel"], padx=16, pady=12,
            highlightthickness=1, highlightbackground=self.theme["border"],
        )
        tabla_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 16))

        self._tree_usuarios = self._mk_treeview(tabla_frame, [
            ("id",       "ID",       50),
            ("nombre",   "Nombre",  180),
            ("apellido", "Apellido",180),
            ("correo",   "Correo",  240),
            ("rol",      "Rol",      90),
        ])
        self._cargar_usuarios()
        return frame

    def _cargar_usuarios(self) -> None:
        """Carga la lista de usuarios desde la BD de forma asincrona."""
        if self._lbl_est_usuarios:
            self._lbl_est_usuarios.config(text="Cargando...", fg=self.theme["muted"])

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
            self._lbl_est_usuarios.config(
                text=f"{len(filas)} usuario(s)", fg=self.theme["muted"])

        self._async(_fetch, _aplicar)

    def _cambiar_rol(self) -> None:
        """
        Abre un dialogo para cambiar el rol del usuario seleccionado en la tabla.

        Valida el permiso de administrador tanto en la UI como en el backend
        antes de ejecutar el UPDATE para prevenir escalada de privilegios.
        """
        if not self._tree_usuarios:
            return
        sel = self._tree_usuarios.selection()
        if not sel:
            messagebox.showwarning("Seleccion requerida", "Selecciona un usuario de la lista.")
            return

        valores = self._tree_usuarios.item(sel[0])["values"]
        if not valores:
            return

        id_usuario = valores[0]
        nombre = f"{valores[1]} {valores[2]}"
        rol_actual = str(valores[4])

        # Dialogo modal de confirmacion
        dlg = tk.Toplevel(self)
        dlg.title("Cambiar Rol de Usuario")
        dlg.configure(bg=self.theme["panel"])
        dlg.geometry("380x240")
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.transient(self.winfo_toplevel())

        tk.Label(
            dlg, text=f"Usuario: {nombre}",
            bg=self.theme["panel"], fg=self.theme["text"],
            font=(self.fonts["body"], 11, "bold"),
        ).pack(pady=(20, 4))
        tk.Label(
            dlg, text=f"Rol actual: {rol_actual}",
            bg=self.theme["panel"], fg=self.theme["muted"],
            font=(self.fonts["body"], 10),
        ).pack(pady=(0, 12))

        nuevo_rol = tk.StringVar(value=rol_actual)
        for r in self._ROLES_DISPONIBLES:
            tk.Radiobutton(
                dlg, text=r.capitalize(), variable=nuevo_rol, value=r,
                bg=self.theme["panel"], fg=self.theme["text"],
                selectcolor=self.theme["panel_soft"],
                activebackground=self.theme["panel"],
                font=(self.fonts["body"], 10),
            ).pack()

        def _confirmar() -> None:
            rol_nuevo = nuevo_rol.get()
            if rol_nuevo == rol_actual:
                dlg.destroy()
                return
            # Validacion de permiso en backend: no confiar solo en la UI
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
                messagebox.showinfo("Exito", f"Rol de {nombre} actualizado a '{rol_nuevo}'.")
                self._cargar_usuarios()
            else:
                messagebox.showerror("Error", MENSAJES["error_bd"])

        btn_frame = tk.Frame(dlg, bg=self.theme["panel"])
        btn_frame.pack(pady=12)
        self._mk_button(btn_frame, "Confirmar", _confirmar).pack(side=tk.LEFT, padx=8)
        tk.Button(
            btn_frame, text="Cancelar", command=dlg.destroy,
            bg=self.theme["panel_soft"], fg=self.theme["muted"],
            relief=tk.FLAT, padx=12, pady=7,
            font=(self.fonts["body"], 9), cursor="hand2",
        ).pack(side=tk.LEFT)

    # ------------------------------------------------------------------
    # Pestana Logs de auditoria
    # ------------------------------------------------------------------

    def _construir_tab_logs(self, parent: tk.Widget) -> tk.Frame:
        """
        Construye la pestana de logs de auditoria.

        Si la tabla auditoria.consultas no existe (database_patch.sql no fue
        ejecutado), la carga mostrara un mensaje explicativo sin errores.
        """
        frame = tk.Frame(parent, bg=self.theme["bg"])

        actions = tk.Frame(frame, bg=self.theme["bg"], padx=20, pady=8)
        actions.pack(fill=tk.X)
        self._lbl_est_logs = tk.Label(
            actions, text="",
            bg=self.theme["bg"], fg=self.theme["muted"],
            font=(self.fonts["body"], 9),
        )
        self._lbl_est_logs.pack(side=tk.LEFT)
        self._mk_button(actions, "⟳ Recargar", self._cargar_logs).pack(side=tk.RIGHT)

        tabla_frame = tk.Frame(
            frame, bg=self.theme["panel"], padx=16, pady=12,
            highlightthickness=1, highlightbackground=self.theme["border"],
        )
        tabla_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 16))

        self._tree_logs = self._mk_treeview(tabla_frame, [
            ("fecha",    "Fecha/Hora",  150),
            ("usuario",  "Usuario",     170),
            ("pregunta", "Pregunta",    300),
            ("resultado","Resultado",    90),
        ])
        self._cargar_logs()
        return frame

    def _cargar_logs(self) -> None:
        """
        Carga los ultimos 100 registros de auditoria.consultas.

        Si la tabla no existe, devuelve lista vacia y muestra un mensaje
        pidiendo ejecutar database_patch.sql, sin lanzar errores a la UI.
        """
        if self._lbl_est_logs:
            self._lbl_est_logs.config(text="Cargando...", fg=self.theme["muted"])

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
                # La tabla aun no existe; tratar como lista vacia
                return []

        def _aplicar(filas) -> None:
            if not self._tree_logs or not self._lbl_est_logs:
                return
            self._limpiar_tree(self._tree_logs)
            if filas is None:
                self._mostrar_estado(self._lbl_est_logs, MENSAJES["error_bd"], ok=False)
                return
            if not filas:
                self._lbl_est_logs.config(
                    text="Sin registros de auditoría aún.",
                    fg=self.theme["muted"],
                )
                return
            for i, fila in enumerate(filas):
                self._insertar_fila(self._tree_logs, fila, i)
            self._lbl_est_logs.config(
                text=f"{len(filas)} registro(s)", fg=self.theme["muted"])

        self._async(_fetch, _aplicar)
