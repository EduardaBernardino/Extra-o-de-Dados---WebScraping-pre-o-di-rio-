import re, sys, math, argparse
from datetime import datetime, date as _date
from typing import List, Dict, Optional

import requests
from bs4 import BeautifulSoup
import pandas as pd
import pyodbc

URL = "https://agrural.com.br/precossojaemilho/"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"}

# ----------- util -----------
def normalize(s: str) -> str:
    return (s or "").strip().replace("\xa0", " ")

def br_to_float(text: str) -> float:
    if text is None:
        return float("nan")
    t = text.strip().replace("\xa0", " ").replace("−", "-").replace("\u2212", "-")
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
            t = h.find_next("table")
            if t:
                return t
    for t in soup.find_all("table"):
        txt = t.get_text(" ", strip=True).lower()
        if all(x in txt for x in ["estado", "praça", "compra"]):
            return t
    return None

def parse_date_near(table: BeautifulSoup) -> Optional[str]:
    prev = []
    node = table
    for _ in range(8):
        node = node.find_previous(string=True)
        if not node:
            break
        prev.append(str(node))
    blob = " ".join(prev)
    m = re.search(r"(\d{2}-[A-Za-z]{3}-\d{2,4})", blob)
    if not m:
        return None
    raw = m.group(1)
    for fmt in ("%d-%b-%y", "%d-%b-%Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            pass
    pt2en = {
        "jan": "Jan", "fev": "Feb", "mar": "Mar", "abr": "Apr", "mai": "May", "jun": "Jun",
        "jul": "Jul", "ago": "Aug", "set": "Sep", "out": "Oct", "nov": "Nov", "dez": "Dec",
    }
    m2 = re.search(r"(\d{2})-([A-Za-z]{3})-(\d{2,4})", raw, flags=re.IGNORECASE)
    if m2:
        d, mon, y = m2.groups()
        mon = pt2en.get(mon.lower(), mon.title())
        for fmt in ("%d-%b-%y", "%d-%b-%Y"):
            try:
                return datetime.strptime(f"{d}-{mon}-{y}", fmt).date().isoformat()
            except ValueError:
                pass
    return None

def expand_html_table(table: BeautifulSoup) -> List[List[str]]:
    body = table.find("tbody") or table
    rows_raw = body.find_all("tr")
    grid, carry = [], {}  # col -> {"val": str, "left": int}
    for tr in rows_raw:
        cells = tr.find_all(["td", "th"])
        cur, col = [], 0
        while col in carry and carry[col]["left"] > 0:
            cur.append(carry[col]["val"])
            carry[col]["left"] -= 1
            if carry[col]["left"] == 0:
                del carry[col]
            col += 1
        for c in cells:
            while col in carry and carry[col]["left"] > 0:
                cur.append(carry[col]["val"])
                carry[col]["left"] -= 1
                if carry[col]["left"] == 0:
                    del carry[col]
                col += 1
            txt = normalize(c.get_text(" ", strip=True))
            rs = int(c.get("rowspan") or 1)
            cur.append(txt)
            if rs > 1:
                carry[col] = {"val": txt, "left": rs - 1}
            col += 1
        grid.append([x if x is not None else "" for x in cur])
    return grid

def fetch_rows() -> List[Dict]:
    soup = BeautifulSoup(requests.get(URL, headers=HEADERS, timeout=30).text, "html.parser")
    table = find_soja_table(soup)
    if table is None:
        raise RuntimeError("Tabela de Soja não encontrada.")
    date_iso = parse_date_near(table)
    # Fallback: se não achar a data no HTML, usa a data de hoje (YYYY-MM-DD)
    if not date_iso:
        date_iso = _date.today().isoformat()

    grid = expand_html_table(table)
    if not grid:
        return []

    # header
    hdr_i = None
    for i, row in enumerate(grid[:3]):
        low = [c.lower() for c in row]
        if "estado" in " ".join(low) and "praça" in " ".join(low) and "compra" in " ".join(low):
            hdr_i = i
            break
    header = grid[hdr_i] if hdr_i is not None else grid[0]
    lower = [h.lower() for h in header]

    def idx_of(*names):
        for i, h in enumerate(lower):
            if any(n in h for n in names):
                return i
        return None

    i_estado = idx_of("estado")
    i_praca  = idx_of("praça", "praca")
    i_compra = idx_of("compra")
    i_var_d  = idx_of("variação hoje", "variacao hoje", "variação do dia", "var hoje")
    i_var_w  = idx_of("1 semana", "semana")
    i_var_m  = idx_of("1 mês", "1 mes", "mês", "mes")

    start = (hdr_i + 1) if hdr_i is not None else 1
    data_rows = grid[start:]

    rows, last_uf = [], None
    for r in data_rows:
        if "agrural" in " ".join([c.lower() for c in r]):
            continue
        uf_cell = r[i_estado] if (i_estado is not None and i_estado < len(r)) else (r[0] if r else "")
        uf = uf_cell if re.fullmatch(r"[A-Z]{2}", (uf_cell or "").strip()) else last_uf
        if re.fullmatch(r"[A-Z]{2}", (uf_cell or "").strip()):
            last_uf = uf

        if None in (i_praca, i_compra, i_var_d, i_var_w, i_var_m):
            if len(r) < 5:
                continue
            praca, compra, var_d, var_w, var_m = r[-5:]
        else:
            praca = r[i_praca] if i_praca is not None and i_praca < len(r) else ""
            compra = r[i_compra] if i_compra is not None and i_compra < len(r) else ""
            var_d = r[i_var_d] if i_var_d is not None and i_var_d < len(r) else ""
            var_w = r[i_var_w] if i_var_w is not None and i_var_w < len(r) else ""
            var_m = r[i_var_m] if i_var_m is not None and i_var_m < len(r) else ""

        compra_f, var_d_f, var_w_f, var_m_f = map(br_to_float, [compra, var_d, var_w, var_m])
        if not praca or math.isnan(compra_f) or praca.lower() in {"praça", "praca"}:
            continue

        rows.append({
            "data": date_iso, "uf": uf, "praca": praca,
            "compra_R$/sc": compra_f, "var_dia_%": var_d_f,
            "var_sem_%": var_w_f, "var_mes_%": var_m_f
        })
    return rows

# ----------- SQL -----------
CREATE_TABLE_SQL = r"""
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'PrecoSoja' AND schema_id = SCHEMA_ID('dbo'))
BEGIN
  CREATE TABLE dbo.PrecoSoja(
    [data] date NOT NULL,
    [uf] char(2) NOT NULL,
    [praca] nvarchar(120) NOT NULL,
    [compra_rs_sc] decimal(10,2) NOT NULL,
    [var_dia_pct]  decimal(6,2) NULL,
    [var_sem_pct]  decimal(6,2) NULL,
    [var_mes_pct]  decimal(6,2) NULL,
    [fonte] nvarchar(100) NOT NULL CONSTRAINT DF_PrecoSoja_fonte DEFAULT(N'AgRural'),
    [load_ts] datetime2(0) NOT NULL CONSTRAINT DF_PrecoSoja_load DEFAULT(SYSUTCDATETIME()),
    CONSTRAINT PK_PrecoSoja PRIMARY KEY([data],[uf],[praca])
  );
END
"""

MERGE_SQL = r"""
MERGE dbo.PrecoSoja AS T
USING #stg AS S
  ON T.[data]=S.[data] AND T.[uf]=S.[uf] AND T.[praca]=S.[praca]
WHEN MATCHED AND (
  ISNULL(T.[compra_rs_sc],-1)<>ISNULL(S.[compra_rs_sc],-1) OR
  ISNULL(T.[var_dia_pct],-999)<>ISNULL(S.[var_dia_pct],-999) OR
  ISNULL(T.[var_sem_pct],-999)<>ISNULL(S.[var_sem_pct],-999) OR
  ISNULL(T.[var_mes_pct],-999)<>ISNULL(S.[var_mes_pct],-999)
) THEN UPDATE SET
  T.[compra_rs_sc]=S.[compra_rs_sc],
  T.[var_dia_pct]=S.[var_dia_pct],
  T.[var_sem_pct]=S.[var_sem_pct],
  T.[var_mes_pct]=S.[var_mes_pct],
  T.[load_ts]=SYSUTCDATETIME()
WHEN NOT MATCHED BY TARGET THEN
  INSERT([data],[uf],[praca],[compra_rs_sc],[var_dia_pct],[var_sem_pct],[var_mes_pct])
  VALUES(S.[data],S.[uf],S.[praca],S.[compra_rs_sc],S.[var_dia_pct],S.[var_sem_pct],S.[var_mes_pct]);
"""

def upsert_to_sqlserver(rows: List[Dict], conn_str: str):
    if not rows:
        print("Nenhuma linha para inserir/atualizar.")
        return

    cn = pyodbc.connect(conn_str)
    try:
        cn.autocommit = False
        cur = cn.cursor()

        try:
            cur.fast_executemany = True
        except Exception:
            pass


        cur.execute(CREATE_TABLE_SQL)


        cur.execute("""
            IF OBJECT_ID('tempdb..#stg') IS NOT NULL DROP TABLE #stg;
            CREATE TABLE #stg (
                [data] date NOT NULL,
                [uf]   char(2) NOT NULL,
                [praca] nvarchar(120) NOT NULL,
                [compra_rs_sc] decimal(10,2) NOT NULL,
                [var_dia_pct]  decimal(6,2) NULL,
                [var_sem_pct]  decimal(6,2) NULL,
                [var_mes_pct]  decimal(6,2) NULL
            );
        """)

        params = [
            (
                r["data"], r["uf"], r["praca"],
                float(r["compra_R$/sc"]) if pd.notna(r["compra_R$/sc"]) else None,
                float(r["var_dia_%"])    if pd.notna(r["var_dia_%"])    else None,
                float(r["var_sem_%"])    if pd.notna(r["var_sem_%"])    else None,
                float(r["var_mes_%"])    if pd.notna(r["var_mes_%"])    else None,
            )
            for r in rows
        ]

        cur.executemany(
            "INSERT INTO #stg ([data],[uf],[praca],[compra_rs_sc],[var_dia_pct],[var_sem_pct],[var_mes_pct]) "
            "VALUES (?,?,?,?,?,?,?)",
            params
        )

        # 3) MERGE
        cur.execute(MERGE_SQL)

        cn.commit()
        print(f"Upsert concluído: {len(rows)} linhas processadas.")
    finally:
        cn.close()

# ----------- helpers -----------
def build_conn_str(args) -> str:
    base = f"Driver={{{args.driver}}};Server={args.server};Database={args.database};"
    if args.auth == "windows":
        return base + f"Trusted_Connection=yes;Encrypt={args.encrypt};TrustServerCertificate={args.trust};"
    else:
        return base + f"Uid={args.user};Pwd={args.password};Encrypt={args.encrypt};TrustServerCertificate={args.trust};"

def get_max_date_from_db(conn_str: str) -> Optional[str]:
    cn = pyodbc.connect(conn_str)
    try:
        cur = cn.cursor()
        cur.execute(
            "IF OBJECT_ID('dbo.PrecoSoja','U') IS NOT NULL "
            "SELECT MAX([data]) FROM dbo.PrecoSoja ELSE SELECT NULL"
        )
        row = cur.fetchone()
        return row[0].isoformat() if row and row[0] else None
    finally:
        cn.close()


def main() -> int:
    p = argparse.ArgumentParser(description="Scrape AgRural (Soja) e upsert no SQL Server (Windows/SQL Auth).")
    p.add_argument("--server", required=True, help=r'Ex.: BS-NOT-BS01Q1\SQLEXPRESS ou localhost\SQLEXPRESS')
    p.add_argument("--database", default="CotacaoSoja")
    p.add_argument("--auth", choices=["windows", "sql"], default="windows")
    p.add_argument("--user", help="(se auth=sql)")
    p.add_argument("--password", help="(se auth=sql)")
    p.add_argument("--driver", default="ODBC Driver 18 for SQL Server")
    # Para SQL Express local, se criptografia der erro, use: --encrypt yes --trust yes OU --encrypt no
    p.add_argument("--encrypt", default="yes", choices=["yes", "no"])
    p.add_argument("--trust", default="yes", choices=["yes", "no"])
    args = p.parse_args()

    conn_str = build_conn_str(args)


    rows = fetch_rows()
    # ffill UF (linhas sob rowspan)
    for i in range(1, len(rows)):
        if not rows[i]["uf"]:
            rows[i]["uf"] = rows[i - 1]["uf"]


    scrape_date = next((r.get("data") for r in rows if r.get("data")), None)
    if not scrape_date:
        print("⚠️ Data do site não encontrada. Nada gravado (evitando data incorreta).")
        return 0


    last = get_max_date_from_db(conn_str)
    if last and scrape_date <= last:
        print(f"ℹ️ Sem novidades: site={scrape_date} <= banco={last}. Nada a fazer.")
        return 0

    upsert_to_sqlserver(rows, conn_str)
    return 0

if __name__ == "__main__":
    sys.exit(main())
