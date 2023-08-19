# -*- coding: utf-8 -*-
#
# Copyright (c) 2021, Ansible Project
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import absolute_import, division, print_function

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


class TestProxmoxSdnModule(ModuleTestCase):
    def setUp(self):
        super(TestProxmoxSdnModule, self).setUp()
        proxmox_utils.HAS_PROXMOXER = True
        self.module = proxmox_sdn
        self.connect_mock = patch(
            "ansible_collections.community.general.plugins.module_utils.proxmox.ProxmoxAnsible._connect"
        ).start()
        self.get_node_mock = patch.object(
            proxmox_utils.ProxmoxAnsible, "get_node"
        ).start()
        self.is_sdn_existing_mock = patch.object(
            proxmox_sdn.ProxmoxSDNAnsible, "is_sdn_existing"
        ).start()

    def tearDown(self):
        self.connect_mock.stop()
        super(TestProxmoxSdnModule, self).tearDown()

    def test_module_fail_when_required_args_missing(self):
        with self.assertRaises(AnsibleFailJson):
            set_module_args({})
            self.module.main()

    def test_module_exits_unchanged_when_provided_zone_id_exists(self):
        set_module_args(
            {
                "api_host": "host",
                "api_user": "user",
                "api_password": "password",
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
                "api_host": "host",
                "api_user": "user",
                "api_password": "password",
                "zone": {
                    "id": "1test",
                    "type": "simple",
                },
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
                "api_host": "host",
                "api_user": "user",
                "api_password": "password",
                "zone": {
                    "id": "test",
                    "type": "vlan",
                    "bridge": "vmbr0",
                    "additionals": {
                        "mtu": "1450"
                    }
                },
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
                "api_host": "host",
                "api_user": "user",
                "api_password": "password",
                "zone": {
                    "id": "exists",
                    "type": "vlan",
                    "bridge": "vmbr0",
                    "additionals": {
                        "mtu": "1450"
                    }
                },
                "update": True
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
        assert zones_mock.call_count == 2 # one when calling the set-function, 2nd call when getting zone-info
        zones_mock.assert_called_with("exists")
        zones_mock.return_value.set.assert_called_once_with(bridge="vmbr0", mtu="1450")
        
        zones_mock.reset_mock()
        self.is_sdn_existing_mock.reset_mock()

    def test_module_exits_failed_when_zone_updated_does_not_exist(self):
        set_module_args(
            {
                "api_host": "host",
                "api_user": "user",
                "api_password": "password",
                "zone": {
                    "id": "exists",
                    "type": "vlan",
                    "bridge": "vmbr0",
                },
                "update": True
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
                "api_host": "host",
                "api_user": "user",
                "api_password": "password",
                "zone": {
                    "id": "exists"               
                },
                "state": "absent"
            }
        )

        self.is_sdn_existing_mock.return_value = True
        zones_mock = self.connect_mock.return_value.cluster.sdn.zones
                
        with pytest.raises(AnsibleExitJson) as exc_info:
            self.module.main()

        result = exc_info.value.args[0]
        
        assert result["changed"] is True
        assert result["msg"] == "Zone exists successfully deleted"
        assert self.is_sdn_existing_mock.call_count == 1
        zones_mock.assert_called_once_with("exists")
        assert zones_mock.return_value.delete.call_count == 1

    def test_module_exits_unchanged_when_zone_deleted_does_not_exist(self):
        set_module_args(
            {
                "api_host": "host",
                "api_user": "user",
                "api_password": "password",
                "zone": {
                    "id": "exists"               
                },
                "state": "absent"
            }
        )

        self.is_sdn_existing_mock.return_value = False
        
        with pytest.raises(AnsibleExitJson) as exc_info:
            self.module.main()

        result = exc_info.value.args[0]
        
        assert result["changed"] is False
        assert result["msg"] == "sdn exists doesn't exist"
        assert self.is_sdn_existing_mock.call_count == 1

    def test_module_exits_failed_when_zone_deleted_vnet_belongs_to_zone(self):
        set_module_args(
            {
                "api_host": "host",
                "api_user": "user",
                "api_password": "password",
                "zone": {
                    "id": "exists"               
                },
                "state": "absent"
            }
        )

        self.is_sdn_existing_mock.return_value = True

        with patch.object(
            proxmox_sdn.ProxmoxSDNAnsible, "is_sdn_empty"
        ) as is_sdn_empty_mock:
            is_sdn_empty_mock.return_value = False
            with pytest.raises(AnsibleFailJson) as exc_info:
                self.module.main()

        result = exc_info.value.args[0]
        
        assert result["failed"] is True
        assert result["msg"] == "Can't delete sdn exists with vnets. Please remove vnets from sdn first."
        assert self.is_sdn_existing_mock.call_count == 1
        is_sdn_empty_mock.assert_called_once_with("exists")

    @patch.object(proxmox_sdn.ProxmoxSDNAnsible, "create_zone")
    @patch.object(proxmox_sdn.ProxmoxSDNAnsible, "apply_changes")
    def test_module_exits_changed_when_apply_true(self, create_zone_mock: MagicMock, apply_changes_mock: MagicMock):
        set_module_args(
            {
                "api_host": "host",
                "api_user": "user",
                "api_password": "password",
                "zone": {
                    "id": "exists",
                    "type": "vlan",
                    "bridge": "vmbr0",
                    "additionals": {
                        "mtu": "1450"
                    }
                },
                "apply": True
            }
        )
        create_zone_mock.return_value = True
        
        with pytest.raises(AnsibleExitJson) as exc_info:
            self.module.main()

        result = exc_info.value.args[0]
        
        assert result["changed"] is True
        assert result["msg"] == "Zone exists successfully created.\nPending changes applied."
        assert apply_changes_mock.call_count == 1

    def test_create_zone_return_false_sdn_exists(self):
        
        self.is_sdn_existing_mock.return_value = True
        sut = self.module.ProxmoxSDNAnsible(self.mock_module)
        result = sut.create_zone({"id": "test"}, False, True)        
        assert result is False

    # def test_is_sdn_existing_return_false(self):
        
    #     # self.is_sdn_existing_mock.return_value = True
    #     self.connect_mock.return_value.cluster.sdn.zones.get.return_value = [{"zone":"asdf"}]
    #     sut = self.module.ProxmoxSDNAnsible(self.mock_module)
    #     sut.is_sdn_existing.stop()
    #     result = sut.is_sdn_existing("test")        
    #     assert result is False
    #     sut.is_sdn_existing.start()
