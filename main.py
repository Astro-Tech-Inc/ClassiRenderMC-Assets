

from panda3d.core import (
    WindowProperties,
    Vec3,
    CardMaker,
    Texture,
    TextNode,
    Filename,
    loadPrcFileData
)
from direct.showbase.ShowBase import ShowBase
from direct.gui.OnscreenText import OnscreenText
from direct.gui.DirectGui import (
    DirectFrame,
    DirectButton,
    DirectLabel,
    DirectEntry,
    DirectSlider
)
from direct.task import Task
import argparse
import json
import math
import os
import socket
import threading
import time

loadPrcFileData("", "window-title ClassiRenderMC")
loadPrcFileData("", "sync-video false")
loadPrcFileData("", "show-frame-rate-meter false")
loadPrcFileData("", "threading-model Cull/Draw")
loadPrcFileData("", "support-threads 1")

BLOCK_AIR = "air"
BLOCK_GRASS = "grass"
BLOCK_STONE = "stone"
BLOCK_WOOD = "wood"

STONE_TEXTURE = "resources/cobblestone.png"
GRASS_SIDE_TEXTURE = "resources/grass.png"
GRASS_TOP_TEXTURE = "resources/grass_top.png"
WOOD_TEXTURE = "resources/wood.png"

SETTINGS_FILE = "settings.json"

FACE_DEFS = [
    ((0, 1, 0), 0, 0, 0),
    ((0, -1, 0), 180, 0, 0),
    ((1, 0, 0), 90, 0, 0),
    ((-1, 0, 0), -90, 0, 0),
    ((0, 0, 1), 0, -90, 0),
    ((0, 0, -1), 0, 90, 0)
]

DEFAULT_SETTINGS = {
    "fov": 75,
    "uiScale": 1.0,
    "mouseSensitivity": 0.14,
    "playerSpeed": 6.0,
    "jumpPower": 8.5,
    "gravityStrength": 22.0,
    "maxRayDistance": 7.0,
    "chatVisibleSeconds": 10,
    "showFps": False
}

SETTING_RANGES = {
    "fov": (60, 110),
    "uiScale": (0.75, 1.6),
    "mouseSensitivity": (0.03, 0.5),
    "playerSpeed": (1, 20),
    "jumpPower": (1, 20),
    "gravityStrength": (1, 40),
    "maxRayDistance": (2, 20),
    "chatVisibleSeconds": (1, 30)
}


def nice_setting_name(key):
    result = ""

    for i, char in enumerate(key):
        if i > 0 and char.isupper():
            result += " "

        result += char

    return result.replace("_", " ").title()


class LanManager:
    DISCOVERY_PORT = 40404
    GAME_PORT = 40405
    DISCOVERY_MAGIC = "CLASSIRENDERMC_LAN_V1"

    def __init__(self, game):
        self.game = game
        self.running = False
        self.hosting = False
        self.client = False
        self.host_ip = ""
        self.game_port = self.GAME_PORT
        self.available_worlds = {}
        self.last_broadcast = 0
        self.last_position_send = 0
        self.server_addr = None
        self.game_socket = None
        self.discovery_socket = None
        self.peers = {}
        self.discovery_listener_running = True

        threading.Thread(target=self.discovery_listener, daemon=True).start()

    def get_local_ip(self):
        return self.game.get_local_ip()

    def make_socket(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except Exception:
            pass

        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(0.25)
        return sock

    def get_broadcast_targets(self):
        local_ip = self.get_local_ip()
        targets = [("255.255.255.255", self.DISCOVERY_PORT)]

        parts = local_ip.split(".")

        if len(parts) == 4:
            targets.append((f"{parts[0]}.{parts[1]}.{parts[2]}.255", self.DISCOVERY_PORT))

        return targets

    def start_host(self):
        self.stop()

        self.running = True
        self.hosting = True
        self.client = False
        self.host_ip = self.get_local_ip()
        self.game_port = self.GAME_PORT
        self.peers = {}

        self.game_socket = self.make_socket()
        self.game_socket.bind(("0.0.0.0", self.game_port))

        threading.Thread(target=self.game_receive_loop, daemon=True).start()

        self.game.show_message(f"LAN opened on {self.host_ip}:{self.game_port}")
        self.game.add_chat_line(f"[System] LAN opened on {self.host_ip}:{self.game_port}")

    def start_client(self, ip, port):
        self.stop()

        self.running = True
        self.hosting = False
        self.client = True
        self.server_addr = (ip, int(port))

        self.game_socket = self.make_socket()
        self.game_socket.bind(("0.0.0.0", 0))

        threading.Thread(target=self.game_receive_loop, daemon=True).start()

        self.send_packet(self.server_addr, {
            "type": "join",
            "username": self.game.username
        })

        self.game.show_message(f"Joining {ip}:{port}")
        self.game.add_chat_line(f"[System] Joining {ip}:{port}")

    def stop(self):
        self.running = False
        self.hosting = False
        self.client = False
        self.server_addr = None
        self.peers = {}

        if self.game_socket:
            try:
                self.game_socket.close()
            except Exception:
                pass

        self.game_socket = None

    def scan_worlds(self):
        self.available_worlds = {}
        scan_socket = None

        try:
            scan_socket = self.make_socket()
            scan_socket.bind(("0.0.0.0", 0))

            packet = {
                "magic": self.DISCOVERY_MAGIC,
                "type": "scan",
                "username": self.game.username
            }

            data = json.dumps(packet).encode("utf-8")

            for target in self.get_broadcast_targets():
                try:
                    scan_socket.sendto(data, target)
                except Exception:
                    pass

            if self.hosting:
                key = f"{self.get_local_ip()}:{self.game_port}"
                self.available_worlds[key] = {
                    "world_name": "ClassiRenderMC World",
                    "host_username": self.game.username,
                    "ip": self.get_local_ip(),
                    "port": self.game_port
                }

            start = time.time()

            while time.time() - start < 1.5:
                try:
                    data, addr = scan_socket.recvfrom(4096)
                    msg = json.loads(data.decode("utf-8"))

                    if msg.get("magic") != self.DISCOVERY_MAGIC:
                        continue

                    if msg.get("type") != "announce":
                        continue

                    ip = msg.get("ip", addr[0])
                    port = int(msg.get("port", self.GAME_PORT))

                    self.available_worlds[f"{ip}:{port}"] = {
                        "world_name": msg.get("world_name", "ClassiRenderMC World"),
                        "host_username": msg.get("host_username", "Player"),
                        "ip": ip,
                        "port": port
                    }
                except socket.timeout:
                    pass
                except Exception:
                    pass

        except Exception as e:
            print("LAN scan error:", e)

        if scan_socket:
            try:
                scan_socket.close()
            except Exception:
                pass

    def discovery_listener(self):
        try:
            self.discovery_socket = self.make_socket()
            self.discovery_socket.bind(("0.0.0.0", self.DISCOVERY_PORT))
            print(f"LAN discovery listening on UDP {self.DISCOVERY_PORT}")
        except Exception as e:
            print("LAN discovery failed:", e)
            return

        while self.discovery_listener_running:
            try:
                data, addr = self.discovery_socket.recvfrom(4096)
                msg = json.loads(data.decode("utf-8"))

                if msg.get("magic") != self.DISCOVERY_MAGIC:
                    continue

                if msg.get("type") == "scan" and self.hosting:
                    self.send_discovery_announce(addr)

                if msg.get("type") == "announce":
                    ip = msg.get("ip", addr[0])
                    port = int(msg.get("port", self.GAME_PORT))

                    self.available_worlds[f"{ip}:{port}"] = {
                        "world_name": msg.get("world_name", "ClassiRenderMC World"),
                        "host_username": msg.get("host_username", "Player"),
                        "ip": ip,
                        "port": port
                    }
            except socket.timeout:
                pass
            except Exception:
                pass

    def send_discovery_announce(self, addr=None):
        if not self.hosting:
            return

        packet = {
            "magic": self.DISCOVERY_MAGIC,
            "type": "announce",
            "world_name": "ClassiRenderMC World",
            "host_username": self.game.username,
            "ip": self.get_local_ip(),
            "port": self.game_port
        }

        data = json.dumps(packet).encode("utf-8")

        try:
            if addr:
                self.discovery_socket.sendto(data, addr)
            else:
                for target in self.get_broadcast_targets():
                    try:
                        self.discovery_socket.sendto(data, target)
                    except Exception:
                        pass
        except Exception:
            pass

    def send_packet(self, addr, packet):
        if not self.game_socket:
            return

        try:
            self.game_socket.sendto(json.dumps(packet).encode("utf-8"), addr)
        except Exception:
            pass

    def broadcast_packet(self, packet):
        if self.hosting:
            for addr in list(self.peers.keys()):
                self.send_packet(addr, packet)

        if self.client and self.server_addr:
            self.send_packet(self.server_addr, packet)

    def find_peer_by_username(self, username):
        wanted = username.lower()

        for addr, peer_username in self.peers.items():
            if peer_username.lower() == wanted:
                return addr

        return None

    def send_chat(self, message, target_username=None):
        message = message.strip()

        if not message:
            return

        packet = {
            "type": "chat",
            "username": self.game.username,
            "message": message,
            "to": target_username
        }

        if not self.running:
            self.game.add_chat_line("[System] Open or join a LAN world first.")
            return

        if self.hosting:
            self.route_chat_packet(packet, None)
            return

        if self.client and self.server_addr:
            self.send_packet(self.server_addr, packet)

    def route_chat_packet(self, packet, source_addr):
        username = packet.get("username", "Player")
        message = packet.get("message", "")
        target = packet.get("to", None)

        if target:
            private_packet = {
                "type": "chat",
                "username": username,
                "message": message,
                "to": target,
                "private": True
            }

            if target.lower() == self.game.username.lower():
                self.game.receive_chat_message(username, message, private=True, target=target)

                if source_addr:
                    self.send_packet(source_addr, private_packet)

                return

            target_addr = self.find_peer_by_username(target)

            if not target_addr:
                if source_addr:
                    self.send_packet(source_addr, {
                        "type": "chat",
                        "username": "System",
                        "message": f"User '{target}' was not found.",
                        "to": None,
                        "private": False
                    })
                else:
                    self.game.add_chat_line(f"[System] User '{target}' was not found.")

                return

            self.send_packet(target_addr, private_packet)

            if source_addr:
                self.send_packet(source_addr, private_packet)
            else:
                self.game.receive_chat_message(username, message, private=True, target=target)

            return

        public_packet = {
            "type": "chat",
            "username": username,
            "message": message,
            "to": None,
            "private": False
        }

        self.game.receive_chat_message(username, message, private=False)

        for peer_addr in list(self.peers.keys()):
            if peer_addr != source_addr:
                self.send_packet(peer_addr, public_packet)

    def game_receive_loop(self):
        while self.running:
            try:
                data, addr = self.game_socket.recvfrom(65535)
                packet = json.loads(data.decode("utf-8"))
                self.handle_game_packet(packet, addr)
            except socket.timeout:
                pass
            except Exception:
                pass

    def handle_game_packet(self, packet, addr):
        packet_type = packet.get("type", "")

        if packet_type == "join" and self.hosting:
            username = packet.get("username", "Player")
            self.peers[addr] = username

            self.send_packet(addr, {
                "type": "welcome",
                "username": self.game.username,
                "blocks": [[x, y, z, block] for (x, y, z), block in self.game.blocks.items()]
            })

            self.game.show_message(f"{username} joined LAN")
            self.game.add_chat_line(f"[System] {username} joined LAN")

            join_packet = {
                "type": "chat",
                "username": "System",
                "message": f"{username} joined LAN",
                "to": None,
                "private": False
            }

            for peer_addr in list(self.peers.keys()):
                if peer_addr != addr:
                    self.send_packet(peer_addr, join_packet)

        elif packet_type == "welcome" and self.client:
            blocks = packet.get("blocks", None)

            if blocks:
                new_blocks = {}

                for item in blocks:
                    x, y, z, block = item
                    new_blocks[(int(x), int(y), int(z))] = block

                self.game.blocks = new_blocks
                self.game.rebuild_world()

            self.game.show_message("Joined LAN world")
            self.game.add_chat_line("[System] Joined LAN world")

        elif packet_type == "chat":
            if self.hosting:
                self.route_chat_packet(packet, addr)
                return

            username = packet.get("username", "Player")
            message = packet.get("message", "")
            private = bool(packet.get("private", False))
            target = packet.get("to", None)

            self.game.receive_chat_message(username, message, private=private, target=target)

        elif packet_type == "pos":
            username = packet.get("username", "Player")

            if username == self.game.username:
                return

            self.game.remote_players[username] = {
                "pos": [
                    float(packet.get("x", 0)),
                    float(packet.get("y", 0)),
                    float(packet.get("z", 0))
                ],
                "last_seen": time.time()
            }

            if self.hosting:
                for peer_addr in list(self.peers.keys()):
                    if peer_addr != addr:
                        self.send_packet(peer_addr, packet)

        elif packet_type == "setblock":
            x = int(packet.get("x"))
            y = int(packet.get("y"))
            z = int(packet.get("z"))
            block = packet.get("block")

            if block == BLOCK_AIR:
                self.game.blocks.pop((x, y, z), None)
            else:
                self.game.blocks[(x, y, z)] = block

            self.game.rebuild_block_and_neighbors(x, y, z)

            if self.hosting:
                for peer_addr in list(self.peers.keys()):
                    if peer_addr != addr:
                        self.send_packet(peer_addr, packet)

    def send_position(self):
        pos = self.game.playerPos

        packet = {
            "type": "pos",
            "username": self.game.username,
            "x": pos.x,
            "y": pos.y,
            "z": pos.z
        }

        self.broadcast_packet(packet)

    def send_block_update(self, x, y, z, block):
        packet = {
            "type": "setblock",
            "x": x,
            "y": y,
            "z": z,
            "block": block
        }

        self.broadcast_packet(packet)

    def tick(self):
        now = time.time()

        if self.hosting and now - self.last_broadcast > 1.0:
            self.send_discovery_announce()
            self.last_broadcast = now

        if self.running and now - self.last_position_send > 0.05:
            self.send_position()
            self.last_position_send = now


class ClassiRenderMC(ShowBase):
    def __init__(self, username="Player"):
        super().__init__()

        self.username = self.clean_username(username)
        self.disableMouse()

        self.settings = self.load_settings()

        self.worldSize = 24
        self.grassDepth = 2
        self.cobblestoneDepth = 10
        self.worldTopZ = 0
        self.worldDepth = self.grassDepth + self.cobblestoneDepth

        self.playerHeight = 1.8
        self.playerRadius = 0.34

        self.playerSpeed = float(self.settings.get("playerSpeed", 6.0))
        self.jumpPower = float(self.settings.get("jumpPower", 8.5))
        self.gravityStrength = float(self.settings.get("gravityStrength", 22.0))
        self.mouseSensitivity = float(self.settings.get("mouseSensitivity", 0.14))
        self.maxRayDistance = float(self.settings.get("maxRayDistance", 7.0))
        self.chatVisibleSeconds = float(self.settings.get("chatVisibleSeconds", 10))
        self.showFps = bool(self.settings.get("showFps", False))
        self.fov = float(self.settings.get("fov", 75))
        self.uiScale = float(self.settings.get("uiScale", 1.0))

        self.rayStep = 0.03
        self.maxDeltaTime = 0.05

        self.playerPos = Vec3(0, -8, 3)
        self.velocityZ = 0.0
        self.onGround = False

        self.keys = {}
        self.blocks = {}
        self.blockNodes = {}
        self.remote_players = {}
        self.remote_player_nodes = {}
        self.remote_player_names = {}

        self.menuOpen = False
        self.menuFrame = None
        self.lanWorldsFrame = None
        self.optionsFrame = None
        self.optionsPage = 0
        self.optionWidgets = {}

        self.messageTimer = 0

        self.chatOpen = False
        self.chatEntry = None
        self.chatLines = []
        self.chatVisibleTimer = 0.0
        self.chatText = None

        self.lan = LanManager(self)

        self.load_textures()
        self.setup_window()
        self.setup_controls()
        self.make_world()
        self.rebuild_world()
        self.create_ui()

        self.taskMgr.add(self.update, "update")
        self.taskMgr.add(self.lan_update_task, "lan_update_task")

    def ui(self, value):
        return value * self.uiScale

    def load_settings(self):
        settings = dict(DEFAULT_SETTINGS)

        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as file:
                    loaded = json.load(file)

                if isinstance(loaded, dict):
                    settings.update(loaded)
            except Exception as e:
                print("Failed to read settings.json:", e)

        self.save_settings_file(settings)
        return settings

    def save_settings_file(self, settings=None):
        if settings is None:
            settings = self.settings

        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as file:
                json.dump(settings, file, indent=4)
        except Exception as e:
            print("Failed to save settings.json:", e)

    def apply_setting(self, key, value):
        self.settings[key] = value

        if key == "fov":
            self.fov = float(value)
            self.camLens.setFov(self.fov)

        elif key == "uiScale":
            self.uiScale = float(value)

        elif key == "mouseSensitivity":
            self.mouseSensitivity = float(value)

        elif key == "playerSpeed":
            self.playerSpeed = float(value)

        elif key == "jumpPower":
            self.jumpPower = float(value)

        elif key == "gravityStrength":
            self.gravityStrength = float(value)

        elif key == "maxRayDistance":
            self.maxRayDistance = float(value)

        elif key == "chatVisibleSeconds":
            self.chatVisibleSeconds = float(value)

        elif key == "showFps":
            self.showFps = bool(value)

            if not self.showFps and hasattr(self, "fpsText"):
                self.fpsText.setText("")

        self.save_settings_file()

    def clean_username(self, username):
        clean = ""

        for c in username:
            if c.isalnum() or c == "_":
                clean += c

        if not clean:
            clean = "Player"

        return clean[:16]

    def get_local_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def setup_window(self):
        self.win.setClearColor((0.45, 0.75, 1.0, 1))
        self.camLens.setNearFar(0.01, 500)
        self.camLens.setFov(self.fov)

        props = WindowProperties()
        props.setCursorHidden(True)
        props.setMouseMode(WindowProperties.M_relative)
        self.win.requestProperties(props)

    def setup_controls(self):
        for key in ["w", "a", "s", "d", "space"]:
            self.accept(key, self.set_key, [key, True])
            self.accept(key + "-up", self.set_key, [key, False])

        self.accept("mouse1", self.break_block)
        self.accept("mouse3", self.place_block)
        self.accept("escape", self.toggle_menu)
        self.accept("f1", self.take_screenshot)
        self.accept("f3", self.toggle_fps)
        self.accept("t", self.open_chat)

    def set_key(self, key, value):
        self.keys[key] = value

    def load_texture(self, path):
        tex = self.loader.loadTexture(path)

        if hasattr(Texture, "FTNearest"):
            tex.setMagfilter(Texture.FTNearest)
            tex.setMinfilter(Texture.FTNearest)
        else:
            tex.setMagfilter(Texture.FT_nearest)
            tex.setMinfilter(Texture.FT_nearest)

        return tex

    def load_textures(self):
        self.stoneTexture = self.load_texture(STONE_TEXTURE)
        self.grassSideTexture = self.load_texture(GRASS_SIDE_TEXTURE)
        self.grassTopTexture = self.load_texture(GRASS_TOP_TEXTURE)
        self.woodTexture = self.load_texture(WOOD_TEXTURE)

    def make_world(self):
        half = self.worldSize // 2

        for x in range(-half, half):
            for y in range(-half, half):
                for i in range(self.worldDepth):
                    z = self.worldTopZ - i

                    if i < self.grassDepth:
                        block = BLOCK_GRASS
                    else:
                        block = BLOCK_STONE

                    self.blocks[(x, y, z)] = block

        for z in range(1, 6):
            self.blocks[(4, 5, z)] = BLOCK_STONE
            self.blocks[(5, 5, z)] = BLOCK_STONE
            self.blocks[(6, 5, z)] = BLOCK_STONE

        for z in range(1, 8):
            self.blocks[(-5, 3, z)] = BLOCK_WOOD

        for i in range(5):
            self.blocks[(-2 + i, 8, 1 + i)] = BLOCK_GRASS

    def get_texture_for_face(self, block, direction):
        dx, dy, dz = direction

        if block == BLOCK_WOOD:
            return self.woodTexture

        if block == BLOCK_STONE:
            return self.stoneTexture

        if block == BLOCK_GRASS:
            if dz == 1:
                return self.grassTopTexture

            if dz == -1:
                return self.stoneTexture

            return self.grassSideTexture

        return self.stoneTexture

    def create_face(self, parent, x, y, z, direction, h, p, r, block):
        cm = CardMaker("face")
        cm.setFrame(-0.5, 0.5, -0.5, 0.5)

        face = parent.attachNewNode(cm.generate())
        dx, dy, dz = direction

        face.setPos(x + 0.5 + dx * 0.5, y + 0.5 + dy * 0.5, z + 0.5 + dz * 0.5)
        face.setHpr(h, p, r)
        face.setTexture(self.get_texture_for_face(block, direction))
        face.setTwoSided(True)

    def create_block_node(self, x, y, z, block):
        node = self.render.attachNewNode(f"block-{x}-{y}-{z}")

        for direction, h, p, r in FACE_DEFS:
            dx, dy, dz = direction

            if (x + dx, y + dy, z + dz) not in self.blocks:
                self.create_face(node, x, y, z, direction, h, p, r, block)

        self.blockNodes[(x, y, z)] = node

    def rebuild_world(self):
        for node in self.blockNodes.values():
            node.removeNode()

        self.blockNodes.clear()

        for (x, y, z), block in self.blocks.items():
            self.create_block_node(x, y, z, block)

    def rebuild_block_and_neighbors(self, x, y, z):
        positions = [(x, y, z)]

        for direction, _, _, _ in FACE_DEFS:
            dx, dy, dz = direction
            positions.append((x + dx, y + dy, z + dz))

        for pos in positions:
            node = self.blockNodes.pop(pos, None)

            if node:
                node.removeNode()

        for pos in positions:
            if pos in self.blocks:
                bx, by, bz = pos
                self.create_block_node(bx, by, bz, self.blocks[pos])

    def create_ui(self):
        self.crosshair = OnscreenText(
            text="+",
            pos=(0, 0),
            scale=0.055,
            fg=(1, 1, 1, 1),
            align=TextNode.ACenter
        )

        self.usernameText = OnscreenText(
            text=f"ClassiRenderMC | {self.username}",
            pos=(-1.3, 0.94),
            scale=0.04,
            fg=(1, 1, 1, 1),
            align=TextNode.ALeft
        )

        self.messageText = OnscreenText(
            text="",
            pos=(0, 0.82),
            scale=0.045,
            fg=(1, 1, 1, 1),
            align=TextNode.ACenter,
            mayChange=True
        )

        self.chatText = OnscreenText(
            text="",
            pos=(-1.28, -0.55),
            scale=0.038,
            fg=(1, 1, 1, 1),
            align=TextNode.ALeft,
            mayChange=True
        )

        self.fpsText = OnscreenText(
            text="",
            pos=(1.25, 0.94),
            scale=0.04,
            fg=(1, 1, 1, 1),
            align=TextNode.ARight,
            mayChange=True
        )

    def show_message(self, text):
        self.messageText.setText(text)
        self.messageTimer = 3.0
        print(text)

    def add_chat_line(self, text):
        self.chatLines.append(text)

        if len(self.chatLines) > 50:
            self.chatLines = self.chatLines[-50:]

        self.chatVisibleTimer = self.chatVisibleSeconds
        self.update_chat_text()

    def update_chat_text(self):
        if not self.chatText:
            return

        if self.chatOpen:
            self.chatText.setText("\n".join(self.chatLines[-12:]))
            return

        if self.chatVisibleTimer > 0:
            self.chatText.setText("\n".join(self.chatLines[-8:]))
            return

        self.chatText.setText("")

    def receive_chat_message(self, username, message, private=False, target=None):
        if private:
            if username == self.username:
                self.add_chat_line(f"[Whisper to {target}] {message}")
            else:
                self.add_chat_line(f"[Whisper from {username}] {message}")
        else:
            self.add_chat_line(f"<{username}> {message}")

    def open_chat(self):
        if self.menuOpen or self.chatOpen:
            return

        self.chatOpen = True
        self.update_chat_text()

        props = WindowProperties()
        props.setCursorHidden(False)
        props.setMouseMode(WindowProperties.M_absolute)
        self.win.requestProperties(props)

        self.chatEntry = DirectEntry(
            text="",
            scale=0.05,
            pos=(-1.25, 0, -0.88),
            width=48,
            numLines=1,
            focus=1,
            command=self.submit_chat,
            frameColor=(0, 0, 0, 0.8),
            text_fg=(1, 1, 1, 1),
            initialText=""
        )

        self.accept("escape", self.close_chat)

    def close_chat(self):
        if not self.chatOpen:
            return

        self.chatOpen = False

        if self.chatEntry:
            self.chatEntry.destroy()
            self.chatEntry = None

        self.update_chat_text()

        props = WindowProperties()
        props.setCursorHidden(True)
        props.setMouseMode(WindowProperties.M_relative)
        self.win.requestProperties(props)

        self.ignore("escape")
        self.accept("escape", self.toggle_menu)

    def submit_chat(self, text):
        message = text.strip()
        self.close_chat()

        if not message:
            return

        if message.startswith("/w "):
            parts = message.split(" ", 2)

            if len(parts) < 3:
                self.add_chat_line("[System] Usage: /w username message")
                return

            target_username = parts[1].strip()
            private_message = parts[2].strip()

            if not target_username or not private_message:
                self.add_chat_line("[System] Usage: /w username message")
                return

            self.lan.send_chat(private_message, target_username)
            return

        self.lan.send_chat(message)

    def toggle_fps(self):
        self.apply_setting("showFps", not self.showFps)

    def take_screenshot(self):
        folder = "screenshots"
        os.makedirs(folder, exist_ok=True)

        filename = time.strftime("ClassiRenderMC_%Y-%m-%d_%H-%M-%S.png")
        path = os.path.join(folder, filename)

        self.win.saveScreenshot(Filename.fromOsSpecific(path))
        self.show_message("Screenshot saved")

    def toggle_menu(self):
        if self.chatOpen:
            self.close_chat()
            return

        if self.menuOpen:
            self.close_menu()
        else:
            self.open_menu()

    def make_menu_button(self, text, y, command, extra_args=None):
        if extra_args is None:
            extra_args = []

        return DirectButton(
            parent=self.menuFrame,
            text=text,
            scale=self.ui(0.065),
            pos=(0, 0, y),
            command=command,
            extraArgs=extra_args,
            frameSize=(-4.8, 4.8, -0.50, 0.50),
            frameColor=(0.20, 0.20, 0.20, 1),
            relief=1,
            text_fg=(1, 1, 1, 1),
            text_scale=(0.9, 0.9)
        )

    def open_menu(self):
        self.menuOpen = True

        props = WindowProperties()
        props.setCursorHidden(False)
        props.setMouseMode(WindowProperties.M_absolute)
        self.win.requestProperties(props)

        self.menuFrame = DirectFrame(
            frameColor=(0, 0, 0, 0.82),
            frameSize=(-0.72, 0.72, -0.82, 0.82),
            pos=(0, 0, 0)
        )

        DirectLabel(
            parent=self.menuFrame,
            text="Game Menu",
            scale=self.ui(0.09),
            pos=(0, 0, 0.64),
            text_fg=(1, 1, 1, 1),
            frameColor=(0, 0, 0, 0)
        )

        self.make_menu_button("Back to Game", 0.42, self.close_menu)
        self.make_menu_button("Open to LAN", 0.24, self.open_to_lan)
        self.make_menu_button("Available LAN Worlds", 0.06, self.show_available_lan_worlds)
        self.make_menu_button("Options", -0.12, self.open_options_menu)
        self.make_menu_button("Close LAN", -0.30, self.close_lan)
        self.make_menu_button("Quit Game", -0.54, self.userExit)

    def close_menu(self):
        self.menuOpen = False

        if self.menuFrame:
            self.menuFrame.destroy()
            self.menuFrame = None

        self.close_lan_worlds_menu()
        self.close_options_menu()

        props = WindowProperties()
        props.setCursorHidden(True)
        props.setMouseMode(WindowProperties.M_relative)
        self.win.requestProperties(props)

    def get_numeric_range(self, key, value):
        if key in SETTING_RANGES:
            return SETTING_RANGES[key]

        value = float(value)

        if value <= 1:
            return 0, 1

        return 0, max(value * 2, 10)

    def open_options_menu(self):
        if self.optionsFrame:
            self.optionsFrame.destroy()
            self.optionsFrame = None

        self.optionWidgets = {}

        self.optionsFrame = DirectFrame(
            frameColor=(0, 0, 0, 0.92),
            frameSize=(-1.05, 1.05, -0.82, 0.82),
            pos=(0, 0, 0)
        )

        DirectLabel(
            parent=self.optionsFrame,
            text="Options",
            scale=self.ui(0.085),
            pos=(0, 0, 0.68),
            text_fg=(1, 1, 1, 1),
            frameColor=(0, 0, 0, 0)
        )

        keys = list(self.settings.keys())
        per_page = 4
        page_count = max(1, math.ceil(len(keys) / per_page))
        self.optionsPage = max(0, min(self.optionsPage, page_count - 1))

        start = self.optionsPage * per_page
        visible_keys = keys[start:start + per_page]

        y = 0.44

        for key in visible_keys:
            value = self.settings[key]
            label = nice_setting_name(key)

            DirectLabel(
                parent=self.optionsFrame,
                text=label,
                scale=self.ui(0.052),
                pos=(-0.78, 0, y + 0.04),
                text_fg=(1, 1, 1, 1),
                text_align=TextNode.ALeft,
                frameColor=(0, 0, 0, 0)
            )

            if isinstance(value, bool):
                text = "ON" if value else "OFF"

                button = DirectButton(
                    parent=self.optionsFrame,
                    text=text,
                    scale=self.ui(0.055),
                    pos=(0.56, 0, y + 0.03),
                    command=self.toggle_bool_setting,
                    extraArgs=[key],
                    frameSize=(-1.8, 1.8, -0.50, 0.50),
                    frameColor=(0.20, 0.20, 0.20, 1),
                    text_fg=(1, 1, 1, 1)
                )

                self.optionWidgets[key] = button

            elif isinstance(value, int) or isinstance(value, float):
                min_value, max_value = self.get_numeric_range(key, value)

                value_label = DirectLabel(
                    parent=self.optionsFrame,
                    text=str(round(float(value), 2)),
                    scale=self.ui(0.046),
                    pos=(0.82, 0, y + 0.04),
                    text_fg=(1, 1, 1, 1),
                    frameColor=(0, 0, 0, 0)
                )

                slider = DirectSlider(
                    parent=self.optionsFrame,
                    range=(min_value, max_value),
                    value=float(value),
                    pageSize=0.1,
                    scale=self.ui(0.48),
                    pos=(0.20, 0, y - 0.025),
                    command=self.change_numeric_setting,
                    extraArgs=[key]
                )

                self.optionWidgets[key] = {
                    "slider": slider,
                    "label": value_label
                }

            elif isinstance(value, str):
                entry = DirectEntry(
                    parent=self.optionsFrame,
                    text="",
                    initialText=value,
                    scale=self.ui(0.055),
                    width=14,
                    numLines=1,
                    pos=(0.08, 0, y),
                    command=self.change_string_setting,
                    extraArgs=[key],
                    frameColor=(0.12, 0.12, 0.12, 1),
                    text_fg=(1, 1, 1, 1)
                )

                self.optionWidgets[key] = entry

            else:
                DirectLabel(
                    parent=self.optionsFrame,
                    text="Unsupported",
                    scale=self.ui(0.05),
                    pos=(0.40, 0, y + 0.02),
                    text_fg=(0.8, 0.8, 0.8, 1),
                    frameColor=(0, 0, 0, 0)
                )

            y -= 0.20

        DirectLabel(
            parent=self.optionsFrame,
            text=f"Page {self.optionsPage + 1}/{page_count}",
            scale=self.ui(0.05),
            pos=(0, 0, -0.52),
            text_fg=(0.8, 0.8, 0.8, 1),
            frameColor=(0, 0, 0, 0)
        )

        DirectButton(
            parent=self.optionsFrame,
            text="<",
            scale=self.ui(0.06),
            pos=(-0.32, 0, -0.65),
            command=self.previous_options_page,
            frameSize=(-0.95, 0.95, -0.50, 0.50),
            frameColor=(0.20, 0.20, 0.20, 1),
            text_fg=(1, 1, 1, 1)
        )

        DirectButton(
            parent=self.optionsFrame,
            text="Done",
            scale=self.ui(0.06),
            pos=(0, 0, -0.65),
            command=self.close_options_menu,
            frameSize=(-1.45, 1.45, -0.50, 0.50),
            frameColor=(0.20, 0.20, 0.20, 1),
            text_fg=(1, 1, 1, 1)
        )

        DirectButton(
            parent=self.optionsFrame,
            text=">",
            scale=self.ui(0.06),
            pos=(0.32, 0, -0.65),
            command=self.next_options_page,
            frameSize=(-0.95, 0.95, -0.50, 0.50),
            frameColor=(0.20, 0.20, 0.20, 1),
            text_fg=(1, 1, 1, 1)
        )

    def previous_options_page(self):
        self.optionsPage = max(0, self.optionsPage - 1)
        self.open_options_menu()

    def next_options_page(self):
        page_count = max(1, math.ceil(len(self.settings.keys()) / 4))
        self.optionsPage = min(page_count - 1, self.optionsPage + 1)
        self.open_options_menu()

    def toggle_bool_setting(self, key):
        value = not bool(self.settings.get(key, False))
        self.apply_setting(key, value)
        self.open_options_menu()

    def change_numeric_setting(self, key):
        widget_data = self.optionWidgets.get(key)

        if not widget_data:
            return

        slider = widget_data["slider"]
        label = widget_data["label"]

        value = float(slider["value"])
        old_value = self.settings.get(key)

        if isinstance(old_value, int) and not isinstance(old_value, bool):
            value_to_save = int(round(value))
        else:
            value_to_save = round(value, 3)

        self.apply_setting(key, value_to_save)
        label["text"] = str(round(float(value_to_save), 2))

    def change_string_setting(self, text, key):
        self.apply_setting(key, text)

    def close_options_menu(self):
        if self.optionsFrame:
            self.optionsFrame.destroy()
            self.optionsFrame = None

        self.optionWidgets = {}

    def open_to_lan(self):
        self.lan.start_host()

    def close_lan(self):
        self.lan.stop()
        self.show_message("LAN closed")
        self.add_chat_line("[System] LAN closed")

    def show_available_lan_worlds(self):
        if self.lanWorldsFrame:
            self.lanWorldsFrame.destroy()

        self.lan.scan_worlds()

        self.lanWorldsFrame = DirectFrame(
            frameColor=(0, 0, 0, 0.92),
            frameSize=(-0.95, 0.95, -0.74, 0.74),
            pos=(0, 0, 0)
        )

        DirectLabel(
            parent=self.lanWorldsFrame,
            text="Available LAN Worlds",
            scale=self.ui(0.075),
            pos=(0, 0, 0.58),
            text_fg=(1, 1, 1, 1),
            frameColor=(0, 0, 0, 0)
        )

        worlds = list(self.lan.available_worlds.values())

        if not worlds:
            DirectLabel(
                parent=self.lanWorldsFrame,
                text="No LAN worlds found.\nMake sure another player clicked Open to LAN.",
                scale=self.ui(0.052),
                pos=(0, 0, 0.18),
                text_fg=(1, 1, 1, 1),
                frameColor=(0, 0, 0, 0)
            )
        else:
            y = 0.34

            for world in worlds[:5]:
                name = world.get("world_name", "ClassiRenderMC World")
                host = world.get("host_username", "Player")
                ip = world.get("ip", "127.0.0.1")
                port = world.get("port", 40405)

                DirectButton(
                    parent=self.lanWorldsFrame,
                    text=f"{name} - {host}\n{ip}:{port}",
                    scale=self.ui(0.052),
                    pos=(0, 0, y),
                    command=self.join_lan_world,
                    extraArgs=[ip, port],
                    frameSize=(-6.8, 6.8, -0.62, 0.62),
                    frameColor=(0.20, 0.20, 0.20, 1),
                    text_fg=(1, 1, 1, 1)
                )

                y -= 0.18

        DirectButton(
            parent=self.lanWorldsFrame,
            text="Close",
            scale=self.ui(0.06),
            pos=(0, 0, -0.56),
            command=self.close_lan_worlds_menu,
            frameSize=(-1.6, 1.6, -0.50, 0.50),
            frameColor=(0.20, 0.20, 0.20, 1),
            text_fg=(1, 1, 1, 1)
        )

    def close_lan_worlds_menu(self):
        if self.lanWorldsFrame:
            self.lanWorldsFrame.destroy()
            self.lanWorldsFrame = None

    def join_lan_world(self, ip, port):
        self.close_lan_worlds_menu()
        self.lan.start_client(ip, port)

    def get_placement_block_type(self, z):
        if z > self.worldTopZ:
            return BLOCK_WOOD

        if self.worldTopZ - self.grassDepth < z <= self.worldTopZ:
            return BLOCK_GRASS

        return BLOCK_STONE

    def raycast(self):
        origin = self.camera.getPos(self.render)
        direction = self.camera.getQuat(self.render).getForward()

        last_empty = None
        distance = 0.0

        while distance <= self.maxRayDistance:
            point = origin + direction * distance
            pos = (math.floor(point.x), math.floor(point.y), math.floor(point.z))

            if pos in self.blocks:
                return pos, last_empty

            last_empty = pos
            distance += self.rayStep

        return None, None

    def break_block(self):
        if self.menuOpen or self.chatOpen:
            return

        hit, empty = self.raycast()

        if hit is None:
            return

        self.blocks.pop(hit, None)
        x, y, z = hit
        self.rebuild_block_and_neighbors(x, y, z)
        self.lan.send_block_update(x, y, z, BLOCK_AIR)

    def place_block(self):
        if self.menuOpen or self.chatOpen:
            return

        hit, empty = self.raycast()

        if empty is None:
            return

        if empty in self.blocks:
            return

        x, y, z = empty
        block_type = self.get_placement_block_type(z)

        self.blocks[empty] = block_type
        self.rebuild_block_and_neighbors(x, y, z)
        self.lan.send_block_update(x, y, z, block_type)

    def check_collision(self, pos):
        min_x = math.floor(pos.x - self.playerRadius)
        max_x = math.floor(pos.x + self.playerRadius)
        min_y = math.floor(pos.y - self.playerRadius)
        max_y = math.floor(pos.y + self.playerRadius)
        min_z = math.floor(pos.z)
        max_z = math.floor(pos.z + self.playerHeight)

        for x in range(min_x, max_x + 1):
            for y in range(min_y, max_y + 1):
                for z in range(min_z, max_z + 1):
                    if (x, y, z) in self.blocks:
                        return True

        return False

    def move_axis(self, delta):
        old = Vec3(self.playerPos)
        new = self.playerPos + delta

        if not self.check_collision(new):
            self.playerPos = new
        else:
            self.playerPos = old

    def update_mouse(self):
        if self.menuOpen or self.chatOpen:
            return

        if not self.mouseWatcherNode.hasMouse():
            return

        md = self.win.getPointer(0)
        center_x = self.win.getXSize() // 2
        center_y = self.win.getYSize() // 2

        dx = md.getX() - center_x
        dy = md.getY() - center_y

        self.camera.setH(self.camera.getH() - dx * self.mouseSensitivity)
        self.camera.setP(max(-89, min(89, self.camera.getP() - dy * self.mouseSensitivity)))

        self.win.movePointer(0, center_x, center_y)

    def update_movement(self, dt):
        if self.menuOpen or self.chatOpen:
            return

        forward = self.camera.getQuat(self.render).getForward()
        right = self.camera.getQuat(self.render).getRight()

        forward.z = 0
        right.z = 0

        if forward.length() > 0:
            forward.normalize()

        if right.length() > 0:
            right.normalize()

        move = Vec3(0, 0, 0)

        if self.keys.get("w", False):
            move += forward

        if self.keys.get("s", False):
            move -= forward

        if self.keys.get("d", False):
            move += right

        if self.keys.get("a", False):
            move -= right

        if move.length() > 0:
            move.normalize()
            move *= self.playerSpeed * dt
            self.move_axis(Vec3(move.x, 0, 0))
            self.move_axis(Vec3(0, move.y, 0))

        if self.keys.get("space", False) and self.onGround:
            self.velocityZ = self.jumpPower
            self.onGround = False

        self.velocityZ -= self.gravityStrength * dt
        old_z = self.playerPos.z
        self.move_axis(Vec3(0, 0, self.velocityZ * dt))

        if self.playerPos.z == old_z and self.velocityZ < 0:
            self.onGround = True
            self.velocityZ = 0
        else:
            self.onGround = False

    def update_remote_players(self):
        now = time.time()

        for username in list(self.remote_players.keys()):
            data = self.remote_players[username]

            if now - data.get("last_seen", 0) > 10:
                node = self.remote_player_nodes.pop(username, None)

                if node:
                    node.removeNode()

                self.remote_players.pop(username, None)
                continue

            if username == self.username:
                continue

            pos = data.get("pos", [0, 0, 0])

            if username not in self.remote_player_nodes:
                node = self.render.attachNewNode(f"remote-player-{username}")

                body = self.loader.loadModel("models/box")
                body.reparentTo(node)
                body.setScale(0.35, 0.35, 0.9)
                body.setColor(0.2, 0.45, 1.0, 1)

                name_text = TextNode(f"name-{username}")
                name_text.setText(username)
                name_text.setAlign(TextNode.ACenter)
                name_text.setTextColor(1, 1, 1, 1)

                name_np = node.attachNewNode(name_text)
                name_np.setBillboardPointEye()
                name_np.setScale(0.35)
                name_np.setZ(1.45)

                self.remote_player_nodes[username] = node
                self.remote_player_names[username] = name_np

            node = self.remote_player_nodes[username]
            node.setPos(pos[0], pos[1], pos[2])

    def lan_update_task(self, task):
        self.lan.tick()
        self.update_remote_players()
        return Task.cont

    def update(self, task):
        dt = min(globalClock.getDt(), self.maxDeltaTime)

        self.update_mouse()
        self.update_movement(dt)

        self.camera.setPos(self.playerPos.x, self.playerPos.y, self.playerPos.z + self.playerHeight)

        if self.messageTimer > 0:
            self.messageTimer -= dt

            if self.messageTimer <= 0:
                self.messageText.setText("")

        if self.chatVisibleTimer > 0 and not self.chatOpen:
            self.chatVisibleTimer -= dt

            if self.chatVisibleTimer <= 0:
                self.update_chat_text()

        if self.showFps:
            fps = globalClock.getAverageFrameRate()
            self.fpsText.setText(f"FPS: {fps:.0f}")

        return Task.cont


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", default="Player")
    return parser.parse_args()


def main():
    args = parse_args()
    game = ClassiRenderMC(username=args.username)
    game.run()


if __name__ == "__main__":
    main()



