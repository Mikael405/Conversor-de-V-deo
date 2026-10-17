#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Conversor de Vídeo para Áudio
-----------------------------
Converte MP4, MKV, AVI, MOV, WEBM e outros vídeos para MP3, M4A, WAV, FLAC, OGG ou OPUS.

- Vários arquivos de uma vez (fila), arrastar e soltar (se tkinterdnd2 estiver instalado)
- Barra de progresso por arquivo e geral, botão cancelar
- Nunca sobrescreve arquivos existentes (cria "nome (1).mp3")
- O FFmpeg é encontrado/instalado automaticamente (imageio-ffmpeg), não precisa instalar nada à mão
"""
import os
import re
import sys
import queue
import shutil
import threading
import subprocess
from collections import deque

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    HAS_DND = True
except Exception:
    HAS_DND = False

IS_WIN = os.name == "nt"
NO_WINDOW = subprocess.CREATE_NO_WINDOW if IS_WIN else 0

MEDIA_EXTS = {
    ".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv", ".m4v", ".mpg",
    ".mpeg", ".3gp", ".ts", ".mts", ".m2ts", ".ogv", ".vob", ".asf", ".divx",
    ".mp3", ".m4a", ".wav", ".flac", ".ogg", ".opus", ".aac", ".wma",
}

# nome -> (extensão, argumentos do codec, usa bitrate?)
FORMATS = {
    "MP3": ("mp3", ["-c:a", "libmp3lame"], True),
    "M4A (AAC)": ("m4a", ["-c:a", "aac"], True),
    "WAV (sem perda)": ("wav", ["-c:a", "pcm_s16le"], False),
    "FLAC (sem perda)": ("flac", ["-c:a", "flac"], False),
    "OGG (Vorbis)": ("ogg", ["-c:a", "libvorbis"], True),
    "OPUS": ("opus", ["-c:a", "libopus"], True),
}
BITRATES = ["96", "128", "160", "192", "256", "320"]

PROGRESS_KEYS = {
    "frame", "fps", "stream_0_0_q", "bitrate", "total_size", "out_time_us",
    "out_time_ms", "out_time", "dup_frames", "drop_frames", "speed", "progress",
}


# --------------------------------------------------------------------------
# FFmpeg
# --------------------------------------------------------------------------
def pip_install(pkg):
    if getattr(sys, "frozen", False):  # dentro de um .exe não dá para usar pip
        return False
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet", pkg],
            creationflags=NO_WINDOW,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300,
        )
        return True
    except Exception:
        return False


def find_ffmpeg():
    name = "ffmpeg.exe" if IS_WIN else "ffmpeg"
    folders = []
    if getattr(sys, "_MEIPASS", None):
        folders.append(sys._MEIPASS)
    folders.append(os.path.dirname(os.path.abspath(sys.argv[0])))
    for f in folders:
        p = os.path.join(f, name)
        if os.path.isfile(p):
            return p
    p = shutil.which("ffmpeg")
    if p:
        return p
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    if pip_install("imageio-ffmpeg"):
        try:
            import importlib
            importlib.invalidate_caches()
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            pass
    return None


def probe_duration(ffmpeg, path):
    """Duração em segundos (ou None se não der para saber)."""
    try:
        r = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", path],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            creationflags=NO_WINDOW, timeout=60, stdin=subprocess.DEVNULL,
        )
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr)
        if m:
            h, mi, s = m.groups()
            return int(h) * 3600 + int(mi) * 60 + float(s)
    except Exception:
        pass
    return None


def unique_path(folder, base, ext):
    p = os.path.join(folder, f"{base}.{ext}")
    i = 1
    while os.path.exists(p):
        p = os.path.join(folder, f"{base} ({i}).{ext}")
        i += 1
    return p


def friendly_error(tail):
    text = " ".join(tail).lower()
    if "matches no streams" in text or "does not contain any stream" in text:
        return "Este arquivo não tem faixa de áudio"
    if "invalid data found" in text or "moov atom not found" in text:
        return "Arquivo corrompido ou incompleto"
    if "no such file" in text:
        return "Arquivo não encontrado"
    if "permission denied" in text:
        return "Sem permissão para gravar na pasta de saída"
    if "no space left" in text:
        return "Sem espaço em disco"
    if "unknown encoder" in text or "encoder" in text and "not found" in text:
        return "Este FFmpeg não suporta o formato escolhido"
    last = tail[-1] if tail else "erro desconhecido"
    return last[:80]


# --------------------------------------------------------------------------
# Motor de conversão (independente da interface)
# --------------------------------------------------------------------------
class Engine:
    def __init__(self, ffmpeg, emit):
        self.ffmpeg = ffmpeg
        self.emit = emit  # emit(evento_tupla)
        self.cancel_event = threading.Event()
        self.proc = None

    def cancel(self):
        self.cancel_event.set()
        p = self.proc
        if p is not None and p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass

    def run(self, jobs, fmt_key, bitrate, outdir):
        ext, codec, uses_br = FORMATS[fmt_key]
        total = len(jobs)
        ok = err = canc = 0
        for n, (iid, path) in enumerate(jobs):
            if self.cancel_event.is_set():
                canc += 1
                self.emit(("status", iid, "Cancelado"))
                continue
            folder = outdir or os.path.dirname(path)
            try:
                os.makedirs(folder, exist_ok=True)
            except Exception:
                err += 1
                self.emit(("status", iid, "Erro: não foi possível criar a pasta de saída"))
                continue
            base = os.path.splitext(os.path.basename(path))[0]
            out = unique_path(folder, base, ext)

            cmd = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                   "-i", path, "-map", "0:a:0", "-vn", *codec]
            if uses_br:
                cmd += ["-b:a", f"{bitrate}k"]
            if ext == "mp3":
                cmd += ["-id3v2_version", "3"]
            cmd += ["-progress", "pipe:1", "-nostats", out]

            self.emit(("status", iid, "Convertendo... 0%"))
            duration = probe_duration(self.ffmpeg, path)
            result = self._run_one(cmd, out, duration, iid, n, total)
            if result == "ok":
                ok += 1
                self.emit(("status", iid, "Concluído"))
                self.emit(("outdir", folder))
            elif result == "cancel":
                canc += 1
                self.emit(("status", iid, "Cancelado"))
            else:
                err += 1
                self.emit(("status", iid, "Erro: " + result))
            self.emit(("overall", (n + 1) / total * 100))
        self.emit(("finished", ok, err, canc))

    def _run_one(self, cmd, out, duration, iid, n, total):
        tail = deque(maxlen=12)
        last_pct = -1
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, text=True, encoding="utf-8",
                errors="replace", creationflags=NO_WINDOW,
            )
        except Exception as e:
            return f"não foi possível iniciar o FFmpeg ({e})"
        self.proc = proc
        try:
            for line in proc.stdout:
                if self.cancel_event.is_set():
                    proc.terminate()
                    break
                line = line.strip()
                if not line:
                    continue
                if line.startswith("out_time=") and duration:
                    m = re.match(r"out_time=(-?)(\d+):(\d+):(\d+(?:\.\d+)?)", line)
                    if m and not m.group(1):
                        secs = int(m.group(2)) * 3600 + int(m.group(3)) * 60 + float(m.group(4))
                        pct = max(0, min(99, int(secs / duration * 100)))
                        if pct != last_pct:
                            last_pct = pct
                            self.emit(("status", iid, f"Convertendo... {pct}%"))
                            self.emit(("overall", (n + pct / 100) / total * 100))
                    continue
                key = line.split("=", 1)[0]
                if "=" in line and key in PROGRESS_KEYS:
                    continue
                tail.append(line)
            proc.wait()
        finally:
            self.proc = None

        if self.cancel_event.is_set():
            self._remove(out)
            return "cancel"
        if proc.returncode == 0 and os.path.isfile(out) and os.path.getsize(out) > 0:
            return "ok"
        self._remove(out)
        return friendly_error(list(tail))

    @staticmethod
    def _remove(path):
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass


# --------------------------------------------------------------------------
# Interface
# --------------------------------------------------------------------------
class App:
    def __init__(self, root):
        self.root = root
        root.title("Conversor de Vídeo para Áudio")
        root.geometry("800x600")
        root.minsize(700, 520)

        self.q = queue.Queue()
        self.ffmpeg = None
        self.engine = None
        self.running = False
        self.paths = set()
        self.item_path = {}
        self.last_dir = None
        self.lockables = []

        self.build_ui()
        self.set_running(False)

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        threading.Thread(target=self._load_ffmpeg, daemon=True).start()
        root.after(100, self.poll)

    # ---------- construção da tela ----------
    def build_ui(self):
        style = ttk.Style()
        try:
            style.theme_use("vista" if IS_WIN else "clam")
        except tk.TclError:
            pass

        main = ttk.Frame(self.root, padding=12)
        main.pack(fill="both", expand=True)

        bar = ttk.Frame(main)
        bar.pack(fill="x")
        self.btn_add = ttk.Button(bar, text="Adicionar vídeos...", command=self.add_files)
        self.btn_folder = ttk.Button(bar, text="Adicionar pasta...", command=self.add_folder)
        self.btn_remove = ttk.Button(bar, text="Remover selecionados", command=self.remove_selected)
        self.btn_clear = ttk.Button(bar, text="Limpar lista", command=self.clear_list)
        for b in (self.btn_add, self.btn_folder, self.btn_remove, self.btn_clear):
            b.pack(side="left", padx=(0, 6))
            self.lockables.append(b)

        frame = ttk.Frame(main)
        frame.pack(fill="both", expand=True, pady=(10, 4))
        self.tree = ttk.Treeview(frame, columns=("arquivo", "status"), show="headings",
                                 selectmode="extended")
        self.tree.heading("arquivo", text="Arquivo")
        self.tree.heading("status", text="Status")
        self.tree.column("arquivo", width=470, anchor="w")
        self.tree.column("status", width=230, anchor="w", stretch=False)
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        hint = "Dica: arraste e solte os vídeos (ou pastas) aqui na lista." if HAS_DND else \
               "Dica: instale 'tkinterdnd2' (pip install tkinterdnd2) para poder arrastar e soltar arquivos."
        ttk.Label(main, text=hint, foreground="#666").pack(anchor="w")

        opt = ttk.LabelFrame(main, text="Configurações", padding=10)
        opt.pack(fill="x", pady=10)

        ttk.Label(opt, text="Formato de saída:").grid(row=0, column=0, sticky="w")
        self.var_fmt = tk.StringVar(value="MP3")
        self.cb_fmt = ttk.Combobox(opt, textvariable=self.var_fmt, values=list(FORMATS),
                                   state="readonly", width=18)
        self.cb_fmt.grid(row=0, column=1, sticky="w", padx=(6, 24))
        self.cb_fmt.bind("<<ComboboxSelected>>", lambda e: self.update_quality_state())

        ttk.Label(opt, text="Qualidade (kbps):").grid(row=0, column=2, sticky="w")
        self.var_br = tk.StringVar(value="192")
        self.cb_br = ttk.Combobox(opt, textvariable=self.var_br, values=BITRATES,
                                  state="readonly", width=8)
        self.cb_br.grid(row=0, column=3, sticky="w", padx=6)

        ttk.Label(opt, text="Salvar em:").grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.var_mode = tk.StringVar(value="same")
        r1 = ttk.Radiobutton(opt, text="Mesma pasta de cada vídeo", variable=self.var_mode,
                             value="same")
        r1.grid(row=1, column=1, columnspan=3, sticky="w", padx=6, pady=(10, 0))
        r2 = ttk.Radiobutton(opt, text="Outra pasta:", variable=self.var_mode, value="custom")
        r2.grid(row=2, column=1, sticky="w", padx=6)
        self.var_out = tk.StringVar()
        ttk.Entry(opt, textvariable=self.var_out, state="readonly").grid(
            row=2, column=2, columnspan=2, sticky="ew", padx=6)
        self.btn_browse = ttk.Button(opt, text="Procurar...", command=self.choose_outdir)
        self.btn_browse.grid(row=2, column=4, padx=(0, 0))
        opt.columnconfigure(3, weight=1)
        self.lockables += [r1, r2, self.btn_browse]

        self.progress = ttk.Progressbar(main, maximum=100)
        self.progress.pack(fill="x")
        self.lbl_status = ttk.Label(main, text="Preparando o FFmpeg...")
        self.lbl_status.pack(anchor="w", pady=(4, 8))

        btns = ttk.Frame(main)
        btns.pack(fill="x")
        self.btn_start = ttk.Button(btns, text="Converter", command=self.start)
        self.btn_cancel = ttk.Button(btns, text="Cancelar", command=self.cancel)
        self.btn_open = ttk.Button(btns, text="Abrir pasta de saída", command=self.open_output)
        self.btn_start.pack(side="left", padx=(0, 6))
        self.btn_cancel.pack(side="left", padx=(0, 6))
        self.btn_open.pack(side="right")

        if HAS_DND:
            for w in (self.root, self.tree):
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", self.on_drop)

    # ---------- estado ----------
    def set_running(self, flag):
        self.running = flag
        st = "disabled" if flag else "normal"
        for w in self.lockables:
            w.configure(state=st)
        self.cb_fmt.configure(state="disabled" if flag else "readonly")
        self.btn_start.configure(state="normal" if (not flag and self.ffmpeg) else "disabled")
        self.btn_cancel.configure(state="normal" if flag else "disabled")
        self.update_quality_state()

    def update_quality_state(self):
        uses_br = FORMATS[self.var_fmt.get()][2]
        self.cb_br.configure(state="readonly" if (uses_br and not self.running) else "disabled")

    # ---------- lista de arquivos ----------
    def add_paths(self, paths):
        added = 0
        for p in paths:
            p = os.path.abspath(p)
            if os.path.isdir(p):
                for dirpath, _dirs, files in os.walk(p):
                    for f in sorted(files):
                        if os.path.splitext(f)[1].lower() in MEDIA_EXTS:
                            added += self._add_one(os.path.join(dirpath, f))
            elif os.path.isfile(p):
                added += self._add_one(p)
        if added:
            self.lbl_status.configure(text=f"{len(self.paths)} arquivo(s) na lista.")

    def _add_one(self, path):
        if path in self.paths:
            return 0
        self.paths.add(path)
        iid = self.tree.insert("", "end", values=(os.path.basename(path), "Aguardando"))
        self.item_path[iid] = path
        return 1

    def add_files(self):
        exts = " ".join("*" + e for e in sorted(MEDIA_EXTS))
        files = filedialog.askopenfilenames(
            title="Escolha os vídeos",
            filetypes=[("Vídeos e áudios", exts), ("Todos os arquivos", "*.*")])
        if files:
            self.add_paths(files)

    def add_folder(self):
        d = filedialog.askdirectory(title="Escolha uma pasta com vídeos")
        if d:
            self.add_paths([d])

    def remove_selected(self):
        for iid in self.tree.selection():
            self.paths.discard(self.item_path.pop(iid, None))
            self.tree.delete(iid)

    def clear_list(self):
        self.tree.delete(*self.tree.get_children())
        self.paths.clear()
        self.item_path.clear()
        self.progress["value"] = 0
        self.lbl_status.configure(text="Lista vazia.")

    def on_drop(self, event):
        if not self.running:
            self.add_paths(self.root.tk.splitlist(event.data))

    def choose_outdir(self):
        d = filedialog.askdirectory(title="Escolha a pasta de saída")
        if d:
            self.var_out.set(d)
            self.var_mode.set("custom")

    # ---------- ações ----------
    def start(self):
        if not self.ffmpeg or self.running:
            return
        if not self.item_path:
            messagebox.showwarning("Lista vazia", "Adicione pelo menos um vídeo para converter.")
            return
        outdir = None
        if self.var_mode.get() == "custom":
            outdir = self.var_out.get().strip()
            if not outdir:
                self.choose_outdir()
                outdir = self.var_out.get().strip()
                if not outdir:
                    return
        jobs = [(iid, self.item_path[iid]) for iid in self.tree.get_children()]
        for iid, _ in jobs:
            self.tree.set(iid, "status", "Na fila")
        self.progress["value"] = 0
        self.lbl_status.configure(text="Convertendo...")
        self.last_dir = None
        self.engine = Engine(self.ffmpeg, self.q.put)
        self.set_running(True)
        threading.Thread(
            target=self.engine.run,
            args=(jobs, self.var_fmt.get(), self.var_br.get(), outdir),
            daemon=True).start()

    def cancel(self):
        if self.running and self.engine:
            self.lbl_status.configure(text="Cancelando...")
            self.engine.cancel()

    def open_output(self):
        folder = self.last_dir
        if not folder:
            if self.var_mode.get() == "custom" and self.var_out.get():
                folder = self.var_out.get()
            elif self.paths:
                folder = os.path.dirname(sorted(self.paths)[0])
        if not folder or not os.path.isdir(folder):
            messagebox.showinfo("Pasta de saída", "Ainda não há nenhuma pasta de saída.")
            return
        try:
            if IS_WIN:
                os.startfile(folder)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception as e:
            messagebox.showerror("Erro", f"Não foi possível abrir a pasta:\n{e}")

    def on_close(self):
        if self.running:
            if not messagebox.askyesno("Sair", "Há uma conversão em andamento. Cancelar e sair?"):
                return
            if self.engine:
                self.engine.cancel()
        self.root.destroy()

    # ---------- threads ----------
    def _load_ffmpeg(self):
        self.q.put(("ffmpeg", find_ffmpeg()))

    def poll(self):
        try:
            while True:
                ev = self.q.get_nowait()
                kind = ev[0]
                if kind == "ffmpeg":
                    self.ffmpeg = ev[1]
                    if self.ffmpeg:
                        self.lbl_status.configure(text="Pronto. Adicione vídeos e clique em Converter.")
                    else:
                        self.lbl_status.configure(text="FFmpeg não encontrado.")
                        messagebox.showerror(
                            "FFmpeg não encontrado",
                            "Não consegui obter o FFmpeg automaticamente.\n\n"
                            "Conecte-se à internet e abra o programa de novo, ou rode:\n"
                            "    pip install imageio-ffmpeg\n\n"
                            "Também funciona colocar o ffmpeg.exe na mesma pasta deste programa.")
                    self.set_running(self.running)
                elif kind == "status":
                    if self.tree.exists(ev[1]):
                        self.tree.set(ev[1], "status", ev[2])
                elif kind == "overall":
                    self.progress["value"] = ev[1]
                elif kind == "outdir":
                    self.last_dir = ev[1]
                elif kind == "finished":
                    _, ok, err, canc = ev
                    self.set_running(False)
                    parts = [f"{ok} convertido(s)"]
                    if err:
                        parts.append(f"{err} com erro")
                    if canc:
                        parts.append(f"{canc} cancelado(s)")
                    msg = ", ".join(parts) + "."
                    self.lbl_status.configure(text=msg)
                    if ok and not canc:
                        self.progress["value"] = 100
                    if canc:
                        messagebox.showinfo("Cancelado", msg)
                    elif err:
                        messagebox.showwarning("Concluído com erros", msg + "\nVeja o status de cada arquivo na lista.")
                    else:
                        messagebox.showinfo("Concluído", msg)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)


def main():
    if IS_WIN:
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    root = TkinterDnD.Tk() if HAS_DND else tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
