# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from tempest.common.utils import data_utils
from tempest.scenario import manager
from tempest.test import services
from tempest.common.utils.data_utils import rand_name

#LOG = logging.getLogger(__name__)

class TestVolumeBootPattern(manager.NetworkScenarioTest):

    """
    This test case attempts to reproduce the following steps:

     * Create in Cinder some bootable volume importing a Glance image
     * Boot an instance from the bootable volume
     * Write content to the volume
     * Delete an instance and Boot a new instance from the volume
     * Check written content in the instance
     * Create a volume snapshot while the instance is running
     * Boot an additional instance from the new snapshot based volume
     * Check written content in the instance booted from snapshot
    """

    @classmethod
    def check_preconditions(cls):
        super(TestVolumeBootPattern, cls).check_preconditions()
        cfg = cls.config.network
        if not (cfg.tenant_networks_reachable or cfg.public_network_id):
            msg = ('Either tenant_networks_reachable must be "true", or '
                   'public_network_id must be defined.')
            cls.enabled = False
            raise cls.skipException(msg)

    @classmethod
    def setUpClass(cls):
        super(TestVolumeBootPattern, cls).setUpClass()
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
        #LOG.debug("paths: ami: %s"
                  #% (ami_img_path))

        properties = {}
        self.image = self._image_create('scenario-qcow2', 'qcow2', 'ovf',
                                        path=ami_img_path,
                                        properties=properties)
	image_id = self.image
	return image_id         
        
    def _create_volume_from_image(self,image_id):
        img_uuid = image_id
        #img_uuid = self.config.compute.image_ref
        vol_name = data_utils.rand_name('volume-origin')
        return self.create_volume(name=vol_name, imageRef=img_uuid)

    def _boot_instance_from_volume(self, image_id, vol_id, keypair):
        # NOTE(gfidente): the syntax for block_device_mapping is
        # dev_name=id:type:size:delete_on_terminate
        # where type needs to be "snap" if the server is booted
        # from a snapshot, size instead can be safely left empty
        bd_map = {
            'vda': vol_id + ':::0'
        }
        create_kwargs = {
            'block_device_mapping': bd_map,
            'key_name': keypair.name
        }
        image = image_id
        self.server = self.create_server(image=image, create_kwargs=create_kwargs)
        return self.server

    def _create_snapshot_from_volume(self, vol_id):
        volume_snapshots = self.volume_client.volume_snapshots
        snap_name = data_utils.rand_name('snapshot')
        snap = volume_snapshots.create(volume_id=vol_id,
                                       force=True,
                                       display_name=snap_name)
        self.set_resource(snap.id, snap)
        self.status_timeout(volume_snapshots,
                            snap.id,
                            'available')
        return snap

    def _create_volume_from_snapshot(self, snap_id):
        vol_name = data_utils.rand_name('volume')
        return self.create_volume(name=vol_name, snapshot_id=snap_id)

    def _stop_instances(self, instances):
        # NOTE(gfidente): two loops so we do not wait for the status twice
        for i in instances:
            self.compute_client.servers.stop(i)
        for i in instances:
            self.status_timeout(self.compute_client.servers,
                                i.id,
                                'SHUTOFF')

    def _detach_volumes(self, volumes):
        # NOTE(gfidente): two loops so we do not wait for the status twice
        for v in volumes:
            self.volume_client.volumes.detach(v)
        for v in volumes:
            self.status_timeout(self.volume_client.volumes,
                                v.id,
                                'available')

    def _create_floating_ip2(self):
        public_network_id = self.config.network.public_network_id
        server = self.server
        self.floating_ip = self._create_floating_ip(server, public_network_id)
        floating_ip = self.floating_ip
        self.floating_ips.setdefault(server, [])
        self.floating_ips[server].append(floating_ip)
        #return  floating_ip

    def _ssh_to_server(self, server, keypair, floating_ip):
        if self.config.compute.use_floatingip_for_ssh:
            self.floating_ip = floating_ip
            #fip_name = data_utils.rand_name('scenario-fip')
            #self.set_resource(fip_name, self.floating_ip)
            ip = self.floating_ip.floating_ip_address
        else:
            network_name_for_ssh = self.config.compute.public_network_id
            ip = server.networks[network_name_for_ssh][0]

        client = self.get_remote_client(ip,
                                        private_key=keypair.private_key)
        return client.ssh_client

    def _get_content(self, ssh_client):
        return ssh_client.exec_command('cat /tmp/text')

    def _write_text(self, ssh_client):
        text = data_utils.rand_name('text-')
        ssh_client.exec_command('echo "%s" > /tmp/text; sync' % (text))

        return self._get_content(ssh_client)

    def _delete_server(self, server):
        self.compute_client.servers.delete(server)
        self.delete_timeout(self.compute_client.servers, server.id)

    def _check_content_of_written_file(self, ssh_client, expected):
        actual = self._get_content(ssh_client)
        self.assertEqual(expected, actual)

    @services('compute', 'volume', 'image')
    def test_volume_boot_pattern(self):
        keypair = self.create_keypair()
        self.create_loginable_secgroup_rule()

        # create an instance from volume
        image_id = self.glance_image_create()
        volume_origin = self._create_volume_from_image(image_id)
        instance_1st = self._boot_instance_from_volume(image_id,volume_origin.id,
                                                       keypair)

        self._create_floating_ip2()
        # write content to volume on instance
        ssh_client_for_instance_1st = self._ssh_to_server(instance_1st,
                                                          keypair, self.floating_ip)
        text = self._write_text(ssh_client_for_instance_1st)

        # delete instance
        self._delete_server(instance_1st)

        # create a 2nd instance from volume
        instance_2nd = self._boot_instance_from_volume(image_id,volume_origin.id,
                                                       keypair)
        self._create_floating_ip2()
        # check the content of written file
        ssh_client_for_instance_2nd = self._ssh_to_server(instance_2nd,
                                                          keypair, self.floating_ip)
        self._check_content_of_written_file(ssh_client_for_instance_2nd, text)

        # snapshot a volume
        snapshot = self._create_snapshot_from_volume(volume_origin.id)

        

        # create a 3rd instance from snapshot
        
        volume = self._create_volume_from_snapshot(snapshot.id)
        instance_from_snapshot = self._boot_instance_from_volume(image_id,volume.id,
                                                                 keypair)

        self._create_floating_ip2()
        # check the content of written file
        ssh_client = self._ssh_to_server(instance_from_snapshot, keypair, self.floating_ip)
        self._check_content_of_written_file(ssh_client, text)

        # NOTE(gfidente): ensure resources are in clean state for
        # deletion operations to succeed
        self._stop_instances([instance_2nd, instance_from_snapshot])
        self._detach_volumes([volume_origin, volume])
