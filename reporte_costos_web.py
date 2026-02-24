"""
=============================================================
  REPORTE DE COSTOS - VERSIÓN WEB (Render.com)
  Este archivo es el punto de entrada para el servidor web.
  Lee el Excel desde la misma carpeta del proyecto.
=============================================================
"""

import pandas as pd
import os
from datetime import datetime
import plotly.graph_objects as go
from dash import Dash, html, dcc, Input, Output, dash_table, State

# ─── CONFIGURACIÓN ─────────────────────────────────────────
ARCHIVO_DATOS    = "Analisis de costos_PY.xlsx"
HOJA_EXPLOSION   = "Explosión"
HOJA_TIEMPOS     = "Tiempos"
PREFIJO_FABRIC   = "231"
PROCESOS_EXCLUIR = []
# ───────────────────────────────────────────────────────────

# ── Cargar datos ────────────────────────────────────────────
df_exp = pd.read_excel(ARCHIVO_DATOS, sheet_name=HOJA_EXPLOSION)
df_tie = pd.read_excel(ARCHIVO_DATOS, sheet_name=HOJA_TIEMPOS)

df_exp.columns = df_exp.columns.str.strip()
df_tie.columns = df_tie.columns.str.strip()

for col in ["Código PT", "Código Semi", "Componente", "Familia"]:
    if col in df_exp.columns:
        df_exp[col] = df_exp[col].astype(str).str.strip()
df_tie["Código Semi"] = df_tie["Código Semi"].astype(str).str.strip()

for col in ["Cantidad Total Requerida", "Cantidad Base", "Costo estandar"]:
    df_exp[col] = pd.to_numeric(df_exp[col], errors="coerce").fillna(0)
for col in ["Cantidad Base", "T.MO", "T.Maq", "Tarifa MO", "Tarifa Maquina"]:
    if col in df_tie.columns:
        df_tie[col] = pd.to_numeric(df_tie[col], errors="coerce").fillna(0)

# ── Funciones de cálculo ────────────────────────────────────
def es_fabricado(familia):
    return str(familia).strip().startswith(PREFIJO_FABRIC)

def get_tiempos(codigo, df_t):
    row = df_t[df_t["Código Semi"] == str(codigo)]
    return row.iloc[0] if not row.empty else None

def calcular_semi(codigo_semi, cantidad_req, df_e, df_t, cache, resumen_global):
    cache_key = f"{codigo_semi}_{cantidad_req}"
    if cache_key in cache:
        return cache[cache_key]["costo_x_und"], []

    hijos = df_e[df_e["Código Semi"] == str(codigo_semi)].copy()
    if hijos.empty:
        return 0, []

    desc_semi     = hijos["Descripción Semi"].iloc[0] if "Descripción Semi" in hijos.columns else ""
    t             = get_tiempos(codigo_semi, df_t)
    proceso       = str(t["Proceso"]).strip().upper() if t is not None else "SIN PROCESO"
    cant_base_t   = float(t["Cantidad Base"])          if t is not None else 1
    tarifa_maq    = float(t["Tarifa Maquina"])         if t is not None else 0
    tarifa_mo     = float(t["Tarifa MO"])              if t is not None else 0
    t_maq         = float(t["T.Maq"])                  if t is not None else 0
    t_mo          = float(t["T.MO"])                   if t is not None else 0
    if cant_base_t == 0:
        cant_base_t = 1

    cif = (t_maq / cant_base_t) * cantidad_req * tarifa_maq
    mod = (t_mo  / cant_base_t) * cantidad_req * tarifa_mo

    detalle      = []
    cm_total     = 0
    cm_comprados = 0

    for _, row in hijos.iterrows():
        componente = str(row["Componente"])
        desc_comp  = str(row.get("Descripción Componente", ""))
        cantidad   = float(row["Cantidad Total Requerida"])
        costo_std  = float(row["Costo estandar"])
        familia    = str(row.get("Familia", componente[:3])).strip()

        if es_fabricado(familia):
            costo_calc, sub_det = calcular_semi(componente, cantidad, df_e, df_t, cache, resumen_global)
            detalle.extend(sub_det)
            cm_comp = cantidad * costo_calc
        else:
            costo_calc   = costo_std
            cm_comp      = cantidad * costo_calc
            cm_comprados += cm_comp

        cm_total += cm_comp
        detalle.append({
            "Código Semi": codigo_semi, "Descripción Semi": desc_semi,
            "Componente": componente,   "Descripción Componente": desc_comp,
            "Familia": familia, "Tipo": "FABRICADO" if es_fabricado(familia) else "COMPRADO",
            "Proceso": proceso, "Cantidad Total Req": cantidad,
            "Costo Calculado": costo_calc, "CM": cm_comp,
            "CIF": 0, "MOD": 0, "Total": cm_comp,
        })

    total_semi  = cm_total + cif + mod
    costo_x_und = total_semi / cantidad_req if cantidad_req != 0 else 0

    if proceso not in PROCESOS_EXCLUIR:
        if proceso not in resumen_global:
            resumen_global[proceso] = {"CM": 0, "CIF": 0, "MOD": 0}
        resumen_global[proceso]["CM"]  += cm_comprados
        resumen_global[proceso]["CIF"] += cif
        resumen_global[proceso]["MOD"] += mod

    detalle.append({
        "Código Semi": codigo_semi, "Descripción Semi": desc_semi,
        "Componente": f"[PROCESO] {codigo_semi}",
        "Descripción Componente": f"{proceso} — CIF + MOD",
        "Familia": PREFIJO_FABRIC, "Tipo": "PROCESO", "Proceso": proceso,
        "Cantidad Total Req": cantidad_req, "Costo Calculado": costo_x_und,
        "CM": cm_total, "CIF": cif, "MOD": mod, "Total": cm_total + cif + mod,
    })

    cache[cache_key] = {"costo_x_und": costo_x_und}
    return costo_x_und, detalle


def explotar_pt(codigo_pt, df_e, df_t):
    nivel1 = df_e[df_e["Código Semi"] == str(codigo_pt)].copy()
    if nivel1.empty:
        return {}, [], 0

    cant_base_pt = float(nivel1["Cantidad Base"].iloc[0])
    if cant_base_pt == 0:
        cant_base_pt = 1
    desc_pt = nivel1["Descripción Semi"].iloc[0] if "Descripción Semi" in nivel1.columns else ""

    t           = get_tiempos(codigo_pt, df_t)
    proceso_pt  = str(t["Proceso"]).strip().upper() if t is not None else "ENCAJADO"
    cant_base_t = float(t["Cantidad Base"])          if t is not None else 1
    tarifa_maq  = float(t["Tarifa Maquina"])         if t is not None else 0
    tarifa_mo   = float(t["Tarifa MO"])              if t is not None else 0
    t_maq       = float(t["T.Maq"])                  if t is not None else 0
    t_mo        = float(t["T.MO"])                   if t is not None else 0
    if cant_base_t == 0:
        cant_base_t = 1

    cif_pt = (t_maq / cant_base_t) * cant_base_pt * tarifa_maq
    mod_pt = (t_mo  / cant_base_t) * cant_base_pt * tarifa_mo

    cache          = {}
    detalle        = []
    resumen_global = {}
    cm_total       = 0
    cm_comprados   = 0

    for _, row in nivel1.iterrows():
        componente = str(row["Componente"])
        desc_comp  = str(row.get("Descripción Componente", ""))
        cantidad   = float(row["Cantidad Total Requerida"])
        costo_std  = float(row["Costo estandar"])
        familia    = str(row.get("Familia", componente[:3])).strip()

        if es_fabricado(familia):
            costo_calc, sub_det = calcular_semi(componente, cantidad, df_e, df_t, cache, resumen_global)
            detalle.extend(sub_det)
            cm_comp = cantidad * costo_calc
        else:
            costo_calc   = costo_std
            cm_comp      = cantidad * costo_calc
            cm_comprados += cm_comp

        cm_total += cm_comp
        detalle.append({
            "Código Semi": codigo_pt, "Descripción Semi": desc_pt,
            "Componente": componente, "Descripción Componente": desc_comp,
            "Familia": familia, "Tipo": "FABRICADO" if es_fabricado(familia) else "COMPRADO",
            "Proceso": proceso_pt, "Cantidad Total Req": cantidad,
            "Costo Calculado": costo_calc, "CM": cm_comp,
            "CIF": 0, "MOD": 0, "Total": cm_comp,
        })

    if proceso_pt not in resumen_global:
        resumen_global[proceso_pt] = {"CM": 0, "CIF": 0, "MOD": 0}
    resumen_global[proceso_pt]["CM"]  += cm_comprados
    resumen_global[proceso_pt]["CIF"] += cif_pt
    resumen_global[proceso_pt]["MOD"] += mod_pt

    total_pt    = cm_total + cif_pt + mod_pt
    costo_x_und = total_pt / cant_base_pt
    return resumen_global, detalle, costo_x_und


# ── Generar resumen global ──────────────────────────────────
lista_pt      = df_exp["Código PT"].unique()
filas_resumen = []
filas_detalle = []

for codigo_pt in lista_pt:
    df_pt_rows = df_exp[df_exp["Código PT"] == codigo_pt]
    if df_pt_rows.empty:
        continue
    desc_pt = df_pt_rows["Descripción PT"].iloc[0]
    resumen, detalle, _ = explotar_pt(codigo_pt, df_exp, df_tie)
    total_general = sum(v["CM"] + v["CIF"] + v["MOD"] for v in resumen.values())
    if total_general == 0:
        continue
    cant_base_pt = float(df_exp[df_exp["Código Semi"] == codigo_pt]["Cantidad Base"].iloc[0]) \
                   if not df_exp[df_exp["Código Semi"] == codigo_pt].empty else 1
    if cant_base_pt == 0:
        cant_base_pt = 1
    for proceso, valores in resumen.items():
        for tipo, monto in [("CM", valores["CM"]), ("CIF", valores["CIF"]), ("MOD", valores["MOD"])]:
            if monto > 0:
                filas_resumen.append({
                    "Código PT": codigo_pt, "Descripción PT": desc_pt,
                    "Proceso": proceso, "Tipo de Costo": f"{tipo} {proceso}",
                    "Costo Unitario": monto / cant_base_pt, "Total PT": total_general,
                })
    for d in detalle:
        d["Código PT"]      = codigo_pt
        d["Descripción PT"] = desc_pt
        filas_detalle.append(d)

df_resumen = pd.DataFrame(filas_resumen)
df_detalle = pd.DataFrame(filas_detalle)
if not df_resumen.empty:
    df_resumen["% del Total"] = (
        df_resumen["Costo Unitario"] /
        df_resumen.groupby("Código PT")["Costo Unitario"].transform("sum")
    )

# ── Dashboard ───────────────────────────────────────────────
app    = Dash(__name__)
server = app.server  # Necesario para Render/gunicorn

COLORES = {
    "bg": "#0F1923", "card": "#1A2633", "text": "#E8EDF2",
    "accent": "#00C8FF", "CM": "#2196F3", "MOD": "#4CAF50",
    "CIF": "#FF9800", "TOTAL": "#E91E63",
}

lista_pt_dd = df_resumen[["Código PT", "Descripción PT"]].drop_duplicates()


def get_maquinas_inyeccion(codigo_pt):
    """Máquinas de INYECCIÓN con T.Ciclo y Cav.Oper editables."""
    visitados = set()
    maquinas  = {}

    def buscar(codigo):
        if codigo in visitados:
            return
        visitados.add(codigo)
        hijos = df_exp[df_exp["Código Semi"] == codigo]
        for _, row in hijos.iterrows():
            comp    = str(row["Componente"])
            familia = str(row.get("Familia", comp[:3])).strip()
            t       = df_tie[df_tie["Código Semi"] == comp]
            if not t.empty:
                proc = str(t.iloc[0].get("Proceso", "")).strip().upper()
                if "INYEC" in proc:
                    t_row = t.iloc[0]
                    maq   = str(t_row.get("Maquina", comp))
                    if maq not in maquinas:
                        maquinas[maq] = {
                            "Maquina":   maq,
                            "T.Ciclo":   float(t_row.get("T.ciclo",        0) or 0),
                            "Cav.Oper":  float(t_row.get("Cav. Oper",      0) or 0),
                            "Cav.Tot":   float(t_row.get("Cav. Tot",       0) or 0),
                            "Tarifa Maq":float(t_row.get("Tarifa Maquina", 0) or 0),
                            "Tarifa MO": float(t_row.get("Tarifa MO",      0) or 0),
                        }
            if familia.startswith("231"):
                buscar(comp)

    buscar(codigo_pt)
    return list(maquinas.values())


def get_semis_otros_procesos(codigo_pt):
    """Otros procesos agrupados por máquina — incluye PT (ENCAJADO) y semis."""
    visitados  = set()
    maquinas   = {}
    excluidos  = ["INYEC", "MYT", "M&T", "MASAS"]

    def agregar_si_aplica(codigo):
        """Agrega el código a la tabla si su proceso no está excluido."""
        t = df_tie[df_tie["Código Semi"] == codigo]
        if not t.empty:
            proc = str(t.iloc[0].get("Proceso", "")).strip().upper()
            if not any(ex in proc for ex in excluidos) and proc != "SIN PROCESO":
                t_row = t.iloc[0]
                maq   = str(t_row.get("Maquina", codigo))
                key   = f"{proc}_{maq}"
                if key not in maquinas:
                    maquinas[key] = {
                        "Proceso":      proc,
                        "Maquina":      maq,
                        "Cantidad Base":float(t_row.get("Cantidad Base", 0) or 0),
                        "T.MO":         float(t_row.get("T.MO",          0) or 0),
                        "T.Maq":        float(t_row.get("T.Maq",         0) or 0),
                        "Cant.Opr":     float(t_row.get("Cant.Opr",      0) or 0),
                        "Tarifa Maq":   float(t_row.get("Tarifa Maquina",0) or 0),
                        "Tarifa MO":    float(t_row.get("Tarifa MO",     0) or 0),
                    }

    def buscar(codigo):
        if codigo in visitados:
            return
        visitados.add(codigo)
        # Verificar el propio código (para capturar ENCAJADO del PT)
        agregar_si_aplica(codigo)
        hijos = df_exp[df_exp["Código Semi"] == codigo]
        for _, row in hijos.iterrows():
            comp    = str(row["Componente"])
            familia = str(row.get("Familia", comp[:3])).strip()
            agregar_si_aplica(comp)
            if familia.startswith("231"):
                buscar(comp)

    buscar(codigo_pt)
    return list(maquinas.values())


app.layout = html.Div(
    style={"backgroundColor": COLORES["bg"], "minHeight": "100vh",
           "fontFamily": "'Segoe UI', sans-serif",
           "color": COLORES["text"], "padding": "20px"},
    children=[
        html.H1("📦 Reporte de Costos por Proceso",
                style={"color": COLORES["accent"], "textAlign": "center", "marginBottom": "5px"}),
        html.P(f"Generado: {datetime.now().strftime('%d/%m/%Y %H:%M')}",
               style={"color": "#7A9BBF", "textAlign": "center", "marginBottom": "25px"}),

        html.Div(style={"marginBottom": "25px"}, children=[
            html.Label("Selecciona un Producto Terminado:",
                       style={"color": COLORES["accent"], "fontWeight": "bold"}),
            dcc.Dropdown(
                id="selector-pt",
                options=[{"label": f"{r['Código PT']} — {r['Descripción PT']}",
                          "value": r["Código PT"]}
                         for _, r in lista_pt_dd.iterrows()],
                value=lista_pt_dd["Código PT"].iloc[0],
                style={"marginTop": "8px", "color": "#000"}
            ),
        ]),

        html.Div(id="kpis", style={"display": "flex", "gap": "15px",
                                    "marginBottom": "25px", "flexWrap": "wrap"}),

        # Simulador
        html.Div(style={"backgroundColor": COLORES["card"], "borderRadius": "12px",
                        "padding": "15px", "marginBottom": "20px",
                        "border": "1px solid #00C8FF"}, children=[
            html.H3("🔧 Simulador de Inyección — Modifica T.Ciclo y Cav.Oper por Máquina",
                    style={"color": COLORES["accent"], "fontSize": "16px",
                           "marginTop": 0, "marginBottom": "10px"}),
            html.P("Edita los valores en la tabla y presiona Recalcular.",
                   style={"color": "#7A9BBF", "fontSize": "12px", "marginBottom": "10px"}),
            dash_table.DataTable(
                id="tabla-simulador",
                columns=[
                    {"name": "Máquina",        "id": "Maquina",    "editable": False},
                    {"name": "T.Ciclo (s)",    "id": "T.Ciclo",    "editable": True,  "type": "numeric"},
                    {"name": "Cav.Oper",       "id": "Cav.Oper",   "editable": True,  "type": "numeric"},
                    {"name": "Cav.Tot",        "id": "Cav.Tot",    "editable": False},
                    {"name": "Cant.Base Calc", "id": "Cant.Base",  "editable": False},
                    {"name": "Tarifa Maq",     "id": "Tarifa Maq", "editable": False},
                    {"name": "Tarifa MO",      "id": "Tarifa MO",  "editable": False},
                ],
                style_header={"backgroundColor": "#1F3864", "color": "white", "fontWeight": "bold"},
                style_cell={"backgroundColor": "#1E2D3D", "color": COLORES["text"],
                            "border": "1px solid #2A3F54", "padding": "8px", "textAlign": "center"},
                style_data_conditional=[
                    {"if": {"column_editable": True},
                     "backgroundColor": "#0D2137", "border": "1px solid #00C8FF"},
                    {"if": {"row_index": "odd"}, "backgroundColor": "#162030"},
                ],
                editable=True, page_action="none",
            ),
        ]),

        # Botón recalcular — aplica a AMBOS simuladores
        html.Div(style={"textAlign": "center", "margin": "15px 0"}, children=[
            html.Button("🔄 Recalcular Todos los Procesos", id="btn-recalcular",
                style={"backgroundColor": COLORES["accent"], "color": "#000",
                       "fontWeight": "bold", "border": "none", "borderRadius": "8px",
                       "padding": "12px 40px", "cursor": "pointer", "fontSize": "15px",
                       "boxShadow": "0 0 15px rgba(0,200,255,0.4)"}),
            html.Div(id="msg-simulador",
                     style={"color": "#4CAF50", "fontSize": "13px", "marginTop": "8px"}),
        ]),

        # Simulador otros procesos
        html.Div(style={"backgroundColor": COLORES["card"], "borderRadius": "12px",
                        "padding": "15px", "marginBottom": "20px",
                        "border": "1px solid #4CAF50"}, children=[
            html.H3("⚙️ Simulador Otros Procesos — Modifica Cantidad Base, T.MO, T.Maq",
                    style={"color": "#4CAF50", "fontSize": "16px",
                           "marginTop": 0, "marginBottom": "10px"}),
            html.P("Edita los valores y presiona Recalcular para ver el impacto.",
                   style={"color": "#7A9BBF", "fontSize": "12px", "marginBottom": "10px"}),
            dash_table.DataTable(
                id="tabla-simulador-otros",
                columns=[
                    {"name": "Proceso",        "id": "Proceso",       "editable": False},
                    {"name": "Máquina",        "id": "Maquina",       "editable": False},
                    {"name": "Cantidad Base",  "id": "Cantidad Base", "editable": True,  "type": "numeric"},
                    {"name": "T.MO",           "id": "T.MO",          "editable": True,  "type": "numeric"},
                    {"name": "T.Maq",          "id": "T.Maq",         "editable": True,  "type": "numeric"},
                    {"name": "Cant.Opr",       "id": "Cant.Opr",      "editable": False},
                    {"name": "Tarifa Maq",     "id": "Tarifa Maq",    "editable": False},
                    {"name": "Tarifa MO",      "id": "Tarifa MO",     "editable": False},
                ],
                style_header={"backgroundColor": "#1F3864", "color": "white", "fontWeight": "bold"},
                style_cell={"backgroundColor": "#1E2D3D", "color": COLORES["text"],
                            "border": "1px solid #2A3F54", "padding": "8px", "textAlign": "center"},
                style_data_conditional=[
                    {"if": {"column_editable": True},
                     "backgroundColor": "#0D2137", "border": "1px solid #4CAF50"},
                    {"if": {"row_index": "odd"}, "backgroundColor": "#162030"},
                ],
                editable=True, page_action="none",
            ),
        ]),

        html.Div(style={"display": "grid", "gridTemplateColumns": "1fr 1fr",
                        "gap": "20px", "marginBottom": "20px"}, children=[
            html.Div(style={"backgroundColor": COLORES["card"],
                            "borderRadius": "12px", "padding": "15px"}, children=[
                html.H3("Cascada de Costos (S/)", style={"color": COLORES["accent"],
                        "fontSize": "16px", "marginTop": 0}),
                dcc.Graph(id="grafico-cascada")
            ]),
            html.Div(style={"backgroundColor": COLORES["card"],
                            "borderRadius": "12px", "padding": "15px"}, children=[
                html.H3("Cascada de Costos (%)", style={"color": COLORES["accent"],
                        "fontSize": "16px", "marginTop": 0}),
                dcc.Graph(id="grafico-cascada-pct")
            ]),
        ]),

        html.Div(style={"display": "grid", "gridTemplateColumns": "1fr 1fr",
                        "gap": "20px", "marginBottom": "20px"}, children=[
            html.Div(style={"backgroundColor": COLORES["card"],
                            "borderRadius": "12px", "padding": "15px"}, children=[
                html.H3("Costo por Proceso (%)", style={"color": COLORES["accent"],
                        "fontSize": "16px", "marginTop": 0}),
                dcc.Graph(id="grafico-donut")
            ]),
            html.Div(style={"backgroundColor": COLORES["card"],
                            "borderRadius": "12px", "padding": "15px"}, children=[
                html.H3("Costo por Proceso (S/)", style={"color": COLORES["accent"],
                        "fontSize": "16px", "marginTop": 0}),
                dcc.Graph(id="grafico-donut-soles")
            ]),
        ]),

        html.Div(style={"backgroundColor": COLORES["card"], "borderRadius": "12px",
                        "padding": "15px", "marginBottom": "20px"}, children=[
            html.H3("Resumen por Proceso", style={"color": COLORES["accent"],
                    "fontSize": "16px", "marginTop": 0}),
            dash_table.DataTable(
                id="tabla-resumen",
                style_header={"backgroundColor": "#1F3864", "color": "white", "fontWeight": "bold"},
                style_cell={"backgroundColor": "#1E2D3D", "color": COLORES["text"],
                            "border": "1px solid #2A3F54", "padding": "8px", "textAlign": "center"},
                style_data_conditional=[{"if": {"row_index": "odd"}, "backgroundColor": "#162030"}],
                page_size=15,
            )
        ]),

        html.Div(style={"backgroundColor": COLORES["card"], "borderRadius": "12px",
                        "padding": "15px"}, children=[
            html.H3("Detalle por Componente", style={"color": COLORES["accent"],
                    "fontSize": "16px", "marginTop": 0}),
            dash_table.DataTable(
                id="tabla-detalle",
                style_header={"backgroundColor": "#1F3864", "color": "white", "fontWeight": "bold"},
                style_cell={"backgroundColor": "#1E2D3D", "color": COLORES["text"],
                            "border": "1px solid #2A3F54", "padding": "8px", "textAlign": "center"},
                style_data_conditional=[{"if": {"row_index": "odd"}, "backgroundColor": "#162030"}],
                page_size=15, filter_action="native", sort_action="native",
            )
        ]),
    ]
)


@app.callback(
    Output("tabla-simulador", "data"),
    Output("tabla-simulador-otros", "data"),
    Input("selector-pt", "value"),
)
def cargar_simuladores(codigo_pt):
    # Inyección
    maquinas = get_maquinas_inyeccion(codigo_pt)
    rows_iny = []
    for m in maquinas:
        cant_base = round((3600 / m["T.Ciclo"]) * m["Cav.Oper"] * 24, 2)                     if m["T.Ciclo"] > 0 else 0
        rows_iny.append({
            "Maquina":   m["Maquina"],   "T.Ciclo":   m["T.Ciclo"],
            "Cav.Oper":  m["Cav.Oper"],  "Cav.Tot":   m["Cav.Tot"],
            "Cant.Base": cant_base,       "Tarifa Maq":m["Tarifa Maq"],
            "Tarifa MO": m["Tarifa MO"],
        })
    # Otros procesos
    otros    = get_semis_otros_procesos(codigo_pt)
    rows_otros = []
    for s in otros:
        rows_otros.append({
            "Proceso":      s["Proceso"],
            "Maquina":      s["Maquina"],
            "Cantidad Base":s["Cantidad Base"],
            "T.MO":         s["T.MO"],
            "T.Maq":        s["T.Maq"],
            "Cant.Opr":     s["Cant.Opr"],
            "Tarifa Maq":   s["Tarifa Maq"],
            "Tarifa MO":    s["Tarifa MO"],
        })
    return rows_iny, rows_otros


@app.callback(
    Output("kpis",                "children"),
    Output("grafico-cascada",     "figure"),
    Output("grafico-cascada-pct", "figure"),
    Output("grafico-donut",       "figure"),
    Output("grafico-donut-soles", "figure"),
    Output("tabla-resumen",       "data"),
    Output("tabla-resumen",       "columns"),
    Output("tabla-detalle",       "data"),
    Output("tabla-detalle",       "columns"),
    Output("msg-simulador",       "children"),
    Input("btn-recalcular",       "n_clicks"),
    Input("selector-pt",          "value"),
    State("tabla-simulador",      "data"),
    State("tabla-simulador-otros","data"),
)
def actualizar(n_clicks, codigo_pt, datos_simulador, datos_otros):
    df_tie_sim = df_tie.copy()
    # Aplicar cambios de inyección por máquina
    if datos_simulador:
        for row in datos_simulador:
            maquina  = str(row.get("Maquina", ""))
            t_ciclo  = float(row.get("T.Ciclo", 0) or 0)
            cav_oper = float(row.get("Cav.Oper", 0) or 0)
            if t_ciclo > 0 and cav_oper > 0 and maquina:
                nueva_base = (3600 / t_ciclo) * cav_oper * 24
                mask = df_tie_sim["Maquina"].astype(str).str.strip() == maquina
                df_tie_sim.loc[mask, "Cantidad Base"] = nueva_base
    # Aplicar cambios de otros procesos por máquina
    if datos_otros:
        for row in datos_otros:
            maquina    = str(row.get("Maquina", ""))
            nueva_base = float(row.get("Cantidad Base", 0) or 0)
            nuevo_tmo  = float(row.get("T.MO",          0) or 0)
            nuevo_tmaq = float(row.get("T.Maq",         0) or 0)
            if maquina and nueva_base > 0:
                # Aplica a todos los semis que usan esta máquina
                mask = df_tie_sim["Maquina"].astype(str).str.strip() == maquina
                df_tie_sim.loc[mask, "Cantidad Base"] = nueva_base
                if nuevo_tmo  > 0: df_tie_sim.loc[mask, "T.MO"]  = nuevo_tmo
                if nuevo_tmaq > 0: df_tie_sim.loc[mask, "T.Maq"] = nuevo_tmaq

    resumen_sim, detalle_sim, _ = explotar_pt(codigo_pt, df_exp, df_tie_sim)

    cant_base_pt = float(df_exp[df_exp["Código Semi"] == codigo_pt]["Cantidad Base"].iloc[0]) \
                   if not df_exp[df_exp["Código Semi"] == codigo_pt].empty else 1
    if cant_base_pt == 0:
        cant_base_pt = 1

    filas = []
    for proceso, valores in resumen_sim.items():
        for tipo, monto in [("CM", valores["CM"]), ("CIF", valores["CIF"]), ("MOD", valores["MOD"])]:
            if monto > 0:
                filas.append({
                    "Proceso": proceso, "Tipo de Costo": f"{tipo} {proceso}",
                    "Costo Unitario": monto / cant_base_pt,
                })

    df_pt = pd.DataFrame(filas)
    if df_pt.empty:
        df_pt = df_resumen[df_resumen["Código PT"] == codigo_pt].copy()
    else:
        total = df_pt["Costo Unitario"].sum()
        df_pt["% del Total"] = df_pt["Costo Unitario"] / total if total > 0 else 0

    msg    = f"✅ Recalculado — {datetime.now().strftime('%H:%M:%S')}" if n_clicks else ""
    df_det = df_detalle[df_detalle["Código PT"] == codigo_pt].copy()
    total  = df_pt["Costo Unitario"].sum()
    tot_cm  = df_pt[df_pt["Tipo de Costo"].str.startswith("CM")]["Costo Unitario"].sum()
    tot_mod = df_pt[df_pt["Tipo de Costo"].str.startswith("MOD")]["Costo Unitario"].sum()
    tot_cif = df_pt[df_pt["Tipo de Costo"].str.startswith("CIF")]["Costo Unitario"].sum()

    def kpi(titulo, valor, color):
        return html.Div(
            style={"backgroundColor": COLORES["card"], "borderLeft": f"4px solid {color}",
                   "borderRadius": "10px", "padding": "15px 20px",
                   "flex": "1", "minWidth": "160px"},
            children=[
                html.P(titulo, style={"margin": 0, "fontSize": "12px", "color": "#7A9BBF"}),
                html.H2(f"S/ {valor:.6f}",
                        style={"margin": "5px 0 0 0", "color": color, "fontSize": "18px"}),
            ]
        )

    kpis_elem = [
        kpi("💰 Costo x Und", total,   COLORES["accent"]),
        kpi("🧱 CM Total",    tot_cm,  COLORES["CM"]),
        kpi("👷 MOD Total",   tot_mod, COLORES["MOD"]),
        kpi("⚙️ CIF Total",   tot_cif, COLORES["CIF"]),
    ]

    labels       = list(df_pt["Tipo de Costo"]) + ["TOTAL"]
    valores      = list(df_pt["Costo Unitario"]) + [total]
    measures     = ["relative"] * len(df_pt) + ["total"]

    fig_cas = go.Figure(go.Waterfall(
        x=labels, y=valores, measure=measures,
        text=[f"S/ {v:.4f}" for v in valores], textposition="outside",
        increasing=dict(marker_color=COLORES["CM"]),
        totals=dict(marker_color=COLORES["TOTAL"]),
        connector=dict(line=dict(color="#4A5568", width=1)),
        hovertemplate="<b>%{x}</b><br>S/ %{y:.6f}<extra></extra>"
    ))
    fig_cas.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
                          plot_bgcolor="rgba(0,0,0,0)",
                          margin=dict(l=10, r=10, t=30, b=80),
                          xaxis_tickangle=-35, showlegend=False)

    pcts         = list(df_pt["% del Total"] * 100) + [100.0]
    measures_pct = ["relative"] * len(df_pt) + ["total"]
    fig_cas_pct  = go.Figure(go.Waterfall(
        x=labels, y=pcts, measure=measures_pct,
        text=[f"{v:.1f}%" for v in pcts], textposition="outside",
        increasing=dict(marker_color=COLORES["MOD"]),
        totals=dict(marker_color=COLORES["TOTAL"]),
        connector=dict(line=dict(color="#4A5568", width=1)),
        hovertemplate="<b>%{x}</b><br>%{y:.1f}%<extra></extra>"
    ))
    fig_cas_pct.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
                              plot_bgcolor="rgba(0,0,0,0)", yaxis=dict(ticksuffix="%"),
                              margin=dict(l=10, r=10, t=30, b=80),
                              xaxis_tickangle=-35, showlegend=False)

    resumen_proc = df_pt.groupby("Proceso")["Costo Unitario"].sum().reset_index()
    paleta       = ["#2196F3", "#4CAF50", "#FF9800", "#E91E63", "#9C27B0", "#00BCD4", "#FF5722"]

    # Dona en porcentaje
    fig_don = go.Figure(go.Pie(
        labels=resumen_proc["Proceso"], values=resumen_proc["Costo Unitario"],
        hole=0.55, marker_colors=paleta[:len(resumen_proc)],
        textinfo="label+percent",
        hovertemplate="<b>%{label}</b><br>S/ %{value:.6f}<br>%{percent}<extra></extra>"
    ))
    fig_don.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
                          margin=dict(l=10, r=10, t=10, b=10))

    # Dona en soles
    fig_don_soles = go.Figure(go.Pie(
        labels=resumen_proc["Proceso"], values=resumen_proc["Costo Unitario"],
        hole=0.55, marker_colors=paleta[:len(resumen_proc)],
        textinfo="label+value",
        texttemplate="<b>%{label}</b><br>S/ %{value:.4f}",
        hovertemplate="<b>%{label}</b><br>S/ %{value:.6f}<br>%{percent}<extra></extra>"
    ))
    fig_don_soles.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
                                margin=dict(l=10, r=10, t=10, b=10))

    df_res_fmt = df_pt[["Tipo de Costo", "Costo Unitario", "% del Total"]].copy()
    df_res_fmt["Costo Unitario"] = df_res_fmt["Costo Unitario"].map("S/ {:.6f}".format)
    df_res_fmt["% del Total"]    = df_res_fmt["% del Total"].map("{:.1%}".format)
    cols_res = [{"name": c, "id": c} for c in df_res_fmt.columns]

    cols_show  = ["Código Semi", "Descripción Semi", "Componente", "Descripción Componente",
                  "Proceso", "Tipo", "Cantidad Total Req", "Costo Calculado",
                  "CM", "CIF", "MOD", "Total"]
    cols_show  = [c for c in cols_show if c in df_det.columns]
    df_det_fmt = df_det[cols_show].copy()
    for c in ["Costo Calculado", "CM", "CIF", "MOD", "Total"]:
        if c in df_det_fmt.columns:
            df_det_fmt[c] = df_det_fmt[c].map("{:.6f}".format)
    cols_det = [{"name": c, "id": c} for c in df_det_fmt.columns]

    return (kpis_elem, fig_cas, fig_cas_pct, fig_don, fig_don_soles,
            df_res_fmt.to_dict("records"), cols_res,
            df_det_fmt.to_dict("records"), cols_det, msg)


if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=int(os.environ.get("PORT", 8050)))
