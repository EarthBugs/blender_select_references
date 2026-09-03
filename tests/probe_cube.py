# -*- coding: utf-8 -*-
"""探针：查明 Cube 为何出现在 Image 扫描结果中（一次性诊断，无副作用）。"""
import bpy
import sys

sys.path.insert(0, r"C:\Users\EarthBugs\Documents\current_working\20260901_blender_select_references")
import select_references as sr

res = {}

# 1) Cube 的材质槽与节点明细
cube = bpy.data.objects.get("Cube")
cube_info = []
if cube is not None:
    res["cube_slots"] = [(s.link, s.material.name if s.material else None) for s in cube.material_slots]
    for s in cube.material_slots:
        m = s.material
        if m and m.use_nodes and m.node_tree:
            for n in m.node_tree.nodes:
                entry = {"bl_idname": n.bl_idname}
                if n.bl_idname in ("ShaderNodeTexImage", "ShaderNodeTexEnvironment"):
                    entry["image"] = n.image.name if n.image else None
                if n.bl_idname == "ShaderNodeGroup":
                    entry["node_tree"] = n.node_tree.name if n.node_tree else None
                cube_info.append({m.name: entry})
res["cube_nodes"] = cube_info

# 2) 全场景所有材质的树名与图像纹理节点
all_mats = []
for m in bpy.data.materials:
    imgs = []
    if m.use_nodes and m.node_tree:
        for n in m.node_tree.nodes:
            if n.bl_idname in ("ShaderNodeTexImage", "ShaderNodeTexEnvironment"):
                imgs.append(n.image.name if n.image else None)
    all_mats.append({"material": m.name, "tree": m.node_tree.name if m.node_tree else None,
                     "tex_images": imgs})
res["all_materials"] = all_mats

# 3) 当前 SR_TEST_ 图像及引用者
res["sr_images"] = [i.name for i in bpy.data.images if i.name.startswith("SR_TEST_")]

# 4) 探针：全新图像跑插件内部函数，看 Cube 是否重现
probe = bpy.data.images.new("SR_PROBE_IMG", 8, 8)
trees = sr._shader_trees_with_image(probe)
res["probe_hit_trees"] = [t.name for t in trees]
users = sr.find_referencing_objects(probe)
res["probe_users"] = sorted(o.name for o in users)
worlds = sr._worlds_using_image(probe)
res["probe_worlds"] = [w.name for w in worlds]
bpy.data.images.remove(probe, do_unlink=True)

result = res
