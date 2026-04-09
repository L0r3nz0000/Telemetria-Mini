#!/usr/bin/env python3
"""
MINI Cooper D — Racing Dashboard
ESP32 → Raspberry Pi OBD2 / CAN Bus Display
Riceve dati via seriale (JSON) o li simula se la porta non è disponibile.

Protocollo seriale atteso (JSON su newline):
  {"rpm": 2500, "speed": 87, "coolant": 92, "turbo_bar": 1.2,
   "fuel_pct": 68, "oil_temp": 95, "battery_v": 14.1, "throttle_pct": 45}
"""

import tkinter as tk
from tkinter import font as tkfont
import math
import time
import threading
import random
import json
import sys
import os

# ── CONFIG ────────────────────────────────────────────────────────────────────
# Font: metti il nome esatto del tuo TTF (come appare dopo fc-list o dopo
# l'installazione). Esempio: "Orbitron", "RacingSans One", "D-DIN", ecc.
FONT = "Bruno Ace"
SERIAL_PORT   = "/dev/ttyUSB0"   # cambia con la tua porta
BAUD_RATE     = 115200
SIMULATE      = True             # True = dati simulati, False = seriale reale
FULLSCREEN    = False            # True per schermo intero su RPi
UPDATE_MS     = 80               # refresh rate ~12 fps
# ─────────────────────────────────────────────────────────────────────────────

# Palette
BG          = "#0a0a0f"
PANEL       = "#11111a"
BORDER      = "#1e1e30"
RED         = "#ff2040"
ORANGE      = "#ff6820"
YELLOW      = "#ffd020"
GREEN       = "#20ff80"
CYAN        = "#00e5ff"
WHITE       = "#f0f4ff"
DIM         = "#3a3a5a"
REDLINE     = "#ff0030"

# ── DATA MODEL ────────────────────────────────────────────────────────────────
class CarData:
    def __init__(self):
        self.rpm          = 0.0
        self.speed        = 0.0
        self.coolant_temp = 80.0
        self.turbo_bar    = 0.0
        self.fuel_pct     = 75.0
        self.oil_temp     = 80.0
        self.battery_v    = 12.6
        self.throttle_pct = 0.0
        self.gear         = 0      # 0 = N
        self._sim_phase   = 0.0

    def simulate(self):
        """Genera dati finti realistici per test."""
        t = self._sim_phase
        self._sim_phase += 0.025

        self.speed        = max(0, 60 + 55 * math.sin(t * 0.4) + random.uniform(-1, 1))
        self.rpm          = max(800, 1800 + 1500 * math.sin(t * 0.6) +
                                500 * math.sin(t * 1.3) + random.uniform(-30, 30))
        self.turbo_bar    = max(0, min(2.2, 0.9 + 1.0 * math.sin(t * 0.7) +
                                      random.uniform(-0.05, 0.05)))
        self.throttle_pct = max(0, min(100, 45 + 40 * math.sin(t * 0.65) +
                                       random.uniform(-2, 2)))
        self.coolant_temp = min(105, 85 + 8 * math.sin(t * 0.1) + random.uniform(-0.2, 0.2))
        self.oil_temp     = min(120, 90 + 12 * math.sin(t * 0.08) + random.uniform(-0.2, 0.2))
        self.fuel_pct     = max(0, self.fuel_pct - 0.003)
        self.battery_v    = 14.1 + 0.3 * math.sin(t * 0.3) + random.uniform(-0.02, 0.02)

        # stima marcia rozza
        spd = self.speed
        if spd < 5:   self.gear = 0
        elif spd < 20: self.gear = 1
        elif spd < 38: self.gear = 2
        elif spd < 60: self.gear = 3
        elif spd < 85: self.gear = 4
        elif spd < 115: self.gear = 5
        else:          self.gear = 6

    def from_json(self, raw: str):
        try:
            d = json.loads(raw)
            self.rpm          = float(d.get("rpm", self.rpm))
            self.speed        = float(d.get("speed", self.speed))
            self.coolant_temp = float(d.get("coolant", self.coolant_temp))
            self.turbo_bar    = float(d.get("turbo_bar", self.turbo_bar))
            self.fuel_pct     = float(d.get("fuel_pct", self.fuel_pct))
            self.oil_temp     = float(d.get("oil_temp", self.oil_temp))
            self.battery_v    = float(d.get("battery_v", self.battery_v))
            self.throttle_pct = float(d.get("throttle_pct", self.throttle_pct))
        except Exception:
            pass

# ── SERIAL THREAD ─────────────────────────────────────────────────────────────
def serial_reader(data: CarData, stop_event: threading.Event):
    try:
        import serial
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        while not stop_event.is_set():
            line = ser.readline().decode("utf-8", errors="ignore").strip()
            if line:
                data.from_json(line)
    except Exception as e:
        print(f"[Serial] {e} — fallback simulazione")

# ── DRAW HELPERS ──────────────────────────────────────────────────────────────
def arc_pts(cx, cy, r, start_deg, end_deg, steps=60):
    pts = []
    for i in range(steps + 1):
        a = math.radians(start_deg + (end_deg - start_deg) * i / steps)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts

def needle_endpoint(cx, cy, r, angle_deg):
    a = math.radians(angle_deg)
    return cx + r * math.cos(a), cy + r * math.sin(a)

def draw_arc(canvas, cx, cy, r, a0, a1, color, width=2, steps=60, collect=None, **kw):
    pts = arc_pts(cx, cy, r, a0, a1, steps)
    for i in range(len(pts) - 1):
        tid = canvas.create_line(pts[i][0], pts[i][1], pts[i+1][0], pts[i+1][1],
                                 fill=color, width=width, **kw)
        if collect is not None:
            collect.append(tid)

def lerp_color(t, c1, c2):
    """Interpola tra due colori hex, t in [0,1]."""
    r1, g1, b1 = int(c1[1:3],16), int(c1[3:5],16), int(c1[5:7],16)
    r2, g2, b2 = int(c2[1:3],16), int(c2[3:5],16), int(c2[5:7],16)
    r = int(r1 + (r2-r1)*t)
    g = int(g1 + (g2-g1)*t)
    b = int(b1 + (b2-b1)*t)
    return f"#{r:02x}{g:02x}{b:02x}"

# ── WIDGET: GAUGE TACHIMETRO / TACHIMETRO ─────────────────────────────────────
class BigGauge:
    """Gauge circolare grande con lancetta.
    clockwise=True  -> arco percorre senso orario da start a end
    clockwise=False -> arco percorre senso antiorario da start a end
    """
    def __init__(self, canvas, cx, cy, r,
                 min_val, max_val, redline,
                 label, unit,
                 arc_start=225, arc_end=-45,
                 color=CYAN, clockwise=True):
        self.c        = canvas
        self.cx, self.cy = cx, cy
        self.r        = r
        self.min_val  = min_val
        self.max_val  = max_val
        self.redline  = redline
        self.label    = label
        self.unit     = unit
        self.a_start  = arc_start
        self.color    = color
        self.clockwise = clockwise
        self.tags     = []
        # Calcola end effettivo per il senso di percorrenza richiesto
        delta = (arc_end - arc_start) % 360   # delta orario puro [0,360)
        if clockwise:
            self._a_end_eff = arc_start + (delta if delta != 0 else 360)
        else:
            self._a_end_eff = arc_start - (360 - delta if delta != 0 else 360)
        self._draw_static()

    def _val_to_angle(self, v):
        t = (v - self.min_val) / (self.max_val - self.min_val)
        t = max(0, min(1, t))
        return self.a_start + (self._a_end_eff - self.a_start) * t

    def _draw_static(self):
        cx, cy, r = self.cx, self.cy, self.r
        c = self.c

        # cerchio esterno decorativo
        c.create_oval(cx-r-8, cy-r-8, cx+r+8, cy+r+8,
                      outline=BORDER, width=2, fill=PANEL)
        c.create_oval(cx-r, cy-r, cx+r, cy+r,
                      outline=DIM, width=1, fill="")

        # arco scala
        draw_arc(c, cx, cy, r-8, self.a_start, self._a_end_eff,
                 DIM, width=4, steps=80)

        # tacche e numeri
        steps = 10
        for i in range(steps + 1):
            t   = i / steps
            val = self.min_val + t * (self.max_val - self.min_val)
            ang = math.radians(self._val_to_angle(val))
            r_out = r - 4
            r_in  = r - 16 if i % 2 == 0 else r - 10
            col   = RED if val >= self.redline else WHITE
            x1 = cx + r_out * math.cos(ang)
            y1 = cy + r_out * math.sin(ang)
            x2 = cx + r_in  * math.cos(ang)
            y2 = cy + r_in  * math.sin(ang)
            c.create_line(x1, y1, x2, y2, fill=col, width=2 if i%2==0 else 1)
            if i % 2 == 0:
                r_txt = r - 28
                tx = cx + r_txt * math.cos(ang)
                ty = cy + r_txt * math.sin(ang)
                lbl = str(int(val // 1000)) if self.max_val >= 5000 else str(int(val))
                c.create_text(tx, ty, text=lbl, fill=WHITE,
                              font=(FONT, 9, "bold"))

        # etichetta
        c.create_text(cx, cy + r*0.45, text=self.label,
                      fill=DIM, font=(FONT, 10, "bold"))
        c.create_text(cx, cy + r*0.60, text=self.unit,
                      fill=DIM, font=(FONT, 8))

        # centro
        c.create_oval(cx-7, cy-7, cx+7, cy+7, fill=WHITE, outline="")

    def update(self, value):
        for t in self.tags:
            self.c.delete(t)
        self.tags.clear()
        cx, cy, r = self.cx, self.cy, self.r
        c = self.c

        ang_deg = self._val_to_angle(value)

        # arco colorato fino al valore
        col = RED if value >= self.redline else self.color
        draw_arc(c, cx, cy, r-8, self.a_start, ang_deg, col, width=4, steps=80, collect=self.tags)
        # glow
        draw_arc(c, cx, cy, r-8, self.a_start, ang_deg,
                 col, width=2, steps=80, collect=self.tags)

        # lancetta
        nx, ny = needle_endpoint(cx, cy, r-20, ang_deg)
        tid = c.create_line(cx, cy, nx, ny, fill=col, width=3,
                            capstyle=tk.ROUND)
        self.tags.append(tid)

        # pallino centro
        tid = c.create_oval(cx-5, cy-5, cx+5, cy+5, fill=col, outline="")
        self.tags.append(tid)

        # valore numerico
        tid = c.create_text(cx, cy - r*0.25, text=f"{int(value)}",
                            fill=WHITE, font=(FONT, 18, "bold"))
        self.tags.append(tid)

# ── WIDGET: BARRA VERTICALE ───────────────────────────────────────────────────
class VBar:
    def __init__(self, canvas, x, y, w, h, min_val, max_val,
                 label, unit, warn_pct=0.8, color=GREEN):
        self.c = canvas
        self.x, self.y = x, y
        self.w, self.h = w, h
        self.min_val   = min_val
        self.max_val   = max_val
        self.label     = label
        self.unit      = unit
        self.warn_pct  = warn_pct
        self.color     = color
        self.tags      = []
        self._draw_static()

    def _draw_static(self):
        x, y, w, h = self.x, self.y, self.w, self.h
        self.c.create_rectangle(x, y, x+w, y+h,
                                outline=BORDER, fill=PANEL, width=1)
        # tacche
        for i in range(5):
            ty = y + h - (h * i / 4)
            self.c.create_line(x, ty, x+w, ty, fill=BORDER, width=1)
        self.c.create_text(x + w//2, y + h + 14, text=self.label,
                           fill=DIM, font=(FONT, 8, "bold"))

    def update(self, value):
        for t in self.tags:
            self.c.delete(t)
        self.tags.clear()
        x, y, w, h = self.x, self.y, self.w, self.h

        pct = (value - self.min_val) / (self.max_val - self.min_val)
        pct = max(0, min(1, pct))
        fill_h = int(h * pct)

        col = RED if pct >= self.warn_pct else self.color

        if fill_h > 0:
            # barra
            t = self.c.create_rectangle(x+2, y+h-fill_h, x+w-2, y+h,
                                        outline="", fill=col)
            self.tags.append(t)
            # riflesso
            t = self.c.create_rectangle(x+2, y+h-fill_h, x+4, y+h,
                                        outline="", fill=lerp_color(0.5, col, WHITE))
            self.tags.append(t)

        # valore
        t = self.c.create_text(x+w//2, y-12, text=f"{value:.1f}{self.unit}",
                               fill=col if fill_h > 0 else DIM,
                               font=(FONT, 8, "bold"))
        self.tags.append(t)

# ── WIDGET: BARRA OBLIQUA TURBO ───────────────────────────────────────────────
class TurboBar:
    """Barra obliqua stile motorsport per pressione turbo."""
    def __init__(self, canvas, x, y, w, h, max_bar=2.5):
        self.c = canvas
        self.x, self.y = x, y
        self.w, self.h = w, h
        self.max_bar   = max_bar
        self.tags      = []
        self.segments  = 20
        self._draw_static()

    def _draw_static(self):
        x, y, w, h = self.x, self.y, self.w, self.h
        self.c.create_text(x + w//2, y - 16, text="TURBO BOOST",
                           fill=ORANGE, font=(FONT, 10, "bold"))
        self.c.create_text(x + w//2, y + h + 14, text="bar",
                           fill=DIM, font=(FONT, 8))
        # cornice obliqua — stessa forma dei segmenti interni
        skew = h * 0.3
        frame_pts = [
            x + skew - 2,     y - 2,
            x + w + skew + 2, y - 2,
            x + w + 2,        y + h + 2,
            x - 2,            y + h + 2,
        ]
        self.c.create_polygon(frame_pts, outline=BORDER, fill="", width=1)

    def update(self, value):
        for t in self.tags:
            self.c.delete(t)
        self.tags.clear()
        x, y, w, h = self.x, self.y, self.w, self.h
        n = self.segments
        seg_w = w / n
        skew  = h * 0.3  # inclinazione obliqua

        filled = int(n * min(1.0, value / self.max_bar))

        for i in range(n):
            x0 = x + i * seg_w
            # trapezio obliquo
            pts = [
                x0 + skew,       y,
                x0 + seg_w + skew - 1, y,
                x0 + seg_w - 1,  y + h,
                x0,              y + h,
            ]
            if i < filled:
                t_ratio = i / n
                if t_ratio < 0.5:
                    col = lerp_color(t_ratio * 2, GREEN, YELLOW)
                else:
                    col = lerp_color((t_ratio - 0.5) * 2, YELLOW, RED)
            else:
                col = BORDER
            t = self.c.create_polygon(pts, fill=col, outline="")
            self.tags.append(t)

        # valore
        t = self.c.create_text(x + w//2, y + h//2,
                               text=f"{value:.2f}",
                               fill=WHITE, font=(FONT, 14, "bold"))
        self.tags.append(t)

# ── WIDGET: SPEEDOMETER DIGITALE ─────────────────────────────────────────────
class SpeedDigital:
    def __init__(self, canvas, cx, cy):
        self.c  = canvas
        self.cx = cx
        self.cy = cy
        self.tags = []

    def update(self, value):
        for t in self.tags:
            self.c.delete(t)
        self.tags.clear()
        spd = int(value)
        col = RED if spd > 150 else WHITE
        # numero senza padding — anchor center garantisce centratura reale
        t = self.c.create_text(self.cx, self.cy, text=str(spd),
                               fill=col, font=(FONT, 64, "bold"),
                               anchor="center")
        self.tags.append(t)
        # "km/h" sempre centrato sotto, stessa cx
        t = self.c.create_text(self.cx, self.cy + 56, text="km/h",
                               fill=DIM, font=(FONT, 13, "bold"),
                               anchor="center")
        self.tags.append(t)

# ── WIDGET: GEAR INDICATOR ────────────────────────────────────────────────────
class GearIndicator:
    def __init__(self, canvas, cx, cy):
        self.c  = canvas
        self.cx = cx
        self.cy = cy
        self.tags = []
        self.c.create_text(cx, cy + 42, text="GEAR",
                           fill=DIM, font=(FONT, 9, "bold"))

    def update(self, gear):
        for t in self.tags:
            self.c.delete(t)
        self.tags.clear()
        label = "N" if gear == 0 else str(gear)
        col   = YELLOW if gear == 0 else CYAN
        t = self.c.create_text(self.cx, self.cy,
                               text=label, fill=col,
                               font=(FONT, 52, "bold"))
        self.tags.append(t)

# ── WIDGET: THROTTLE BAR OBLIQUA ─────────────────────────────────────────────
class ThrottleBar:
    def __init__(self, canvas, x, y, w, h):
        self.c = canvas
        self.x, self.y = x, y
        self.w, self.h = w, h
        self.tags = []
        self.c.create_text(x + w//2, y - 14, text="THROTTLE",
                           fill=CYAN, font=(FONT, 9, "bold"))
        self.c.create_rectangle(x, y, x+w, y+h, outline=BORDER, fill=PANEL)

    def update(self, value):
        for t in self.tags:
            self.c.delete(t)
        self.tags.clear()
        pct = max(0, min(100, value)) / 100
        fw  = int(self.w * pct)
        if fw > 2:
            col = lerp_color(pct, GREEN, RED)
            t = self.c.create_rectangle(self.x+1, self.y+1,
                                        self.x+fw, self.y+self.h-1,
                                        fill=col, outline="")
            self.tags.append(t)
        t = self.c.create_text(self.x + self.w//2, self.y + self.h//2,
                               text=f"{int(value)}%",
                               fill=WHITE, font=(FONT, 9, "bold"))
        self.tags.append(t)

# ── MAIN APP ──────────────────────────────────────────────────────────────────
class Dashboard:
    def __init__(self):
        self.data      = CarData()
        self.stop_evt  = threading.Event()

        self.root = tk.Tk()
        self.root.title("MINI Cooper D — Telemetry")
        self.root.configure(bg=BG)
        if FULLSCREEN:
            self.root.attributes("-fullscreen", True)
        else:
            self.root.geometry("1024x600")
        self.root.resizable(False, False)

        W, H = 1024, 600
        self.canvas = tk.Canvas(self.root, width=W, height=H,
                                bg=BG, highlightthickness=0)
        self.canvas.pack()

        self._build_background(W, H)
        self._build_widgets(W, H)

        if not SIMULATE:
            t = threading.Thread(target=serial_reader,
                                 args=(self.data, self.stop_evt), daemon=True)
            t.start()

        self.root.bind("<Escape>", lambda e: self.quit())
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        self._loop()
        self.root.mainloop()

    def _build_background(self, W, H):
        c = self.canvas
        # bordo racing
        c.create_rectangle(4, 4, W-4, H-4, outline=RED, width=2, dash=(8,6))
        # angoli decorativi
        for ax, ay, dx, dy in [(10,10,1,1),(W-10,10,-1,1),
                               (10,H-10,1,-1),(W-10,H-10,-1,-1)]:
            c.create_line(ax, ay, ax+dx*30, ay, fill=RED, width=2)
            c.create_line(ax, ay, ax, ay+dy*30, fill=RED, width=2)
        # titolo
        c.create_text(W//2, 18, text="MINI COOPER D  ·  CAN BUS TELEMETRY",
                      fill=DIM, font=(FONT, 10, "bold"))
        # linea separatore centrale
        c.create_line(W//2, 60, W//2, H-40, fill=BORDER, width=1, dash=(4,6))

    def _build_widgets(self, W, H):
        c = self.canvas

        # ── COLONNA SINISTRA: TACHIMETRO + MARCIA ─────────────────────────
        # Tachimetro (RPM) — gauge grande
        self.rpm_gauge = BigGauge(c, 200, 310, 170,
                                  0, 7000, 5000,
                                  "RPM", "\u00d71000",
                                  arc_start=135, arc_end=45,
                                  color=RED, clockwise=True)

        # ── CENTRO: VELOCITÀ + MARCIA ──────────────────────────────────────
        c.create_text(W//2, 68, text="SPEED", fill=DIM,
                      font=(FONT, 10, "bold"))
        self.speed_disp = SpeedDigital(c, W//2, 145)
        self.gear_disp  = GearIndicator(c, W//2, 260)

        # ── TURBO (barra obliqua) ──────────────────────────────────────────
        self.turbo_bar = TurboBar(c, 380, 350, 260, 34, max_bar=2.5)

        # ── THROTTLE ──────────────────────────────────────────────────────
        self.throttle = ThrottleBar(c, 380, 430, 260, 22)

        # ── COLONNA DESTRA: BARRE VERTICALI ───────────────────────────────
        bar_y  = 100
        bar_h  = 220
        bar_w  = 38
        gap    = 56

        x_start = 710
        self.bar_coolant = VBar(c, x_start,       bar_y, bar_w, bar_h,
                                60, 110, "COOL", "°C", warn_pct=0.82,
                                color=CYAN)
        self.bar_oil     = VBar(c, x_start+gap,   bar_y, bar_w, bar_h,
                                60, 130, "OIL",  "°C", warn_pct=0.85,
                                color=ORANGE)
        self.bar_fuel    = VBar(c, x_start+gap*2, bar_y, bar_w, bar_h,
                                0,  100, "FUEL", "%",  warn_pct=0.99,
                                color=GREEN)
        self.bar_batt    = VBar(c, x_start+gap*3, bar_y, bar_w, bar_h,
                                10, 16,  "BATT", "V",  warn_pct=0.99,
                                color=YELLOW)

        # ── TIMESTAMP / SIM LABEL ─────────────────────────────────────────
        self._sim_lbl = c.create_text(W - 12, H - 12,
                                      text="[SIM]" if SIMULATE else "[LIVE]",
                                      fill=YELLOW if SIMULATE else GREEN,
                                      font=(FONT, 8), anchor="se")

    def _loop(self):
        if SIMULATE:
            self.data.simulate()

        d = self.data
        self.rpm_gauge.update(d.rpm)
        self.speed_disp.update(d.speed)
        self.gear_disp.update(d.gear)
        self.turbo_bar.update(d.turbo_bar)
        self.throttle.update(d.throttle_pct)
        self.bar_coolant.update(d.coolant_temp)
        self.bar_oil.update(d.oil_temp)
        self.bar_fuel.update(d.fuel_pct)
        self.bar_batt.update(d.battery_v)

        self.root.after(UPDATE_MS, self._loop)

    def quit(self):
        self.stop_evt.set()
        self.root.destroy()


if __name__ == "__main__":
    Dashboard()