# coding=utf-8
import sys, os, pyglet
import numpy as np
import libs.transformations as tr
import libs.scene_graph as sg
import libs.shapes as shp
import libs.shaders as sh
import libs.lighting_shaders as ls

from libs.gpu_shape import createGPUShape
from libs.obj_handler import read_OBJ2
from libs.assets_path import getAssetPath
from pyglet.graphics.shader import Shader, ShaderProgram
from itertools import chain
from pathlib import Path
from OpenGL.GL import *

""" Controls:
    W/S: move forward/backward
    A/D: turn left/right
    move mouse up/down: turn up/down
    hold shift: turbo
    C: change perspective
    R: create control point
    V: view curve
    B: restart curves
    1: reproduce path
    P: special move
"""

# Initial data
N=50
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ASSETS = {
    "ship_obj": getAssetPath("ship.obj"), "ship_tex": getAssetPath("ship.png"), # models and textures by me
    "ring_obj": getAssetPath("ring.obj"), "ring_tex": getAssetPath("ring.png"), # ---
    "coin_obj": getAssetPath("coin.obj"), "black_tex": getAssetPath("black.png"), # ---
    "cube_obj": getAssetPath("cube.obj"), "cube_tex": getAssetPath("dirt_1.png"), # texture by Screaming Brain Studios
    "among_us_obj": getAssetPath("among_us.obj"), "among_us_tex": getAssetPath("among_us.png"), # model and texture by Vilitay
    "build1_obj": getAssetPath("build1.obj"), "build1_tex": getAssetPath("build1.png"), # models and textures by Mykhailo Ohorodnichuk
    "build2_obj": getAssetPath("build2.obj"), "build2_tex": getAssetPath("build2.png"), # ---
    "icon": getAssetPath("icon.png"), # icon by Freepik
}

# Aspect ratio and projection
display = pyglet.canvas.Display()
screen = display.get_default_screen()
screen_height, screen_width = screen.height, screen.width
PROJECTIONS = [
    tr.ortho(-10*screen_width/screen_height, 10*screen_width/screen_height, -10, 10, 0.1, 200),  # ORTOGRAPHIC_PROJECTION
    tr.perspective(100, float(screen_width)/float(screen_height), 0.1, 200)  # PERSPECTIVE_PROJECTION
]
TEX = [GL_REPEAT, GL_REPEAT, GL_NEAREST, GL_NEAREST]

# Hermite curve
def hermiteMatrix(P1, P2, T1, T2):
    # Generate a matrix concatenating the columns
    G = np.concatenate((P1, P2, T1, T2), axis=1)
    # Hermite base matrix is a constant
    Mh = np.array([[1, 0, -3, 2], [0, 0, 3, -2], [0, 1, -2, 1], [0, 0, -1, 1]])
    return np.matmul(G, Mh)

# M is the cubic curve matrix, N is the number of samples between 0 and 1
def evalCurve(M, N):
    # The parameter t should move between 0 and 1
    ts = np.linspace(0.0, 1.0, N)
    # The computed value in R3 for each sample will be stored here
    curve = np.ndarray(shape=(N, 3), dtype=float)
    for i in range(len(ts)):
        T = np.array([[1, ts[i], ts[i]**2, ts[i]**3]]).T
        curve[i, 0:3] = np.matmul(M, T).T
    return curve

# Set lightning shader
def setLightShader(shader):
    glUniform3f(glGetUniformLocation(shader.shaderProgram, "La"), 0.8, 0.8, 0.8)
    glUniform3f(glGetUniformLocation(shader.shaderProgram, "Ld"), 0.9, 0.9, 0.9)
    glUniform3f(glGetUniformLocation(shader.shaderProgram, "Ls"), 1, 1, 1)
    glUniform3f(glGetUniformLocation(shader.shaderProgram, "Ka"), 1, 1, 1)
    glUniform3f(glGetUniformLocation(shader.shaderProgram, "Kd"), 1, 1, 1)
    glUniform3f(glGetUniformLocation(shader.shaderProgram, "Ks"), 1, 1, 1)
    glUniform3f(glGetUniformLocation(shader.shaderProgram, "lightPosition"), 0, 0, 25)
    glUniform3f(glGetUniformLocation(shader.shaderProgram, "viewPosition"), camera.eye[0], camera.eye[1], camera.eye[2])
    glUniform1ui(glGetUniformLocation(shader.shaderProgram, "shininess"), 300)
    glUniform1f(glGetUniformLocation(shader.shaderProgram, "constantAttenuation"), 0.1)
    glUniform1f(glGetUniformLocation(shader.shaderProgram, "linearAttenuation"), 0.1)
    glUniform1f(glGetUniformLocation(shader.shaderProgram, "quadraticAttenuation"), 0.01)

# Controller of the pyglet window
class Controller(pyglet.window.Window):
    def __init__(self, width, height, title=f"La mejor tarea 3 de la sección"):
        # Initial setup of the window
        super().__init__(width, height, title, fullscreen=True)
        self.set_exclusive_mouse(True)
        self.set_icon(pyglet.image.load(ASSETS["icon"]))
        self.showCurve = False
        self.total_time = 0.0 # Time in the scene
        self.step = 0

# Scene graph manager
class Scene:
    def __init__(self) -> None:
        # Initial setup of the scene
        self.pipeline = ls.SimpleTexturePhongShaderProgram()
        self.root = sg.SceneGraphNode("root")
        self.tex_params = TEX

        # --- Squad ---
        ship_obj = createGPUShape(self.pipeline, read_OBJ2(ASSETS["ship_obj"]))
        ship_obj.texture = sh.textureSimpleSetup(ASSETS["ship_tex"], *self.tex_params)
        ship_shadow_obj = createGPUShape(self.pipeline, read_OBJ2(ASSETS["ship_obj"]))
        ship_shadow_obj.texture = sh.textureSimpleSetup(ASSETS["black_tex"], *self.tex_params)
        self.squad = sg.SceneGraphNode("squad")
        self.root.childs += [self.squad]

        # Ships
        self.shipRotation = sg.SceneGraphNode("shipRotation") # Main ship
        self.shipRotation.childs += [ship_obj]
        self.shipRotation2 = sg.SceneGraphNode("shipRotation2") # Side ships
        self.shipRotation2.childs += [ship_obj]
        self.shipRotation3 = sg.SceneGraphNode("shipRotation3")
        self.shipRotation3.childs += [ship_obj]
        # Perspective camera
        self.eye = sg.SceneGraphNode("eye")
        self.at = sg.SceneGraphNode("at")
        self.up = sg.SceneGraphNode("up")
        self.squad.childs += [self.shipRotation, self.shipRotation2, self.shipRotation3, self.eye, self.up, self.at] # Add ships

        # Shadows
        self.ship_shadows = sg.SceneGraphNode("ship_shadows")
        self.shipRotationShadow = sg.SceneGraphNode("shipRotationShadow") # Main ship
        self.shipRotationShadow.childs += [ship_shadow_obj]
        self.shipRotationShadow2 = sg.SceneGraphNode("shipRotationShadow2") # Side ships
        self.shipRotationShadow2.childs += [ship_shadow_obj]
        self.shipRotationShadow3 = sg.SceneGraphNode("shipRotationShadow3")
        self.shipRotationShadow3.childs += [ship_shadow_obj]
        self.ship_shadows.childs += [self.shipRotationShadow, self.shipRotationShadow2, self.shipRotationShadow3] # Add shadows
        self.root.childs += [self.ship_shadows]

        # --- Scenery ---
        self.scenario = sg.SceneGraphNode("scenario")
        self.root.childs += [self.scenario]
        # Floor
        floor = sg.SceneGraphNode("floor")
        cube = createGPUShape(self.pipeline, shp.createTextureQuad(*[50, 50]), "cube")
        cube.texture = sh.textureSimpleSetup(ASSETS["cube_tex"], *self.tex_params)
        floor.transform = tr.scale(200, 200, 1)
        floor.childs += [cube]
        self.scenario.childs += [floor]

    # Add scenery to the scene
    def addScenery(self, obj, tex, pos, rotX, rotZ, scale):
        # Model
        node = sg.SceneGraphNode(obj)
        model = createGPUShape(self.pipeline, read_OBJ2(ASSETS[obj]))
        model.texture = sh.textureSimpleSetup(ASSETS[tex], *self.tex_params)
        node.transform = tr.matmul([tr.translate(*pos), tr.uniformScale(scale), tr.rotationZ(rotZ), tr.rotationX(rotX)])
        node.childs += [model]
        self.scenario.childs += [node]
        # Shadow
        shadow = sg.SceneGraphNode(obj+"_shadow")
        shadow_model = createGPUShape(self.pipeline, read_OBJ2(ASSETS[obj]))
        shadow_model.texture = sh.textureSimpleSetup(ASSETS["black_tex"], *self.tex_params)
        shadow.transform = tr.matmul([tr.translate(pos[0], pos[1], 0), tr.scale(scale, scale, 0.01), tr.rotationZ(rotZ), tr.rotationX(rotX)])
        shadow.childs += [shadow_model]
        self.scenario.childs += [shadow]

# Camera which controls the projection and view
class Camera:
    def __init__(self, at=np.array([0.0, 0.0, 0.0]), eye=np.array([5.0, 5.0, 5.0]), up=np.array([-0.577, -0.577, 0.577])) -> None:
        # View parameters
        self.at = at
        self.eye = eye
        self.up = up

        # Cartesian coordinates
        self.x = np.square(self.eye[0])
        self.y = np.square(self.eye[1])
        self.z = np.square(self.eye[2])

        # Projections
        self.available_projections = PROJECTIONS
        self.proj = 0
        self.projection = self.available_projections[0]

    # Set orthographic or perspective projection
    def set_projection(self):
        self.proj = (self.proj+1)%2
        self.projection = self.available_projections[self.proj]

    # Follow the ship
    def update(self, eye, at, up, ship):
        if(self.proj==0): # orthographic projection
            self.up = np.array([-0.577, -0.577, 0.577])
            self.eye = np.array([self.x+ship[0][0], self.y+ship[1][0], self.z+ship[2][0]])
            self.at = np.array([ship[0][0], ship[1][0], ship[2][0]])
        else: # perspective projection
            self.eye = np.array([eye[0][0], eye[1][0], eye[2][0]])
            self.at = np.array([at[0][0], at[1][0], at[2][0]])
            self.up = np.array([up[0][0]-eye[0][0], up[1][0]-eye[1][0], up[2][0]-eye[2][0]])

# Movement of the ships
class Movement:
    def __init__(self, eye=np.array([1.0, 1.0, 1.5]), rotation_y=0.01, rotation_z=0.01) -> None:
        # Initial setup
        self.eye = eye
        self.speed = 0.15
        self.rotation_x = 0
        self.rotation_y = rotation_y
        self.rotation_z = rotation_z
        self.x_direction = 0 # local x axis direction
        self.x_angle = 0 # special move
        self.y_angle = 0 # theta
        self.z_angle = 0 # phi
        self.curving = False # curve
        self.looping = False
        self.change = False

    # Move the ship
    def update(self):
        # Update facing angle of the ship
        if np.abs(self.rotation_x) > 2*np.pi:
            self.x_angle = 0
            self.rotation_x = 0
            self.looping = False
        self.rotation_x += self.x_angle*0.1
        self.rotation_y += self.y_angle*0.1
        self.rotation_z += self.z_angle*0.05

        # Move in the local x axis, hover a little bit and set the limits of the map
        if np.abs(self.eye[0]) < 50: self.eye[0] += (self.x_direction*np.cos(self.rotation_y)+np.sin(self.rotation_y)*np.sin(2*controller.total_time)*0.01/self.speed)*np.cos(self.rotation_z)*self.speed
        elif self.eye[0] >= 50: self.eye[0] -= 0.01
        else: self.eye[0] += 0.01
        if np.abs(self.eye[1]) < 50: self.eye[1] += (self.x_direction*np.cos(self.rotation_y)+np.sin(self.rotation_y)*np.sin(2*controller.total_time)*0.01/self.speed)*np.sin(self.rotation_z)*self.speed
        elif self.eye[1] >= 50: self.eye[1] -= 0.01
        else: self.eye[1] += 0.01
        if self.eye[2] < 30 and self.eye[2] > 0.4: self.eye[2] += (self.x_direction*np.sin(self.rotation_y)*-1+np.cos(self.rotation_y)*np.sin(2*controller.total_time)*0.01/self.speed)*self.speed
        elif self.eye[2] >= 30: self.eye[2] -= 0.01
        else: self.eye[2] += 0.01

        # Stop rotation with the mouse
        movement.y_angle = 0

# Initial setup
controller, scene, camera, movement = Controller(width=screen_width, height=screen_height), Scene(), Camera(), Movement()
control_points = [[], []] # Coordenates, angles
prevHermiteCurve, hermiteCurve = None, None

# Scenario
scene.addScenery("build1_obj", "build1_tex", [10, 12, 0], np.pi/2, 0, 1.5)
scene.addScenery("build2_obj", "build2_tex", [-7, -2, 0], np.pi/2, np.pi/2, 1.4)
scene.addScenery("ring_obj", "ring_tex", [0, 0, 0], 0, 0, 1)
scene.addScenery("coin_obj", "ring_tex", [0, 0, 0], 0, 0, 1)
scene.addScenery("among_us_obj", "among_us_tex", [9, -1, 1.6], np.pi/2, np.pi, 2) # generan lag xd
scene.addScenery("among_us_obj", "among_us_tex", [9, -1, 4.4], np.pi/2, np.pi, 2) # estan muy detallados
scene.addScenery("among_us_obj", "among_us_tex", [9, -1, 7.1], np.pi/2, np.pi, 2)

# Camera setup
glClearColor(0.05, 0.05, 0.1, 1.0)
glEnable(GL_DEPTH_TEST)
glUseProgram(scene.pipeline.shaderProgram)

# What happens when the user presses these keys
@controller.event
def on_key_press(symbol, modifiers):
    # global variables
    global control_points, prevHermiteCurve, hermiteCurve, n

    # everything else
    if symbol == pyglet.window.key._1:
        controller.step = 0
        if len(control_points[0]) > 0: movement.curving = not movement.curving
    if symbol == pyglet.window.key.C: camera.set_projection()
    if symbol == pyglet.window.key.V: controller.showCurve = not controller.showCurve
    if symbol == pyglet.window.key.P and not movement.looping: # special move
        movement.looping = True
        movement.x_angle = np.random.choice([1, -1])
    if not movement.curving:
        if symbol == pyglet.window.key.B: # delete path
            control_points = [[], []]
            prevHermiteCurve, hermiteCurve = None, None
        if symbol == pyglet.window.key.R: # curve
            point = np.array([[movement.eye[0], movement.eye[1], movement.eye[2]]]).T
            rot_y, rot_z = movement.rotation_y, movement.rotation_z
            angle = np.array([[np.cos(rot_y)*np.cos(rot_z), np.cos(rot_y)*np.sin(rot_z), -np.sin(rot_y)]]).T
            control_points[0].append(point)
            control_points[1].append(angle)
            lenC = len(control_points[0])
            if lenC > 2: # re create prev curve and create the end of the curve
                vector = point-control_points[0][-3]
                control_points[1][-2] = vector
                GMh = hermiteMatrix(control_points[0][-3], control_points[0][-2], control_points[1][-3], control_points[1][-2])
                if lenC > 3: prevHermiteCurve = np.concatenate((prevHermiteCurve[0:-1], evalCurve(GMh, N)), axis=0)
                else: prevHermiteCurve = evalCurve(GMh, N)
                GMh = hermiteMatrix(control_points[0][-2], control_points[0][-1], control_points[1][-2], control_points[1][-1])
                hermiteCurve = np.concatenate((prevHermiteCurve[0:-1], evalCurve(GMh, N)), axis=0)
            elif lenC == 2: # Create curve when just 2 control points
                GMh = hermiteMatrix(control_points[0][-2], control_points[0][-1], control_points[1][-2], control_points[1][-1])
                hermiteCurve = evalCurve(GMh, N)
        if symbol == pyglet.window.key.A: movement.z_angle += 1
        if symbol == pyglet.window.key.D: movement.z_angle -= 1
        if symbol == pyglet.window.key.W: movement.x_direction += 1
        if symbol == pyglet.window.key.S: movement.x_direction -= 1
        if modifiers == 17: movement.speed = 0.3 # MOD_SHIFT does not always work for some reason
    if symbol == pyglet.window.key.ESCAPE: controller.close() # close the window

# What happens when the user releases these keys
@controller.event
def on_key_release(symbol, modifiers):
    if not movement.curving:
        if symbol == pyglet.window.key.A: movement.z_angle -= 1
        if symbol == pyglet.window.key.D: movement.z_angle += 1
        if symbol == pyglet.window.key.W: movement.x_direction -= 1
        if symbol == pyglet.window.key.S: movement.x_direction += 1
        if modifiers == 17-1: movement.speed = 0.15

# What happens when the user moves the mouse
@controller.event
def on_mouse_motion(x, y, dx, dy):
    if not movement.curving:
        if dy>0: movement.y_angle = -0.6
        if dy<0: movement.y_angle = 0.6

# What draws at every frame
@controller.event
def on_draw():
    # Step update
    if controller.step >= N*(len(control_points[0])-1)-len(control_points[0]): controller.step = -1
    controller.step += 1

    # Things
    controller.clear()
    glUseProgram(scene.pipeline.shaderProgram)
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

    # Ships movement
    movement.update()
    if movement.curving: # curve movement
        vector = hermiteCurve[controller.step+1]-hermiteCurve[controller.step]
        if controller.step-1 >= 0: prev_x = hermiteCurve[controller.step][0]-hermiteCurve[controller.step-1][0]
        else: prev_x = hermiteCurve[controller.step+1][0]-hermiteCurve[controller.step][0]
        vector /= np.linalg.norm(vector)
        prev_x /= np.linalg.norm(prev_x)
        if (prev_x*vector[1] < 0) and np.abs(movement.rotation_y) > 1.50: movement.change = not movement.change
        if movement.change:
            if not movement.looping: movement.rotation_x = np.pi
            movement.rotation_y = np.arcsin(-vector[2]/np.sqrt(vector[0]*vector[0]+vector[1]*vector[1]+vector[2]*vector[2]))
        else:
            if not movement.looping: movement.rotation_x = 0
            movement.rotation_y = -np.arcsin(vector[2]/np.sqrt(vector[0]*vector[0]+vector[1]*vector[1]+vector[2]*vector[2]))
        movement.rotation_z = np.sign(vector[1])*np.arccos(vector[0]/np.sqrt(vector[0]*vector[0]+vector[1]*vector[1]))
        ship_move = [tr.translate(*hermiteCurve[controller.step])]
    else: # free movement
        ship_move = [tr.translate(movement.eye[0], movement.eye[1], movement.eye[2])]
    if movement.change and controller.step == 0: # restart when beginning curve again
        movement.rotation_x = 0
        movement.rotation_x = np.pi
        movement.rotation_x = 0
        movement.change = not movement.change
    ship_rot = [tr.rotationZ(movement.rotation_z), tr.rotationY(movement.rotation_y), tr.rotationX(movement.rotation_x)]
    scene.shipRotation2.transform = tr.matmul([tr.translate(-2, -1, 0)])
    scene.shipRotation3.transform = tr.matmul([tr.translate(-2, 1, 0)])
    ship1, ship2, ship3 = sg.findPosition(scene.squad, "shipRotation"), sg.findPosition(scene.squad, "shipRotation2"), sg.findPosition(scene.squad, "shipRotation3")
    scene.shipRotationShadow.transform = tr.matmul([tr.translate(ship1[0][0], ship1[1][0], 0.01)]+[tr.scale(1, 1, 0.01)]+ship_rot)
    scene.shipRotationShadow2.transform = tr.matmul([tr.translate(ship2[0][0], ship2[1][0], 0.01)]+[tr.scale(1, 1, 0.01)]+ship_rot)
    scene.shipRotationShadow3.transform = tr.matmul([tr.translate(ship3[0][0], ship3[1][0], 0.01)]+[tr.scale(1, 1, 0.01)]+ship_rot)
    scene.squad.transform = tr.matmul(ship_move+ship_rot) # Start movement of the ships

    # Camera in perspective
    scene.eye.transform = tr.matmul([tr.translate(-4.0, 0, 2.0)])
    scene.at.transform = tr.matmul([tr.translate(0.0, 0, 2.0)])
    scene.up.transform = tr.matmul([tr.translate(-4.0, 0, 3.0)])
    eye, up, at = sg.findPosition(scene.squad, "eye"), sg.findPosition(scene.squad, "up"), sg.findPosition(scene.squad, "at")

    # Ring and coin movement
    ring = sg.findNode(scene.root, "ring_obj")
    ringShadow = sg.findNode(scene.root, "ring_obj_shadow")
    ring.transform = tr.matmul([tr.translate(5, -4, 5+np.sin(controller.total_time)), tr.uniformScale(2), tr.rotationZ(controller.total_time*0.2)])
    ringShadow.transform = tr.matmul([tr.translate(5, -4, 0.1), tr.scale(2, 2, 0.01), tr.rotationZ(controller.total_time*0.2)])
    coin = sg.findNode(scene.root, "coin_obj")
    coinShadow = sg.findNode(scene.root, "coin_obj_shadow")
    coin.transform = tr.matmul([tr.translate(-2, 10, 3+np.sin(controller.total_time)*0.5), tr.uniformScale(0.7), tr.rotationZ(controller.total_time)])
    coinShadow.transform = tr.matmul([tr.translate(-2, 10, 0.1), tr.scale(0.7, 0.7, 0.01), tr.rotationZ(controller.total_time)])

    # Camera tracking of the ship, projection and view
    setLightShader(scene.pipeline)
    camera.update(eye, at, up, ship1)
    view = tr.lookAt(camera.eye, camera.at, camera.up)
    glUniformMatrix4fv(glGetUniformLocation(scene.pipeline.shaderProgram, "projection"), 1, GL_TRUE, camera.projection)
    glUniformMatrix4fv(glGetUniformLocation(scene.pipeline.shaderProgram, "view"), 1, GL_TRUE, view)

    # Draw curve
    with open(Path(os.path.dirname(__file__)) / "shaders\point_vertex_program.glsl") as f: vertex_program = f.read()
    with open(Path(os.path.dirname(__file__)) / "shaders\point_fragment_program.glsl") as f: fragment_program = f.read()
    vert_shader = Shader(vertex_program, "vertex")
    frag_shader = Shader(fragment_program, "fragment")
    linePipeline = ShaderProgram(vert_shader, frag_shader)
    if(controller.showCurve and len(control_points[0]) > 1):
        controller.node_data = linePipeline.vertex_list(len(hermiteCurve), pyglet.gl.GL_POINTS, position="f")
        controller.joint_data = linePipeline.vertex_list_indexed(len(hermiteCurve), pyglet.gl.GL_LINES,
            tuple(chain(*(j for j in [range(len(hermiteCurve))]))), position="f",)
        controller.node_data.position[:] = tuple(chain(*((p[0], p[1], p[2]) for p in hermiteCurve)))
        controller.joint_data.position[:] = tuple(chain(*((p[0], p[1], p[2]) for p in hermiteCurve)))
        linePipeline["projection"], linePipeline["view"] = camera.projection.reshape(16, 1, order="F"), view.reshape(16, 1, order="F")
        linePipeline.use()
        # controller.node_data.draw(pyglet.gl.GL_POINTS)
        controller.joint_data.draw(pyglet.gl.GL_LINES)

    # Light shader
    glUseProgram(scene.pipeline.shaderProgram)
    sg.drawSceneGraphNode(scene.root, scene.pipeline, "model")

# Set a time in controller
def update(dt, controller):
    controller.total_time += dt

# Start the scene
if __name__ == '__main__':
    pyglet.clock.schedule(update, controller)
    pyglet.app.run()