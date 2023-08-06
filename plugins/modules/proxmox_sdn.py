#!/usr/bin/python
# -*- coding: utf-8 -*-
#
from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.community.general.plugins.module_utils.proxmox import (proxmox_auth_argument_spec, ProxmoxAnsible)


import urllib3
urllib3.disable_warnings()

class ProxmoxSDNAnsible(ProxmoxAnsible):

    def is_sdn_existing(self, sdnid):
        """Check whether sdn already exist

        :param sdnid: str - name of the sdn
        :return: bool - is sdn exists?
        """
        try:
            sdns = self.proxmox_api.cluster.sdn.zones.get()
            return any(sdn['zone'] == sdnid for sdn in sdns)
        except Exception as e:
            self.module.fail_json(msg="Unable to retrieve sdns: {0}".format(e))

    def is_sdn_empty(self, sdnid):
        """Check whether sdn has vnets

        :param sdnid: str - name of the sdn
        :return: bool - is sdn empty?
        """
        return not any( vnet["zone"] == sdnid for vnet in self.proxmox_api.cluster.sdn.vnets.get())

    def create_zone(self, zone, update):
        """Create Proxmox VE sdn

        :param sdnid: str - name of the sdn
        :return: None
        """
        if self.is_sdn_existing(zone["id"]):
            if not update:
                self.module.exit_json(changed=False, id=zone["id"], msg="sdn {0} already exists".format(zone["id"]))
        if self.module.check_mode:
            return

        zone_copy = dict(**zone)
        zone_id = zone_copy.pop("id")
        additionals = zone_copy.pop("additionals", {})
        if update:
            zone_copy.pop("type")
            self.proxmox_api.cluster.sdn.zones(zone_id).set(**zone_copy, **additionals)
        else:
            self.proxmox_api.cluster.sdn.zones(zone_id).post(**zone_copy, **additionals)

    def delete_zone(self, sdnid):
        """Delete Proxmox VE sdn

        :param sdnid: str - name of the sdn
        :return: None
        """
        if not self.is_sdn_existing(sdnid):
            self.module.exit_json(changed=False, id=sdnid, msg="sdn {0} doesn't exist".format(sdnid))

        if self.is_sdn_empty(sdnid):
            if self.module.check_mode:
                return

            try:
                self.proxmox_api.cluster.sdn.zones(sdnid).delete()
            except Exception as e:
                self.module.fail_json(msg="Failed to delete sdn with ID {0}: {1}".format(sdnid, e))
        else:
            self.module.fail_json(msg="Can't delete sdn {0} with members. Please remove members from sdn first.".format(sdnid))

    def apply_changes(self):
        taskid = self.proxmox_api.cluster.sdn.set()
        timeout = self.module.params['timeout']
        nodes = self.proxmox_api.resources.get(type="node")
        import time
        while timeout:
            all_ok = all(self.api_task_ok(node, taskid) for node in nodes)
            if all_ok:
                # Wait an extra second as the API can be a ahead of the hypervisor
                time.sleep(1)
                break
            timeout = timeout - 1
            time.sleep(1)
        else:
            self.module.fail_json(msg="Timeout ")


def main():
    module_args = proxmox_auth_argument_spec()
    sdn_args = dict(
        state=dict(default="present", choices=["present", "absent"]),
        update=dict(default=False, type='bool'),
        apply=dict(default=False, type='bool'),
        timeout=dict(type='int', default=30),
        zone = dict(type='dict',
                    options=dict(
                        id=dict(type="str", required=True),
                        type=dict(type="str", choices=["simple", "vlan"]),
                        bridge=dict(type="str"),
                        additionals=dict(type="dict"),
                    )),
    )

    module_args.update(sdn_args)

    module = AnsibleModule(
        argument_spec=module_args,
        required_together=[("api_token_id", "api_token_secret")],
        required_one_of=[("api_password", "api_token_id")],
        mutually_exclusive=[('delete', 'update')],

        supports_check_mode=True
    )

    zone = module.params["zone"]
    state = module.params["state"]
    update = bool(module.params["update"])
    apply = bool(module.params["apply"])

    proxmox = ProxmoxSDNAnsible(module)
    applied = False
    if state == "present":
        try:
            proxmox.create_zone(zone=zone, update=update)
        except Exception as e:
            if update:
                module.fail_json(msg="Unable to update sdn {0}. Reason: {1}".format(zone["id"], str(e)))
            else:
                module.fail_json(msg="Unable to create sdn {0}. Reason: {1}".format(zone["id"], str(e)))

        if apply:
            proxmox.apply_changes()
            applied = True
        if update:
            module.exit_json(changed=True, id=zone["id"], applied=applied, msg="Zone {0} successfully updated".format(zone["id"]))
        else:
            module.exit_json(changed=True, id=zone["id"], applied=applied, msg="Zone {0} successfully created".format(zone["id"]))
    
    else:
        proxmox.delete_zone(zone["id"])
        proxmox.apply_changes()
        module.exit_json(changed=True, id=zone["id"], applied=applied, msg="Zone {0} successfully deleted".format(zone["id"]))


if __name__ == "__main__":
    main()
