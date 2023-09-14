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
    def is_sdn_existing(self, sdnid):
        """Check whether sdn already exist

        :param sdnid: str - name of the sdn
        :return: bool - is sdn exists?
        """
        try:
            sdns = self.proxmox_api.cluster.sdn.zones.get()
            return any(sdn["zone"] == sdnid for sdn in sdns)
        except Exception as e:
            self.module.fail_json(msg="Unable to retrieve sdns: {0}".format(e))

    def is_sdn_empty(self, sdnid):
        """Check whether sdn has vnets

        :param sdnid: str - name of the sdn
        :return: list of vnets
        """
        return [vnet for vnet in self.proxmox_api.cluster.sdn.vnets.get() if vnet["zone"] == sdnid]

    def create_zone(self, zone, update, apply):
        """Create Proxmox VE sdn

        :param sdnid: str - name of the sdn
        :return: True if we have created or potential changed a zone
        """
        zone_exists = False
        if self.is_sdn_existing(zone["id"]):
            # Ugly ifs
            if not update and not apply:
                self.module.exit_json(changed=False, id=zone["id"], msg="sdn {0} already exists".format(zone["id"]))
            if not update and apply:
                return False
            zone_exists = True

        zone_copy = dict(**zone)
        zone_id = zone_copy.pop("id")
        if not sdn_object_id.match(zone_id):
            self.module.fail_json(msg="{0} is not a valid sdn object identifier".format(zone_id))

        additionals = zone_copy.pop("additionals")
        if update:
            if not zone_exists:
                self.module.fail_json(msg="Zone object {0} does not exist".format(zone["id"]))

            zone_copy.pop("type")
            self.proxmox_api.cluster.sdn.zones(zone_id).set(**zone_copy, **additionals)
        else:
            self.proxmox_api.cluster.sdn.zones.post(zone=zone_id, **zone_copy, **additionals)

        return True

    def delete_vnet(self, vnetid):
        if not self.is_vnet_existing(vnetid):
            self.module.exit_json(changed=False, id=vnetid, msg="vnet {0} doesn't exist".format(vnetid))
        try:
            self.proxmox_api.cluster.sdn.vnets(vnetid).delete()
        except Exception as e:
            self.module.fail_json(msg="Failed to delete vnet with ID {0}: {1}".format(vnetid, e))

    def delete_zone(self, force, sdnid):
        """Delete Proxmox VE sdn

        :param sdnid: str - name of the sdn
        :return: None
        """
        if not self.is_sdn_existing(sdnid):
            self.module.exit_json(changed=False, id=sdnid, msg="sdn {0} doesn't exist".format(sdnid))

        vnets = self.is_sdn_empty(sdnid)

        if force and vnets:
            for vnet in vnets:
                self.delete_vnet(vnet["vnet"])
        elif not force and vnets:
            self.module.fail_json(
                msg="Can't delete sdn {0} with vnets. Please remove vnets from sdn first or use `force: True`.".format(
                    sdnid
                )
            )
        try:
            self.proxmox_api.cluster.sdn.zones(sdnid).delete()
        except Exception as e:
            self.module.fail_json(msg="Failed to delete sdn with ID {0}: {1}".format(sdnid, e))

    def is_vnet_existing(self, vnet_id):
        try:
            vnets = self.proxmox_api.cluster.sdn.vnets.get()
            return next((vnet for vnet in vnets if vnet["vnet"] == vnet_id), None)
        except Exception as e:
            self.module.fail_json(msg="Unable to retrieve vnets: {0}".format(e))

    def create_vnet(self, vnet, zone, alias=None, tag=None, type=None, vlanaware=False, update=False, apply=False):
        if not self.is_sdn_existing(zone):
            self.module.fail_json(msg="SDN {0} doesn't exist".format(zone))
        if self.is_vnet_existing(vnet):
            # Ugly ifs
            if not update and not apply:
                self.module.exit_json(changed=False, id=vnet, msg="Vnet {0} already exists".format(vnet))
            if not update and apply:
                return False

        if not sdn_object_id.match(vnet):  # TODO should we do the check before creating zone
            self.module.fail_json(msg="{0} is not a valid sdn object identifier".format(vnet))

        if update:
            self.proxmox_api.cluster.sdn.vnets(vnet).set(
                zone=zone, alias=alias, tag=tag, type=type, vlanaware=ansible_to_proxmox_bool(vlanaware)
            )
        else:
            self.proxmox_api.cluster.sdn.vnets.post(
                vnet=vnet, zone=zone, alias=alias, tag=tag, type=type, vlanaware=ansible_to_proxmox_bool(vlanaware)
            )
        return True

    def is_subnet_existing(self, cidr, vnet):
        """Check whether sdn already exist

        :param sdnid: str - name of the sdn
        :return: bool - is sdn exists?
        """
        try:
            sdns = self.proxmox_api.cluster.sdn.vnets(vnet).subnets.get(pending="1")
            return next((sdn for sdn in sdns if sdn["cidr"] == cidr), None)
        except Exception as e:
            self.module.fail_json(msg="Unable to retrieve sdns: {0}".format(e))

    def delete_subnet(self, subnet, vnet):
        subnet_obj = self.is_subnet_existing(subnet, vnet)
        if not subnet_obj:
            self.module.exit_json(changed=False, id=subnet, msg="Subnet {0} doesn't exist".format(subnet))
        try:
            self.proxmox_api.cluster.sdn.vnets(vnet).subnets(subnet_obj["subnet"]).delete()
        except Exception as e:
            self.module.fail_json(msg="Failed to delete subnet with ID {0}: {1}".format(subnet, e))

    def create_subnet(self, cidr, vnet, dnszoneprefix=None, gateway=None, snat=False, update=False, apply=False):
        vnet_object = self.is_vnet_existing(vnet)
        if not vnet_object:
            self.module.fail_json(msg="Vnet {0} doesn't exist".format(vnet))

        # addr, _ = ipaddress.IPv4Network._split_addr_prefix(cidr)
        # name = f"{vnet_object['zone']}-{addr}-{ip_nw.prefixlen}"
        subnet = self.is_subnet_existing(cidr, vnet)
        if subnet:
            # Ugly ifs
            if not update and not apply:
                self.module.exit_json(changed=False, id=vnet, msg="Subnet {0} already exists".format(cidr))
            if not update and apply:
                return False

        # if not sdn_object_id.match(vnet):  # TODO should we do the check before creating zone
        #     self.module.fail_json(msg="{0} is not a valid sdn object identifier".format(vnet))

        if update:
            self.proxmox_api.cluster.sdn.vnets(vnet).subnets(subnet["subnet"]).set(
                vnet=vnet,
                # cidr=cidr,
                # subnet=cidr,
                dnszoneprefix=dnszoneprefix,
                gateway=gateway,
                snat=ansible_to_proxmox_bool(snat),
            )
        else:
            self.proxmox_api.cluster.sdn.vnets(vnet).subnets.post(
                subnet=cidr,
                type="subnet",
                # cidr=cidr,
                vnet=vnet,
                dnszoneprefix=dnszoneprefix,
                gateway=gateway,
                snat=ansible_to_proxmox_bool(snat),
            )
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

    if subnet:
        try:
            _ = ipaddress.ip_network(subnet["cidr"], False)
        except e:
            module.fail_json(msg=f"{subnet['cidr']} not a valid CIDR")

    if state == "present":
        try:
            if zone:
                check_changes = proxmox.create_zone(zone=zone, update=update, apply=apply)
                if check_changes:
                    # get zone info's to check for pending changes
                    zone_info = proxmox.proxmox_api.cluster.sdn.zones(zone["id"]).get(pending="1")
                    state = zone_info.get("state")
                    if state:
                        pending_changes = True
                        msgs.append(
                            "Zone {0} successfully {1}.".format(
                                zone["id"], "changed" if state == "changed" else "created"
                            )
                        )

            if vnet:
                if vnet["zone"] == "vlan" and not vnet.get("tag"):
                    module.fail_json(msg="missing vlan tag")

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
                    vnet_info = proxmox.proxmox_api.cluster.sdn.vnets(vnet["id"]).get(pending="1")
                    state = vnet_info.get("state", "")
                    if state:
                        pending_changes = True
                        msgs.append("Vnet {0} successfully {1}.".format(vnet["id"], "updated" if update else "created"))

            if subnet:
                check_changes = proxmox.create_subnet(
                    cidr=subnet["cidr"],
                    vnet=subnet["vnet"],
                    dnszoneprefix=subnet["dnszoneprefix"],
                    gateway=subnet["gateway"],
                    snat=subnet["snat"],
                    update=update,
                    apply=apply,
                )
                if check_changes:
                    # get subnet info's to check for pending changes
                    subnet_info = proxmox.is_subnet_existing(subnet["cidr"], subnet["vnet"])
                    state = subnet_info.get("state", "")
                    if state:
                        pending_changes = True
                        msgs.append(
                            "Subnet {0} successfully {1}.".format(subnet["cidr"], "updated" if update else "created")
                        )

        except ResourceException as e:
            if update:
                module.fail_json(msg="Unable to update sdn objects. Reason: {0}".format(str(e)))
            else:
                module.fail_json(msg="Unable to create sdn objects. Reason: {0}".format(str(e)))
        # if we have pending changes, we have changed something
        data["changed"] = pending_changes
        if pending_changes and apply:
            proxmox.apply_changes()
            msgs.append("Pending changes applied.")
        if not pending_changes:
            msgs.append("Everything is up to date.")
        module.exit_json(applied=apply, **data, msg="\n".join(msgs))

    else:
        if subnet:
            proxmox.delete_subnet(subnet["cidr"], subnet["vnet"])
            subnet_info = proxmox.is_subnet_existing(subnet["cidr"], subnet["vnet"])
            if subnet_info:  # can be none if subnet was in 'new' state before and is now deleted
                state = subnet_info.get("state")
                if state:
                    pending_changes = True
                    msgs.append("Subnet {0} deleted".format(subnet["cidr"]))

        if vnet:
            proxmox.delete_vnet(vnet["id"])
            # get vnet info's to check for pending changes
            vnet_info = proxmox.proxmox_api.cluster.sdn.vnets(vnet["id"]).get(pending="1")
            state = vnet_info.get("state")
            if state:
                pending_changes = True
                msgs.append("Vnet {0} deleted".format(vnet["id"]))

        if zone:
            proxmox.delete_zone(module.params["force"], zone["id"])
            # get zone info's to check for pending changes
            zone_info = proxmox.proxmox_api.cluster.sdn.zones(zone["id"]).get(pending="1")
            state = zone_info.get("state")
            if state:
                pending_changes = True
                msgs.append("Zone {0} deleted".format(zone["id"]))
        data["changed"] = pending_changes
        if pending_changes and apply:
            proxmox.apply_changes()
            msgs.append("Pending changes applied.")
        if not pending_changes:
            msgs.append("Everything is up to date.")

        module.exit_json(applied=apply, **data, msg="\n".join(msgs))


if __name__ == "__main__":
    main()
