import socket
import json
import time
import os
import threading
import uuid
import tkinter as tk
from tkinter import messagebox
from datetime import datetime

HOST        = '127.0.0.1'
PORT        = 5050
SCORES_FILE = "scores.json"
CLIENT_ID   = uuid.uuid4().hex

NUMBER_COLORS = {
    1: "#1565C0", 2: "#2E7D32", 3: "#C62828", 4: "#283593",
    5: "#6A1B9A", 6: "#00838F", 7: "#37474F", 8: "#9E9E9E",
}

LEVELS = [
    ("beginner",     "Principiante",  "8x8  ·  10 💣",    8,    8,  10),
    ("intermediate", "Intermedio",    "16x16  ·  40 💣",  16,  16,  40),
    ("expert",       "Experto",       "16x30  ·  99 💣",  16,  30,  99),
    ("custom",       "Personalizado", "",      None, None, None),
]

LEVEL_NAMES = {
    "beginner":     "Principiante",
    "intermediate": "Intermedio",
    "expert":       "Experto",
}


def send_msg(sock, data):
    msg = json.dumps(data).encode('utf-8')
    sock.sendall(len(msg).to_bytes(4, 'big') + msg)

def recv_msg(sock):
    raw_len = _recvall(sock, 4)
    if raw_len is None:
        return None
    length = int.from_bytes(raw_len, 'big')
    data   = _recvall(sock, length)
    if data is None:
        return None
    return json.loads(data.decode('utf-8'))

def _recvall(sock, n):
    buf = b''
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


class ScoreManager:

    @staticmethod
    def _empty_scores():
        return {"beginner": [], "intermediate": [], "expert": []}

    @staticmethod
    def _request(data):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.connect((HOST, PORT))
            send_msg(sock, data)
            return recv_msg(sock)
        finally:
            sock.close()

    @staticmethod
    def load():
        """Devuelve el diccionario completo de puntajes desde el archivo."""
        try:
            resp = ScoreManager._request({"type": "scores_get"})
            if resp and resp.get("type") == "scores_data":
                return resp["scores"]
        except Exception:
            pass

        if os.path.exists(SCORES_FILE):
            try:
                with open(SCORES_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return ScoreManager._empty_scores()

    @staticmethod
    def save_score(level_key, name, elapsed_secs):
        resp = ScoreManager._request({
            "type": "score_submit",
            "level": level_key,
            "name": name,
            "time": elapsed_secs,
            "client_id": CLIENT_ID,
        })
        if not resp or resp.get("type") != "score_saved":
            raise RuntimeError("No se pudo guardar el puntaje.")
        return resp

        """
        Agrega un puntaje al nivel correspondiente, ordena de menor a mayor
        tiempo y guarda solo el top 10.
        """
        data  = ScoreManager.load()
        entry = {
            "name": name.strip() or "Anónimo",
            "time": elapsed_secs,
            "date": datetime.now().strftime("%d/%m/%Y"),
        }
        data[level_key].append(entry)
        data[level_key].sort(key=lambda x: x["time"])
        data[level_key] = data[level_key][:10]
        with open(SCORES_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


class ScoreAlertListener:
    def __init__(self, root):
        self.root = root
        self.sock = None
        self.running = False
        self.closed = False
        self._start()

    def _start(self):
        if self.closed or self.running:
            return
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((HOST, PORT))
            send_msg(self.sock, {
                "type": "scores_subscribe",
                "client_id": CLIENT_ID,
            })
            self.running = True
            threading.Thread(target=self._listen, daemon=True).start()
        except Exception:
            self.sock = None
            self._retry_later()

    def _retry_later(self):
        if self.closed:
            return
        try:
            self.root.after(2000, self._start)
        except tk.TclError:
            self.closed = True

    def _listen(self):
        while self.running:
            try:
                msg = recv_msg(self.sock)
            except Exception:
                break
            if not msg:
                break
            if msg.get("type") == "scores_update" and msg.get("show_popup"):
                try:
                    self.root.after(0, lambda m=msg: self._show_popup(m))
                except tk.TclError:
                    break
        self.running = False
        if not self.closed:
            self._retry_later()

    def _show_popup(self, msg):
        if not self.root.winfo_exists():
            return

        new_score = msg.get("new_score", {})
        entry = new_score.get("entry", {})
        position = new_score.get("position")
        level = new_score.get("level")
        if not position:
            return

        popup = tk.Toplevel(self.root)
        popup.title("Nuevo top 5")
        popup.resizable(False, False)
        popup.configure(bg="#16213e")
        popup.attributes("-topmost", True)

        level_name = LEVEL_NAMES.get(level, "Ranking")
        tk.Label(
            popup,
            text="Nuevo puntaje destacado",
            font=("Segoe UI", 11, "bold"),
            bg="#16213e", fg="#FFD700"
        ).pack(padx=18, pady=(14, 4))
        tk.Label(
            popup,
            text=f"{entry.get('name', 'Jugador')} entro al puesto #{position} en {level_name}",
            font=("Segoe UI", 10),
            bg="#16213e", fg="white"
        ).pack(padx=18, pady=(0, 12))
        tk.Button(
            popup, text="Cerrar",
            font=("Segoe UI", 9, "bold"),
            bg="#e94560", fg="white",
            activebackground="#c73652", activeforeground="white",
            relief="flat", cursor="hand2",
            command=popup.destroy
        ).pack(pady=(0, 14))

        popup.update_idletasks()
        w = popup.winfo_reqwidth()
        h = popup.winfo_reqheight()
        sw = popup.winfo_screenwidth()
        popup.geometry(f"{w}x{h}+{sw - w - 28}+28")
        popup.after(10000, lambda: popup.destroy() if popup.winfo_exists() else None)

    def close(self):
        self.closed = True
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None


class BuscaminasClient:
    def __init__(self):
        self.sock = None

    def connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((HOST, PORT))

    def disconnect(self):
        if self.sock:
            self.sock.close()
            self.sock = None

    def init_game(self, rows, cols, mines):
        send_msg(self.sock, {
            "type": "init", "rows": rows, "cols": cols,
            "mines": mines, "safe_start": True
        })
        return recv_msg(self.sock)

    def click_cell(self, row, col):
        send_msg(self.sock, {"type": "click", "row": row, "col": col})
        return recv_msg(self.sock)

    def solve(self):
        send_msg(self.sock, {"type": "solve"})
        return recv_msg(self.sock)


class WinDialog:
    def __init__(self, parent, elapsed, level_key, on_save):
        self.on_save   = on_save
        self.elapsed   = elapsed
        self.level_key = level_key

        self.dialog = tk.Toplevel(parent)
        self.dialog.title("¡Victoria!")
        self.dialog.resizable(False, False)
        self.dialog.configure(bg="#1a1a2e")
        self.dialog.grab_set()
        self.dialog.focus_set()
        self.dialog.protocol("WM_DELETE_WINDOW", self._save)

        self._build_ui()
        self._center(parent)

    def _center(self, parent):
        self.dialog.update_idletasks()
        w  = max(self.dialog.winfo_reqwidth(), 300)
        h  = self.dialog.winfo_reqheight()
        px = parent.winfo_rootx() + parent.winfo_width()  // 2
        py = parent.winfo_rooty() + parent.winfo_height() // 2
        self.dialog.geometry(f"{w}x{h}+{px - w//2}+{py - h//2}")

    def _build_ui(self):
        m, s = divmod(self.elapsed, 60)

        tk.Label(self.dialog, text="🎉  ¡GANASTE!",
                 font=("Segoe UI", 20, "bold"),
                 bg="#1a1a2e", fg="#e94560").pack(pady=(24, 4))

        tk.Label(self.dialog,
                 text=f"{LEVEL_NAMES[self.level_key]}  ·  {m}:{s:02d}",
                 font=("Segoe UI", 12),
                 bg="#1a1a2e", fg="#a8b2d8").pack(pady=(0, 20))

        tk.Label(self.dialog, text="Ingresa tu nombre para el ranking:",
                 font=("Segoe UI", 10),
                 bg="#1a1a2e", fg="#a8b2d8").pack()

        self.entry = tk.Entry(
            self.dialog,
            font=("Segoe UI", 13), width=16,
            bg="#16213e", fg="white",
            insertbackground="white",
            relief="flat", justify="center"
        )
        self.entry.pack(pady=(8, 18), ipady=7)
        self.entry.focus_set()
        self.entry.bind("<Return>", lambda e: self._save())

        tk.Button(
            self.dialog, text="💾  Guardar",
            font=("Segoe UI", 11, "bold"),
            bg="#e94560", fg="white",
            activebackground="#c73652", activeforeground="white",
            relief="flat", cursor="hand2",
            padx=20, pady=8,
            command=self._save
        ).pack(pady=(0, 24))

    def _save(self):
        name = self.entry.get().strip() or "Anónimo"
        self.on_save(name)
        self.dialog.destroy()


class ScoreWindow:
    def __init__(self, parent, initial_level="beginner"):
        self.level_btns = {}
        self.current_level = initial_level
        self.scores = ScoreManager.load()
        self.score_sock = None
        self.listening = False

        self.window = tk.Toplevel(parent)
        self.window.title("Tabla de Puntajes")
        self.window.resizable(False, False)
        self.window.configure(bg="#1a1a2e")
        self.window.grab_set()
        self.window.protocol("WM_DELETE_WINDOW", self._close)

        self._build_ui()
        self._show_level(initial_level)
        self._start_score_listener()
        self._center()

    def _center(self):
        self.window.update_idletasks()
        w  = max(self.window.winfo_reqwidth(), 420)
        h  = self.window.winfo_reqheight()
        sw = self.window.winfo_screenwidth()
        sh = self.window.winfo_screenheight()
        self.window.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")


    def _build_ui(self):

        tk.Label(self.window, text="🏆  TABLA DE PUNTAJES",
                 font=("Segoe UI", 18, "bold"),
                 bg="#1a1a2e", fg="#e94560").pack(pady=(24, 16))

        tab_frame = tk.Frame(self.window, bg="#1a1a2e")
        tab_frame.pack(padx=20)
        for key, name in LEVEL_NAMES.items():
            btn = tk.Button(
                tab_frame, text=name,
                font=("Segoe UI", 10, "bold"),
                width=13, pady=6,
                bg="#0f3460", fg="#a8b2d8",
                activebackground="#1a4a80", activeforeground="white",
                relief="flat", cursor="hand2",
                command=lambda k=key: self._show_level(k)
            )
            btn.pack(side="left", padx=4)
            self.level_btns[key] = btn

        tk.Frame(self.window, bg="#2a2a4e", height=1).pack(
            fill="x", padx=20, pady=(14, 0))

        self.table_frame = tk.Frame(self.window, bg="#1a1a2e")
        self.table_frame.pack(padx=20, pady=12, fill="both")

        tk.Button(
            self.window, text="✕  Cerrar",
            font=("Segoe UI", 10, "bold"),
            bg="#0f3460", fg="white",
            activebackground="#1a4a80", activeforeground="white",
            relief="flat", cursor="hand2",
            padx=16, pady=6,
            command=self._close
        ).pack(pady=(0, 20))

    def _start_score_listener(self):
        try:
            self.score_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.score_sock.connect((HOST, PORT))
            send_msg(self.score_sock, {
                "type": "scores_subscribe",
                "client_id": CLIENT_ID,
            })
            self.listening = True
            threading.Thread(target=self._listen_scores, daemon=True).start()
        except Exception:
            self.score_sock = None

    def _listen_scores(self):
        while self.listening:
            try:
                msg = recv_msg(self.score_sock)
            except Exception:
                break
            if not msg:
                break
            try:
                self.window.after(0, lambda m=msg: self._handle_score_message(m))
            except tk.TclError:
                break
        self.listening = False

    def _handle_score_message(self, msg):
        if not self.window.winfo_exists():
            return
        if msg.get("type") not in ("scores_data", "scores_update"):
            return

        self.scores = msg.get("scores", ScoreManager._empty_scores())
        self._show_level(self.current_level)

    def _show_score_popup(self, name, position, level):
        if not position:
            return

        popup = tk.Toplevel(self.window)
        popup.title("Nuevo top 5")
        popup.resizable(False, False)
        popup.configure(bg="#16213e")
        popup.attributes("-topmost", True)

        level_name = LEVEL_NAMES.get(level, "Ranking")
        tk.Label(
            popup,
            text="Nuevo puntaje destacado",
            font=("Segoe UI", 11, "bold"),
            bg="#16213e", fg="#FFD700"
        ).pack(padx=18, pady=(14, 4))
        tk.Label(
            popup,
            text=f"{name} entro al puesto #{position} en {level_name}",
            font=("Segoe UI", 10),
            bg="#16213e", fg="white"
        ).pack(padx=18, pady=(0, 12))
        tk.Button(
            popup, text="Cerrar",
            font=("Segoe UI", 9, "bold"),
            bg="#e94560", fg="white",
            activebackground="#c73652", activeforeground="white",
            relief="flat", cursor="hand2",
            command=popup.destroy
        ).pack(pady=(0, 14))

        popup.update_idletasks()
        w = popup.winfo_reqwidth()
        h = popup.winfo_reqheight()
        x = self.window.winfo_rootx() + self.window.winfo_width() - w - 16
        y = self.window.winfo_rooty() + 16
        popup.geometry(f"{w}x{h}+{x}+{y}")
        popup.after(3000, lambda: popup.destroy() if popup.winfo_exists() else None)

    def _close(self):
        self.listening = False
        if self.score_sock:
            try:
                self.score_sock.close()
            except Exception:
                pass
            self.score_sock = None
        self.window.destroy()


    def _show_level(self, key):
        self.current_level = key
        for k, btn in self.level_btns.items():
            btn.config(
                bg="#e94560" if k == key else "#0f3460",
                fg="white"   if k == key else "#a8b2d8"
            )

        for w in self.table_frame.winfo_children():
            w.destroy()

        scores = self.scores.get(key, [])

        headers = ("#",  "Nombre",  "Tiempo", "Fecha")
        widths  = (4,    16,         8,        10)
        anchors = ("center", "w",   "center", "center")

        header_frame = tk.Frame(self.table_frame, bg="#16213e")
        header_frame.pack(fill="x", pady=(0, 6))
        for col, (h, w, a) in enumerate(zip(headers, widths, anchors)):
            tk.Label(
                header_frame, text=h,
                font=("Segoe UI", 9, "bold"),
                width=w, anchor=a,
                bg="#16213e", fg="#a8b2d8",
                padx=6, pady=5
            ).grid(row=0, column=col, padx=1)

        if not scores:
            tk.Label(
                self.table_frame,
                text="Aún no hay puntajes en este nivel.\n¡Sé el primero en registrarte!",
                font=("Segoe UI", 10),
                bg="#1a1a2e", fg="#a8b2d8",
                justify="center"
            ).pack(pady=28)
        else:
            for i, score in enumerate(scores):
                m, s  = divmod(score["time"], 60)
                row_bg = "#1e2a40" if i % 2 == 0 else "#16213e"
                medal  = ("🥇", "🥈", "🥉")[i] if i < 3 else f"  {i+1}."

                row = tk.Frame(self.table_frame, bg=row_bg)
                row.pack(fill="x", pady=1)

                vals = (medal, score["name"], f"{m}:{s:02d}", score["date"])
                for col, (val, w, a) in enumerate(zip(vals, widths, anchors)):
                    tk.Label(
                        row, text=val,
                        font=("Segoe UI", 11 if col != 0 else 13),
                        width=w, anchor=a,
                        bg=row_bg,
                        fg="#FFD700" if i == 0 else ("white" if col == 0 else "#e0e0e0"),
                        padx=6, pady=5
                    ).grid(row=0, column=col, padx=1)

        self.window.update_idletasks()
        w = max(self.window.winfo_reqwidth(), 420)
        h = self.window.winfo_reqheight()
        self.window.geometry(f"{w}x{h}")


class ConfigWindow:
    def __init__(self, root):
        self.root          = root
        self.current_level = "beginner"
        self.diff_btns     = {}
        self.custom_frame  = None
        self.play_anchor   = None
        self.score_alert   = ScoreAlertListener(root)

        self.root.title("Buscaminas")
        self.root.resizable(False, False)
        self.root.configure(bg="#1a1a2e")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build_ui()
        self._select("beginner")

    def _center(self):
        self.root.update_idletasks()
        w  = max(self.root.winfo_reqwidth(), 360)
        h  = self.root.winfo_reqheight()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    def _build_ui(self):

        tk.Label(self.root, text="💣  BUSCAMINAS",
                 font=("Segoe UI", 22, "bold"),
                 bg="#1a1a2e", fg="#e94560").pack(pady=(28, 4))

        tk.Label(self.root, text="Configura tu partida",
                 font=("Segoe UI", 11),
                 bg="#1a1a2e", fg="#a8b2d8").pack()

        tk.Button(
            self.root, text="🏆  Ver Puntajes",
            font=("Segoe UI", 9),
            bg="#1a1a2e", fg="#a8b2d8",
            activebackground="#1a1a2e", activeforeground="white",
            relief="flat", cursor="hand2",
            command=lambda: ScoreWindow(self.root)
        ).pack(pady=(4, 14))

        self._build_difficulty_grid()

        tk.Frame(self.root, bg="#2a2a4e", height=1).pack(
            fill="x", padx=30, pady=(18, 0))

        self.custom_frame = self._build_custom_frame()

        self.play_anchor = tk.Frame(self.root, bg="#1a1a2e")
        self.play_anchor.pack(pady=(18, 28))
        tk.Button(
            self.play_anchor, text="▶   JUGAR",
            font=("Segoe UI", 13, "bold"),
            bg="#e94560", fg="white",
            activebackground="#c73652", activeforeground="white",
            relief="flat", cursor="hand2",
            padx=24, pady=9,
            command=self._start_game
        ).pack()

        self._center()

    def _build_difficulty_grid(self):
        frame = tk.Frame(self.root, bg="#1a1a2e")
        frame.pack(padx=26)
        for i, (key, label, subtitle, *_) in enumerate(LEVELS):
            btn = tk.Button(
                frame,
                text=f"{label}\n{subtitle}",
                font=("Segoe UI", 9, "bold"),
                width=15, height=2,
                bg="#0f3460", fg="#a8b2d8",
                activebackground="#1a4a80", activeforeground="white",
                relief="flat", cursor="hand2",
                command=lambda k=key: self._select(k)
            )
            btn.grid(row=i // 2, column=i % 2, padx=5, pady=5)
            self.diff_btns[key] = btn

    def _build_custom_frame(self):
        frame = tk.Frame(self.root, bg="#1a1a2e")
        self.e_rows  = self._field(frame, "Filas",    "10")
        self.e_cols  = self._field(frame, "Columnas", "10")
        self.e_mines = self._field(frame, "Minas",    "15")
        return frame

    def _field(self, parent, label, default):
        row = tk.Frame(parent, bg="#1a1a2e")
        row.pack(fill="x", pady=4)
        tk.Label(row, text=label,
                 font=("Segoe UI", 10), width=9, anchor="w",
                 bg="#1a1a2e", fg="#a8b2d8").pack(side="left")
        entry = tk.Entry(row,
                         font=("Segoe UI", 11), width=7,
                         bg="#16213e", fg="white",
                         insertbackground="white",
                         relief="flat", justify="center")
        entry.insert(0, default)
        entry.pack(side="left", ipady=5, padx=(8, 0))
        return entry

    def _select(self, key):
        self.current_level = key
        for k, btn in self.diff_btns.items():
            btn.config(
                bg="#e94560" if k == key else "#0f3460",
                fg="white"   if k == key else "#a8b2d8"
            )
        if key == "custom":
            self.custom_frame.pack(
                before=self.play_anchor, padx=55, pady=(14, 0), fill="x")
        else:
            self.custom_frame.pack_forget()
        self.root.update_idletasks()
        w = max(self.root.winfo_reqwidth(), 360)
        self.root.geometry(f"{w}x{self.root.winfo_reqheight()}")

    def _start_game(self):
        if self.current_level == "custom":
            try:
                rows  = int(self.e_rows.get())
                cols  = int(self.e_cols.get())
                mines = int(self.e_mines.get())
            except ValueError:
                messagebox.showerror("Error", "Ingresa solo números enteros.")
                return
            if rows < 2 or cols < 2:
                messagebox.showerror("Error", "El tablero debe ser mínimo 2x2.")
                return
            if mines < 1 or mines >= rows * cols:
                messagebox.showerror("Error",
                    f"Las minas deben estar entre 1 y {rows*cols-1}.")
                return
            level_key = None
        else:
            preset    = {k: (r, c, m) for k, _, _, r, c, m in LEVELS}
            rows, cols, mines = preset[self.current_level]
            level_key = self.current_level

        client = BuscaminasClient()
        try:
            client.connect()
        except ConnectionRefusedError:
            messagebox.showerror(
                "Sin conexión",
                "No se pudo conectar al servidor.\n\n"
                "Asegúrate de que server.py esté corriendo."
            )
            return

        resp = client.init_game(rows, cols, mines)
        if resp and resp.get("type") == "init_ok":
            self.root.withdraw()
            GameWindow(self.root, client, rows, cols, mines, level_key)
        else:
            messagebox.showerror("Error", "El servidor no pudo iniciar la partida.")
            client.disconnect()

    def _on_close(self):
        self.score_alert.close()
        self.root.destroy()


class GameWindow:
    def __init__(self, master, client, rows, cols, mines, level_key=None):
        self.master      = master
        self.client      = client
        self.rows        = rows
        self.cols        = cols
        self.total_mines = mines
        self.level_key   = level_key
        self.game_active = True
        self.buttons     = {}

        self.flagged     = set()
        self.flags_count = 0

        self.start_time    = None
        self.timer_running = False

        self.window = tk.Toplevel(master)
        self.window.title("Buscaminas")
        self.window.resizable(False, False)
        self.window.configure(bg="#1a1a2e")
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_top_bar()
        self._build_board()
        self._center()

    def _center(self):
        self.window.update_idletasks()
        w  = self.window.winfo_reqwidth()
        h  = self.window.winfo_reqheight()
        sw = self.window.winfo_screenwidth()
        sh = self.window.winfo_screenheight()
        self.window.geometry(f"+{(sw-w)//2}+{(sh-h)//2}")


    def _build_top_bar(self):
        bar = tk.Frame(self.window, bg="#16213e", pady=8)
        bar.pack(fill="x", padx=8, pady=(10, 2))

        self.mine_label = tk.Label(
            bar, text=f"💣  {self.total_mines}",
            font=("Segoe UI", 14, "bold"),
            bg="#16213e", fg="#e94560"
        )
        self.mine_label.pack(side="left", padx=10)

        self.timer_label = tk.Label(
            bar, text="⏱  0:00",
            font=("Segoe UI", 14, "bold"),
            bg="#16213e", fg="#a8b2d8"
        )
        self.timer_label.pack(side="left", padx=14)

        tk.Button(
            bar, text="↺  Nueva Partida",
            font=("Segoe UI", 10, "bold"),
            bg="#0f3460", fg="white",
            activebackground="#1a4a80", activeforeground="white",
            relief="flat", cursor="hand2", padx=10, pady=4,
            command=self._new_game
        ).pack(side="right", padx=4)

        tk.Button(
            bar, text="🔍  RESOLVER",
            font=("Segoe UI", 10, "bold"),
            bg="#e94560", fg="white",
            activebackground="#c73652", activeforeground="white",
            relief="flat", cursor="hand2", padx=10, pady=4,
            command=self._solve
        ).pack(side="right", padx=4)

        if self.level_key:
            tk.Button(
                bar, text="🏆",
                font=("Segoe UI", 13),
                bg="#16213e", fg="#FFD700",
                activebackground="#16213e", activeforeground="#FFD700",
                relief="flat", cursor="hand2", padx=6,
                command=lambda: ScoreWindow(self.window, self.level_key)
            ).pack(side="right", padx=2)


    def _build_board(self):
        board_frame = tk.Frame(self.window, bg="#1a1a2e")
        board_frame.pack(padx=8, pady=8)
        for r in range(self.rows):
            for c in range(self.cols):
                btn = tk.Button(
                    board_frame,
                    text="", width=2, height=1,
                    font=("Consolas", 11, "bold"),
                    bg="#0f3460", fg="white",
                    activebackground="#1a4a80",
                    relief="raised", cursor="hand2"
                )
                btn.bind("<Button-1>",
                         lambda e, row=r, col=c: self._on_left_click(e, row, col))
                btn.bind("<Button-3>",
                         lambda e, row=r, col=c: self._toggle_flag(row, col))
                btn.grid(row=r, column=c, padx=1, pady=1)
                self.buttons[(r, c)] = btn


    def _start_timer(self):
        self.start_time    = time.time()
        self.timer_running = True
        self._tick()

    def _tick(self):
        if not self.timer_running:
            return
        elapsed = int(time.time() - self.start_time)
        m, s    = divmod(elapsed, 60)
        self.timer_label.config(text=f"⏱  {m}:{s:02d}")
        self.window.after(1000, self._tick)

    def _stop_timer(self):
        self.timer_running = False
        if self.start_time is None:
            return 0
        return int(time.time() - self.start_time)


    def _on_left_click(self, event, r, c):
        """Ctrl + click izquierdo → marcar  |  click normal → revelar"""
        if event.state & 4:
            self._toggle_flag(r, c)
        else:
            self._on_click(r, c)

    def _on_click(self, r, c):
        if not self.game_active:
            return
        if (r, c) in self.flagged:
            return
        if self.start_time is None:
            self._start_timer()
        resp = self.client.click_cell(r, c)
        if resp:
            self._handle_response(resp, clicked_cell=(r, c))

    def _toggle_flag(self, r, c):
        if not self.game_active:
            return
        btn = self.buttons[(r, c)]
        if str(btn.cget("state")) == tk.DISABLED:
            return
        if (r, c) in self.flagged:
            self.flagged.discard((r, c))
            self.flags_count -= 1
            btn.config(text="", bg="#0f3460", fg="white",
                       font=("Consolas", 11, "bold"))
        else:
            self.flagged.add((r, c))
            self.flags_count += 1
            btn.config(text="✖", bg="#1a2a50", fg="#FF7043",
                       font=("Consolas", 12, "bold"))
        self.mine_label.config(
            text=f"💣  {self.total_mines - self.flags_count}")


    def _handle_response(self, resp, clicked_cell=None):
        t = resp.get("type")

        if t == "update":
            self._reveal_cells(resp["cells"])

        elif t == "win":
            self._reveal_cells(resp["cells"])
            elapsed = self._stop_timer()
            self.game_active = False

            if self.level_key:
                def handle_win():
                    def on_name_saved(name):
                        try:
                            ScoreManager.save_score(self.level_key, name, elapsed)
                            ScoreWindow(self.window, self.level_key)
                        except Exception as exc:
                            messagebox.showerror(
                                "Error",
                                f"No se pudo guardar el puntaje.\n\n{exc}"
                            )
                    WinDialog(self.window, elapsed, self.level_key, on_name_saved)
                self.window.after(150, handle_win)
            else:
                m, s = divmod(elapsed, 60)
                self.window.after(150, lambda: messagebox.showinfo(
                    "¡Ganaste! 🎉",
                    f"¡Despejaste el tablero en {m}:{s:02d}!\n\n"
                    "Presiona 'Nueva Partida' para jugar de nuevo."
                ))

        elif t == "game_over":
            self._stop_timer()
            self._show_mines(resp["mines"], exploded=clicked_cell)
            self.game_active = False
            self.window.after(150, lambda: messagebox.showerror(
                "💥 ¡BOOM!",
                "¡Pisaste una mina!\n\n"
                "Presiona 'Nueva Partida' para intentarlo de nuevo."
            ))

    def _reveal_cells(self, cells):
        for cell in cells:
            r, c, v = cell["row"], cell["col"], cell["value"]
            if (r, c) in self.flagged:
                self.flagged.discard((r, c))
                self.flags_count -= 1
            color = NUMBER_COLORS.get(v, "#cccccc")
            self.buttons[(r, c)].config(
                text=str(v) if v > 0 else "",
                state="disabled", relief="sunken",
                bg="#2a2a4a", fg=color, disabledforeground=color
            )
        self.mine_label.config(
            text=f"💣  {self.total_mines - self.flags_count}")

    def _show_mines(self, mines, exploded=None):
        for mine in mines:
            r, c = mine["row"], mine["col"]
            bg   = "#c62828" if (exploded and (r, c) == exploded) else "#e65100"
            self.buttons[(r, c)].config(
                text="💣", bg=bg, state="disabled",
                relief="sunken", disabledforeground="white"
            )

    def _solve(self):
        if not self.game_active:
            return
        self._stop_timer()
        resp = self.client.solve()
        if resp:
            self._show_mines(resp["mines"])
            self.game_active = False

    def _new_game(self):
        self._stop_timer()
        self.client.disconnect()
        self.window.destroy()
        client = BuscaminasClient()
        try:
            client.connect()
        except ConnectionRefusedError:
            messagebox.showerror("Sin conexión", "¿Está corriendo server.py?")
            self.master.deiconify()
            return
        resp = client.init_game(self.rows, self.cols, self.total_mines)
        if resp and resp.get("type") == "init_ok":
            GameWindow(self.master, client, self.rows, self.cols,
                       self.total_mines, self.level_key)
        else:
            messagebox.showerror("Error", "El servidor no pudo iniciar la partida.")
            client.disconnect()
            self.master.deiconify()

    def _on_close(self):
        self._stop_timer()
        self.client.disconnect()
        self.window.destroy()
        self.master.deiconify()


if __name__ == "__main__":
    root = tk.Tk()
    ConfigWindow(root)
    root.mainloop()
