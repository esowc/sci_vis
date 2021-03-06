# <pep8 compliant>
# ---------------------------------------------------------------------------------
#   debug/__init__.py
#
#   Define nodes used for debugging.
# ---------------------------------------------------------------------------------


from ... utilities import *
from .. core import *


class BVTK_NT_Info(Node, BVTK_Node):
    """BVTK Info Node"""
    bl_idname = 'BVTK_NT_Info'
    bl_label = 'Info'

    def m_properties(self):
        return []

    def m_connections(self):
        return ["Input"], [], [], ["Output"]

    def update_cb(self):
        log.debug("Tree updated.")

    def setup(self):
        # Make info node wider to show all text
        self.width = 300

    def draw_buttons(self, context, layout):
        fs = "{:.5g}"  # Format string
        in_node, vtkobj = self.get_input_node("Input")
        if not in_node:
            layout.label("Connect a node")
        elif not vtkobj:
            layout.label("Input has not vtkobj (try updating)")
        else:
            vtkobj = resolve_algorithm_output(vtkobj)
            if vtkobj:
                layout.label(text="Type: " + vtkobj.__class__.__name__)

                if hasattr(vtkobj, "GetNumberOfPoints"):
                    layout.label(text="Points: " + str(vtkobj.GetNumberOfPoints()))
                if hasattr(vtkobj, "GetNumberOfCells"):
                    layout.label(text="Cells: " + str(vtkobj.GetNumberOfCells()))
                if hasattr(vtkobj, "GetBounds"):
                    layout.label(text="X range: " + fs.format(vtkobj.GetBounds()[0]) +
                                 " - " + fs.format(vtkobj.GetBounds()[1]))
                    layout.label(text="Y range: " + fs.format(vtkobj.GetBounds()[2]) +
                                 " - " + fs.format(vtkobj.GetBounds()[3]))
                    layout.label(text="Z range: " + fs.format(vtkobj.GetBounds()[4]) +
                                 " - " + fs.format(vtkobj.GetBounds()[5]))
                data = {}
                if hasattr(vtkobj, "GetPointData"):
                    data["Point data "] = vtkobj.GetPointData()
                if hasattr(vtkobj, "GetCellData"):
                    data["Cell data "] = vtkobj.GetCellData()
                if hasattr(vtkobj, "GetFieldData"):
                    data["Field data "] = vtkobj.GetFieldData()
                for k in data:
                    d = data[k]
                    for i in range(d.GetNumberOfArrays()):
                        arr = d.GetArray(i)
                        r = arr.GetRange()
                        name = arr.GetName()
                        row = layout.row()
                        row.label(text=k + "[" + str(i) + "]: '" + name + "': "
                                  + fs.format(r[0]) + " - " + fs.format(r[1]))

        layout.separator()
        high_op(layout, "bvtk.node_update", text="update").node_path = node_path(self)

    def apply_properties(self, vtkobj):
        pass

    def apply_inputs(self, vtkobj):
        pass

    def get_output(self, socket):
        return self.get_input_node("Input")[1]


cat = "Debug"
register.set_category_icon(cat, "VIEWZOOM")
add_node(BVTK_NT_Info, cat)
