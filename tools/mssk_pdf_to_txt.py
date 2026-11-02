"""
Классификатор МССК из PDF (exp.mos.ru, раздел «Классификаторы для информационного моделирования»)
→ текстовый файл в формате, который понимают АтрибутыАГР и программа обучения:
    код <TAB> наименование <TAB> уровень     (UTF-16)

Запуск:
    pip install pdfplumber pandas
    python tools/mssk_pdf_to_txt.py "05. Помещения и зоны.pdf" Классификатор_Помещения_и_зоны_МССК.txt
    python tools/mssk_pdf_to_txt.py "08. Строительные изделия и материалы.pdf" Классификатор_Материалы_МССК.txt --drop-last-column

--drop-last-column — для классификаторов с колонкой «Код ОКПД2» в конце таблицы (материалы).
"""
import re
import sys

import pandas as pd
import pdfplumber

CODE = re.compile(r"^[А-ЯA-Z]{2}( \d{2})+$")


def parse(path, drop_last_col=False) -> pd.DataFrame:
    rows = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for r in table:
                    code = re.sub(r"\s+", " ", (r[0] or "").replace("\n", " ")).strip()
                    code = code.replace("П3", "ПЗ")          # в PDF встречается цифра 3 вместо буквы З
                    if not CODE.match(code):
                        continue
                    cells = r[1:-1] if drop_last_col else r[1:]
                    name = next((re.sub(r"\s+", " ", c.replace("\n", " ")).strip()
                                 for c in cells if c and c.strip()), "")
                    rows.append((code, name, len(code.split()) - 1))
    return pd.DataFrame(rows, columns=["code", "name", "level"]).drop_duplicates("code")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 2:
        sys.exit(__doc__)
    d = parse(args[0], "--drop-last-column" in sys.argv)
    d.to_csv(args[1], sep="\t", header=False, index=False, encoding="utf-16")
    print(f"{args[1]}: {len(d)} кодов, без наименования: {(d.name == '').sum()}")
