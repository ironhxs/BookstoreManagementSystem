import argparse
import json
import re
from pathlib import Path

import psycopg2


PROJECT_TABLES = [
    "book_category",
    "publisher",
    "purchase_order",
    "sales_order",
    "users",
    "book",
    "inventory",
    "purchase_detail",
    "sales_detail",
]


def split_sql(text):
    statements = []
    buf = []
    in_single = False
    dollar_tag = None
    procedure_mode = False

    def flush():
        sql = "".join(buf).strip()
        buf.clear()
        if sql:
            statements.append(sql)

    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if not buf and not stripped:
            continue
        if not buf and stripped.startswith("--"):
            continue
        if not buf and line.lstrip().upper().startswith("CREATE OR REPLACE PROCEDURE"):
            procedure_mode = True

        if procedure_mode:
            if stripped == "/":
                flush()
                procedure_mode = False
            else:
                buf.append(line)
            continue

        i = 0
        while i < len(line):
            ch = line[i]

            if dollar_tag:
                if line.startswith(dollar_tag, i):
                    buf.append(dollar_tag)
                    i += len(dollar_tag)
                    dollar_tag = None
                    continue
                buf.append(ch)
                i += 1
                continue

            if not in_single and ch == "$":
                match = re.match(r"\$[A-Za-z_]*\$", line[i:])
                if match:
                    dollar_tag = match.group(0)
                    buf.append(dollar_tag)
                    i += len(dollar_tag)
                    continue

            if ch == "'":
                buf.append(ch)
                if in_single and i + 1 < len(line) and line[i + 1] == "'":
                    buf.append("'")
                    i += 2
                    continue
                in_single = not in_single
                i += 1
                continue

            if ch == ";" and not in_single:
                flush()
                i += 1
                if not line[i:].strip():
                    break
                continue

            buf.append(ch)
            i += 1

    flush()
    return statements


def execute_file(conn, path):
    text = path.read_text(encoding="utf-8")
    statements = split_sql(text)
    with conn.cursor() as cur:
        for idx, statement in enumerate(statements, start=1):
            try:
                cur.execute(statement)
            except Exception as exc:
                raise RuntimeError(f"{path.name} statement {idx} failed:\n{statement[:800]}") from exc
    conn.commit()
    return len(statements)


def main():
    parser = argparse.ArgumentParser(description="Restore BookstoreManagementSystem SQL export to a target GaussDB.")
    parser.add_argument("--config", default=str(Path(__file__).with_name("target_config.json")))
    parser.add_argument("--yes", action="store_true", help="Confirm destructive restore into the target database.")
    args = parser.parse_args()

    if not args.yes:
        raise SystemExit("Refusing to restore without --yes because this drops same-name project objects.")

    base = Path(__file__).resolve().parent
    config_path = Path(args.config)
    config = json.loads(config_path.read_text(encoding="utf-8"))

    scripts = [
        base / "01_schema.sql",
        base / "02_data.sql",
        base / "03_routines_views_triggers.sql",
        base / "04_acceptance_optimization.sql",
    ]

    with psycopg2.connect(**config) as conn:
        for script in scripts:
            count = execute_file(conn, script)
            print(f"OK {script.name}: {count} statements")

        with conn.cursor() as cur:
            print("ROW COUNTS")
            for table in PROJECT_TABLES:
                cur.execute(f'SELECT count(*) FROM public."{table}"')
                print(f"{table}: {cur.fetchone()[0]}")


if __name__ == "__main__":
    main()
