import serial
import serial.tools.list_ports
import threading
import queue
import time
import random
import math
from collections import deque
import tkinter as tk
from tkinter import ttk

BAUD = 115200

ONLINE_TIMEOUT = 15
OFFLINE_TIMEOUT = 60
HISTORY_LEN = 60
DEMO_INTERVAL = 2.0
RSSI_WARN = -95

STATUS_ONLINE = "online"
STATUS_STALE = "stale"
STATUS_OFFLINE = "offline"

STATUS_COLORS = {
    STATUS_ONLINE: "#2ecc71",
    STATUS_STALE: "#f1c40f",
    STATUS_OFFLINE: "#e74c3c",
}

data_queue = queue.Queue()
nodes = {}
alerts = []
ser = None
demo_sim = None


def serial_reader(port):
    global ser
    try:
        ser = serial.Serial(port, BAUD, timeout=1)
    except serial.SerialException as e:
        return

    while True:
        line = ser.readline().decode(errors="replace").strip()
        if line:
            data_queue.put(line)


def parse_line(line):
    if ",DATA:" not in line:
        return None

    meta_part, payload_part = line.split(",DATA:", 1)

    meta = {}
    for item in meta_part.split(","):
        if ":" in item:
            k, v = item.split(":", 1)
            meta[k] = v

    payload = {}
    for item in payload_part.split(","):
        if ":" in item:
            k, v = item.split(":", 1)
            payload[k.strip()] = v

    if "ID" in payload:
        node_id = payload["ID"]
    elif "Node ID" in payload:
        node_id = payload["Node ID"]
    else:
        node_id = "UNKNOWN"

    return node_id, meta, payload


def format_line(node_id, rssi, snr, x, y, z, m, p, d, h):
    return ("RSSI:%s,SNR:%s,DATA:ID:%s,X:%s,Y:%s,Z:%s,M:%s,P:%s,D:%s,H:%s"
            % (rssi, snr, node_id, x, y, z, m, p, d, h))


def compute_status(last_seen):
    age = time.time() - last_seen
    if age <= ONLINE_TIMEOUT:
        return STATUS_ONLINE
    elif age <= OFFLINE_TIMEOUT:
        return STATUS_STALE
    else:
        return STATUS_OFFLINE


def new_node_entry():
    return {
        "meta": {},
        "payload": {},
        "last_seen": 0,
        "first_seen": time.time(),
        "packet_count": 0,
        "status": STATUS_OFFLINE,
        "prev_h": "0",
        "demo": False,
        "accel_hist": deque(maxlen=HISTORY_LEN),
        "dist_hist": deque(maxlen=HISTORY_LEN),
        "rssi_hist": deque(maxlen=HISTORY_LEN),
    }


def push_alert(level, node_id, text):
    alerts.append({
        "time": time.time(),
        "level": level,
        "node": node_id,
        "text": text,
    })


class DemoNode:
    def __init__(self, node_id, profile):
        self.node_id = node_id
        self.profile = profile
        self.gx = random.uniform(-0.1, 0.1)
        self.gy = random.uniform(-0.1, 0.1)
        self.gz = 1.0
        self.presence = False
        self.presence_timer = time.time() + random.uniform(3, 15)
        self.distance = random.uniform(150, 400)
        self.rssi = random.uniform(-70, -55)
        self.go_offline_at = None
        if profile == "silent":
            self.go_offline_at = time.time() + random.uniform(20, 40)

    def tick(self):
        now = time.time()

        if self.go_offline_at and now >= self.go_offline_at:
            return None

        if now >= self.presence_timer:
            self.presence = not self.presence
            if self.presence:
                self.presence_timer = now + random.uniform(10, 40)
            else:
                self.presence_timer = now + random.uniform(15, 60)

        if self.profile == "human":
            self.presence = True

        jitter = 0.6 if self.presence else 0.05
        x = self.gx + random.uniform(-jitter, jitter)
        y = self.gy + random.uniform(-jitter, jitter)
        z = self.gz + random.uniform(-jitter, jitter)

        mag_delta = abs(x - self.gx) + abs(y - self.gy) + abs(z - self.gz)
        motion = 1 if mag_delta > 0.3 else 0

        if self.presence:
            self.distance += random.uniform(-15, 15)
            self.distance = max(30, min(600, self.distance))
        else:
            self.distance = min(999, self.distance + random.uniform(0, 20))

        if self.profile == "human":
            human = 1 if (self.presence and self.distance < 450) else 0
        elif self.profile == "degrading":
            human = 0
        else:
            human = 1 if (self.presence and motion and self.distance < 300 and random.random() < 0.3) else 0

        if self.profile == "degrading":
            self.rssi -= random.uniform(0.5, 2.0)
        else:
            self.rssi += random.uniform(-2, 2)
        self.rssi = max(-120, min(-40, self.rssi))
        snr = round(random.uniform(2, 12) + (self.rssi + 90) / 10, 1)

        return format_line(
            self.node_id,
            round(self.rssi, 1),
            snr,
            round(x, 2),
            round(y, 2),
            round(z, 2),
            motion,
            1 if self.presence else 0,
            round(self.distance, 1),
            human,
        )


class DemoEnvNode:
    def __init__(self, node_id):
        self.node_id = node_id
        self.temp = random.uniform(18.0, 35.0)
        self.pressure = random.uniform(1000.0, 1025.0)
        self.humidity = random.uniform(30.0, 70.0)
        self.gx = random.uniform(-0.1, 0.1)
        self.gy = random.uniform(-0.1, 0.1)
        self.gz = 1.0
        self.gas_temp = random.uniform(20.0, 30.0)
        self.voc = random.randint(50, 400)
        self.rssi = random.uniform(-85, -60)

    def tick(self):
        self.temp += random.uniform(-0.5, 0.5)
        self.pressure += random.uniform(-1.0, 1.0)
        self.humidity += random.uniform(-1.5, 1.5)
        self.gx += random.uniform(-0.02, 0.02)
        self.gy += random.uniform(-0.02, 0.02)
        self.gz += random.uniform(-0.02, 0.02)
        self.gas_temp += random.uniform(-0.5, 0.5)
        self.voc += random.randint(-15, 15)
        self.voc = max(0, self.voc)
        
        self.rssi += random.uniform(-2, 2)
        self.rssi = max(-120, min(-40, self.rssi))
        snr = round(random.uniform(2, 12) + (self.rssi + 90) / 10, 1)

        payload_str = "Node ID:%s,Temp:%.2f,Pressure:%.2f,Humidity:%.2f,X gyro:%.2f,Y gyro:%.2f,Z gyro:%.2f,Gas temp:%.2f,VOC:%d" % (
            self.node_id, self.temp, self.pressure, self.humidity, self.gx, self.gy, self.gz, self.gas_temp, self.voc
        )
        return "RSSI:%.1f,SNR:%.1f,DATA:%s" % (self.rssi, snr, payload_str)


class DemoSimulator:
    def __init__(self):
        self.running = False
        self.thread = None
        self.demo_nodes = [
            DemoNode("DEMO-IDLE", "idle"),
            DemoNode("DEMO-MOTION", "motion"),
            DemoNode("DEMO-HUMAN", "human"),
            DemoNode("DEMO-SILENT", "silent"),
            DemoNode("DEMO-WEAK", "degrading"),
            DemoEnvNode("DEMO-ENV-1"),
            DemoEnvNode("DEMO-ENV-2"),
        ]

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False

    def run(self):
        while self.running:
            for dn in self.demo_nodes:
                line = dn.tick()
                if line:
                    data_queue.put(line)
                time.sleep(0.15)
            time.sleep(DEMO_INTERVAL)


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("First Responder System")
        self.root.configure(bg="#1e1e24")

        self.cards = {}
        self.current_node = None

        top = tk.Frame(root, bg="#1e1e24")
        top.pack(fill="x", padx=10, pady=10)

        conn = tk.Frame(top, bg="#1e1e24")
        conn.pack(side="left")

        tk.Label(conn, text="port:", bg="#1e1e24", fg="white").grid(row=0, column=0, padx=(0, 5))

        self.port_var = tk.StringVar()
        self.port_dropdown = ttk.Combobox(conn, textvariable=self.port_var, width=22, state="readonly")
        self.port_dropdown.grid(row=0, column=1, padx=(0, 5))

        tk.Button(conn, text="refresh", command=self.refresh_ports).grid(row=0, column=2, padx=(0, 5))
        tk.Button(conn, text="connect", command=self.connect).grid(row=0, column=3, padx=(0, 5))
        self.demo_btn = tk.Button(conn, text="start demo", command=self.toggle_demo)
        self.demo_btn.grid(row=0, column=4, padx=(0, 5))

        summary = tk.Frame(top, bg="#1e1e24")
        summary.pack(side="right")

        self.summary_label = tk.Label(summary, text="", bg="#1e1e24", fg="white", font=("Segoe UI", 10, "bold"))
        self.summary_label.pack(side="right")

        self.conn_status = tk.Label(root, text="not connected", fg="gray", bg="#1e1e24")
        self.conn_status.pack(anchor="w", padx=10)

        body = tk.Frame(root, bg="#1e1e24")
        body.pack(fill="both", expand=True, padx=10, pady=5)

        self.grid_frame = tk.Frame(body, bg="#1e1e24")
        self.grid_frame.pack(side="left", fill="both", expand=True)

        self.detail_frame = tk.Frame(body, bg="#1e1e24")

        self.back_btn = tk.Button(self.detail_frame, text="< back", command=self.show_grid)
        self.back_btn.pack(anchor="w")

        self.detail_title = tk.Label(self.detail_frame, text="", bg="#1e1e24", fg="white",
                                      font=("Segoe UI", 14, "bold"), justify="left", anchor="w")
        self.detail_title.pack(anchor="w", pady=(5, 0))

        self.detail_sub = tk.Label(self.detail_frame, text="", bg="#1e1e24", fg="#aaaaaa",
                                    justify="left", anchor="w")
        self.detail_sub.pack(anchor="w")

        sections = tk.Frame(self.detail_frame, bg="#1e1e24")
        sections.pack(fill="both", expand=True, pady=10)

        self.link_label = self.make_section(sections, "link quality", 0)
        self.motion_label = self.make_section(sections, "motion / orientation", 1)
        self.presence_label = self.make_section(sections, "presence / human detection", 2)
        self.env_label = self.make_section(sections, "environment", 3)

        chart_frame = tk.Frame(self.detail_frame, bg="#1e1e24")
        chart_frame.pack(fill="x", pady=10)

        tk.Label(chart_frame, text="accel magnitude", bg="#1e1e24", fg="#aaaaaa").pack(anchor="w")
        self.accel_canvas = tk.Canvas(chart_frame, height=60, bg="#26262e", highlightthickness=0)
        self.accel_canvas.pack(fill="x", pady=(0, 8))

        tk.Label(chart_frame, text="distance / voc", bg="#1e1e24", fg="#aaaaaa").pack(anchor="w")
        self.dist_canvas = tk.Canvas(chart_frame, height=60, bg="#26262e", highlightthickness=0)
        self.dist_canvas.pack(fill="x", pady=(0, 8))

        tk.Label(chart_frame, text="rssi", bg="#1e1e24", fg="#aaaaaa").pack(anchor="w")
        self.rssi_canvas = tk.Canvas(chart_frame, height=60, bg="#26262e", highlightthickness=0)
        self.rssi_canvas.pack(fill="x")

        alert_frame = tk.Frame(root, bg="#1e1e24")
        alert_frame.pack(fill="both", padx=10, pady=(0, 10))

        alert_head = tk.Frame(alert_frame, bg="#1e1e24")
        alert_head.pack(fill="x")
        tk.Label(alert_head, text="alerts", bg="#1e1e24", fg="white", font=("Segoe UI", 10, "bold")).pack(side="left")
        tk.Button(alert_head, text="clear", command=self.clear_alerts).pack(side="right")

        self.alert_list = tk.Listbox(alert_frame, height=6, bg="#26262e", fg="white", highlightthickness=0)
        self.alert_list.pack(fill="both", expand=True, pady=(3, 0))

        self.status_label = tk.Label(root, text="", fg="gray", bg="#1e1e24")
        self.status_label.pack(side="bottom", anchor="w", padx=5, pady=5)

        self.refresh_ports()
        self.poll()

    def make_section(self, parent, title, col):
        frame = tk.Frame(parent, bg="#26262e", padx=10, pady=8)
        frame.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 8, 0))
        parent.grid_columnconfigure(col, weight=1)
        tk.Label(frame, text=title, bg="#26262e", fg="#aaaaaa",
                 font=("Segoe UI", 9, "bold")).pack(anchor="w")
        label = tk.Label(frame, text="", bg="#26262e", fg="white", justify="left", anchor="w")
        label.pack(anchor="w", pady=(5, 0))
        return label

    def refresh_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.port_dropdown["values"] = ports
        if ports and not self.port_var.get():
            self.port_var.set(ports[0])

    def connect(self):
        port = self.port_var.get()
        if not port:
            return
        self.conn_status.config(text="connecting to " + port + "...")
        threading.Thread(target=serial_reader, args=(port,), daemon=True).start()
        self.conn_status.config(text="listening on " + port)

    def toggle_demo(self):
        global demo_sim
        if demo_sim is None:
            demo_sim = DemoSimulator()
        if demo_sim.running:
            demo_sim.stop()
            self.demo_btn.config(text="start demo")
        else:
            demo_sim.start()
            self.demo_btn.config(text="stop demo")

    def clear_alerts(self):
        alerts.clear()
        self.alert_list.delete(0, tk.END)

    def ingest(self, node_id, meta, payload):
        if node_id not in nodes:
            nodes[node_id] = new_node_entry()

        node = nodes[node_id]
        prev_status = node["status"]
        node["meta"] = meta
        node["payload"] = payload
        node["last_seen"] = time.time()
        node["packet_count"] += 1
        node["demo"] = node_id.startswith("DEMO-")
        node["status"] = STATUS_ONLINE

        try:
            if "X gyro" in payload:
                x = float(payload.get("X gyro", 0))
                y = float(payload.get("Y gyro", 0))
                z = float(payload.get("Z gyro", 0))
            else:
                x = float(payload.get("X", 0))
                y = float(payload.get("Y", 0))
                z = float(payload.get("Z", 0))
            mag = math.sqrt(x * x + y * y + z * z)
            node["accel_hist"].append(mag)
        except ValueError:
            pass

        try:
            if "VOC" in payload:
                node["dist_hist"].append(float(payload.get("VOC", 0)))
            else:
                node["dist_hist"].append(float(payload.get("D", 0)))
        except ValueError:
            pass

        try:
            rssi_val = float(meta.get("RSSI", 0))
            node["rssi_hist"].append(rssi_val)
            if rssi_val < RSSI_WARN:
                push_alert("warning", node_id, "weak signal, rssi %.0f dBm" % rssi_val)
        except ValueError:
            pass

        h = payload.get("H", "0")
        if h == "1" and node["prev_h"] != "1":
            push_alert("critical", node_id, "human detected")
        node["prev_h"] = h

        if prev_status != STATUS_ONLINE and prev_status != STATUS_OFFLINE:
            pass
        if prev_status == STATUS_OFFLINE and node["packet_count"] > 1:
            push_alert("info", node_id, "node back online")

    def sweep_status(self):
        for node_id, node in nodes.items():
            prev = node["status"]
            new_status = compute_status(node["last_seen"])
            if new_status != prev:
                node["status"] = new_status
                if new_status == STATUS_STALE:
                    push_alert("warning", node_id, "no packets received, node stale")
                elif new_status == STATUS_OFFLINE:
                    push_alert("critical", node_id, "node offline")

    def render_alerts(self):
        self.alert_list.delete(0, tk.END)
        colors = {"critical": "#e74c3c", "warning": "#f1c40f", "info": "#7f8c8d"}
        for a in reversed(alerts[-100:]):
            ts = time.strftime("%H:%M:%S", time.localtime(a["time"]))
            entry = "%s  [%s]  %s - %s" % (ts, a["level"].upper(), a["node"], a["text"])
            self.alert_list.insert(tk.END, entry)
            self.alert_list.itemconfig(tk.END, fg=colors.get(a["level"], "white"))

    def poll(self):
        got_packet = False
        while not data_queue.empty():
            line = data_queue.get()
            result = parse_line(line)
            if result is None:
                continue
            node_id, meta, payload = result
            self.ingest(node_id, meta, payload)
            self.update_card(node_id)
            got_packet = True

        self.sweep_status()

        for node_id in nodes:
            self.update_card(node_id)

        if self.current_node and self.current_node in nodes:
            self.show_detail(self.current_node)

        online = sum(1 for n in nodes.values() if n["status"] == STATUS_ONLINE)
        self.summary_label.config(text="nodes: %d   online: %d   alerts: %d" %
                                   (len(nodes), online, len(alerts)))
        self.render_alerts()

        if got_packet:
            self.status_label.config(text="last packet: " + time.strftime("%H:%M:%S"))

        self.root.after(300, self.poll)

    def update_card(self, node_id):
        node = nodes[node_id]

        if node_id not in self.cards:
            idx = len(self.cards)
            row = idx // 4
            col = idx % 4
            frame = tk.Frame(self.grid_frame, bg="#26262e", padx=10, pady=8, cursor="hand2")
            frame.grid(row=row, column=col, padx=5, pady=5, sticky="nsew")
            frame.bind("<Button-1>", lambda e, n=node_id: self.show_detail(n))

            dot = tk.Canvas(frame, width=12, height=12, bg="#26262e", highlightthickness=0)
            dot.pack(anchor="w")
            dot_id = dot.create_oval(2, 2, 10, 10, fill="#888888", outline="")

            title = tk.Label(frame, text=node_id, bg="#26262e", fg="white",
                              font=("Segoe UI", 11, "bold"), anchor="w")
            title.pack(anchor="w", pady=(4, 0))

            sub = tk.Label(frame, text="", bg="#26262e", fg="#aaaaaa", anchor="w")
            sub.pack(anchor="w")

            flags = tk.Label(frame, text="", bg="#26262e", fg="#e74c3c", anchor="w",
                              font=("Segoe UI", 9, "bold"))
            flags.pack(anchor="w", pady=(4, 0))

            for w in (frame, title, sub, flags):
                w.bind("<Button-1>", lambda e, n=node_id: self.show_detail(n))

            self.cards[node_id] = {
                "frame": frame, "dot": dot, "dot_id": dot_id,
                "sub": sub, "flags": flags,
            }

        card = self.cards[node_id]
        color = STATUS_COLORS.get(node["status"], "#888888")
        card["dot"].itemconfig(card["dot_id"], fill=color)

        age = int(time.time() - node["last_seen"])
        card["sub"].config(text="%s   %ds ago" % (node["status"], age))

        flags = []
        if "Temp" in node["payload"]:
            flags.append("ENV")
        else:
            if node["payload"].get("H") == "1":
                flags.append("HUMAN")
            if node["payload"].get("P") == "1":
                flags.append("presence")
            if node["payload"].get("M") == "1":
                flags.append("motion")
        card["flags"].config(text="  ".join(flags))

    def draw_sparkline(self, canvas, values, color):
        canvas.delete("all")
        w = canvas.winfo_width()
        h = canvas.winfo_height()
        if w <= 1 or len(values) < 2:
            return
        lo = min(values)
        hi = max(values)
        span = hi - lo if hi != lo else 1
        step = w / (len(values) - 1)
        points = []
        for i, v in enumerate(values):
            x = i * step
            y = h - ((v - lo) / span) * (h - 6) - 3
            points.append((x, y))
        for i in range(len(points) - 1):
            canvas.create_line(points[i][0], points[i][1], points[i + 1][0], points[i + 1][1],
                                fill=color, width=2)

    def show_detail(self, node_id):
        self.current_node = node_id
        node = nodes[node_id]
        payload = node["payload"]
        meta = node["meta"]

        title = node_id
        if node["demo"]:
            title += "   [SIMULATED]"
        self.detail_title.config(text=title)

        self.detail_sub.config(
            text="status: %s   last seen: %s   packets: %d" % (
                node["status"],
                time.strftime("%H:%M:%S", time.localtime(node["last_seen"])),
                node["packet_count"],
            )
        )

        self.link_label.config(text="rssi: %s dBm\nsnr: %s dB" % (
            meta.get("RSSI", "?"), meta.get("SNR", "?")))

        if "Temp" in payload:
            self.motion_label.config(text="x: %s\ny: %s\nz: %s\nmotion: n/a" % (
                payload.get("X gyro", "?"), payload.get("Y gyro", "?"), payload.get("Z gyro", "?")))
            self.presence_label.config(text="presence: n/a\ndistance: n/a\nhuman: n/a")
            self.env_label.config(text="temp: %s C\npressure: %s hPa\nhumidity: %s %%\ngas temp: %s C\nvoc: %s" % (
                payload.get("Temp", "?"), payload.get("Pressure", "?"), payload.get("Humidity", "?"),
                payload.get("Gas temp", "?"), payload.get("VOC", "?")
            ))
        else:
            self.motion_label.config(text="x: %s\ny: %s\nz: %s\nmotion: %s" % (
                payload.get("X", "?"), payload.get("Y", "?"), payload.get("Z", "?"),
                "yes" if payload.get("M") == "1" else "no"))
            self.presence_label.config(text="presence: %s\ndistance: %s\nhuman: %s" % (
                "yes" if payload.get("P") == "1" else "no",
                payload.get("D", "?"),
                "YES" if payload.get("H") == "1" else "no"))
            self.env_label.config(text="temp: n/a\npressure: n/a\nhumidity: n/a\ngas temp: n/a\nvoc: n/a")

        self.grid_frame.pack_forget()
        self.detail_frame.pack(fill="both", expand=True)

        self.draw_sparkline(self.accel_canvas, list(node["accel_hist"]), "#3498db")
        self.draw_sparkline(self.dist_canvas, list(node["dist_hist"]), "#9b59b6")
        self.draw_sparkline(self.rssi_canvas, list(node["rssi_hist"]), "#2ecc71")

    def show_grid(self):
        self.current_node = None
        self.detail_frame.pack_forget()
        self.grid_frame.pack(side="left", fill="both", expand=True)


root = tk.Tk()
root.geometry("1100x750")
app = App(root)
root.mainloop()