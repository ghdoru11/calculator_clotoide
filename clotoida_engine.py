#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
clotoida_engine_unificat_v1.4.py

Versiunea 1.4 — extinde Anexa I si Anexa II; pastreaza comanda 'abac' pentru a calcula analitic elementele
clotoidei de baza (Anexele 1/2), ale clotoidei reale si ale CLC simetrice.

Motor unic pentru calculul analitic al clotoidei si pentru cazurile de
racordare mentionate in cele doua scripturi initiale.

Principii:
- fara numpy/pandas; foloseste numai biblioteca standard Python;
- unghiurile publice sunt in grade centesimale [g], calculele interne in radiani;
- separa formulele confirmate de procedurile speciale care necesita sursa/figura;
- nu inventeaza o solutie completa pentru racordari ovoidale, in dusina sau bucle;
- include verificari numerice pe geometria AX_FINAL (C1 si C3).

Cazuri incluse:
1. Clotoida-arc de cerc-clotoida (CLC), simetrica; calcul complet.
2. Doua clotoide simetrice fara arc central (LL); calcul complet.
3. Doua clotoide nesimetrice fara arc central; calcul geometric complet dupa
   alegerea unuia dintre unghiurile de capat.
4. Racordare in bolta intre aliniamente paralele; inventariata, blocata pana la
   confirmarea schemei geometrice exacte.
5. Racordare in dusina; inventariata, blocata pana la confirmarea schemei.
6. Serpentina de categoria a II-a; modul geometric d1, d2, D1, D2 si unghiuri.
7. Bucla; se poate calcula un arc individual de clotoida, nu intreaga bucla.
8. Racordare ovoidala; raportul razelor si controlul datelor, fara geometria
   completa a racordarii.

Comenzi rapide:
    python clotoida_engine_unificat.py selftest
    python clotoida_engine_unificat.py table --R 60 --L 36 --n 10 --xlsx tabel_C1.xlsx
    python clotoida_engine_unificat.py case1 --delta-g 118.93055 --R 60 --L 36
    python clotoida_engine_unificat.py case2 --U-g 80 --R 60
    python clotoida_engine_unificat.py case3 --U-g 80 --R 60 --alpha1-g 50
    python clotoida_engine_unificat.py serpentina2 --U-g 24.444444 --R2 32 --F 25 --x 24.6 --y 72.5
    python clotoida_engine_unificat_v1.4.py raport --tip clc --R 60 --L 36 --delta-g 118.93055 --xlsx C1.xlsx
    python clotoida_engine_unificat_v1.4.py raport --tip arc --R 55 --delta-g 49.58174 --n-arc 5 --xlsx C2.xlsx
    python clotoida_engine_unificat_v1.4.py raport --tip cc --R 60 --U-g 120 --n-cl 8 --xlsx CC.xlsx
    python clotoida_engine_unificat_v1.4.py inventory

Nota privind unghiurile:
- U_g = unghiul la varf dintre aliniamente;
- delta_g = unghiul total de schimbare a directiei / unghiul la centru;
- pentru racordarea obisnuita: delta_g = 200g - U_g;
- pentru viraje reflexe/serpentine se introduce direct delta_g; nu se forteaza
  formula 200g-U_g.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

PI = math.pi
GON_PER_RAD = 200.0 / PI
RAD_PER_GON = PI / 200.0
TOL = 1e-12

STATUS_CONFIRMAT = "Confirmat"
STATUS_DEDUCTIE = "Deducție"
STATUS_VERIFICARE = "Necesită verificare"


# ---------------------------------------------------------------------------
# Modele de date
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PunctClotoida:
    pichet: str
    s_m: float
    s1: float
    alfa_g: float
    phi_g: float
    gamma_g: float
    x_m: float
    y_m: float
    r_m: float
    kappa_1_m: float
    rho_m: float | None


@dataclass(frozen=True)
class PunctArcCerc:
    pichet: str
    beta_g: float       # unghi central parcurs de la începutul arcului
    phi_g: float        # unghi polar al coardei: beta/2
    r_m: float          # coarda de la începutul arcului
    x_local_m: float
    y_local_m: float
    c_m: float          # lungimea de arc de la început
    phi_global_g: float | None = None
    r_global_m: float | None = None
    x_global_m: float | None = None
    y_global_m: float | None = None


@dataclass(frozen=True)
class CriteriuLungime:
    nume: str
    valoare_m: float
    status: str
    observatie: str


@dataclass(frozen=True)
class RezultatClotoida:
    R_m: float
    L_m: float
    A_m: float
    alfa0_g: float
    x0_m: float
    y0_m: float
    r0_m: float
    k_m: float
    p_m: float
    verificare_rho: bool


# ---------------------------------------------------------------------------
# Utilitare unghiuri si validare
# ---------------------------------------------------------------------------

def gon_to_rad(angle_g: float) -> float:
    return angle_g * RAD_PER_GON


def rad_to_gon(angle_rad: float) -> float:
    return angle_rad * GON_PER_RAD


def deg_to_gon(angle_deg: float) -> float:
    return angle_deg * 10.0 / 9.0


def gon_to_deg(angle_g: float) -> float:
    return angle_g * 0.9


def _positive(name: str, value: float) -> float:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} trebuie sa fie finit si > 0; primit {value!r}.")
    return float(value)


def _nonnegative(name: str, value: float) -> float:
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} trebuie sa fie finit si >= 0; primit {value!r}.")
    return float(value)


def _angle_open(name: str, value_g: float, upper_g: float = 400.0) -> float:
    if not math.isfinite(value_g) or not (0.0 < value_g < upper_g):
        raise ValueError(f"{name} trebuie sa fie in intervalul (0, {upper_g}) g; primit {value_g!r}.")
    return float(value_g)


def _safe_asin(value: float, label: str) -> float:
    if value < -1.0 - 1e-10 or value > 1.0 + 1e-10:
        raise ValueError(f"Argument invalid pentru asin la {label}: {value:.12g}.")
    return math.asin(max(-1.0, min(1.0, value)))


def delta_din_U(U_g: float) -> float:
    """Unghiul la centru pentru un viraj obisnuit, ne-reflex: delta=200g-U."""
    _angle_open("U_g", U_g, 200.0)
    return 200.0 - U_g


# ---------------------------------------------------------------------------
# Clotoida: formule analitice confirmate
# ---------------------------------------------------------------------------

def modul_clotoida(R_m: float, L_m: float) -> float:
    R_m = _positive("R_m", R_m)
    L_m = _positive("L_m", L_m)
    return math.sqrt(R_m * L_m)


def _sexagesimal_dms(angle_g: float) -> str:
    """Reda unghiul in grade, minute, secunde, ca in Anexa I."""
    total = round(abs(gon_to_deg(angle_g)) * 3600)
    deg, remainder = divmod(total, 3600)
    mins, secs = divmod(remainder, 60)
    return ("-" if angle_g < 0 else "") + f"{deg}.{mins:02d}.{secs:02d}"


def _fresnel_xy1(s1: float, max_terms: int = 80, tol: float = 1e-17) -> tuple[float, float]:
    """
    Integralele Fresnel normalizate prin serii Taylor pana la convergenta.

    x/A = sum((-1)^n*l^(4n+1)/[(4n+1)*2^(2n)*(2n)!])
    y/A = sum((-1)^n*l^(4n+3)/[(4n+3)*2^(2n+1)*(2n+1)!])

    Forma elimina eroarea de trunchiere observabila la C3 cand se retin doar
    patru termeni.
    """
    x_sum = 0.0
    y_sum = 0.0
    for n in range(max_terms):
        sign = -1.0 if n % 2 else 1.0
        x_term = sign * s1 ** (4 * n + 1) / (
            (4 * n + 1) * 2.0 ** (2 * n) * math.factorial(2 * n)
        )
        y_term = sign * s1 ** (4 * n + 3) / (
            (4 * n + 3) * 2.0 ** (2 * n + 1) * math.factorial(2 * n + 1)
        )
        x_sum += x_term
        y_sum += y_term
        if n >= 3 and abs(x_term) < tol and abs(y_term) < tol:
            break
    else:
        raise ArithmeticError(
            f"Seriile Fresnel nu au atins toleranta pentru s1={s1:.6g}; "
            f"mariti max_terms sau folositi integrare numerica."
        )
    return x_sum, y_sum


def _x1(s1: float) -> float:
    return _fresnel_xy1(s1)[0]


def _y1(s1: float) -> float:
    return _fresnel_xy1(s1)[1]


def punct_clotoida(s_m: float, A_m: float, pichet: str = "") -> PunctClotoida:
    """Elementele unui punct la distanta curbilinie s de originea clotoidei."""
    A_m = _positive("A_m", A_m)
    s_m = _nonnegative("s_m", s_m)

    if s_m == 0.0:
        return PunctClotoida(
            pichet=pichet or "O",
            s_m=0.0,
            s1=0.0,
            alfa_g=0.0,
            phi_g=0.0,
            gamma_g=100.0,
            x_m=0.0,
            y_m=0.0,
            r_m=0.0,
            kappa_1_m=0.0,
            rho_m=None,
        )

    s1 = s_m / A_m
    alfa_rad = s1**2 / 2.0
    alfa_g = rad_to_gon(alfa_rad)

    x_m = A_m * _x1(s1)
    y_m = A_m * _y1(s1)
    r_m = math.hypot(x_m, y_m)
    phi_g = rad_to_gon(math.atan2(y_m, x_m))
    gamma_g = 100.0 - (alfa_g - phi_g)

    kappa = s_m / A_m**2
    rho_m = 1.0 / kappa

    return PunctClotoida(
        pichet=pichet,
        s_m=s_m,
        s1=s1,
        alfa_g=alfa_g,
        phi_g=phi_g,
        gamma_g=gamma_g,
        x_m=x_m,
        y_m=y_m,
        r_m=r_m,
        kappa_1_m=kappa,
        rho_m=rho_m,
    )


def rezultat_clotoida(R_m: float, L_m: float, toleranta_m: float = 1e-9) -> RezultatClotoida:
    """Rezumat la capatul clotoidei si elementele k/p ale arcului deplasat."""
    R_m = _positive("R_m", R_m)
    L_m = _positive("L_m", L_m)
    A_m = modul_clotoida(R_m, L_m)
    cap = punct_clotoida(L_m, A_m, "S")
    alfa_rad = gon_to_rad(cap.alfa_g)

    # k = abscisa piciorului centrului cercului pe tangenta initiala
    # p = stramutarea cercului fata de pozitia arcului circular simplu
    k_m = cap.x_m - R_m * math.sin(alfa_rad)
    p_m = cap.y_m - R_m * (1.0 - math.cos(alfa_rad))
    rho_ok = cap.rho_m is not None and abs(cap.rho_m - R_m) <= toleranta_m

    return RezultatClotoida(
        R_m=R_m,
        L_m=L_m,
        A_m=A_m,
        alfa0_g=cap.alfa_g,
        x0_m=cap.x_m,
        y0_m=cap.y_m,
        r0_m=cap.r_m,
        k_m=k_m,
        p_m=p_m,
        verificare_rho=rho_ok,
    )


def tabel_trasare(
    R_m: float,
    L_m: float,
    n: int = 10,
    distante_m: Sequence[float] | None = None,
) -> list[PunctClotoida]:
    """Tabel de la O (s=0) la S (s=L), inclusiv originea."""
    R_m = _positive("R_m", R_m)
    L_m = _positive("L_m", L_m)
    if n <= 0:
        raise ValueError("n trebuie sa fie un intreg > 0.")

    if distante_m is None:
        distante = [i * L_m / n for i in range(n + 1)]
    else:
        distante = [float(v) for v in distante_m]
        if not distante:
            raise ValueError("distante_m nu poate fi o lista vida.")
        for value in distante:
            if value < -TOL or value > L_m + TOL:
                raise ValueError(f"Distanta {value} nu apartine intervalului [0, L].")
        distante = sorted(set(max(0.0, min(L_m, v)) for v in distante))
        if abs(distante[0]) > TOL:
            distante.insert(0, 0.0)
        if abs(distante[-1] - L_m) > TOL:
            distante.append(L_m)

    A_m = modul_clotoida(R_m, L_m)
    puncte: list[PunctClotoida] = []
    for i, s_m in enumerate(distante):
        if abs(s_m) <= TOL:
            name = "O"
        elif abs(s_m - L_m) <= TOL:
            name = "S"
        else:
            name = str(i)
        puncte.append(punct_clotoida(s_m, A_m, name))
    return puncte


def verifica_inchidere(R_m: float, L_m: float, toleranta_m: float = 0.001) -> dict[str, Any]:
    rez = rezultat_clotoida(R_m, L_m, toleranta_m)
    rho_cap = (rez.A_m**2) / rez.L_m
    return {
        "A_m": rez.A_m,
        "rho_cap_m": rho_cap,
        "R_m": rez.R_m,
        "eroare_m": rho_cap - rez.R_m,
        "ok": abs(rho_cap - rez.R_m) <= toleranta_m,
    }


# ---------------------------------------------------------------------------
# Lungimea minima a clotoidei
# ---------------------------------------------------------------------------

def criterii_lungime_clotoida(
    R_m: float,
    V_kmh: float,
    j_m_s3: float = 0.5,
    Bcar_m: float | None = None,
    i_s: float | None = None,
    i_r: float | None = None,
    include_optic: bool = True,
) -> list[CriteriuLungime]:
    """
    Calculeaza criteriile disponibile.

    i_s si i_r trebuie furnizate in aceeasi forma: ambele procente (6 si 1)
    sau ambele zecimale (0.06 si 0.01).

    Criteriul optic folosit este alfa0 >= 1/18 rad, de unde L >= R/9.
    Formula este preluata din revizia documentului tehnic (2026-11-16); verificati
    aplicabilitatea normativului pentru cazul proiectat.
    Formula sqrt(12R) nu este implementata.
    """
    R_m = _positive("R_m", R_m)
    V_kmh = _positive("V_kmh", V_kmh)
    j_m_s3 = _positive("j_m_s3", j_m_s3)

    criterii = [
        CriteriuLungime(
            "variatia_acceleratiei_normale",
            V_kmh**3 / (47.0 * R_m * j_m_s3),
            STATUS_CONFIRMAT,
            "L_j = V^3/(47*R*j)",
        ),
        CriteriuLungime(
            "timp_minim_2_s",
            (2.0 / 3.6) * V_kmh,
            STATUS_CONFIRMAT,
            "L_t = 2*(V/3.6) = 0.555556*V",
        ),
    ]

    if include_optic:
        criterii.append(
            CriteriuLungime(
                "confort_optic_alfa0_min_1_18_rad",
                R_m / 9.0,
                STATUS_VERIFICARE,
                "Din alfa0=L/(2R) si alfa0>=1/18 rad rezulta L>=R/9; validati aplicabilitatea normativului.",
            )
        )

    ramp_args = (Bcar_m, i_s, i_r)
    if any(v is not None for v in ramp_args):
        if not all(v is not None for v in ramp_args):
            raise ValueError("Pentru criteriul rampei trebuie furnizate Bcar_m, i_s si i_r.")
        assert Bcar_m is not None and i_s is not None and i_r is not None
        Bcar_m = _positive("Bcar_m", Bcar_m)
        i_s = _positive("i_s", i_s)
        i_r = _positive("i_r", i_r)
        criterii.append(
            CriteriuLungime(
                "rampa_suprainaltare",
                Bcar_m * i_s / i_r,
                STATUS_VERIFICARE,
                "L_r=Bcar*i_s/i_r; i_s si i_r trebuie sa aiba aceeasi conventie de unitate.",
            )
        )

    return criterii


def lungime_adoptata(
    R_m: float,
    V_kmh: float,
    j_m_s3: float = 0.5,
    Bcar_m: float | None = None,
    i_s: float | None = None,
    i_r: float | None = None,
    include_optic: bool = True,
    rotunjire_m: float | None = None,
) -> dict[str, Any]:
    criterii = criterii_lungime_clotoida(
        R_m=R_m,
        V_kmh=V_kmh,
        j_m_s3=j_m_s3,
        Bcar_m=Bcar_m,
        i_s=i_s,
        i_r=i_r,
        include_optic=include_optic,
    )
    dominant = max(criterii, key=lambda c: c.valoare_m)
    raw = dominant.valoare_m
    if rotunjire_m is not None:
        rotunjire_m = _positive("rotunjire_m", rotunjire_m)
        adopted = math.ceil((raw - TOL) / rotunjire_m) * rotunjire_m
    else:
        adopted = raw
    return {
        "L_neutronjit_m": raw,
        "L_adoptat_m": adopted,
        "criteriu_dominant": dominant.nume,
        "criterii": [asdict(c) for c in criterii],
    }


# ---------------------------------------------------------------------------
# Arc de cerc: tabel de trasare
# ---------------------------------------------------------------------------

def _sens_semn(sens: str) -> int:
    sens_norm = sens.strip().lower()
    if sens_norm in {"stanga", "stânga", "left", "ccw"}:
        return 1
    if sens_norm in {"dreapta", "right", "cw"}:
        return -1
    raise ValueError("sens trebuie sa fie 'stanga' sau 'dreapta'.")


def tabel_arc_cerc_simplu(
    R_m: float,
    delta_g: float,
    n: int = 5,
    mod_arc: str = "jumatate",
    sens: str = "stanga",
) -> list[PunctArcCerc]:
    """
    Tabel pentru arc de cerc simplu.

    mod_arc='jumatate':
      Ti -> B; beta_max=delta/2, phi_max=delta/4.
      Aceasta este forma uzuala din tabelul-model, cealalta jumatate fiind simetrica.

    mod_arc='complet':
      Ti -> Te; beta_max=delta, phi_max=delta/2.

    Formule:
      phi = beta/2
      r = 2 R sin(phi)
      x = r cos(phi) = R sin(beta)
      y = +/- r sin(phi) = +/- R(1-cos(beta))
      c = pi R beta_g / 200
    """
    R_m = _positive("R_m", R_m)
    delta_g = _angle_open("delta_g", delta_g)
    if n <= 0:
        raise ValueError("n trebuie sa fie un intreg > 0.")
    if mod_arc not in {"jumatate", "complet"}:
        raise ValueError("mod_arc trebuie sa fie 'jumatate' sau 'complet'.")

    semn = _sens_semn(sens)
    beta_max_g = delta_g / 2.0 if mod_arc == "jumatate" else delta_g
    puncte: list[PunctArcCerc] = []
    for i in range(n + 1):
        beta_g = beta_max_g * i / n
        beta_rad = gon_to_rad(beta_g)
        phi_g = beta_g / 2.0
        phi_rad = gon_to_rad(phi_g)
        r_m = 2.0 * R_m * math.sin(phi_rad)
        x_m = r_m * math.cos(phi_rad)
        y_m = semn * r_m * math.sin(phi_rad)
        c_m = PI * R_m * beta_g / 200.0

        if i == 0:
            pichet = "Ti"
        elif i == n:
            pichet = "B" if mod_arc == "jumatate" else "Te"
        else:
            pichet = str(i)

        puncte.append(PunctArcCerc(
            pichet=pichet,
            beta_g=beta_g,
            phi_g=phi_g,
            r_m=r_m,
            x_local_m=x_m,
            y_local_m=y_m,
            c_m=c_m,
        ))
    return puncte


def tabel_arc_central_clc(
    R_m: float,
    L_m: float,
    delta_total_g: float,
    n: int = 8,
    sens: str = "stanga",
) -> list[PunctArcCerc]:
    """
    Tabelul arcului circular central pentru racordarea CLC.

    Coordonatele locale x',y' sunt raportate la capatul clotoidei de intrare Si,
    cu axa x' pe tangenta la Si. Coordonatele globale x,y sunt raportate la
    originea clotoidei Oi.
    """
    R_m = _positive("R_m", R_m)
    L_m = _positive("L_m", L_m)
    delta_total_g = _angle_open("delta_total_g", delta_total_g)
    if n <= 0:
        raise ValueError("n trebuie sa fie un intreg > 0.")

    cl = rezultat_clotoida(R_m, L_m)
    delta_arc_g = delta_total_g - 2.0 * cl.alfa0_g
    if delta_arc_g <= 0:
        raise ValueError("Nu ramane arc central; folositi cazul clotoida-clotoida.")

    semn = _sens_semn(sens)
    alfa0_rad = semn * gon_to_rad(cl.alfa0_g)
    x0 = cl.x0_m
    y0 = semn * cl.y0_m

    puncte: list[PunctArcCerc] = []
    for i in range(n + 1):
        beta_g = delta_arc_g * i / n
        beta_rad = gon_to_rad(beta_g)
        phi_g = beta_g / 2.0
        phi_rad = gon_to_rad(phi_g)
        r_local = 2.0 * R_m * math.sin(phi_rad)
        x_local = R_m * math.sin(beta_rad)
        y_local = semn * R_m * (1.0 - math.cos(beta_rad))

        x_global = x0 + x_local * math.cos(alfa0_rad) - y_local * math.sin(alfa0_rad)
        y_global = y0 + x_local * math.sin(alfa0_rad) + y_local * math.cos(alfa0_rad)
        r_global = math.hypot(x_global, y_global)
        phi_global_g = rad_to_gon(math.atan2(y_global, x_global))
        c_m = PI * R_m * beta_g / 200.0

        if i == 0:
            pichet = "Si"
        elif i == n:
            pichet = "Se"
        else:
            pichet = str(i)

        puncte.append(PunctArcCerc(
            pichet=pichet,
            beta_g=beta_g,
            phi_g=phi_g,
            r_m=r_local,
            x_local_m=x_local,
            y_local_m=y_local,
            c_m=c_m,
            phi_global_g=phi_global_g,
            r_global_m=r_global,
            x_global_m=x_global,
            y_global_m=y_global,
        ))
    return puncte


def _rows_arc_simplu_excel(puncte: Sequence[PunctArcCerc]) -> list[list[Any]]:
    return [[
        p.pichet, p.phi_g, p.r_m, p.x_local_m, p.y_local_m, p.c_m
    ] for p in puncte]


def _rows_arc_clc_excel(puncte: Sequence[PunctArcCerc]) -> list[list[Any]]:
    return [[
        p.pichet,
        p.r_m,
        p.phi_g,
        p.x_local_m,
        p.y_local_m,
        p.r_global_m,
        p.phi_global_g,
        p.x_global_m,
        p.y_global_m,
        p.c_m,
    ] for p in puncte]


# ---------------------------------------------------------------------------
# Caz 1: CLC simetrica
# ---------------------------------------------------------------------------

def caz1_clc_simetrica(
    delta_g: float,
    R_m: float,
    L_m: float,
    V_kmh: float | None = None,
    min_arc_m: float | None = None,
    n: int = 10,
) -> dict[str, Any]:
    """Racordare clotoida-arc-clotoida simetrica."""
    delta_g = _angle_open("delta_g", delta_g)
    R_m = _positive("R_m", R_m)
    L_m = _positive("L_m", L_m)

    cl = rezultat_clotoida(R_m, L_m)
    delta_central_g = delta_g - 2.0 * cl.alfa0_g
    if delta_central_g <= 0.0:
        raise ValueError(
            "Cele doua clotoide consuma integral unghiul disponibil; folositi cazul 2 (LL) "
            "sau reduceti L_m."
        )

    C_central_m = PI * R_m * delta_central_g / 200.0
    geometrie_varf_standard = delta_g < 200.0
    if geometrie_varf_standard:
        delta_half_rad = gon_to_rad(delta_g / 2.0)
        T_total_m: float | None = cl.k_m + (R_m + cl.p_m) * math.tan(delta_half_rad)
        B_total_m: float | None = (R_m + cl.p_m) / math.cos(delta_half_rad) - R_m
        observatie_varf = "Tangenta si bisectoarea sunt calculate pentru un viraj obisnuit, delta<200g."
    else:
        T_total_m = None
        B_total_m = None
        observatie_varf = (
            "delta>=200g: ansamblu reflex/serpentina. Formulele standard de tangenta si "
            "bisectoare la un singur varf nu sunt aplicate."
        )

    if min_arc_m is None and V_kmh is not None:
        min_arc_m = _positive("V_kmh", V_kmh) / 3.6

    arc_ok = None if min_arc_m is None else C_central_m >= min_arc_m - 1e-9

    return {
        "caz": 1,
        "denumire": "clotoida-arc de cerc-clotoida simetrica",
        "status": STATUS_CONFIRMAT,
        "delta_total_g": delta_g,
        "R_m": R_m,
        "L_clotoida_m": L_m,
        "A_m": cl.A_m,
        "alfa0_g": cl.alfa0_g,
        "delta_arc_central_g": delta_central_g,
        "C_arc_central_m": C_central_m,
        "lungime_totala_m": 2.0 * L_m + C_central_m,
        "k_m": cl.k_m,
        "p_m": cl.p_m,
        "T_total_m": T_total_m,
        "B_total_m": B_total_m,
        "geometrie_varf_standard": geometrie_varf_standard,
        "observatie_varf": observatie_varf,
        "prag_arc_m": min_arc_m,
        "verificare_arc_central": arc_ok,
        "verificare_rho": cl.verificare_rho,
        "tabel_clotoida": [asdict(p) for p in tabel_trasare(R_m, L_m, n)],
    }


def caz1_clc_din_U(
    U_g: float,
    R_m: float,
    L_m: float,
    **kwargs: Any,
) -> dict[str, Any]:
    return caz1_clc_simetrica(delta_din_U(U_g), R_m, L_m, **kwargs)


# ---------------------------------------------------------------------------
# Caz 2: LL simetrica
# ---------------------------------------------------------------------------

def caz2_ll_simetrica(
    U_g: float,
    R_m: float,
    L_min_m: float | None = None,
    n: int = 10,
) -> dict[str, Any]:
    """
    Doua clotoide simetrice, fara arc central.

    alfa0=(200-U)/2 si L=2*R*alfa0(rad).
    """
    delta_g = delta_din_U(U_g)
    R_m = _positive("R_m", R_m)
    alfa0_g = delta_g / 2.0
    L_m = 2.0 * R_m * gon_to_rad(alfa0_g)
    cl = rezultat_clotoida(R_m, L_m)

    min_ok = None if L_min_m is None else L_m >= _positive("L_min_m", L_min_m) - 1e-9
    return {
        "caz": 2,
        "denumire": "doua clotoide simetrice fara arc central",
        "status": STATUS_CONFIRMAT,
        "U_g": U_g,
        "delta_total_g": delta_g,
        "R_m": R_m,
        "alfa0_g": alfa0_g,
        "L_fiecare_m": L_m,
        "A_m": cl.A_m,
        "lungime_totala_m": 2.0 * L_m,
        "L_min_m": L_min_m,
        "verificare_L_min": min_ok,
        "verificare_rho": cl.verificare_rho,
        "tabel_clotoida": [asdict(p) for p in tabel_trasare(R_m, L_m, n)],
    }


# ---------------------------------------------------------------------------
# Caz 3: LL nesimetrica
# ---------------------------------------------------------------------------

def caz3_ll_nesimetrica(
    U_g: float,
    R_m: float,
    alfa01_g: float,
    n: int = 10,
) -> dict[str, Any]:
    """Doua clotoide nesimetrice, cu aceeasi raza de curbura R in punctul comun."""
    delta_g = delta_din_U(U_g)
    R_m = _positive("R_m", R_m)
    alfa01_g = _angle_open("alfa01_g", alfa01_g, delta_g)
    alfa02_g = delta_g - alfa01_g

    L1_m = 2.0 * R_m * gon_to_rad(alfa01_g)
    L2_m = 2.0 * R_m * gon_to_rad(alfa02_g)
    cl1 = rezultat_clotoida(R_m, L1_m)
    cl2 = rezultat_clotoida(R_m, L2_m)

    return {
        "caz": 3,
        "denumire": "doua clotoide nesimetrice fara arc central",
        "status": STATUS_CONFIRMAT,
        "U_g": U_g,
        "delta_total_g": delta_g,
        "R_m": R_m,
        "alfa01_g": alfa01_g,
        "alfa02_g": alfa02_g,
        "verificare_unghi_g": alfa01_g + alfa02_g + U_g,
        "clotoida_1": {
            **asdict(cl1),
            "tabel": [asdict(p) for p in tabel_trasare(R_m, L1_m, n)],
        },
        "clotoida_2": {
            **asdict(cl2),
            "tabel": [asdict(p) for p in tabel_trasare(R_m, L2_m, n)],
        },
    }


# ---------------------------------------------------------------------------
# Cazurile 4, 5, 7, 8: inventar si parti calculabile
# ---------------------------------------------------------------------------

def caz4_bolta_aliniamente_paralele(D_m: float) -> dict[str, Any]:
    """
    Racordare in bolta intre aliniamente paralele.

    Scriptul vechi folosea direct y0=D/2 si un alfa0 adoptat. Acea reducere nu
    este suficient documentata pentru a fi declarata calcul complet.
    """
    D_m = _positive("D_m", D_m)
    return {
        "caz": 4,
        "denumire": "racordare in bolta intre aliniamente paralele",
        "status": STATUS_VERIFICARE,
        "D_m": D_m,
        "rezultat": None,
        "mesaj": (
            "Caz inventariat, dar calculul este blocat pana la confirmarea figurii si a relatiilor "
            "geometrice. Formula veche y0=D/2 nu este pastrata ca solutie validata."
        ),
    }


def caz5_dusina(R1_m: float, R2_m: float, D_m: float | None = None) -> dict[str, Any]:
    R1_m = _positive("R1_m", R1_m)
    R2_m = _positive("R2_m", R2_m)
    if D_m is not None:
        D_m = _positive("D_m", D_m)
    return {
        "caz": 5,
        "denumire": "racordare in dusina intre curbe succesive de sens contrar",
        "status": STATUS_VERIFICARE,
        "R1_m": R1_m,
        "R2_m": R2_m,
        "D_m": D_m,
        "rezultat": None,
        "mesaj": (
            "Nu exista suficiente relatii confirmate pentru geometria completa. "
            "Formula veche cu n0=D/sqrt(2) nu este folosita automat."
        ),
    }


def caz7_arc_individual_bucla(R_m: float, alfa0_g: float, n: int = 20) -> dict[str, Any]:
    """Calculeaza doar un arc individual de clotoida dintr-o bucla."""
    R_m = _positive("R_m", R_m)
    alfa0_g = _angle_open("alfa0_g", alfa0_g)
    L_m = 2.0 * R_m * gon_to_rad(alfa0_g)
    cl = rezultat_clotoida(R_m, L_m)
    return {
        "caz": 7,
        "denumire": "arc individual de clotoida pentru bucla",
        "status": STATUS_DEDUCTIE,
        "observatie": "Nu reprezinta proiectarea completa a buclei; doar geometria unui arc individual.",
        **asdict(cl),
        "tabel": [asdict(p) for p in tabel_trasare(R_m, L_m, n)],
    }


def caz8_ovoidala_raport(R1_m: float, R2_m: float) -> dict[str, Any]:
    R1_m = _positive("R1_m", R1_m)
    R2_m = _positive("R2_m", R2_m)
    F = max(R1_m, R2_m) / min(R1_m, R2_m)
    return {
        "caz": 8,
        "denumire": "racordare ovoidala",
        "status": STATUS_VERIFICARE,
        "R1_m": R1_m,
        "R2_m": R2_m,
        "F_raport_raze": F,
        "rezultat": None,
        "mesaj": (
            "Raportul razelor este calculat; geometria completa necesita tipul de cercuri "
            "(exterioare/secante/interioare), elementul geometric cunoscut si relatiile/nomogramele sursa."
        ),
    }


# ---------------------------------------------------------------------------
# Caz 6: serpentina categoria a II-a
# ---------------------------------------------------------------------------

def caz6_serpentina_categoria_II(
    U_g: float,
    R2_m: float,
    F_m: float,
    x_m: float,
    y_m: float,
) -> dict[str, Any]:
    """
    Modul geometric pentru schema de serpentina categoria a II-a.

    Intrari:
      U_g  - unghiul dintre directiile de baza [g]
      R2_m - raza folosita la curbele auxiliare [m]
      F_m  - distanta F din schema [m]
      x_m, y_m - coordonatele centrului O1 in sistemul local al schemei [m]

    Returneaza d1, d2, D1, D2 si unghiurile intermediare.
    """
    U_g = _angle_open("U_g", U_g, 200.0)
    R2_m = _positive("R2_m", R2_m)
    F_m = _positive("F_m", F_m)
    x_m = _nonnegative("x_m", x_m)
    y_m = _positive("y_m", y_m)

    U = gon_to_rad(U_g)
    half = U / 2.0
    if abs(math.sin(half)) <= TOL or abs(math.cos(half)) <= TOL:
        raise ValueError("U_g produce o configuratie singulara pentru schema serpentinei.")

    O1A_m = y_m - x_m * math.tan(half)
    A_angle = PI / 2.0 + half
    AV1_m = F_m / (2.0 * math.sin(half)) + x_m / math.cos(half)
    d1_m = math.sqrt(
        O1A_m**2 + AV1_m**2 - 2.0 * O1A_m * AV1_m * math.cos(A_angle)
    )
    tau1 = _safe_asin((O1A_m / d1_m) * math.sin(A_angle), "tau1")

    O1C_m = y_m + x_m * math.tan(half)
    C_angle = PI / 2.0 - half
    CV3_m = AV1_m
    d2_m = math.sqrt(
        O1C_m**2 + CV3_m**2 - 2.0 * O1C_m * CV3_m * math.cos(C_angle)
    )
    tau2 = _safe_asin((O1C_m / d2_m) * math.sin(C_angle), "tau2")

    if R2_m > min(d1_m, d2_m) + 1e-10:
        raise ValueError("R2_m este mai mare decat d1 sau d2; beta nu are solutie reala.")

    beta1 = _safe_asin(R2_m / d1_m, "beta1")
    beta2 = _safe_asin(R2_m / d2_m, "beta2")
    D1_m = d1_m * math.cos(beta1)
    D2_m = d2_m * math.cos(beta2)
    eps1 = PI / 2.0 - beta1
    eps2 = PI / 2.0 - beta2
    alpha1 = U + tau1 - tau2
    gamma1 = 2.0 * PI - (eps1 + eps2 + alpha1)
    delta = gamma1 - PI

    return {
        "caz": 6,
        "denumire": "serpentina categoria a II-a - schema geometrica",
        "status": STATUS_DEDUCTIE,
        "intrari": {
            "U_g": U_g,
            "R2_m": R2_m,
            "F_m": F_m,
            "x_m": x_m,
            "y_m": y_m,
        },
        "lungimi_m": {
            "O1A": O1A_m,
            "AV1": AV1_m,
            "d1": d1_m,
            "O1C": O1C_m,
            "CV3": CV3_m,
            "d2": d2_m,
            "D1": D1_m,
            "D2": D2_m,
        },
        "unghiuri_g": {
            "tau1": rad_to_gon(tau1),
            "tau2": rad_to_gon(tau2),
            "beta1": rad_to_gon(beta1),
            "beta2": rad_to_gon(beta2),
            "epsilon1": rad_to_gon(eps1),
            "epsilon2": rad_to_gon(eps2),
            "alpha1": rad_to_gon(alpha1),
            "gamma1": rad_to_gon(gamma1),
            "delta_peste_semicerc": rad_to_gon(delta),
        },
        "observatie": (
            "Modulul reproduce schema geometrica si exemplul numeric disponibil. "
            "Nu dimensioneaza automat toate curbele, clotoidele si aliniamentele serpentinei."
        ),
    }


# ---------------------------------------------------------------------------
# Inventar, serializare, afisare
# ---------------------------------------------------------------------------

def inventar_cazuri() -> list[dict[str, str]]:
    return [
        {"caz": "1", "denumire": "CLC simetrica", "status": STATUS_CONFIRMAT},
        {"caz": "2", "denumire": "LL simetrica", "status": STATUS_CONFIRMAT},
        {"caz": "3", "denumire": "LL nesimetrica", "status": STATUS_CONFIRMAT},
        {"caz": "4", "denumire": "Bolta intre aliniamente paralele", "status": STATUS_VERIFICARE},
        {"caz": "5", "denumire": "Dusina", "status": STATUS_VERIFICARE},
        {"caz": "6", "denumire": "Serpentina categoria a II-a", "status": STATUS_DEDUCTIE},
        {"caz": "7", "denumire": "Arc individual pentru bucla", "status": STATUS_DEDUCTIE},
        {"caz": "8", "denumire": "Ovoidala - raport raze", "status": STATUS_VERIFICARE},
    ]


def _round_for_output(value: Any, digits: int = 9) -> Any:
    if isinstance(value, float):
        return round(value, digits)
    if isinstance(value, list):
        return [_round_for_output(v, digits) for v in value]
    if isinstance(value, dict):
        return {k: _round_for_output(v, digits) for k, v in value.items()}
    return value


def print_json(data: Any) -> None:
    print(json.dumps(_round_for_output(data), ensure_ascii=False, indent=2))


def print_tabel(puncte: Iterable[PunctClotoida]) -> None:
    header = (
        f"{'PICHET':>7} {'s[m]':>11} {'s1':>10} {'alfa[g]':>11} {'phi[g]':>11} "
        f"{'gamma[g]':>11} {'x[m]':>12} {'y[m]':>12} {'r[m]':>12} {'rho[m]':>12}"
    )
    print(header)
    print("-" * len(header))
    for p in puncte:
        rho = "inf" if p.rho_m is None else f"{p.rho_m:.6f}"
        print(
            f"{p.pichet:>7} {p.s_m:11.6f} {p.s1:10.6f} {p.alfa_g:11.6f} "
            f"{p.phi_g:11.6f} {p.gamma_g:11.6f} {p.x_m:12.6f} {p.y_m:12.6f} "
            f"{p.r_m:12.6f} {rho:>12}"
        )


def export_tabel_csv(path: str | Path, puncte: Sequence[PunctClotoida]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(asdict(puncte[0]).keys()) if puncte else []
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for point in puncte:
            writer.writerow(asdict(point))
    return path


# ---------------------------------------------------------------------------
# Export Excel nativ pe Windows (Excel COM prin PowerShell)
# ---------------------------------------------------------------------------

def _excel_value(value: Any) -> Any:
    """Convertește valorile Python într-o formă sigură pentru JSON/Excel."""
    if value is None:
        return "∞"
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "∞" if value > 0 else "-∞"
    if isinstance(value, (str, int, float, bool)):
        return value
    return json.dumps(_round_for_output(value), ensure_ascii=False)


def _rows_tabel_excel(
    puncte: Sequence[PunctClotoida],
    ordine: str = "desc",
    sufix: str = "i",
) -> list[list[Any]]:
    """
    Construiește rândurile în structura tabelului din model:
    PICHET, alfa0, phi, r1, r, x1, x, y1, y, s1, s, rho1, rho, Y.
    """
    if ordine not in {"asc", "desc"}:
        raise ValueError("ordine trebuie să fie 'asc' sau 'desc'.")
    if not puncte:
        return []

    seq = list(puncte)
    if ordine == "desc":
        seq.reverse()

    finite = next((p for p in seq if p.s_m > 0 and p.rho_m is not None), None)
    if finite is None:
        raise ValueError("Tabelul nu conține niciun punct finit pentru determinarea modulului A.")
    A_m = math.sqrt(finite.s_m * finite.rho_m)

    rows: list[list[Any]] = []
    for p in seq:
        if p.pichet == "S":
            pichet = f"S{sufix}" if sufix else "S"
        elif p.pichet == "O":
            pichet = f"O{sufix}" if sufix else "O"
        else:
            pichet = p.pichet

        rho1 = None if p.rho_m is None else p.rho_m / A_m
        rows.append([
            pichet,
            p.alfa_g,
            p.phi_g,
            p.r_m / A_m,
            p.r_m,
            p.x_m / A_m,
            p.x_m,
            p.y_m / A_m,
            p.y_m,
            p.s1,
            p.s_m,
            rho1,
            p.rho_m,
            p.gamma_g,
        ])
    return rows


def _flatten_summary(data: Any, prefix: str = "") -> list[list[Any]]:
    """Aplatizează un rezultat imbricat într-un tabel Parametru/Valoare."""
    rows: list[list[Any]] = []
    if isinstance(data, dict):
        for key, value in data.items():
            if key in {"tabel", "tabel_clotoida", "clotoida_1", "clotoida_2"}:
                continue
            label = f"{prefix}.{key}" if prefix else str(key)
            rows.extend(_flatten_summary(value, label))
    elif isinstance(data, list):
        rows.append([prefix, json.dumps(_round_for_output(data), ensure_ascii=False)])
    else:
        rows.append([prefix, _excel_value(data)])
    return rows


def export_excel_native(
    path: str | Path,
    tables: Sequence[dict[str, Any]] | None = None,
    summary: Any | None = None,
) -> Path:
    """
    Exportă un fișier .xlsx formatat prin Excel COM.

    Cerințe de rulare:
    - Windows;
    - Microsoft Excel instalat;
    - PowerShell disponibil.

    Nu necesită openpyxl, pandas, numpy sau alte biblioteci Python.
    """
    if os.name != "nt":
        raise RuntimeError(
            "Exportul .xlsx nativ folosește Excel COM și rulează numai pe Windows cu Excel instalat. "
            "Pe alte sisteme folosiți --csv."
        )

    output = Path(path).expanduser().resolve()
    if output.suffix.lower() != ".xlsx":
        output = output.with_suffix(".xlsx")
    output.parent.mkdir(parents=True, exist_ok=True)

    payload_tables: list[dict[str, Any]] = []
    for idx, spec in enumerate(tables or [], start=1):
        points = spec.get("points")
        if points is None:
            raise ValueError("Fiecare tabel Excel trebuie să conțină cheia 'points'.")
        payload_tables.append({
            "sheet": str(spec.get("sheet", f"Clotoida_{idx}"))[:31],
            "title": str(spec.get("title", "COORDONATE DE TRASARE PENTRU CLOTOIDĂ")),
            "rows": _rows_tabel_excel(
                list(points),
                ordine=str(spec.get("ordine", "desc")),
                sufix=str(spec.get("sufix", "i")),
            ),
        })

    payload = {
        "summary": _flatten_summary(summary) if summary is not None else [],
        "tables": payload_tables,
    }

    powershell = r"""
param(
    [Parameter(Mandatory=$true)][string]$JsonPath,
    [Parameter(Mandatory=$true)][string]$OutputPath
)
$ErrorActionPreference = 'Stop'
$data = Get-Content -LiteralPath $JsonPath -Raw -Encoding UTF8 | ConvertFrom-Json
$excel = $null
$book = $null
try {
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $book = $excel.Workbooks.Add()

    while ($book.Worksheets.Count -gt 1) {
        $book.Worksheets.Item($book.Worksheets.Count).Delete()
    }

    function Set-AllBorders($range) {
        foreach ($edge in 7,8,9,10,11,12) {
            $border = $range.Borders.Item($edge)
            $border.LineStyle = 1
            $border.Weight = 2
            $border.Color = 0
        }
    }

    function Add-SummarySheet($book, $rows) {
        $ws = $book.Worksheets.Item(1)
        $ws.Name = 'Rezumat'
        $ws.Cells.Item(1,1).Value2 = 'PARAMETRU'
        $ws.Cells.Item(1,2).Value2 = 'VALOARE'
        $ws.Range('A1:B1').Font.Bold = $true
        $ws.Range('A1:B1').Interior.Color = 14277081
        $ws.Range('A1:B1').HorizontalAlignment = -4108
        $r = 2
        foreach ($item in $rows) {
            $ws.Cells.Item($r,1).Value2 = [string]$item[0]
            $ws.Cells.Item($r,2).Value2 = $item[1]
            $r++
        }
        if ($r -gt 2) { Set-AllBorders $ws.Range("A1:B$($r-1)") }
        $ws.Columns.Item(1).ColumnWidth = 38
        $ws.Columns.Item(2).ColumnWidth = 28
        $ws.Range("A1:B$($r-1)").VerticalAlignment = -4108
        $ws.Range("A1:B$($r-1)").WrapText = $true
        $ws.Application.ActiveWindow.SplitRow = 1
        $ws.Application.ActiveWindow.FreezePanes = $true
        return $ws
    }

    function Add-ClothoidSheet($book, $table, [bool]$reuseFirst) {
        if ($reuseFirst) { $ws = $book.Worksheets.Item(1) }
        else { $ws = $book.Worksheets.Add() }
        $name = [string]$table.sheet
        if ([string]::IsNullOrWhiteSpace($name)) { $name = 'Clotoida' }
        $ws.Name = $name.Substring(0, [Math]::Min(31, $name.Length))

        $ws.Range('A1:N1').Merge()
        $ws.Cells.Item(1,1).Value2 = [string]$table.title
        $ws.Range('A1:N1').Font.Bold = $true
        $ws.Range('A1:N1').Font.Size = 12
        $ws.Range('A1:N1').HorizontalAlignment = -4108
        $ws.Range('A1:N1').VerticalAlignment = -4108
        $ws.Range('A1:N1').Interior.Color = 15132390

        $ws.Range('A2:A3').Merge()
        $ws.Cells.Item(2,1).Value2 = 'PICHET'
        $ws.Cells.Item(2,2).Value2 = 'α0'
        $ws.Range('C2:E2').Merge(); $ws.Cells.Item(2,3).Value2 = 'Coordonate polare'
        $ws.Range('F2:I2').Merge(); $ws.Cells.Item(2,6).Value2 = 'Coordonate carteziene'
        $ws.Range('J2:K2').Merge(); $ws.Cells.Item(2,10).Value2 = 'Lungime arc'
        $ws.Range('L2:M2').Merge(); $ws.Cells.Item(2,12).Value2 = 'Raze de curbură'
        $ws.Cells.Item(2,14).Value2 = 'Y'

        $headers = @('(g,c,cc)','Φ','r1','r','x1','x','y1','y','s1','s','ρ1','ρ','(g,c,cc)')
        for ($c=2; $c -le 14; $c++) { $ws.Cells.Item(3,$c).Value2 = $headers[$c-2] }
        $ws.Range('A2:N3').HorizontalAlignment = -4108
        $ws.Range('A2:N3').VerticalAlignment = -4108
        $ws.Range('A2:N3').Interior.Color = 15921906

        $row = 4
        foreach ($record in $table.rows) {
            for ($col=1; $col -le 14; $col++) {
                $value = $record[$col-1]
                if ($null -eq $value) { $value = '∞' }
                $ws.Cells.Item($row,$col).Value2 = $value
            }
            $row++
        }
        $last = [Math]::Max(3, $row-1)
        $ws.Range("B4:N$last").NumberFormat = '0.0000'
        $ws.Range("A1:N$last").HorizontalAlignment = -4108
        $ws.Range("A1:N$last").VerticalAlignment = -4108
        Set-AllBorders $ws.Range("A1:N$last")

        $widths = @(10,11,10,10,11,10,11,10,11,10,11,10,11,11)
        for ($c=1; $c -le 14; $c++) { $ws.Columns.Item($c).ColumnWidth = $widths[$c-1] }
        $ws.Rows.Item(1).RowHeight = 23
        $ws.Rows.Item(2).RowHeight = 22
        $ws.Rows.Item(3).RowHeight = 20
        $ws.Application.ActiveWindow.SplitRow = 3
        $ws.Application.ActiveWindow.FreezePanes = $true
        $ws.PageSetup.Orientation = 2
        $ws.PageSetup.Zoom = $false
        $ws.PageSetup.FitToPagesWide = 1
        $ws.PageSetup.FitToPagesTall = 0
        return $ws
    }

    $hasSummary = ($data.summary.Count -gt 0)
    if ($hasSummary) { [void](Add-SummarySheet $book $data.summary) }

    $firstTable = $true
    foreach ($table in $data.tables) {
        $reuse = (-not $hasSummary) -and $firstTable
        [void](Add-ClothoidSheet $book $table $reuse)
        $firstTable = $false
    }

    if (($data.tables.Count -eq 0) -and (-not $hasSummary)) {
        $book.Worksheets.Item(1).Name = 'Rezumat'
        $book.Worksheets.Item(1).Cells.Item(1,1).Value2 = 'Nu există date pentru export.'
    }

    $full = [System.IO.Path]::GetFullPath($OutputPath)
    $book.SaveAs($full, 51)
}
finally {
    if ($book -ne $null) { $book.Close($false) }
    if ($excel -ne $null) { $excel.Quit() }
    if ($book -ne $null) { [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($book) }
    if ($excel -ne $null) { [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($excel) }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
"""

    with tempfile.TemporaryDirectory(prefix="clotoida_xlsx_") as tmp:
        tmp_path = Path(tmp)
        json_path = tmp_path / "payload.json"
        ps_path = tmp_path / "export_clotoida.ps1"
        json_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8-sig")
        ps_path.write_text(powershell, encoding="utf-8-sig")

        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", str(ps_path),
            "-JsonPath", str(json_path),
            "-OutputPath", str(output),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise RuntimeError("powershell.exe nu a fost găsit.") from exc
        except subprocess.CalledProcessError as exc:
            details = (exc.stderr or exc.stdout or str(exc)).strip()
            raise RuntimeError(f"Exportul Excel a eșuat: {details}") from exc

    if not output.exists():
        raise RuntimeError("Excel nu a creat fișierul de ieșire solicitat.")
    return output

# ---------------------------------------------------------------------------
# Autoteste
# ---------------------------------------------------------------------------

def _assert_close(actual: float, expected: float, tol: float, label: str) -> None:
    if abs(actual - expected) > tol:
        raise AssertionError(
            f"{label}: calculat {actual:.12f}, asteptat {expected:.12f}, toleranta {tol}."
        )


def selftest() -> dict[str, Any]:
    tests: list[dict[str, Any]] = []

    # AX_FINAL C1: R=60, L=36; valori LandXML Civil 3D.
    c1 = rezultat_clotoida(60.0, 36.0)
    _assert_close(c1.A_m, 46.475800154489, 1e-10, "C1 A")
    _assert_close(c1.x0_m, 35.677347199552, 2e-9, "C1 x0")
    _assert_close(c1.y0_m, 3.576923311587, 2e-9, "C1 y0")
    _assert_close(gon_to_deg(c1.alfa0_g), 17.188733853925, 2e-10, "C1 theta deg")
    tests.append({"test": "AX_FINAL C1", "ok": True})

    # AX_FINAL C3: R=25, L=36.
    c3 = rezultat_clotoida(25.0, 36.0)
    _assert_close(c3.A_m, 30.0, 1e-12, "C3 A")
    _assert_close(c3.x0_m, 34.178017704483, 1e-8, "C3 x0")
    _assert_close(c3.y0_m, 8.325302696482, 1e-9, "C3 y0")
    _assert_close(gon_to_deg(c3.alfa0_g), 41.252961249419, 2e-10, "C3 theta deg")
    tests.append({"test": "AX_FINAL C3", "ok": True})

    # Verificarea formulei corectate L=2R*alfa(rad), nu R*sqrt(2*alfa).
    case2 = caz2_ll_simetrica(U_g=100.0, R_m=60.0, n=4)
    expected_L = 2.0 * 60.0 * gon_to_rad(50.0)
    _assert_close(case2["L_fiecare_m"], expected_L, 1e-12, "Caz 2 L")
    tests.append({"test": "caz2 formula L=2R*alfa", "ok": True})

    # Exemplul geometric serpentina: U=22°, R2=32, F=25, O1=(24.6,72.5).
    serp = caz6_serpentina_categoria_II(
        U_g=deg_to_gon(22.0), R2_m=32.0, F_m=25.0, x_m=24.6, y_m=72.5
    )
    _assert_close(
        gon_to_deg(serp["unghiuri_g"]["alpha1"]),
        9.69907218799428,
        1e-9,
        "Serpentina alpha1",
    )
    _assert_close(
        gon_to_deg(serp["unghiuri_g"]["gamma1"]),
        202.73857624883482,
        1e-9,
        "Serpentina gamma1",
    )
    tests.append({"test": "serpentina categoria II", "ok": True})

    ab = elemente_anexe(raport_L_R=0.6, R_m=60.0)
    bc = ab["clotoida_baza_A_1"]
    rc = ab["clotoida_reala"]
    assert rc is not None
    assert abs(rc["L_m"]-36.0)<1e-10
    assert abs(bc["s1"]/bc["rho1"]-0.6)<1e-12
    assert abs(bc["t_rad_sqrt"]**2-gon_to_rad(bc["alfa0_g"]))<1e-12
    tests.append({"test": "Anexa 2 / clotoida reala", "ok": True})

    ab2 = elemente_anexe(alfa0_g=100.0)
    assert abs(ab2["clotoida_baza_A_1"]["t_rad_sqrt"]-math.sqrt(PI/2.0))<1e-12
    tests.append({"test": "Anexa 1 / unghi de capat", "ok": True})

    # Confruntare directa cu Anexa I, p. 114-115, t=0.820,
    # si Anexa II, p. 120-121, t=0.300 (valorile tabelate sunt rotunjite).
    ref = elemente_anexe(t=0.82)
    b = ref["clotoida_baza_A_1"]
    assert b["alpha_dms"] == "38.31.32"
    assert b["gamma_dms"] == "64.15.59"
    for label, target in {"x1_prim":0.5712,"x1_secund":0.5371,"delta1":0.0639,
                          "n1":1.3087,"b1":0.3216,"y01":0.9262}.items():
        _assert_close(b[label], target, 1.2e-4, "Anexa I t=0.82 / "+label)
    assert abs(b["x1_prim"]+b["x1_secund"]-b["x1"])<1e-12
    tests.append({"test":"Anexa I elemente omise / t=0.820", "ok":True})

    ratios = elemente_anexe(t=0.3)["rapoarte_anexa_II"]
    for label,target in {"s1_rho1":0.1800,"delta1_rho1":0.0013,
                         "x1_prim_rho1":0.0900,"n1_rho1":0.1803,
                         "delta1_s1":0.0075,"n1_s1":1.0019}.items():
        _assert_close(ratios[label], target, 1.0e-4, "Anexa II t=0.300 / "+label)
    tests.append({"test":"Anexa II sase rapoarte / t=0.300", "ok":True})

    assert elemente_anexe(t=1.205)["clotoida_baza_A_1"]["n1"] is None
    assert elemente_anexe(t=1.205)["rapoarte_anexa_II"]["n1_s1"] is None
    tests.append({"test":"Anexe n1/b1 netabelate dupa t=1.200", "ok":True})

    opt = [x for x in criterii_lungime_clotoida(90, 40) if x.nume.startswith("confort_optic")]
    assert len(opt)==1 and abs(opt[0].valoare_m-10)<1e-12
    tests.append({"test": "criteriu optic revizie 2026-11-16", "ok": True})

    return {"ok": True, "numar_teste": len(tests), "teste": tests}


# ---------------------------------------------------------------------------
# Export Excel pentru cele trei cazuri uzuale: CLC, arc simplu, CC
# ---------------------------------------------------------------------------

def export_excel_cazuri_uzuale(path: str | Path, cazuri: Sequence[dict[str, Any]]) -> Path:
    """
    Exporta unul sau mai multe cazuri intr-un singur workbook:
    - clc: clotoida intrare + arc central + clotoida iesire;
    - arc: arc de cerc simplu;
    - cc: doua clotoide simetrice fara arc central.

    Foloseste Excel COM prin PowerShell: Windows + Microsoft Excel instalat.
    """
    if os.name != "nt":
        raise RuntimeError(
            "Exportul .xlsx al scriptului foloseste Excel COM si necesita Windows + Microsoft Excel."
        )

    output = Path(path).expanduser().resolve()
    if output.suffix.lower() != ".xlsx":
        output = output.with_suffix(".xlsx")
    output.parent.mkdir(parents=True, exist_ok=True)

    payload = {"cases": list(cazuri)}

    powershell = r"""
param(
    [Parameter(Mandatory=$true)][string]$JsonPath,
    [Parameter(Mandatory=$true)][string]$OutputPath
)
$ErrorActionPreference = 'Stop'
$data = Get-Content -LiteralPath $JsonPath -Raw -Encoding UTF8 | ConvertFrom-Json
$excel = $null
$book = $null

function Set-AllBorders($range) {
    foreach ($edge in 7,8,9,10,11,12) {
        $border = $range.Borders.Item($edge)
        $border.LineStyle = 1
        $border.Weight = 2
        $border.Color = 0
    }
}

function Write-InputBlock($ws, $inputs) {
    $r = 1
    $ws.Cells.Item($r,16).Value2 = 'DATE DE INTRARE / REZULTATE'
    $ws.Range("P$r:Q$r").Merge()
    $ws.Range("P$r:Q$r").Font.Bold = $true
    $ws.Range("P$r:Q$r").HorizontalAlignment = -4108
    $ws.Range("P$r:Q$r").Interior.Color = 14277081
    $r++
    foreach ($item in $inputs) {
        $ws.Cells.Item($r,16).Value2 = [string]$item[0]
        $ws.Cells.Item($r,17).Value2 = $item[1]
        $r++
    }
    Set-AllBorders $ws.Range("P1:Q$($r-1)")
    $ws.Columns.Item(16).ColumnWidth = 24
    $ws.Columns.Item(17).ColumnWidth = 20
    $ws.Range("Q2:Q$($r-1)").NumberFormat = '0.0000'
}

function Write-ClothoidTable($ws, [int]$startRow, [string]$title, $rows) {
    $r1 = $startRow
    $r2 = $startRow + 1
    $r3 = $startRow + 2
    $ws.Range("A$r1:N$r1").Merge()
    $ws.Cells.Item($r1,1).Value2 = $title
    $ws.Range("A$r1:N$r1").Font.Bold = $true
    $ws.Range("A$r1:N$r1").HorizontalAlignment = -4108

    $ws.Range("A$r2:A$r3").Merge(); $ws.Cells.Item($r2,1).Value2 = 'PICHET'
    $ws.Cells.Item($r2,2).Value2 = 'α'
    $ws.Range("C$r2:E$r2").Merge(); $ws.Cells.Item($r2,3).Value2 = 'Coordonate polare'
    $ws.Range("F$r2:I$r2").Merge(); $ws.Cells.Item($r2,6).Value2 = 'Coordonate carteziene'
    $ws.Range("J$r2:K$r2").Merge(); $ws.Cells.Item($r2,10).Value2 = 'Lungime arc clotoidă'
    $ws.Range("L$r2:M$r2").Merge(); $ws.Cells.Item($r2,12).Value2 = 'Raze de curbură'
    $ws.Cells.Item($r2,14).Value2 = 'γ'

    $headers = @('(g,c,cc)','φ','r1','r','x1','x','y1','y','s1','s','ρ1','ρ','(g,c,cc)')
    for ($c=2; $c -le 14; $c++) { $ws.Cells.Item($r3,$c).Value2 = $headers[$c-2] }

    $row = $startRow + 3
    foreach ($record in $rows) {
        for ($col=1; $col -le 14; $col++) {
            $value = $record[$col-1]
            if ($null -eq $value) { $value = '∞' }
            $ws.Cells.Item($row,$col).Value2 = $value
        }
        $row++
    }
    $last = $row - 1
    $ws.Range("A$r1:N$last").HorizontalAlignment = -4108
    $ws.Range("A$r1:N$last").VerticalAlignment = -4108
    $ws.Range("A$r2:N$r3").Interior.Color = 15921906
    $ws.Range("B$($startRow+3):N$last").NumberFormat = '0.0000'
    Set-AllBorders $ws.Range("A$r1:N$last")
    return $last + 2
}

function Write-ArcSimpleTable($ws, [int]$startRow, [string]$title, $rows) {
    $r1 = $startRow
    $r2 = $startRow + 1
    $r3 = $startRow + 2
    $ws.Range("A$r1:F$r1").Merge()
    $ws.Cells.Item($r1,1).Value2 = $title
    $ws.Range("A$r1:F$r1").Font.Bold = $true
    $ws.Range("A$r1:F$r1").HorizontalAlignment = -4108

    $ws.Range("A$r2:A$r3").Merge(); $ws.Cells.Item($r2,1).Value2 = 'Picheți'
    $ws.Range("B$r2:C$r2").Merge(); $ws.Cells.Item($r2,2).Value2 = 'Coordonate polare'
    $ws.Range("D$r2:E$r2").Merge(); $ws.Cells.Item($r2,4).Value2 = 'Coordonate carteziene'
    $ws.Range("F$r2:F$r3").Merge(); $ws.Cells.Item($r2,6).Value2 = 'Lungime arc c'
    $headers = @('φ','r = 2R sin φ','x = r cos φ','y = r sin φ')
    for ($c=2; $c -le 5; $c++) { $ws.Cells.Item($r3,$c).Value2 = $headers[$c-2] }

    $row = $startRow + 3
    foreach ($record in $rows) {
        for ($col=1; $col -le 6; $col++) {
            $ws.Cells.Item($row,$col).Value2 = $record[$col-1]
        }
        $row++
    }
    $last = $row - 1
    $ws.Range("A$r1:F$last").HorizontalAlignment = -4108
    $ws.Range("A$r1:F$last").VerticalAlignment = -4108
    $ws.Range("A$r2:F$r3").Interior.Color = 15921906
    $ws.Range("B$($startRow+3):F$last").NumberFormat = '0.0000'
    Set-AllBorders $ws.Range("A$r1:F$last")
    return $last + 2
}

function Write-ArcCLCTable($ws, [int]$startRow, [string]$title, $rows) {
    $r1 = $startRow
    $r2 = $startRow + 1
    $r3 = $startRow + 2
    $ws.Range("A$r1:J$r1").Merge()
    $ws.Cells.Item($r1,1).Value2 = $title
    $ws.Range("A$r1:J$r1").Font.Bold = $true
    $ws.Range("A$r1:J$r1").HorizontalAlignment = -4108

    $ws.Range("A$r2:A$r3").Merge(); $ws.Cells.Item($r2,1).Value2 = 'Pichet'
    $ws.Range("B$r2:C$r2").Merge(); $ws.Cells.Item($r2,2).Value2 = 'Coordonate polare față de Si'
    $ws.Range("D$r2:E$r2").Merge(); $ws.Cells.Item($r2,4).Value2 = 'Coordonate carteziene față de Si'
    $ws.Range("F$r2:G$r2").Merge(); $ws.Cells.Item($r2,6).Value2 = 'Coordonate polare față de Oi'
    $ws.Range("H$r2:I$r2").Merge(); $ws.Cells.Item($r2,8).Value2 = 'Coordonate carteziene față de Oi'
    $ws.Range("J$r2:J$r3").Merge(); $ws.Cells.Item($r2,10).Value2 = 'Lungime arc c'
    $headers = @("r'=2Rsinφ'","φ'","x'","y'","r","φ","x","y")
    for ($c=2; $c -le 9; $c++) { $ws.Cells.Item($r3,$c).Value2 = $headers[$c-2] }

    $row = $startRow + 3
    foreach ($record in $rows) {
        for ($col=1; $col -le 10; $col++) {
            $ws.Cells.Item($row,$col).Value2 = $record[$col-1]
        }
        $row++
    }
    $last = $row - 1
    $ws.Range("A$r1:J$last").HorizontalAlignment = -4108
    $ws.Range("A$r1:J$last").VerticalAlignment = -4108
    $ws.Range("A$r2:J$r3").Interior.Color = 15921906
    $ws.Range("B$($startRow+3):J$last").NumberFormat = '0.0000'
    Set-AllBorders $ws.Range("A$r1:J$last")
    return $last + 2
}

try {
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $book = $excel.Workbooks.Add()
    while ($book.Worksheets.Count -gt 1) {
        $book.Worksheets.Item($book.Worksheets.Count).Delete()
    }

    $index = 0
    foreach ($case in $data.cases) {
        if ($index -eq 0) { $ws = $book.Worksheets.Item(1) }
        else { $ws = $book.Worksheets.Add() }
        $name = [string]$case.sheet
        $ws.Name = $name.Substring(0, [Math]::Min(31, $name.Length))
        Write-InputBlock $ws $case.inputs

        $row = 1
        foreach ($section in $case.sections) {
            if ($section.kind -eq 'clothoid') {
                $row = Write-ClothoidTable $ws $row ([string]$section.title) $section.rows
            }
            elseif ($section.kind -eq 'arc_simple') {
                $row = Write-ArcSimpleTable $ws $row ([string]$section.title) $section.rows
            }
            elseif ($section.kind -eq 'arc_clc') {
                $row = Write-ArcCLCTable $ws $row ([string]$section.title) $section.rows
            }
        }

        $widths = @(10,11,11,11,12,11,12,11,12,11,12,11,12,11)
        for ($c=1; $c -le 14; $c++) { $ws.Columns.Item($c).ColumnWidth = $widths[$c-1] }
        $ws.PageSetup.Orientation = 2
        $ws.PageSetup.Zoom = $false
        $ws.PageSetup.FitToPagesWide = 1
        $ws.PageSetup.FitToPagesTall = 0
        $index++
    }

    $book.SaveAs([System.IO.Path]::GetFullPath($OutputPath), 51)
}
finally {
    if ($book -ne $null) { $book.Close($false) }
    if ($excel -ne $null) { $excel.Quit() }
    if ($book -ne $null) { [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($book) }
    if ($excel -ne $null) { [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($excel) }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
"""

    with tempfile.TemporaryDirectory(prefix="clotoida_3cazuri_") as tmp:
        tmp_path = Path(tmp)
        json_path = tmp_path / "payload.json"
        ps_path = tmp_path / "export_3cazuri.ps1"
        json_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8-sig")
        ps_path.write_text(powershell, encoding="utf-8-sig")
        command = [
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(ps_path), "-JsonPath", str(json_path), "-OutputPath", str(output)
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise RuntimeError("powershell.exe nu a fost gasit.") from exc
        except subprocess.CalledProcessError as exc:
            details = (exc.stderr or exc.stdout or str(exc)).strip()
            raise RuntimeError(f"Exportul Excel a esuat: {details}") from exc
    return output


def construieste_caz_excel(
    tip: str,
    R_m: float,
    *,
    L_m: float | None = None,
    delta_g: float | None = None,
    U_g: float | None = None,
    n_cl: int = 8,
    n_arc: int = 5,
    sens: str = "stanga",
    mod_arc: str = "jumatate",
    sheet: str | None = None,
) -> dict[str, Any]:
    tip = tip.lower()
    R_m = _positive("R_m", R_m)
    sections: list[dict[str, Any]] = []
    inputs: list[list[Any]] = [["Tip", tip.upper()], ["R [m]", R_m], ["Sens", sens]]

    if tip == "arc":
        if delta_g is None:
            raise ValueError("Pentru tip=arc este obligatoriu --delta-g.")
        delta_g = _angle_open("delta_g", delta_g)
        puncte = tabel_arc_cerc_simplu(R_m, delta_g, n_arc, mod_arc, sens)
        C_total = PI * R_m * delta_g / 200.0
        inputs += [
            ["αc [g]", delta_g],
            ["C total [m]", C_total],
            ["nr. intervale", n_arc],
            ["mod tabel", mod_arc],
            ["Formula lungime", "c=πRβ/200"],
        ]
        sections.append({
            "kind": "arc_simple",
            "title": "CURBĂ ARC DE CERC SIMPLU",
            "rows": _rows_arc_simplu_excel(puncte),
        })
        return {"sheet": sheet or "Arc_cerc", "inputs": inputs, "sections": sections}

    if tip == "clc":
        if L_m is None or delta_g is None:
            raise ValueError("Pentru tip=clc sunt obligatorii --L si --delta-g.")
        L_m = _positive("L_m", L_m)
        delta_g = _angle_open("delta_g", delta_g)
        cl = rezultat_clotoida(R_m, L_m)
        delta_arc_g = delta_g - 2.0 * cl.alfa0_g
        if delta_arc_g <= 0:
            raise ValueError("Nu ramane arc central; folositi tip=cc.")
        C_arc = PI * R_m * delta_arc_g / 200.0
        puncte_cl = tabel_trasare(R_m, L_m, n_cl)
        puncte_arc = tabel_arc_central_clc(R_m, L_m, delta_g, n_arc, sens)
        inputs += [
            ["Lcl [m]", L_m],
            ["A [m]", cl.A_m],
            ["α0 [g]", cl.alfa0_g],
            ["Δ total [g]", delta_g],
            ["αc' arc [g]", delta_arc_g],
            ["C' arc [m]", C_arc],
            ["n clotoidă", n_cl],
            ["n arc", n_arc],
        ]
        sections += [
            {
                "kind": "clothoid",
                "title": "CLOTOIDĂ DE INTRARE",
                "rows": _rows_tabel_excel(puncte_cl, ordine="asc", sufix="i"),
            },
            {
                "kind": "arc_clc",
                "title": "ARC DE CERC CENTRAL",
                "rows": _rows_arc_clc_excel(puncte_arc),
            },
            {
                "kind": "clothoid",
                "title": "CLOTOIDĂ DE IEȘIRE — SIMETRICĂ",
                "rows": _rows_tabel_excel(puncte_cl, ordine="desc", sufix="e"),
            },
        ]
        return {"sheet": sheet or "Clotoida_Arc_Clotoida", "inputs": inputs, "sections": sections}

    if tip == "cc":
        if U_g is None:
            raise ValueError("Pentru tip=cc este obligatoriu --U-g.")
        result = caz2_ll_simetrica(U_g, R_m, n=n_cl)
        L_calc = result["L_fiecare_m"]
        puncte_cl = tabel_trasare(R_m, L_calc, n_cl)
        inputs += [
            ["U [g]", U_g],
            ["Δ total [g]", result["delta_total_g"]],
            ["α0 fiecare [g]", result["alfa0_g"]],
            ["L fiecare [m]", L_calc],
            ["A [m]", result["A_m"]],
            ["n clotoidă", n_cl],
        ]
        sections += [
            {
                "kind": "clothoid",
                "title": "CLOTOIDĂ DE INTRARE",
                "rows": _rows_tabel_excel(puncte_cl, ordine="asc", sufix="i"),
            },
            {
                "kind": "clothoid",
                "title": "CLOTOIDĂ DE IEȘIRE — SIMETRICĂ",
                "rows": _rows_tabel_excel(puncte_cl, ordine="desc", sufix="e"),
            },
        ]
        return {"sheet": sheet or "Clotoida_Clotoida", "inputs": inputs, "sections": sections}

    raise ValueError("tip trebuie sa fie unul dintre: clc, arc, cc.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _add_excel_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--xlsx", type=str, help="Cale pentru export Excel .xlsx formatat")
    parser.add_argument("--ordine", choices=["asc", "desc"], default="desc", help="Ordinea rândurilor în Excel")
    parser.add_argument("--sufix", default="i", help="Sufix pentru punctele O/S în tabelul Excel")


def _add_common_table_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--R", type=float, required=True, help="Raza la capatul clotoidei [m]")
    parser.add_argument("--L", type=float, required=True, help="Lungimea clotoidei [m]")
    parser.add_argument("--n", type=int, default=10, help="Numarul de intervale")
    parser.add_argument("--distante", type=str, help="Distanțe s explicite, separate prin virgulă")
    parser.add_argument("--csv", type=str, help="Cale optionala pentru export CSV")
    _add_excel_args(parser)



# ---------------------------------------------------------------------------
# Elemente din Anexele 1/2: consultare numerica, fara extragere grafica
# ---------------------------------------------------------------------------

def elemente_anexe(
    *,
    alfa0_g: float | None = None,
    t: float | None = None,
    raport_L_R: float | None = None,
    R_m: float | None = None,
    L_m: float | None = None,
    U_g: float | None = None,
    delta_g: float | None = None,
) -> dict[str, Any]:
    """Calculeaza elementele clotoidei de baza pentru A=1 si le scaleaza.

    Este o reconstituire analitica a valorilor de tip Anexa 1/2 din relatiile
    matematice ale clotoidei. Nu este o transcriere/verificare fata de fiecare
    celula a anexelor tiparite din carte.

    Se accepta UNA din intrarile de tabel: alfa0 [g], t=sqrt(alfa0 [rad]),
    sau raport L/R=s1/rho1. Alternativ, R si L determina intrarea in tabel.
    Pentru elemente reale se poate da o singura dimensiune (R sau L) plus
    una dintre intrarile de tabel; daca sunt date R si L, acestea se verifica.
    """
    sels = sum(x is not None for x in (alfa0_g, t, raport_L_R))
    if sels > 1:
        raise ValueError("Furnizati doar una: alfa0_g, t, raport_L_R.")
    if R_m is not None:
        R_m = _positive("R_m", R_m)
    if L_m is not None:
        L_m = _positive("L_m", L_m)

    if alfa0_g is not None:
        alfa0_g = _angle_open("alfa0_g", alfa0_g, 200.0)
        alfa_rad = gon_to_rad(alfa0_g)
        metoda = "Anexa 1: alfa0 [g]"
    elif t is not None:
        t = _positive("t", t)
        alfa_rad = t*t
        metoda = "Anexa 1/2: t=sqrt(alfa0[rad])"
    elif raport_L_R is not None:
        raport_L_R = _positive("raport_L_R", raport_L_R)
        alfa_rad = raport_L_R / 2.0
        metoda = "Anexa 2: s1/rho1=L/R"
    elif R_m is not None and L_m is not None:
        alfa_rad = L_m / (2.0*R_m)
        metoda = "R si L (intrare echivalenta in anexe)"
    else:
        raise ValueError("Introduceti --alpha0-g / --t / --raport sau perechea --R si --L.")

    if not math.isfinite(alfa_rad) or not (0.0 < alfa_rad < PI):
        raise ValueError("Unghiul la capat trebuie sa fie in (0, 200g).")
    raport = 2.0*alfa_rad
    alfa0_g = rad_to_gon(alfa_rad)
    t = math.sqrt(alfa_rad)

    if R_m is not None and L_m is not None:
        if not math.isclose(L_m/R_m, raport, rel_tol=1e-10, abs_tol=1e-12):
            raise ValueError("R, L si intrarea in anexa sunt incompatibile: L/R != 2*alfa0[rad].")
    elif R_m is not None:
        L_m = R_m*raport
    elif L_m is not None:
        R_m = L_m/raport

    s1 = math.sqrt(2.0*alfa_rad)  # A=1 -> s1=sqrt(2 alfa)
    rho1 = 1.0/s1
    baza = punct_clotoida(s1, 1.0, "S1")
    p1 = baza.y_m-rho1*(1.0-math.cos(alfa_rad))
    k1 = baza.x_m-rho1*math.sin(alfa_rad)
    # Anexa I, pp. 108-119: descompunerea abscisei si proiectia pe normala.
    # In notatia cartii: x'_1=k1, x''_1=rho1*sin(alpha), delta1=p1,
    # y01=rho1+delta1, n1=x1+y1*tan(alpha), b1=y1/cos(alpha).
    x1_secund = rho1 * math.sin(alfa_rad)
    y01 = rho1 + p1
    # Din tabelele scanate, autorul opreste n1 si b1 dupa t=1.200
    # (de la t=1.205 apar liniute), desi formulele matematice ar mai
    # produce valori pana aproape de alpha=pi/2. Respectam domeniul ANEXEI.
    n_b_tabelate = t <= 1.20000000001
    n1 = baza.x_m + baza.y_m*math.tan(alfa_rad) if n_b_tabelate else None
    b1 = baza.y_m/math.cos(alfa_rad) if n_b_tabelate else None
    # Anexa II, pp. 120-125: toate cele sase rapoarte (independente de A).
    rapoarte_II = {
        "s1_rho1": s1/rho1,
        "delta1_rho1": p1/rho1,
        "x1_prim_rho1": k1/rho1,
        "n1_rho1": None if n1 is None else n1/rho1,
        "delta1_s1": p1/s1,
        "n1_s1": None if n1 is None else n1/s1,
    }
    result: dict[str, Any] = {
        "metoda_intrare": metoda,
        "tip_calcul": "Analitic (integrale Fresnel); confruntare selectiva cu Anexele I si II",
        "clotoida_baza_A_1": {
            "alfa0_g": alfa0_g,
            "alfa0_rad": alfa_rad,
            "t_rad_sqrt": t,
            "raport_s1_rho1": raport,
            "s1": s1,
            "rho1": rho1,
            "x1": baza.x_m,
            "y1": baza.y_m,
            "r1": baza.r_m,
            "phi_g": baza.phi_g,
            "gamma_g": baza.gamma_g,
            "alpha_deg": gon_to_deg(alfa0_g),
            "phi_deg": gon_to_deg(baza.phi_g),
            "gamma_deg": gon_to_deg(baza.gamma_g),
            "alpha_dms": _sexagesimal_dms(alfa0_g),
            "phi_dms": _sexagesimal_dms(baza.phi_g),
            "gamma_dms": _sexagesimal_dms(baza.gamma_g),
            "x1_prim": k1,
            "x1_secund": x1_secund,
            "delta1": p1,
            "n1": n1,
            "b1": b1,
            "y01": y01,
            "n1_b1_tabelate_in_anexa_I": n_b_tabelate,
            "k1": k1,  # alias compatibil cu v1.3
            "p1": p1,  # alias compatibil cu v1.3
        },
        "rapoarte_anexa_II": rapoarte_II,
        "clotoida_reala": None,
        "racordare_CLC_simetrica": None,
    }
    if R_m is not None and L_m is not None:
        A = math.sqrt(R_m*L_m)
        real = rezultat_clotoida(R_m, L_m)
        result["clotoida_reala"] = {
            "R_m": R_m, "L_m": L_m, "A_m": A,
            "alfa0_g": real.alfa0_g,
            "x0_m": real.x0_m,
            "y0_m": real.y0_m,
            "r0_m": real.r0_m,
            "phi0_g": baza.phi_g,
            "gamma0_g": baza.gamma_g,
            "k_m": real.k_m,
            "p_m": real.p_m,
            "x_prim_m": A*k1,
            "x_secund_m": A*x1_secund,
            "delta_m": A*p1,
            "n_m": None if n1 is None else A*n1,
            "b_m": None if b1 is None else A*b1,
            "y0_cerc_m": A*y01,
            "verificare_A2_RL": math.isclose(A*A, R_m*L_m, rel_tol=1e-11),
            "verificare_rho_L_R": math.isclose(baza.rho_m*A, R_m, rel_tol=1e-11),
        }

    if U_g is not None and delta_g is not None:
        raise ValueError("Furnizati doar --U-g sau --delta-g, nu ambele.")
    if U_g is not None:
        delta_g = delta_din_U(U_g)
    if delta_g is not None:
        if R_m is None or L_m is None:
            raise ValueError("Unghiul virajului necesita si o scara reala: --R sau --L.")
        delta_g = _angle_open("delta_g", delta_g, 200.0)
        if delta_g <= 2.0*alfa0_g:
            result["racordare_CLC_simetrica"] = {
                "CLC_posibila": False,
                "delta_total_g": delta_g,
                "delta_arc_central_g": delta_g-2.0*alfa0_g,
                "observatie": "Nu ramane arc circular central; reconsiderati L/R sau tipul de racordare.",
            }
        else:
            clc = caz1_clc_simetrica(delta_g, R_m, L_m)
            result["racordare_CLC_simetrica"] = {
                key: val for key, val in clc.items() if key != "tabel_clotoida"
            }
    return result


def afiseaza_elemente_anexe(rez: dict[str, Any]) -> None:
    """Rezumat in notatia originala a anexelor, fara tabele de trasare."""
    print("ELEMENTE ANEXA I / ANEXA II — ION RACANEL (CALCUL ANALITIC)")
    print("Intrare:", rez["metoda_intrare"])
    for caption, key in (
        ("Anexa I — clotoida de baza A=1", "clotoida_baza_A_1"),
        ("Anexa II — rapoarte independente de A", "rapoarte_anexa_II"),
        ("Clotoida reala", "clotoida_reala"),
        ("Racordare CLC simetrica", "racordare_CLC_simetrica"),
    ):
        block = rez.get(key)
        if block is None:
            continue
        print(caption + ":")
        for k, v in block.items():
            if v is None:
                display = "— (necompletat in anexa / neaplicabil)"
            elif isinstance(v, bool):
                display = str(v)
            elif isinstance(v, (int, float)):
                display = f"{v:.10f}"
            else:
                display = str(v)
            print(f"  {k:31s} = {display}")
    print("NOTA: verificare selectiva cu randuri din Anexele I si II scanate;")
    print("nu este o transcriere integrala a tabelelor tiparite.")
    print("n1/b1 si rapoartele lor sunt marcate — pentru t>1.200, ca in anexe.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Motor unificat pentru clotoide si tipuri de racordare.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_table = sub.add_parser("table", help="Tabel de trasare pentru o clotoida")
    _add_common_table_args(p_table)

    p_case1 = sub.add_parser("case1", help="CLC simetrica")
    p_case1.add_argument("--delta-g", type=float, required=True, help="Unghi total la centru [g]")
    p_case1.add_argument("--R", type=float, required=True)
    p_case1.add_argument("--L", type=float, required=True)
    p_case1.add_argument("--V", type=float, help="Viteza [km/h], pentru pragul C'>=V/3.6")
    p_case1.add_argument("--min-arc", type=float, help="Prag explicit pentru arcul central [m]")
    p_case1.add_argument("--n", type=int, default=10)
    _add_excel_args(p_case1)

    p_case2 = sub.add_parser("case2", help="Doua clotoide simetrice fara arc central")
    p_case2.add_argument("--U-g", type=float, required=True)
    p_case2.add_argument("--R", type=float, required=True)
    p_case2.add_argument("--L-min", type=float)
    p_case2.add_argument("--n", type=int, default=10)
    _add_excel_args(p_case2)

    p_case3 = sub.add_parser("case3", help="Doua clotoide nesimetrice fara arc central")
    p_case3.add_argument("--U-g", type=float, required=True)
    p_case3.add_argument("--R", type=float, required=True)
    p_case3.add_argument("--alpha1-g", type=float, required=True)
    p_case3.add_argument("--n", type=int, default=10)
    _add_excel_args(p_case3)

    p_report = sub.add_parser(
        "raport",
        help="Export Excel pentru unul dintre cele 3 cazuri uzuale: clc, arc, cc",
    )
    p_report.add_argument("--tip", choices=["clc", "arc", "cc"], required=True)
    p_report.add_argument("--R", type=float, required=True, help="Raza [m]")
    p_report.add_argument("--L", type=float, help="Lungimea unei clotoide [m], obligatorie la clc")
    p_report.add_argument("--delta-g", type=float, help="Unghi total la centru [g], pentru clc/arc")
    p_report.add_argument("--U-g", type=float, help="Unghiul la varf [g], pentru cc")
    p_report.add_argument("--n-cl", type=int, default=8, help="Numar intervale pe clotoida")
    p_report.add_argument("--n-arc", type=int, default=5, help="Numar intervale pe arc")
    p_report.add_argument("--sens", choices=["stanga", "dreapta"], default="stanga")
    p_report.add_argument(
        "--mod-arc", choices=["jumatate", "complet"], default="jumatate",
        help="Pentru arc simplu: Ti-B sau Ti-Te",
    )
    p_report.add_argument("--xlsx", required=True, help="Fisierul Excel rezultat")

    p_serp = sub.add_parser("serpentina2", help="Serpentina categoria a II-a")
    p_serp.add_argument("--U-g", type=float, required=True)
    p_serp.add_argument("--R2", type=float, required=True)
    p_serp.add_argument("--F", type=float, required=True)
    p_serp.add_argument("--x", type=float, required=True)
    p_serp.add_argument("--y", type=float, required=True)
    p_serp.add_argument("--xlsx", type=str, help="Cale pentru export Excel .xlsx")

    p_case4 = sub.add_parser("case4", help="Boltă între aliniamente paralele")
    p_case4.add_argument("--D", type=float, required=True)
    p_case4.add_argument("--xlsx", type=str)

    p_case5 = sub.add_parser("case5", help="Racordare în dușină")
    p_case5.add_argument("--R1", type=float, required=True)
    p_case5.add_argument("--R2", type=float, required=True)
    p_case5.add_argument("--D", type=float)
    p_case5.add_argument("--xlsx", type=str)

    p_case7 = sub.add_parser("case7", help="Arc individual de clotoidă pentru buclă")
    p_case7.add_argument("--R", type=float, required=True)
    p_case7.add_argument("--alpha0-g", type=float, required=True)
    p_case7.add_argument("--n", type=int, default=20)
    _add_excel_args(p_case7)

    p_case8 = sub.add_parser("case8", help="Racordare ovoidală - raport raze")
    p_case8.add_argument("--R1", type=float, required=True)
    p_case8.add_argument("--R2", type=float, required=True)
    p_case8.add_argument("--xlsx", type=str)

    p_inventory = sub.add_parser("inventory", help="Inventarul celor 8 cazuri si starea lor")
    p_inventory.add_argument("--xlsx", type=str)
    sub.add_parser("selftest", help="Ruleaza verificarile numerice incluse")

    p_abac = sub.add_parser("abac", help="TOATE elementele Anexa I si cele 6 rapoarte Anexa II, analitic")
    grp = p_abac.add_mutually_exclusive_group()
    grp.add_argument("--alpha0-g", type=float, help="Unghi clotoida la capat [g]; Anexa 1")
    grp.add_argument("--t", type=float, help="Parametrul t=sqrt(alpha0[rad])")
    grp.add_argument("--raport", type=float, help="Raport s1/rho1=L/R; Anexa 2")
    p_abac.add_argument("--R", type=float, help="Raza reala la capatul clotoidei [m]")
    p_abac.add_argument("--L", type=float, help="Lungimea reala a clotoidei [m]")
    grpvir = p_abac.add_mutually_exclusive_group()
    grpvir.add_argument("--U-g", type=float, help="Unghiul la varf [g] pentru CLC")
    grpvir.add_argument("--delta-g", type=float, help="Unghiul total la centru [g] pentru CLC")
    p_abac.add_argument("--json", action="store_true", help="Afisare JSON complet")
    p_abac.add_argument("--csv", help="Export parametru/valoare pentru Excel")
    p_abac.add_argument("--xlsx", help="Export Excel nativ (Windows, Excel instalat)")
    p_abac.add_argument("--n", type=int, default=10, help="Intervale in tabelul de trasare Excel")

    return parser


def _parse_distante(value: str | None) -> list[float] | None:
    if value is None:
        return None
    # Pentru notația românească se recomandă separatorul ";":
    # --distante "0;7,2831;14,3409;57,0417"
    if ";" in value:
        tokens = [token.strip().replace(",", ".") for token in value.split(";") if token.strip()]
    else:
        tokens = [token.strip() for token in value.split(",") if token.strip()]
    if not tokens:
        raise ValueError("--distante nu conține valori numerice.")
    return [float(token) for token in tokens]


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "abac":
        result = elemente_anexe(
            alfa0_g=args.alpha0_g, t=args.t, raport_L_R=args.raport,
            R_m=args.R, L_m=args.L, U_g=args.U_g, delta_g=args.delta_g,
        )
        if args.json:
            print_json(result)
        else:
            afiseaza_elemente_anexe(result)
        if args.csv:
            out = Path(args.csv)
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open("w", newline="", encoding="utf-8-sig") as fd:
                wr = csv.writer(fd)
                wr.writerow(["parametru", "valoare"])
                wr.writerows(_flatten_summary(result))
            print(f"CSV: {out}")
        if args.xlsx:
            real = result["clotoida_reala"]
            tables = []
            if real is not None:
                tables = [{"sheet": "Clotoida", "points": tabel_trasare(real["R_m"], real["L_m"], args.n)}]
            output = export_excel_native(args.xlsx, tables=tables, summary=result)
            print(f"XLSX: {output}")
        return 0

    if args.command == "table":
        points = tabel_trasare(args.R, args.L, args.n, _parse_distante(args.distante))
        print_tabel(points)
        closure = verifica_inchidere(args.R, args.L)
        print_json(closure)
        if args.csv:
            output = export_tabel_csv(args.csv, points)
            print(f"CSV: {output}")
        if args.xlsx:
            output = export_excel_native(
                args.xlsx,
                tables=[{
                    "sheet": "Clotoida",
                    "title": "COORDONATE DE TRASARE PENTRU CLOTOIDĂ",
                    "points": points,
                    "ordine": args.ordine,
                    "sufix": args.sufix,
                }],
                summary={"intrari": {"R_m": args.R, "L_m": args.L, "n": args.n}, "verificare": closure},
            )
            print(f"XLSX: {output}")
        return 0

    if args.command == "raport":
        case_spec = construieste_caz_excel(
            args.tip,
            args.R,
            L_m=args.L,
            delta_g=args.delta_g,
            U_g=args.U_g,
            n_cl=args.n_cl,
            n_arc=args.n_arc,
            sens=args.sens,
            mod_arc=args.mod_arc,
        )
        output = export_excel_cazuri_uzuale(args.xlsx, [case_spec])
        print(f"XLSX: {output}")
        return 0

    if args.command == "case1":
        result = caz1_clc_simetrica(
            delta_g=args.delta_g,
            R_m=args.R,
            L_m=args.L,
            V_kmh=args.V,
            min_arc_m=args.min_arc,
            n=args.n,
        )
        print_json(result)
        if args.xlsx:
            points = tabel_trasare(args.R, args.L, args.n)
            output = export_excel_native(
                args.xlsx,
                tables=[{"sheet": "Clotoida", "points": points, "ordine": args.ordine, "sufix": args.sufix}],
                summary=result,
            )
            print(f"XLSX: {output}")
        return 0

    if args.command == "case2":
        result = caz2_ll_simetrica(args.U_g, args.R, args.L_min, args.n)
        print_json(result)
        if args.xlsx:
            points = tabel_trasare(args.R, result["L_fiecare_m"], args.n)
            output = export_excel_native(
                args.xlsx,
                tables=[{"sheet": "Clotoida", "points": points, "ordine": args.ordine, "sufix": args.sufix}],
                summary=result,
            )
            print(f"XLSX: {output}")
        return 0

    if args.command == "case3":
        result = caz3_ll_nesimetrica(args.U_g, args.R, args.alpha1_g, args.n)
        print_json(result)
        if args.xlsx:
            p1 = tabel_trasare(args.R, result["clotoida_1"]["L_m"], args.n)
            p2 = tabel_trasare(args.R, result["clotoida_2"]["L_m"], args.n)
            output = export_excel_native(
                args.xlsx,
                tables=[
                    {"sheet": "Clotoida_1", "points": p1, "ordine": args.ordine, "sufix": "i"},
                    {"sheet": "Clotoida_2", "points": p2, "ordine": args.ordine, "sufix": "e"},
                ],
                summary=result,
            )
            print(f"XLSX: {output}")
        return 0

    if args.command == "serpentina2":
        result = caz6_serpentina_categoria_II(args.U_g, args.R2, args.F, args.x, args.y)
        print_json(result)
        if args.xlsx:
            output = export_excel_native(args.xlsx, summary=result)
            print(f"XLSX: {output}")
        return 0

    if args.command == "case4":
        result = caz4_bolta_aliniamente_paralele(args.D)
        print_json(result)
        if args.xlsx:
            output = export_excel_native(args.xlsx, summary=result)
            print(f"XLSX: {output}")
        return 0

    if args.command == "case5":
        result = caz5_dusina(args.R1, args.R2, args.D)
        print_json(result)
        if args.xlsx:
            output = export_excel_native(args.xlsx, summary=result)
            print(f"XLSX: {output}")
        return 0

    if args.command == "case7":
        result = caz7_arc_individual_bucla(args.R, args.alpha0_g, args.n)
        print_json(result)
        if args.xlsx:
            points = tabel_trasare(result["R_m"], result["L_m"], args.n)
            output = export_excel_native(
                args.xlsx,
                tables=[{"sheet": "Clotoida_bucla", "points": points, "ordine": args.ordine, "sufix": args.sufix}],
                summary=result,
            )
            print(f"XLSX: {output}")
        return 0

    if args.command == "case8":
        result = caz8_ovoidala_raport(args.R1, args.R2)
        print_json(result)
        if args.xlsx:
            output = export_excel_native(args.xlsx, summary=result)
            print(f"XLSX: {output}")
        return 0

    if args.command == "inventory":
        result = inventar_cazuri()
        print_json(result)
        if args.xlsx:
            output = export_excel_native(args.xlsx, summary={"cazuri": result})
            print(f"XLSX: {output}")
        return 0

    if args.command == "selftest":
        print_json(selftest())
        return 0

    raise RuntimeError(f"Comanda neimplementata: {args.command}")

if __name__ == "__main__":
    raise SystemExit(main())

