import maya.cmds as cmds

if cmds.unknownPlugin(q=True, list=True):
    plugins = cmds.unknownPlugin(q=True, list=True)
    deleted_plugins = []
    for plugin in plugins:
        cmds.unknownPlugin(plugin, remove=True)
        deleted_plugins.append(plugin)
    deleted_plugins_str = ', '.join(deleted_plugins)
    cmds.confirmDialog(title='Unknown Plugin', message=deleted_plugins_str + ' deleted', button=['OK'], defaultButton='OK')
else:
    cmds.confirmDialog(title='Unknown Plugin', message='no unknownPlugin', button=['OK'], defaultButton='OK')
