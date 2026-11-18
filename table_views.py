"""Tabele de trasare cu antete tehnice grupate.
Acest modul formatează doar vizual datele calculate; nu modifică geometria.
"""
from __future__ import annotations

from html import escape
import math
from typing import Any, Sequence


STYLE = """<style>
.trasare-wrap { overflow-x:auto; width:100%; border:1px solid #9ca3af; border-radius:3px; margin:.25rem 0 1rem; }
.trasare { border-collapse:collapse; background:#fff; color:#101010; width:100%; min-width:830px;
  font-family:Arial,Helvetica,sans-serif; font-size:13px; font-variant-numeric:tabular-nums; }
.trasare th,.trasare td { border:1px solid #444; padding:5px 7px; text-align:center; vertical-align:middle; white-space:nowrap; }
.trasare thead th { background:#fafafa; font-weight:500; }
.trasare thead tr.trasare-title th { background:white; font-size:14px; font-weight:600; padding:7px; }
.trasare tbody tr:nth-child(even) td { background:#f7f7f7; }
.trasare tbody tr:hover td { background:#eaf4ff; }
.trasare tbody td:first-child { font-weight:500; }
.trasare .trasare-unit { color:#444; font-size:11px; }
</style>"""


def num(value: Any, digits: int = 4) -> str:
    if value is None:
        return "∞"
    if isinstance(value, (int, float)):
        if math.isinf(value):
            return "∞" if value > 0 else "−∞"
        if math.isnan(value):
            return "—"
        return f"{value:.{digits}f}"
    return escape(str(value))


def _th(text: str, *, colspan: int = 1, rowspan: int = 1) -> str:
    attrs = (f' colspan="{colspan}"' if colspan > 1 else '') + (f' rowspan="{rowspan}"' if rowspan > 1 else '')
    return f"<th{attrs}>{text}</th>"


def _table(title: str, header: str, rows: Sequence[Sequence[Any]], widths: int, two_decimal_columns: set[int] | None = None) -> str:
    parts = [STYLE, '<div class="trasare-wrap">', '<table class="trasare">',
             '<thead>', '<tr class="trasare-title">', _th(escape(title), colspan=widths), '</tr>', header, '</thead>', '<tbody>']
    special = two_decimal_columns or set()
    for record in rows:
        if len(record) != widths:
            raise ValueError(f"Tabelul {title!r} are {len(record)} valori pe rând în loc de {widths}.")
        parts.append('<tr>')
        for i,value in enumerate(record):
            parts.append(f'<td>{num(value, 2 if i in special else 4)}</td>')
        parts.append('</tr>')
    parts.extend(['</tbody>', '</table>', '</div>'])
    return ''.join(parts)


def clothoid_html(points: list[dict], *, is_clc: bool = False, heading: str = 'CURBA – COORDONATE DE TRASARE PENTRU CLOTOIDĂ') -> str:
    """Ca în modelul CAD: de la capătul clotoidei spre origine (Si ... Oi)."""
    if not points:
        return ''
    last = max(points, key=lambda p: p['s_m'])
    A = math.sqrt(last['s_m'] * last['rho_m'])
    ordered = sorted(points, key=lambda p:p['s_m'], reverse=True)
    rows = []
    for i,p in enumerate(ordered):
        name = ('Si' if is_clc else 'S') if i == 0 else (('Oi' if is_clc else 'O') if i == len(ordered)-1 else str(i))
        rho = p['rho_m']
        rows.append([
            name, p['alfa_g'], p['phi_g'], p['r_m']/A, p['r_m'],
            p['x_m']/A, p['x_m'], p['y_m']/A, p['y_m'],
            p['s_m']/A, p['s_m'], None if rho is None else rho/A,
            rho, p['gamma_g'],
        ])
    header = ('<tr>'
      + _th('PICHET',rowspan=2)
      + _th('α₀')
      + _th('Coordonate polare',colspan=3)
      + _th('Coordonate carteziene',colspan=4)
      + _th('Lungimea arcului',colspan=2)
      + _th('Raze de curbură',colspan=2)
      + _th('γ') + '</tr><tr>'
      + ''.join(_th(v) for v in ['(g,c,cc)','Φ','r₁','r','x₁','x','y₁','y','s₁','s','ρ₁','ρ','(g,c,cc)'])
      + '</tr>')
    return _table(heading, header, rows, 14)


def clc_arc_html(points: list[dict]) -> str:
    """Arcul circular cu două sisteme de coordonate: local Si și general Oi."""
    header = ('<tr>'
      + _th('Pichet',rowspan=2)
      + _th('Coordonate polare<br>față de Si',colspan=2)
      + _th('Coordonate carteziene<br>față de Si',colspan=2)
      + _th('Coordonate polare<br>față de Oi',colspan=2)
      + _th('Coordonate carteziene<br>față de Oi',colspan=2)
      + _th('Lungime<br>arc, C′',rowspan=2) + '</tr><tr>'
      + ''.join(_th(v) for v in ['r′','Φ′','x′','y′','r','Φ','x','y']) + '</tr>')
    rows = []
    for p in points:
        rows.append([
            p['pichet'], p['r_m'], p['phi_g'], p['x_local_m'], p['y_local_m'],
            p['r_global_m'], p['phi_global_g'], p['x_global_m'], p['y_global_m'], p['c_m'],
        ])
    return _table('CURBA – COORDONATE DE TRASARE PENTRU VIRAJUL ARC DE CERC', header, rows, 10, {9})


def simple_arc_html(points: list[dict]) -> str:
    header = ('<tr>'
      + _th('Pichet',rowspan=2)
      + _th('Coordonate polare',colspan=2)
      + _th('Coordonate carteziene',colspan=2)
      + _th('Lungimea arcului<br>de cerc',rowspan=2) + '</tr><tr>'
      + ''.join(_th(v) for v in ['Φ (g)','r=2RsinΦ','x=rcosΦ','y=rsinΦ'])
      + '</tr>')
    rows = [[p['pichet'],p['phi_g'],p['r_m'],p['x_local_m'],p['y_local_m'],p['c_m']] for p in points]
    return _table('CURBA – COORDONATE DE TRASARE (ARC DE CERC)', header, rows, 6, {5})


def render_html(name: str, rows: list[dict], mode: str) -> str:
    if name == 'arc_cerc':
        return simple_arc_html(rows)
    if name == 'arc_central_Oi_0_0':
        return clc_arc_html(rows)
    return clothoid_html(rows, is_clc=(name == 'clotoida_intrare'))
