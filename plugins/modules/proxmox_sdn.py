#!/usr/bin/python
# -*- coding: utf-8 -*-
#
from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.community.general.plugins.module_utils.proxmox import (proxmox_auth_argument_spec, ProxmoxAnsible)


import urllib3
urllib3.disable_warnings()

import re
# sdn_object_id = re.compile(r'^[a-z0-9_][a-z0-9_\-\+\.]*$')
sdn_object_id = re.compile(r'^[a-z][a-z0-9]*$')

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

    def create_zone(self, zone, update, apply):
        """Create Proxmox VE sdn

        :param sdnid: str - name of the sdn
        :return: None
        """
        if self.is_sdn_existing(zone["id"]):
            # Ugly ifs
            if not update and not apply:
                self.module.exit_json(changed=False, id=zone["id"], msg="sdn {0} already exists".format(zone["id"]))
            if apply:
                return False
                # self.apply_changes()
                # # TODO: how do we now that something has changed?
                # self.module.exit_json(changed=True, msg="Changes applied")
        if self.module.check_mode:
            return

        zone_copy = dict(**zone)
        zone_id = zone_copy.pop("id")
        if not sdn_object_id.match(zone_id):
            self.module.fail_json(msg='{0} is not a valid sdn object identifier'.format(zone_id))

        additionals = zone_copy.pop("additionals", {})
        if update:
            zone_copy.pop("type")
            self.proxmox_api.cluster.sdn.zones(zone_id).set(**zone_copy, **additionals)
        else:
            self.proxmox_api.cluster.sdn.zones().post(zone=zone_id, **zone_copy, **additionals)
        
        return True      
        

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

    def is_vnet_existing(self, vnet_id):
        try:
            vnets = self.proxmox_api.cluster.sdn.vnets.get()
            return any(vnet['vnet'] == vnet_id for vnet in vnets)
        except Exception as e:
            self.module.fail_json(msg="Unable to retrieve vnets: {0}".format(e))


    def create_vnet(self, vnet, zone, update, apply,
                     alias=None, tag=None, type=None, vlanaware=False):
        if not self.is_sdn_existing(zone):
            self.module.fail_json(msg="SDN {0} doesn't exist".format(zone))
        if self.is_vnet_existing(vnet):
            # Ugly ifs
            if not update and not apply: # TODO exit not possible if we have multiple vnets...
                self.module.exit_json(changed=False, id=vnet, msg="Vnet {0} already exists".format(vnet))
            if apply:
                self.apply_changes()
                # TODO: how do we now that something has changed?
                self.module.exit_json(changed=True, msg="Changes applied")
        if self.module.check_mode:
            return
        
        if not sdn_object_id.match(vnet): # TODO should we do the check before creating zones and other vnets?
            self.module.fail_json(msg='{0} is not a valid sdn object identifier'.format(vnet))

        if update:
            self.proxmox_api.cluster.sdn.vnets(vnet).set(
                zone=zone, alias=alias, tag=tag, type=type, vlanaware=vlanaware
                )
        else:
            self.proxmox_api.cluster.sdn.vnets.post(vnet=vnet,
                zone=zone, alias=alias, tag=tag, type=type, vlanaware=vlanaware)
        
        if apply:
            self.apply_changes()


    def apply_changes(self):
        taskid = self.proxmox_api.cluster.sdn.set()
        timeout = self.module.params['timeout']
        nodes = self.proxmox_api.cluster.resources.get(type="node")
        import time
        while timeout:
            all_ok = all(self.api_task_ok(node["node"], taskid) for node in nodes)
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
        vnets = dict(type='list', elements='dict'
                    #  elements=dict(
                    #     id=dict(type="str", required=True),
                    #     zone=dict(type="str"),
                    #     alias=dict(type="str"),
                    #     tag=dict(type="int"),
                    #     type=dict(type="str", choices=[""]),
                    #     vlanaware=dict(type="bool"),
                    #  )
                     ),
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
    vnets = list(module.params["vnets"])
    proxmox = ProxmoxSDNAnsible(module)

    data = {}
    pending_changes = False
    if state == "present":
        try:
            if zone:
                pending_changes |= proxmox.create_zone(zone=zone, update=update, apply=apply)
                zone_info = proxmox.get_zone(zone["id"])
                data["msg"] = "Zone {0} successfully {1}.".format(zone["id"], "updated" if update else "created")
                data["zone"] = zone_info
            if vnets:
                for vnet in vnets:
                    proxmox.create_vnet(vnet=vnet["id"], zone=vnet["zone"], alias=vnet.get("alias"), type=vnet.get("type"), vlanaware=vnet.get("vlanaware"),apply=apply,update=update)
                    data["msg"] = "Vnet {0} successfully {1}.".format(zone["id"], "updated" if update else "created")

        except Exception as e:
            if update:
                module.fail_json(msg="Unable to update sdn objects. Reason: {0}".format(str(e)))
            else:
                module.fail_json(msg="Unable to create sdn objects. Reason: {0}".format(str(e)))
        data["changed"] = True
        if apply:
            proxmox.apply_changes()
            data["msg"] += " Changes applied."
        module.exit_json(applied=apply, **data)
    
    else:
        proxmox.delete_zone(zone["id"])
        proxmox.apply_changes()
        module.exit_json(changed=True, id=zone["id"], applied=apply, msg="Zone {0} successfully deleted".format(zone["id"]))


if __name__ == "__main__":
    main()
