"""Interfaz de escritorio por lotes para TE263 Color Corrector."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from .calibrator import DEFAULT_ADOBE_RGB_PROFILE, iter_images, process_one


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Corrección Color TE263")
        self.geometry("1050x760")
        self.minsize(900, 650)

        self.language = tk.StringVar(value="Español")
        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.debug_var = tk.StringVar()
        self.error_var = tk.StringVar()
        self.icc_var = tk.StringVar(value=str(DEFAULT_ADOBE_RGB_PROFILE))
        self.mode_var = tk.StringVar(value="hybrid")
        self.strength_var = tk.StringVar(value="1.0")
        self.manual_var = tk.BooleanVar(value=False)
        self.aggressive_var = tk.BooleanVar(value=False)
        self.debug_enabled_var = tk.BooleanVar(value=True)
        self.continue_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="Listo")
        self.events: queue.Queue[tuple[str, str]] = queue.Queue()
        self.stop_event = threading.Event()
        self.running = False
        self.preview_photo: ImageTk.PhotoImage | None = None

        self._build_ui()
        self.after(100, self._drain_events)

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(4, weight=1)

        self._language_bar(root)
        self._paths_section(root)
        self._execution_section(root)
        self._options_section(root)
        self._log_section(root)
        self._buttons(root)

    def _language_bar(self, root: ttk.Frame) -> None:
        bar = ttk.Frame(root)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(bar, text="Sprache / Idioma").pack(side="left", padx=(0, 12))
        ttk.Radiobutton(bar, text="Español", variable=self.language, value="Español").pack(side="left", padx=5)
        ttk.Radiobutton(bar, text="Deutsch", variable=self.language, value="Deutsch").pack(side="left", padx=5)
        ttk.Label(bar, textvariable=self.status_var).pack(side="right")

    def _paths_section(self, root: ttk.Frame) -> None:
        frame = ttk.LabelFrame(root, text="Rutas / Pfade", padding=8)
        frame.grid(row=1, column=0, sticky="ew", pady=4)
        frame.columnconfigure(1, weight=1)
        self._path_row(frame, 0, "Fuente / Quelle", self.input_var, self._choose_input)
        self._path_row(frame, 1, "Destino TIFF / Ziel TIFF", self.output_var, self._choose_output)
        self._path_row(frame, 2, "JPG y CSV secundarios", self.debug_var, self._choose_debug)
        self._path_row(frame, 3, "Errores / Fehler", self.error_var, self._choose_error)
        self._path_row(frame, 4, "Perfil ICC", self.icc_var, self._choose_icc)

    def _path_row(self, parent: ttk.Frame, row: int, label: str, variable: tk.StringVar, command) -> None:
        ttk.Label(parent, text=label, width=23).grid(row=row, column=0, sticky="w", pady=3)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=8, pady=3)
        ttk.Button(parent, text="Auswählen / Elegir", command=command).grid(row=row, column=2, pady=3)

    def _execution_section(self, root: ttk.Frame) -> None:
        frame = ttk.LabelFrame(root, text="Ejecución / Ausführung", padding=8)
        frame.grid(row=2, column=0, sticky="ew", pady=4)
        batch_mode = tk.StringVar(value="batch")
        ttk.Radiobutton(frame, text="Una imagen", value="single", variable=batch_mode, state="disabled").pack(side="left", padx=(0, 15))
        ttk.Radiobutton(frame, text="Carpeta completa", value="batch", variable=batch_mode, state="disabled").pack(side="left", padx=(0, 22))
        ttk.Label(frame, text="Modo color").pack(side="left")
        ttk.Combobox(frame, textvariable=self.mode_var, values=("hybrid", "matrix", "neutral"), state="readonly", width=12).pack(side="left", padx=8)
        ttk.Label(frame, text="Intensidad").pack(side="left")
        ttk.Entry(frame, textvariable=self.strength_var, width=7).pack(side="left", padx=8)

    def _options_section(self, root: ttk.Frame) -> None:
        frame = ttk.LabelFrame(root, text="Opciones / Optionen", padding=8)
        frame.grid(row=3, column=0, sticky="ew", pady=4)
        ttk.Checkbutton(frame, text="Selección manual de carta con ratón", variable=self.manual_var).grid(row=0, column=0, sticky="w", padx=(0, 20), pady=2)
        ttk.Checkbutton(frame, text="Detección agresiva", variable=self.aggressive_var).grid(row=0, column=1, sticky="w", padx=(0, 20), pady=2)
        ttk.Checkbutton(frame, text="Generar JPG/CSV de control", variable=self.debug_enabled_var).grid(row=0, column=2, sticky="w", pady=2)
        ttk.Checkbutton(frame, text="Continuar si falla una imagen", variable=self.continue_var).grid(row=1, column=0, sticky="w", padx=(0, 20), pady=2)

    def _log_section(self, root: ttk.Frame) -> None:
        frame = ttk.LabelFrame(root, text="Protocolo / Protokoll", padding=8)
        frame.grid(row=4, column=0, sticky="nsew", pady=4)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        self.log = tk.Text(frame, state="disabled", wrap="none", font=("Consolas", 10))
        self.log.grid(row=0, column=0, sticky="nsew")
        scroll_y = ttk.Scrollbar(frame, orient="vertical", command=self.log.yview)
        scroll_y.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scroll_y.set)

        preview = ttk.LabelFrame(frame, text="Miniatura", padding=6)
        preview.grid(row=0, column=2, sticky="ns", padx=(10, 0))
        self.preview_label = ttk.Label(preview, text="Sin imagen", anchor="center", width=28)
        self.preview_label.pack(fill="both", expand=True)
        self.preview_name = ttk.Label(preview, text="", anchor="center", width=32)
        self.preview_name.pack(pady=(6, 0))

    def _buttons(self, root: ttk.Frame) -> None:
        bar = ttk.Frame(root)
        bar.grid(row=5, column=0, sticky="ew", pady=(8, 0))
        self.start_button = ttk.Button(bar, text="Starten / Iniciar", command=self._start)
        self.start_button.pack(side="left", padx=(0, 8))
        self.stop_button = ttk.Button(bar, text="Stoppen / Detener", command=self._stop, state="disabled")
        self.stop_button.pack(side="left", padx=8)
        ttk.Button(bar, text="Ziel öffnen / Abrir destino", command=self._open_output).pack(side="left", padx=8)
        ttk.Button(bar, text="Fehler öffnen / Abrir errores", command=self._open_error).pack(side="left", padx=8)

    def _choose_input(self) -> None:
        path = filedialog.askdirectory(title="Seleccionar carpeta de imágenes")
        if path:
            self.input_var.set(path)
            self.output_var.set(str(Path(path).parent / (Path(path).name + "_CORREGIDAS")))
            self.debug_var.set(str(Path(path).parent / (Path(path).name + "_DEBUG")))
            self._preview_first(Path(path))

    def _choose_output(self) -> None:
        path = filedialog.askdirectory(title="Seleccionar carpeta TIFF de salida")
        if path:
            self.output_var.set(path)

    def _choose_debug(self) -> None:
        path = filedialog.askdirectory(title="Seleccionar carpeta JPG/CSV")
        if path:
            self.debug_var.set(path)

    def _choose_error(self) -> None:
        path = filedialog.askdirectory(title="Seleccionar carpeta de errores")
        if path:
            self.error_var.set(path)

    def _choose_icc(self) -> None:
        path = filedialog.askopenfilename(title="Seleccionar perfil ICC", filetypes=[("ICC", "*.icc *.icm"), ("Todos", "*.*")])
        if path:
            self.icc_var.set(path)

    def _preview_first(self, folder: Path) -> None:
        images = list(iter_images(folder, recursive=True))
        if not images:
            return
        try:
            image = Image.open(images[0]).convert("RGB")
            image.thumbnail((230, 260))
            self.preview_photo = ImageTk.PhotoImage(image)
            self.preview_label.configure(image=self.preview_photo, text="")
            self.preview_name.configure(text=images[0].name)
        except Exception as exc:
            self._append_log(f"AVISO miniatura: {exc}")

    def _append_log(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", message + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _start(self) -> None:
        if self.running:
            return
        input_path = Path(self.input_var.get().strip())
        output_text = self.output_var.get().strip()
        if not input_path.exists() or not output_text:
            messagebox.showerror("Entrada", "Selecciona una entrada y una carpeta de destino validas.")
            return
        try:
            strength = max(0.0, min(1.0, float(self.strength_var.get().replace(",", "."))))
        except ValueError:
            messagebox.showerror("Intensidad", "La intensidad debe ser un numero entre 0 y 1.")
            return

        self.running = True
        self.stop_event.clear()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.status_var.set("Verarbeitung läuft... / Procesando...")
        threading.Thread(target=self._worker, args=(input_path, Path(output_text), strength), daemon=True).start()

    def _stop(self) -> None:
        if self.running:
            self.stop_event.set()
            self.status_var.set("Deteniendo...")

    def _worker(self, input_path: Path, output_path: Path, strength: float) -> None:
        try:
            debug_dir = Path(self.debug_var.get().strip()) if self.debug_enabled_var.get() and self.debug_var.get().strip() else None
            icc = Path(self.icc_var.get().strip()) if self.icc_var.get().strip() else None
            images = list(iter_images(input_path, recursive=True)) if input_path.is_dir() else [input_path]
            if not images:
                raise RuntimeError("No se encontraron imagenes compatibles.")
            ok = 0
            errors = 0
            for image_path in images:
                if self.stop_event.is_set():
                    self.events.put(("done", f"Detenido. Procesadas: {ok}/{len(images)}."))
                    return
                relative = image_path.relative_to(input_path) if input_path.is_dir() else Path(image_path.name)
                destination = output_path / relative.with_suffix(".tif") if input_path.is_dir() else output_path
                image_debug = debug_dir / relative.parent if debug_dir and input_path.is_dir() else debug_dir
                try:
                    process_one(
                        image_path,
                        destination,
                        self.mode_var.get(),
                        strength,
                        self.debug_enabled_var.get(),
                        debug_dir=image_debug,
                        icc_profile_path=icc,
                        aggressive_detection=self.aggressive_var.get(),
                        manual_chart=self.manual_var.get(),
                    )
                    ok += 1
                    self.events.put(("log", f"OK | {image_path.name}"))
                except Exception as exc:
                    errors += 1
                    self.events.put(("log", f"ERROR | {image_path.name} | {exc}"))
                    if not self.continue_var.get():
                        raise
            self.events.put(("done", f"Finalizado. OK: {ok}/{len(images)}. Errores: {errors}."))
        except Exception as exc:
            self.events.put(("failed", str(exc)))

    def _open_output(self) -> None:
        path = Path(self.output_var.get().strip())
        if path.exists():
            import os
            os.startfile(str(path))

    def _open_error(self) -> None:
        path = Path(self.error_var.get().strip())
        if path.exists():
            import os
            os.startfile(str(path))

    def _drain_events(self) -> None:
        try:
            while True:
                kind, message = self.events.get_nowait()
                if kind == "log":
                    self._append_log(message)
                elif kind == "done":
                    self._append_log(message)
                    self.status_var.set(message)
                    self.running = False
                    self.start_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")
                elif kind == "failed":
                    self._append_log("ERROR | " + message)
                    self.status_var.set("Error")
                    self.running = False
                    self.start_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")
                    messagebox.showerror("Procesamiento", message)
        except queue.Empty:
            pass
        self.after(100, self._drain_events)


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()
