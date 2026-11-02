"""
АГР: подготовка данных для обучения — окно для тех, кто не хочет в терминал.

1. Выбрать IFC (файлы или папку) и классификатор.
2. «Обработать» → IFC читаются (повторно — из кэша), обновляется labels.xlsx:
   ваши прежние правки сохраняются, новые типы и расхождения с правилами — «проверить».
3. Поправить коды в Excel, сохранить.
4. «Проверить модель» → точность на новых типах и errors_model.csv.

Сборка exe — см. build_exe.bat.
"""
from __future__ import annotations

import contextlib
import io
import multiprocessing
import os
import queue
import subprocess
import sys
import threading
import traceback
from pathlib import Path

# модули программы ищем рядом с app.py, даже после смены рабочей папки
sys.path.insert(0, str(Path(__file__).resolve().parent))

# В exe без консоли sys.stdout = None, и любой print() падает. Направляем вывод в никуда.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")


# ---------- логика (без интерфейса, чтобы можно было вызывать и из кода) ----------

def run_pipeline(ifc_files, classifier, out_dir, log=print, workers=None):
    from ifc_to_dataset import extract_files, save_tables
    import build_labels

    out = Path(out_dir).resolve()
    workers = workers or max(1, min(4, (os.cpu_count() or 2) - 1))
    log(f"Читаю IFC: {len(ifc_files)} шт. (потоков: {workers})")
    df = extract_files([Path(f) for f in ifc_files], out / "cache", log=log, workers=workers)
    types_csv = save_tables(df, out / "выгрузка", log=log)
    labels = out / "labels.xlsx"
    log("\nОбновляю таблицу разметки…")
    with _capture(log):
        build_labels.main(str(types_csv), str(classifier), str(labels))

    # помещения и зоны — своя разметка
    spaces_csv = types_csv.parent / "spaces.csv"
    if spaces_csv.exists():
        import build_space_labels
        clf_sp = _find_space_classifier(classifier)
        if clf_sp is None:
            log("⚠ не найден Классификатор_Помещения_и_зоны_МССК.txt — положите его рядом с классификатором "
                "элементов; разметка помещений будет без наименований кодов")
        log("\nОбновляю разметку помещений…")
        with _capture(log):
            build_space_labels.main(str(spaces_csv), str(clf_sp or ""), str(out / "labels_spaces.xlsx"))
    return labels


def _find_space_classifier(elements_clf):
    name = "Классификатор_Помещения_и_зоны_МССК.txt"
    for d in (Path(elements_clf).parent, Path(__file__).resolve().parent, Path.cwd()):
        if (d / name).exists():
            return d / name
    return None


def run_check(labels, log=print):
    import train_model

    labels = Path(labels).resolve()
    folder = labels.parent
    cwd = os.getcwd()
    os.chdir(folder)  # errors_model.csv и model.joblib — рядом с labels.xlsx
    try:
        with _capture(log):
            train_model.main(str(labels))
        spaces = folder / "labels_spaces.xlsx"
        if spaces.exists():
            import train_spaces
            log("\n=== Помещения и зоны ===")
            with _capture(log):
                train_spaces.main(str(spaces))
    finally:
        os.chdir(cwd)
    return folder / "errors_model.csv"


def find_rules(folder) -> Path | None:
    """Таблица правил: в папке результата, рядом с программой (exe или app.py)."""
    places = [Path(folder)]
    if getattr(sys, "frozen", False):
        places.append(Path(sys.executable).resolve().parent)        # рядом с AtributyAGR_Trainer.exe
        places.append(Path(sys.executable).resolve().parent.parent.parent)   # папка 3_обучение
    places.append(Path(__file__).resolve().parent)
    for p in places:
        for name in ("Правила_АГР.xlsx", "rules.xlsx"):
            if (p / name).exists():
                return p / name
    return None


def run_compare(labels, split="types", rules=None, log=print):
    """Сравнение подходов: только правила / только модель / гибрид → compare_report.xlsx."""
    import compare_approaches
    labels = Path(labels).resolve()
    folder = labels.parent
    rules = Path(rules) if rules else find_rules(folder)
    if rules is None:
        raise FileNotFoundError("не найдена таблица правил Правила_АГР.xlsx — положите её в папку результата")
    log(f"Таблица правил: {rules}")
    spaces = folder / "labels_spaces.xlsx"
    with _capture(log):
        compare_approaches.main(str(rules), str(labels), str(spaces) if spaces.exists() else None,
                                split, out_dir=str(folder))
    return folder / "compare_report.xlsx"


def run_control(labels, ifc_files, rules=None, log=print, workers=None):
    """Проверка на контрольных IFC → control_report.xlsx (в разметку они не попадают)."""
    import compare_approaches
    labels = Path(labels).resolve()
    folder = labels.parent
    rules = Path(rules) if rules else find_rules(folder)
    if rules is None:
        raise FileNotFoundError("не найдена таблица правил Правила_АГР.xlsx — положите её в папку результата")
    spaces = folder / "labels_spaces.xlsx"
    workers = workers or max(1, min(4, (os.cpu_count() or 2) - 1))
    with _capture(log):
        return compare_approaches.control(str(rules), str(labels), list(ifc_files),
                                          str(spaces) if spaces.exists() else None, str(folder), log, workers)


def run_corrections(corrections_csv, labels, log=print):
    """Правки коллег с сервера (corrections.csv) → labels.xlsx и corrections_report.xlsx."""
    import merge_corrections
    with _capture(log):
        merge_corrections.main(str(corrections_csv), str(Path(labels).resolve()))


@contextlib.contextmanager
def _capture(log):
    """print() внутри скриптов → в окно журнала."""
    real = sys.stdout

    class W(io.TextIOBase):
        def write(self, s):
            for line in s.rstrip("\n").split("\n"):
                if line.strip():
                    with contextlib.redirect_stdout(real):  # если log — это print
                        log(line)
            return len(s)
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with contextlib.redirect_stdout(W()):
            yield


def open_file(path):
    path = str(path)
    if sys.platform.startswith("win"):
        os.startfile(path)  # noqa
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


# ---------- окно ----------

def gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title("АтрибутыАГР — обучение")
    root.geometry("820x600")
    root.minsize(640, 460)

    ifc_files: list[str] = []
    clf_var = tk.StringVar()
    out_var = tk.StringVar(value=str(Path.home() / "АГР_обучение"))
    logq: queue.Queue = queue.Queue()

    def log(msg):
        logq.put(str(msg))

    pad = {"padx": 10, "pady": 4}
    frm = ttk.Frame(root)
    frm.pack(fill="x", **pad)
    frm.columnconfigure(1, weight=1)

    # IFC
    ttk.Label(frm, text="IFC для обучения:").grid(row=0, column=0, sticky="w")
    ifc_lbl = ttk.Label(frm, text="не выбраны", foreground="#777")
    ifc_lbl.grid(row=0, column=1, sticky="w", padx=6)
    btns = ttk.Frame(frm)
    btns.grid(row=0, column=2, sticky="e")

    def set_files(files):
        ifc_files[:] = sorted(set(files))
        ifc_lbl.config(text=f"выбрано файлов: {len(ifc_files)}" if ifc_files else "не выбраны",
                       foreground="#000" if ifc_files else "#777")

    def pick_files():
        f = filedialog.askopenfilenames(title="Выберите IFC", filetypes=[("IFC", "*.ifc")])
        if f:
            set_files(list(f))

    def pick_folder():
        d = filedialog.askdirectory(title="Папка с IFC (включая вложенные)")
        if d:
            set_files([str(p) for p in Path(d).rglob("*.ifc")])

    ttk.Button(btns, text="Файлы…", command=pick_files).pack(side="left", padx=2)
    ttk.Button(btns, text="Папка…", command=pick_folder).pack(side="left", padx=2)

    # Классификатор
    ttk.Label(frm, text="Классификатор (.txt):").grid(row=1, column=0, sticky="w", pady=4)
    ttk.Entry(frm, textvariable=clf_var).grid(row=1, column=1, sticky="ew", padx=6)
    ttk.Button(frm, text="Выбрать…", command=lambda: clf_var.set(
        filedialog.askopenfilename(title="Классификатор МССК", filetypes=[("Текст", "*.txt")])
        or clf_var.get())).grid(row=1, column=2, sticky="e")

    # Папка результата
    ttk.Label(frm, text="Папка результата:").grid(row=2, column=0, sticky="w", pady=4)
    ttk.Entry(frm, textvariable=out_var).grid(row=2, column=1, sticky="ew", padx=6)
    ttk.Button(frm, text="Выбрать…", command=lambda: out_var.set(
        filedialog.askdirectory(title="Куда сохранить labels.xlsx") or out_var.get())
               ).grid(row=2, column=2, sticky="e")

    ttk.Label(root, foreground="#555", wraplength=780, justify="left",
              text="Если в папке результата уже есть labels.xlsx, ваши правки в нём сохранятся: "
                   "добавятся только новые типы, а расхождения с правилами будут помечены «проверить».").pack(
        fill="x", padx=10)

    # Кнопки действий
    act = ttk.Frame(root)
    act.pack(fill="x", padx=10, pady=8)
    b_run = ttk.Button(act, text="Обработать")
    b_open = ttk.Button(act, text="Открыть labels.xlsx", state="disabled")
    b_open_sp = ttk.Button(act, text="Открыть labels_spaces.xlsx", state="disabled")
    b_check = ttk.Button(act, text="Проверить модель", state="disabled")
    b_corr = ttk.Button(act, text="Правки коллег…", state="disabled")
    b_cmp = ttk.Button(act, text="Сравнить подходы", state="disabled")
    b_ctl = ttk.Button(act, text="Контрольные IFC…", state="disabled")
    b_folder = ttk.Button(act, text="Открыть папку")
    for b in (b_run, b_open, b_open_sp, b_check, b_cmp, b_ctl, b_corr, b_folder):
        b.pack(side="left", padx=4)
    bar = ttk.Progressbar(act, mode="indeterminate", length=160)
    bar.pack(side="right")

    # Журнал
    txt = tk.Text(root, wrap="word", font=("Consolas", 10), state="disabled", background="#FAFAFA")
    txt.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def labels_path():
        return Path(out_var.get()) / "labels.xlsx"

    def refresh_buttons():
        st = "normal" if labels_path().exists() else "disabled"
        b_open.config(state=st)
        b_check.config(state=st)
        b_corr.config(state=st)
        b_cmp.config(state=st)
        b_ctl.config(state=st)
        b_open_sp.config(state="normal" if (Path(out_var.get()) / "labels_spaces.xlsx").exists() else "disabled")

    def busy(on):
        for b in (b_run, b_check):
            b.config(state="disabled" if on else "normal")
        if on:
            bar.start(12)
        else:
            bar.stop()
        if not on:
            refresh_buttons()

    def in_thread(fn, done_msg):
        def work():
            try:
                fn()
                log(f"\n✔ {done_msg}")
            except Exception as e:
                log(f"\n✘ Ошибка: {e}")
                log(traceback.format_exc())
            finally:
                root.after(0, lambda: busy(False))
        busy(True)
        threading.Thread(target=work, daemon=True).start()

    def on_run():
        if not ifc_files:
            messagebox.showwarning("АГР", "Выберите IFC-файлы или папку.")
            return
        if not Path(clf_var.get()).is_file():
            messagebox.showwarning("АГР", "Укажите файл классификатора (.txt).")
            return
        txt.config(state="normal")
        txt.delete("1.0", "end")
        txt.config(state="disabled")
        in_thread(lambda: run_pipeline(ifc_files, clf_var.get(), out_var.get(), log),
                  f"Готово: {labels_path()} и labels_spaces.xlsx. Поправьте строки «проверить».")

    def on_check():
        in_thread(lambda: run_check(labels_path(), log),
                  "Проверка закончена. Ошибки — в errors_model.csv в папке результата.")

    def on_corr():
        f = filedialog.askopenfilename(title="corrections.csv с сервера (папка data)",
                                       filetypes=[("CSV", "*.csv")])
        if f:
            in_thread(lambda: run_corrections(f, labels_path(), log),
                      "Правки коллег добавлены в labels.xlsx (статус «проверить»), отчёт — corrections_report.xlsx.")

    b_corr.config(command=on_corr)

    def on_cmp():
        split = "projects" if messagebox.askyesno(
            "Сравнить подходы",
            "Как проверять?\n\nДа — по проектам (прятать целые IFC: «как будет на новом проекте»)\n"
            "Нет — по новым типам (прятать группы похожих имён)") else "types"
        rules = find_rules(Path(out_var.get()))
        if rules is None:
            rules = filedialog.askopenfilename(title="Где таблица правил (Правила_АГР.xlsx)?",
                                               filetypes=[("Excel", "*.xlsx")])
            if not rules:
                return
        in_thread(lambda: open_file(run_compare(labels_path(), split, rules, log)),
                  "Сравнение готово: compare_report.xlsx (сводка, пороги, категории, все строки).")

    b_cmp.config(command=on_cmp)

    def on_ctl():
        files = filedialog.askopenfilenames(
            title="Контрольные IFC — объекты, которых НЕТ в обучении (в разметку не попадут)",
            filetypes=[("IFC", "*.ifc")])
        if not files:
            return
        rules = find_rules(Path(out_var.get()))
        if rules is None:
            rules = filedialog.askopenfilename(title="Где таблица правил (Правила_АГР.xlsx)?",
                                               filetypes=[("Excel", "*.xlsx")])
            if not rules:
                return
        in_thread(lambda: open_file(run_control(labels_path(), files, rules, log)),
                  "Проверка на контрольных IFC готова: control_report.xlsx.")

    b_ctl.config(command=on_ctl)
    b_run.config(command=on_run)
    b_check.config(command=on_check)
    b_open.config(command=lambda: open_file(labels_path()))
    b_open_sp.config(command=lambda: open_file(Path(out_var.get()) / "labels_spaces.xlsx"))
    b_folder.config(command=lambda: (Path(out_var.get()).mkdir(parents=True, exist_ok=True),
                                     open_file(out_var.get())))
    out_var.trace_add("write", lambda *a: refresh_buttons())
    refresh_buttons()

    def pump():
        try:
            while True:
                msg = logq.get_nowait()
                txt.config(state="normal")
                txt.insert("end", msg + "\n")
                txt.see("end")
                txt.config(state="disabled")
        except queue.Empty:
            pass
        root.after(100, pump)

    pump()
    root.mainloop()


if __name__ == "__main__":
    multiprocessing.freeze_support()  # нужно для параллельного чтения IFC внутри exe
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":
        # без окна: app --cli классификатор.txt папка_результата файл1.ifc файл2.ifc …
        run_pipeline(sys.argv[4:], sys.argv[2], sys.argv[3])
    elif len(sys.argv) > 1 and sys.argv[1] == "--check":
        run_check(sys.argv[2])
    else:
        gui()
