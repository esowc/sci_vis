import sqlite3
from jinja2 import Template

# -------------------------------------
# sqlite3 shortcuts
# -------------------------------------


def retrieve_query(query, param=()):
    for statement in query.split(";"):
        if statement.strip():
            cursor.execute(statement, param)
            return cursor.fetchall()


# -------------------------------------
# Retrieve data from the DB file
# -------------------------------------
conn = sqlite3.connect("VTKClasses.sqlite")
cursor = conn.cursor()


def get_classes(group):
    classes = retrieve_query(
        """SELECT VTKClassID, C.Name, OutPortsNumber, InPortsNumber, Doc FROM VTKClasses C
        INNER JOIN VTKClassGroups G ON VTKClassGroupFK = VTKClassGroupID WHERE G.Name = ?""",
        (group, ))
    class_list = []
    for c in classes:
        class_data = {
            "Name": c[1],
            "MProps": [],
            "OutPortsNumber": c[2],
            "InPortsNumber": c[3],
            "Doc": c[4],
            "ExtraConnections": [],
            "Methods": []
        }
        props = retrieve_query("SELECT VTKMPropID, Name, Type, Size, DefaultValue, Description "
                               "FROM VTKMProps WHERE VTKClassFK = ?", (c[0], ))
        for prop in props:
            p_id = prop[0]
            p_name = prop[1]
            p_type = prop[2]
            p_size = prop[3]
            p_value = prop[4]
            p_desc = prop[5]

            if p_type == "VTKObject":
                class_data['ExtraConnections'].append(p_name)
                continue  # not a property

            p_type += "Property"

            if p_type == 'BoolProperty' and p_value != "True" and p_value != "False":
                if p_value[0] != 0:
                    p_value = "True"
                else:
                    p_value = "False"

            # Retrieve enum items
            p_enum_items = []
            enum_rows = retrieve_query("SELECT EnumItem FROM VTKMPropEnumItems WHERE VTKMPropFK = ?", (p_id,))
            for row in enum_rows:
                p_enum_items.append(row[0])

            # Clamp integers and floats
            def clamp_int(value):
                return max(min(int(value), 1000000000), -1000000000)

            def clamp_float(value):
                return max(min(float(value), 1e30), -1e30)

            if p_type == 'IntProperty':
                p_value = repr(clamp_int(p_value))
            if p_type == 'FloatProperty':
                p_value = repr(clamp_float(p_value))
            if p_type == 'IntVectorProperty':
                list = eval(p_value)
                p_value = repr([clamp_int(x) for x in list])
            if p_type == 'FloatVectorProperty':
                list = eval(p_value)
                p_value = repr([clamp_float(x) for x in list])

            class_data['MProps'].append({
                "Name":         p_name,
                "Type":         p_type,
                "Size":         p_size,
                "DefaultValue": p_value,
                "EnumItems":    p_enum_items,
                "Description":  p_desc
            })

        methods = retrieve_query("SELECT VTKMethodFK FROM VTKClassMethods WHERE VTKClassFK = ?", (c[0],))
        for method in methods:
            class_data["Methods"].append(method[0])

        class_list.append(class_data)
    return class_list


def get_methods(group):
    methods = retrieve_query("""SELECT VTKMethodID, Fullname, M.Name, VTKReturnFK FROM VTKMethods M
                             INNER JOIN VTKMethodGroups G ON VTKMethodGroupFK = VTKMethodGroupID WHERE G.Name = ?""",
                             (group,))
    method_list = []
    for method in methods:
        m_data = {
            "MethodID": method[0],
            "Fullname": method[1],
            "Name": method[2],
            "MethodArguments": None,
            "ReturnVariable": None
        }
        arguments = retrieve_query("SELECT VTKVariableFK, ArgumentIndex FROM VTKMethodArguments "
                                   "WHERE VTKMethodFK = ? ORDER BY ArgumentIndex", (method[0],))
        arg_list = []
        for arg in arguments:
            var_id = arg[0]
            var = retrieve_query("SELECT Name, Type, Size FROM VTKVariables WHERE VTKVariableID = ?", (var_id, ))
            var = var[0]
            arg_list.append({
                "Name": var[0],
                "Type": var[1] + "Property",
                "Size": var[2],
                "ArgumentIndex": arg[1]
            })
        m_data["MethodArguments"] = arg_list
        if method[3]:
            return_var = retrieve_query("SELECT Name, Type, Size FROM VTKVariables WHERE VTKVariableID = ?", (method[3], ))
            return_var = return_var[0]
            m_data["ReturnVariable"] = {
                "Name": return_var[0],
                "Type": return_var[1] + "Property",
                "Size": return_var[2]
            }
        method_list.append(m_data)
    return method_list


# -------------------------------------
# Node file template
# -------------------------------------
node_template_s = """from .. core import *
cat = "{{MENU}}"
{% for C in node_classes %}

# --------------------------------------------------------------


class BVTK_NT_{{C.NAME}}(Node, {{BASE}}):

    bl_idname = "BVTK_NT_{{C.NAME}}"
    bl_label = "vtk{{C.NAME}}"
    {% for x in C.ENUM_ITEMS %}{{x}}
    {% endfor %}
    {% for x in C.PROPS  %}{{x.definition}}
    {% endfor %}
    b_properties = bpy.props.BoolVectorProperty(name="", size={{C.NP}}, get={{BASE}}.get_b, set={{BASE}}.set_b)

    def m_properties(self):
        return [{% for x in C.PROPS %}"{{x.prefix}}{{x.name}}", {% endfor %}]
    
    def m_connections(self):
        return {{C.CONNECTIONS}}
    
    def methods(self):
        return {{C.METHODS}}


add_node(BVTK_NT_{{C.NAME}}, cat)
{% endfor %}

# --------------------------------------------------------------

"""
node_template = Template(node_template_s)


# -------------------------------------
# Node files writing
# -------------------------------------

def generate_node_file(group):
    classes = get_classes(db_tables[group])

    template_dict = {'MENU': group, 'node_classes': [], 'BASE': bases[group]}

    for class_data in classes:

        class_dict = {
            'NAME': class_data['Name'],
            'PROPS': [],
            'ENUM_ITEMS': [],
            'CONNECTIONS': ((), (), (), ()),
            "METHODS": []
        }

        for prop in class_data["MProps"]:

            p_name, p_type, p_default, p_size, p_items, p_desc = \
                prop["Name"], prop["Type"], prop["DefaultValue"], \
                prop["Size"], prop["EnumItems"], prop["Description"][:-1]

            prop_dict = {"name": p_name}

            prefix = "m_"

            items_arg = ""
            if p_items:  # the property is an enum
                prefix = "e_"
                items_arg = ", items={}{}_items".format(prefix, p_name)
                class_dict["ENUM_ITEMS"].append("{}{}_items = [(x, x, x) for x in {}]".format(prefix, p_name, p_items))

            prop_dict['prefix'] = prefix

            if p_size == 0:
                p_size = ""
            else:
                p_size = ", size=" + str(p_size)

            if p_type == "StringProperty" and "FileName" in p_name:
                items_arg = ", subtype='FILE_PATH'"

            if p_default is not None:
                p_default = ", default={}".format(p_default)
            else:
                p_default = ""

            p_desc = repr(p_desc)

            prop_dict["definition"] = "{}{} = bpy.props.{}(name='{}', description={}{}{}{})".format(
                prefix,
                p_name,
                p_type,
                p_name,
                p_desc,
                p_default,
                p_size,
                items_arg
            )
            class_dict["PROPS"].append(prop_dict)

        in_ports = class_data["InPortsNumber"]
        if in_ports == 1:
            input_ports = ["Input"]
        else:
            input_ports = ["Input " + str(i) for i in range(in_ports)]

        out_ports = class_data["OutPortsNumber"]
        if out_ports == 1:
            output_ports = ["Output"]
        else:
            output_ports = ["Output " + str(i) for i in range(out_ports)]

        extra_inputs = class_data["ExtraConnections"]
        extra_outputs = []
        if group not in ["Source", "Reader", "Writer", "Filter", "Filter1", "Filter2"]:
            extra_outputs = ["Self"]
        class_dict["CONNECTIONS"] = repr((input_ports, output_ports, extra_inputs, extra_outputs))[1:][:-1]

        class_dict["NP"] = max(1, len(class_dict["PROPS"]))

        if class_dict["NP"] > 32:  # blender BoolVector max size is 32
            print(class_dict["NAME"], "has too many properties ({})".format(class_dict["NP"]))
        else:
            template_dict["node_classes"].append(class_dict)

    text = node_template.render(template_dict)
    f = open(node_filenames[group], "w")
    f.write(text)
    f.close()


bases = {
    "Sources": "BVTK_Node",
    "Readers": "BVTK_Node",
    "Writers": "BVTK_Node",
    "Filters": "BVTK_Node",
    "Filters 1": "BVTK_Node",
    "Filters 2": "BVTK_Node",
    "Transform": "BVTK_Node",
    "Implicit Functions": "BVTK_Node",
    "Parametric Functions": "BVTK_Node",
    "Integrators": "BVTK_Node"
}

node_filenames = {
    "Sources":         "output/gen_vtk_sources.py",
    "Readers":         "output/gen_vtk_readers.py",
    "Writers":         "output/gen_vtk_writers.py",
    "Filters":         "output/gen_vtk_filters.py",
    "Filters 1":        "output/gen_vtk_filters1.py",
    "Filters 2":        "output/gen_vtk_filters2.py",
    "Transform":      "output/gen_vtk_transform.py",
    "Implicit Functions":   "output/gen_vtk_implicit_func.py",
    "Parametric Functions": "output/gen_vtk_parametric_func.py",
    "Integrators":     "output/gen_vtk_integrator.py"
}

db_tables = {
    "Sources"             : "Source",
    "Readers"             : "Reader",
    "Writers"             : "Writer",
    "Filters"             : "Filter",
    "Filters 1"           : "Filter1",
    "Filters 2"           : "Filter2",
    "Transform"           : "Transform",
    "Implicit Functions"  : "ImplicitFunc",
    "Parametric Functions": "ParametricFunc",
    "Integrators"         : "Integrator",
}

generate_node_file("Sources")
generate_node_file("Readers")
generate_node_file("Writers")
generate_node_file("Filters 1")
generate_node_file("Filters 2")
generate_node_file("Filters")
generate_node_file("Transform")
generate_node_file("Implicit Functions")
generate_node_file("Parametric Functions")
generate_node_file("Integrators")

# -------------------------------------
# Socket file template
# -------------------------------------
socket_template_s = """from .core import *
{% for S in SOCKETS %}

# --------------------------------------------------------------


class BVTK_NS_{{S.ID}}(NodeSocket, BVTK_NodeSocket):

    bl_idname = 'BVTK_NS_{{S.ID}}'
    bl_label = '{{S.NAME}}'
    fullname = bpy.props.StringProperty(default='{{S.FULLNAME}}')
    {% for x in S.PROPS  %}{{x.definition}}
    {% endfor %}

    def a_properties(self):
        return [{% for x in S.PROPS %}'{{x.prefix}}{{x.name}}', {% endfor %}]


add_socket(BVTK_NS_{{S.ID}}, {{S.ID}})
{% endfor %}

# --------------------------------------------------------------

"""
socket_template = Template(socket_template_s)


# -------------------------------------
# Socket file writing
# -------------------------------------


def generate_sockets(group):
    methods = get_methods(group)

    template_dict = {'SOCKETS': []}

    for method in methods:
        socket_dict = {
            "ID": str(method["MethodID"]),
            "NAME": method["Name"],
            "FULLNAME": method["Fullname"],
            "PROPS": []
        }

        skip_method = False  # invalid methods won't be considered

        for arg in method["MethodArguments"]:
            a_name, a_type, a_size = arg["Name"], arg["Type"], arg["Size"]
            prefix = "a_"
            prop_dict = dict(name=a_name, prefix=prefix)

            if a_size == 0:
                a_size = ''
            elif a_size>32:
                skip_method = True  # Blender max vector size is 32
            else:
                a_size = ", size=" + str(a_size)

            if a_type == "StringProperty" and "FileName" in a_name:
                items_arg = ", subtype='FILE_PATH'"

            if a_type == "VTKObjectProperty":
                skip_method = True  # methods with objects as arguments won't be considered

            if not a_name:
                a_name = "arg{}".format(arg["ArgumentIndex"])

            prop_dict["definition"] = "{}{} = bpy.props.{}(name='{}'{})".format(
                prefix,
                a_name,
                a_type,
                a_name,
                a_size,
            )
            socket_dict["PROPS"].append(prop_dict)

        if skip_method:
            continue

        template_dict["SOCKETS"].append(socket_dict)

    text = socket_template.render(template_dict)
    f = open(socket_filenames[group], "w")
    f.write(text)
    f.close()


socket_filenames = {
    "Setter": "gen_VTKSetters.py",
    "Getter": "gen_VTKGetters.py"
}

# generate_sockets("Setter")
# generate_sockets("Getter")

print("Generation complete.")
