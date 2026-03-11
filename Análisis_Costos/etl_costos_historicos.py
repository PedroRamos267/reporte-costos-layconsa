"""
ETL - Costos Históricos Layconsa
================================
Fuente : Reportes_Costos.xlsx
Output : costos_historicos_limpio.xlsx  (listo para Power BI)

Lógica principal:
  - Base: Hoja "Cuadro Ordenes BEAS" (resumen por OP)
  - Enriquece con costo unitario real desde "Ingresos de Producción X Fechas"
  - Solo órdenes con ESTADO = CERRADA
  - Periodo mensual = Mes/Año de la columna Fecha de BEAS
  - Agrega por Año, Mes, SKU → CM, CIF, MO, Costo Total, Costo Unitario
"""

import pandas as pd
import os
from datetime import datetime

# ─────────────────────────────────────────────
# CONFIGURACIÓN  ← ajusta solo estas rutas
# ─────────────────────────────────────────────
RUTA_INPUT = r"D:\Users\pramos\Desktop\Reporte_Costos_Web\Análisis_Costos\Reportes_Costos.xlsx"
RUTA_OUTPUT = r"D:\Users\pramos\Desktop\Reporte_Costos_Web\Análisis_Costos\costos_historicos_limpio.xlsx"

# Nombres exactos de las hojas (ajusta si difieren)
HOJA_BEAS      = "Cuadro Ordenes BEAS"
HOJA_INGRESOS  = "Ingresos de Producción X Fechas"
HOJA_CONSUMOS  = "Consumos de Producción X Fechas"   # opcional, para drill-down
HOJA_TIEMPOS   = "Tiempos de Producción X Fecha"     # opcional, para drill-down

# Palabras clave que indican orden CERRADA (en mayúsculas)
ESTADOS_CERRADOS = ["CERRADA", "CERRADO", "CLOSED"]

# ─────────────────────────────────────────────
# 1. CARGA DE DATOS
# ─────────────────────────────────────────────
print("Cargando datos...")

xls = pd.ExcelFile(RUTA_INPUT)
print(f"  Hojas disponibles: {xls.sheet_names}")

df_beas     = pd.read_excel(xls, sheet_name=HOJA_BEAS)
df_ingresos = pd.read_excel(xls, sheet_name=HOJA_INGRESOS)

print(f"  BEAS: {len(df_beas):,} filas")
print(f"  Ingresos: {len(df_ingresos):,} filas")

# ─────────────────────────────────────────────
# 2. LIMPIEZA BEAS
# ─────────────────────────────────────────────
print("\nProcesando BEAS...")

# Normalizar nombres de columnas (quitar espacios, mayúsculas)
df_beas.columns = df_beas.columns.str.strip()

# Filtrar solo órdenes CERRADAS
df_beas["ESTADO_NORM"] = df_beas["ESTADO"].astype(str).str.upper().str.strip()
df_beas = df_beas[df_beas["ESTADO_NORM"].isin(ESTADOS_CERRADOS)].copy()
print(f"  OPs cerradas: {len(df_beas):,} filas")

# Parsear fecha
df_beas["Fecha"] = pd.to_datetime(df_beas["Fecha"], errors="coerce", dayfirst=True)
df_beas = df_beas.dropna(subset=["Fecha"])

# Extraer periodo
df_beas["Año"]  = df_beas["Fecha"].dt.year
df_beas["Mes"]  = df_beas["Fecha"].dt.month
df_beas["Periodo"] = df_beas["Fecha"].dt.to_period("M").astype(str)  # "2024-03"

# Renombrar columnas clave
rename_beas = {
    "CODIGO"      : "SKU",
    "ARTICULO"    : "Descripcion",
    "PLANIFICADO" : "Cant_Planificada",
    "ING CANTIDAD": "Cant_Ingresada",
    "CONSUMO"     : "CM",
    "GIF"         : "CIF",
    "MO"          : "MOD",
    "OP EXTERNAS" : "OP_Externas",
    "INGRESO"     : "Valor_Ingreso",
    "DIFERENCIAS" : "Diferencia",
}
df_beas = df_beas.rename(columns=rename_beas)

# Columnas numéricas
cols_num = ["CM", "CIF", "MOD", "OP_Externas", "Valor_Ingreso", "Cant_Ingresada", "Cant_Planificada"]
for c in cols_num:
    if c in df_beas.columns:
        df_beas[c] = pd.to_numeric(df_beas[c], errors="coerce").fillna(0)

# Costo total de fabricación por fila
df_beas["Costo_Total"] = df_beas["CM"] + df_beas["CIF"] + df_beas["MOD"] + df_beas["OP_Externas"]

# ─────────────────────────────────────────────
# 3. COSTO UNITARIO REAL (desde Ingresos)
# ─────────────────────────────────────────────
print("Procesando Ingresos para costo unitario...")

df_ingresos.columns = df_ingresos.columns.str.strip()

# Costo unitario por OP + Posición (promedio ponderado si hay varias líneas)
rename_ing = {
    "Código"      : "SKU",
    "Cantidad"    : "Cant_Ingresada_ing",
    "Costo Unit." : "Costo_Unitario",
    "Valor"       : "Valor_ing",
    "OP"          : "OP",
    "Posición"    : "Posicion",
}
df_ingresos = df_ingresos.rename(columns={k: v for k, v in rename_ing.items() if k in df_ingresos.columns})

for c in ["Cant_Ingresada_ing", "Costo_Unitario", "Valor_ing"]:
    if c in df_ingresos.columns:
        df_ingresos[c] = pd.to_numeric(df_ingresos[c], errors="coerce").fillna(0)

# Costo unitario ponderado por OP
cu_por_op = (
    df_ingresos
    .groupby("OP")
    .apply(lambda g: g["Valor_ing"].sum() / g["Cant_Ingresada_ing"].sum()
           if g["Cant_Ingresada_ing"].sum() > 0 else 0)
    .reset_index()
    .rename(columns={0: "Costo_Unit_Real"})
)

# Merge al BEAS
df_beas = df_beas.merge(cu_por_op, on="OP", how="left")
df_beas["Costo_Unit_Real"] = df_beas["Costo_Unit_Real"].fillna(0)

# ─────────────────────────────────────────────
# 4. TABLA DETALLE (1 fila por OP)
# ─────────────────────────────────────────────
cols_detalle = [
    "Periodo", "Año", "Mes", "OP", "Posicion",
    "SKU", "Descripcion",
    "Cant_Planificada", "Cant_Ingresada",
    "CM", "CIF", "MOD", "OP_Externas", "Costo_Total",
    "Valor_Ingreso", "Diferencia",
    "Costo_Unit_Real",
]
cols_detalle = [c for c in cols_detalle if c in df_beas.columns]
df_detalle = df_beas[cols_detalle].copy()

# ─────────────────────────────────────────────
# 5. TABLA RESUMEN MENSUAL (agregado por Periodo + SKU)
# ─────────────────────────────────────────────
print("Generando resumen mensual...")

df_resumen = (
    df_beas
    .groupby(["Periodo", "Año", "Mes", "SKU", "Descripcion"])
    .agg(
        OPs_Producidas       = ("OP", "nunique"),
        Cant_Total_Ingresada = ("Cant_Ingresada", "sum"),
        CM_Total             = ("CM", "sum"),
        CIF_Total            = ("CIF", "sum"),
        MOD_Total            = ("MOD", "sum"),
        OP_Ext_Total         = ("OP_Externas", "sum"),
        Costo_Total          = ("Costo_Total", "sum"),
        Valor_Ingreso_Total  = ("Valor_Ingreso", "sum"),
    )
    .reset_index()
)

# Costo unitario promedio del mes (Costo_Total / Cant_Total_Ingresada)
df_resumen["Costo_Unit_Mes"] = (
    df_resumen["Costo_Total"] / df_resumen["Cant_Total_Ingresada"].replace(0, pd.NA)
).fillna(0)

# % participación de cada componente
df_resumen["CM_%"]  = (df_resumen["CM_Total"]  / df_resumen["Costo_Total"].replace(0, pd.NA) * 100).fillna(0).round(1)
df_resumen["CIF_%"] = (df_resumen["CIF_Total"] / df_resumen["Costo_Total"].replace(0, pd.NA) * 100).fillna(0).round(1)
df_resumen["MOD_%"] = (df_resumen["MOD_Total"] / df_resumen["Costo_Total"].replace(0, pd.NA) * 100).fillna(0).round(1)

# Variación mes a mes por SKU (%)
df_resumen = df_resumen.sort_values(["SKU", "Año", "Mes"])
df_resumen["Costo_Unit_Mes_Ant"] = df_resumen.groupby("SKU")["Costo_Unit_Mes"].shift(1)
df_resumen["Variacion_%"] = (
    (df_resumen["Costo_Unit_Mes"] - df_resumen["Costo_Unit_Mes_Ant"])
    / df_resumen["Costo_Unit_Mes_Ant"].replace(0, pd.NA) * 100
).fillna(0).round(1)

# ─────────────────────────────────────────────
# 6. TABLA RESUMEN ANUAL
# ─────────────────────────────────────────────
df_anual = (
    df_beas
    .groupby(["Año", "SKU", "Descripcion"])
    .agg(
        OPs_Producidas       = ("OP", "nunique"),
        Cant_Total_Ingresada = ("Cant_Ingresada", "sum"),
        CM_Total             = ("CM", "sum"),
        CIF_Total            = ("CIF", "sum"),
        MOD_Total            = ("MOD", "sum"),
        OP_Ext_Total         = ("OP_Externas", "sum"),
        Costo_Total          = ("Costo_Total", "sum"),
    )
    .reset_index()
)
df_anual["Costo_Unit_Año"] = (
    df_anual["Costo_Total"] / df_anual["Cant_Total_Ingresada"].replace(0, pd.NA)
).fillna(0)

# ─────────────────────────────────────────────
# 7. EXPORTAR A EXCEL (multi-hoja para Power BI)
# ─────────────────────────────────────────────
print(f"\nExportando a: {RUTA_OUTPUT}")

with pd.ExcelWriter(RUTA_OUTPUT, engine="openpyxl") as writer:

    df_resumen.to_excel(writer, sheet_name="Resumen_Mensual", index=False)
    df_anual.to_excel(writer,   sheet_name="Resumen_Anual",   index=False)
    df_detalle.to_excel(writer, sheet_name="Detalle_OP",      index=False)

    # Hoja de metadata
    meta = pd.DataFrame({
        "Campo": ["Fecha de generación", "Archivo fuente", "OPs cerradas procesadas",
                  "SKUs únicos", "Periodos cubiertos"],
        "Valor": [
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            RUTA_INPUT,
            len(df_beas["OP"].unique()),
            len(df_resumen["SKU"].unique()),
            f"{df_resumen['Periodo'].min()} → {df_resumen['Periodo'].max()}",
        ]
    })
    meta.to_excel(writer, sheet_name="Metadata", index=False)

print("\n✅ ETL completado exitosamente.")
print(f"   Resumen mensual : {len(df_resumen):,} filas")
print(f"   Resumen anual   : {len(df_anual):,} filas")
print(f"   Detalle OP      : {len(df_detalle):,} filas")
print(f"   SKUs únicos     : {df_resumen['SKU'].nunique():,}")
print(f"   Periodos        : {df_resumen['Periodo'].min()} → {df_resumen['Periodo'].max()}")
