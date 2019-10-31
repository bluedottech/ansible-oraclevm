import json, requests, time
from ansible.module_utils.basic import AnsibleModule
from requests.packages import urllib3
urllib3.disable_warnings()
from six.moves.urllib import parse as urlparse


class Client:
    def __init__(self, base_uri, ovm_user, ovm_password):
        self.session = requests.Session()
        self.session.auth = (ovm_user, ovm_password)
        self.session.headers.update({'Accept': 'application/json', 'Content-Type': 'application/json'})
        self.session.verify = False
        self.base_uri = base_uri

    def _get_url(self, rel_path, params={}):
        url = "{0}/{1}".format(self.base_uri, rel_path)
        if params:
            query_str = urlparse.urlencode(params)
            url = "{0}?{1}".format(url, query_str)
        return url

    def get_id_for_name(self, object_type, object_name):
        response = self.session.get(self.base_uri+'/'+object_type+'/id')
        for element in response.json():
            if element['name'] == object_name:
                return element['value']
        return None

    def get_ids(self, object_type):
        response = self.session.get(self.base_uri+'/'+object_type)
        return response.json()

    def get(self, object_type, object_id):
        response = self.session.get(self.base_uri+'/'+object_type+'/'+object_id)
        return response.json()

    def check_manager(self):
        while True:
            r = self.session.get(self.base_uri+'/Manager')
            manager = r.json()
            if manager[0]['managerRunState'].upper() == 'RUNNING':
                break
            time.sleep(1)
        return manager

    def create(self, object_type, id, data, params={}):
        if object_type == 'VirtualDisk':
            rel_path = 'Repository/{}/VirtualDisk'.format(id)
        elif object_type == 'Diskmap':
            rel_path = 'Vm/{}/VmDiskMapping'.format(id)
        elif object_type == 'VirtualNic':
            rel_path = 'Vm/{}/VirtualNic'.format(id)
        else:
            rel_path = '/Vm/{}'.format(id)

        response = self.session.post(self._get_url(rel_path, params), data=json.dumps(data))
        try:
            job = response.json()
        except Exception as e:
            return e
        return self.monitor_job(job['id']['value'])

    def clone(self, object_type, template, data):
        response = self.session.put('{0}/{1}/{2}/clone'.format(self.base_uri, object_type, template), params=data)
        job = response.json()
        self.monitor_job(job['id']['value'])
        res = self.monitor_job(job['id']['value'])
        return res

    def update(self, object_type, id, data):
        response = self.session.put('{0}/{1}/{2}'.format(self.base_uri, object_type, id), data=json.dumps(data))
        job = response.json()
        try:
            res = self.monitor_job(job['id']['value'])
        except Exception as e:
            res = e
        return res

    def delete(self, object_type, id):
        response = self.session.delete('{0}/{1}/{2}'.format(self.base_uri, object_type, id))
        job = response.json()
        try:
            res = self.monitor_job(job['id']['value'])
        except Exception as e:
            res = e
        return res

    def start_vm(self, id):
        response = self.session.put('{0}/Vm/{1}/start'.format(self.base_uri, id))
        job = response.json()
        try:
            res = self.monitor_job(job['id']['value'])
        except Exception as e:
            res = e
        return res

    def stop_vm(self, id):
        response = self.session.put('{0}/Vm/{1}/kill'.format(self.base_uri, id))
        job = response.json()
        try:
            res = self.monitor_job(job['id']['value'])
        except Exception as e:
            res = e
        return res

    def monitor_job(self, job_id):
        while True:
            response = self.session.get(self.base_uri+'/Job/'+job_id)
            job = response.json()
            if job['summaryDone'] is True:
                if job['jobRunState'] == 'FAILURE':
                    raise Exception('Job failed: {}'.format(job['error']))
                elif job['jobRunState'] == 'SUCCESS':
                    if 'resultId' in job:
                        return job['resultId']['value']
                    break
                elif job['jobRunState'] == 'RUNNING':
                    continue
                else:
                    break


def main():
    module = AnsibleModule(
        argument_spec=dict(
            state=dict(
                default='present',
                choices=['present', 'absent']),
            name=dict(required=True),
            ovm_user=dict(required=True),
            ovm_pass=dict(required=True),
            ovm_host=dict(required=True),
            server_pool=dict(required=True),
            repository=dict(required=True),
            vm_domain_type=dict(
                default='XEN_HVM_PV_DRIVERS',
                choices=['XEN_HVM', 'XEN_PVM', 'XEN_HVM_PV_DRIVERS']),
            memory=dict(type='int', required=True),
            max_memory=dict(type='int'),
            vcpu_cores=dict(type='int', required=True),
            max_vcpu_cores=dict(type='int'),
            networks=dict(type='list'),
            disks=dict(type='list'),
            boot_order=dict(required=True, type='list'),
            template=dict(required=True),
            )
        )

    memory = module.params['memory']
    max_memory = module.params['max_memory']
    vcpu_cores = module.params['vcpu_cores']
    max_vcpu_cores = module.params['max_vcpu_cores']
    disks = module.params['disks']
    networks = module.params['networks']

    if max_memory is None:
        max_memory = memory

    if memory % 1024 != 0 or max_memory % 1024 != 0:
        module.fail_json(msg="Memory must be in GiB")

    if max_vcpu_cores is None:
        max_vcpu_cores = vcpu_cores

    base_uri = module.params['ovm_host'] + '/ovm/core/wsapi/rest'
    ovm_user = module.params['ovm_user']
    ovm_pass = module.params['ovm_pass']
    client = Client(base_uri, ovm_user, ovm_pass)
    repo_id = client.get_id_for_name('Repository', module.params['repository'])
    server_pool_id = client.get_id_for_name('ServerPool', module.params['server_pool'])
    template_id = client.get_id_for_name('Vm', module.params['template'])
    vm_id = client.get_id_for_name('Vm', module.params['name'])
    if vm_id is None:
        vm = client.clone('Vm', template_id, data={'repositoryId': repo_id,
                                                   'serverPoolId': server_pool_id, 'createTemplate': False,
                                         })
    else:
        vm = client.get(
            'Vm',
            vm_id
        )
        module.exit_json(changed=False)

    vm_data = client.get('Vm', vm)
    vm_data['name'] = module.params['name']
    vm_data['memory'] = memory
    vm_data['memoryLimit'] = memory
    vm_data['cpuCount'] = vcpu_cores
    vm_data['cpuCountLimit'] = max_vcpu_cores
    client.update('Vm', vm, vm_data)
    time.sleep(5)
    disk_ids = []
    module.debug(msg=disks)
    for disk in disks:
        repo_id = client.get_id_for_name('Repository', disk['repository'])
        disk_data = {'diskType': 'VIRTUAL_DISK', 'name': disk['name'], 'description': disk['description'], 'size': 1024 * 1024 * 1024 * int(disk['size']), 'shareable': False}
        params = {'sparse': disk_data}
        res = client.create('VirtualDisk', repo_id, disk_data, params)
        disk_ids.append(res)

    disk_target = 1
    for disk in disk_ids:
        disk_info = client.get('VirtualDisk', disk)
        data = {"id": {"type": "com.oracle.ovm.mgr.ws.model.VmDiskMapping"},
                "virtualDiskId": {
                    "type": "com.oracle.ovm.mgr.ws.model.VirtualDisk",
                    "value": disk
                },
                "diskTarget": disk_target,
                "name": disk_info['name'],
                "description": disk_info['description'],
                "diskWriteMode": 'READ_WRITE'
                }
        res = client.create('Diskmap', vm, data)
        disk_target += 1

    template_nic = vm_data['virtualNicIds'][0]['value']
    client.delete('Vm/{vmId}/VirtualNic'.format(vmId=vm), template_nic)

    for net in networks:
        net_id = client.get_id_for_name('Network', net['network'])
        net_data = client.get('Network', net_id)
        data = {'networkId': {'type': 'com.oracle.ovm.mgr.ws.model.Network', 'value': net_data['id']['value'], 'uri': net_data['id']['uri'], 'name': net['name']} }
        res = client.create('VirtualNic', vm, data)

    #client.start_vm(vm)

    module.exit_json(changed=True)

from ansible.module_utils.basic import AnsibleModule
if __name__ == '__main__':
    main()
