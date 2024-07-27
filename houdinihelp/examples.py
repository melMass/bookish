from __future__ import print_function
import os.path
import re
from collections import defaultdict

from hutil.Qt import QtCore, QtGui, QtWidgets


EGFOR_SECTION_NAME = "EXAMPLE_FOR"
EGFOR_DATA_KEY = "__example_for"
MANAGER = {
    "Chop": "chopnet",
    "Cop2": "cop2net",
    "Dop": "dopnet",
    "Driver": "ropnet",  # sigh :(
    "Lop": "lopnet",
    "Sop": "geo",
    "Top": "topnet",
    "Vop": "vopnet"
}


example_index = {}


def index_for_category(category):
    catname = category.name()
    try:
        return example_index[catname]
    except KeyError:
        cat_index = example_index[catname] =defaultdict(set)
        return cat_index


def encode_node_token(category, hdafile, typename):
    return "%s|%s|%s" % (category.name(), hdafile, typename)


def decode_node_token(token):
    import hou
    catname, hdafile, typename = token.split("|")
    category = hou.nodeTypeCategories()[catname]
    return category, hdafile, typename


class ExampleRef(object):
    def __init__(self, target_category, target_typename, example_definition,
                 description=None):
        # NodeTypeCategory
        self.target_category = target_category
        # string - name of the node type this is an example for; we use a string
        # so it can be the key in a dictionary
        self.target_typename = target_typename
        # HDA Definition
        self.example_definition = example_definition
        # string - optional description string for legacy examples
        self._description = description

    def _comparables(self):
        # Return a unique immutable tuple for this example that can be used for
        # equality testing and hashing
        defn = self.example_definition
        return (
            self.target_category.name(),
            self.target_typename,
            defn.nodeTypeCategory().name(),
            defn.nodeTypeName(),
            defn.libraryFilePath()
        )

    def __eq__(self, other):
        return (type(self) is type(other) and
                self._comparables() == other._comparables())

    def __hash__(self):
        return hash(self._comparables())

    def token(self):
        defn = self.example_definition
        return encode_node_token(
            defn.nodeTypeCategory(),
            defn.libraryFilePath(),
            defn.nodeTypeName()
        )

    def target_type(self):
        return self.target_category.nodeType(self.target_typename)

    def description(self):
        if self._description:
            return self._description
        else:
            return self.example_definition.description()

    def create(self, beside=None):
        return create_example_node(self.example_definition, beside=beside)


# Example indexing

def refs_for_hdafile(filepath):
    import hou

    for defn in hou.hda.definitionsInFile(filepath):
        try:
            if defn.hasSection(EGFOR_SECTION_NAME):
                for ref in refs_for_definition(defn):
                    yield ref
        except hou.ObjectWasDeleted:
            continue


def refs_for_definition(defn):
    category = defn.nodeTypeCategory()
    egforsect = defn.sections()[EGFOR_SECTION_NAME]
    targets = egforsect.contents()
    for target_typename in re.split(r"\s+", targets.strip()):
        yield ExampleRef(category, target_typename, defn)


def add_legacy_examples():
    import hou

    try:
        egdirs = hou.findDirectories("help/examples/nodes")
    except hou.OperationFailed:
        egdirs = []

    for egdir in egdirs:
        _add_refs_for_legacy_topdir(egdir)


def _add_refs_for_legacy_topdir(egdir):
    import hou
    from houdinihelp.api import dir_to_table

    catdict = hou.nodeTypeCategories()
    for catdir in os.listdir(egdir):
        if not catdir in dir_to_table:
            continue
        catname = dir_to_table[catdir]
        typecat = catdict[catname]
        _add_refs_for_legacy_cat("%s/%s" % (egdir, catdir), typecat)


def _add_refs_for_legacy_cat(catdir, typecat):
    cat_index = index_for_category(typecat)
    typedict = typecat.nodeTypes()
    for typedir in os.listdir(catdir):
        if not typedir in typedict:
            continue
        nodetype = typedict[typedir]
        _add_refs_for_legacy_type("%s/%s" % (catdir, typedir), nodetype,
                                  cat_index)


def _add_refs_for_legacy_type(typedir, nodetype, cat_index):
    import hou

    for libname in os.listdir(typedir):
        if not (libname.endswith(".hda") or libname.endswith(".otl")):
            continue
        libpath = "%s/%s" % (typedir, libname)

        try:
            defns = hou.hda.definitionsInFile(libpath)
        except hou.OperationFailed:
            # This can fail if an HDA file is badly formed
            print("Warning: could not open HDA file %s" % libpath)
            continue

        for defn in defns:
            desc = libname.replace(".otl", "").replace(".hda", "")
            ref = ExampleRef(nodetype.category(), nodetype.name(), defn,
                             description=desc)
            cat_index[ref.target_typename].add(ref)


def rebuild_example_index():
    import hou

    example_index.clear()
    for filepath in hou.hda.loadedFiles():
        add_examples_from_hdafile(filepath)

    # Index old-style examples
    from time import time
    # t = time()
    add_legacy_examples()
    # print("Legacy: %0.04f" % (time() - t))


def add_examples_from_hdafile(filepath):
    for ref in refs_for_hdafile(filepath):
        cat_index = index_for_category(ref.target_category)
        cat_index[ref.target_typename].add(ref)


def remove_examples_from_hdafile(filepath):
    for ref in refs_for_hdafile(filepath):
        cat_index = index_for_category(ref.target_category)
        cat_index[ref.target_typename].discard(ref)


def update_examples_callback(event_type, library_path):
    import hou

    if event_type == hou.hdaEventType.LibraryInstalled:
        add_examples_from_hdafile(library_path)
    elif event_type == hou.hdaEventType.LibraryUninstalled:
        remove_examples_from_hdafile(library_path)


def setup_examples():
    import hou

    # Build the initial reverse index of node type -> example set
    rebuild_example_index()
    # Set up callback so subsequent changes will update the index
    hou.hda.addEventCallback((hou.hdaEventType.LibraryInstalled,
                              hou.hdaEventType.LibraryUninstalled),
                             update_examples_callback)


def examples_for(node):
    return examples_for_nodetype(node.type())


def examples_for_nodetype(nodetype):
    cat_index = index_for_category(nodetype.category())
    typename = nodetype.name()
    refs = list(cat_index.get(typename, ()))
    refs.sort(key=lambda ref: ref.description())
    return refs


def nodetype_has_examples(nodetype):
    cat_index = index_for_category(nodetype.category())
    typename = nodetype.name()
    return bool(cat_index.get(typename))


def examples_menu(node):
    # The person who made this API didn't know Python, so we have to build a
    # flat list of ["token1", "Label 1", "token2", "Label 2"] because they
    # didn't know about tuples
    menu = []
    if node:
        for ref in examples_for(node):
            menu.extend((ref.token(), ref.description()))
    return menu


def has_examples(node):
    return nodetype_has_examples(node.type())


def can_have_example(node):
    if node:
        defn = node.type().definition()
        if defn:
            return not defn.hasSection(EGFOR_SECTION_NAME)
    return False


def load_token(token, node, shift=False, alt=False):
    category, hdafile, typename = decode_node_token(token)
    return load_node_example(category, hdafile, typename, node, enter=shift,
                             extract=alt)


def load_node_example(example_category, hdafile, example_typename, node,
                      enter=False, extract=False):
    import hou

    hou.hda.installFile(hdafile)
    for defn in hou.hda.definitionsInFile(hdafile):
        if (
            defn.nodeTypeCategory() == example_category and
            defn.nodeTypeName() == example_typename
        ):
            break
    else:
        return hou.ui.displayMessage(
            "Error loading %s %s from %s" %
            (example_typename, example_category.name(), hdafile),
            hou.severityType.Error,
        )

    return create_example_node(defn, beside=node, enter=enter, extract=extract)


def create_example_node(defn, beside=None, select=True, enter=False,
                        extract=False):
    import hou

    is_beside = False

    if beside:
        # Create the example "beside" (in the same network) as a "target" node
        network = beside.parent()
        egnode = create_example_in(defn, network)

        if egnode.parent() == network:
            is_beside = True
            # Move the node we created beside the existing node
            pos = beside.position()
            egnode.setPosition(hou.Vector2(pos.x() + 3, pos.y()))

    else:
        # Just create the example at the object level
        egnode = create_example_in(defn, hou.node("/obj"))

    # Display a comment telling the user to dive inside
    egnode.setComment("Double-click to view example network")
    egnode.setGenericFlag(hou.nodeFlag.DisplayComment, True)
    egnode.allowEditingOfContents(True)

    if extract and is_beside:
        egnode.extractAndDelete()
    elif enter:
        hou.setPwd(egnode)
    elif select:
        hou.setPwd(egnode.parent())
        egnode.setSelected(True, clear_all_selected=True)

    return egnode


def create_example_in(defn, network):
    import hou

    typecat = defn.nodeTypeCategory()
    typename = defn.nodeTypeName()
    nodename = typename.replace(":", "_").replace(".", "_")
    netcat = network.childTypeCategory()

    if netcat == typecat:
        egnode = network.createNode(typename, node_name=nodename)

    elif typecat == hou.objNodeTypeCategory():
        egnode = obj = create_example_obj(defn)

        # Check if this is an old-style example and we can copy its contents
        # into a subnet in the desired network
        items = obj.allItems()
        if len(items) == 1 and items[0].childTypeCategory() == netcat:
            # Create a subnet in the target network as a container for the
            # example contents
            egnode = network.createNode("subnet", node_name=nodename)

            # Copy and paste the contents of the example from the asset into the
            # subnet
            items[0].copyItemsToClipboard(items[0].allItems())
            egnode.pasteItemsFromClipboard()
            #hou.copyNodesTo(items[0].allItems(), egnode)

            # Delete the asset
            obj.destroy()
    else:
        egnode = create_example_obj(defn)

    return egnode


def create_example_obj(defn):
    import hou

    network = hou.node("/obj")

    typecat = defn.nodeTypeCategory()
    catname = typecat.name()
    typename = defn.nodeTypeName()
    nodename = typename.replace(":", "_").replace(".", "_")

    if catname == "Object":
        egnode = network.createNode(typename, exact_type_name=True)
    else:
        # Not an object network, create a manager to contain the example asset
        egnode = network.createNode(MANAGER[catname], node_name=nodename)
        egnode.moveToGoodPosition()
        egnode.createNode(typename, exact_type_name=True)

    egnode.allowEditingOfContents(True)
    return egnode


# Example creation workflow

def start_node_example(node, alt=False):
    import hou

    network = node.parent()

    nodetype = node.type()
    typename = nodetype.name()
    _, ns, corename, ver = hou.hda.componentsFromFullNodeTypeName(typename)

    # Create a subnet to hold the example
    subnet_name = corename + "_example"
    subnet = network.createNode("subnet", subnet_name)

    # Move the subnet next to the original node
    pos = node.position()
    subnet.setPosition(hou.Vector2(pos.x() + 3, pos.y()))
    # Remember which node we're making an example for
    subnet.setUserData(EGFOR_DATA_KEY, typename)
    # Set the comment to tell the user what to do with this subnet
    subnet.setComment(
        "Build example network inside,\nthen RMB > Save Node Example"
    )
    # Turn on comment display on the subnet
    subnet.setGenericFlag(hou.nodeFlag.DisplayComment, True)

    # Create a note inside the subnet with a
    note = subnet.createStickyNote()
    note.setName("__example_instructions")
    note.setSize(hou.Vector2(5, 5))
    note.setText((
        "Build a network here to demonstrate the use of the {} node. "
        "To save this example, go up, right-click this subnet, and choose "
        "Save Node Example."
    ).format(nodetype.description()))
    note_pos = note.position()
    note.setDrawBackground(False)
    note.setTextColor(hou.ui.colorFromName("GraphPromptText"))
    note.setTextSize(0.4)

    # Create a note telling the user to write a description of the example
    desc = subnet.createStickyNote()
    desc.setName("__example_description")
    desc.setSize(hou.Vector2(4, 2.5))
    desc.setPosition(hou.Vector2(note_pos.x() + 6, note_pos.y()))
    desc.setText(
        "Replace this text with a description of this example. "
        # "This text will be used to make the example searchable."
    )
    desc.setColor(hou.Color(0.765, 1, 0.576))


def save_node_example(subnet, alt=False):
    import hou

    # Get the node type this is an example for
    typename = subnet.userData(EGFOR_DATA_KEY)
    # Get the library path and other info for the target node
    category = subnet.type().category()
    nodetype = category.nodeType(typename)
    # _, ns, corename, ver = hou.hda.componentsFromFullNodeTypeName(typename)

    mainwin = hou.qt.mainWindow()
    dialog = NodeExampleDialog(nodetype, name=subnet.name(), parent=mainwin)
    if not dialog.exec_():
        # User cancelled the save dialog
        button = hou.ui.displayMessage(
            "Delete the subnetwork?",
            buttons=("Keep", "Delete"),
            default_choice=0, close_choice=0,
            help="If you want to continue editing the example network, click Keep.",
        )
        if button == 1:
            subnet.destroy()
        return

    egpath = dialog.libraryPath()
    egname = dialog.internalName()
    eglabel = dialog.exampleLabel()
    del dialog

    _, ns, corename, ver = hou.hda.componentsFromFullNodeTypeName(egname)

    # Check if the example internal name already exists
    if os.path.exists(egpath):
        try:
            defns = list(hou.hda.definitionsInFile(egpath))
        except hou.OperationFailed:
            return hou.ui.displayMessage(
                "%s is not a valid HDA library file",
                severity=hou.severityType.Error,
            )

        counter = 0
        while True:
            if counter:
                tryname = egname + "_" + str(counter + 1)
            else:
                tryname = egname

            # Loop through the typenames in this library, checking for naming
            # conflicts
            for defn in defns:
                if defn.nodeTypeName() == tryname:
                    break
            else:
                # We got through the list without breaking, so break out of
                # the outer loop
                break
            counter += 1

    # Find and delete the instructions sticky note inside the subnet
    note = subnet.node("__example_instructions")
    if note:
        note.destroy()
    # Delete marker (strangely it survives being turned into an asset)
    subnet.destroyUserData(EGFOR_DATA_KEY)

    # Convert the subnet into an asset, saved in the same .hda file as the
    # target node
    try:
        egnode = subnet.createDigitalAsset(egname, egpath, eglabel)
    except hou.OperationFailed:
        return hou.ui.displayMessage(
            "Could not turn the subnet into an asset",
            severity=hou.severityType.Error,
        )

    # Note: "egnode" is the node instance created from the subnet; we need to
    # get its type and definition from that
    egtype = egnode.type()
    egdef = egtype.definition()
    # Hide from tab menu
    egtype.setHidden(True)
    # Mark this as an example
    egdef.addSection(EGFOR_SECTION_NAME, typename)
    # Set icon
    egdef.setIcon("MISC_present")

    # Set more HDA options
    options = egdef.options()
    options.setUnlockNewInstances(True)
    egdef.setOptions(options)

    # Unlock the example instance in case the user wants to edit it further
    egnode.allowEditingOfContents()

    # Put some final instructions on the example instance
    egnode.setComment(
        "You can continue to edit this example and sync the asset.\n"
        "Or just delete this instance of the example."
    )
    egnode.setGenericFlag(hou.nodeFlag.DisplayComment, True)

    # Update the index with this new example
    egref = ExampleRef(category, nodetype.name(), egdef)
    cat_index = index_for_category(category)
    cat_index[egref.target_typename].add(egref)


class NodeExampleDialog(QtWidgets.QDialog):
    def __init__(self, nodetype, name=None, parent=None):
        super(NodeExampleDialog, self).__init__(parent)
        self._nodetype = nodetype
        self._name = name

        self.setWindowTitle("Save Node Example")
        self._setup_ui()
        self._ignore = False

    def _setup_ui(self):
        import hou

        nodetype = self._nodetype
        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignRight)
        self.setLayout(form)

        # Label showing what node type this example is for
        type_label = QtWidgets.QLabel(
            "<b>%s</b> (%s)" % (nodetype.description(),
                                nodetype.category().name())
        )
        form.addRow("Example for", type_label)

        # Pop-up menu letting you choose what library to save the example in
        self.where_menu = QtWidgets.QComboBox()
        libpath = nodetype.definition().libraryFilePath()
        prefpath = os.environ["HOUDINI_USER_PREF_DIR"] + "/otls/examples.hda"
        self.where_menu.addItem("Same library as target asset", libpath)
        self.where_menu.addItem("In user preferences", prefpath)
        try:
            pathdirs = hou.findDirectories("otls")
        except hou.OperationFailed:
            pathdirs = []
        for pathdir in pathdirs:
            if not os.access(pathdir, os.W_OK):
                continue
            pathpath = pathdir + "/examples.hda"
            if pathpath == prefpath:
                continue
            self.where_menu.addItem(pathpath, pathpath)
        self.where_menu.addItem("Embedded", "Embedded")
        self.where_menu.addItem("Custom library", "")
        self.where_menu.currentIndexChanged.connect(self._where_changed)
        form.addRow("Save to Library", self.where_menu)

        # Editable path to library
        self.path_box = QtWidgets.QLineEdit(libpath)
        self.path_box.textEdited.connect(self._path_changed)
        form.addRow("", self.path_box)

        # Internal name of example
        typename = nodetype.name()
        _, ns, corename, ver = hou.hda.componentsFromFullNodeTypeName(typename)
        if self._name:
            internal = self._name
        else:
            internal = corename + "_example"
        if ns:
            internal = ns + "::" + internal
        if ver:
            internal = internal + "::" + ver
        self.internal_box = QtWidgets.QLineEdit(internal)
        form.addRow("Internal name", self.internal_box)

        # UI Label of example
        self.label_box = QtWidgets.QLineEdit(nodetype.description() +
                                             " Example")
        form.addRow("Description", self.label_box)

        # OK and Cancel buttons
        buttons = QtWidgets.QHBoxLayout()
        buttons.setAlignment(QtCore.Qt.AlignRight)
        form.addRow(buttons)

        self.ok_button = QtWidgets.QPushButton("OK")
        self.ok_button.clicked.connect(self.accept)
        buttons.addWidget(self.ok_button)

        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_button)

    def _where_changed(self):
        if not self._ignore:
            data = self.where_menu.currentData()
            self.path_box.setText(data)

    def _path_changed(self):
        text = self.path_box.text()
        index = self.where_menu.findData(text)
        if index > -1:
            self._ignore = True
            self.where_menu.setCurrentIndex(index)
            self._ignore = False

    def libraryPath(self):
        return self.path_box.text()

    def internalName(self):
        return self.internal_box.text()

    def exampleLabel(self):
        return self.label_box.text()

    # def accept(self):
    #     print("OK!!!")
    #     return super(NodeExampleDialog, self).accept()
    #     # return self.path_box.text(), self.label_box.text()
    #
    # def reject(self):
    #     print("Cancel!!!")
    #     return super(NodeExampleDialog, self).reject()

