import maya.cmds as cmds


if cmds.unknownPlugin(q=True, list=True):
    plugin_name = cmds.unknownPlugin(q=True, list=True)[0]
    cmds.unknownPlugin(plugin_name, remove=True)
    message = plugin_name + "‚ğíœ‚µ‚Ü‚µ‚½"
else:
    message = "unknownPlugin‚Í‚ ‚è‚Ü‚¹‚ñ"


cmds.confirmDialog(title="Plugin Check", message=message, button=["OK"])