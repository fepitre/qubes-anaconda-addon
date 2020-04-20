#
# Copyright (C) 2016  M. Vefa Bicakci <m.v.b@runbox.com>
# Copyright (C) 2016  Qubes OS Developers
# Copyright (C) 2013  Red Hat, Inc.
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# the GNU General Public License v.2, or (at your option) any later version.
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY expressed or implied, including the implied warranties of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General
# Public License for more details.  You should have received a copy of the
# GNU General Public License along with this program; if not, write to the
# Free Software Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA.  Any Red Hat trademarks that are incorporated in the
# source code or documentation are not subject to the GNU General Public
# License and may only be used or replicated with the express permission of
# Red Hat, Inc.
#
# Red Hat Author(s): Vratislav Podzimek <vpodzime@redhat.com>
#

"""Module with the QubesOsSpoke class."""

# import gettext
# _ = lambda x: gettext.ldgettext("qubes-os-anaconda-plugin", x)

# will never be translated
_ = lambda x: x
N_ = lambda x: x

import logging
import gi

gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('GLib', '2.0')

from gi.repository import Gtk
from pyanaconda.ui.categories.system import SystemCategory
from pyanaconda.ui.gui.spokes import NormalSpoke
from pyanaconda.ui.common import FirstbootOnlySpokeMixIn

# Useful for devel mode
try:
    from qubes.storage.lvm import list_thin_pools
except ImportError:
    def list_thin_pools():
        return [('qubes_dom0', 'pool01')]

# export only the spoke, no helper functions, classes or constants
__all__ = ["QubesOsSpoke"]

class QubesBaseChoice:
    instances = []

    def __init__(self, widget, depend=None, extra_check=None, indent=False):
        self.widget = widget
        self.depend = depend
        self.extra_check = extra_check

        self.selected = None
        self._can_be_sensitive = True

        if indent:
            self.outer_widget = Gtk.Alignment()
            self.outer_widget.add(self.widget)
            self.outer_widget.set_padding(0, 0, 20, 0)
        else:
            self.outer_widget = self.widget

    def append_instance(self):
        self.instances.append(self)

    def set_selected(self, value):
        self.widget.set_active(value)
        if self.selected is not None:
            self.selected = value

    def set_sensitive(self, sensitive):
        if self._can_be_sensitive:
            self.widget.set_sensitive(sensitive)

    def get_selected(self):
        return (self.selected
                if self.selected is not None
                else self.widget.get_sensitive() and self.widget.get_active())

    @classmethod
    def on_check_advanced_toggled(cls, widget):
        selected = widget.get_active()

        # this works, because you cannot instantiate the choices in wrong order
        # (cls.instances is a list and have deterministic ordering)
        for choice in cls.instances:
            choice.set_sensitive(not selected and (
                        choice.depend is None or choice.depend.get_selected()))


class QubesChoice(QubesBaseChoice):

    def __init__(self, label, depend=None, extra_check=None, indent=False):
        self.widget = Gtk.CheckButton(label=label)
        self.depend = depend
        super(QubesChoice, self).__init__(widget=self.widget,
                                          depend=depend,
                                          extra_check=extra_check,
                                          indent=indent)

        if self.depend is not None:
            self.depend.widget.connect('toggled', self.friend_on_toggled)
            self.depend.widget.connect('notify::sensitive',
                                       self.friend_on_toggled)
            self.friend_on_toggled(self.depend.widget)

        self.append_instance()

    def get_selected(self):
        return (self.selected
                if self.selected is not None
                else self.widget.get_sensitive() and self.widget.get_active())

    def store_selected(self):
        self.selected = self.get_selected()

    def friend_on_toggled(self, other_widget, *args):
        self.set_sensitive(other_widget.get_active())


class DisabledChoice(QubesChoice):
    def __init__(self, label, indent=False):
        super(DisabledChoice, self).__init__(label, indent)
        self.widget.set_sensitive(False)
        self._can_be_sensitive = False


class QubesChoicePool(QubesBaseChoice):
    def __init__(self, pools, depend=None, extra_check=None, indent=False):
        self.pools = {}
        self.depend = depend
        self.extra_check = extra_check

        # Merge pools info
        for key, val in pools:
            self.pools[key] = self.pools.get(key, ()) + (val,)

        main_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        vgroups_label = Gtk.Label("Logical Volume Group", xalign=0)
        tpools_label = Gtk.Label("Logical Thin Pool", xalign=0)

        vgroups_combo = Gtk.ComboBoxText()
        vgroups_combo.set_entry_text_column(0)
        vgroups_combo.connect("changed", self.on_vgroups_combo_changed)

        tpools_combo = Gtk.ComboBoxText()
        tpools_combo.set_entry_text_column(0)

        grid = Gtk.Grid()
        grid.set_column_spacing(20)
        grid.attach(vgroups_label, 0, 0, 1, 1)
        grid.attach(vgroups_combo, 1, 0, 1, 1)
        grid.attach(tpools_label, 0, 1, 1, 1)
        grid.attach(tpools_combo, 1, 1, 1, 1)

        main_vbox.pack_start(grid, False, False, 0)

        self.vgroups_combo = vgroups_combo
        self.tpools_combo = tpools_combo
        self.widget = main_vbox
        super(QubesChoicePool, self).__init__(widget=self.widget,
                                              depend=depend,
                                              extra_check=extra_check,
                                              indent=indent)

        if self.depend is not None:
            self.depend.widget.connect('toggled', self.friend_on_toggled)
            self.depend.widget.connect('notify::sensitive', self.friend_on_toggled)
            self.friend_on_toggled(self.depend.widget)

        self.vgroups = list(self.pools.keys())
        for vg in self.vgroups:
            self.vgroups_combo.append_text(vg)

        self.append_instance()

    def friend_on_toggled(self, other_widget, *args):
        self.set_sensitive(other_widget.get_active())

    def on_vgroups_combo_changed(self, *args):
        vgroup = self.get_vgroup()
        self.set_tpools_combo_entries(vgroup)

    def set_tpools_combo_entries(self, vgroup):
        self.tpools_combo.remove_all()
        for tpool in self.pools[vgroup]:
            self.tpools_combo.append_text(tpool)

        self.tpools_combo.set_active(0)

    def get_vgroup(self):
        return self.vgroups_combo.get_active_text()

    def get_tpool(self):
        return self.tpools_combo.get_active_text()

    def set_vgroup(self, vgroup):
        try:
            vgroup_index = self.vgroups.index(vgroup)
        except ValueError:
            # In case of custom install and default value not available
            vgroup_index = 0
        self.vgroups_combo.set_active(vgroup_index)

    def set_tpool(self, tpool):
        vgroup = self.get_vgroup()
        try:
            tpool_index = self.pools[vgroup].index(tpool)
        except ValueError:
            tpool_index = 0
        self.tpools_combo.set_active(tpool_index)


class QubesOsSpoke(FirstbootOnlySpokeMixIn, NormalSpoke):
    """
    Since this class inherits from the FirstbootOnlySpokeMixIn, it will
    only appear in the Initial Setup (successor of the Firstboot tool).

    :see: pyanaconda.ui.common.UIObject
    :see: pyanaconda.ui.common.Spoke
    :see: pyanaconda.ui.gui.GUIObject
    :see: pyanaconda.ui.common.FirstbootSpokeMixIn
    :see: pyanaconda.ui.gui.spokes.NormalSpoke

    """

    ### class attributes defined by API ###

    # list all top-level objects from the .glade file that should be exposed
    # to the spoke or leave empty to extract everything
    builderObjects = ["qubesOsSpokeWindow"]

    # the name of the main window widget
    mainWidgetName = "qubesOsSpokeWindow"

    # name of the .glade file in the same directory as this source
    uiFile = "qubes_os.glade"

    # category this spoke belongs to
    category = SystemCategory

    # spoke icon (will be displayed on the hub)
    # preferred are the -symbolic icons as these are used in Anaconda's spokes
    icon = "qubes-logo-icon"

    # title of the spoke (will be displayed on the hub)
    title = N_("_QUBES OS")

    ### methods defined by API ###
    def __init__(self, data, storage, payload):
        """
        :see: pyanaconda.ui.common.Spoke.__init__
        :param data: data object passed to every spoke to load/store data
                     from/to it
        :type data: pykickstart.base.BaseHandler
        :param storage: object storing storage-related information
                        (disks, partitioning, bootloader, etc.)
        :type storage: blivet.Blivet
        :param payload: object storing packaging-related information
        :type payload: pyanaconda.packaging.Payload

        """

        NormalSpoke.__init__(self, data, storage, payload)

        self.logger = logging.getLogger("anaconda")

        self.main_box = self.builder.get_object("mainBox")
        self.thread_dialog = None

        self.qubes_data = self.data.addons.org_qubes_os_initial_setup

        self.__init_qubes_choices()

    def __init_qubes_choices(self):

        self.choice_system = QubesChoice(_('Create default system qubes (sys-net, sys-firewall, default DispVM)'))

        self.choice_default = QubesChoice(_('Create default application qubes (personal, work, untrusted, vault)'), depend=self.choice_system)

        if self.qubes_data.whonix_available:
            self.choice_whonix = QubesChoice(_('Create Whonix Gateway and Workstation qubes (sys-whonix, anon-whonix)'), depend=self.choice_system)
        else:
            self.choice_whonix = DisabledChoice(_("Whonix not installed"))

        self.choice_whonix_updates = QubesChoice(_('Enable system and template updates over the Tor anonymity network using Whonix'), depend=self.choice_whonix, indent=True)

        if self.qubes_data.usbvm_available:
            self.choice_usb = QubesChoice(_('Use a qube to hold all USB controllers (create a new qube called sys-usb by default)'))
        else:
            self.choice_usb = DisabledChoice(_('USB qube configuration disabled - you are using USB keyboard or USB disk'))

        self.choice_usb_with_netvm = QubesChoice(_("Use sys-net qube for both networking and USB devices"), depend=self.choice_usb, indent=True)

        self.choice_custom_pool = QubesChoice(_("Enable custom storage pool (for advanced users)"))
        self.choice_pool_list = QubesChoicePool(pools=list_thin_pools(), depend=self.choice_custom_pool, indent=True)

        self.check_advanced = Gtk.CheckButton(label=_('Do not configure anything (for advanced users)'))
        self.check_advanced.connect('toggled', QubesChoice.on_check_advanced_toggled)

        for choice in QubesChoice.instances:
            self.main_box.pack_start(choice.outer_widget, False, True, 0)

        self.main_box.pack_end(self.check_advanced, False, True, 0)

        self.check_advanced.set_active(False)

        self.choice_system.widget.set_active(True)
        self.choice_default.widget.set_active(True)
        if self.choice_whonix.widget.get_sensitive():
            self.choice_whonix.widget.set_active(True)
        if self.choice_usb.widget.get_sensitive():
            self.choice_usb.widget.set_active(True)

        self.choice_custom_pool.widget.set_active(False)
        self.choice_pool_list.widget.set_sensitive(False)

    def initialize(self):
        """
        The initialize method that is called after the instance is created.
        The difference between __init__ and this method is that this may take
        a long time and thus could be called in a separated thread.

        :see: pyanaconda.ui.common.UIObject.initialize

        """

        NormalSpoke.initialize(self)
        self.qubes_data.gui_mode = True

    def refresh(self):
        """
        The refresh method that is called every time the spoke is displayed.
        It should update the UI elements according to the contents of
        self.data.

        :see: pyanaconda.ui.common.UIObject.refresh

        """

        self.choice_system.set_selected(self.qubes_data.system_vms)
        self.choice_default.set_selected(self.qubes_data.default_vms)
        self.choice_whonix.set_selected(self.qubes_data.whonix_vms)
        self.choice_whonix_updates.set_selected(self.qubes_data.whonix_default)
        self.choice_usb.set_selected(self.qubes_data.usbvm)
        self.choice_usb_with_netvm.set_selected(self.qubes_data.usbvm_with_netvm)
        self.choice_custom_pool.set_selected(self.qubes_data.custom_pool)

        vg, tpool = self.qubes_data.vg_tpool
        self.choice_pool_list.set_vgroup(vg)
        self.choice_pool_list.set_tpool(tpool)

    def apply(self):
        """
        The apply method that is called when the spoke is left. It should
        update the contents of self.data with values set in the GUI elements.

        """

        self.qubes_data.skip = self.check_advanced.get_active()

        self.qubes_data.system_vms = self.choice_system.get_selected()
        self.qubes_data.default_vms = self.choice_default.get_selected()
        self.qubes_data.whonix_vms = self.choice_whonix.get_selected()
        self.qubes_data.whonix_default = self.choice_whonix_updates.get_selected()
        self.qubes_data.usbvm = self.choice_usb.get_selected()
        self.qubes_data.usbvm_with_netvm = self.choice_usb_with_netvm.get_selected()
        self.qubes_data.custom_pool = self.choice_custom_pool.get_selected()
        self.qubes_data.vg_tpool = (self.choice_pool_list.get_vgroup(), self.choice_pool_list.get_tpool())

        self.qubes_data.seen = True

    @property
    def ready(self):
        """
        The ready property that tells whether the spoke is ready (can be visited)
        or not. The spoke is made (in)sensitive based on the returned value.

        :rtype: bool

        """

        return True

    @property
    def completed(self):
        """
        The completed property that tells whether all mandatory items on the
        spoke are set, or not. The spoke will be marked on the hub as completed
        or uncompleted acording to the returned value.

        :rtype: bool

        """

        return self.qubes_data.seen

    @property
    def mandatory(self):
        """
        The mandatory property that tells whether the spoke is mandatory to be
        completed to continue in the installation process.

        :rtype: bool

        """
        return True

    @property
    def status(self):
        """
        The status property that is a brief string describing the state of the
        spoke. It should describe whether all values are set and if possible
        also the values themselves. The returned value will appear on the hub
        below the spoke's title.

        :rtype: str

        """

        return ""

    def execute(self):
        """
        The execute method that is called when the spoke is left. It is
        supposed to do all changes to the runtime environment according to
        the values set in the GUI elements.

        """

        pass
