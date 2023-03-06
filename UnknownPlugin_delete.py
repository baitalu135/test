import maya.cmds as cmds


if cmds.unknownPlugin(q=True, list=True):
    plugin_name = cmds.unknownPlugin(q=True, list=True)[0]
    cmds.unknownPlugin(plugin_name, remove=True)
    message = plugin_name + "を削除しました"
else:
    message = "unknownPluginはありません"


cmds.confirmDialog(title="Plugin Check", message=message, button=["OK"])