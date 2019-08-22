from . utils import *
from . update import *
import bmesh

# -----------------------------------------------------------------------------
# Converters from VTK to Blender
# -----------------------------------------------------------------------------


class BVTK_NT_ToBlender(Node, BVTK_Node):
    """Convert output from VTK Node to Blender Mesh Object"""
    bl_idname = 'BVTK_NT_ToBlender'
    bl_label = 'ToBlender'

    def start_scan(self, context):
        if context:
            if self.auto_update:
                bpy.ops.bvtk.auto_update_scan(
                    node_name=self.name,
                    tree_name=context.space_data.node_tree.name)

    m_Name = bpy.props.StringProperty(name="Name", default="mesh")
    auto_update = bpy.props.BoolProperty(default=False, update=start_scan)
    smooth = bpy.props.BoolProperty(name="Smooth", default=False)

    def m_properties(self):
        return ["m_Name", "smooth", ]

    def m_connections(self):
        return ( ["Input"],[],[],[] )

    def draw_buttons(self, context, layout):
        layout.prop(self, "m_Name")
        layout.prop(self, "auto_update", text="Auto update")
        layout.prop(self, "smooth", text="Smooth")
        layout.separator()
        layout.operator("bvtk.node_update", text="update").node_path = node_path(self)

    def update_cb(self):
        """Update node"""
        input_node, vtkobj = self.get_input_node("Input")
        color_node = None
        if input_node and (input_node.bl_idname == "BVTK_NT_ColorMapper" or
                           input_node.bl_idname == "BVTK_NT_ColorToImage"):
            color_node = input_node
            color_node.update()  # setting auto range
            input_node, vtkobj = input_node.get_input_node("Input")
        if vtkobj:
            vtkobj = resolve_algorithm_output(vtkobj)
            vtkdata_to_blender(vtkobj, self.m_Name, color_node, self.smooth)
            update_3d_view()

    def apply_properties(self, vtkobj):
        pass


# ---------------------------------------------------------------------------------
# Operator Update
# ---------------------------------------------------------------------------------


class BVTK_OT_NodeUpdate(bpy.types.Operator):
    bl_idname = "bvtk.node_update"
    bl_label = "update"
    node_path = bpy.props.StringProperty()
    use_queue = bpy.props.BoolProperty(default=True)

    def execute(self, context):
        check_cache()
        node = eval(self.node_path)
        if node:
            log.info('Updating from {}'.format(node.name))
            cb = None
            if hasattr(node, "update_cb"):
                cb = node.update_cb
            if self.use_queue:
                update(node, cb)
            else:
                no_queue_update(node, cb)
        self.use_queue = True
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Operator Write
# -----------------------------------------------------------------------------


class BVTK_OT_NodeWrite(Operator):
    """Operator to call VTK Write() for a node"""
    bl_idname = "bvtk.node_write"
    bl_label = "Write"

    id = bpy.props.IntProperty()

    def execute(self, context):
        check_cache()
        # TODO: retrieve the node with the path, not with the id.
        node = get_node(self.id)
        if node:
            def cb():
                node.get_vtkobj().Write()
            update(node, cb)

        return {'FINISHED'}


# ---------------------------------------------------------------------------------
# Auto Update Scan
# ---------------------------------------------------------------------------------


def map(node, pmap = None):
    """ Creates a map which represent
    the status (m_properties and inputs) of
    every node connected to the one given. """
    # {} map:        node name -> (nodeprops, nodeinputs)
    # {} nodeprops:  property name -> property value
    # {} nodeinputs: input name -> connected node name

    if not pmap:
        pmap = {}
    props = {}
    for prop in node.m_properties():
        val = getattr(node, prop)
        # Special for arrays. Any other type to include?
        if val.__class__.__name__ == 'bpy_prop_array':
            val = [x for x in val]
        props[prop] = val

    if hasattr(node, 'special_properties'):
        # you can add to a node a function called special_properties
        # to make auto update notice differences outside of m_properties
        props['special_properties'] = node.special_properties()

    links = {}
    for input in node.inputs:
        links[input.name] = ''
        for link in input.links:
            links[input.name] = link.from_node.name
            pmap = map(link.from_node, pmap)
    pmap[node.name] = (props, links)
    return pmap


def differences(map1, map2):
    """Generate differences in properties and inputs of argument maps"""
    props = {}   # differences in properties
    inputs = {}  # differences in inputs
    for node in map1:
        nodeprops1, nodeinputs1 = map1[node]
        if node not in map2:
            props[node] = nodeprops1.keys()
            inputs[node] = nodeinputs1.keys()
        else:
            nodeprops2, nodeinputs2 = map2[node]
            props[node] = compare(nodeprops1, nodeprops2)
            if not props[node]:
                props.pop(node)
            inputs[node] = compare(nodeinputs1, nodeinputs2)
            if not inputs[node]:
                inputs.pop(node)
    return props, inputs


def compare(dict1, dict2):
    """Compare two dictionaries. Return a list of mismatching keys"""
    diff = []
    for k in dict1:
        if k not in dict2:
            diff.append(k)
        else:
            val1 = dict1[k]
            val2 = dict2[k]
            if val1 != val2:
                diff.append(k)
    for k in dict2:
        if k not in dict1:
            diff.append(k)
    return diff


class BVTK_OT_AutoUpdateScan(bpy.types.Operator):
    """BVTK Auto Update Scan"""
    bl_idname = "bvtk.auto_update_scan"
    bl_label = "Auto Update"

    _timer = None
    node_name = bpy.props.StringProperty()
    tree_name = bpy.props.StringProperty()

    def modal(self, context, event):
        if event.type == 'TIMER':
            if self.node_is_valid():
                actual_map = map(self.node)
                props, conn = differences(actual_map, self.last_map)
                if props or conn:
                    self.last_map = actual_map
                    check_cache()
                    try:
                        no_queue_update(self.node, self.node.update_cb)
                    except Exception as e:
                        log.error('ERROR UPDATING ' + str(e))
            else:
                self.cancel(context)
                return {'CANCELLED'}
        return {'PASS_THROUGH'}

    def node_is_valid(self):
        """Node validity test. Return false if node has been deleted or auto
        update has been turned off.
        """
        return self.node.name in self.tree and self.node.auto_update

    def execute(self, context):
        self.tree = bpy.data.node_groups[self.tree_name].nodes
        self.node = bpy.data.node_groups[self.tree_name].nodes[self.node_name]
        self.last_map = map(self.node)
        bpy.ops.bvtk.node_update(node_path=node_path(self.node))
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.01, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        wm = context.window_manager
        wm.event_timer_remove(self._timer)


def cut_excess(original_seq, new_len):
    # Takes a blender BMElemSeq (basically an array)
    # and removes all items that exceed the new length
    original_len = len(original_seq)
    if original_len > new_len:
        for i, el in enumerate(original_seq):
            if i > (new_len-1):
                original_seq.remove(el)


def vtkdata_to_blender(data, name, color_node=None, smooth=False):
    """Convert the given vtkdata creating or overwriting
    a blender object named 'name'.
    """
    if not data:
        log.warning('vtkdata_to_blender -- no data!')
        return
    if issubclass(data.__class__, vtk.vtkImageData):
        imgdata_to_blender(data, name)
        return
    if issubclass(data.__class__, vtk.vtkRectilinearGrid):
        # rect_grid_to_blender(data, name, color_node)
        return
    me, ob = mesh_and_object(name)
    if me.is_editmode:
        bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
    err = 0
    bm = bmesh.new()
    bm.from_mesh(me)  # fill it in from a Mesh
    # Create vertices
    data_p = data.GetPoints()
    bm.verts.ensure_lookup_table()
    verts = []
    log.info("Creating vertices")
    for i in range(data.GetNumberOfPoints()):
        if i < len(bm.verts):
            bm.verts[i].co = data_p.GetPoint(i)
            vert = bm.verts[i]
        else:
            vert = bm.verts.new(data_p.GetPoint(i))
        verts.append(vert)
    # Remove surplus vertices
    log.info("Removing surplus vertices")
    cut_excess(bm.verts, data.GetNumberOfPoints())
    # Creating faces and edges
    bm.faces.ensure_lookup_table()
    log.info("Creating faces")
    for i in range(data.GetNumberOfCells()):
        data_pi = data.GetCell(i).GetPointIds()
        try:
            face_verts = [verts[data_pi.GetId(x)] for x in range(data_pi.GetNumberOfIds())]
            if len(face_verts) == 2:
                e = bm.edges.get(face_verts)
                if not e:
                    e = bm.edges.new(face_verts)
                # Modified edges are marked with a negative index,
                # so that later unmarked edges can be deleted. This
                # approach is suggested by the blender api documentation.
                e.index = -10
            else:
                f = bm.faces.get(face_verts)
                if not f:
                    f = bm.faces.new(face_verts)
                    f.smooth = smooth
                # Modified faces and edges are marked with a negative index,
                # so that later unmarked edges can be deleted. This
                # approach is suggested by the blender api documentation.
                f.index = -10
                for e in f.edges:
                    e.index = -10
        except:
            err += 1
    # Removing surplus faces and edges
    log.info("Removing excess faces")
    for f in bm.faces:
        if f.index == -10:
            continue
        bm.faces.remove(f)
    log.info("Removing excess edges")
    for e in bm.edges:
        if e.index == -10:
            continue
        bm.edges.remove(e)

    if err:
        log.info('num err', err)

    # set normals
    point_normals = data.GetPointData().GetNormals()
    cell_normals = data.GetCellData().GetNormals()
    if cell_normals:
        bm.faces.ensure_lookup_table()
        for i in range(len(bm.faces)):
            bm.faces[i].normal = cell_normals.GetTuple(i)
    if point_normals:
        for i in range(len(verts)):
            verts[i].normal = point_normals.GetTuple(i)

    # apply colors and create lut
    if color_node:
        bm = apply_colors(color_node, bm, me, data)

    bm.to_mesh(me)  # store bmesh to mesh

    log.info('VTK data to blender ok! {} vertices'.format(len(verts)))


def mesh_and_object(name):
    """ method gets/creates an object and his mesh and returns both """
    me = get_item(bpy.data.meshes, name)
    ob = get_object(name, me)
    return me, ob


def get_item(data, *args):
    """ method gets/creates the item with key args[0] from data and return it """
    item = data.get(args[0])
    if not item:
        item = data.new(*args)
    return item


def set_link(data, item):
    """ method links item to data if item isn't already linked """
    if item.name not in data:
        data.link(item)


def get_object(name, data):
    """ method gets/creates object, sets his data, adds it to current scene """
    ob = get_item(bpy.data.objects, name, data)
    ob.data = data
    set_link(bpy.context.scene.objects, ob)
    return ob


# ---------------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------------


def apply_colors(color_node, bm, me, data):
    if color_node.color_by:
        texture = color_node.get_texture()
        color_by = color_node.color_by
        uv_layer = ""
        if color_node.bl_idname == 'BVTK_NT_ColorToImage':  # todo: move color logic inside node classes
            img = color_node.image
            uv_layer = color_node.uv_layer
            if not img:
                log.warning("Image not selected in {} node".format(color_node.name))
            else:
                ramp_to_image(texture.color_ramp, image=img)
        else:
            if color_node.texture_type == 'IMAGE':
                img = ramp_to_image(texture.color_ramp, name=texture.name + 'IMAGE')
                texture = get_item(bpy.data.textures, texture.name + 'IMAGE', 'IMAGE')
                texture.image = img
            texture_material(me, 'VTK' + me.name, texture)

        s_range = (color_node.range_min, color_node.range_max)
        if color_node.lut:
            create_lut(me.name, s_range, 6, texture, font=color_node.font, h=color_node.height)
        if color_by[0] == 'P':
            bm = point_unwrap(bm, data, int(color_by[1:]), s_range, uv_layer)
        else:
            bm = face_unwrap(bm, data, int(color_by[1:]), s_range, uv_layer)
    return bm


def texture_material(me, name, texture = None, texturetype = 'IMAGE'):
    """Get or create a material and link with given texture,
    then apply it to given object.
    """
    if not texture:
        texture = get_item(bpy.data.textures, name, texturetype)
        texture.type = texturetype
    mat = get_item(bpy.data.materials, name)
    if mat.name not in me.materials:
        me.materials.append(mat)
    # Disable other textures
    for ts in mat.texture_slots:
        if ts:
            ts.use = False
    if texture.name not in mat.texture_slots:
        ts = mat.texture_slots.add()
        ts.texture = texture
        ts.texture_coords = 'UV'
    else:
        ts = mat.texture_slots[texture.name]
    ts.use = True

    return texture, mat


def ramp_to_image(ramp, name=None, image=None, w=1000, h=4):
    """ takes a color ramp and creates a blender image h pixel tall
    and w pixels wide. """
    if not image:
        image = get_item(bpy.data.images, name, w, h)
    else:
        w = image.generated_width
        h = image.generated_height
    p = []
    for y in range(h):
        for x in range(w):
            p.extend(ramp.evaluate(x/w))
    image.pixels = p
    # The image could be deleted automatically by blender
    # if it's not used, this must be prevented setting
    # 'use_fake_user' to true
    image.use_fake_user = True
    # The image has to be packed into the file,
    # otherwise it will be deleted after closing blender.
    image.pack(as_png=True)
    return image


def face_unwrap(bm, data, array_index, s_range, uv_layer_key=""):
    scalars = data.GetCellData().GetArray(array_index)
    if scalars is not None:
        minr, maxr = s_range
        if maxr == minr:
            log.warning("Can't unwrap -- values are constant -- range(" + \
                    str(minr) + "," + str(maxr) + ")!")
            return bm
        uv_layer = bm.loops.layers.uv.get(uv_layer_key)
        if not uv_layer:
            uv_layer = bm.loops.layers.uv.verify()
        bm.faces.index_update()
        for face in bm.faces:
            for loop in face.loops:
                v = (scalars.GetValue(face.index) - minr)/(maxr - minr)
                # Force value inside range.
                v = min(0.999, max(0.001, v))
                loop[uv_layer].uv = (v, 0.5)
    return bm


def point_unwrap(bm, data, array_index, s_range, uv_layer_key=""):
    scalars = data.GetPointData().GetArray(array_index)
    if scalars is not None:
        minr, maxr = s_range
        if maxr == minr:
            log.warning("Can't unwrap, values are constant: range({},{})!".format(minr, maxr))
            return bm
        uv_layer = bm.loops.layers.uv.get(uv_layer_key)
        if not uv_layer:
            uv_layer = bm.loops.layers.uv.verify()
        bm.verts.index_update()
        for face in bm.faces:
            for loop in face.loops:
                v = (scalars.GetValue(loop.vert.index) - minr)/(maxr - minr)
                # Force value inside range.
                v = min(0.999, max(0.001, v))
                loop[uv_layer].uv = (v, 0.5)
    return bm


# -----------------------------------------------------------------------------
# Color legend
# -----------------------------------------------------------------------------


def text(name, body):
    """Get/create a text data block"""
    font = get_item(bpy.data.curves, name, 'FONT')
    ob = get_object(name, font)
    font.body = body
    return ob


def delete_texts(name):
    """Delete text data block"""
    for ob in bpy.data.objects:
        if ob.name.startswith(name):
            curve = ob.data
            bpy.data.objects.remove(ob)
            bpy.data.curves.remove(curve)


def create_lut(name, Range, n_div, texture, font="", b=0.5, h=5.5, x=5, y=0, z=0, fontsize=0.35, roundto=2):
    """Create value labels and color legends and add to current scene"""
    name = name+'_colormap'
    delete_texts(name+'_lab') # Delete old labels
    # Create plane and UVs
    plane = bmesh.new()
    plane.faces.new((
        plane.verts.new((0, 0, 0)),
        plane.verts.new((b, 0, 0)),
        plane.verts.new((b, 0, h)),
        plane.verts.new((0, 0, h)),
    ))
    uv_layer = plane.loops.layers.uv.verify()
    plane.faces.ensure_lookup_table()
    plane.faces[0].loops[0][uv_layer].uv = (0, 1)
    plane.faces[0].loops[1][uv_layer].uv = (0, 0)
    plane.faces[0].loops[2][uv_layer].uv = (1, 0)
    plane.faces[0].loops[3][uv_layer].uv = (1, 1)
    me, ob = mesh_and_object(name)
    plane.to_mesh(me)
    texture_material(me, name, texture)
    min, max = Range
    if min>max or h<=0:
        log.error('range maximum greater than minimum')
        return
    import math
    idealspace = (max-min)/(h)
    exponent = math.floor(math.log10(idealspace))
    mantissa = idealspace/(10**exponent)
    if mantissa < 2.5:
        step = 10 ** exponent
    elif mantissa < 7.5:
        step = 5*10**exponent
    else:
        step = 10*10**exponent
    start = math.ceil(min/step)*step
    delta = max-min
    if step>delta:
        return
    starth = (h*(start-min))/delta
    steph = (h*step)/delta

    # Add labels as texts
    for i in range(int(math.floor((max-start)/step))+1):
        t = text(name+'_lab'+str(i), '{:.15}'.format(float(start+i*step)))
        t.data.size = fontsize
        if font:
            t.data.font = font
        t.rotation_mode = 'XYZ'
        t.rotation_euler = (1.5707963705062866, 0.0, 0.0)
        t.location = b+b/5, 0, starth+steph*i
        t.parent = ob


# -----------------------------------------------------------------------------
#  Rectilinear grid data conversion
# -----------------------------------------------------------------------------

def rect_grid_to_blender(data, name, color_node):
    """Under development.
    Convert vtkImageData to a Blender object with a
    volumetric material.
    """

    from array import array

    if color_node.color_by[0] == 'P':
        data_array = data.GetPointData().GetArray(int(color_node.color_by[1:]))
    else:
        data_array = data.GetCellData().GetArray(int(color_node.color_by[1:]))

    dim = data.GetDimensions()
    s_range = (color_node.range_min, color_node.range_max)
    img_slice_size = dim[0]*dim[1]
    # min_r, max_r = s_range
    # color_ramp = color_node.get_texture().color_ramp
    # color_ramp = color_node.get_texture().color_ramp

    min_r = None
    max_r = None

    for j in range(img_slice_size):
        val = data_array.GetValue(j)
        if max_r is None or val > max_r:
            max_r = val
        if min_r is None or val < min_r:
            min_r = val

    nx = dim[0]
    ny = dim[1]
    nz = dim[2]
    nf = 1
    header = [nx, ny, nz, nf]
    vol_data = []
    i = 0
    for t in range(nf):  # frame
        for z in range(nz):  # layer
            for y in range(ny):  # line
                for x in range(nx):  # value
                    val = (data_array.GetValue(i) - min_r) / (max_r - min_r)
                    vol_data.append(val)
                    i += 1
    binfile = open('/tmp/', 'wb')
    header = array("I", header)
    vol_data = array("f", vol_data)
    header.tofile(binfile)
    vol_data.tofile(binfile)

    log.info("Done")

# -----------------------------------------------------------------------------
#  Image data conversion
# -----------------------------------------------------------------------------


def imgdata_to_blender(data, name):
    """Convert vtkImageData to a Blender image"""

    wm = bpy.context.window_manager
    scalars = data.GetPointData().GetScalars()
    if not scalars:
        scalars = data.GetPointData().GetArray(0)

    # Generate image data to img
    dim = data.GetDimensions()
    z = 0
    wm.progress_begin(0, 100)
    if name in bpy.data.images:
        bpy.data.images.remove(bpy.data.images[name])
    img = bpy.data.images.new(name, dim[0], dim[1])
    l = scalars.GetNumberOfTuples()
    p = []
    prog = 0
    l_prog = 1
    for j in range(l):
        t = scalars.GetTuple(j)
        if len(t) == 1:
            p.extend([t[0] / 255, t[0] / 255, t[0] / 255, 1])
        else:
            alpha = 1 if len(t) < 4 else t[3]/255
            p.extend([t[0]/255, t[1]/255, t[2]/255, alpha])

        prog = int(j/l*100)
        if prog != l_prog:
            l_prog = prog
            wm.progress_update(prog)
            print('Converting to img: '+str(prog)+'%', end='\r'),
    img.pixels = p
    wm.progress_end()
    log.info('Image data conversion successful, num pixels = ' + str(l))

    # Create plane mesh with UVs to show the image
    spacing = data.GetSpacing() if hasattr(data, "GetSpacing") else (1,)
    x = dim[0] * spacing[0]
    y = dim[1] * spacing[0]
    plane = bmesh.new()
    plane.faces.new((
        plane.verts.new((0, 0, 0)),
        plane.verts.new((x, 0, 0)),
        plane.verts.new((x, y, 0)),
        plane.verts.new((0, y, 0)),
    ))
    uv_layer = plane.loops.layers.uv.verify()
    plane.faces.ensure_lookup_table()
    plane.faces[0].loops[0][uv_layer].uv = (0, 0)
    plane.faces[0].loops[1][uv_layer].uv = (1, 0)
    plane.faces[0].loops[2][uv_layer].uv = (1, 1)
    plane.faces[0].loops[3][uv_layer].uv = (0, 1)
    me, ob = mesh_and_object(name)
    ob.location = data.GetOrigin() if hasattr(data, "GetOrigin") else (0, 0, 0)
    plane.to_mesh(me)
    tex, mat = texture_material(me, 'VTK' + name)
    mat.use_shadeless = True
    tex.image = img


# Add classes and menu items
TYPENAMES = []
add_class(BVTK_NT_ToBlender)
TYPENAMES.append('BVTK_NT_ToBlender')
menu_items = [NodeItem(x) for x in TYPENAMES]
CATEGORIES.append(BVTK_NodeCategory("Converter", "Converter", items=menu_items))

add_class(BVTK_OT_NodeUpdate)
add_ui_class(BVTK_OT_AutoUpdateScan)
add_ui_class(BVTK_OT_NodeWrite)
