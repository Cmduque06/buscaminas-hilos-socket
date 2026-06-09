import socket
import threading
import random
import json
from datetime import datetime

HOST = '127.0.0.1'
PORT = 5050
SCORES_FILE = "scores.json"
LEVEL_KEYS = ("beginner", "intermediate", "expert")
score_lock = threading.Lock()
subscribers_lock = threading.Lock()
score_subscribers = {}


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
    def load():
        try:
            with open(SCORES_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            data = {}
        for key in LEVEL_KEYS:
            data.setdefault(key, [])
        return data

    @staticmethod
    def save_score(level_key, name, elapsed_secs):
        entry = {
            "name": name.strip() or "Anónimo",
            "time": elapsed_secs,
            "date": datetime.now().strftime("%d/%m/%Y"),
        }

        with score_lock:
            data = ScoreManager.load()
            data[level_key].append(entry)
            data[level_key].sort(key=lambda x: x["time"])
            kept_scores = data[level_key][:10]
            position = next(
                (i + 1 for i, score in enumerate(kept_scores) if score is entry),
                None
            )
            data[level_key] = kept_scores

            with open(SCORES_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

        return data, entry, position


def add_score_subscriber(client_id, conn):
    with subscribers_lock:
        score_subscribers[conn] = client_id


def remove_score_subscriber(conn):
    with subscribers_lock:
        score_subscribers.pop(conn, None)


def broadcast_score_update(data, entry, level_key, position, source_id):
    payload = {
        "type": "scores_update",
        "scores": data,
        "new_score": {
            "level": level_key,
            "entry": entry,
            "position": position,
        }
    }
    stale = []
    with subscribers_lock:
        targets = list(score_subscribers.items())

    for conn, client_id in targets:
        try:
            message = dict(payload)
            message["show_popup"] = (
                position is not None and position <= 5 and client_id != source_id
            )
            send_msg(conn, message)
        except Exception:
            stale.append(conn)

    for conn in stale:
        remove_score_subscriber(conn)


class BuscaminasGame:
    def __init__(self, rows, cols, mines_count, safe_start=True):
        self.rows        = rows
        self.cols        = cols
        self.mines_count = mines_count
        self.safe_start  = safe_start
        self.first_click = True
        self.board    = [[False] * cols for _ in range(rows)]
        self.revealed = [[False] * cols for _ in range(rows)]

        if not safe_start:
            self._place_mines_random()
            self.first_click = False

    def _place_mines_random(self):
        positions = random.sample(range(self.rows * self.cols), self.mines_count)
        for pos in positions:
            self.board[pos // self.cols][pos % self.cols] = True

    def _place_mines_safe(self, safe_row, safe_col):
        safe_set = set()
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                nr, nc = safe_row + dr, safe_col + dc
                if 0 <= nr < self.rows and 0 <= nc < self.cols:
                    safe_set.add(nr * self.cols + nc)

        available = [i for i in range(self.rows * self.cols) if i not in safe_set]

        if len(available) < self.mines_count:
            clicked   = safe_row * self.cols + safe_col
            available = [i for i in range(self.rows * self.cols) if i != clicked]

        positions = random.sample(available, self.mines_count)
        for pos in positions:
            self.board[pos // self.cols][pos % self.cols] = True


    def count_adjacent(self, row, col):
        count = 0
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                nr, nc = row + dr, col + dc
                if 0 <= nr < self.rows and 0 <= nc < self.cols and self.board[nr][nc]:
                    count += 1
        return count

    def reveal_cell(self, row, col):
        cells = []
        stack = [(row, col)]
        while stack:
            r, c = stack.pop()
            if self.revealed[r][c]:
                continue
            self.revealed[r][c] = True
            adj = self.count_adjacent(r, c)
            cells.append({"row": r, "col": c, "value": adj})
            if adj == 0:
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        if dr == 0 and dc == 0:
                            continue
                        nr, nc = r + dr, c + dc
                        if 0 <= nr < self.rows and 0 <= nc < self.cols and not self.revealed[nr][nc]:
                            stack.append((nr, nc))
        return cells

    def check_win(self):
        for r in range(self.rows):
            for c in range(self.cols):
                if not self.board[r][c] and not self.revealed[r][c]:
                    return False
        return True

    def get_all_mines(self):
        return [
            {"row": r, "col": c}
            for r in range(self.rows)
            for c in range(self.cols)
            if self.board[r][c]
        ]


def handle_client(conn, addr):
    print(f"[CONEXIÓN]    {addr} conectado.")
    game = None
    subscribed_to_scores = False
    try:
        while True:
            msg = recv_msg(conn)
            if msg is None:
                break
            t = msg.get("type")

            if t == "scores_get":
                send_msg(conn, {
                    "type": "scores_data",
                    "scores": ScoreManager.load(),
                })

            elif t == "scores_subscribe":
                add_score_subscriber(msg.get("client_id"), conn)
                subscribed_to_scores = True
                send_msg(conn, {
                    "type": "scores_data",
                    "scores": ScoreManager.load(),
                })
                print(f"[{addr}]  SUSCRITO A PUNTAJES.")

            elif t == "score_submit":
                level_key = msg.get("level")
                if level_key not in LEVEL_KEYS:
                    send_msg(conn, {"type": "score_error", "message": "Nivel invalido."})
                    continue

                data, entry, position = ScoreManager.save_score(
                    level_key,
                    msg.get("name", ""),
                    int(msg.get("time", 0))
                )
                send_msg(conn, {
                    "type": "score_saved",
                    "scores": data,
                    "position": position,
                })
                broadcast_score_update(
                    data, entry, level_key, position, msg.get("client_id")
                )
                print(f"[{addr}]  PUNTAJE {level_key}: {entry['name']} #{position}.")

            elif t == "init":
                rows       = msg["rows"]
                cols       = msg["cols"]
                mines      = msg["mines"]
                safe_start = msg.get("safe_start", True)
                game       = BuscaminasGame(rows, cols, mines, safe_start)
                send_msg(conn, {"type": "init_ok"})
                print(f"[{addr}]  {rows}×{cols} | {mines} minas | safe={safe_start}")

            elif t == "click" and game:
                r = msg["row"]
                c = msg["col"]

                if game.first_click:
                    game.first_click = False
                    if game.safe_start:
                        game._place_mines_safe(r, c)

                if game.board[r][c]:
                    send_msg(conn, {"type": "game_over", "mines": game.get_all_mines()})
                    print(f"[{addr}]  GAME OVER ({r},{c}).")
                else:
                    cells = game.reveal_cell(r, c)
                    if game.check_win():
                        send_msg(conn, {"type": "win", "cells": cells})
                        print(f"[{addr}]  GANÓ.")
                    else:
                        send_msg(conn, {"type": "update", "cells": cells})

            elif t == "solve" and game:
                send_msg(conn, {"type": "solve", "mines": game.get_all_mines()})
                print(f"[{addr}]  RESOLVER.")

    except Exception as e:
        print(f"[ERROR]       {addr}: {e}")
    finally:
        if subscribed_to_scores:
            remove_score_subscriber(conn)
        conn.close()
        print(f"[DESCONEXIÓN] {addr} desconectado.")


def start_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen()
    print(f"[SERVIDOR]    Escuchando en {HOST}:{PORT} ...")
    while True:
        conn, addr = server.accept()
        t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
        t.start()
        print(f"[HILOS ACTIVOS] {threading.active_count() - 1}")


if __name__ == "__main__":
    start_server()
