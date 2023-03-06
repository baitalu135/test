import maya.cmds as cmds

if cmds.unknownPlugin(q=True, list=True):
    plugins = cmds.unknownPlugin(q=True, list=True)
    for plugin in plugins:
        cmds.unknownPlugin(plugin, remove=True)
    cmds.confirmDialog(title='Unknown Plugin', message=str(len(plugins))+' deleted', button=['OK'], defaultButton='OK')
else:
    cmds.confirmDialog(title='Unknown Plugin', message='no unknownPlugin', button=['OK'], defaultButton='OK')
