
import re
import sys
import math
import argparse
from datetime import datetime
from typing import List, Dict, Optional

import requests
from bs4 import BeautifulSoup
import pandas as pd

URL = "https://agrural.com.br/precossojaemilho/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
}

# ------------ utilidades ------------
def normalize(s: str) -> str:
    return (s or "").strip().replace("\xa0", " ")

def br_to_float(text: str) -> float:

    if text is None:
        return float("nan")
    t = text.strip().replace("\xa0", " ")
    t = t.replace("−", "-").replace("\u2212", "-")
    t = t.replace(".", "").replace(",", ".").replace("%", "").strip()
    if t in {"", "-", "—"}:
        return float("nan")
    try:
        return float(t)
    except ValueError:
        return float("nan")

def find_soja_table(soup: BeautifulSoup) -> Optional[BeautifulSoup]:

    for h in soup.find_all(["h2", "h3", "h4", "strong", "p"]):
        if "soja" in h.get_text(" ", strip=True).lower():
            tbl = h.find_next("table")
            if tbl:
                return tbl

    for tbl in soup.find_all("table"):
        text = tbl.get_text(" ", strip=True).lower()
        if all(x in text for x in ["estado", "praça", "compra"]):
            return tbl
    return None

def parse_date_near(table: BeautifulSoup) -> Optional[str]:

    prev_txt = []
    node = table
    for _ in range(8):
        node = node.find_previous(string=True)
        if not node:
            break
        prev_txt.append(str(node))
    blob = " ".join(prev_txt)
    m = re.search(r"(\d{2}-[A-Za-z]{3}-\d{2,4})", blob)
    if not m:
        return None
    raw = m.group(1)
    for fmt in ("%d-%b-%y", "%d-%b-%Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            pass
    pt_to_en = {"jan":"Jan","fev":"Feb","mar":"Mar","abr":"Apr","mai":"May","jun":"Jun",
                "jul":"Jul","ago":"Aug","set":"Sep","out":"Oct","nov":"Nov","dez":"Dec"}
    m2 = re.search(r"(\d{2})-([A-Za-z]{3})-(\d{2,4})", raw, flags=re.IGNORECASE)
    if m2:
        d, mon, y = m2.groups()
        mon_en = pt_to_en.get(mon.lower(), mon.title())
        for fmt in ("%d-%b-%y", "%d-%b-%Y"):
            try:
                return datetime.strptime(f"{d}-{mon_en}-{y}", fmt).date().isoformat()
            except ValueError:
                pass
    return None


def expand_html_table(table: BeautifulSoup) -> List[List[str]]:

    body = table.find("tbody") or table
    rows_raw = body.find_all("tr")
    grid: List[List[str]] = []
    # mapa: col_index -> (valor, restantes) para células que continuam nas próximas linhas
    carry: Dict[int, Dict[str, object]] = {}

    for tr in rows_raw:
        cells = tr.find_all(["td", "th"])
        # linha atual começando com valores "carregados" de rowspans anteriores
        current: List[Optional[str]] = []
        col_idx = 0


        while True:
            if col_idx in carry and carry[col_idx]["left"] > 0:
                current.append(carry[col_idx]["val"])
                carry[col_idx]["left"] -= 1
                if carry[col_idx]["left"] == 0:
                    del carry[col_idx]
                col_idx += 1
            else:
                break


        for cell in cells:
            # avança col_idx até a próxima coluna livre (pode ter múltiplos carregados)
            while col_idx in carry and carry[col_idx]["left"] > 0:
                current.append(carry[col_idx]["val"])
                carry[col_idx]["left"] -= 1
                if carry[col_idx]["left"] == 0:
                    del carry[col_idx]
                col_idx += 1

            text = normalize(cell.get_text(" ", strip=True))
            rs = cell.get("rowspan")
            try:
                rs = int(rs) if rs else 1
            except Exception:
                rs = 1

            current.append(text)

            if rs > 1:
                carry[col_idx] = {"val": text, "left": rs - 1}

            col_idx += 1


        grid.append([c if c is not None else "" for c in current])

    return grid


def fetch_rows() -> List[Dict]:
    resp = requests.get(URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    table = find_soja_table(soup)
    if table is None:
        raise RuntimeError("Tabela de Soja não encontrada (layout pode ter mudado).")

    date_iso = parse_date_near(table)
    grid = expand_html_table(table)
    if not grid:
        return []


    header_row = None
    for i, row in enumerate(grid[:3]):  # primeiras linhas costumam ter o header
        low = [cell.lower() for cell in row]
        if "estado" in " ".join(low) and "praça" in " ".join(low) and "compra" in " ".join(low):
            header_row = i
            break

    if header_row is None:
        header = [r for r in grid[0] if r]
    else:
        header = grid[header_row]

    lower = [h.lower() for h in header]
    def idx_of(*names):
        for i, h in enumerate(lower):
            for nm in names:
                if nm in h:
                    return i
        return None

    i_estado = idx_of("estado")
    i_praca  = idx_of("praça", "praca")
    i_compra = idx_of("compra")
    i_var_d  = idx_of("variação hoje", "variacao hoje", "variação do dia", "var hoje")
    i_var_w  = idx_of("1 semana", "semana")
    i_var_m  = idx_of("1 mês", "1 mes", "mês", "mes")

    # dados começam após o cabeçalho, se detectado
    start_idx = (header_row + 1) if header_row is not None else 1
    data_rows = grid[start_idx:]

    rows: List[Dict] = []
    last_uf: Optional[str] = None

    for r in data_rows:
        # ignora linhas vazias ou de rodapé
        joined_lower = " ".join([c.lower() for c in r])
        if "agrural" in joined_lower:
            continue
        # fallback se não achamos índices: usa últimas 5 colunas como dados
        if None in (i_praca, i_compra, i_var_d, i_var_w, i_var_m):
            if len(r) < 5:
                continue
            praca, compra, var_dia, var_sem, var_mes = r[-5:]
            uf_cell = r[0] if r else ""
        else:
            uf_cell = r[i_estado] if (i_estado is not None and i_estado < len(r)) else ""
            praca   = r[i_praca]  if (i_praca  is not None and i_praca  < len(r)) else ""
            compra  = r[i_compra] if (i_compra is not None and i_compra < len(r)) else ""
            var_dia = r[i_var_d]  if (i_var_d  is not None and i_var_d  < len(r)) else ""
            var_sem = r[i_var_w]  if (i_var_w  is not None and i_var_w  < len(r)) else ""
            var_mes = r[i_var_m]  if (i_var_m  is not None and i_var_m  < len(r)) else ""

        # UF: pega da célula ou carrega da anterior
        uf = None
        if re.fullmatch(r"[A-Z]{2}", (uf_cell or "").strip()):
            uf = uf_cell.strip()
            last_uf = uf
        else:
            uf = last_uf

        # números
        compra_f = br_to_float(compra)
        var_dia_f = br_to_float(var_dia)
        var_sem_f = br_to_float(var_sem)
        var_mes_f = br_to_float(var_mes)

        # filtros mínimos
        if not praca or math.isnan(compra_f):
            continue
        if praca.lower() in {"praça", "praca"}:
            continue

        rows.append({
            "data": date_iso,
            "uf": uf,
            "praca": praca,
            "compra_R$/sc": compra_f,
            "var_dia_%": var_dia_f,
            "var_sem_%": var_sem_f,
            "var_mes_%": var_mes_f,
        })

    return rows

def main(output_csv: str = "soja_agrural.csv"):
    rows = fetch_rows()
    if not rows:
        print("Nenhuma linha capturada. O layout pode ter mudado.", file=sys.stderr)
        return 2

    df = pd.DataFrame(rows, columns=[
        "data", "uf", "praca", "compra_R$/sc", "var_dia_%", "var_sem_%", "var_mes_%"
    ])
    # ffill para garantir UF nas linhas sob rowspan
    df["uf"] = df["uf"].ffill()
    df = df.dropna(subset=["uf", "praca"]).reset_index(drop=True)

    df.to_csv(output_csv, index=False, encoding="utf-8")
    print(f"OK! {len(df)} linhas salvas em {output_csv}")
    return 0

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scraper de preços de Soja (AgRural) — v4 (rowspan robusto).")
    parser.add_argument("-o", "--output", default="soja_agrural.csv", help="Caminho do CSV de saída.")
    args = parser.parse_args()
    sys.exit(main(args.output))
