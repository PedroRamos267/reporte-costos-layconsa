"""
=============================================================
  SIMULADOR DE RECETA — Layconsa
  Usa la misma lógica de cálculo que reporte_costos_web.py
  Filtra df_exp por Código PT para evitar duplicados
=============================================================
"""

import pandas as pd
import os, io
from datetime import datetime
from dash import Dash, html, dcc, Input, Output, State, dash_table
import plotly.graph_objects as go

ARCHIVO_DATOS  = "Analisis de costos_PY.xlsx"
PREFIJO_FABRIC = "231"
PROCESOS_EXCLUIR = []

import sys
if not os.path.exists(ARCHIVO_DATOS):
    print(f"❌ ERROR: No se encontró {ARCHIVO_DATOS}"); sys.exit(1)

df_exp = pd.read_excel(ARCHIVO_DATOS, sheet_name="Explosión")
df_tie = pd.read_excel(ARCHIVO_DATOS, sheet_name="Tiempos")
df_cos = pd.read_excel(ARCHIVO_DATOS, sheet_name="Costos")
df_exp.columns = df_exp.columns.str.strip()
df_tie.columns = df_tie.columns.str.strip()
df_cos.columns = df_cos.columns.str.strip()

for col in ["Código PT","Código Semi","Componente","Familia"]:
    if col in df_exp.columns:
        df_exp[col] = df_exp[col].astype(str).str.strip()
df_tie["Código Semi"]        = df_tie["Código Semi"].astype(str).str.strip()
df_cos["Número de artículo"] = df_cos["Número de artículo"].astype(str).str.strip()

for col in ["Cantidad Total Requerida","Cantidad Base","Costo estandar"]:
    if col in df_exp.columns:
        df_exp[col] = pd.to_numeric(df_exp[col], errors="coerce").fillna(0)
for col in ["Cantidad Base","T.MO","T.Maq","Tarifa MO","Tarifa Maquina","Cant.Opr"]:
    if col in df_tie.columns:
        df_tie[col] = pd.to_numeric(df_tie[col], errors="coerce").fillna(0)
df_cos["Precio promedio"] = pd.to_numeric(df_cos["Precio promedio"], errors="coerce").fillna(0)

# ── Helpers ─────────────────────────────────────────────────
def es_fabricado(familia):
    return str(familia).strip().startswith(PREFIJO_FABRIC)

def get_tiempos(codigo, df_t):
    row = df_t[df_t["Código Semi"] == str(codigo)]
    return row.iloc[0] if not row.empty else None

def get_unidad(codigo):
    codigo = str(codigo).strip()
    row = df_cos[df_cos["Número de artículo"] == codigo]
    if not row.empty: return str(row.iloc[0]["UnidadMedida"])
    row = df_exp[df_exp["Componente"] == codigo]
    if not row.empty and "Unidad" in df_exp.columns: return str(row.iloc[0]["Unidad"])
    return "—"

def get_descripcion(codigo):
    codigo = str(codigo).strip()
    row = df_cos[df_cos["Número de artículo"] == codigo]
    if not row.empty: return str(row.iloc[0]["Descripción del artículo"])
    row = df_exp[df_exp["Componente"] == codigo]
    if not row.empty: return str(row.iloc[0].get("Descripción Componente",""))
    return "—"

def get_familia(codigo):
    """
    Busca la familia del componente.
    Primero como Componente, luego como Código Semi (para semis que se usan como nivel 1).
    Si empieza con 231 en df_exp como Código Semi, es fabricado.
    """
    codigo = str(codigo).strip()
    # Buscar como componente dentro de una explosión
    row = df_exp[df_exp["Componente"] == codigo]
    if not row.empty:
        return str(row.iloc[0].get("Familia", codigo[:3]))
    # Buscar como semi terminado (existe como Código Semi en Tiempos o Explosión)
    row_semi = df_exp[df_exp["Código Semi"] == codigo]
    if not row_semi.empty:
        # Si existe en Explosión como semi, su familia se deduce del prefijo
        return codigo[:3]
    return codigo[:3]

def get_costo_estandar_comp(codigo, codigo_pt):
    """Costo estándar desde Explosión filtrando por PT, o desde Costos."""
    codigo = str(codigo).strip()
    # Primero buscar en explosión del PT específico
    row = df_exp[(df_exp["Componente"] == codigo) & (df_exp["Código PT"] == str(codigo_pt))]
    if not row.empty:
        c = float(row.iloc[0]["Costo estandar"])
        if c > 0: return c
    # Luego en Costos (precio promedio)
    row = df_cos[df_cos["Número de artículo"] == codigo]
    if not row.empty: return float(row.iloc[0]["Precio promedio"])
    # Finalmente en cualquier fila de Explosión
    row = df_exp[df_exp["Componente"] == codigo]
    if not row.empty:
        c = float(row.iloc[0]["Costo estandar"])
        if c > 0: return c
    return 0.0

# ── Lógica de cálculo idéntica al dashboard ─────────────────
def calcular_semi(codigo_semi, cantidad_req, df_e, df_t, cache, resumen_global, codigo_pt, factor_escala=1.0):
    """
    Igual que reporte_costos_web.py — filtra por codigo_pt para evitar duplicados.
    factor_escala: escala las cantidades de sub-semis proporcionalmente a cant_base_nueva.
    """
    cache_key = f"{codigo_semi}_{cantidad_req}_{factor_escala}"
    if cache_key in cache:
        return cache[cache_key]["costo_x_und"], []

    hijos = df_e[
        (df_e["Código Semi"] == str(codigo_semi)) &
        (df_e["Código PT"]   == str(codigo_pt))
    ].copy()

    # Si no hay hijos en el PT base, buscar en cualquier PT que tenga ese semi
    # Esto permite usar componentes de otros PTs al simular una receta nueva
    if hijos.empty:
        hijos = df_e[df_e["Código Semi"] == str(codigo_semi)].copy()
        if not hijos.empty:
            # Usar el primer PT que lo contenga como referencia
            pt_ref = hijos["Código PT"].iloc[0]
            hijos  = df_e[
                (df_e["Código Semi"] == str(codigo_semi)) &
                (df_e["Código PT"]   == str(pt_ref))
            ].copy()
    if hijos.empty:
        return 0, []

    desc_semi   = hijos["Descripción Semi"].iloc[0] if "Descripción Semi" in hijos.columns else ""
    t           = get_tiempos(codigo_semi, df_t)
    proceso     = str(t["Proceso"]).strip().upper() if t is not None else "SIN PROCESO"
    cant_base_t = float(t["Cantidad Base"])          if t is not None else 1
    tarifa_maq  = float(t["Tarifa Maquina"])         if t is not None else 0
    tarifa_mo   = float(t["Tarifa MO"])              if t is not None else 0
    t_maq       = float(t["T.Maq"])                  if t is not None else 0
    t_mo        = float(t["T.MO"])                   if t is not None else 0
    if cant_base_t == 0: cant_base_t = 1

    # CIF y MOD escalan con factor_escala para mantener costo unitario constante
    cif = (t_maq / cant_base_t) * cantidad_req * tarifa_maq
    mod = (t_mo  / cant_base_t) * cantidad_req * tarifa_mo

    cm_total = 0; cm_comprados = 0; detalle = []

    for _, row in hijos.iterrows():
        componente = str(row["Componente"])
        # Escalar cantidad del sub-semi con el mismo factor que nivel 1
        cantidad   = float(row["Cantidad Total Requerida"]) * factor_escala
        costo_std  = float(row["Costo estandar"])
        familia    = str(row.get("Familia", componente[:3])).strip()

        if es_fabricado(familia):
            costo_calc, sub_det = calcular_semi(componente, cantidad, df_e, df_t, cache, resumen_global, codigo_pt, factor_escala)
            cm_comp = cantidad * costo_calc
        else:
            costo_calc   = costo_std
            cm_comp      = cantidad * costo_calc
            cm_comprados += cm_comp

        cm_total += cm_comp

    total_semi  = cm_total + cif + mod
    costo_x_und = total_semi / cantidad_req if cantidad_req != 0 else 0

    if proceso not in PROCESOS_EXCLUIR:
        if proceso not in resumen_global:
            resumen_global[proceso] = {"CM": 0, "CIF": 0, "MOD": 0}
        resumen_global[proceso]["CM"]  += cm_comprados
        resumen_global[proceso]["CIF"] += cif
        resumen_global[proceso]["MOD"] += mod

    cache[cache_key] = {"costo_x_und": costo_x_und}
    return costo_x_und, detalle


def calcular_receta_simulada(filas_receta, cant_base_nueva, df_t_sim, codigo_pt_base):
    """
    Calcula el costo de una receta simulada.
    - Para componentes 231: usa calcular_semi con filtro de codigo_pt_base
    - Para no fabricados: usa costo estándar de Costos/Explosión
    - El factor de escala se calcula por componente:
      factor = cantidad_editada / cantidad_original_del_PT
      Así si reduces la masa a la mitad, sus sub-componentes también se reducen a la mitad.
    """
    cache          = {}
    resumen_global = {}
    cm_total       = 0
    cm_comprados   = 0

    # Cantidad base original del PT para calcular factor por componente
    cant_base_orig = get_cant_base_original(codigo_pt_base)

    # Mapa de cantidades originales del PT base: {codigo: cantidad_original}
    filas_orig     = get_nivel1_pt(codigo_pt_base)
    orig_cant_map  = {str(f["Código"]): float(f["Cantidad"]) for f in filas_orig}

    # Factor global (cant_base_nueva / cant_base_orig) para el proceso PT
    factor_global  = (cant_base_nueva / cant_base_orig) if cant_base_orig > 0 else 1.0

    # Proceso del PT base (DOSIFICADO, ENCAJADO, etc.)
    t_pt        = get_tiempos(codigo_pt_base, df_t_sim)
    proceso_pt  = str(t_pt["Proceso"]).strip().upper() if t_pt is not None else "PROCESO_PT"
    cant_base_t = float(t_pt["Cantidad Base"])          if t_pt is not None else 1
    tarifa_maq  = float(t_pt["Tarifa Maquina"])         if t_pt is not None else 0
    tarifa_mo   = float(t_pt["Tarifa MO"])              if t_pt is not None else 0
    t_maq       = float(t_pt["T.Maq"])                  if t_pt is not None else 0
    t_mo        = float(t_pt["T.MO"])                   if t_pt is not None else 0
    if cant_base_t == 0: cant_base_t = 1

    # CIF y MOD del proceso PT escalan con cant_base_nueva
    cif_pt = (t_maq / cant_base_t) * cant_base_nueva * tarifa_maq
    mod_pt = (t_mo  / cant_base_t) * cant_base_nueva * tarifa_mo

    for fila in filas_receta:
        codigo   = str(fila.get("Código", "")).strip()
        cantidad = float(fila.get("Cantidad", 0) or 0)
        if not codigo or cantidad == 0:
            continue
        familia = get_familia(codigo)

        # Factor por componente: cantidad editada / cantidad original
        # Si el código fue cambiado manualmente, usar factor global
        cant_orig_comp = orig_cant_map.get(codigo, 0)
        if cant_orig_comp > 0:
            factor_comp = cantidad / cant_orig_comp
        else:
            # Código nuevo o cambiado — usar factor global
            factor_comp = factor_global

        if es_fabricado(familia):
            # Si el semi no existe bajo el PT base, buscar el PT donde sí existe
            codigo_pt_para_semi = codigo_pt_base
            hijos_check = df_exp[
                (df_exp["Código Semi"] == str(codigo)) &
                (df_exp["Código PT"]   == str(codigo_pt_base))
            ]
            if hijos_check.empty:
                # Código cambiado manualmente — buscar en cualquier PT
                alt = df_exp[df_exp["Código Semi"] == str(codigo)]
                if not alt.empty:
                    codigo_pt_para_semi = str(alt.iloc[0]["Código PT"])
            costo_calc, _ = calcular_semi(
                codigo, cantidad, df_exp, df_t_sim,
                cache, resumen_global, codigo_pt_para_semi, factor_comp
            )
            cm_comp = cantidad * costo_calc
        else:
            costo_std    = get_costo_estandar_comp(codigo, codigo_pt_base)
            cm_comp      = cantidad * costo_std
            cm_comprados += cm_comp

        cm_total += cm_comp

    # Agregar proceso del PT con CIF y MOD
    if proceso_pt not in resumen_global:
        resumen_global[proceso_pt] = {"CM": 0, "CIF": 0, "MOD": 0}
    resumen_global[proceso_pt]["CM"]  += cm_comprados
    resumen_global[proceso_pt]["CIF"] += cif_pt
    resumen_global[proceso_pt]["MOD"] += mod_pt

    # Limpiar vacíos
    resumen_global = {k: v for k, v in resumen_global.items()
                      if v["CM"] + v["CIF"] + v["MOD"] > 0}

    total_pt    = cm_total + cif_pt + mod_pt
    costo_x_und = total_pt / cant_base_nueva if cant_base_nueva > 0 else 0
    return resumen_global, costo_x_und


def get_nivel1_pt(codigo_pt):
    """Nivel 1 usando Código PT como filtro principal."""
    nivel1 = df_exp[df_exp["Código Semi"] == str(codigo_pt)].copy()
    rows = []
    for _, row in nivel1.iterrows():
        comp     = str(row["Componente"])
        cantidad = float(row["Cantidad Total Requerida"])
        rows.append({
            "Código":      comp,
            "Descripción": str(row.get("Descripción Componente", get_descripcion(comp))),
            "Unidad":      get_unidad(comp),
            "Cantidad":    cantidad,
        })
    return rows


def get_cant_base_original(codigo_pt):
    """
    Obtiene la cantidad base original del PT desde Explosión.
    Usamos Explosión porque las cantidades de la receta están
    expresadas en esa misma escala.
    """
    row = df_exp[df_exp["Código Semi"] == str(codigo_pt)]
    if not row.empty:
        cant = float(row.iloc[0]["Cantidad Base"] or 0)
        if cant > 0:
            return cant
    # Fallback: Tiempos
    t = get_tiempos(codigo_pt, df_tie)
    if t is not None:
        return float(t["Cantidad Base"] or 0)
    return 0.0


def get_procesos_tiempos(filas_receta, codigo_pt):
    """Carga procesos del PT base y de todos los semis fabricados en la receta."""
    visitados = set()
    maquinas  = {}

    def registrar(codigo):
        rows = df_tie[df_tie["Código Semi"] == str(codigo)]
        for _, t_row in rows.iterrows():
            proceso = str(t_row.get("Proceso","")).strip()
            maq     = str(t_row.get("Maquina", codigo))
            key     = f"{proceso}_{maq}"
            if key not in maquinas and proceso:
                maquinas[key] = {
                    "Proceso":       proceso,
                    "Maquina":       maq,
                    "Cantidad Base": float(t_row.get("Cantidad Base", 0) or 0),
                    "T.MO":          float(t_row.get("T.MO",          0) or 0),
                    "T.Maq":         float(t_row.get("T.Maq",         0) or 0),
                    "Tarifa Maq":    float(t_row.get("Tarifa Maquina",0) or 0),
                    "Tarifa MO":     float(t_row.get("Tarifa MO",     0) or 0),
                }

    def buscar(codigo, codigo_pt_buscar=None):
        if codigo in visitados: return
        visitados.add(codigo)
        registrar(codigo)
        # Buscar hijos bajo el PT correcto
        pt_usar = codigo_pt_buscar or codigo_pt
        hijos = df_exp[(df_exp["Código Semi"] == str(codigo)) &
                       (df_exp["Código PT"]   == str(pt_usar))]
        if hijos.empty:
            # Código cambiado — buscar en cualquier PT
            hijos = df_exp[df_exp["Código Semi"] == str(codigo)]
        for _, row in hijos.iterrows():
            comp    = str(row["Componente"])
            familia = str(row.get("Familia", comp[:3])).strip()
            if es_fabricado(familia):
                buscar(comp)

    # Proceso del PT base
    registrar(str(codigo_pt))
    # Procesos de semis fabricados en la receta (con sus códigos actuales)
    for fila in filas_receta:
        codigo  = str(fila.get("Código","")).strip()
        familia = get_familia(codigo)
        if es_fabricado(familia):
            # Verificar si existe bajo el PT base, si no buscar en cualquier PT
            hijos_check = df_exp[
                (df_exp["Código Semi"] == str(codigo)) &
                (df_exp["Código PT"]   == str(codigo_pt))
            ]
            pt_correcto = codigo_pt
            if hijos_check.empty:
                alt = df_exp[df_exp["Código Semi"] == str(codigo)]
                if not alt.empty:
                    pt_correcto = str(alt.iloc[0]["Código PT"])
            buscar(codigo, pt_correcto)

    return list(maquinas.values())


# ── App ──────────────────────────────────────────────────────
app    = Dash(__name__)
server = app.server

COLORES = {
    "bg": "#0F1923", "card": "#1A2633", "text": "#E8EDF2",
    "accent": "#00C8FF", "green": "#4CAF50", "orange": "#FF9800",
}

lista_pt = df_exp[["Código PT","Descripción PT"]].drop_duplicates()

app.layout = html.Div(
    style={"backgroundColor": COLORES["bg"], "minHeight": "100vh",
           "fontFamily": "'Segoe UI', sans-serif", "color": COLORES["text"], "padding": "20px"},
    children=[
        html.H1("🧪 Simulador de Receta", style={"color": COLORES["accent"],
                "textAlign": "center", "marginBottom": "5px"}),
        html.P("Arma un nuevo producto combinando componentes existentes",
               style={"color": "#7A9BBF", "textAlign": "center", "marginBottom": "25px"}),

        # ── Datos nuevo producto ────────────────────────────
        html.Div(style={"backgroundColor": COLORES["card"], "borderRadius": "12px",
                        "padding": "15px", "marginBottom": "20px"}, children=[
            html.H3("📝 Nuevo Producto", style={"color": COLORES["accent"],
                    "fontSize": "16px", "marginTop": 0}),
            html.Div(style={"display": "grid", "gridTemplateColumns": "1fr 1fr 1fr", "gap": "15px"},
                     children=[
                html.Div([
                    html.Label("Código:", style={"color": "#7A9BBF", "fontSize": "12px"}),
                    dcc.Input(id="input-codigo-nuevo", type="text", placeholder="Ej: 2110099999",
                              style={"width": "100%", "padding": "8px", "marginTop": "5px",
                                     "backgroundColor": "#0D2137", "color": COLORES["text"],
                                     "border": "1px solid #00C8FF", "borderRadius": "6px"}),
                ]),
                html.Div([
                    html.Label("Descripción:", style={"color": "#7A9BBF", "fontSize": "12px"}),
                    dcc.Input(id="input-desc-nuevo", type="text", placeholder="Ej: Tempera 125ml Rojo",
                              style={"width": "100%", "padding": "8px", "marginTop": "5px",
                                     "backgroundColor": "#0D2137", "color": COLORES["text"],
                                     "border": "1px solid #00C8FF", "borderRadius": "6px"}),
                ]),
                html.Div([
                    html.Label("Cantidad Base (lote):", style={"color": "#7A9BBF", "fontSize": "12px"}),
                    dcc.Input(id="input-cant-base", type="number", placeholder="Ej: 8000", value=8000,
                              style={"width": "100%", "padding": "8px", "marginTop": "5px",
                                     "backgroundColor": "#0D2137", "color": COLORES["text"],
                                     "border": "1px solid #FF9800", "borderRadius": "6px"}),
                ]),
            ]),
        ]),

        # ── PT Base ────────────────────────────────────────
        html.Div(style={"backgroundColor": COLORES["card"], "borderRadius": "12px",
                        "padding": "15px", "marginBottom": "20px"}, children=[
            html.H3("📦 PT Base", style={"color": COLORES["accent"], "fontSize": "16px", "marginTop": 0}),
            dcc.Dropdown(
                id="selector-pt-base",
                options=[{"label": f"{r['Código PT']} — {r['Descripción PT']}", "value": r["Código PT"]}
                         for _, r in lista_pt.iterrows()],
                placeholder="Selecciona un PT base...", style={"color": "#000"}
            ),
            html.Button("📥 Cargar Receta Base", id="btn-cargar",
                style={"marginTop": "12px", "backgroundColor": COLORES["accent"],
                       "color": "#000", "fontWeight": "bold", "border": "none",
                       "borderRadius": "8px", "padding": "10px 24px", "cursor": "pointer"}),
            # Almacena cant_base original del PT para calcular el factor
            dcc.Store(id="store-cant-base-orig", data=0),
            dcc.Store(id="store-receta-orig",    data=[]),
            dcc.Store(id="store-codigo-pt",      data=None),
        ]),

        # ── Tabla receta editable ───────────────────────────
        html.Div(style={"backgroundColor": COLORES["card"], "borderRadius": "12px",
                        "padding": "15px", "marginBottom": "20px",
                        "border": "1px solid #00C8FF"}, children=[
            html.H3("✏️ Receta Editable — Nivel 1",
                    style={"color": COLORES["accent"], "fontSize": "16px", "marginTop": 0}),
            html.P("Modifica códigos y cantidades. Las cantidades se ajustan automáticamente con la cantidad base.",
                   style={"color": "#7A9BBF", "fontSize": "12px", "marginBottom": "10px"}),
            dash_table.DataTable(
                id="tabla-receta",
                columns=[
                    {"name": "Código",      "id": "Código",      "editable": True},
                    {"name": "Descripción", "id": "Descripción", "editable": True},
                    {"name": "Unidad",      "id": "Unidad",      "editable": False},
                    {"name": "Cantidad",    "id": "Cantidad",    "editable": True, "type": "numeric"},
                ],
                data=[], editable=True, row_deletable=True,
                style_header={"backgroundColor": "#1F3864", "color": "white", "fontWeight": "bold"},
                style_cell={"backgroundColor": "#1E2D3D", "color": COLORES["text"],
                            "border": "1px solid #2A3F54", "padding": "8px", "textAlign": "center"},
                style_cell_conditional=[
                    {"if": {"column_id": "Código"},      "width": "130px"},
                    {"if": {"column_id": "Descripción"}, "width": "280px", "textAlign": "left"},
                    {"if": {"column_id": "Unidad"},      "width": "80px"},
                    {"if": {"column_id": "Cantidad"},    "width": "120px"},
                ],
                style_data_conditional=[
                    {"if": {"column_editable": True},
                     "backgroundColor": "#0D2137", "border": "1px solid #00C8FF"},
                    {"if": {"row_index": "odd"}, "backgroundColor": "#162030"},
                ],
                page_action="none",
            ),
            html.Button("➕ Agregar Fila", id="btn-agregar-fila",
                style={"marginTop": "10px", "backgroundColor": "#4A5568", "color": "white",
                       "border": "none", "borderRadius": "8px", "padding": "8px 20px",
                       "cursor": "pointer", "fontSize": "13px"}),
        ]),

        # ── Procesos ────────────────────────────────────────
        html.Div(style={"backgroundColor": COLORES["card"], "borderRadius": "12px",
                        "padding": "15px", "marginBottom": "20px",
                        "border": "1px solid #4CAF50"}, children=[
            html.H3("⚙️ Procesos — Cantidad Base Editable",
                    style={"color": COLORES["green"], "fontSize": "16px", "marginTop": 0}),
            html.P("Modifica la Cantidad Base para recalcular CIF y MOD de cada proceso.",
                   style={"color": "#7A9BBF", "fontSize": "12px", "marginBottom": "10px"}),
            dash_table.DataTable(
                id="tabla-procesos",
                columns=[
                    {"name": "Proceso",       "id": "Proceso",       "editable": False},
                    {"name": "Máquina",       "id": "Maquina",       "editable": False},
                    {"name": "Cantidad Base", "id": "Cantidad Base", "editable": True, "type": "numeric"},
                    {"name": "T.MO",          "id": "T.MO",          "editable": False},
                    {"name": "T.Maq",         "id": "T.Maq",         "editable": False},
                    {"name": "Tarifa Maq",    "id": "Tarifa Maq",    "editable": False},
                    {"name": "Tarifa MO",     "id": "Tarifa MO",     "editable": False},
                ],
                data=[], editable=True,
                style_header={"backgroundColor": "#1F3864", "color": "white", "fontWeight": "bold"},
                style_cell={"backgroundColor": "#1E2D3D", "color": COLORES["text"],
                            "border": "1px solid #2A3F54", "padding": "8px", "textAlign": "center"},
                style_data_conditional=[
                    {"if": {"column_editable": True},
                     "backgroundColor": "#0D2137", "border": "1px solid #4CAF50"},
                    {"if": {"row_index": "odd"}, "backgroundColor": "#162030"},
                ],
                page_action="none",
            ),
        ]),

        # ── Botones ─────────────────────────────────────────
        html.Div(style={"display": "flex", "gap": "15px", "justifyContent": "center",
                        "marginBottom": "20px"}, children=[
            html.Button("🔢 Calcular Costo", id="btn-calcular",
                style={"backgroundColor": COLORES["green"], "color": "#000", "fontWeight": "bold",
                       "border": "none", "borderRadius": "8px", "padding": "12px 30px",
                       "cursor": "pointer", "fontSize": "15px",
                       "boxShadow": "0 0 15px rgba(76,175,80,0.4)"}),
            html.Button("⬇️ Exportar Excel", id="btn-exportar",
                style={"backgroundColor": COLORES["orange"], "color": "#000", "fontWeight": "bold",
                       "border": "none", "borderRadius": "8px", "padding": "12px 30px",
                       "cursor": "pointer", "fontSize": "15px",
                       "boxShadow": "0 0 15px rgba(255,152,0,0.4)"}),
            dcc.Download(id="descarga-receta"),
            html.Div(id="msg-receta", style={"color": COLORES["green"],
                                              "fontSize": "13px", "alignSelf": "center"}),
        ]),

        html.Div(id="resultado-receta"),
    ]
)


# ── Callback 1: Cargar receta base ──────────────────────────
@app.callback(
    Output("tabla-receta",        "data"),
    Output("tabla-procesos",      "data"),
    Output("store-cant-base-orig","data"),
    Output("store-receta-orig",   "data"),
    Output("store-codigo-pt",     "data"),
    Input("btn-cargar",           "n_clicks"),
    State("selector-pt-base",     "value"),
    prevent_initial_call=True,
)
def cargar_receta(n_clicks, codigo_pt):
    if not codigo_pt:
        return [], [], 0, [], None
    filas         = get_nivel1_pt(codigo_pt)
    procesos      = get_procesos_tiempos(filas, codigo_pt)
    cant_base_ori = get_cant_base_original(codigo_pt)
    return filas, procesos, cant_base_ori, filas, codigo_pt


# ── Callback 2: Actualizar cantidades al cambiar cantidad base
@app.callback(
    Output("tabla-receta", "data", allow_duplicate=True),
    Input("input-cant-base",      "value"),
    State("store-cant-base-orig", "data"),
    State("store-receta-orig",    "data"),
    State("tabla-receta",         "data"),
    prevent_initial_call=True,
)
def actualizar_cantidades(cant_base_nueva, cant_base_orig, receta_orig, data_actual):
    if not cant_base_nueva or not cant_base_orig or cant_base_orig == 0:
        return data_actual or []
    factor    = float(cant_base_nueva) / float(cant_base_orig)
    orig_map  = {str(f["Código"]): float(f["Cantidad"]) for f in (receta_orig or [])}
    resultado = []
    for row in (data_actual or []):
        codigo = str(row.get("Código","")).strip()
        cant_orig = orig_map.get(codigo, float(row.get("Cantidad", 0) or 0))
        row = dict(row)
        row["Cantidad"] = round(cant_orig * factor, 6)
        resultado.append(row)
    return resultado


# ── Callback 3: Agregar fila ────────────────────────────────
@app.callback(
    Output("tabla-receta", "data", allow_duplicate=True),
    Input("btn-agregar-fila", "n_clicks"),
    State("tabla-receta",     "data"),
    prevent_initial_call=True,
)
def agregar_fila(n_clicks, data):
    if data is None: data = []
    data.append({"Código": "", "Descripción": "", "Unidad": "—", "Cantidad": 0})
    return data


# ── Callback 4: Calcular ────────────────────────────────────
@app.callback(
    Output("resultado-receta", "children"),
    Output("tabla-procesos",   "data",     allow_duplicate=True),
    Output("msg-receta",       "children"),
    Input("btn-calcular",      "n_clicks"),
    State("tabla-receta",      "data"),
    State("tabla-procesos",    "data"),
    State("input-codigo-nuevo","value"),
    State("input-desc-nuevo",  "value"),
    State("input-cant-base",   "value"),
    State("store-codigo-pt",   "data"),
    prevent_initial_call=True,
)
def calcular(n_clicks, data, datos_procesos, codigo_nuevo, desc_nuevo, cant_base, codigo_pt_base):
    if not data:
        return "", "⚠️ Agrega componentes primero"
    if not codigo_pt_base:
        return "", "⚠️ Selecciona un PT base primero"

    cant_base_pt = float(cant_base or 8000)

    # Aplicar ediciones de Cantidad Base en Tiempos
    df_tie_sim = df_tie.copy()
    if datos_procesos:
        for row in datos_procesos:
            maq        = str(row.get("Maquina",""))
            nueva_base = float(row.get("Cantidad Base", 0) or 0)
            if maq and nueva_base > 0:
                mask = df_tie_sim["Maquina"].astype(str).str.strip() == maq
                df_tie_sim.loc[mask, "Cantidad Base"] = nueva_base

    resumen_sim, costo_x_und = calcular_receta_simulada(
        data, cant_base_pt, df_tie_sim, codigo_pt_base
    )

    nombre  = f"{codigo_nuevo or 'NUEVO'} — {desc_nuevo or 'Sin descripción'}"
    paleta  = ["#2196F3","#4CAF50","#FF9800","#E91E63","#9C27B0","#00BCD4","#FF5722"]
    total   = sum(v["CM"]+v["CIF"]+v["MOD"] for v in resumen_sim.values()) / cant_base_pt
    tot_cm  = sum(v["CM"]  for v in resumen_sim.values()) / cant_base_pt
    tot_cif = sum(v["CIF"] for v in resumen_sim.values()) / cant_base_pt
    tot_mod = sum(v["MOD"] for v in resumen_sim.values()) / cant_base_pt

    def kpi(titulo, valor, color):
        return html.Div(
            style={"backgroundColor": COLORES["card"], "borderLeft": f"4px solid {color}",
                   "borderRadius": "10px", "padding": "15px 20px", "flex": "1", "minWidth": "160px"},
            children=[
                html.P(titulo, style={"margin": 0, "fontSize": "12px", "color": "#7A9BBF"}),
                html.H2(valor, style={"margin": "5px 0 0 0", "color": color, "fontSize": "18px"}),
            ]
        )

    kpis = html.Div(style={"display": "flex", "gap": "15px", "flexWrap": "wrap", "marginBottom": "20px"},
                    children=[
        kpi("💰 Costo Unitario",  f"S/ {total:.6f}",              COLORES["accent"]),
        kpi("📦 Costo del Lote",  f"S/ {total*cant_base_pt:.2f}", COLORES["orange"]),
        kpi("🧱 CM Unitario",     f"S/ {tot_cm:.6f}",             "#2196F3"),
        kpi("⚙️ CIF Unitario",    f"S/ {tot_cif:.6f}",            COLORES["orange"]),
        kpi("👷 MOD Unitario",    f"S/ {tot_mod:.6f}",            COLORES["green"]),
        kpi("🔢 Cantidad Base",   f"{int(cant_base_pt):,}",        "#7A9BBF"),
    ])

    # Cascada
    filas_cas = []; tg = 0
    for proceso, v in resumen_sim.items():
        for tipo, monto in [("CM",v["CM"]),("CIF",v["CIF"]),("MOD",v["MOD"])]:
            if monto > 0:
                cu = monto / cant_base_pt; tg += cu
                filas_cas.append({"Proceso": proceso, "Tipo": tipo, "Costo": f"S/ {cu:.6f}"})
    for f in filas_cas:
        v = float(f["Costo"].replace("S/ ",""))
        f["%TG"] = f"{v/tg*100:.1f}%" if tg > 0 else "0%"
    filas_cas.append({"Proceso": "TOTAL PT", "Tipo": "", "Costo": f"S/ {tg:.6f}", "%TG": "100.0%"})

    tabla_cas = dash_table.DataTable(
        columns=[{"name": c, "id": c} for c in ["Proceso","Tipo","Costo","%TG"]],
        data=filas_cas,
        style_header={"backgroundColor": "#1F3864", "color": "white", "fontWeight": "bold"},
        style_cell={"backgroundColor": "#1E2D3D", "color": COLORES["text"],
                    "border": "1px solid #2A3F54", "padding": "8px", "textAlign": "center"},
        style_data_conditional=[
            {"if": {"row_index": "odd"}, "backgroundColor": "#162030"},
            {"if": {"filter_query": '{Tipo} = "MOD"'}, "color": "#4CAF50", "fontWeight": "bold"},
            {"if": {"filter_query": '{Tipo} = "CIF"'}, "color": "#FF9800", "fontWeight": "bold"},
            {"if": {"filter_query": '{Proceso} = "TOTAL PT"'},
             "backgroundColor": "#1F3864", "color": "#00C8FF", "fontWeight": "bold"},
        ],
        page_action="none",
    )

    labels_don = [f"{f['Proceso']} {f['Tipo']}" for f in filas_cas if f["Proceso"] != "TOTAL PT"]
    values_don = [float(f["Costo"].replace("S/ ","")) for f in filas_cas if f["Proceso"] != "TOTAL PT"]
    fig_don = go.Figure(go.Pie(
        labels=labels_don, values=values_don, hole=0.55,
        marker_colors=(paleta*5)[:len(labels_don)], textinfo="percent",
        hovertemplate="<b>%{label}</b><br>S/ %{value:.6f}<br>%{percent}<extra></extra>"
    ))
    fig_don.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
                          margin=dict(l=10,r=10,t=10,b=10))

    resultado = html.Div([
        html.Div(style={"backgroundColor": COLORES["card"], "borderRadius": "12px",
                        "padding": "15px", "marginBottom": "20px"}, children=[
            html.H3(f"📊 Resultado: {nombre}",
                    style={"color": COLORES["accent"], "fontSize": "16px", "marginTop": 0}),
            kpis,
        ]),
        html.Div(style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "20px"}, children=[
            html.Div(style={"backgroundColor": COLORES["card"], "borderRadius": "12px", "padding": "15px"},
                     children=[
                html.H3("📋 Cascada por Proceso",
                        style={"color": COLORES["accent"], "fontSize": "16px", "marginTop": 0}),
                tabla_cas,
            ]),
            html.Div(style={"backgroundColor": COLORES["card"], "borderRadius": "12px", "padding": "15px"},
                     children=[
                html.H3("🥧 Distribución de Costos",
                        style={"color": COLORES["accent"], "fontSize": "16px", "marginTop": 0}),
                dcc.Graph(figure=fig_don),
            ]),
        ]),
    ])

    # Actualizar tabla de procesos con los códigos actuales de la receta
    procesos_actualizados = get_procesos_tiempos(data, codigo_pt_base)

    return resultado, procesos_actualizados, f"✅ Calculado — {datetime.now().strftime('%H:%M:%S')}"


# ── Callback 5: Exportar Excel ──────────────────────────────
@app.callback(
    Output("descarga-receta",  "data"),
    Input("btn-exportar",      "n_clicks"),
    State("tabla-receta",      "data"),
    State("tabla-procesos",    "data"),
    State("input-codigo-nuevo","value"),
    State("input-desc-nuevo",  "value"),
    State("input-cant-base",   "value"),
    State("store-codigo-pt",   "data"),
    prevent_initial_call=True,
)
def exportar(n_clicks, data, datos_procesos, codigo_nuevo, desc_nuevo, cant_base, codigo_pt_base):
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    if not data or not codigo_pt_base: return None

    cant_base_pt = float(cant_base or 8000)
    df_tie_sim   = df_tie.copy()
    if datos_procesos:
        for row in datos_procesos:
            maq        = str(row.get("Maquina",""))
            nueva_base = float(row.get("Cantidad Base", 0) or 0)
            if maq and nueva_base > 0:
                mask = df_tie_sim["Maquina"].astype(str).str.strip() == maq
                df_tie_sim.loc[mask, "Cantidad Base"] = nueva_base

    resumen_sim, _ = calcular_receta_simulada(data, cant_base_pt, df_tie_sim, codigo_pt_base)
    nombre = f"{codigo_nuevo or 'NUEVO'} — {desc_nuevo or 'Sin descripción'}"
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        # Resumen Global
        filas_res = []; tg = 0
        for proceso, v in resumen_sim.items():
            for tipo, monto in [("CM",v["CM"]),("CIF",v["CIF"]),("MOD",v["MOD"])]:
                if monto > 0:
                    cu = monto / cant_base_pt; tg += cu
                    filas_res.append({
                        "Código PT": codigo_nuevo or "NUEVO",
                        "Descripción PT": desc_nuevo or "Sin descripción",
                        "Proceso": proceso, "Tipo de Costo": f"{tipo} {proceso}",
                        "Costo Unitario": round(cu, 6), "Costo Lote": round(monto, 2),
                    })
        filas_res.append({
            "Código PT": codigo_nuevo or "NUEVO", "Descripción PT": desc_nuevo or "Sin descripción",
            "Proceso": "TOTAL", "Tipo de Costo": "TOTAL PT",
            "Costo Unitario": round(tg, 6), "Costo Lote": round(tg * cant_base_pt, 2),
        })
        df_res = pd.DataFrame(filas_res)
        df_res["%TG"] = df_res["Costo Unitario"].apply(
            lambda x: f"{x/tg*100:.1f}%" if tg > 0 else "0%")
        df_res.to_excel(writer, sheet_name="Resumen Global", index=False)

        # Cascada Detallada
        filas_cas = []; tg2 = 0
        for proceso, v in resumen_sim.items():
            for tipo, monto in [("CM",v["CM"]),("CIF",v["CIF"]),("MOD",v["MOD"])]:
                if monto > 0:
                    cu = monto / cant_base_pt; tg2 += cu
                    filas_cas.append({"Proceso": proceso, "Tipo": tipo,
                                      "Costo Unitario": round(cu,6), "Costo Lote": round(monto,2)})
        for f in filas_cas:
            f["%TG"] = f"{f['Costo Unitario']/tg2*100:.1f}%" if tg2 > 0 else "0%"
        filas_cas.append({"Proceso": "TOTAL PT", "Tipo": "",
                          "Costo Unitario": round(tg2,6),
                          "Costo Lote": round(tg2*cant_base_pt,2), "%TG": "100.0%"})
        pd.DataFrame(filas_cas).to_excel(writer, sheet_name="Cascada Detallada", index=False)

        fills = {
            "Resumen Global":    PatternFill("solid", fgColor="1F3864"),
            "Cascada Detallada": PatternFill("solid", fgColor="1F5C2E"),
        }
        hf   = Font(bold=True, color="FFFFFF")
        info = f"Simulación: {nombre}  |  Cant. Base: {int(cant_base_pt):,}  |  {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        for sn, ws in writer.sheets.items():
            ws.insert_rows(1); ws["A1"] = info
            ws["A1"].font = Font(bold=True, color="00C8FF")
            ws["A1"].fill = PatternFill("solid", fgColor="0F1923")
            ws.insert_rows(2)
            for cell in ws[3]:
                cell.font = hf; cell.fill = fills.get(sn, fills["Resumen Global"])
                cell.alignment = Alignment(horizontal="center")
            for col in ws.columns:
                ml = max((len(str(c.value)) for c in col if c.value), default=10)
                ws.column_dimensions[get_column_letter(col[0].column)].width = min(ml+4, 50)

    output.seek(0)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return dcc.send_bytes(output.read(), filename=f"Receta_{codigo_nuevo or 'nuevo'}_{ts}.xlsx")


if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=int(os.environ.get("PORT", 8051)))
