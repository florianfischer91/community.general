#!/usr/bin/python
# -*- coding: utf-8 -*-
#
from __future__ import absolute_import, division, print_function

__metaclass__ = type

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.community.general.plugins.module_utils.proxmox import (
    proxmox_auth_argument_spec,
    ansible_to_proxmox_bool,
    ProxmoxAnsible,
)
from proxmoxer import ResourceException
import ipaddress
import urllib3

urllib3.disable_warnings()

import re

sdn_object_id = re.compile(r"^[a-z][a-z0-9]*$")


class ProxmoxSDNAnsible(ProxmoxAnsible):
    def get_zone(self, zone, pending="0"):
        try:
            return next((z for z in self.proxmox_api.cluster.sdn.zones.get(pending=pending) if z["zone"] == zone), None)
        except Exception as e:
            self.module.fail_json(msg="Unable to retrieve zone: {0}".format(e))

    def get_vnets_of_zone(self, zone, pending="0"):
        try:
            return [vnet for vnet in self.proxmox_api.cluster.sdn.vnets.get(pending=pending) if vnet["zone"] == zone]
        except Exception as e:
            self.module.fail_json(msg="Unable to retrieve vnets: {0}".format(e))

    def create_zone(self, zone, update, apply):
        zone_exists = False
        if self.get_zone(zone["id"]):
            # Ugly ifs
            if not update:
                return False
            # if not update and not apply:
            #     return False
            #     self.module.exit_json(changed=False, id=zone["id"], msg="sdn {0} already exists".format(zone["id"]))
            # if not update and apply:
            #     return False
            zone_exists = True

        zone_copy = dict(**zone)
        zone_id = zone_copy.pop("id")

        additionals = zone_copy.pop("additionals")
        if update:
            if not zone_exists:
                self.module.fail_json(msg="Zone object {0} does not exist".format(zone["id"]))

            zone_copy.pop("type")
            self.proxmox_api.cluster.sdn.zones(zone_id).set(**zone_copy, **additionals)
        else:
            self.proxmox_api.cluster.sdn.zones.post(zone=zone_id, **zone_copy, **additionals)

        return True

    def delete_vnet(self, force, vnet):
        vnet_obj = self.get_vnet(vnet, pending="1")
        if vnet_obj is None or vnet_obj.get("state") == "deleted":
            return False

        subnets = self.get_subnets_of_vnet(vnet)
        if force and subnets:
            for subnet in subnets:
                self.delete_subnet(subnet["cidr"], vnet)
        elif not force and subnets:
            self.module.fail_json(
                msg="Can't delete vnet {0} with subnets. Please remove subnets from vnet first or use `force: True`.".format(
                    vnet
                )
            )
        try:
            self.proxmox_api.cluster.sdn.vnets(vnet).delete()
        except Exception as e:
            self.module.fail_json(msg="Failed to delete vnet with ID {0}: {1}".format(vnet, e))
        return True

    def delete_zone(self, force, zone):
        zone_obj = self.get_zone(zone, pending="1")
        if zone_obj is None or zone_obj.get("state") == "deleted":
            return False

        vnets = self.get_vnets_of_zone(zone)

        if force and vnets:
            for vnet in vnets:
                self.delete_vnet(force, vnet["vnet"])
        elif not force and vnets:
            self.module.fail_json(
                msg="Can't delete zone {0} with vnets. Please remove vnets from zone first or use `force: True`.".format(
                    zone
                )
            )
        try:
            self.proxmox_api.cluster.sdn.zones(zone).delete()
        except Exception as e:
            self.module.fail_json(msg="Failed to delete zone with ID {0}: {1}".format(zone, e))
        return True

    def get_vnet(self, vnet, pending="0"):
        try:
            return next((v for v in self.proxmox_api.cluster.sdn.vnets.get(pending=pending) if v["vnet"] == vnet), None)
        except Exception as e:
            self.module.fail_json(msg="Unable to retrieve vnet: {0}".format(e))

    def create_vnet(self, vnet, zone, alias=None, tag=None, type=None, vlanaware=False, update=False, apply=False):
        if not self.get_zone(zone):
            self.module.fail_json(msg="Zone {0} doesn't exist".format(zone))
        if self.get_vnet(vnet):
            # Ugly ifs
            if not update and not apply:
                return False
                # self.module.exit_json(changed=False, id=vnet, msg="Vnet {0} already exists".format(vnet))
            if not update and apply:
                return False

        if update:
            self.proxmox_api.cluster.sdn.vnets(vnet).set(
                zone=zone, alias=alias, tag=tag, type=type, vlanaware=ansible_to_proxmox_bool(vlanaware)
            )
        else:
            self.proxmox_api.cluster.sdn.vnets.post(
                vnet=vnet, zone=zone, alias=alias, tag=tag, type=type, vlanaware=ansible_to_proxmox_bool(vlanaware)
            )
        return True

    def get_subnet(self, cidr, vnet):
        return next((sdn for sdn in self.get_subnets_of_vnet(vnet) if sdn["cidr"] == cidr), None)

    def get_subnets_of_vnet(self, vnet):
        try:
            return self.proxmox_api.cluster.sdn.vnets(vnet).subnets.get(pending="1")
        except Exception as e:
            self.module.fail_json(msg="Unable to retrieve subnet: {0}".format(e))

    def delete_subnet(self, subnet, vnet):
        """Return `True` if subnet was deleted, `False` when already absent"""
        subnet_obj = self.get_subnet(subnet, vnet)
        if subnet_obj is None or subnet_obj.get("state") == "deleted":
            return False
        try:
            self.proxmox_api.cluster.sdn.vnets(vnet).subnets(subnet_obj["subnet"]).delete()
        except Exception as e:
            self.module.fail_json(msg="Failed to delete subnet with ID {0}: {1}".format(subnet, e))
        return True

    def create_subnet(self, cidr, vnet, data, update=False, apply=False):
        vnet_object = self.get_vnet(vnet)
        if not vnet_object:
            self.module.fail_json(msg="Vnet {0} doesn't exist".format(vnet))

        subnet = self.get_subnet(cidr, vnet)
        if subnet:
            # Ugly ifs
            if not update and not apply:
                return False
                # self.module.exit_json(changed=False, id=vnet, msg="Subnet {0} does already exist".format(cidr))
            if not update and apply:
                return False

        if update:
            self.proxmox_api.cluster.sdn.vnets(vnet).subnets(subnet["subnet"]).set(vnet=vnet, **data)
        else:
            self.proxmox_api.cluster.sdn.vnets(vnet).subnets.post(subnet=cidr, type="subnet", vnet=vnet, **data)
        return True

    def apply_changes(self):
        taskid = self.proxmox_api.cluster.sdn.set()
        timeout = self.module.params["timeout"]
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
        update=dict(default=False, type="bool"),
        apply=dict(default=False, type="bool"),
        force=dict(default=False, type="bool"),  # force recursive delete
        timeout=dict(type="int", default=30),
        zone=dict(
            type="dict",
            options=dict(
                id=dict(type="str", required=True),
                type=dict(type="str", choices=["simple", "vlan"]),
                bridge=dict(type="str"),
                additionals=dict(type="dict", default={}),
            ),
        ),
        vnet=dict(
            type="dict",
            options=dict(
                id=dict(type="str", required=True),
                zone=dict(type="str", required=True),
                alias=dict(type="str"),
                tag=dict(type="int"),
                # type=dict(type="str"), # defined in api-doc but proxmox doesn't allow it
                vlanaware=dict(type="bool"),
            ),
        ),
        subnet=dict(
            type="dict",
            options=dict(
                cidr=dict(type="str", required=True),
                vnet=dict(type="str", required=True),
                dnszoneprefix=dict(type="str"),
                gateway=dict(type="str"),
                snat=dict(type="bool"),
            ),
        ),
    )

    module_args.update(sdn_args)

    module = AnsibleModule(
        argument_spec=module_args,
        required_together=[("api_token_id", "api_token_secret")],
        required_one_of=[("api_password", "api_token_id")],
        mutually_exclusive=[("delete", "update")],
    )

    zone = module.params["zone"]
    state = module.params["state"]
    update = bool(module.params["update"])
    apply = bool(module.params["apply"])
    vnet = module.params["vnet"]
    subnet = module.params["subnet"]
    proxmox = ProxmoxSDNAnsible(module)

    data = {}
    msgs = []
    pending_changes = False

    # validation
    if subnet:
        cidr = subnet.pop("cidr")
        subnet_vnet = subnet.pop("vnet")
        try:
            _ = ipaddress.ip_network(cidr, False)
        except Exception as e:
            module.fail_json(msg=f"{cidr} not a valid CIDR")
    if vnet:
        if not sdn_object_id.match(vnet["id"]):
            module.fail_json(msg="{0} is not a valid sdn object identifier".format(vnet["id"]))

        if vnet["zone"] == "vlan" and not vnet.get("tag"):
            module.fail_json(msg="missing vlan tag")
    if zone:
        zone_id = zone["id"]
        if not sdn_object_id.match(zone_id):
            module.fail_json(msg="{0} is not a valid sdn object identifier".format(zone_id))

    # execute
    try:
        if state == "present":
            if zone:
                created_or_updated = proxmox.create_zone(zone=zone, update=update, apply=apply)
                # if check_changes:
                # get zone info's to check for pending changes
                # zone_info = proxmox.proxmox_api.cluster.sdn.zones(zone_id).get(pending="1")
                # zone_state = zone_info.get("state")
                # if zone_state:
                #     pending_changes = True
                if created_or_updated:
                    pending_changes = True
                    msgs.append("Zone {0} successfully {1}.".format(zone["id"], "updated" if update else "created"))
                else:
                    msgs.append("Zone {0} already exists.".format(zone_id))

            if vnet:
                check_changes = proxmox.create_vnet(
                    vnet=vnet["id"],
                    zone=vnet["zone"],
                    alias=vnet.get("alias"),
                    tag=vnet.get("tag"),
                    type=vnet.get("type"),
                    vlanaware=vnet.get("vlanaware"),
                    apply=apply,
                    update=update,
                )
                if check_changes:
                    # get vnet info's to check for pending changes
                    # vnet_info = proxmox.proxmox_api.cluster.sdn.vnets(vnet["id"]).get(pending="1")
                    # state = vnet_info.get("state")
                    # if state:
                    #     pending_changes = True
                    pending_changes = True
                    msgs.append("Vnet {0} successfully {1}.".format(vnet["id"], "updated" if update else "created"))
                else:
                    msgs.append("Vnet {0} already exists.".format(vnet["id"]))

            if subnet:
                subnet["snat"] = ansible_to_proxmox_bool(subnet["snat"])
                check_changes = proxmox.create_subnet(
                    cidr=cidr, vnet=subnet_vnet, data=subnet, update=update, apply=apply
                )
                if check_changes:
                    # get subnet info's to check for pending changes
                    # subnet_info = proxmox.get_subnet(cidr, subnet_vnet)
                    # state = subnet_info.get("state")
                    # if state:
                    #     pending_changes = True
                    pending_changes = True
                    msgs.append("Subnet {0} successfully {1}.".format(cidr, "updated" if update else "created"))
                else:
                    msgs.append("Subnet {0} of {1} already exists.".format(cidr, subnet_vnet))

        else:  # delete objects
            if subnet:
                check_changes = proxmox.delete_subnet(cidr, subnet_vnet)
                if not check_changes:
                    msgs.append("Subnet '{0}' of vnet {1} is already absent".format(cidr, subnet_vnet))
                else:
                    # subnet_info = proxmox.get_subnet(cidr, subnet_vnet)
                    # if subnet_info:  # can be none if subnet was in 'new' state before and is now deleted
                    #     state = subnet_info.get("state")
                    #     if state:
                    pending_changes = True
                    msgs.append("Subnet {0} of {1} deleted.".format(cidr, subnet_vnet))

            if vnet:
                check_changes_vnet = proxmox.delete_vnet(module.params["force"], vnet["id"])
                if not check_changes_vnet:
                    msgs.append("Vnet '{0}' is already absent".format(vnet["id"]))
                else:
                    # get vnet info's to check for pending changes
                    # vnet_info = proxmox.proxmox_api.cluster.sdn.vnets(vnet["id"]).get(pending="1")
                    # state = vnet_info.get("state")
                    # if state:
                    pending_changes = True
                    msgs.append("Vnet {0} deleted.".format(vnet["id"]))

            if zone:
                check_changes = proxmox.delete_zone(module.params["force"], zone_id)
                if not check_changes:
                    msgs.append("Zone '{0}' is already absent".format(zone_id))
                else:
                    # get zone info's to check for pending changes
                    # zone_info = proxmox.proxmox_api.cluster.sdn.zones(zone_id).get(pending="1")
                    # state = zone_info.get("state")
                    # if state:
                    pending_changes = True
                    msgs.append("Zone {0} deleted.".format(zone_id))

        # if we have pending changes, we have changed something
        # if pending_changes:
        if apply:
            if not pending_changes:
                zone_info = proxmox.proxmox_api.cluster.sdn.zones.get(pending="1")
                pending_changes = any(info.get("state") for info in zone_info)
            if not pending_changes:
                vnet_info = proxmox.proxmox_api.cluster.sdn.vnets.get(pending="1")
                pending_changes = any(info.get("state") for info in vnet_info)
            if not pending_changes:
                for info in vnet_info:
                    subnet_info = proxmox.get_subnets_of_vnet(info["vnet"])
                    pending_changes = any(sinfo.get("state") for sinfo in subnet_info)
                    if pending_changes:
                        break
            if pending_changes:
                proxmox.apply_changes()
                msgs.append("Pending changes applied.")
            else:
                # msgs.append(zone_info)
                msgs.append("No pending changes detected.")
        # else:
        #     msgs.append("Pending changes not applied.")
        data["changed"] = pending_changes
        # else:
        #     msgs.append("Everything is up to date.")

        module.exit_json(**data, msg=" ".join(msgs))

    except ResourceException as e:
        if update:
            module.fail_json(msg="Unable to update sdn objects. Reason: {0}".format(str(e)))
        elif state == "absent":
            module.fail_json(msg="Unable to delete sdn objects. Reason: {0}".format(str(e)))
        else:
            module.fail_json(msg="Unable to create sdn objects. Reason: {0}".format(str(e)))


if __name__ == "__main__":
    main()
