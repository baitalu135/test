"""
ZBrush-like Divide tool for Autodesk Maya.

How to use:
1. In Maya, open Script Editor > Python tab.
2. Execute this file, or paste and run:

   import sys
   sys.path.append(r"C:\\Users\\atoyr\\Documents\\Codex\\2026-08-16\\new-chat\\outputs")
   import zbrush_divide_maya
   zbrush_divide_maya.show()

What it does:
- Tags the selected polygon mesh as SDiv level 1.
- Divide creates a new higher-resolution mesh level.
- Smt ON uses Maya polySmooth continuity 1.0 and allows hard edges to smooth.
- Smt OFF uses Maya polySmooth continuity 0.0 and preserves hard edges.
- Lower/Higher/SDiv switch visibility between stored mesh levels.
- Delete Lower/Delete Higher remove stored levels around the active level.
- Keep Previous SDiv Levels can be disabled to reduce memory and scene weight.
- Crease selected edges with a Maya crease value and a ZBrush-like CreaseLvl.
- Dynamic Subdiv uses Maya Smooth Mesh Preview.
- Apply Dynamic Subdiv converts the preview to real polygons when Maya supports it.
- Feature-aware decimation protects high-curvature silhouette features while
  reducing flatter areas first.
- Smart Remesh uses Maya Retopologize to rebuild the mesh as mostly uniform quads
  while preserving silhouette features.
- Smart Panel Remesh simplifies hard-surface dense meshes into large panels while
  preserving bevel/silhouette loops.

Limitations:
- This is a practical Maya approximation, not ZBrush's internal sculpting
  multiresolution engine. Edits made on one level are not automatically
  propagated as sculpt deltas to other levels.
"""

import time

import maya.cmds as cmds
import maya.mel as mel
try:
    import maya.api.OpenMaya as om
except Exception:
    om = None


WINDOW_NAME = "zbrushDivideForMayaWindow"
ATTR_ASSET_ID = "zdivAssetId"
ATTR_LEVEL = "zdivLevel"
ATTR_GROUP = "zdivGroup"
ATTR_CREASE_LEVEL = "zdivCreaseLevel"
ATTR_DYNAMIC_LEVEL = "zdivDynamicLevel"
ZDIV_ATTRS = (
    ATTR_ASSET_ID,
    ATTR_LEVEL,
    ATTR_GROUP,
    ATTR_CREASE_LEVEL,
    ATTR_DYNAMIC_LEVEL,
)


def _long_name(node):
    matches = cmds.ls(node, long=True) or []
    return matches[0] if matches else node


def _selected_transform():
    selection = cmds.ls(selection=True, long=True) or []
    if not selection:
        raise RuntimeError("ポリゴンメッシュを1つ選択してください。")

    objects = cmds.ls(selection, objectsOnly=True, long=True) or []
    node = objects[0] if objects else selection[0].split(".", 1)[0]
    if cmds.nodeType(node) == "mesh":
        parents = cmds.listRelatives(node, parent=True, fullPath=True) or []
        if not parents:
            raise RuntimeError("選択メッシュのtransformが見つかりません。")
        node = parents[0]

    shapes = cmds.listRelatives(node, shapes=True, noIntermediate=True, fullPath=True) or []
    mesh_shapes = [shape for shape in shapes if cmds.nodeType(shape) == "mesh"]
    if not mesh_shapes:
        raise RuntimeError("ポリゴンメッシュのtransformを選択してください。")

    return _long_name(node)


def _has_attr(node, attr):
    return cmds.objExists("{0}.{1}".format(node, attr))


def _get_string_attr(node, attr):
    if not _has_attr(node, attr):
        return None
    return cmds.getAttr("{0}.{1}".format(node, attr))


def _get_int_attr(node, attr):
    if not _has_attr(node, attr):
        return None
    return int(cmds.getAttr("{0}.{1}".format(node, attr)))


def _ensure_string_attr(node, attr, value):
    if not _has_attr(node, attr):
        cmds.addAttr(node, longName=attr, dataType="string")
    cmds.setAttr("{0}.{1}".format(node, attr), value, type="string")


def _ensure_int_attr(node, attr, value):
    if not _has_attr(node, attr):
        cmds.addAttr(node, longName=attr, attributeType="long")
    cmds.setAttr("{0}.{1}".format(node, attr), int(value))


def _mesh_shapes(node):
    shapes = cmds.listRelatives(node, shapes=True, noIntermediate=True, fullPath=True) or []
    return [shape for shape in shapes if cmds.nodeType(shape) == "mesh"]


def _selected_edges():
    selection = cmds.ls(selection=True, flatten=True, long=True) or []
    edges = cmds.filterExpand(selection, selectionMask=32, fullPath=True) or []
    return edges


def _all_edges(node):
    edges = cmds.polyListComponentConversion(node, toEdge=True) or []
    return cmds.filterExpand(edges, selectionMask=32, fullPath=True) or []


def _clear_all_creases_and_hard_edges(node):
    edges = _all_edges(node)
    if not edges:
        return

    previous_selection = cmds.ls(selection=True, long=True) or []
    try:
        try:
            cmds.polyCrease(edges, value=0.0)
        except Exception:
            pass
        cmds.select(edges, replace=True)
        cmds.polySoftEdge(angle=180, constructionHistory=False)
    finally:
        if previous_selection:
            cmds.select(previous_selection, replace=True)


def _asset_id_for(node):
    return _get_string_attr(node, ATTR_ASSET_ID)


def _level_for(node):
    return _get_int_attr(node, ATTR_LEVEL)


def _group_for(node):
    group_name = _get_string_attr(node, ATTR_GROUP)
    if group_name and cmds.objExists(group_name):
        return _long_name(group_name)
    return None


def _candidate_zdiv_transforms():
    pattern = "*.{}".format(ATTR_ASSET_ID)
    try:
        nodes = cmds.ls(pattern, objectsOnly=True, long=True) or []
        if nodes:
            return nodes
    except Exception:
        pass
    return cmds.ls(type="transform", long=True) or []


def _levels_for_asset(asset_id):
    transforms = _candidate_zdiv_transforms()
    levels = []
    for transform in transforms:
        if _asset_id_for(transform) != asset_id:
            continue
        level = _level_for(transform)
        if level is None:
            continue
        levels.append((level, transform))
    levels.sort(key=lambda item: item[0])
    return levels


def _active_level_node(asset_id):
    levels = _levels_for_asset(asset_id)
    visible = [item for item in levels if cmds.getAttr("{0}.visibility".format(item[1]))]
    if visible:
        return visible[-1]
    if levels:
        return levels[-1]
    return None


def _unique_asset_id():
    return "zdiv_{0}".format(int(time.time() * 1000))


def initialize_selected():
    node = _selected_transform()
    asset_id = _asset_id_for(node)

    if asset_id:
        return asset_id, _level_for(node) or 1, node

    asset_id = _unique_asset_id()
    short = node.split("|")[-1]
    group = cmds.group(empty=True, name="{0}_ZDiv".format(short))
    parent = cmds.listRelatives(node, parent=True, fullPath=True)
    if parent:
        group = cmds.parent(group, parent[0])[0]
    node = cmds.parent(node, group)[0]
    node = _long_name(node)
    group = _long_name(group)

    _ensure_string_attr(node, ATTR_ASSET_ID, asset_id)
    _ensure_int_attr(node, ATTR_LEVEL, 1)
    _ensure_string_attr(node, ATTR_GROUP, group)
    _ensure_int_attr(node, ATTR_CREASE_LEVEL, 0)
    _ensure_int_attr(node, ATTR_DYNAMIC_LEVEL, 2)
    cmds.rename(node, "{0}_SDiv01".format(short))
    node = _long_name("{0}|{1}_SDiv01".format(group, short))

    cmds.select(node, replace=True)
    return asset_id, 1, node


def _set_active_level(asset_id, target_level):
    levels = _levels_for_asset(asset_id)
    if not levels:
        raise RuntimeError("SDivレベルが見つかりません。")

    target_node = None
    for level, node in levels:
        is_target = level == target_level
        cmds.setAttr("{0}.visibility".format(node), bool(is_target))
        if is_target:
            target_node = node

    if not target_node:
        raise RuntimeError("SDiv {0} が見つかりません。".format(target_level))

    cmds.select(target_node, replace=True)
    _refresh_ui()
    return target_node


def current_state():
    node = _selected_transform()
    asset_id = _asset_id_for(node)
    if not asset_id:
        asset_id, _, node = initialize_selected()

    active = _active_level_node(asset_id)
    if not active:
        raise RuntimeError("アクティブなSDivレベルが見つかりません。")

    levels = _levels_for_asset(asset_id)
    return {
        "asset_id": asset_id,
        "active_level": active[0],
        "active_node": active[1],
        "min_level": levels[0][0],
        "max_level": levels[-1][0],
        "levels": levels,
    }


def divide(smooth=True, keep_previous=True):
    asset_id, _, node = initialize_selected()
    state = current_state()

    cmds.undoInfo(openChunk=True)
    cmds.refresh(suspend=True)
    try:
        if state["active_level"] != state["max_level"]:
            cmds.warning("ZBrushと同様、Divideは最高SDivで実行してください。最高SDivへ切り替えます。")
            node = _set_active_level(asset_id, state["max_level"])
            state = current_state()

        source = state["active_node"]
        next_level = state["max_level"] + 1
        group = _group_for(source)
        source_short = source.split("|")[-1].rsplit("_SDiv", 1)[0]

        duplicate = cmds.duplicate(source, name="{0}_SDiv{1:02d}".format(source_short, next_level))[0]
        if group:
            current_parent = cmds.listRelatives(duplicate, parent=True, fullPath=True)
            if not current_parent or _long_name(current_parent[0]) != group:
                duplicate = cmds.parent(duplicate, group)[0]
        duplicate = _long_name(duplicate)

        _ensure_string_attr(duplicate, ATTR_ASSET_ID, asset_id)
        _ensure_int_attr(duplicate, ATTR_LEVEL, next_level)
        _ensure_string_attr(duplicate, ATTR_GROUP, group or "")

        crease_level = _get_int_attr(source, ATTR_CREASE_LEVEL) or 0
        preserve_crease_level = smooth and crease_level > 0 and state["active_level"] < crease_level
        _ensure_int_attr(duplicate, ATTR_CREASE_LEVEL, crease_level)
        if smooth and crease_level > 0 and not preserve_crease_level:
            _clear_all_creases_and_hard_edges(duplicate)
        continuity = 1.0 if smooth else 0.0
        keep_hard_edge = True if (preserve_crease_level or not smooth) else False
        cmds.polySmooth(
            duplicate,
            divisions=1,
            continuity=continuity,
            keepBorder=True,
            keepHardEdge=keep_hard_edge,
            keepSelectionBorder=False,
            keepTessellation=True,
            constructionHistory=False,
        )

        if keep_previous:
            for _, level_node in state["levels"]:
                if cmds.objExists(level_node):
                    cmds.setAttr("{0}.visibility".format(level_node), False)
        else:
            old_levels = [level_node for _, level_node in state["levels"] if cmds.objExists(level_node)]
            if old_levels:
                cmds.delete(old_levels)

        cmds.setAttr("{0}.visibility".format(duplicate), True)
        cmds.select(duplicate, replace=True)
        _refresh_ui()
        return duplicate
    finally:
        cmds.refresh(suspend=False)
        cmds.undoInfo(closeChunk=True)


def crease_selected_edges(crease_value=10.0, crease_level=2):
    node = _selected_transform()
    edges = _selected_edges()
    if not edges:
        raise RuntimeError("Creaseを設定するエッジを選択してください。")

    _ensure_int_attr(node, ATTR_CREASE_LEVEL, int(crease_level))
    try:
        cmds.polyCrease(edges, value=float(crease_value))
    except Exception as exc:
        raise RuntimeError("MayaのpolyCreaseに失敗しました: {0}".format(exc))

    # Hard edges give classic polySmooth a practical way to protect creased edges.
    previous_selection = cmds.ls(selection=True, long=True) or []
    try:
        cmds.select(edges, replace=True)
        cmds.polySoftEdge(angle=0, constructionHistory=False)
    finally:
        if previous_selection:
            cmds.select(previous_selection, replace=True)
    _refresh_ui()


def uncrease_selected_edges():
    edges = _selected_edges()
    if not edges:
        raise RuntimeError("Creaseを解除するエッジを選択してください。")

    try:
        cmds.polyCrease(edges, value=0.0)
    except Exception as exc:
        raise RuntimeError("MayaのpolyCrease解除に失敗しました: {0}".format(exc))

    previous_selection = cmds.ls(selection=True, long=True) or []
    try:
        cmds.select(edges, replace=True)
        cmds.polySoftEdge(angle=180, constructionHistory=False)
    finally:
        if previous_selection:
            cmds.select(previous_selection, replace=True)
    _refresh_ui()


def set_crease_level(crease_level):
    node = _selected_transform()
    _ensure_int_attr(node, ATTR_CREASE_LEVEL, int(crease_level))
    _refresh_ui()


def set_dynamic_subdiv(enabled=True, level=2):
    node = _selected_transform()
    level = max(0, int(level))
    _ensure_int_attr(node, ATTR_DYNAMIC_LEVEL, level)

    for shape in _mesh_shapes(node):
        if _has_attr(shape, "displaySmoothMesh"):
            cmds.setAttr("{0}.displaySmoothMesh".format(shape), 2 if enabled else 0)
        if _has_attr(shape, "smoothLevel"):
            cmds.setAttr("{0}.smoothLevel".format(shape), level)
        if _has_attr(shape, "renderSmoothLevel"):
            cmds.setAttr("{0}.renderSmoothLevel".format(shape), level)
        if _has_attr(shape, "useSmoothPreviewForRender"):
            cmds.setAttr("{0}.useSmoothPreviewForRender".format(shape), bool(enabled))
    _refresh_ui()


def apply_dynamic_subdiv():
    node = _selected_transform()
    level = _get_int_attr(node, ATTR_DYNAMIC_LEVEL) or 1
    previous_selection = cmds.ls(selection=True, long=True) or []

    cmds.undoInfo(openChunk=True)
    cmds.refresh(suspend=True)
    try:
        cmds.select(node, replace=True)
        try:
            mel.eval("performSmoothMeshPreviewToPolygon 0;")
        except Exception:
            cmds.polySmooth(
                node,
                divisions=max(1, int(level)),
                continuity=1.0,
                keepBorder=True,
                keepHardEdge=True,
                keepSelectionBorder=False,
                keepTessellation=True,
                constructionHistory=False,
            )

        node = _selected_transform()
        for shape in _mesh_shapes(node):
            if _has_attr(shape, "displaySmoothMesh"):
                cmds.setAttr("{0}.displaySmoothMesh".format(shape), 0)
        cmds.select(node, replace=True)
        _refresh_ui()
    finally:
        cmds.refresh(suspend=False)
        cmds.undoInfo(closeChunk=True)
        if previous_selection and cmds.objExists(previous_selection[0].split(".", 1)[0]):
            try:
                cmds.select(previous_selection, replace=True)
            except Exception:
                pass


def _strip_zdiv_attrs(node):
    for attr in ZDIV_ATTRS:
        if _has_attr(node, attr):
            try:
                cmds.deleteAttr("{0}.{1}".format(node, attr))
            except Exception:
                pass


def _dag_path_for_mesh(node):
    if om is None:
        return None

    shapes = _mesh_shapes(node)
    target = shapes[0] if shapes else node
    selection = om.MSelectionList()
    selection.add(target)
    dag_path = selection.getDagPath(0)
    if dag_path.node().hasFn(om.MFn.kTransform):
        dag_path.extendToShape()
    return dag_path


def _feature_edges_by_normal_angle(node, sensitivity=0.55):
    if om is None:
        cmds.warning("maya.api.OpenMaya が使えないため、特徴エッジ解析をスキップします。")
        return []

    sensitivity = max(0.0, min(1.0, float(sensitivity)))
    threshold_degrees = 80.0 - (sensitivity * 72.0)
    threshold_radians = threshold_degrees * 3.141592653589793 / 180.0

    dag_path = _dag_path_for_mesh(node)
    if dag_path is None:
        return []

    mesh_fn = om.MFnMesh(dag_path)
    edge_iter = om.MItMeshEdge(dag_path)
    protected = []
    node_name = _long_name(node)

    while not edge_iter.isDone():
        edge_index = edge_iter.index()
        faces = edge_iter.getConnectedFaces()
        if len(faces) == 2:
            normal_a = mesh_fn.getPolygonNormal(faces[0], om.MSpace.kWorld)
            normal_b = mesh_fn.getPolygonNormal(faces[1], om.MSpace.kWorld)
            if normal_a.angle(normal_b) >= threshold_radians:
                protected.append("{0}.e[{1}]".format(node_name, edge_index))
        elif len(faces) < 2:
            protected.append("{0}.e[{1}]".format(node_name, edge_index))
        edge_iter.next()

    return protected


def analyze_feature_edges(sensitivity=0.55):
    node = _selected_transform()
    edges = _feature_edges_by_normal_angle(node, sensitivity)
    if not edges:
        cmds.warning("保護対象の特徴エッジは見つかりませんでした。")
        return []
    cmds.select(edges, replace=True)
    return edges


def _protect_feature_edges(edges, preserve_strength=1.0):
    if not edges:
        return

    preserve_strength = max(0.0, min(1.0, float(preserve_strength)))
    crease_value = max(0.0, min(10.0, preserve_strength * 10.0))
    previous_selection = cmds.ls(selection=True, long=True) or []
    try:
        cmds.select(edges, replace=True)
        cmds.polySoftEdge(angle=0, constructionHistory=False)
        if crease_value > 0.0:
            try:
                cmds.polyCrease(edges, value=crease_value)
            except Exception:
                pass
    finally:
        if previous_selection:
            cmds.select(previous_selection, replace=True)


def _run_poly_reduce(
    node,
    mode,
    reduce_percent,
    target_vertices,
    target_triangles,
    preserve_topology=True,
    keep_border=True,
    keep_uv_border=True,
    keep_hard_edge=True,
    keep_crease_edge=True,
    preserve_strength=1.0,
):
    mode = mode or "Percentage"
    preserve_strength = max(0.0, min(1.0, float(preserve_strength)))

    kwargs = {
        "version": 1,
        "preserveTopology": bool(preserve_topology),
        "keepBorder": bool(keep_border),
        "keepMapBorder": bool(keep_uv_border),
        "keepHardEdge": bool(keep_hard_edge),
        "keepCreaseEdge": bool(keep_crease_edge),
        "keepBorderWeight": preserve_strength,
        "keepMapBorderWeight": preserve_strength,
        "keepHardEdgeWeight": preserve_strength,
        "keepCreaseEdgeWeight": preserve_strength,
        "constructionHistory": False,
    }

    if mode == "Target Vertices":
        kwargs.update({"termination": 1, "vertexCount": max(1, int(target_vertices))})
    elif mode == "Target Triangles":
        kwargs.update({"termination": 2, "triangleCount": max(1, int(target_triangles))})
    else:
        kwargs.update({"termination": 0, "percentage": max(0.0, min(100.0, float(reduce_percent)))})

    try:
        return cmds.polyReduce(node, **kwargs)
    except Exception:
        # Older Maya builds expose fewer flags. Fall back to the stable core.
        fallback = {
            "version": 1,
            "constructionHistory": False,
        }
        if mode == "Target Vertices":
            fallback.update({"termination": 1, "vertexCount": max(1, int(target_vertices))})
        elif mode == "Target Triangles":
            fallback.update({"termination": 2, "triangleCount": max(1, int(target_triangles))})
        else:
            fallback.update({"termination": 0, "percentage": max(0.0, min(100.0, float(reduce_percent)))})
        return cmds.polyReduce(node, **fallback)


def feature_aware_decimate(
    mode="Percentage",
    reduce_percent=70.0,
    target_vertices=5000,
    target_triangles=10000,
    sensitivity=0.55,
    preserve_strength=1.0,
    duplicate_before=True,
    preserve_topology=True,
    keep_border=True,
    keep_uv_border=True,
    keep_hard_edge=True,
    keep_crease_edge=True,
):
    source = _selected_transform()

    cmds.undoInfo(openChunk=True)
    cmds.refresh(suspend=True)
    try:
        if duplicate_before:
            base = source.split("|")[-1]
            target = cmds.duplicate(source, name="{0}_DECIMATED".format(base))[0]
            target = _long_name(target)
            _strip_zdiv_attrs(target)
        else:
            target = source

        feature_edges = _feature_edges_by_normal_angle(target, sensitivity)
        _protect_feature_edges(feature_edges, preserve_strength)

        _run_poly_reduce(
            target,
            mode,
            reduce_percent,
            target_vertices,
            target_triangles,
            preserve_topology=preserve_topology,
            keep_border=keep_border,
            keep_uv_border=keep_uv_border,
            keep_hard_edge=keep_hard_edge,
            keep_crease_edge=keep_crease_edge,
            preserve_strength=preserve_strength,
        )

        cmds.select(target, replace=True)
        _refresh_ui()
        return target
    finally:
        cmds.refresh(suspend=False)
        cmds.undoInfo(closeChunk=True)


def set_decimation_preset(reduce_percent):
    if _ui_exists("zdivDecimatePercentSlider"):
        cmds.floatSliderGrp("zdivDecimatePercentSlider", edit=True, value=float(reduce_percent))


def _retopo_settings_for_mode(mode, topology_regular, face_uniformity, anisotropy):
    if mode == "Hard Surface":
        return {
            "topologyRegularity": 0.9 if topology_regular is None else float(topology_regular),
            "faceUniformity": 0.85 if face_uniformity is None else float(face_uniformity),
            "anisotropy": 0.1 if anisotropy is None else float(anisotropy),
        }
    return {
        "topologyRegularity": 0.35 if topology_regular is None else float(topology_regular),
        "faceUniformity": 0.2 if face_uniformity is None else float(face_uniformity),
        "anisotropy": 0.65 if anisotropy is None else float(anisotropy),
    }


def _run_poly_retopo(
    node,
    target_faces=5000,
    tolerance=10,
    preserve_hard_edges=True,
    topology_regular=0.35,
    face_uniformity=0.2,
    anisotropy=0.65,
    target_edge_deviation=0.2929,
):
    if not hasattr(cmds, "polyRetopo"):
        raise RuntimeError("このMayaには polyRetopo がありません。Maya 2020以降が必要です。")

    kwargs = {
        "replaceOriginal": True,
        "preserveHardEdges": bool(preserve_hard_edges),
        "targetFaceCount": max(0, int(target_faces)),
        "targetFaceCountTolerance": max(1, int(tolerance)),
        "topologyRegularity": max(0.0, min(1.0, float(topology_regular))),
        "faceUniformity": max(0.0, min(1.0, float(face_uniformity))),
        "anisotropy": max(0.0, min(1.0, float(anisotropy))),
        "targetEdgeDeviation": max(0.01, min(1.0, float(target_edge_deviation))),
        "constructionHistory": False,
    }

    try:
        return cmds.polyRetopo(node, **kwargs)
    except Exception:
        fallback = {
            "replaceOriginal": True,
            "preserveHardEdges": bool(preserve_hard_edges),
            "targetFaceCount": max(0, int(target_faces)),
            "targetFaceCountTolerance": max(1, int(tolerance)),
            "constructionHistory": False,
        }
        return cmds.polyRetopo(node, **fallback)


def smart_remesh(
    mode="Organic",
    target_faces=5000,
    tolerance=10,
    sensitivity=0.55,
    preserve_features=True,
    duplicate_before=True,
    topology_regular=None,
    face_uniformity=None,
    anisotropy=None,
    target_edge_deviation=0.2929,
):
    source = _selected_transform()
    settings = _retopo_settings_for_mode(mode, topology_regular, face_uniformity, anisotropy)

    cmds.undoInfo(openChunk=True)
    cmds.refresh(suspend=True)
    try:
        if duplicate_before:
            base = source.split("|")[-1]
            target = cmds.duplicate(source, name="{0}_SMART_REMESH".format(base))[0]
            target = _long_name(target)
            _strip_zdiv_attrs(target)
        else:
            target = source

        if preserve_features:
            _clear_all_creases_and_hard_edges(target)
            feature_edges = _feature_edges_by_normal_angle(target, sensitivity)
            _protect_feature_edges(feature_edges, 1.0)

        _run_poly_retopo(
            target,
            target_faces=target_faces,
            tolerance=tolerance,
            preserve_hard_edges=preserve_features,
            topology_regular=settings["topologyRegularity"],
            face_uniformity=settings["faceUniformity"],
            anisotropy=settings["anisotropy"],
            target_edge_deviation=target_edge_deviation,
        )

        if not cmds.objExists(target):
            selected_after = cmds.ls(selection=True, long=True) or []
            if selected_after:
                target = selected_after[0].split(".", 1)[0]
        if cmds.objExists(target):
            cmds.delete(target, constructionHistory=True)
            cmds.select(target, replace=True)
        _refresh_ui()
        return target
    finally:
        cmds.refresh(suspend=False)
        cmds.undoInfo(closeChunk=True)


def smart_panel_remesh(
    reduce_percent=92.0,
    sensitivity=0.55,
    preserve_strength=1.0,
    duplicate_before=True,
    keep_uv_border=True,
    keep_border=True,
):
    source = _selected_transform()

    cmds.undoInfo(openChunk=True)
    cmds.refresh(suspend=True)
    try:
        if duplicate_before:
            base = source.split("|")[-1]
            target = cmds.duplicate(source, name="{0}_SMART_PANEL".format(base))[0]
            target = _long_name(target)
            _strip_zdiv_attrs(target)
        else:
            target = source

        _clear_all_creases_and_hard_edges(target)
        feature_edges = _feature_edges_by_normal_angle(target, sensitivity)
        _protect_feature_edges(feature_edges, preserve_strength)

        _run_poly_reduce(
            target,
            "Percentage",
            reduce_percent,
            0,
            0,
            preserve_topology=False,
            keep_border=keep_border,
            keep_uv_border=keep_uv_border,
            keep_hard_edge=True,
            keep_crease_edge=True,
            preserve_strength=preserve_strength,
        )

        try:
            cmds.delete(target, constructionHistory=True)
        except Exception:
            pass
        cmds.select(target, replace=True)
        _refresh_ui()
        return target
    finally:
        cmds.refresh(suspend=False)
        cmds.undoInfo(closeChunk=True)


def set_smart_remesh_preset(target_faces):
    if _ui_exists("zdivSmartTargetFacesField"):
        cmds.intFieldGrp("zdivSmartTargetFacesField", edit=True, value1=int(target_faces))


def lower_res():
    state = current_state()
    target = max(state["min_level"], state["active_level"] - 1)
    return _set_active_level(state["asset_id"], target)


def higher_res():
    state = current_state()
    target = min(state["max_level"], state["active_level"] + 1)
    return _set_active_level(state["asset_id"], target)


def set_sdiv(level):
    state = current_state()
    level = int(level)
    level = max(state["min_level"], min(state["max_level"], level))
    return _set_active_level(state["asset_id"], level)


def delete_lower():
    state = current_state()
    to_delete = [node for level, node in state["levels"] if level < state["active_level"]]
    if to_delete:
        cmds.delete(to_delete)
    _refresh_ui()


def delete_higher():
    state = current_state()
    to_delete = [node for level, node in state["levels"] if level > state["active_level"]]
    if to_delete:
        cmds.delete(to_delete)
    _refresh_ui()


def _ui_exists(name):
    try:
        return cmds.control(name, exists=True)
    except Exception:
        return False


def _refresh_ui():
    if not cmds.window(WINDOW_NAME, exists=True):
        return

    try:
        state = current_state()
        label = "SDiv {0} / {1}".format(state["active_level"], state["max_level"])
        cmds.text("zdivStatusText", edit=True, label=label)
        cmds.intSliderGrp(
            "zdivSlider",
            edit=True,
            minValue=state["min_level"],
            maxValue=state["max_level"],
            fieldMinValue=state["min_level"],
            fieldMaxValue=max(10, state["max_level"]),
            value=state["active_level"],
            enable=state["max_level"] > state["min_level"],
        )
        crease_level = _get_int_attr(state["active_node"], ATTR_CREASE_LEVEL) or 0
        dynamic_level = _get_int_attr(state["active_node"], ATTR_DYNAMIC_LEVEL) or 2
        if _ui_exists("zdivCreaseLevelSlider"):
            cmds.intSliderGrp("zdivCreaseLevelSlider", edit=True, value=crease_level)
        if _ui_exists("zdivDynamicLevelSlider"):
            cmds.intSliderGrp("zdivDynamicLevelSlider", edit=True, value=dynamic_level)
    except Exception as exc:
        cmds.text("zdivStatusText", edit=True, label=str(exc))


def show():
    if cmds.window(WINDOW_NAME, exists=True):
        cmds.deleteUI(WINDOW_NAME)

    cmds.window(WINDOW_NAME, title="ZBrush Divide for Maya", sizeable=False)
    cmds.columnLayout(adjustableColumn=True, rowSpacing=8, columnOffset=("both", 10))

    cmds.text("zdivStatusText", label="メッシュを選択して Initialize")
    cmds.button(label="Initialize Selected as SDiv 1", command=lambda *_: _run(initialize_selected))

    cmds.separator(height=8, style="in")
    cmds.checkBox("zdivSmoothCheck", label="Smt: Smooth Divide", value=True)
    cmds.checkBox("zdivKeepPreviousCheck", label="Keep Previous SDiv Levels", value=True)
    cmds.button(
        label="Divide",
        height=34,
        command=lambda *_: _run(
            lambda: divide(
                cmds.checkBox("zdivSmoothCheck", query=True, value=True),
                cmds.checkBox("zdivKeepPreviousCheck", query=True, value=True),
            )
        ),
    )

    cmds.separator(height=8, style="in")
    cmds.rowLayout(numberOfColumns=2, adjustableColumn=1, columnWidth2=(150, 150))
    cmds.button(label="Lower Res", command=lambda *_: _run(lower_res))
    cmds.button(label="Higher Res", command=lambda *_: _run(higher_res))
    cmds.setParent("..")

    cmds.intSliderGrp(
        "zdivSlider",
        label="SDiv",
        field=True,
        minValue=1,
        maxValue=1,
        value=1,
        enable=False,
        changeCommand=lambda value: _run(lambda: set_sdiv(value)),
    )

    cmds.separator(height=8, style="in")
    cmds.rowLayout(numberOfColumns=2, adjustableColumn=1, columnWidth2=(150, 150))
    cmds.button(label="Delete Lower", command=lambda *_: _run(delete_lower))
    cmds.button(label="Delete Higher", command=lambda *_: _run(delete_higher))
    cmds.setParent("..")

    cmds.separator(height=8, style="in")
    cmds.text(label="Crease", align="left")
    cmds.floatSliderGrp(
        "zdivCreaseValueSlider",
        label="Value",
        field=True,
        minValue=0.0,
        maxValue=10.0,
        fieldMinValue=0.0,
        fieldMaxValue=20.0,
        value=10.0,
        precision=2,
    )
    cmds.intSliderGrp(
        "zdivCreaseLevelSlider",
        label="CreaseLvl",
        field=True,
        minValue=0,
        maxValue=8,
        fieldMinValue=0,
        fieldMaxValue=32,
        value=2,
        changeCommand=lambda value: _run(lambda: set_crease_level(value)),
    )
    cmds.rowLayout(numberOfColumns=2, adjustableColumn=1, columnWidth2=(150, 150))
    cmds.button(
        label="Crease Selected Edges",
        command=lambda *_: _run(
            lambda: crease_selected_edges(
                cmds.floatSliderGrp("zdivCreaseValueSlider", query=True, value=True),
                cmds.intSliderGrp("zdivCreaseLevelSlider", query=True, value=True),
            )
        ),
    )
    cmds.button(label="Uncrease Selected", command=lambda *_: _run(uncrease_selected_edges))
    cmds.setParent("..")

    cmds.separator(height=8, style="in")
    cmds.text(label="Dynamic Subdiv", align="left")
    cmds.intSliderGrp(
        "zdivDynamicLevelSlider",
        label="Level",
        field=True,
        minValue=0,
        maxValue=6,
        fieldMinValue=0,
        fieldMaxValue=12,
        value=2,
    )
    cmds.rowLayout(numberOfColumns=3, adjustableColumn=1, columnWidth3=(100, 100, 140))
    cmds.button(
        label="Enable",
        command=lambda *_: _run(
            lambda: set_dynamic_subdiv(
                True,
                cmds.intSliderGrp("zdivDynamicLevelSlider", query=True, value=True),
            )
        ),
    )
    cmds.button(label="Disable", command=lambda *_: _run(lambda: set_dynamic_subdiv(False, 0)))
    cmds.button(label="Apply Dynamic Subdiv", command=lambda *_: _run(apply_dynamic_subdiv))
    cmds.setParent("..")

    cmds.separator(height=8, style="in")
    cmds.text(label="Feature Aware Decimation", align="left")
    cmds.optionMenu("zdivDecimateModeMenu", label="Mode")
    cmds.menuItem(label="Percentage")
    cmds.menuItem(label="Target Vertices")
    cmds.menuItem(label="Target Triangles")
    cmds.floatSliderGrp(
        "zdivDecimatePercentSlider",
        label="Reduce %",
        field=True,
        minValue=0.0,
        maxValue=98.0,
        fieldMinValue=0.0,
        fieldMaxValue=99.9,
        value=70.0,
        precision=1,
    )
    cmds.intFieldGrp("zdivTargetVerticesField", label="Target Verts", value1=5000)
    cmds.intFieldGrp("zdivTargetTrianglesField", label="Target Tris", value1=10000)
    cmds.floatSliderGrp(
        "zdivFeatureSensitivitySlider",
        label="Sensitivity",
        field=True,
        minValue=0.0,
        maxValue=1.0,
        fieldMinValue=0.0,
        fieldMaxValue=1.0,
        value=0.55,
        precision=2,
    )
    cmds.floatSliderGrp(
        "zdivPreserveStrengthSlider",
        label="Preserve",
        field=True,
        minValue=0.0,
        maxValue=1.0,
        fieldMinValue=0.0,
        fieldMaxValue=1.0,
        value=1.0,
        precision=2,
    )
    cmds.rowLayout(numberOfColumns=4, adjustableColumn=1, columnWidth4=(75, 75, 75, 75))
    cmds.button(label="Light", command=lambda *_: _run(lambda: set_decimation_preset(30.0)))
    cmds.button(label="Medium", command=lambda *_: _run(lambda: set_decimation_preset(60.0)))
    cmds.button(label="Heavy", command=lambda *_: _run(lambda: set_decimation_preset(85.0)))
    cmds.button(label="Extreme", command=lambda *_: _run(lambda: set_decimation_preset(95.0)))
    cmds.setParent("..")
    cmds.checkBox("zdivDecimateDuplicateCheck", label="Duplicate Before Decimate", value=True)
    cmds.checkBox("zdivPreserveTopologyCheck", label="Preserve Topology", value=True)
    cmds.checkBox("zdivKeepBorderCheck", label="Keep Mesh Border", value=True)
    cmds.checkBox("zdivKeepUvBorderCheck", label="Keep UV Border", value=True)
    cmds.checkBox("zdivKeepHardEdgeCheck", label="Keep Hard Edge", value=True)
    cmds.checkBox("zdivKeepCreaseEdgeCheck", label="Keep Crease Edge", value=True)
    cmds.rowLayout(numberOfColumns=2, adjustableColumn=1, columnWidth2=(150, 150))
    cmds.button(
        label="Analyze Features",
        command=lambda *_: _run(
            lambda: analyze_feature_edges(
                cmds.floatSliderGrp("zdivFeatureSensitivitySlider", query=True, value=True)
            )
        ),
    )
    cmds.button(
        label="Decimate Feature Aware",
        command=lambda *_: _run(
            lambda: feature_aware_decimate(
                cmds.optionMenu("zdivDecimateModeMenu", query=True, value=True),
                cmds.floatSliderGrp("zdivDecimatePercentSlider", query=True, value=True),
                cmds.intFieldGrp("zdivTargetVerticesField", query=True, value1=True),
                cmds.intFieldGrp("zdivTargetTrianglesField", query=True, value1=True),
                cmds.floatSliderGrp("zdivFeatureSensitivitySlider", query=True, value=True),
                cmds.floatSliderGrp("zdivPreserveStrengthSlider", query=True, value=True),
                cmds.checkBox("zdivDecimateDuplicateCheck", query=True, value=True),
                cmds.checkBox("zdivPreserveTopologyCheck", query=True, value=True),
                cmds.checkBox("zdivKeepBorderCheck", query=True, value=True),
                cmds.checkBox("zdivKeepUvBorderCheck", query=True, value=True),
                cmds.checkBox("zdivKeepHardEdgeCheck", query=True, value=True),
                cmds.checkBox("zdivKeepCreaseEdgeCheck", query=True, value=True),
            )
        ),
    )
    cmds.setParent("..")

    cmds.separator(height=8, style="in")
    cmds.text(label="Smart Remesh", align="left")
    cmds.optionMenu("zdivSmartModeMenu", label="Mode")
    cmds.menuItem(label="Organic")
    cmds.menuItem(label="Hard Surface")
    cmds.intFieldGrp("zdivSmartTargetFacesField", label="Target Quads", value1=5000)
    cmds.intSliderGrp(
        "zdivSmartToleranceSlider",
        label="Tolerance %",
        field=True,
        minValue=1,
        maxValue=50,
        fieldMinValue=1,
        fieldMaxValue=100,
        value=10,
    )
    cmds.floatSliderGrp(
        "zdivSmartSensitivitySlider",
        label="Feature Sens",
        field=True,
        minValue=0.0,
        maxValue=1.0,
        fieldMinValue=0.0,
        fieldMaxValue=1.0,
        value=0.55,
        precision=2,
    )
    cmds.floatSliderGrp(
        "zdivSmartRegularitySlider",
        label="Regularity",
        field=True,
        minValue=0.0,
        maxValue=1.0,
        fieldMinValue=0.0,
        fieldMaxValue=1.0,
        value=0.35,
        precision=2,
    )
    cmds.floatSliderGrp(
        "zdivSmartUniformitySlider",
        label="Uniformity",
        field=True,
        minValue=0.0,
        maxValue=1.0,
        fieldMinValue=0.0,
        fieldMaxValue=1.0,
        value=0.2,
        precision=2,
    )
    cmds.floatSliderGrp(
        "zdivSmartAnisotropySlider",
        label="Anisotropy",
        field=True,
        minValue=0.0,
        maxValue=1.0,
        fieldMinValue=0.0,
        fieldMaxValue=1.0,
        value=0.65,
        precision=2,
    )
    cmds.floatSliderGrp(
        "zdivSmartEdgeDeviationSlider",
        label="Edge Dev",
        field=True,
        minValue=0.01,
        maxValue=1.0,
        fieldMinValue=0.01,
        fieldMaxValue=1.0,
        value=0.2929,
        precision=3,
    )
    cmds.floatSliderGrp(
        "zdivSmartPanelReduceSlider",
        label="Panel Reduce %",
        field=True,
        minValue=50.0,
        maxValue=98.0,
        fieldMinValue=0.0,
        fieldMaxValue=99.5,
        value=92.0,
        precision=1,
    )
    cmds.rowLayout(numberOfColumns=4, adjustableColumn=1, columnWidth4=(75, 75, 75, 75))
    cmds.button(label="1k", command=lambda *_: _run(lambda: set_smart_remesh_preset(1000)))
    cmds.button(label="5k", command=lambda *_: _run(lambda: set_smart_remesh_preset(5000)))
    cmds.button(label="10k", command=lambda *_: _run(lambda: set_smart_remesh_preset(10000)))
    cmds.button(label="25k", command=lambda *_: _run(lambda: set_smart_remesh_preset(25000)))
    cmds.setParent("..")
    cmds.checkBox("zdivSmartDuplicateCheck", label="Duplicate Before Smart Remesh", value=True)
    cmds.checkBox("zdivSmartPreserveFeaturesCheck", label="Preserve Silhouette Features", value=True)
    cmds.rowLayout(numberOfColumns=3, adjustableColumn=1, columnWidth3=(130, 130, 130))
    cmds.button(
        label="Preview Feature Edges",
        command=lambda *_: _run(
            lambda: analyze_feature_edges(
                cmds.floatSliderGrp("zdivSmartSensitivitySlider", query=True, value=True)
            )
        ),
    )
    cmds.button(
        label="Smart Remesh Quads",
        command=lambda *_: _run(
            lambda: smart_remesh(
                cmds.optionMenu("zdivSmartModeMenu", query=True, value=True),
                cmds.intFieldGrp("zdivSmartTargetFacesField", query=True, value1=True),
                cmds.intSliderGrp("zdivSmartToleranceSlider", query=True, value=True),
                cmds.floatSliderGrp("zdivSmartSensitivitySlider", query=True, value=True),
                cmds.checkBox("zdivSmartPreserveFeaturesCheck", query=True, value=True),
                cmds.checkBox("zdivSmartDuplicateCheck", query=True, value=True),
                cmds.floatSliderGrp("zdivSmartRegularitySlider", query=True, value=True),
                cmds.floatSliderGrp("zdivSmartUniformitySlider", query=True, value=True),
                cmds.floatSliderGrp("zdivSmartAnisotropySlider", query=True, value=True),
                cmds.floatSliderGrp("zdivSmartEdgeDeviationSlider", query=True, value=True),
            )
        ),
    )
    cmds.button(
        label="Smart Panel Remesh",
        command=lambda *_: _run(
            lambda: smart_panel_remesh(
                cmds.floatSliderGrp("zdivSmartPanelReduceSlider", query=True, value=True),
                cmds.floatSliderGrp("zdivSmartSensitivitySlider", query=True, value=True),
                1.0,
                cmds.checkBox("zdivSmartDuplicateCheck", query=True, value=True),
                True,
                True,
            )
        ),
    )
    cmds.setParent("..")

    cmds.separator(height=8, style="none")
    cmds.text(
        label="Note: Smart Panel Remesh removes flat-area loops and preserves bevel/silhouette features.",
        align="left",
    )

    cmds.showWindow(WINDOW_NAME)
    _refresh_ui()


def _run(function):
    try:
        result = function()
        _refresh_ui()
        return result
    except Exception as exc:
        cmds.warning(str(exc))
        _refresh_ui()
        return None


if __name__ == "__main__":
    show()
