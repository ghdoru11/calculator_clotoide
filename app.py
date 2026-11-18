"""Interfață web minimală pentru motorul analitic de clotoide v1.4."""
from __future__ import annotations

import csv
import io
import json
import math
import zipfile
from dataclasses import asdict

import streamlit as st

import clotoida_engine as engine
from table_views import render_html


def dataframe(rows: list[dict]) -> None:
    st.dataframe(rows, use_container_width=True, hide_index=True)


def as_rows(values: dict) -> list[dict]:
    # Notațiile din manual sunt folosite în interfață; cheile interne/JSON rămân compatibile.
    etichete = {
        "delta_g": "αc — unghi total la centru (g)",
        "delta_total_g": "αc — unghi total la centru (g)",
        "delta_arc_central_g": "α′c — unghiul arcului intermediar (g)",
        "p_m": "ΔR — strămutarea cercului (m)",
        "delta_m": "ΔR — strămutarea cercului (m)",
        "delta1": "δ₁ — strămutare, clotoidă de bază",
    }

    def fmt(value):
        if value is None:
            return "—"
        if isinstance(value, bool):
            return "Da" if value else "Nu"
        if isinstance(value, float):
            return f"{value:.9f}" if math.isfinite(value) else str(value)
        return str(value)

    return [{"Element": etichete.get(key, key), "Valoare": fmt(value)} for key, value in values.items()]


def csv_table_bytes(rows: list[dict]) -> bytes:
    if not rows:
        return b""
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return ("\ufeff" + buf.getvalue()).encode("utf-8")


def as_archive(summary: dict, tables: dict[str, list[dict]], mode: str) -> bytes:
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, mode="w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("rezultate.json", json.dumps(summary, ensure_ascii=False, indent=2, default=str))
        z.writestr("tabele_trasare_formatate.html", html_document(tables, mode))
        for name, rows in tables.items():
            z.writestr(f"{name}.csv", csv_table_bytes(rows))
    return raw.getvalue()


def html_document(tables: dict[str, list[dict]], mode: str) -> str:
    body = "".join(render_html(name, rows, mode) for name, rows in tables.items())
    return (
        '<!DOCTYPE html><html lang="ro"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>Tabele de trasare</title></head><body>'
        + body + '</body></html>'
    )


st.set_page_config(page_title="Calculator curbe rutiere", page_icon="📐", layout="wide")
st.title("Calculator curbe rutiere")
st.caption("Motor analitic v1.4 · Unghiuri în grade centesimale (g) · Lungimi în metri")

mode = st.radio(
    "Tipul racordării",
    ["Arc de cerc", "Clotoidă", "CLC"],
    horizontal=True,
)

with st.form("parameters"):
    c1, c2, c3 = st.columns(3)
    with c1:
        R = st.number_input("Raza R (m)", min_value=0.001, value=120.0, step=1.0, format="%.4f")
    if mode in {"CLC", "Clotoidă"}:
        with c2:
            L = st.number_input("Lungimea clotoidei L (m)", min_value=0.001, value=38.4, step=1.0, format="%.4f")
    else:
        L = None
    if mode in {"Arc de cerc", "CLC"}:
        with c3:
            delta = st.number_input("Unghiul total la centru αc (g)", min_value=0.001, max_value=199.999, value=118.93055, format="%.6f")
    else:
        delta = None
    with c1:
        n = st.number_input("Numărul de intervale de trasare", min_value=1, max_value=500, value=10, step=1)
    submit = st.form_submit_button("Calculează", use_container_width=True)

if submit:
    try:
        summary: dict = {}
        tables: dict[str, list[dict]] = {}

        if mode == "Arc de cerc":
            assert delta is not None
            rad = engine.gon_to_rad(delta)
            summary = {
                "tip": mode, "R_m": R, "delta_g": delta,
                "tangenta_T_m": R * math.tan(rad / 2),
                "bisectoare_B_m": R * (1 / math.cos(rad / 2) - 1),
                "coarda_m": 2 * R * math.sin(rad / 2),
                "lungime_arc_C_m": R * rad,
            }
            tables["arc_cerc"] = [asdict(p) for p in engine.tabel_arc_cerc_simplu(R, delta, n, "complet")]

        elif mode == "Clotoidă":
            assert L is not None
            summary = engine.elemente_anexe(R_m=R, L_m=L)
            tables["clotoida"] = [asdict(p) for p in engine.tabel_trasare(R, L, n)]

        elif mode == "CLC":
            assert L is not None and delta is not None
            main = engine.caz1_clc_simetrica(delta, R, L, n=n)
            summary = engine.elemente_anexe(R_m=R, L_m=L, delta_g=delta)
            summary["geometrie_CLC"] = {k: v for k, v in main.items() if k != "tabel_clotoida"}
            tables["clotoida_intrare"] = [asdict(p) for p in engine.tabel_trasare(R, L, n)]
            tables["arc_central_Oi_0_0"] = [asdict(p) for p in engine.tabel_arc_central_clc(R, L, delta, n)]

        st.session_state["result"] = {"mode": mode, "summary": summary, "tables": tables}

    except (ValueError, ArithmeticError, OverflowError) as exc:
        st.error(str(exc))

result = st.session_state.get("result")
if result is not None:
    saved_mode = result["mode"]
    summary = result["summary"]
    tables = result["tables"]

    st.subheader("Elemente principale")
    if saved_mode == "Arc de cerc":
        dataframe(as_rows(summary))
    else:
        if saved_mode == "CLC":
            st.info("Arcul central este raportat atât local la Si, cât și în sistemul Oi=(0,0), în continuarea clotoidei de intrare. Clotoida de ieșire este simetrică.")
            with st.expander("Racordare CLC", expanded=True):
                dataframe(as_rows(summary["geometrie_CLC"]))
        with st.expander("Clotoida reală", expanded=True):
            dataframe(as_rows(summary["clotoida_reala"]))
        with st.expander("Anexa I — clotoida de bază A=1", expanded=True):
            dataframe(as_rows(summary["clotoida_baza_A_1"]))
        with st.expander("Anexa II — rapoarte independente de A", expanded=True):
            dataframe(as_rows(summary["rapoarte_anexa_II"]))

    st.subheader("Tabele de trasare")
    for title, rows in tables.items():
        with st.expander(title.replace("_", " "), expanded=True):
            st.markdown(render_html(title, rows, saved_mode), unsafe_allow_html=True)

    st.download_button(
        "Descarcă tabelele formatate (HTML)",
        data=html_document(tables, saved_mode).encode("utf-8"),
        file_name="tabele_trasare_formatate.html",
        mime="text/html",
        use_container_width=True,
    )
    st.download_button(
        "Descarcă rezultate (ZIP: HTML + JSON + CSV)",
        data=as_archive(summary, tables, saved_mode),
        file_name="elemente_curbe.zip",
        mime="application/zip",
        use_container_width=True,
    )
    st.caption("Valorile din anexe sunt reconstruite analitic și confruntate selectiv cu materialul scanat, nu certificate normativ. Pentru utilizare în proiecte, efectuați verificarea inginerească.")
