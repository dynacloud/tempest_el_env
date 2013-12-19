# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 NEC Corporation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from tempest.scenario import manager
from tempest.test import services
from tempest.common.utils.data_utils import rand_name
from tempest.openstack.common import log as logging

LOG = logging.getLogger(__name__)

class TestSnapshotPattern(manager.NetworkScenarioTest):
    """
    This test is for snapshotting an instance and booting with it.
    The following is the scenario outline:
     * boot a instance and create a timestamp file in it
     * snapshot the instance
     * boot a second instance from the snapshot
     * check the existence of the timestamp file in the second instance

    """
    @classmethod
    def check_preconditions(cls):
        super(TestSnapshotPattern, cls).check_preconditions()
        cfg = cls.config.network
        if not (cfg.tenant_networks_reachable or cfg.public_network_id):
            msg = ('Either tenant_networks_reachable must be "true", or '
                   'public_network_id must be defined.')
            cls.enabled = False
            raise cls.skipException(msg)

    @classmethod
    def setUpClass(cls):
        super(TestSnapshotPattern, cls).setUpClass()
        cls.check_preconditions()
        # TODO(mnewby) Consider looking up entities as needed instead
        # of storing them as collections on the class.
        cls.floating_ips = {}


    def _image_create(self, name, fmt, fmt2, path, properties={}):
        name = rand_name('%s-' % name)
        image_file = open(path, 'rb')
        self.addCleanup(image_file.close)
        params = {
            'name': name,
            'container_format': fmt2,
            'disk_format': fmt,
            'is_public': 'True',
        }
        params.update(properties)
        image = self.image_client.images.create(**params)
        self.addCleanup(self.image_client.images.delete, image)
        self.assertEqual("queued", image.status)
        image.update(data=image_file)
        return image.id

    def glance_image_create(self):
        ami_img_path = self.config.scenario.img_dir + "/" + \
            self.config.scenario.ami_img_file
        LOG.debug("paths: ami: %s"
                  % (ami_img_path))

        properties = {}
        self.image = self._image_create('scenario-qcow2', 'qcow2', 'ovf',
                                        path=ami_img_path,
                                        properties=properties)

    def _boot_image(self, image_id):
        create_kwargs = {
            'key_name': self.keypair.name
        }
        self.server = self.create_server(image=image_id, create_kwargs=create_kwargs)
        #return self.server

    def _add_keypair(self):
        self.keypair = self.create_keypair()

    def _ssh_to_server(self, server_or_ip):
        linux_client = self.get_remote_client(server_or_ip)
        return linux_client.ssh_client

    def _write_timestamp(self, server_or_ip):
        ssh_client = self._ssh_to_server(server_or_ip)
        ssh_client.exec_command('date > /tmp/timestamp; sync')
        self.timestamp = ssh_client.exec_command('cat /tmp/timestamp')

    def _check_timestamp(self, server_or_ip):
        ssh_client = self._ssh_to_server(server_or_ip)
        got_timestamp = ssh_client.exec_command('cat /tmp/timestamp')
        self.assertEqual(self.timestamp, got_timestamp)


    def _create_floating_ip2(self):
        public_network_id = self.config.network.public_network_id
        server = self.server
        self.floating_ip = self._create_floating_ip(server, public_network_id)
        floating_ip = self.floating_ip
        self.floating_ips.setdefault(server, [])
        self.floating_ips[server].append(floating_ip)
        #return floating_ip      

    @services('compute', 'network', 'image')
    def test_snapshot_pattern(self):
        # prepare for booting a instance
        self._add_keypair()
        self.glance_image_create()
        self.create_loginable_secgroup_rule()

        # boot a instance and create a timestamp file in it
        self._boot_image(self.image)
        if self.config.compute.use_floatingip_for_ssh:
            self._create_floating_ip2()
            self._write_timestamp(self.floating_ip.floating_ip_address)
        else:
            self._write_timestamp(self.server)

        # snapshot the instance
        snapshot_image = self.create_server_snapshot(server=self.server)

        # boot a second instance from the snapshot
        self._boot_image(snapshot_image.id)

        # check the existence of the timestamp file in the second instance
        if self.config.compute.use_floatingip_for_ssh:
            self._create_floating_ip2()
            self._check_timestamp(self.floating_ip.floating_ip_address)
        else:
            self._check_timestamp(self.server)
