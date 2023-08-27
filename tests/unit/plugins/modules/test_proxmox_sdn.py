# -*- coding: utf-8 -*-
#
# Copyright (c) 2021, Ansible Project
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import absolute_import, division, print_function
from unittest.mock import call

__metaclass__ = type

import sys

import pytest

proxmoxer = pytest.importorskip("proxmoxer")
mandatory_py_version = pytest.mark.skipif(
    sys.version_info < (2, 7),
    reason="The proxmoxer dependency requires python2.7 or higher",
)

from ansible_collections.community.general.plugins.modules import proxmox_sdn
from ansible_collections.community.general.tests.unit.compat.mock import (
    patch,
    MagicMock,
    DEFAULT,
)
from ansible_collections.community.general.tests.unit.plugins.modules.utils import (
    AnsibleExitJson,
    AnsibleFailJson,
    ModuleTestCase,
    set_module_args,
)
import ansible_collections.community.general.plugins.module_utils.proxmox as proxmox_utils

_api_args = {
    "api_host": "host",
    "api_user": "user",
    "api_password": "password",
}


class TestProxmoxSdnModule(ModuleTestCase):
    def setUp(self):
        super(TestProxmoxSdnModule, self).setUp()
        proxmox_utils.HAS_PROXMOXER = True
        self.module = proxmox_sdn
        self.connect_mock = patch(
            "ansible_collections.community.general.plugins.module_utils.proxmox.ProxmoxAnsible._connect"
        ).start()
        self.get_node_mock = patch.object(proxmox_utils.ProxmoxAnsible, "get_node").start()
        self.is_sdn_existing_mock = patch.object(proxmox_sdn.ProxmoxSDNAnsible, "is_sdn_existing").start()
        self.is_vnet_existing_mock = patch.object(proxmox_sdn.ProxmoxSDNAnsible, "is_vnet_existing").start()

    def tearDown(self):
        self.connect_mock.stop()
        self.is_sdn_existing_mock.stop()
        self.is_vnet_existing_mock.stop()
        super(TestProxmoxSdnModule, self).tearDown()

    def test_module_fail_when_required_args_missing(self):
        with self.assertRaises(AnsibleFailJson):
            set_module_args({})
            self.module.main()

    def test_module_exits_unchanged_when_provided_zone_id_exists(self):
        set_module_args(
            {
                **_api_args,
                "zone": {
                    "id": "test",
                    "type": "simple",
                },
            }
        )
        self.is_sdn_existing_mock.return_value = True
        with pytest.raises(AnsibleExitJson) as exc_info:
            self.module.main()

        assert self.is_sdn_existing_mock.call_count == 1
        result = exc_info.value.args[0]
        assert result["changed"] is False
        assert result["msg"] == "sdn test already exists"
        assert result["id"] == "test"

    def test_module_exits_failed_when_provided_zone_id_invalid(self):
        set_module_args(
            {
                **_api_args,
                "zone": {"id": "1test", "type": "simple"},
            }
        )
        self.is_sdn_existing_mock.return_value = False
        with pytest.raises(AnsibleFailJson) as exc_info:
            self.module.main()

        assert self.is_sdn_existing_mock.call_count == 1
        result = exc_info.value.args[0]

        assert result["failed"] is True
        assert result["msg"] == "1test is not a valid sdn object identifier"

    @patch.object(proxmox_sdn.ProxmoxSDNAnsible, "apply_changes")
    def test_module_exits_changed_when_zone_created(self, apply_changes_mock: MagicMock):
        set_module_args(
            {
                **_api_args,
                "zone": {"id": "test", "type": "vlan", "bridge": "vmbr0", "additionals": {"mtu": "1450"}},
            }
        )

        self.is_sdn_existing_mock.return_value = False
        post_zones: MagicMock = self.connect_mock.return_value.cluster.sdn.zones.post

        with pytest.raises(AnsibleExitJson) as exc_info:
            self.module.main()

        result = exc_info.value.args[0]

        assert result["changed"] is True
        assert result["msg"] == "Zone test successfully created."
        assert self.is_sdn_existing_mock.call_count == 1
        post_zones.assert_called_once_with(zone="test", type="vlan", bridge="vmbr0", mtu="1450")
        assert apply_changes_mock.call_count == 0

    def test_module_exits_changed_when_zone_updated(self):
        self._test_module_exits_changed_when_zone_updated("changed", True, "Zone exists successfully changed.")
        self._test_module_exits_changed_when_zone_updated("", False, "Everything is up to date.")

    def _test_module_exits_changed_when_zone_updated(self, state, changed, msg):
        set_module_args(
            {
                **_api_args,
                "zone": {"id": "exists", "type": "vlan", "bridge": "vmbr0", "additionals": {"mtu": "1450"}},
                "update": True,
            }
        )

        self.is_sdn_existing_mock.return_value = True
        zones_mock: MagicMock = self.connect_mock.return_value.cluster.sdn.zones

        zones_mock.return_value.get.return_value = {"state": state}

        with pytest.raises(AnsibleExitJson) as exc_info:
            self.module.main()

        result = exc_info.value.args[0]

        assert result["changed"] is changed
        zones_mock.return_value.get.assert_called_once_with(pending="1")
        assert result["msg"] == msg
        assert self.is_sdn_existing_mock.call_count == 1
        assert zones_mock.call_count == 2  # one when calling the set-function, 2nd call when getting zone-info
        zones_mock.assert_called_with("exists")
        zones_mock.return_value.set.assert_called_once_with(bridge="vmbr0", mtu="1450")

        zones_mock.reset_mock()
        self.is_sdn_existing_mock.reset_mock()

    def test_module_exits_failed_when_zone_updated_does_not_exist(self):
        set_module_args(
            {
                **_api_args,
                "zone": {"id": "exists", "type": "vlan", "bridge": "vmbr0"},
                "update": True,
            }
        )

        self.is_sdn_existing_mock.return_value = False

        with pytest.raises(AnsibleFailJson) as exc_info:
            self.module.main()

        result = exc_info.value.args[0]

        assert result["failed"] is True
        assert result["msg"] == "Zone object exists does not exist"
        assert self.is_sdn_existing_mock.call_count == 1

    def test_module_exits_changed_when_zone_deleted(self):
        set_module_args(
            {
                **_api_args,
                "zone": {"id": "exists"},
                "state": "absent",
            }
        )

        self.is_sdn_existing_mock.return_value = True
        zones_mock: MagicMock = self.connect_mock.return_value.cluster.sdn.zones

        with pytest.raises(AnsibleExitJson) as exc_info:
            self.module.main()

        result = exc_info.value.args[0]

        assert result["changed"] is True
        assert result["msg"] == "Zone exists deleted"
        assert self.is_sdn_existing_mock.call_count == 1
        zones_mock.assert_called_with("exists")
        assert zones_mock.return_value.delete.call_count == 1

    def test_module_exits_failed_when_zone_deleted_exception_raised(self):
        set_module_args(
            {
                **_api_args,
                "zone": {"id": "exists"},
                "state": "absent",
            }
        )

        self.is_sdn_existing_mock.return_value = True
        zones_mock = self.connect_mock.return_value.cluster.sdn.zones

        def raise_():
            raise Exception("Hello World")

        zones_mock.return_value.delete.side_effect = raise_

        with pytest.raises(AnsibleFailJson) as exc_info:
            self.module.main()

        result = exc_info.value.args[0]

        assert result["failed"] is True
        assert result["msg"] == "Failed to delete sdn with ID exists: Hello World"

    def test_module_exits_unchanged_when_zone_deleted_does_not_exist(self):
        set_module_args(
            {
                **_api_args,
                "zone": {"id": "exists"},
                "state": "absent",
            }
        )

        self.is_sdn_existing_mock.return_value = False

        with pytest.raises(AnsibleExitJson) as exc_info:
            self.module.main()

        result = exc_info.value.args[0]

        assert result["changed"] is False
        assert result["msg"] == "sdn exists doesn't exist"
        assert self.is_sdn_existing_mock.call_count == 1

    def test_module_exits_failed_when_zone_deleted_not_empty(self):
        set_module_args(
            {
                **_api_args,
                "zone": {"id": "exists"},
                "state": "absent",
            }
        )

        self.is_sdn_existing_mock.return_value = True

        with patch.object(proxmox_sdn.ProxmoxSDNAnsible, "is_sdn_empty") as is_sdn_empty_mock:
            is_sdn_empty_mock.return_value = True  # import to be evaluated to True from python
            with pytest.raises(AnsibleFailJson) as exc_info:
                self.module.main()

        result = exc_info.value.args[0]

        assert result["failed"] is True
        assert (
            result["msg"]
            == "Can't delete sdn exists with vnets. Please remove vnets from sdn first or use `force: True`."
        )
        assert self.is_sdn_existing_mock.call_count == 1
        is_sdn_empty_mock.assert_called_once_with("exists")

    @patch.multiple(proxmox_sdn.ProxmoxSDNAnsible, is_sdn_empty=DEFAULT, delete_vnet=DEFAULT)
    def test_module_exits_changed_when_zone_deleted_not_empty_force(
        self, delete_vnet: MagicMock, is_sdn_empty: MagicMock
    ):
        set_module_args({**_api_args, "zone": {"id": "exists"}, "state": "absent", "force": True})

        self.is_sdn_existing_mock.return_value = True

        is_sdn_empty.return_value = [{"vnet": "id1"}, {"vnet": "id2"}]
        with pytest.raises(AnsibleExitJson) as exc_info:
            self.module.main()

        result = exc_info.value.args[0]

        assert result["changed"] is True
        # assert result["msg"] == "Can't delete sdn exists with vnets. Please remove vnets from sdn first or use `force: True`."
        assert self.is_sdn_existing_mock.call_count == 1
        is_sdn_empty.assert_called_once_with("exists")
        delete_vnet.assert_has_calls(
            [
                call("id1"),
                call(
                    "id2",
                ),
            ]
        )

    @patch.multiple(proxmox_sdn.ProxmoxSDNAnsible, create_zone=DEFAULT, apply_changes=DEFAULT)
    def test_module_exits_changed_when_apply_true(self, create_zone: MagicMock, apply_changes: MagicMock):
        set_module_args(
            {
                **_api_args,
                "zone": {
                    "id": "exists",
                    "type": "vlan",
                    "bridge": "vmbr0",
                    "additionals": {"mtu": "1450"},
                },
                "apply": True,
            }
        )
        create_zone.return_value = True

        with pytest.raises(AnsibleExitJson) as exc_info:
            self.module.main()

        result = exc_info.value.args[0]

        assert result["changed"] is True
        assert result["msg"] == "Zone exists successfully created.\nPending changes applied."
        assert apply_changes.call_count == 1

    def test_create_zone_return_false_sdn_exists(self):
        self.is_sdn_existing_mock.return_value = True
        sut = self.module.ProxmoxSDNAnsible(self.mock_module)
        result = sut.create_zone({"id": "test"}, False, True)
        assert result is False

    def test_module_exits_unchanged_when_vnet_exists_no_update(self):
        set_module_args(
            {
                **_api_args,
                "vnet": {"id": "test", "zone": "simple"},
            }
        )
        self.is_sdn_existing_mock.return_value = True
        self.is_vnet_existing_mock.return_value = True
        with pytest.raises(AnsibleExitJson) as exc_info:
            self.module.main()

        assert self.is_sdn_existing_mock.call_count == 1
        assert self.is_vnet_existing_mock.call_count == 1
        result = exc_info.value.args[0]
        assert result["changed"] is False
        assert result["msg"] == "Vnet test already exists"
        assert result["id"] == "test"

    @patch.object(proxmox_sdn.ProxmoxSDNAnsible, "apply_changes")
    def test_module_exits_unchanged_when_vnet_exists_no_update(self, apply_changes_mock: MagicMock):
        set_module_args(
            {
                **_api_args,
                "vnet": {"id": "test", "zone": "simple"},
                "apply": True,
            }
        )
        self.is_sdn_existing_mock.return_value = True
        self.is_vnet_existing_mock.return_value = True
        with pytest.raises(AnsibleExitJson) as exc_info:
            self.module.main()

        assert self.is_sdn_existing_mock.call_count == 1
        assert self.is_vnet_existing_mock.call_count == 1
        result = exc_info.value.args[0]
        assert result["changed"] is False
        assert result["msg"] == "Everything is up to date."
        apply_changes_mock.assert_not_called()

    def test_module_exits_changed_when_vnet_update(self):
        set_module_args(
            {
                **_api_args,
                "vnet": {"id": "test", "zone": "simple"},
                "update": True,
            }
        )
        self.is_sdn_existing_mock.return_value = True
        self.is_vnet_existing_mock.return_value = True
        vnet_mock: MagicMock = self.connect_mock.return_value.cluster.sdn.vnets
        with pytest.raises(AnsibleExitJson) as exc_info:
            self.module.main()

        assert self.is_sdn_existing_mock.call_count == 1
        assert self.is_vnet_existing_mock.call_count == 1
        result = exc_info.value.args[0]
        assert result["changed"] is True
        vnet_mock.assert_called_with("test")
        assert vnet_mock.call_count == 2
        vnet_mock.return_value.set.assert_called_once_with(
            zone="simple", alias=None, tag=None, type=None, vlanaware=None
        )
        assert result["msg"] == "Vnet test successfully updated."

    def test_module_exits_changed_when_vnet_created(self):
        set_module_args(
            {
                **_api_args,
                "vnet": {
                    "id": "test",
                    "zone": "simple",
                    "alias": "test123",
                    "tag": 42,
                    "vlanaware": True,
                },
            }
        )
        self.is_sdn_existing_mock.return_value = True
        self.is_vnet_existing_mock.return_value = False
        vnet_mock: MagicMock = self.connect_mock.return_value.cluster.sdn.vnets
        with pytest.raises(AnsibleExitJson) as exc_info:
            self.module.main()

        assert self.is_sdn_existing_mock.call_count == 1
        assert self.is_vnet_existing_mock.call_count == 1
        result = exc_info.value.args[0]
        assert result["changed"] is True
        vnet_mock.assert_called_with("test")
        assert vnet_mock.call_count == 1
        vnet_mock.post.assert_called_once_with(
            vnet="test", zone="simple", alias="test123", tag=42, type=None, vlanaware=1
        )
        assert result["msg"] == "Vnet test successfully created."


# a couple of functions are mocked in the above testcase-class so we have to use separate functions to test it
def _raise():
    raise Exception("Hello World")


class _DummyModule:
    def fail_json(self, **kwargs):
        kwargs["failed"] = True
        raise AnsibleFailJson(kwargs)


@patch.object(proxmox_utils.ProxmoxAnsible, "_connect")
@pytest.mark.parametrize("zoneid,expected", [("exists", True), ("does_not_exist", False)])
def test_is_sdn_existing_return_false(connect_mock, zoneid, expected):
    connect_mock.return_value.cluster.sdn.zones.get.return_value = [{"zone": zoneid}]

    sut = proxmox_sdn.ProxmoxSDNAnsible(None)
    result = sut.is_sdn_existing("exists")
    assert result is expected


@patch.object(proxmox_utils.ProxmoxAnsible, "_connect")
def test_is_sdn_existing_return_false(connect_mock):
    connect_mock.return_value.cluster.sdn.zones.get.side_effect = _raise

    sut = proxmox_sdn.ProxmoxSDNAnsible(_DummyModule())
    with pytest.raises(AnsibleFailJson) as exc_info:
        result = sut.is_sdn_existing("exists")

    result = exc_info.value.args[0]

    assert result["failed"] is True
    assert result["msg"] == "Unable to retrieve sdns: Hello World"


@patch.object(proxmox_utils.ProxmoxAnsible, "_connect")
@pytest.mark.parametrize("vnetid,expected", [("exists", True), ("does_not_exist", False)])
def test_is_vnet_existing_return_false(connect_mock, vnetid, expected):
    connect_mock.return_value.cluster.sdn.vnets.get.return_value = [{"vnet": vnetid}]

    sut = proxmox_sdn.ProxmoxSDNAnsible(None)
    result = sut.is_vnet_existing("exists")
    assert result is expected


@patch.object(proxmox_utils.ProxmoxAnsible, "_connect")
def test_is_vnet_existing_return_false(connect_mock):
    connect_mock.return_value.cluster.sdn.vnets.get.side_effect = _raise

    sut = proxmox_sdn.ProxmoxSDNAnsible(_DummyModule())
    with pytest.raises(AnsibleFailJson) as exc_info:
        result = sut.is_vnet_existing("exists")

    result = exc_info.value.args[0]

    assert result["failed"] is True
    assert result["msg"] == "Unable to retrieve vnets: Hello World"
