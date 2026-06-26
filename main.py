from panda3d.core import (
    WindowProperties,
    Vec3,
    CardMaker,
    NodePath,
    Texture,
    TextureStage,
    TextNode,
    loadPrcFileData,
)
from direct.showbase.ShowBase import ShowBase
from direct.gui.OnscreenText import OnscreenText
from direct.gui.DirectGui import (
    DirectFrame,
    DirectButton,
    DirectEntry,
    DirectLabel,
    DirectScrolledFrame,
)
from direct.task import Task
import json
import math
import os


loadPrcFileData("", "threading-model Cull/Draw")
loadPrcFileData("", "support-threads 1")


settingsFilePath = "settings.json"

defaultSettings = {
    "gameTitle": "ClassiRenderMC",
    "windowWidth": 1280,
    "windowHeight": 720,
    "backgroundRed": 0.45,
    "backgroundGreen": 0.75,
    "backgroundBlue": 1.0,
    "worldSize": 24,
    "grassDepth": 2,
    "cobblestoneDepth": 10,
    "worldTopZ": 0,
    "spawnX": 0.0,
    "spawnY": -8.0,
    "playerHeight": 1.8,
    "playerRadius": 0.34,
    "playerSpeed": 6.0,
    "jumpPower": 8.5,
    "gravityStrength": 22.0,
    "mouseSensitivity": 0.14,
    "maxRayDistance": 7.0,
    "rayStep": 0.03,
    "maxDeltaTime": 0.05,
    "cameraNearClip": 0.01,
    "cameraFarClip": 500.0,
    "fpsCounterEnabled": False,
    "fpsUpdateInterval": 0.15,
    "visibleFaceOptimization": True,
    "makeFacesTwoSided": True,
    "testWallEnabled": True,
    "testWallStartX": 4,
    "testWallEndX": 8,
    "testWallY": 5,
    "testWallBottomZ": 1,
    "testWallTopZ": 5,
    "pillarEnabled": True,
    "pillarX": -5,
    "pillarY": 3,
    "pillarBottomZ": 1,
    "pillarTopZ": 7,
    "stairsEnabled": True,
    "grassTopTextureRotation": 0.0,
    "grassSideTextureRotation": 0.0,
    "stoneTextureRotation": 0.0,
    "woodTextureRotation": 0.0,
}


settingTypes = {
    key: type(value)
    for key, value in defaultSettings.items()
}


stoneTexturePath = "resources/cobblestone.png"
grassSideTexturePath = "resources/grass.png"
grassTopTexturePath = "resources/grass_top.png"
woodTexturePath = "resources/wood.png"

fallbackStoneColor = (0.45, 0.45, 0.45, 1)
fallbackGrassSideColor = (0.35, 0.75, 0.25, 1)
fallbackGrassTopColor = (0.25, 0.85, 0.25, 1)
fallbackWoodColor = (0.55, 0.32, 0.12, 1)

blockTypeGrass = "grass"
blockTypeStone = "stone"
blockTypeWood = "wood"

placedAboveGrassType = blockTypeWood
placedOnGrassLevelType = blockTypeGrass
placedBelowGrassType = blockTypeStone

faceFront = "front"
faceBack = "back"
faceRight = "right"
faceLeft = "left"
faceTop = "top"
faceBottom = "bottom"

faceData = [
    (faceFront, (0, -0.5, 0), (0, 0, 0), (0, -1, 0)),
    (faceBack, (0, 0.5, 0), (180, 0, 0), (0, 1, 0)),
    (faceRight, (0.5, 0, 0), (90, 0, 0), (1, 0, 0)),
    (faceLeft, (-0.5, 0, 0), (-90, 0, 0), (-1, 0, 0)),
    (faceTop, (0, 0, 0.5), (0, -90, 0), (0, 0, 1)),
    (faceBottom, (0, 0, -0.5), (0, 90, 0), (0, 0, -1)),
]

neighborOffsets = [
    (0, -1, 0),
    (0, 1, 0),
    (1, 0, 0),
    (-1, 0, 0),
    (0, 0, 1),
    (0, 0, -1),
]


def load_settings():
    settings = defaultSettings.copy()

    if not os.path.exists(settingsFilePath):
        return settings

    try:
        with open(settingsFilePath, "r", encoding="utf-8") as file:
            loaded = json.load(file)

        for key in settings:
            if key in loaded:
                settings[key] = loaded[key]
    except (OSError, json.JSONDecodeError):
        pass

    return settings


def save_settings(settings):
    with open(settingsFilePath, "w", encoding="utf-8") as file:
        json.dump(settings, file, indent=4)


class ClassiRenderMC(ShowBase):
    def __init__(self):
        super().__init__()

        self.settings = load_settings()
        self.disableMouse()

        self.blocks = {}
        self.vertical_speed = 0.0
        self.mouse_locked = True
        self.menu_open = False
        self.show_fps = bool(self.settings["fpsCounterEnabled"])
        self.fps_timer = 0.0
        self.setting_entries = {}

        self.keys = {
            "w": False,
            "a": False,
            "s": False,
            "d": False,
            "space": False,
        }

        self.configure_window()

        self.stone_texture = self.load_texture(stoneTexturePath)
        self.grass_side_texture = self.load_texture(grassSideTexturePath)
        self.grass_top_texture = self.load_texture(grassTopTexturePath)
        self.wood_texture = self.load_texture(woodTexturePath)

        self.make_world()
        self.rebuild_all_visible_blocks()
        self.spawn_player()

        self.make_ui()
        self.make_options_menu()
        self.bind_inputs()
        self.lock_mouse()

        self.taskMgr.add(self.update, "update")

    def value(self, name):
        return self.settings[name]

    def configure_window(self):
        props = WindowProperties()
        props.setTitle(str(self.value("gameTitle")))
        props.setSize(
            int(self.value("windowWidth")),
            int(self.value("windowHeight")),
        )
        props.setCursorHidden(True)
        props.setMouseMode(WindowProperties.M_relative)
        self.win.requestProperties(props)

        self.setBackgroundColor(
            float(self.value("backgroundRed")),
            float(self.value("backgroundGreen")),
            float(self.value("backgroundBlue")),
            1,
        )

        self.camLens.setNearFar(
            float(self.value("cameraNearClip")),
            float(self.value("cameraFarClip")),
        )

    def spawn_player(self):
        spawn_z = (
            int(self.value("worldTopZ"))
            + 0.5
            + float(self.value("playerHeight"))
        )

        self.camera.setPos(
            float(self.value("spawnX")),
            float(self.value("spawnY")),
            spawn_z,
        )

        self.camera.setHpr(0, 0, 0)
        self.vertical_speed = 0.0

    def load_texture(self, path):
        if not os.path.exists(path):
            print(f"WARNING: {path} was not found.")
            return None

        texture = self.loader.loadTexture(path)
        texture.setMagfilter(Texture.FT_nearest)
        texture.setMinfilter(Texture.FT_nearest)

        return texture

    def bind_inputs(self):
        self.accept("escape", self.toggle_options_menu)
        self.accept("f3", self.toggle_fps)
        self.accept("mouse1", self.left_click)
        self.accept("mouse3", self.right_click)

        for key in self.keys:
            self.accept(key, self.set_key, [key, True])
            self.accept(key + "-up", self.set_key, [key, False])

    def set_key(self, key, value):
        if self.menu_open:
            self.keys[key] = False
            return

        self.keys[key] = value

    def left_click(self):
        if self.menu_open:
            return

        if not self.mouse_locked:
            self.lock_mouse()
            return

        self.break_block()

    def right_click(self):
        if self.menu_open:
            return

        if not self.mouse_locked:
            self.lock_mouse()
            return

        self.place_block()

    def lock_mouse(self):
        if self.menu_open:
            return

        self.mouse_locked = True

        props = WindowProperties()
        props.setCursorHidden(True)
        props.setMouseMode(WindowProperties.M_relative)
        self.win.requestProperties(props)

        self.center_mouse()

    def unlock_mouse(self):
        self.mouse_locked = False

        props = WindowProperties()
        props.setCursorHidden(False)
        props.setMouseMode(WindowProperties.M_absolute)
        self.win.requestProperties(props)

    def center_mouse(self):
        if self.win:
            self.win.movePointer(
                0,
                self.win.getXSize() // 2,
                self.win.getYSize() // 2,
            )

    def toggle_fps(self):
        self.show_fps = not self.show_fps
        self.settings["fpsCounterEnabled"] = self.show_fps
        save_settings(self.settings)
        self.update_fps_button()

        if not self.show_fps:
            self.fps_text.setText("")

    def make_ui(self):
        self.crosshair = OnscreenText(
            text="+",
            pos=(0, 0),
            scale=0.08,
            fg=(1, 1, 1, 1),
            mayChange=False,
        )

        self.title_text = OnscreenText(
            text=str(self.value("gameTitle")),
            pos=(-1.28, 0.92),
            scale=0.05,
            fg=(1, 1, 1, 1),
            align=TextNode.ALeft,
            mayChange=True,
        )

        self.help_text = OnscreenText(
            text=(
                "WASD move | Space jump | Left break | "
                "Right place | F3 FPS | Esc options"
            ),
            pos=(0, -0.93),
            scale=0.032,
            fg=(1, 1, 1, 1),
            mayChange=False,
        )

        self.fps_text = OnscreenText(
            text="",
            pos=(1.25, 0.92),
            scale=0.045,
            fg=(1, 1, 1, 1),
            align=TextNode.ARight,
            mayChange=True,
        )

    def make_options_menu(self):
        self.options_frame = DirectFrame(
            frameColor=(0.08, 0.08, 0.08, 0.96),
            frameSize=(-1.2, 1.2, -0.95, 0.95),
            pos=(0, 0, 0),
        )

        DirectLabel(
            parent=self.options_frame,
            text="ClassiRenderMC Options",
            scale=0.075,
            pos=(0, 0, 0.84),
            text_fg=(1, 1, 1, 1),
            frameColor=(0, 0, 0, 0),
        )

        self.fps_button = DirectButton(
            parent=self.options_frame,
            text="",
            scale=0.045,
            frameSize=(-4.3, 4.3, -0.8, 0.8),
            pos=(-0.72, 0, 0.7),
            command=self.toggle_fps,
        )

        DirectButton(
            parent=self.options_frame,
            text="Resume",
            scale=0.045,
            frameSize=(-2.7, 2.7, -0.8, 0.8),
            pos=(0, 0, -0.72),
            command=self.close_options_menu,
        )

        DirectButton(
            parent=self.options_frame,
            text="Apply & Save",
            scale=0.045,
            frameSize=(-3.3, 3.3, -0.8, 0.8),
            pos=(-0.57, 0, -0.83),
            command=self.apply_settings_from_menu,
        )

        DirectButton(
            parent=self.options_frame,
            text="Reset Defaults",
            scale=0.045,
            frameSize=(-3.3, 3.3, -0.8, 0.8),
            pos=(0.18, 0, -0.83),
            command=self.reset_default_settings,
        )

        DirectButton(
            parent=self.options_frame,
            text="Quit Game",
            scale=0.045,
            frameSize=(-2.8, 2.8, -0.8, 0.8),
            pos=(0.82, 0, -0.83),
            command=self.quit_game,
        )

        self.status_text = DirectLabel(
            parent=self.options_frame,
            text="",
            scale=0.035,
            pos=(0, 0, -0.64),
            text_fg=(0.8, 1, 0.8, 1),
            frameColor=(0, 0, 0, 0),
        )

        self.settings_scroll = DirectScrolledFrame(
            parent=self.options_frame,
            frameColor=(0.13, 0.13, 0.13, 1),
            frameSize=(-1.05, 1.05, -0.58, 0.58),
            canvasSize=(-1.0, 1.0, -5.3, 0.55),
            scrollBarWidth=0.04,
            pos=(0, 0, 0.02),
        )

        canvas = self.settings_scroll.getCanvas()

        editable_settings = [
            "mouseSensitivity",
            "playerSpeed",
            "jumpPower",
            "gravityStrength",
            "playerHeight",
            "playerRadius",
            "worldSize",
            "grassDepth",
            "cobblestoneDepth",
            "worldTopZ",
            "spawnX",
            "spawnY",
            "maxRayDistance",
            "rayStep",
            "cameraNearClip",
            "cameraFarClip",
            "maxDeltaTime",
            "fpsUpdateInterval",
            "windowWidth",
            "windowHeight",
            "backgroundRed",
            "backgroundGreen",
            "backgroundBlue",
            "visibleFaceOptimization",
            "makeFacesTwoSided",
            "testWallEnabled",
            "testWallStartX",
            "testWallEndX",
            "testWallY",
            "testWallBottomZ",
            "testWallTopZ",
            "pillarEnabled",
            "pillarX",
            "pillarY",
            "pillarBottomZ",
            "pillarTopZ",
            "stairsEnabled",
            "grassTopTextureRotation",
            "grassSideTextureRotation",
            "stoneTextureRotation",
            "woodTextureRotation",
        ]

        y = 0.44

        for setting_name in editable_settings:
            DirectLabel(
                parent=canvas,
                text=setting_name,
                scale=0.04,
                pos=(-0.93, 0, y),
                text_align=TextNode.ALeft,
                text_fg=(1, 1, 1, 1),
                frameColor=(0, 0, 0, 0),
            )

            entry = DirectEntry(
                parent=canvas,
                initialText=str(self.settings[setting_name]),
                scale=0.04,
                width=12,
                numLines=1,
                focus=0,
                pos=(0.25, 0, y),
                frameColor=(0.25, 0.25, 0.25, 1),
                text_fg=(1, 1, 1, 1),
            )

            self.setting_entries[setting_name] = entry
            y -= 0.135

        self.options_frame.hide()
        self.update_fps_button()

    def update_fps_button(self):
        if not hasattr(self, "fps_button"):
            return

        state = "ON" if self.show_fps else "OFF"
        self.fps_button["text"] = f"FPS Counter: {state}"

    def toggle_options_menu(self):
        if self.menu_open:
            self.close_options_menu()
        else:
            self.open_options_menu()

    def open_options_menu(self):
        self.menu_open = True
        self.options_frame.show()
        self.crosshair.hide()
        self.unlock_mouse()

        for key in self.keys:
            self.keys[key] = False

        self.refresh_setting_entries()
        self.status_text["text"] = ""

    def close_options_menu(self):
        self.menu_open = False
        self.options_frame.hide()
        self.crosshair.show()
        self.lock_mouse()

    def refresh_setting_entries(self):
        for key, entry in self.setting_entries.items():
            entry.enterText(str(self.settings[key]))

    def parse_setting(self, key, text):
        expected_type = settingTypes[key]
        value = text.strip()

        if expected_type is bool:
            lowered = value.lower()

            if lowered in ("true", "1", "yes", "on"):
                return True

            if lowered in ("false", "0", "no", "off"):
                return False

            raise ValueError(f"{key} must be true or false")

        if expected_type is int:
            return int(float(value))

        if expected_type is float:
            return float(value)

        return value

    def apply_settings_from_menu(self):
        changed_world = False

        world_settings = {
            "worldSize",
            "grassDepth",
            "cobblestoneDepth",
            "worldTopZ",
            "testWallEnabled",
            "testWallStartX",
            "testWallEndX",
            "testWallY",
            "testWallBottomZ",
            "testWallTopZ",
            "pillarEnabled",
            "pillarX",
            "pillarY",
            "pillarBottomZ",
            "pillarTopZ",
            "stairsEnabled",
            "visibleFaceOptimization",
            "makeFacesTwoSided",
            "grassTopTextureRotation",
            "grassSideTextureRotation",
            "stoneTextureRotation",
            "woodTextureRotation",
        }

        try:
            new_settings = self.settings.copy()

            for key, entry in self.setting_entries.items():
                new_value = self.parse_setting(key, entry.get())

                if key in world_settings and new_value != self.settings[key]:
                    changed_world = True

                new_settings[key] = new_value

            new_settings["worldSize"] = max(1, int(new_settings["worldSize"]))
            new_settings["grassDepth"] = max(0, int(new_settings["grassDepth"]))
            new_settings["cobblestoneDepth"] = max(
                0,
                int(new_settings["cobblestoneDepth"]),
            )
            new_settings["playerRadius"] = max(
                0.05,
                float(new_settings["playerRadius"]),
            )
            new_settings["playerHeight"] = max(
                0.5,
                float(new_settings["playerHeight"]),
            )
            new_settings["mouseSensitivity"] = max(
                0.001,
                float(new_settings["mouseSensitivity"]),
            )
            new_settings["rayStep"] = max(
                0.001,
                float(new_settings["rayStep"]),
            )
            new_settings["cameraNearClip"] = max(
                0.001,
                float(new_settings["cameraNearClip"]),
            )
            new_settings["cameraFarClip"] = max(
                new_settings["cameraNearClip"] + 1,
                float(new_settings["cameraFarClip"]),
            )

            self.settings = new_settings
            self.settings["fpsCounterEnabled"] = self.show_fps

            save_settings(self.settings)
            self.configure_window()
            self.title_text.setText(str(self.settings["gameTitle"]))

            if changed_world:
                self.rebuild_world()

            self.status_text["text"] = "Settings saved"
            self.refresh_setting_entries()

        except (ValueError, TypeError) as error:
            self.status_text["text"] = f"Invalid setting: {error}"

    def reset_default_settings(self):
        self.settings = defaultSettings.copy()
        self.show_fps = bool(self.settings["fpsCounterEnabled"])

        save_settings(self.settings)
        self.configure_window()
        self.refresh_setting_entries()
        self.update_fps_button()
        self.rebuild_world()

        if not self.show_fps:
            self.fps_text.setText("")

        self.status_text["text"] = "Defaults restored"

    def quit_game(self):
        self.settings["fpsCounterEnabled"] = self.show_fps
        save_settings(self.settings)
        self.userExit()

    def clear_world(self):
        for block_data in self.blocks.values():
            node = block_data["node"]

            if node:
                node.removeNode()

        self.blocks.clear()

    def rebuild_world(self):
        self.clear_world()
        self.make_world()
        self.rebuild_all_visible_blocks()
        self.spawn_player()

    def get_block_type(self, pos):
        block_data = self.blocks.get(pos)

        if block_data is None:
            return blockTypeStone

        return block_data["type"]

    def get_texture_and_color_for_face(self, block_type, face_name):
        if block_type == blockTypeGrass:
            if face_name == faceTop:
                return (
                    self.grass_top_texture,
                    fallbackGrassTopColor,
                    float(self.value("grassTopTextureRotation")),
                )

            if face_name == faceBottom:
                return (
                    self.stone_texture,
                    fallbackStoneColor,
                    float(self.value("stoneTextureRotation")),
                )

            return (
                self.grass_side_texture,
                fallbackGrassSideColor,
                float(self.value("grassSideTextureRotation")),
            )

        if block_type == blockTypeWood:
            return (
                self.wood_texture,
                fallbackWoodColor,
                float(self.value("woodTextureRotation")),
            )

        return (
            self.stone_texture,
            fallbackStoneColor,
            float(self.value("stoneTextureRotation")),
        )

    def make_block_node(self, pos):
        block_node = NodePath("block")

        x, y, z = pos
        block_type = self.get_block_type(pos)

        for face_name, face_pos, face_hpr, neighbor in faceData:
            neighbor_pos = (
                x + neighbor[0],
                y + neighbor[1],
                z + neighbor[2],
            )

            if (
                bool(self.value("visibleFaceOptimization"))
                and neighbor_pos in self.blocks
            ):
                continue

            card = CardMaker("face")
            card.setFrame(-0.5, 0.5, -0.5, 0.5)

            face = block_node.attachNewNode(card.generate())
            face.setPos(*face_pos)
            face.setHpr(*face_hpr)

            if bool(self.value("makeFacesTwoSided")):
                face.setTwoSided(True)

            texture, fallback_color, rotation = (
                self.get_texture_and_color_for_face(
                    block_type,
                    face_name,
                )
            )

            if texture:
                face.setTexture(texture)
                face.setTexRotate(
                    TextureStage.getDefault(),
                    rotation,
                )
            else:
                face.setColor(*fallback_color)

        return block_node

    def add_block_data_only(self, x, y, z, block_type=None):
        pos = (int(x), int(y), int(z))

        if block_type is None:
            block_type = self.get_default_block_type(pos)

        if pos not in self.blocks:
            self.blocks[pos] = {
                "node": None,
                "type": block_type,
            }

    def add_block(self, x, y, z, block_type=None):
        pos = (int(x), int(y), int(z))

        if pos in self.blocks:
            return False

        if block_type is None:
            block_type = blockTypeStone

        self.blocks[pos] = {
            "node": None,
            "type": block_type,
        }

        self.rebuild_block_and_neighbors(pos)
        return True

    def remove_block(self, pos):
        if pos not in self.blocks:
            return False

        block_node = self.blocks[pos]["node"]

        if block_node:
            block_node.removeNode()

        del self.blocks[pos]
        self.rebuild_neighbors(pos)

        return True

    def rebuild_block(self, pos):
        if pos not in self.blocks:
            return

        old_block = self.blocks[pos]["node"]

        if old_block:
            old_block.removeNode()

        new_block = self.make_block_node(pos)
        new_block.reparentTo(self.render)
        new_block.setPos(*pos)

        self.blocks[pos]["node"] = new_block

    def rebuild_neighbors(self, pos):
        x, y, z = pos

        for offset_x, offset_y, offset_z in neighborOffsets:
            neighbor_pos = (
                x + offset_x,
                y + offset_y,
                z + offset_z,
            )

            if neighbor_pos in self.blocks:
                self.rebuild_block(neighbor_pos)

    def rebuild_block_and_neighbors(self, pos):
        self.rebuild_block(pos)
        self.rebuild_neighbors(pos)

    def rebuild_all_visible_blocks(self):
        for pos in list(self.blocks.keys()):
            self.rebuild_block(pos)

    def get_default_block_type(self, pos):
        z = pos[2]
        world_top = int(self.value("worldTopZ"))
        grass_depth = int(self.value("grassDepth"))
        lowest_grass_z = world_top - grass_depth + 1

        if lowest_grass_z <= z <= world_top:
            return blockTypeGrass

        return blockTypeStone

    def get_placement_block_type(self, place_pos):
        z = place_pos[2]
        world_top = int(self.value("worldTopZ"))
        grass_depth = int(self.value("grassDepth"))
        lowest_grass_z = world_top - grass_depth + 1

        if z > world_top:
            return placedAboveGrassType

        if lowest_grass_z <= z <= world_top:
            return placedOnGrassLevelType

        return placedBelowGrassType

    def make_world(self):
        world_size = int(self.value("worldSize"))
        grass_depth = int(self.value("grassDepth"))
        cobble_depth = int(self.value("cobblestoneDepth"))
        world_depth = grass_depth + cobble_depth
        world_top = int(self.value("worldTopZ"))

        for x in range(-world_size, world_size + 1):
            for y in range(-world_size, world_size + 1):
                for depth in range(world_depth):
                    self.add_block_data_only(
                        x,
                        y,
                        world_top - depth,
                    )

        if bool(self.value("testWallEnabled")):
            for z in range(
                int(self.value("testWallBottomZ")),
                int(self.value("testWallTopZ")) + 1,
            ):
                for x in range(
                    int(self.value("testWallStartX")),
                    int(self.value("testWallEndX")) + 1,
                ):
                    self.add_block_data_only(
                        x,
                        int(self.value("testWallY")),
                        z,
                        blockTypeStone,
                    )

        if bool(self.value("pillarEnabled")):
            for z in range(
                int(self.value("pillarBottomZ")),
                int(self.value("pillarTopZ")) + 1,
            ):
                self.add_block_data_only(
                    int(self.value("pillarX")),
                    int(self.value("pillarY")),
                    z,
                    blockTypeStone,
                )

        if bool(self.value("stairsEnabled")):
            for x, y, z in [
                (-2, 6, 1),
                (-1, 6, 1),
                (-1, 6, 2),
                (0, 6, 1),
                (0, 6, 2),
                (0, 6, 3),
            ]:
                self.add_block_data_only(
                    x,
                    y,
                    z,
                    blockTypeStone,
                )

    def block_centers_touching_range(self, minimum, maximum):
        start = math.floor(minimum + 0.5)
        end = math.floor(maximum + 0.5)
        return range(start, end + 1)

    def player_collides_at(self, eye_pos):
        player_height = float(self.value("playerHeight"))
        player_radius = float(self.value("playerRadius"))

        feet_z = eye_pos.z - player_height
        min_x = eye_pos.x - player_radius
        max_x = eye_pos.x + player_radius
        min_y = eye_pos.y - player_radius
        max_y = eye_pos.y + player_radius
        min_z = feet_z + 0.06
        max_z = eye_pos.z - 0.1

        for x in self.block_centers_touching_range(min_x, max_x):
            for y in self.block_centers_touching_range(min_y, max_y):
                for z in self.block_centers_touching_range(min_z, max_z):
                    if (x, y, z) in self.blocks:
                        return True

        return False

    def is_on_ground(self):
        pos = self.camera.getPos()
        player_height = float(self.value("playerHeight"))
        player_radius = float(self.value("playerRadius"))

        feet_z = pos.z - player_height
        min_x = pos.x - player_radius
        max_x = pos.x + player_radius
        min_y = pos.y - player_radius
        max_y = pos.y + player_radius

        check_z = feet_z - 0.05
        block_z = math.floor(check_z + 0.5)

        for x in self.block_centers_touching_range(min_x, max_x):
            for y in self.block_centers_touching_range(min_y, max_y):
                if (x, y, block_z) in self.blocks:
                    return True

        return False

    def get_look_direction(self):
        heading = math.radians(self.camera.getH())
        pitch = math.radians(self.camera.getP())

        return Vec3(
            -math.sin(heading) * math.cos(pitch),
            math.cos(heading) * math.cos(pitch),
            math.sin(pitch),
        ).normalized()

    def world_to_block_pos(self, point):
        return (
            math.floor(point.x + 0.5),
            math.floor(point.y + 0.5),
            math.floor(point.z + 0.5),
        )

    def raycast_block(self):
        start = self.camera.getPos()
        direction = self.get_look_direction()
        previous_block_pos = None
        distance = 0.0
        max_distance = float(self.value("maxRayDistance"))
        ray_step = float(self.value("rayStep"))

        while distance <= max_distance:
            point = start + direction * distance
            block_pos = self.world_to_block_pos(point)

            if block_pos in self.blocks:
                return block_pos, previous_block_pos

            previous_block_pos = block_pos
            distance += ray_step

        return None, None

    def break_block(self):
        block_pos, _ = self.raycast_block()

        if block_pos is not None:
            self.remove_block(block_pos)

    def place_block(self):
        hit_block, place_pos = self.raycast_block()

        if hit_block is None or place_pos is None:
            return

        if place_pos in self.blocks:
            return

        block_type = self.get_placement_block_type(place_pos)

        if not self.add_block(*place_pos, block_type):
            return

        if self.player_collides_at(self.camera.getPos()):
            self.remove_block(place_pos)

    def update_mouse(self):
        if not self.mouse_locked or self.menu_open:
            return

        center_x = self.win.getXSize() // 2
        center_y = self.win.getYSize() // 2
        pointer = self.win.getPointer(0)

        delta_x = pointer.getX() - center_x
        delta_y = pointer.getY() - center_y
        sensitivity = float(self.value("mouseSensitivity"))

        if delta_x != 0 or delta_y != 0:
            self.camera.setH(
                self.camera.getH() - delta_x * sensitivity
            )

            pitch = self.camera.getP() - delta_y * sensitivity
            self.camera.setP(max(-89, min(89, pitch)))

        self.center_mouse()

    def update_movement(self, dt):
        if self.menu_open:
            return

        current_pos = self.camera.getPos()
        heading = math.radians(self.camera.getH())
        speed = float(self.value("playerSpeed"))

        forward = Vec3(
            -math.sin(heading),
            math.cos(heading),
            0,
        )

        right = Vec3(
            math.cos(heading),
            math.sin(heading),
            0,
        )

        move = Vec3(0, 0, 0)

        if self.keys["w"]:
            move += forward
        if self.keys["s"]:
            move -= forward
        if self.keys["a"]:
            move -= right
        if self.keys["d"]:
            move += right

        if move.length() > 0:
            move.normalize()

        next_pos = Vec3(
            current_pos.x + move.x * speed * dt,
            current_pos.y,
            current_pos.z,
        )

        if not self.player_collides_at(next_pos):
            self.camera.setX(next_pos.x)

        current_pos = self.camera.getPos()

        next_pos = Vec3(
            current_pos.x,
            current_pos.y + move.y * speed * dt,
            current_pos.z,
        )

        if not self.player_collides_at(next_pos):
            self.camera.setY(next_pos.y)

        grounded = self.is_on_ground()

        if grounded and self.vertical_speed < 0:
            self.vertical_speed = 0

        if grounded and self.keys["space"]:
            self.vertical_speed = float(self.value("jumpPower"))

        self.vertical_speed -= (
            float(self.value("gravityStrength")) * dt
        )

        current_pos = self.camera.getPos()

        next_pos = Vec3(
            current_pos.x,
            current_pos.y,
            current_pos.z + self.vertical_speed * dt,
        )

        if not self.player_collides_at(next_pos):
            self.camera.setZ(next_pos.z)
        else:
            if self.vertical_speed < 0:
                feet_z = (
                    current_pos.z
                    - float(self.value("playerHeight"))
                )

                block_z = math.floor(feet_z - 0.1 + 0.5)

                self.camera.setZ(
                    block_z
                    + 0.5
                    + float(self.value("playerHeight"))
                )

            self.vertical_speed = 0

    def update_fps_counter(self, dt):
        if not self.show_fps:
            return

        self.fps_timer += dt

        if self.fps_timer >= float(self.value("fpsUpdateInterval")):
            frame_time = max(globalClock.getDt(), 0.0001)
            self.fps_text.setText(
                f"FPS: {round(1.0 / frame_time)}"
            )
            self.fps_timer = 0.0

    def update(self, task):
        dt = min(
            globalClock.getDt(),
            float(self.value("maxDeltaTime")),
        )

        self.update_mouse()
        self.update_movement(dt)
        self.update_fps_counter(dt)

        return Task.cont


game = ClassiRenderMC()
game.run()