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

    def test_module_exits_changed_when_zone_created(self):
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
        post_zones = MagicMock()
        self.connect_mock.return_value.cluster.sdn.zones.post = post_zones
        
        with pytest.raises(AnsibleExitJson) as exc_info:
            self.module.main()

        result = exc_info.value.args[0]
        
        assert result["changed"] is True
        assert result["msg"] == "Zone test successfully created."
        assert self.is_sdn_existing_mock.call_count == 1
        post_zones.assert_called_once_with(zone="test", type="vlan", bridge="vmbr0", mtu="1450")

    def test_module_exits_changed_when_zone_updated(self):
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
        set_zones_mock = MagicMock()
        zones_mock = MagicMock()
        zones_mock.return_value.set = set_zones_mock
        self.connect_mock.return_value.cluster.sdn.zones = zones_mock
        
        with pytest.raises(AnsibleExitJson) as exc_info:
            self.module.main()

        result = exc_info.value.args[0]
        
        assert result["changed"] is True
        assert result["msg"] == "Zone exists successfully updated."
        assert self.is_sdn_existing_mock.call_count == 1
        assert zones_mock.call_count == 2 # one when calling the set-function, 2nd call when getting zone-info
        zones_mock.assert_called_with("exists")
        set_zones_mock.assert_called_once_with(bridge="vmbr0", mtu="1450") 
