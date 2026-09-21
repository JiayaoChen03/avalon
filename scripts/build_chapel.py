#!/usr/bin/env python3
"""Deterministic, modular forbidden chapel. Run with Blender 4.5 LTS.

blender --background --python scripts/build_chapel.py -- --stage blockout
blender --background --python scripts/build_chapel.py -- --stage lighting
blender --background --python scripts/build_chapel.py -- --stage final
Without --stage all three stages are built and rendered from an empty scene.
Only this process's scene is cleared; no external files are removed.
"""
import argparse
import json
import math
import random
import sys
from pathlib import Path

import bpy
from mathutils import Vector, Matrix

# -------------------------- ART DIRECTION --------------------------
ROOT = Path(__file__).resolve().parents[1]
ROOM_WIDTH = 9.0
ROOM_DEPTH = 14.0
ROOM_HEIGHT = 8.2
TABLE_WIDTH = 6.1
TABLE_DEPTH = 3.0
TABLE_HEIGHT = 0.82
TABLE_CENTER_Y = -1.0
CAMERA_FOCAL_LENGTH = 39.0
CAMERA_LOCATION = (0.045, -4.70, 1.59)
CAMERA_TARGET = (0.0, 2.5, 1.02)
CANDLE_POWER = 110.0
CANDLE_COLOR = (1.0, 0.38, 0.13)  # art-directed low-key amber candle light
FOG_DENSITY = 0.012
WORLD_STRENGTH = 0.004
EXPOSURE = -1.0
RED_ACCENT_POWER = 8.0
RENDER_WIDTH = 1600
RENDER_HEIGHT = 1000
SAMPLES = {"blockout": 64, "lighting": 128, "final": 320}
SEED = 7319

M = {}
COLLECTIONS = {}
BOX_CACHE = {}
CANDLE_LOCATIONS = []
STAGE = "blockout"
RNG = random.Random(SEED)


def collection(name):
    if name not in COLLECTIONS:
        c = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(c)
        COLLECTIONS[name] = c
    return COLLECTIONS[name]


def move_to(obj, group):
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    collection(group).objects.link(obj)
    return obj


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for c in list(bpy.data.collections):
        bpy.data.collections.remove(c)
    for datablocks in (bpy.data.meshes, bpy.data.curves, bpy.data.materials,
                       bpy.data.cameras, bpy.data.lights, bpy.data.worlds):
        for block in list(datablocks):
            if block.users == 0:
                datablocks.remove(block)
    COLLECTIONS.clear()
    BOX_CACHE.clear()
    M.clear()
    CANDLE_LOCATIONS.clear()
    RNG.seed(SEED)
    bpy.context.scene.unit_settings.system = "METRIC"
    bpy.context.scene.unit_settings.scale_length = 1.0


def material(name, color, roughness=0.8, metallic=0.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.diffuse_color = (*color, 1.0)
    p = mat.node_tree.nodes.get("Principled BSDF")
    p.inputs["Base Color"].default_value = (*color, 1)
    p.inputs["Roughness"].default_value = roughness
    p.inputs["Metallic"].default_value = metallic
    M[name] = mat
    return mat, p


def noise_material(name, low, high, roughness, scale, bump, grain=None,
                   metallic=0.0):
    mat, p = material(name, tuple((a+b)/2 for a, b in zip(low, high)),
                      roughness, metallic)
    if STAGE == "blockout":
        return mat
    n, l = mat.node_tree.nodes, mat.node_tree.links
    coord = n.new("ShaderNodeTexCoord")
    coord.location = (-900, 0)
    tex = n.new("ShaderNodeTexNoise")
    tex.inputs["Scale"].default_value = scale
    tex.inputs["Detail"].default_value = 4.0
    tex.inputs["Roughness"].default_value = .72
    tex.location = (-520, 90)
    if grain:
        mapping = n.new("ShaderNodeVectorMath")
        mapping.operation = "MULTIPLY"
        mapping.inputs[1].default_value = grain
        l.new(coord.outputs["Generated"], mapping.inputs[0])
        l.new(mapping.outputs[0], tex.inputs["Vector"])
        mapping.location = (-700, 90)
    else:
        l.new(coord.outputs["Object"], tex.inputs["Vector"])
    ramp = n.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = .30
    ramp.color_ramp.elements[0].color = (*low, 1)
    ramp.color_ramp.elements[1].position = .72
    ramp.color_ramp.elements[1].color = (*high, 1)
    ramp.location = (-250, 140)
    l.new(tex.outputs["Fac"], ramp.inputs[0])
    # Linked architectural modules keep independent age / damp variation.
    obj_info=n.new("ShaderNodeObjectInfo")
    age=n.new("ShaderNodeMapRange")
    age.inputs["To Min"].default_value=.62
    age.inputs["To Max"].default_value=1.12
    l.new(obj_info.outputs["Random"],age.inputs[0])
    variation=n.new("ShaderNodeMixRGB")
    variation.blend_type="MULTIPLY"
    variation.inputs[0].default_value=1
    l.new(ramp.outputs[0],variation.inputs[1])
    l.new(age.outputs[0],variation.inputs[2])
    l.new(variation.outputs[0], p.inputs["Base Color"])
    if name.startswith("Wood"):
        wave=n.new("ShaderNodeTexWave")
        wave.wave_type="BANDS";wave.bands_direction="Y"
        wave.inputs["Scale"].default_value=27
        wave.inputs["Distortion"].default_value=8
        wave.inputs["Detail"].default_value=4
        wave.inputs["Detail Scale"].default_value=1.8
        l.new(coord.outputs["Generated"],wave.inputs["Vector"])
        g=n.new("ShaderNodeMapRange")
        g.inputs["To Min"].default_value=.18
        g.inputs["To Max"].default_value=1.05
        l.new(wave.outputs["Fac"],g.inputs[0])
        grain_mix=n.new("ShaderNodeMixRGB")
        grain_mix.blend_type="MULTIPLY";grain_mix.inputs[0].default_value=.7
        l.new(variation.outputs[0],grain_mix.inputs[1])
        l.new(g.outputs[0],grain_mix.inputs[2])
        l.new(grain_mix.outputs[0],p.inputs["Base Color"])
    rough = n.new("ShaderNodeMapRange")
    rough.inputs["To Min"].default_value = max(.2, roughness-.12)
    rough.inputs["To Max"].default_value = min(1, roughness+.1)
    l.new(tex.outputs["Fac"], rough.inputs[0])
    l.new(rough.outputs[0], p.inputs["Roughness"])
    fine = n.new("ShaderNodeTexNoise")
    fine.inputs["Scale"].default_value = 42 if name.startswith("Stone") else (110 if not grain else 26)
    fine.inputs["Detail"].default_value = 2
    l.new(tex.inputs["Vector"].links[0].from_socket, fine.inputs["Vector"])
    b = n.new("ShaderNodeBump")
    b.inputs["Strength"].default_value = .3
    b.inputs["Distance"].default_value = bump
    l.new(fine.outputs["Fac"], b.inputs["Height"])
    l.new(b.outputs[0], p.inputs["Normal"])
    p.location = (170, 160)
    return mat


def create_materials():
    noise_material("Stone | soot and damp limestone", (.016,.012,.009),
                   (.100,.076,.050), .89, 2.8, .047)
    noise_material("Stone | worn arch edges", (.029,.021,.014),
                   (.145,.108,.071), .83, 3.2, .026)
    noise_material("Floor | wet slate", (.012,.014,.012),
                   (.067,.059,.044), .73, 4, .026)
    noise_material("Wood | blackened oak", (.008,.003,.0015),
                   (.086,.032,.010), .78, 4.3, .016, (.75,42,9))
    noise_material("Wood | worn endgrain", (.019,.007,.0025),
                   (.115,.051,.014), .72, 5, .012, (28,1,8))
    noise_material("Iron | forged and oxidised", (.009,.009,.007),
                   (.055,.035,.015), .5, 9, .008, metallic=.82)
    noise_material("Bronze | tarnished edges", (.023,.012,.004),
                   (.18,.095,.029), .43, 8, .006, metallic=.8)
    noise_material("Cloth | charcoal wool", (.005,.005,.0045),
                   (.026,.023,.019), .95, 15, .002)
    noise_material("Cloth | dried crimson", (.009,.0006,.001),
                   (.083,.003,.006), .93, 7, .004)
    mat, p = material("Wax | aged ivory", (.48,.32,.145), .64)
    p.inputs["Subsurface Weight"].default_value = .055
    p.inputs["Subsurface Radius"].default_value = (.15,.08,.025)
    material("Void | shadow within hoods", (.0012,.001,.0008), 1)
    material("Wick | carbon", (.003,.002,.001), 1)
    mat, p = material("Flame | candle emission", (.6,.16,.025), .5)
    p.inputs["Emission Color"].default_value = (1,.38,.065,1)
    p.inputs["Emission Strength"].default_value = 12
    noise_material("Parchment | stained vellum", (.16,.085,.031),
                   (.46,.31,.14), .88, 7, .001)
    noise_material("Bone | yellowed ivory", (.085,.049,.022),
                   (.37,.24,.107), .79, 6, .003)
    noise_material("Leather | old binding", (.013,.003,.0015),
                   (.068,.014,.005), .77, 14, .004)
    noise_material("Leather | umber binding", (.011,.009,.003),
                   (.063,.047,.014), .82, 14, .004)
    material("Stain | old oil", (.01,.004,.0017), .31)
    material("Wax | sealing crimson", (.075,.003,.005), .62)
    for name in ["Wood | blackened oak","Wood | worn endgrain"]:
        M[name].node_tree.nodes.get("Principled BSDF").inputs["Specular IOR Level"].default_value=.22


def assign(obj, mat):
    obj.data.materials.clear()
    obj.data.materials.append(M[mat] if isinstance(mat, str) else mat)
    return obj


def mesh_obj(name, vertices, faces, mat, group):
    mesh = bpy.data.meshes.new(name+"_mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    o = bpy.data.objects.new(name, mesh)
    collection(group).objects.link(o)
    assign(o, mat)
    return o


def box(name, loc, size, mat, bevel=.02, group="Architecture", rotation=0):
    # Pre-bevel a reusable mesh once. Repeated modules share the mesh datablock.
    key = (tuple(round(x, 4) for x in size), round(bevel,4), mat)
    if key in BOX_CACHE:
        o = bpy.data.objects.new(name, BOX_CACHE[key])
        collection(group).objects.link(o)
    else:
        bpy.ops.mesh.primitive_cube_add()
        o = bpy.context.object
        o.name = name
        o.dimensions = size
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        assign(o, mat)
        if bevel:
            mod = o.modifiers.new("Worn edge bevel", "BEVEL")
            mod.width = bevel
            mod.segments = 2
            bpy.context.view_layer.objects.active = o
            bpy.ops.object.modifier_apply(modifier=mod.name)
        BOX_CACHE[key] = o.data
        move_to(o, group)
    o.location = loc
    o.rotation_euler[2] = rotation
    return o


def cylinder(name, loc, radius, depth, mat, vertices=12, group="Props"):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius,
                                      depth=depth, location=loc)
    o = bpy.context.object
    o.name = name
    assign(o, mat)
    move_to(o, group)
    for p in o.data.polygons:
        p.use_smooth = len(p.vertices) == 4
    return o


def sphere(name, loc, scale, mat, group="Props", subdivisions=2):
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=subdivisions, radius=1,
                                        location=loc)
    o = bpy.context.object
    o.name = name
    o.scale = scale
    assign(o, mat)
    move_to(o, group)
    for p in o.data.polygons:
        p.use_smooth = True
    return o


def rod(name, a, b, radius, mat, group="Props", vertices=10):
    a, b = Vector(a), Vector(b)
    o = cylinder(name, (a+b)/2, radius, (b-a).length, mat, vertices, group)
    o.rotation_euler = (b-a).to_track_quat("Z", "Y").to_euler()
    return o


def tube(name, points, radius, mat, group="Props", cyclic=False):
    curve = bpy.data.curves.new(name+"_curve", "CURVE")
    curve.dimensions = "3D"
    curve.resolution_u = 1
    curve.bevel_depth = radius
    curve.bevel_resolution = 1
    sp = curve.splines.new("POLY")
    sp.points.add(len(points)-1)
    for p, v in zip(sp.points, points):
        p.co = (*v,1)
    sp.use_cyclic_u = cyclic
    o = bpy.data.objects.new(name, curve)
    collection(group).objects.link(o)
    assign(o, mat)
    return o


def lathe(name, loc, profile, mat, group="Props", segments=20):
    verts = [(r*math.cos(2*math.pi*j/segments)+loc[0],
              r*math.sin(2*math.pi*j/segments)+loc[1], z+loc[2])
             for r,z in profile for j in range(segments)]
    faces = []
    for k in range(len(profile)-1):
        for j in range(segments):
            a=k*segments+j; b=k*segments+(j+1)%segments
            faces.append((a,b,b+segments,a+segments))
    o=mesh_obj(name,verts,faces,mat,group)
    for p in o.data.polygons:
        p.use_smooth=True
    return o


def create_floor():
    box("Floor foundation", (0,0,-.20), (ROOM_WIDTH+.5,ROOM_DEPTH+.5,.28),
        "Floor | wet slate", .02, "01 Floor")
    for row in range(math.ceil(ROOM_DEPTH/.94)):
        for col in range(math.ceil(ROOM_WIDTH/.93)):
            x=-ROOM_WIDTH/2+.15+col*.93+(row%2)*.22
            y=-ROOM_DEPTH/2+.4+row*.94
            box("FloorTile_%02d_%02d"%(row,col),(x,y,-.048+RNG.uniform(-.01,.01)),
                (.89,.90,.10),"Floor | wet slate",.013,"01 Floor",
                RNG.uniform(-.012,.012))


def create_walls():
    mat="Stone | soot and damp limestone"
    box("Back wall mass", (0,ROOM_DEPTH/2+.16,ROOM_HEIGHT/2),
        (ROOM_WIDTH+.8,.5,ROOM_HEIGHT), mat, .03,"02 Walls")
    for sign in [-1,1]:
        box("Side wall mass",(sign*(ROOM_WIDTH/2+.19),0,ROOM_HEIGHT/2),
            (.5,ROOM_DEPTH+.8,ROOM_HEIGHT),mat,.03,"02 Walls")
    box("Front wall enclosure",(0,-ROOM_DEPTH/2-.2,ROOM_HEIGHT/2),
        (ROOM_WIDTH+.8,.5,ROOM_HEIGHT),mat,.03,"02 Walls")
    box("Unlit stone ceiling",(0,0,ROOM_HEIGHT+.03),
        (ROOM_WIDTH+.8,ROOM_DEPTH+.8,.30),mat,.02,"02 Walls")
    for row in range(int(ROOM_HEIGHT/.49)):
        z=.24+row*.49
        for col in range(math.ceil(ROOM_WIDTH/.97)):
            x=-ROOM_WIDTH/2+.1+col*.97+(row%2)*.45
            if x>ROOM_WIDTH/2: continue
            box("StoneWall_Back_%02d_%02d"%(row,col),
                (x,ROOM_DEPTH/2-.15+RNG.uniform(-.022,.022),z),(.938,.39,.454),mat,.026,"02 Walls")
        for sign in [-1,1]:
            for col in range(math.ceil(ROOM_DEPTH/.99)):
                y=-ROOM_DEPTH/2+.35+col*.99+(row%2)*.48
                if y>ROOM_DEPTH/2: continue
                box("StoneWall_Side_%d_%02d_%02d"%(sign,row,col),
                    (sign*(ROOM_WIDTH/2-.02+RNG.uniform(-.018,.018)),y,z),
                    (.40,.954,.454),mat,.024,"02 Walls")


def create_gothic_arch(name, x, y, base, width, spring, thickness=.22,
                       depth=.35, group="03 Arches", stone=None):
    mat=stone or "Stone | worn arch edges"
    a=width/2
    for sign in [-1,1]:
        for j in range(6):
            h=(spring-base)/6
            box(name+"_pier",(x+sign*(a+thickness/2),y,base+h*(j+.5)),
                (thickness,depth,h-.014),mat,.012,group)
        for j in range(13):
            points=[]
            for t,outer in [(j+.025,False),(j+.975,False),
                            (j+.975,True),(j+.025,True)]:
                theta=math.pi-t/13*math.pi/3
                u=a+2*a*math.cos(theta)
                z=2*a*math.sin(theta)
                if outer:
                    u*=1+thickness/a
                    z*=1+thickness/(2*a)
                points.append((x+sign*(-u),spring+z))
            verts=[(px,y+dy,pz) for dy in [-depth/2,depth/2] for px,pz in points]
            faces=[(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),
                   (2,3,7,6),(3,0,4,7)]
            mesh_obj(name+"_voussoir",verts,faces,mat,group)


def create_columns():
    mat="Stone | worn arch edges"
    for sign in [-1,1]:
        for y in [-1.0,2.55,ROOM_DEPTH/2-1.4]:
            x=sign*(ROOM_WIDTH/2-.75)
            box("StoneColumn_square_plinth",(x,y,.20),(.9,.88,.40),mat,.055,"04 Columns")
            cylinder("StoneColumn_octagonal_foot",(x,y,.48),.43,.18,mat,8,"04 Columns")
            for k in range(7):
                cylinder("StoneColumn_shaft_module",(x,y,.90+k*.69),.29,.674,mat,12,"04 Columns")
            for dx,dy in [(0,-.27),(-.24,.10),(.24,.10)]:
                cylinder("StoneColumn_attached_shaft",(x+dx,y+dy,2.54),.10,4.05,mat,10,"04 Columns")
            box("StoneColumn_capital",(x,y,3.39),(.79,.77,.22),mat,.04,"04 Columns")
            cylinder("StoneColumn_capital_neck",(x,y,3.19),.40,.18,mat,8,"04 Columns")
        # The upper ribs are true geometry, but mostly above the low camera.
    for y in [-.95,2.60,ROOM_DEPTH/2-1.35]:
        create_gothic_arch("GothicRib",0,y,3.52,ROOM_WIDTH-1.95,3.70,.14,.22,"03 Arches")


def arch_shadow(name,x,y,width,spring,base=.1):
    a=width/2
    outline=[(-a,base),(-a,spring)]
    for j in range(1,17):
        theta=math.pi-j/16*math.pi/3
        outline.append((a+2*a*math.cos(theta),spring+2*a*math.sin(theta)))
    for j in range(15,-1,-1):
        theta=math.pi-j/16*math.pi/3
        outline.append((-a-2*a*math.cos(theta),spring+2*a*math.sin(theta)))
    outline.append((a,base))
    return mesh_obj(name,[(x+px,y,pz) for px,pz in outline],
                    [tuple(range(len(outline)))],"Void | shadow within hoods","05 Altar")


def create_altar():
    arch_shadow("Altar recessed darkness",0,6.64,3.14,1.20)
    create_gothic_arch("Great altar pointed arch",0,6.13,.0,3.15,.85,.27,.66)
    create_gothic_arch("Altar outer moulding",0,6.28,.0,3.76,.53,.10,.37)
    for sign in [-1,1]:
        x=sign*3.01
        arch_shadow("WallNiche shadow",x,6.60,1.42,1.35,.40)
        create_gothic_arch("WallNiche",x,6.37,.4,1.42,1.35,.16,.29)
        for dx in [-.12,.12]:
            cylinder("Altar colonette",(sign*1.94+dx,5.92,1.47),.12,2.88,
                     "Stone | worn arch edges",12,"05 Altar")
        box("Altar column capital",(sign*1.94,5.92,2.73),(.54,.53,.16),
            "Stone | worn arch edges",.022,"05 Altar")
    box("Altar upper step",(0,5.91,.14),(3.5,1.4,.28),"Stone | worn arch edges",.025,"05 Altar")
    box("Altar lower step",(0,5.68,.06),(4.0,1.7,.12),"Stone | soot and damp limestone",.025,"05 Altar")
    box("Altar stone pedestal",(0,6.04,.65),(2.18,.67,.88),"Stone | soot and damp limestone",.035,"05 Altar")
    box("Altar stone mensa",(0,5.94,1.13),(2.53,.99,.19),"Stone | worn arch edges",.035,"05 Altar")
    box("Crimson in the recess",(0,6.55,2.76),(.82,.035,1.84),"Cloth | dried crimson",0,"05 Altar")


def create_table():
    top=TABLE_HEIGHT
    for j in range(9):
        y=TABLE_CENTER_Y-TABLE_DEPTH/2+(j+.5)*TABLE_DEPTH/9
        box("TableTop_OakPlank_%02d"%j,(0,y,top-.115+RNG.uniform(-.004,.004)),
            (TABLE_WIDTH-RNG.uniform(0,.034),TABLE_DEPTH/9-.010,.23),
            "Wood | blackened oak",.018,"06 Council table")
    for x in [-TABLE_WIDTH/2+.12,TABLE_WIDTH/2-.12]:
        box("Table endgrain breadboard",(x,TABLE_CENTER_Y,top-.12),
            (.23,TABLE_DEPTH+.05,.25),"Wood | worn endgrain",.021,"06 Council table")
    for y in [TABLE_CENTER_Y-TABLE_DEPTH/2+.11,TABLE_CENTER_Y+TABLE_DEPTH/2-.11]:
        box("Table heavy apron",(0,y,.53),(TABLE_WIDTH-.25,.15,.30),
            "Wood | blackened oak",.019,"06 Council table")
    for x in [-2.2,2.2]:
        for y in [-1.94,-.02]:
            box("Table oak leg",(x,y,.32),(.29,.31,.64),"Wood | blackened oak",.025,"06 Council table")
        box("Table trestle foot",(x,-1,.09),(.43,2.65,.18),"Wood | blackened oak",.033,"06 Council table")
    box("Table low stretcher",(0,-1,.26),(4.62,.23,.22),"Wood | blackened oak",.02,"06 Council table")


def robe_mesh(name,x,y,scale):
    rings=[(.46,.29,.20),(.83,.285,.20),(1.15,.235,.155),
           (1.34,.30,.165),(1.44,.145,.12)]
    seg=20; v=[]
    for k,(z,rx,ry) in enumerate(rings):
        for j in range(seg):
            a=j*2*math.pi/seg
            fold=1+(.10 if k<3 else .035)*math.cos(j*math.pi)
            v.append((x+rx*math.cos(a)*fold*scale,
                      y+ry*math.sin(a)*fold*scale,.43+(z-.43)*scale))
    faces=[]
    for k in range(len(rings)-1):
        for j in range(seg):
            a=k*seg+j;b=k*seg+(j+1)%seg
            faces.append((a,b,b+seg,a+seg))
    return mesh_obj(name,v,faces,"Cloth | charcoal wool","07 Hooded placeholders")


def create_character_placeholders():
    for i,x in enumerate([-2.25,-1.50,-.75,0,.75,1.50,2.25]):
        y=1.00+[.13,-.01,.07,.21,.08,.0,.15][i]
        s=.91*[.97,1.04,.94,1.13,1.0,1.03,.96][i]
        robe_mesh("Tribunal_%d_cloaked_body"%(i+1),x,y,s)
        outer=[(0,1.93),(-.13,1.82),(-.205,1.64),(-.18,1.40),
               (0,1.36),(.18,1.40),(.205,1.64),(.13,1.82)]
        inner=[(0,1.80),(-.075,1.74),(-.118,1.62),(-.095,1.48),
               (0,1.43),(.095,1.48),(.118,1.62),(.075,1.74)]
        v=[]
        for ring,dy in [(outer,-.17),(inner,-.159),(outer,.12)]:
            for px,pz in ring:
                v.append((x+px*s,y+dy,.43+(pz-.43)*s))
        faces=[]
        for j in range(8):
            nj=(j+1)%8
            faces.extend([(j,nj,nj+8,j+8),(j,j+16,nj+16,nj)])
        faces.append(tuple(range(16,24)))
        mesh_obj("Tribunal_%d_open_hood"%(i+1),v,faces,
                 "Cloth | charcoal wool","07 Hooded placeholders")
        sphere("Tribunal_%d_shadowed_face"%(i+1),(x,y+.008,.43+1.19*s),
               (.115*s,.095,.17*s),"Void | shadow within hoods","07 Hooded placeholders")
        for sign in [-1,1]:
            shoulder=(x+sign*.23*s,y-.02,.43+.90*s)
            elbow=(x+sign*.28*s,y-.20,.98)
            wrist=(x+sign*.18*s,.45,.863)
            rod("Bent draped upper sleeve",shoulder,elbow,.093,
                "Cloth | charcoal wool","07 Hooded placeholders")
            rod("Forearm resting on table",elbow,wrist,.068,
                "Cloth | charcoal wool","07 Hooded placeholders")
            sphere("Simple dark glove",(wrist[0],.401,.857),(.057,.086,.033),
                   "Cloth | charcoal wool","07 Hooded placeholders",1)
        box("Simple council seat",(x,y+.10,.44),(.56,.48,.10),
            "Wood | blackened oak",.014,"07 Hooded placeholders")
        box("Shadowed chair back",(x,y+.26,1.0),(.51,.07,1.03),
            "Wood | blackened oak",.018,"07 Hooded placeholders")


def candle(name,x,y,z,height,radius=.038,power=1):
    group="08 Candles"
    cylinder(name+"_wax",(x,y,z+height/2),radius,height,"Wax | aged ivory",16,group)
    lathe(name+"_drip_dish",(x,y,z),[(0,-.038),(.075,-.025),(.078,.0),(.07,.012),(.055,-.009),(0,-.014)],
          "Bronze | tarnished edges",group,20)
    fz=z+height
    cylinder(name+"_wick",(x,y,fz+.009),.004,.033,"Wick | carbon",7,group)
    profile=[(.003,0),(.012,.014),(.015,.030),(.010,.049),(.002,.081),(0,.09)]
    flame=lathe(name+"_flame",(x,y,fz),profile,"Flame | candle emission",group,12)
    for vert in flame.data.vertices:
        vert.co.x+=.10*max(0.0,vert.co.z-fz)**1.2
    CANDLE_LOCATIONS.append((name,(x,y,fz+.055),power))


def candlestick(name,x,y,z,stem,height,power=1):
    lathe(name+"_holder",(x,y,z),[(0,0),(.115,0),(.118,.025),(.074,.050),
           (.042,.074),(.027,.105),(.025,stem-.055),(.061,stem-.03),(.065,stem),
           (0,stem)],"Bronze | tarnished edges","08 Candles",20)
    candle(name,x,y,z+stem,height,power=power)


def create_candles():
    # Foreground flames frame the council. No invisible frontal fill.
    for name,x,y,stem,h,p in [
        ("FrontLeft_tall",-1.40,-1.32,.25,.36,1),
        ("FrontLeft_low",-1.72,-1.08,.08,.25,.72),
        ("FrontLeft_stump",-1.15,-1.92,.02,.13,.22),
        ("FrontRight_tall",1.51,-1.21,.28,.39,1.10),
        ("FrontRight_low",1.22,-1.17,.06,.26,.75),
    ]:
        candlestick(name,x,y,TABLE_HEIGHT+.013,stem,h,p)
    for sign in [-1,1]:
        x=sign*2.87;y=2.38
        lathe("Back iron floor stand",(x,y,0),[(0,0),(.30,0),(.30,.07),(.10,.16),
               (.047,.30),(.037,1.48),(.095,1.57),(0,1.57)],
              "Iron | forged and oxidised","08 Candles",16)
        for k,(dx,dy,h) in enumerate([(-.23,0,.35),(0,.05,.56),(.23,.01,.40)]):
            rod("Candelabrum arm",(x,y,1.35),(x+dx,y+dy,1.6),.018,
                "Iron | forged and oxidised","08 Candles")
            candle("Back_%d_%d"%(sign,k),x+dx,y+dy,1.60,h,.042,1.4)
    for sign in [-1,1]:
        candlestick("Altar_%d"%sign,sign*.90,5.83,1.235,.12,.29,.8)
        candlestick("Niche_%d"%sign,sign*3.01,6.09,1.0,.14,.33,1.0)
        candlestick("Rear_bench_%d"%sign,sign*1.12,2.7,.84,.12,.34,1.15)
        box("Low stone candle shelf",(sign*1.12,2.8,.73),(.7,.5,.22),
            "Stone | soot and damp limestone",.025,"05 Altar")


def setup_volume():
    mat=bpy.data.materials.new("Air | thin candle smoke")
    mat.use_nodes=True
    n=mat.node_tree.nodes;n.clear()
    out=n.new("ShaderNodeOutputMaterial")
    vol=n.new("ShaderNodeVolumePrincipled")
    vol.inputs["Density"].default_value=FOG_DENSITY
    vol.inputs["Color"].default_value=(.32,.25,.19,1)
    vol.inputs["Anisotropy"].default_value=.22
    mat.node_tree.links.new(vol.outputs["Volume"],out.inputs["Volume"])
    box("Atmosphere volume (render only)",(0,0,(ROOM_HEIGHT-.2)/2),
        (ROOM_WIDTH-.15,ROOM_DEPTH-.1,ROOM_HEIGHT-.2),mat,0,"10 Atmosphere")


def point_light(name,loc,power,color,size=.035):
    data=bpy.data.lights.new(name,"POINT")
    data.energy=power;data.color=color;data.shadow_soft_size=size
    o=bpy.data.objects.new(name,data)
    collection("09 Lighting").objects.link(o);o.location=loc
    return o


def setup_lighting():
    world=bpy.data.worlds.new("Almost black world")
    world.use_nodes=True
    world.node_tree.nodes["Background"].inputs["Color"].default_value=(.12,.105,.09,1)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value=WORLD_STRENGTH
    bpy.context.scene.world=world
    for name,loc,power in CANDLE_LOCATIONS:
        point_light(name+"_light",loc,CANDLE_POWER*power,CANDLE_COLOR,.037)
    point_light("Faint crimson above altar",(0,6.10,3.07),RED_ACCENT_POWER,(.65,.003,.006),.35)


def setup_camera():
    data=bpy.data.cameras.new("Council camera 39mm")
    o=bpy.data.objects.new("Camera | low tribunal view",data)
    collection("11 Camera").objects.link(o)
    o.location=CAMERA_LOCATION
    o.rotation_euler=(Vector(CAMERA_TARGET)-o.location).to_track_quat("-Z","Y").to_euler()
    data.lens=CAMERA_FOCAL_LENGTH
    data.sensor_width=36
    data.clip_start=.05;data.clip_end=60
    data.dof.use_dof=True
    data.dof.focus_distance=5.8
    data.dof.aperture_fstop=7.1
    bpy.context.scene.camera=o
    return o


def create_props():
    """Sparse foreground framing; the middle stays open to the seven figures."""
    z=TABLE_HEIGHT+.015
    create_book("Left chained folio",(-1.05,-1.63,z),(.57,.43,.105),-.13)
    create_skull((-.99,-1.66,z+.108),.28)
    create_goblet("Left pewter cup",(-1.77,-.35,z),.96)
    create_book("Right lower codex",(1.09,-1.54,z),(.67,.46,.12),.08)
    create_book("Right middle codex",(1.11,-1.52,z+.123),(.61,.43,.088),-.07,
                "Leather | umber binding")
    create_book("Right upper codex",(1.06,-1.50,z+.214),(.57,.40,.095),.14)
    create_goblet("Right tarnished chalice",(.63,-1.35,z),1.06)
    create_reliquary((1.83,-.18,z))
    create_parchment("Loose parchment",(-.19,-1.15,z+.008),.64,.50,-.12)
    create_parchment("Folded vellum",(.11,-.81,z+.014),.40,.29,.24)
    cylinder("Broken wax seal",(.13,-1.27,z+.013),.043,.011,
             "Wax | sealing crimson",15,"12 Foreground props")
    tube("Seal cord",[(.12,-1.26,z+.015),(.05,-1.32,z+.009),(-.05,-1.36,z+.009),
                      (-.14,-1.32,z+.01)],.0024,"Leather | umber binding","12 Foreground props")
    create_chain((-.76,-1.90,z+.012))
    for i in range(7):
        x=RNG.uniform(.33,.61);y=RNG.uniform(-.48,-.28)
        cylinder("Small ritual token",(x,y,z+.004),RNG.uniform(.018,.028),.006,
                 "Bronze | tarnished edges",12,"12 Foreground props")
    create_table_age()
    age_candles()
    create_altar_cloth()
    create_wall_damage()
    # Curves are convenient to author, but the delivered props are mesh geometry.
    for o in list(bpy.context.scene.objects):
        if o.type=="CURVE":
            bpy.ops.object.select_all(action="DESELECT")
            o.select_set(True);bpy.context.view_layer.objects.active=o
            bpy.ops.object.convert(target="MESH")


def move_assembly(before,loc,rotation=0):
    # Flush newly assigned location / scale before reading matrix_world.
    # Without this, recent primitive scales can be replaced by stale matrices.
    bpy.context.view_layer.update()
    transform=Matrix.Translation(Vector(loc)) @ Matrix.Rotation(rotation,4,"Z")
    for o in set(bpy.data.objects)-before:
        o.matrix_world=transform @ o.matrix_world


def create_book(name,loc,size,rotation,leather="Leather | old binding"):
    before=set(bpy.data.objects);w,d,h=size;g="12 Foreground props"
    box(name+"_vellum_pages",(0,0,h/2),(w-.055,d-.035,h-.028),
        "Parchment | stained vellum",.009,g)
    for z in [.008,h-.008]:
        box(name+"_heavy_cover",(0,0,z),(w,d,.022),leather,.009,g)
    box(name+"_spine",(-w/2+.014,0,h/2),(.038,d,h),leather,.012,g)
    for xx in [-w*.31,w*.31]:
        box(name+"_leather_strap",(xx,0,h+.004),(.030,d+.013,.011),
            "Leather | umber binding",.004,g)
        box(name+"_brass_clasp",(xx,-d/2-.008,h-.009),(.060,.024,.032),
            "Bronze | tarnished edges",.004,g)
    for k in range(5):
        zz=.022+k*(h-.04)/5
        tube(name+"_page_edges",[(-w*.43,-d/2+.016,zz),(w*.44,-d/2+.017,zz+.001)],
             .0011,"Leather | umber binding",g)
    for sx in [-1,1]:
        for sy in [-1,1]:
            xx=sx*(w/2-.02);yy=sy*(d/2-.018)
            mesh_obj(name+"_corner_plate",[(xx,yy,h+.004),(xx-sx*.073,yy,h+.004),
                     (xx,yy-sy*.062,h+.004)],[(0,1,2)],"Bronze | tarnished edges",g)
            sphere(name+"_rivet",(xx-sx*.021,yy-sy*.021,h+.008),(.006,.006,.003),
                   "Bronze | tarnished edges",g,1)
    move_assembly(before,loc,rotation)


def create_skull(loc,rotation):
    before=set(bpy.data.objects);g="12 Foreground props";bone="Bone | yellowed ivory"
    cranium=sphere("Skull | carved cranium",(0,.019,.205),(.136,.113,.148),bone,g,3)
    bpy.context.view_layer.objects.active=cranium
    bpy.ops.object.select_all(action="DESELECT");cranium.select_set(True)
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
    for sign in [-1,1]:
        cut=sphere("Temporary orbital cutter",(sign*.059,-.077,.222),
                   (.049,.061,.050),bone,g,2)
        bpy.context.view_layer.objects.active=cut
        bpy.ops.object.select_all(action="DESELECT");cut.select_set(True)
        bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
        mod=cranium.modifiers.new("Orbital cavity","BOOLEAN")
        mod.operation="DIFFERENCE";mod.solver="EXACT";mod.object=cut
        bpy.context.view_layer.objects.active=cranium
        bpy.ops.object.modifier_apply(modifier=mod.name)
        bpy.data.objects.remove(cut,do_unlink=True)
        sphere("Skull | orbital darkness",(sign*.059,-.039,.219),
               (.043,.024,.044),"Void | shadow within hoods",g,2)
        sphere("Skull | cheekbone",(sign*.087,-.046,.149),(.042,.064,.036),bone,g,2)
        rod("Skull | jaw ramus",(sign*.089,-.008,.134),(sign*.079,-.082,.041),.019,bone,g,8)
    sphere("Skull | maxilla",(0,-.072,.116),(.074,.052,.037),bone,g,2)
    mesh_obj("Skull | nasal aperture",[(-.021,-.118,.173),(.021,-.118,.173),
             (.015,-.122,.135),(-.012,-.122,.128),(0,-.121,.190)],
             [(0,1,2,3),(0,4,1)],"Void | shadow within hoods",g)
    jaw=[(-.078,-.028,.055),(-.083,-.075,.032),(-.047,-.116,.026),(0,-.127,.024),
         (.047,-.116,.026),(.083,-.075,.032),(.078,-.028,.055)]
    tube("Skull | lower mandible",jaw,.020,bone,g)
    for row in [0,1]:
        for j in range(8):
            x=(j-3.5)*.0162
            yy=-.115+.025*(abs(x)/.058)**2
            zz=.077 if row==0 else .044
            box("Skull | worn tooth",(x,yy,zz),(.014,.021,.025 if row==0 else .021),
                bone,.004,g,rotation=0)
    tube("Skull | age fissure",[(-.025,-.064,.338),(-.022,-.083,.319),(-.009,-.092,.311),
         (-.015,-.106,.292)],.0011,"Stain | old oil",g)
    move_assembly(before,loc,rotation)


def create_goblet(name,loc,scale=1):
    profile=[(0,0),(.078,0),(.085,.009),(.081,.022),(.038,.038),(.022,.072),
             (.022,.177),(.040,.192),(.061,.208),(.087,.252),(.091,.313),
             (.088,.337),(.080,.338),(.080,.313),(.076,.260),(.050,.225),(0,.222)]
    lathe(name,loc,[(r*scale,z*scale) for r,z in profile],
          "Bronze | tarnished edges","12 Foreground props",28)
    cylinder(name+"_dark_dregs",(loc[0],loc[1],loc[2]+.235*scale),.052*scale,.002,
             "Stain | old oil",24,"12 Foreground props")


def create_reliquary(loc):
    before=set(bpy.data.objects);g="12 Foreground props";mat="Bronze | tarnished edges"
    box("Reliquary | stepped foot",(0,0,.024),(.38,.27,.048),mat,.012,g)
    box("Reliquary | upper foot",(0,0,.06),(.31,.23,.045),mat,.009,g)
    box("Reliquary | dark chamber",(0,.025,.263),(.225,.125,.33),
        "Void | shadow within hoods",.009,g)
    create_gothic_arch("Reliquary | lancet frame",0,-.065,.085,.22,.30,.023,.030,g,mat)
    for x in [-.15,.15]:
        for y in [-.1,.1]:
            rod("Reliquary | column",(x,y,.08),(x,y,.44),.012,mat,g)
            lathe("Reliquary | finial",(x,y,.425),[(.023,0),(.025,.033),(.013,.055),(0,.13)],mat,g,8)
    verts=[(-.16,-.11,.43),(.16,-.11,.43),(.16,.11,.43),(-.16,.11,.43),(0,0,.655)]
    mesh_obj("Reliquary | pitched roof",verts,[(0,1,4),(1,2,4),(2,3,4),(3,0,4)],mat,g)
    sphere("Reliquary | crown stud",(0,0,.66),(.022,.022,.027),mat,g,1)
    rod("Reliquary | crown needle",(0,0,.66),(0,0,.73),.008,mat,g)
    move_assembly(before,loc,-.12)


def create_parchment(name,loc,width,depth,rotation):
    before=set(bpy.data.objects);nx=12;ny=10;v=[]
    for j in range(ny+1):
        for i in range(nx+1):
            x=width*(i/nx-.5);y=depth*(j/ny-.5)
            edge=max(abs(i/nx-.5),abs(j/ny-.5))*2
            x+=RNG.uniform(-.006,.006) if i in [0,nx] else 0
            y+=RNG.uniform(-.006,.006) if j in [0,ny] else 0
            z=.005*math.sin(x*28+y*5)+.024*edge**8*(.55+.45*math.sin(y*30+x*20))
            v.append((x,y,z))
    f=[]
    for j in range(ny):
        for i in range(nx):
            a=j*(nx+1)+i
            f.append((a,a+1,a+nx+2,a+nx+1))
    mesh_obj(name,v,f,"Parchment | stained vellum","12 Foreground props")
    # No letters, player labels or UI text are present on the vellum.
    move_assembly(before,loc,rotation)


def create_chain(loc):
    for i in range(25):
        a=i*.23
        x=loc[0]+.20*math.cos(a);y=loc[1]+.105*math.sin(a)
        tangent=a+math.pi/2;points=[]
        for j in range(12):
            t=j*math.tau/12
            u=.020*math.cos(t);v=.012*math.sin(t)
            zz=loc[2]+(.010 if i%2 else .003)
            points.append((x+u*math.cos(tangent)-v*math.sin(tangent),
                y+u*math.sin(tangent)+v*math.cos(tangent),
                zz+(.009*math.sin(t) if i%2 else 0)))
        tube("Book chain | iron link",points,.0028,"Iron | forged and oxidised",
             "12 Foreground props",True)


def irregular_patch(name,x,y,z,rx,ry,mat):
    v=[(x,y,z)]
    for j in range(20):
        a=j*math.tau/20;d=RNG.uniform(.74,1.18)
        v.append((x+math.cos(a)*rx*d,y+math.sin(a)*ry*d,z+RNG.uniform(0,.0009)))
    return mesh_obj(name,v,[(0,j+1,(j+1)%20+1) for j in range(20)],
                    mat,"12 Foreground props")


def create_table_age():
    z=TABLE_HEIGHT+.008
    for i in range(75):
        x=RNG.uniform(-2.85,2.85);y=RNG.uniform(-2.46,.40)
        length=RNG.uniform(.035,.30)
        end_y=y+RNG.uniform(-.028,.028)
        tube("Oak | old incision",[(x,y,z),(x+length*.55,(y+end_y)/2,z+.0005),
             (x+length,end_y,z)],RNG.uniform(.00065,.0014),
             "Wood | worn endgrain" if i%4==0 else "Stain | old oil","12 Foreground props")
    for x,y,rx,ry in [(-.77,-1.28,.11,.055),(.7,-1.41,.15,.068),
                     (-1.5,-.76,.11,.07),(.38,-1.81,.17,.037),(-.35,-.16,.14,.045)]:
        irregular_patch("Oak | dried oil stain",x,y,z,.8*rx,ry,"Stain | old oil")
    for i in range(22):
        x=RNG.choice([-1,1])*RNG.uniform(1.1,1.5);y=RNG.uniform(-1.6,-.86)
        r=RNG.uniform(.005,.026)
        irregular_patch("Wax | spilled drop",x,y,z+.003,r,r*.65,"Wax | aged ivory")
    for x in [-2.8,2.8]:
        for y in [-2.24,-1.60,-.91,-.25]:
            cylinder("Oak | black iron pin",(x,y,z),.012,.006,
                     "Iron | forged and oxidised",8,"12 Foreground props")
    # A handful of actual chips on the highly visible front edge.
    for i in range(14):
        x=RNG.uniform(-1.3,1.3)
        box("Oak | exposed edge splinter",(x,-2.502,.797-RNG.uniform(0,.022)),
            (RNG.uniform(.015,.065),.004,.008),"Wood | worn endgrain",.002,"12 Foreground props")


def age_candles():
    for o in list(collection("08 Candles").objects):
        if not o.name.endswith("_wax"): continue
        x,y,z=o.location;r=o.dimensions.x/2;h=o.dimensions.z
        for i in range(6):
            a=RNG.uniform(0,math.tau);length=RNG.uniform(.035,min(.18,h*.8))
            xx=x+math.cos(a)*(r+.001);yy=y+math.sin(a)*(r+.001)
            top=z+h/2-RNG.uniform(0,.018)
            rod("Wax | old rivulet",(xx,yy,top),(xx,yy,top-length),RNG.uniform(.003,.006),
                "Wax | aged ivory","12 Foreground props",7)
            sphere("Wax | hanging tear",(xx,yy,top-length),(.006,.006,.010),
                   "Wax | aged ivory","12 Foreground props",1)
        cylinder("Wax | burnt well",(x,y,z+h/2+.001),r*.40,.002,
                 "Wick | carbon",14,"12 Foreground props")


def create_altar_cloth():
    bpy.data.objects["Crimson in the recess"].hide_render=True
    bpy.data.objects["Crimson in the recess"].hide_viewport=True
    g="13 Altar dressing";nx=16;ny=24;v=[]
    for j in range(ny+1):
        t=j/ny
        for i in range(nx+1):
            u=i/nx;x=(u-.5)*.84
            z=3.51-2.05*t
            if j==ny: z+=.10*abs(math.sin(i*2.2))+.12*(1-abs(u-.5)*2)
            y=6.45+.045*math.cos(u*math.tau*4)+.012*math.sin(t*15+u*8)
            v.append((x,y,z))
    f=[]
    for j in range(ny):
        for i in range(nx):
            a=j*(nx+1)+i;f.append((a,a+1,a+nx+2,a+nx+1))
    mesh_obj("Torn altar hanging | deep crimson",v,f,"Cloth | dried crimson",g)
    rod("Altar hanging | iron rod",(-.49,6.46,3.51),(.49,6.46,3.51),.022,
        "Iron | forged and oxidised",g)
    # A nearly lost, non-emissive almond-shaped heraldic mark.
    points=[(-.23,6.37,3.03),(-.12,6.37,3.103),(0,6.37,3.121),
            (.12,6.37,3.103),(.23,6.37,3.03),(.12,6.37,2.957),
            (0,6.37,2.941),(-.12,6.37,2.957)]
    tube("Obscured heraldic eye",points,.008,"Iron | forged and oxidised",g,True)
    mesh_obj("Obscured heraldic pupil",[(0,6.363,3.105),(.025,6.363,3.03),
            (0,6.363,2.963),(-.025,6.363,3.03)],[(0,1,2,3)],
            "Bronze | tarnished edges",g)


def create_wall_damage():
    for x,z in [(-2.20,2.3),(2.7,3.0),(-3.68,1.45),(1.48,3.9)]:
        pts=[(x,6.635,z),(x+.037,6.634,z-.16),(x-.022,6.634,z-.29),
             (x+.055,6.634,z-.45),(x+.035,6.634,z-.51)]
        tube("Stone | old fissure",pts,.004,"Void | shadow within hoods","14 Damage")
    for sign in [-1,1]:
        for i in range(11):
            x=sign*RNG.uniform(3.1,4.2);y=RNG.uniform(1.5,6.5)
            sphere("Fallen limestone chip",(x,y,.035),
                   (RNG.uniform(.04,.12),RNG.uniform(.035,.09),RNG.uniform(.015,.05)),
                   "Stone | soot and damp limestone","14 Damage",1)


def setup_render(samples=None,width=None):
    scene=bpy.context.scene
    scene.render.engine="CYCLES"
    scene.cycles.samples=samples or SAMPLES[STAGE]
    scene.cycles.use_denoising=True
    scene.cycles.adaptive_threshold=.015 if STAGE=="final" else .04
    scene.cycles.max_bounces=8
    scene.cycles.diffuse_bounces=3
    scene.cycles.glossy_bounces=4
    scene.cycles.transmission_bounces=4
    scene.cycles.volume_bounces=2
    scene.cycles.sample_clamp_indirect=3
    scene.cycles.seed=SEED
    scene.cycles.use_light_tree=True
    prefs=bpy.context.preferences.addons["cycles"].preferences
    try:
        prefs.compute_device_type="METAL"
        prefs.get_devices()
        gpu=False
        for d in prefs.devices:
            d.use=d.type=="METAL"
            gpu|=d.use
        scene.cycles.device="GPU" if gpu else "CPU"
    except Exception as e:
        print("GPU unavailable, using CPU:",e)
        scene.cycles.device="CPU"
    scene.render.resolution_x=width or RENDER_WIDTH
    scene.render.resolution_y=round((width or RENDER_WIDTH)*RENDER_HEIGHT/RENDER_WIDTH)
    scene.render.resolution_percentage=100
    scene.render.image_settings.file_format="PNG"
    scene.render.image_settings.color_mode="RGB"
    scene.render.image_settings.color_depth="8"
    scene.render.filepath=str(ROOT/"renders"/("chapel_"+STAGE+".png"))
    scene.view_settings.view_transform="AgX"
    try: scene.view_settings.look="AgX - Medium High Contrast"
    except TypeError: scene.view_settings.look="Medium High Contrast"
    scene.view_settings.exposure=EXPOSURE
    scene.view_settings.gamma=1
    scene.render.film_transparent=False
    scene.use_nodes=True
    nodes=scene.node_tree.nodes;nodes.clear()
    rl=nodes.new("CompositorNodeRLayers")
    glow=nodes.new("CompositorNodeGlare")
    glow.glare_type="FOG_GLOW";glow.quality="HIGH"
    glow.threshold=1.5;glow.size=7;glow.mix=-.90
    output=nodes.new("CompositorNodeComposite")
    scene.node_tree.links.new(rl.outputs["Image"],glow.inputs["Image"])
    scene.node_tree.links.new(glow.outputs["Image"],output.inputs["Image"])


def scene_statistics():
    deps=bpy.context.evaluated_depsgraph_get()
    triangles=0;unique_triangles=0;seen=set()
    by_collection={}
    for o in bpy.context.scene.objects:
        if o.type not in {"MESH","CURVE"}: continue
        ev=o.evaluated_get(deps)
        mesh=ev.to_mesh()
        mesh.calc_loop_triangles()
        count=len(mesh.loop_triangles)
        triangles+=count
        key=o.data.as_pointer()
        if key not in seen: unique_triangles+=count;seen.add(key)
        c=o.users_collection[0].name
        by_collection[c]=by_collection.get(c,0)+count
        ev.to_mesh_clear()
    return {"stage":STAGE,"blender":bpy.app.version_string,
            "triangles_evaluated":triangles,"triangles_unique_meshes":unique_triangles,
            "triangles_by_collection":by_collection,"objects":len(bpy.context.scene.objects),
            "materials":len([m for m in bpy.data.materials if m.users]),
            "external_image_textures":0,"external_texture_memory_bytes":0,
            "texture_memory_note":"All surface textures are procedural. Render buffers and GPU working memory excluded.",
            "render_samples":bpy.context.scene.cycles.samples,
            "render_resolution":[bpy.context.scene.render.resolution_x,bpy.context.scene.render.resolution_y],
            "denoising":bpy.context.scene.cycles.use_denoising,
            "light_count":len([o for o in bpy.context.scene.objects if o.type=="LIGHT"]),
            "render_device":bpy.context.scene.cycles.device,
            "parameters":{"room_m":[ROOM_WIDTH,ROOM_DEPTH,ROOM_HEIGHT],
            "table_m":[TABLE_WIDTH,TABLE_DEPTH,TABLE_HEIGHT],"camera_mm":CAMERA_FOCAL_LENGTH,
            "camera_location":CAMERA_LOCATION,"camera_target":CAMERA_TARGET,
            "candle_power_w":CANDLE_POWER,"fog_density":FOG_DENSITY,
            "candle_color":CANDLE_COLOR,"red_accent_power_w":RED_ACCENT_POWER,
            "world_strength":WORLD_STRENGTH,"exposure":EXPOSURE},
            "godot_note":"Modular meshes, metres, Principled materials, no subdivision. Procedural shaders need baking or recreation; Cycles atmosphere and grading need recreation in Godot. No engine integration performed."}


def save_scene():
    folder=ROOT/"assets"/"chapel";folder.mkdir(parents=True,exist_ok=True)
    scene=bpy.context.scene
    bpy.context.preferences.filepaths.save_version=0
    scene["art_direction"]="Ancient candle-lit secret tribunal / forbidden chapel"
    scene["reference_status"]="No reference image was supplied with this request; built from the written brief."
    scene["build_stage"]=STAGE
    scene["seed"]=SEED
    # A clean camera view when opening the blend, without changing user settings.
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type=="VIEW_3D":
                area.spaces.active.region_3d.view_perspective="CAMERA"
                area.spaces.active.overlay.show_overlays=False
                area.spaces.active.shading.type="MATERIAL"
                area.spaces.active.shading.use_scene_world=True
                area.spaces.active.shading.use_scene_lights=True
    bpy.context.view_layer.objects.active=scene.camera
    bpy.ops.object.select_all(action="DESELECT")
    scene.camera.select_set(True)
    bpy.ops.wm.save_as_mainfile(filepath=str(folder/"black_chapel.blend"))
    report=scene_statistics()
    (folder/("statistics_"+STAGE+".json")).write_text(json.dumps(report,indent=2),encoding="utf-8")
    print("CHAPEL_STATISTICS",json.dumps(report))


def render_preview():
    folder=ROOT/"renders";folder.mkdir(parents=True,exist_ok=True)
    bpy.context.scene.render.filepath=str(folder/("chapel_"+STAGE+".png"))
    bpy.ops.render.render(write_still=True)


def build(stage,args):
    global STAGE
    STAGE=stage
    clear_scene()
    create_materials()
    create_floor()
    create_walls()
    create_columns()
    create_altar()
    create_table()
    create_character_placeholders()
    create_candles()
    if STAGE=="final": create_props()
    setup_volume()
    setup_lighting()
    setup_camera()
    setup_render(args.samples,args.width)
    validate_scene()
    save_scene()
    if not args.no_render: render_preview()
    print("CHAPEL_STAGE_COMPLETE",stage,flush=True)


def validate_scene():
    bpy.context.view_layer.update()
    if STAGE=="final":
        for o in collection("12 Foreground props").objects:
            if max(o.dimensions)>1.6:
                raise RuntimeError("Unexpected oversized foreground object: "+o.name)
    scene=bpy.context.scene
    assert scene.camera is not None and scene.render.engine=="CYCLES"
    assert len([o for o in bpy.data.objects if "cloaked_body" in o.name])==7
    assert all(o.type!="CURVE" for o in scene.objects) if STAGE=="final" else True
    print("CHAPEL_VALIDATION_OK",STAGE,flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage",choices=["all","blockout","lighting","final"],default="all")
    parser.add_argument("--samples",type=int)
    parser.add_argument("--width",type=int)
    parser.add_argument("--no-render",action="store_true")
    args=parser.parse_args(sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else [])
    for stage in (["blockout","lighting","final"] if args.stage=="all" else [args.stage]):
        build(stage,args)


if __name__=="__main__": main()
