import maya.cmds as cmds

WINDOW_NAME = "fileNodeReplaceTool"

def refresh_file_list():
    cmds.textScrollList("fileNodeList", e=True, removeAll=True)
    file_nodes = cmds.ls(type="file")

    for node in file_nodes:
        path = cmds.getAttr(node + ".fileTextureName")
        cmds.textScrollList(
            "fileNodeList",
            e=True,
            append=f"{node} | {path}"
        )

def get_selected_file_nodes():
    selected = cmds.textScrollList("fileNodeList", q=True, selectItem=True)
    if not selected:
        return []

    nodes = []
    for item in selected:
        node = item.split(" | ")[0]
        nodes.append(node)
    return nodes

def preview_replace(*args):
    search = cmds.textField("searchField", q=True, text=True)
    replace = cmds.textField("replaceField", q=True, text=True)

    cmds.textScrollList("previewList", e=True, removeAll=True)

    for node in get_selected_file_nodes():
        path = cmds.getAttr(node + ".fileTextureName")
        if search in path:
            new_path = path.replace(search, replace)
            cmds.textScrollList(
                "previewList",
                e=True,
                append=f"{node}: {path} → {new_path}"
            )

def execute_replace(*args):
    search = cmds.textField("searchField", q=True, text=True)
    replace = cmds.textField("replaceField", q=True, text=True)

    count = 0
    for node in get_selected_file_nodes():
        path = cmds.getAttr(node + ".fileTextureName")
        if search in path:
            new_path = path.replace(search, replace)
            cmds.setAttr(node + ".fileTextureName", new_path, type="string")
            count += 1

    cmds.confirmDialog(
        title="Completed",
        message=f"{count} file node(s) have been updated.",
        button=["OK"]
    )
    refresh_file_list()
    preview_replace()

def create_ui():
    if cmds.window(WINDOW_NAME, exists=True):
        cmds.deleteUI(WINDOW_NAME)

    cmds.window(
        WINDOW_NAME,
        title="File Node Selection & Path Replace Tool",
        widthHeight=(700, 500)
    )
    cmds.columnLayout(adjustableColumn=True, rowSpacing=6)

    cmds.text(
        label="■ File Nodes in Scene (Multiple Selection Allowed)",
        align="left"
    )
    cmds.textScrollList(
        "fileNodeList",
        allowMultiSelection=True,
        height=180
    )

    cmds.button(
        label="Refresh List",
        command=lambda x: refresh_file_list()
    )

    cmds.separator(height=8, style="in")

    cmds.text(label="Search String")
    cmds.textField("searchField")

    cmds.text(label="Replace With")
    cmds.textField("replaceField")

    cmds.rowLayout(numberOfColumns=2, columnWidth2=(350, 350))
    cmds.button(label="Preview", command=preview_replace)
    cmds.button(
        label="Apply to Selected File Nodes",
        command=execute_replace
    )
    cmds.setParent("..")

    cmds.separator(height=8, style="in")

    cmds.text(label="Change Preview", align="left")
    cmds.textScrollList("previewList", height=120)

    refresh_file_list()
    cmds.showWindow(WINDOW_NAME)

create_ui()
