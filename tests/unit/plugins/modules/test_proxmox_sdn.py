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
        self.get_zone_mock = patch.object(proxmox_sdn.ProxmoxSDNAnsible, "get_zone").start()
        self.get_vnet_mock = patch.object(proxmox_sdn.ProxmoxSDNAnsible, "get_vnet").start()
        self.get_subnets_of_vnet_mock = patch.object(proxmox_sdn.ProxmoxSDNAnsible, "get_subnets_of_vnet").start()

    def tearDown(self):
        self.connect_mock.stop()
        self.get_zone_mock.stop()
        self.get_vnet_mock.stop()
        self.get_subnets_of_vnet_mock.stop()
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
        self.get_zone_mock.return_value = True
        with pytest.raises(AnsibleExitJson) as exc_info:
            self.module.main()

        assert self.get_zone_mock.call_count == 1
        result = exc_info.value.args[0]
        assert result["changed"] is False
        assert result["msg"] == "Zone test already exists."

    def test_module_exits_failed_when_validation_failed(self):
        testcases = [
            ({"subnet": {"cidr": "test", "vnet": "simple"}}, "test not a valid CIDR"),
            ({"vnet": {"id": "1a", "zone": "simple"}}, "1a is not a valid sdn object identifier"),
            ({"vnet": {"id": "a1", "zone": "vlan"}}, "missing vlan tag"),
            ({"zone": {"id": "1a"}}, "1a is not a valid sdn object identifier"),
        ]

        for module_args, msg in testcases:
            set_module_args({**_api_args, **module_args})

            with pytest.raises(AnsibleFailJson) as exc_info:
                self.module.main()

            # assert self.get_zone_mock.call_count == 1
            result = exc_info.value.args[0]
            assert result["failed"] is True
            assert result["msg"] == msg

    def test_module_exits_failed_when_provided_zone_id_invalid(self):
        set_module_args(
            {
                **_api_args,
                "zone": {"id": "1test", "type": "simple"},
            }
        )

        with pytest.raises(AnsibleFailJson) as exc_info:
            self.module.main()

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

        self.get_zone_mock.return_value = False
        post_zones: MagicMock = self.connect_mock.return_value.cluster.sdn.zones.post

        with pytest.raises(AnsibleExitJson) as exc_info:
            self.module.main()

        result = exc_info.value.args[0]

        assert result["changed"] is True
        assert result["msg"] == "Zone test successfully created."
        assert self.get_zone_mock.call_count == 1
        post_zones.assert_called_once_with(zone="test", type="vlan", bridge="vmbr0", mtu="1450")
        assert apply_changes_mock.call_count == 0

    # def test_module_exits_changed_when_zone_updated(self):
    #     self._test_module_exits_changed_when_zone_updated("changed", True, "Zone exists successfully updated.")
    #     self._test_module_exits_changed_when_zone_updated("", False, "Everything is up to date.")

    def test_module_exits_changed_when_zone_updated(self):
        set_module_args(
            {
                **_api_args,
                "zone": {"id": "exists", "type": "vlan", "bridge": "vmbr0", "additionals": {"mtu": "1450"}},
                "update": True,
            }
        )

        self.get_zone_mock.return_value = True
        zones_mock: MagicMock = self.connect_mock.return_value.cluster.sdn.zones

        zones_mock.return_value.get.return_value = [{"zone": "exists"}]

        with pytest.raises(AnsibleExitJson) as exc_info:
            self.module.main()

        result = exc_info.value.args[0]

        assert result["changed"] is True
        # assert zones_mock.return_value.get.call_count ==1 #.assert_called_once_with(pending="1")
        assert result["msg"] == "Zone exists successfully updated."
        assert self.get_zone_mock.call_count == 1
        assert zones_mock.call_count == 1
        zones_mock.assert_called_with("exists")
        zones_mock.return_value.set.assert_called_once_with(bridge="vmbr0", mtu="1450")

        zones_mock.reset_mock()
        self.get_zone_mock.reset_mock()

    def test_module_exits_failed_when_zone_updated_does_not_exist(self):
        set_module_args(
            {
                **_api_args,
                "zone": {"id": "exists", "type": "vlan", "bridge": "vmbr0"},
                "update": True,
            }
        )

        self.get_zone_mock.return_value = False

        with pytest.raises(AnsibleFailJson) as exc_info:
            self.module.main()

        result = exc_info.value.args[0]

        assert result["failed"] is True
        assert result["msg"] == "Zone object exists does not exist"
        assert self.get_zone_mock.call_count == 1

    def test_module_exits_changed_when_zone_deleted(self):
        set_module_args(
            {
                **_api_args,
                "zone": {"id": "exists"},
                "state": "absent",
            }
        )

        self.get_zone_mock.return_value = {"key": "value"}
        zones_mock: MagicMock = self.connect_mock.return_value.cluster.sdn.zones

        with pytest.raises(AnsibleExitJson) as exc_info:
            self.module.main()

        result = exc_info.value.args[0]

        assert result["changed"] is True
        assert result["msg"] == "Zone exists deleted."
        assert self.get_zone_mock.call_count == 1
        assert zones_mock.call_args_list == [call("exists")]
        assert zones_mock.return_value.delete.call_count == 1

    def test_module_exits_failed_when_zone_deleted_exception_raised(self):
        set_module_args(
            {
                **_api_args,
                "zone": {"id": "exists"},
                "state": "absent",
            }
        )

        self.get_zone_mock.return_value = {"random-key": "random-value"}
        zones_mock = self.connect_mock.return_value.cluster.sdn.zones

        def raise_():
            raise Exception("My Exception")

        zones_mock.return_value.delete.side_effect = raise_

        with pytest.raises(AnsibleFailJson) as exc_info:
            self.module.main()

        result = exc_info.value.args[0]

        assert result["failed"] is True
        assert result["msg"] == "Failed to delete zone with ID exists: My Exception"

    def test_module_exits_unchanged_when_zone_deleted_does_not_exist(self):
        set_module_args(
            {
                **_api_args,
                "zone": {"id": "exists"},
                "state": "absent",
            }
        )

        self.get_zone_mock.return_value = None

        with pytest.raises(AnsibleExitJson) as exc_info:
            self.module.main()

        result = exc_info.value.args[0]

        assert result["changed"] is False
        assert result["msg"] == "Zone 'exists' is already absent"
        assert self.get_zone_mock.call_count == 1

    def test_module_exits_failed_when_zone_deleted_not_empty(self):
        set_module_args(
            {
                **_api_args,
                "zone": {"id": "exists"},
                "state": "absent",
            }
        )

        self.get_zone_mock.return_value = {"key": "value"}

        with patch.object(proxmox_sdn.ProxmoxSDNAnsible, "get_vnets_of_zone") as get_vnets_of_zone_mock:
            get_vnets_of_zone_mock.return_value = [{"key": "value"}]
            with pytest.raises(AnsibleFailJson) as exc_info:
                self.module.main()

        result = exc_info.value.args[0]

        assert result["failed"] is True
        assert (
            result["msg"]
            == "Can't delete zone exists with vnets. Please remove vnets from zone first or use `force: True`."
        )
        assert self.get_zone_mock.call_count == 1
        get_vnets_of_zone_mock.assert_called_once_with("exists")

    @patch.multiple(proxmox_sdn.ProxmoxSDNAnsible, get_vnets_of_zone=DEFAULT, delete_vnet=DEFAULT)
    def test_module_exits_changed_when_zone_deleted_not_empty_force(
        self, delete_vnet: MagicMock, get_vnets_of_zone: MagicMock
    ):
        set_module_args({**_api_args, "zone": {"id": "exists"}, "state": "absent", "force": True})

        self.get_zone_mock.return_value = {"key": "value"}

        get_vnets_of_zone.return_value = [{"vnet": "id1"}, {"vnet": "id2"}]
        with pytest.raises(AnsibleExitJson) as exc_info:
            self.module.main()

        result = exc_info.value.args[0]

        assert result["changed"] is True
        # assert result["msg"] == "Can't delete sdn exists with vnets. Please remove vnets from sdn first or use `force: True`."
        assert self.get_zone_mock.call_count == 1
        get_vnets_of_zone.assert_called_once_with("exists")
        delete_vnet.assert_has_calls([call(True, "id1"), call(True, "id2")])

    @patch.object(proxmox_sdn.ProxmoxSDNAnsible, "apply_changes")
    def test_module_exits_changed_when_apply_changes(self, apply_changes: MagicMock):
        set_module_args(
            {
                **_api_args,
                "apply": True,
            }
        )
        get_zone: MagicMock = self.connect_mock.return_value.cluster.sdn.zones.get
        get_vnets: MagicMock = self.connect_mock.return_value.cluster.sdn.vnets.get
        get_vnets.return_value = [{"vnet": "myvnet"}]
        self.get_subnets_of_vnet_mock.return_value = [{"state": "deleted"}]
        with pytest.raises(AnsibleExitJson) as exc_info:
            self.module.main()

        result = exc_info.value.args[0]

        assert result["changed"] is True
        assert result["msg"] == "Pending changes applied."
        get_zone.assert_called_once()
        self.get_subnets_of_vnet_mock.assert_called_once_with("myvnet")
        self.get_subnets_of_vnet_mock.assert_called_once()
        assert apply_changes.call_count == 1

    def test_create_zone_return_false_sdn_exists(self):
        self.get_zone_mock.return_value = True
        sut = self.module.ProxmoxSDNAnsible(self.mock_module)
        result = sut.create_zone({"id": "test"}, False, True)
        assert result is False

    def test_module_exits_failed_when_create_vnet_zone_not_exists(self):
        set_module_args(
            {
                **_api_args,
                "vnet": {"id": "test", "zone": "simple"},
            }
        )

        self.get_zone_mock.return_value = None
        with pytest.raises(AnsibleFailJson) as exc_info:
            self.module.main()

        self.get_zone_mock.assert_called_once_with("simple")
        # assert self.get_vnet_mock.call_count == 1
        result = exc_info.value.args[0]
        assert result["failed"] is True
        assert result["msg"] == "Zone simple doesn't exist"

    def test_module_exits_unchanged_when_vnet_exists_no_update(self):
        set_module_args(
            {
                **_api_args,
                "vnet": {"id": "test", "zone": "simple"},
            }
        )
        self.get_zone_mock.return_value = True
        self.get_vnet_mock.return_value = True
        with pytest.raises(AnsibleExitJson) as exc_info:
            self.module.main()

        assert self.get_zone_mock.call_count == 1
        assert self.get_vnet_mock.call_count == 1
        result = exc_info.value.args[0]
        assert result["changed"] is False
        assert result["msg"] == "Vnet test already exists."
        # assert result["id"] == "test"

    @patch.object(proxmox_sdn.ProxmoxSDNAnsible, "apply_changes")
    def test_module_exits_unchanged_when_vnet_exists_no_update_apply(self, apply_changes_mock: MagicMock):
        set_module_args(
            {
                **_api_args,
                "vnet": {"id": "test", "zone": "simple"},
                "apply": True,
            }
        )
        self.get_zone_mock.return_value = True
        self.get_vnet_mock.return_value = True
        with pytest.raises(AnsibleExitJson) as exc_info:
            self.module.main()

        assert self.get_zone_mock.call_count == 1
        assert self.get_vnet_mock.call_count == 1
        result = exc_info.value.args[0]
        assert result["changed"] is False
        assert result["msg"] == "Vnet test already exists. No pending changes detected."
        apply_changes_mock.assert_not_called()

    def test_module_exits_changed_when_vnet_update(self):
        set_module_args(
            {
                **_api_args,
                "vnet": {"id": "test", "zone": "simple"},
                "update": True,
            }
        )
        self.get_zone_mock.return_value = True
        self.get_vnet_mock.return_value = True
        vnet_mock: MagicMock = self.connect_mock.return_value.cluster.sdn.vnets
        with pytest.raises(AnsibleExitJson) as exc_info:
            self.module.main()

        assert self.get_zone_mock.call_count == 1
        assert self.get_vnet_mock.call_count == 1
        result = exc_info.value.args[0]
        assert result["changed"] is True
        vnet_mock.assert_called_once_with("test")
        # assert vnet_mock.call_count == 2
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
        self.get_zone_mock.return_value = True
        self.get_vnet_mock.return_value = False
        vnet_mock: MagicMock = self.connect_mock.return_value.cluster.sdn.vnets
        with pytest.raises(AnsibleExitJson) as exc_info:
            self.module.main()

        assert self.get_zone_mock.call_count == 1
        assert self.get_vnet_mock.call_count == 1
        result = exc_info.value.args[0]
        assert result["changed"] is True
        # vnet_mock.assert_called_with("test")
        # assert vnet_mock.call_count == 1
        vnet_mock.post.assert_called_once_with(
            vnet="test", zone="simple", alias="test123", tag=42, type=None, vlanaware=1
        )
        assert result["msg"] == "Vnet test successfully created."

    @patch.object(proxmox_sdn.ProxmoxSDNAnsible, "delete_subnet")
    def test_module_exits_changed_when_vnet_deleted_exists(self, delete_subnet_mock: MagicMock):
        set_module_args(
            {
                **_api_args,
                "vnet": {"zone": "not used", "id": "exists"},  # TODO make zone optional and check when state==present
                "state": "absent",
                "force": "True",
            }
        )
        self.get_vnet_mock.return_value = {}
        self.get_subnets_of_vnet_mock.return_value = [{"cidr": "sv1"}, {"cidr": "sv2"}, {"cidr": "sv3"}]
        # self.get_zone_mock.return_value = {"key": "value"}
        # zones_mock: MagicMock = self.connect_mock.return_value.cluster.sdn.zones

        with pytest.raises(AnsibleExitJson) as exc_info:
            self.module.main()

        result = exc_info.value.args[0]

        assert result["changed"] is True
        assert result["msg"] == "Vnet exists deleted."
        self.get_vnet_mock.assert_called_once_with("exists", pending="1")
        self.connect_mock.return_value.cluster.sdn.vnets.return_value.delete.assert_called_once()
        delete_subnet_mock.assert_has_calls([call("sv1", "exists"), call("sv2", "exists"), call("sv3", "exists")])
        # assert self.get_zone_mock.call_count == 1
        # assert zones_mock.call_args_list == [call("exists")]
        # assert zones_mock.return_value.delete.call_count == 1

    def test_module_exits_not_changed_when_vnet_deleted_does_not_exist(self):
        self._test_module_exits_not_changed_when_vnet_deleted_does_not_exist(None)
        self._test_module_exits_not_changed_when_vnet_deleted_does_not_exist({"state": "deleted"})

    def _test_module_exits_not_changed_when_vnet_deleted_does_not_exist(self, mock_ret):
        set_module_args(
            {
                **_api_args,
                "vnet": {"zone": "not used", "id": "exists"},  # TODO make zone optional and check when state==present
                "state": "absent",
            }
        )
        self.get_vnet_mock.return_value = mock_ret
        # self.get_subnets_of_vnet_mock.return_value = []
        # self.get_zone_mock.return_value = {"key": "value"}
        # zones_mock: MagicMock = self.connect_mock.return_value.cluster.sdn.zones

        with pytest.raises(AnsibleExitJson) as exc_info:
            self.module.main()

        result = exc_info.value.args[0]

        assert result["changed"] is False
        assert result["msg"] == "Vnet 'exists' is already absent"
        self.get_vnet_mock.assert_called_once_with("exists", pending="1")
        self.get_vnet_mock.reset_mock()

    def test_module_exits_changed_when_subnet_does_not_exist(self):
        set_module_args(
            {
                **_api_args,
                "subnet": {"cidr": "192.168.1.1/24", "vnet": "myvnet", "snat": True},
            }
        )

        self.get_vnet_mock.return_value = {"key", "value"}
        with pytest.raises(AnsibleExitJson) as exc_info:
            self.module.main()

        assert self.get_vnet_mock.call_count == 1
        result = exc_info.value.args[0]
        assert result["changed"] is True
        assert result["msg"] == "Subnet 192.168.1.1/24 successfully created."
        self.get_vnet_mock.assert_called_once_with("myvnet")
        self.connect_mock.return_value.cluster.sdn.vnets.return_value.subnets.post.assert_called_once_with(
            subnet="192.168.1.1/24", type="subnet", vnet="myvnet", dnszoneprefix=None, gateway=None, snat=1
        )
        # assert result["id"] == "test"

    @patch.object(proxmox_sdn.ProxmoxSDNAnsible, "get_subnet")
    def test_module_exits_not_changed_when_subnet_exists(self, get_subnet_mock: MagicMock):
        set_module_args(
            {
                **_api_args,
                "subnet": {"cidr": "192.168.1.1/24", "vnet": "myvnet", "snat": True},
            }
        )

        self.get_vnet_mock.return_value = {"key", "value"}
        get_subnet_mock.return_value = {"key": "value"}

        with pytest.raises(AnsibleExitJson) as exc_info:
            self.module.main()

        assert self.get_vnet_mock.call_count == 1
        get_subnet_mock.assert_called_once_with("192.168.1.1/24", "myvnet")
        result = exc_info.value.args[0]
        assert result["changed"] is False
        assert result["msg"] == "Subnet 192.168.1.1/24 of myvnet already exists."
        self.get_vnet_mock.assert_called_once_with("myvnet")

    @patch.object(proxmox_sdn.ProxmoxSDNAnsible, "get_subnet")
    def test_module_exits_changed_when_subnet_exists_update(self, get_subnet_mock: MagicMock):
        set_module_args(
            {**_api_args, "subnet": {"cidr": "192.168.1.1/24", "vnet": "myvnet", "snat": True}, "update": True}
        )

        self.get_vnet_mock.return_value = {"key", "value"}
        get_subnet_mock.return_value = {"subnet": "subnet-name"}

        with pytest.raises(AnsibleExitJson) as exc_info:
            self.module.main()

        assert self.get_vnet_mock.call_count == 1
        get_subnet_mock.assert_called_once_with("192.168.1.1/24", "myvnet")
        result = exc_info.value.args[0]
        assert result["changed"] is True
        assert result["msg"] == "Subnet 192.168.1.1/24 successfully updated."
        self.get_vnet_mock.assert_called_once_with("myvnet")
        self.connect_mock.return_value.cluster.sdn.vnets.return_value.subnets.return_value.set.assert_called_once_with(
            vnet="myvnet", dnszoneprefix=None, gateway=None, snat=1
        )

    @patch.object(proxmox_sdn.ProxmoxSDNAnsible, "get_subnet")
    @patch.object(proxmox_sdn.ProxmoxSDNAnsible, "apply_changes")
    def test_module_exits_changed_when_subnet_deleted_exists(
        self, apply_changes_mock: MagicMock, get_subnet_mock: MagicMock
    ):
        set_module_args(
            {**_api_args, "subnet": {"cidr": "192.168.1.1/24", "vnet": "myvnet"}, "state": "absent", "apply": False}
        )
        get_subnet_mock.return_value = {"subnet": "subnet-name"}
        # self.get_vnet_mock.return_value = { }
        # self.get_subnets_of_vnet_mock.return_value = [{"cidr": "sv1"}, {"cidr": "sv2"}, {"cidr": "sv3"}]
        # self.get_zone_mock.return_value = {"key": "value"}
        # zones_mock: MagicMock = self.connect_mock.return_value.cluster.sdn.zones

        # self.connect_mock.return_value.cluster.sdn.zones.get.return_value = []
        # self.connect_mock.return_value.cluster.sdn.vnets.get.return_value = [{"vnet": "myvnet"}]
        # self.get_subnets_of_vnet_mock.return_value = [{"state": "deleted"}]
        with pytest.raises(AnsibleExitJson) as exc_info:
            self.module.main()

        result = exc_info.value.args[0]

        assert result["changed"] is True
        assert result["msg"] == "Subnet 192.168.1.1/24 of myvnet deleted."
        get_subnet_mock.assert_called_once_with("192.168.1.1/24", "myvnet")
        self.connect_mock.return_value.cluster.sdn.vnets.return_value.subnets.return_value.delete.assert_called_once()

        apply_changes_mock.assert_not_called()
        # delete_subnet_mock.assert_has_calls([call("sv1", "exists"), call("sv2", "exists"), call("sv3", "exists")])

    @patch.object(proxmox_sdn.ProxmoxSDNAnsible, "get_subnet")
    def test_module_exits_not_changed_when_subnet_deleted_does_not_exists(self, get_subnet_mock: MagicMock):
        self._test_module_exits_not_changed_when_subnet_deleted_does_not_exists(None, get_subnet_mock)
        self._test_module_exits_not_changed_when_subnet_deleted_does_not_exists({"state": "deleted"}, get_subnet_mock)

    def _test_module_exits_not_changed_when_subnet_deleted_does_not_exists(self, mock_ret, get_subnet_mock: MagicMock):
        set_module_args({**_api_args, "subnet": {"cidr": "192.168.1.1/24", "vnet": "myvnet"}, "state": "absent"})
        get_subnet_mock.return_value = mock_ret
        # self.get_vnet_mock.return_value = { }
        # self.get_subnets_of_vnet_mock.return_value = [{"cidr": "sv1"}, {"cidr": "sv2"}, {"cidr": "sv3"}]
        # self.get_zone_mock.return_value = {"key": "value"}
        # zones_mock: MagicMock = self.connect_mock.return_value.cluster.sdn.zones

        with pytest.raises(AnsibleExitJson) as exc_info:
            self.module.main()

        result = exc_info.value.args[0]

        assert result["changed"] is False
        assert result["msg"] == "Subnet '192.168.1.1/24' of vnet myvnet is already absent"
        get_subnet_mock.assert_called_once_with("192.168.1.1/24", "myvnet")
        get_subnet_mock.reset_mock()
        # self.connect_mock.return_value.cluster.sdn.vnets.return_value.subnets.return_value.delete.assert_called_once()

    @patch.object(proxmox_sdn.ProxmoxSDNAnsible, "get_subnet")
    @patch.object(proxmox_sdn.ProxmoxSDNAnsible, "apply_changes")
    def test_module_exits_changed_when_subnet_deleted_exists(
        self, apply_changes_mock: MagicMock, get_subnet_mock: MagicMock
    ):
        set_module_args(
            {**_api_args, "subnet": {"cidr": "192.168.1.1/24", "vnet": "myvnet"}, "state": "absent", "apply": False}
        )
        get_subnet_mock.return_value = {"subnet": "subnet-name"}
        # self.get_vnet_mock.return_value = { }
        # self.get_subnets_of_vnet_mock.return_value = [{"cidr": "sv1"}, {"cidr": "sv2"}, {"cidr": "sv3"}]
        # self.get_zone_mock.return_value = {"key": "value"}
        # zones_mock: MagicMock = self.connect_mock.return_value.cluster.sdn.zones

        # self.connect_mock.return_value.cluster.sdn.zones.get.return_value = []
        # self.connect_mock.return_value.cluster.sdn.vnets.get.return_value = [{"vnet": "myvnet"}]
        # self.get_subnets_of_vnet_mock.return_value = [{"state": "deleted"}]
        with pytest.raises(AnsibleExitJson) as exc_info:
            self.module.main()

        result = exc_info.value.args[0]

        assert result["changed"] is True
        assert result["msg"] == "Subnet 192.168.1.1/24 of myvnet deleted."
        get_subnet_mock.assert_called_once_with("192.168.1.1/24", "myvnet")
        self.connect_mock.return_value.cluster.sdn.vnets.return_value.subnets.return_value.delete.assert_called_once()

        apply_changes_mock.assert_not_called()
        # delete_subnet_mock.assert_has_calls([call("sv1", "exists"), call("sv2", "exists"), call("sv3", "exists")])


# a couple of functions are mocked in the above testcase-class so we have to use separate functions to test it
def _raise(*args, **kwargs):
    raise Exception("My Exception")


class _DummyModule:
    def fail_json(self, **kwargs):
        kwargs["failed"] = True
        raise AnsibleFailJson(kwargs)


@patch.object(proxmox_utils.ProxmoxAnsible, "_connect")
@pytest.mark.parametrize("zoneid,expected", [("exists", {"zone": "exists"}), ("does_not_exist", None)])
def test_get_zone(connect_mock, zoneid, expected):
    connect_mock.return_value.cluster.sdn.zones.get.return_value = [{"zone": zoneid}]

    sut = proxmox_sdn.ProxmoxSDNAnsible(None)
    result = sut.get_zone("exists")
    assert result == expected


@patch.object(proxmox_utils.ProxmoxAnsible, "_connect")
def test_get_zone_raise_exception(connect_mock):
    connect_mock.return_value.cluster.sdn.zones.get.side_effect = _raise

    sut = proxmox_sdn.ProxmoxSDNAnsible(_DummyModule())
    with pytest.raises(AnsibleFailJson) as exc_info:
        result = sut.get_zone("exists")

    result = exc_info.value.args[0]

    assert result["failed"] is True
    assert result["msg"] == "Unable to retrieve zone: My Exception"


@patch.object(proxmox_utils.ProxmoxAnsible, "_connect")
@pytest.mark.parametrize("vnetid,expected", [("exists", True), ("does_not_exist", False)])
def test_get_vnet_return_false(connect_mock, vnetid, expected):
    connect_mock.return_value.cluster.sdn.vnets.get.return_value = [{"vnet": vnetid}]

    sut = proxmox_sdn.ProxmoxSDNAnsible(None)
    result = sut.get_vnet("exists")
    assert result is expected


@patch.object(proxmox_utils.ProxmoxAnsible, "_connect")
def test_get_vnet_return_false(connect_mock):
    connect_mock.return_value.cluster.sdn.vnets.get.side_effect = _raise

    sut = proxmox_sdn.ProxmoxSDNAnsible(_DummyModule())
    with pytest.raises(AnsibleFailJson) as exc_info:
        result = sut.get_vnet("exists")

    result = exc_info.value.args[0]

    assert result["failed"] is True
    assert result["msg"] == "Unable to retrieve vnet: My Exception"


@patch.object(proxmox_utils.ProxmoxAnsible, "_connect")
def test_get_vnets_of_zone_raise_exception(connect_mock):
    connect_mock.return_value.cluster.sdn.vnets.get.side_effect = _raise

    sut = proxmox_sdn.ProxmoxSDNAnsible(_DummyModule())
    with pytest.raises(AnsibleFailJson) as exc_info:
        result = sut.get_vnets_of_zone("exists")

    result = exc_info.value.args[0]

    assert result["failed"] is True
    assert result["msg"] == "Unable to retrieve vnets: My Exception"


@patch.object(proxmox_utils.ProxmoxAnsible, "_connect")
@pytest.mark.parametrize("cidr,expected", [("exists", {"cidr": "exists"}), ("does_not_exist", None)])
def test_get_subnet(connect_mock, cidr, expected):
    vnets_mock: MagicMock = connect_mock.return_value.cluster.sdn.vnets
    vnets_mock.return_value.subnets.get.return_value = [{"cidr": "exists1"}, {"cidr": "exists"}]

    sut = proxmox_sdn.ProxmoxSDNAnsible(None)
    result = sut.get_subnet(cidr, "vnet")
    assert result == expected
    vnets_mock.assert_called_once_with("vnet")


@patch.object(proxmox_utils.ProxmoxAnsible, "_connect")
def test_get_subnet_raise_exception(connect_mock):
    connect_mock.return_value.cluster.sdn.vnets.return_value.subnets.get.side_effect = _raise

    sut = proxmox_sdn.ProxmoxSDNAnsible(_DummyModule())
    with pytest.raises(AnsibleFailJson) as exc_info:
        result = sut.get_subnet("exists", "asdf")

    result = exc_info.value.args[0]

    assert result["failed"] is True
    assert result["msg"] == "Unable to retrieve subnet: My Exception"


@patch.object(proxmox_utils.ProxmoxAnsible, "_connect")
@patch.object(proxmox_utils.ProxmoxAnsible, "api_task_ok")
def test_apply_changes(api_task_mock: MagicMock, connect_mock: MagicMock):
    connect_mock.return_value.cluster.sdn.set.return_value = 42
    connect_mock.return_value.cluster.resources.get.return_value = [{"node": 1}, {"node": 2}, {"node": 3}]

    class _Module(_DummyModule):
        params = {"timeout": 5}

    api_task_mock.return_value = True
    sut = proxmox_sdn.ProxmoxSDNAnsible(_Module())
    ret = sut.apply_changes()
    assert ret is None
    assert api_task_mock.call_count == 3


import time


@patch.object(proxmox_utils.ProxmoxAnsible, "_connect")
@patch.object(proxmox_utils.ProxmoxAnsible, "api_task_ok")
@patch.object(time, "sleep")
def test_apply_changes_fail(sleep_mock: MagicMock, api_task_mock: MagicMock, connect_mock: MagicMock):
    connect_mock.return_value.cluster.sdn.set.return_value = 42
    connect_mock.return_value.cluster.resources.get.return_value = [{"node": 1}, {"node": 2}, {"node": 3}]

    class _Module(_DummyModule):
        params = {"timeout": 5}

    api_task_mock.return_value = False
    sut = proxmox_sdn.ProxmoxSDNAnsible(_Module())
    with pytest.raises(AnsibleFailJson) as exc_info:
        sut.apply_changes()

    result = exc_info.value.args[0]
    sleep_mock.assert_called()

    assert result["failed"] is True
