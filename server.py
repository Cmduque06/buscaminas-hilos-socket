import socket
import threading
import random
import json

HOST = '127.0.0.1'
PORT = 5050


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
    try:
        while True:
            msg = recv_msg(conn)
            if msg is None:
                break
            t = msg.get("type")

            if t == "init":
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