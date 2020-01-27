#!/usr/bin/env/ python
import openstack
import os
import sys
import time
import configparser

cloud_name = sys.argv[1]
compute_node = sys.argv[2]
destination_node = sys.argv[3:]

# function to create openstack sdk connection object
def create_connection():
    try:
        global cloud
        if not cloud_name:
            raise Exception("  |-- \033[1;31;40mERROR\033[0;0m: OS_CLOUD environment variable not set.")
        cloud = openstack.connect(cloud=cloud_name)
        print("\n\n  |-- INFO: Successfully created openstack object")

    except:
        print("\n\n  |-- \033[1;31;40mERROR\033[0;0m: Failed to connect to {}".format(cloud_name))
        sys.exit(2)

# function to import nova create options from .ini file
def import_config():
    global netid
    global image
    global flavor
    global new_flavor
    global floating_network
    config = configparser.ConfigParser()
    config.read('/home/amsi0919/test1.ini')
    netid = config['{}'.format(cloud_name)]['netid']
    image = config['{}'.format(cloud_name)]['image']
    flavor = config['{}'.format(cloud_name)]['flavor']
    new_flavor = config['{}'.format(cloud_name)]['new_flavor']
    floating_network = config['{}'.format(cloud_name)]['floating_network']

# function to display availability zone of the compute node
def az_check():
    global az
    az = []
    for server in cloud.compute.aggregates():
        if "{}".format(compute_node) in server.hosts:
            print("  |-- INFO: Compute node is in: {} availability zone".format(server.availability_zone))
            az = server.availability_zone
    if az == []:
        az = "nova"
        print("  |-- INFO: Compute node {} in NOVA availability zone".format(compute_node))
     
# function to boot a nova instance
def boot_instance():
    global floating_ip
    global vm_id
    global internal_ip
    jenkins_vm = cloud.compute.find_server("test-jenkins-2")
    if jenkins_vm != None:
        jenkins_vm_id = cloud.compute.find_server("test-jenkins-2").id
        cloud.compute.delete_server("{}".format(jenkins_vm_id))
        print("  |-- INFO: An existing instance with name test-jenkins-2 has been deleted.")
    print("  |-- INFO: Booting an instance on node {}".format(compute_node))
    try:
        os.popen("openstack --os-cloud {} server create --image {} --flavor {} --availability-zone {}:{} --nic net-id={} test-jenkins-2 --wait".format(cloud_name, image, flavor, az, compute_node, netid)).read()
        print("  |-- INFO: Instance {} has been booted up on node {}").format(cloud.compute.find_server("test-jenkins-2").name, compute_node)
    except:
        print("  |-- \033[1;31;40mERROR\033[0;0m: Instance creation failed.")
        sys.exit(6) 
    floating_ip = cloud.available_floating_ip().floating_ip_address[0:]
    vm_id = cloud.compute.find_server("test-jenkins-2").id
    for i in cloud.compute.get_server("{}".format(vm_id)).addresses["{}".format(eval(netid))]:
        dict1 = i
        internal_ip = dict1["addr"]
    print("  |-- INFO: Attaching a floating IP to the instance.")
    cloud.compute.add_floating_ip_to_server(vm_id, floating_ip, internal_ip)   
    ping_check()

#function to do a ping check       
def ping_check():
    print("  |-- INFO: Ping test in progress....")
    for i in range(3):
        pckt1 = os.popen('ping -c4 {} | grep "packet loss" | cut -d "," -f3 | awk "{{print $1}}" | awk "{{print $1}}"'.format(floating_ip)).read()
        if "100%" not in pckt1:
            print("  |-- INFO: Instance 'test-jenkins-2' is pinging.\n")
            break
        else:
            print("  |-- \033[1;31;40mERROR\033[0;0m: Pinging instance 'test-jenkins-2' failed in {} attempt".format(i+1))    

# function to live migrate an instance
def live_migrate():
    print("  |-- INFO: Instance will be migrated off compute node now.")
    jenkins_vm = cloud.compute.find_server("test-jenkins-2")
    if len(destination_node) == 1:
        cloud.compute.live_migrate_server("{}".format(vm_id), host="{}".format(destination_node[0]), force=True, block_migration=None)
        cloud.compute.wait_for_server(jenkins_vm, status="ACTIVE", failures=None, interval=2, wait=60)
        destination_hypervisor = cloud.compute.get_server("{}".format(vm_id)).hypervisor_hostname
        if destination_hypervisor in destination_node:
            print("  |-- INFO: Instance is migrated to node {}".format(destination_hypervisor))
            ping_check()
            migrate_back()
        else:
            print("  |-- \033[1;31;40mERROR\033[0;0m: Instance migration failed. ")
            delete_instance()
            sys.exit(3)
           
    else:
        if az == "nova":
            hosts_list = os.popen('openstack --os-cloud {} compute service list -c Host -c Zone -f value | grep nova | grep netcracker.com | cut -d " " -f1'.format(cloud_name)).read().split()
        else:
            for aggr in cloud.list_aggregates():
                if az in aggr.availability_zone:
                    hosts_list = aggr.hosts
        for host in hosts_list:
            try:
                cloud.compute.live_migrate_server("{}".format(vm_id), host="{}".format(host), force=True, block_migration=None)
            except:
                print("  |-- \033[1;31;40mERROR\033[0;0m: Attempt to migrate instance on node {} failed".format(host))
            else:
                break
        cloud.compute.wait_for_server(jenkins_vm, status="ACTIVE", failures=None, interval=2, wait=60)
        destination_hypervisor = cloud.compute.get_server("{}".format(vm_id)).hypervisor_hostname
        if destination_hypervisor != compute_node:
            print("  |-- INFO: Instance is migrated to node {}".format(destination_hypervisor))
            ping_check()
            migrate_back()
        else:
            print("  |-- \033[1;31;40mERROR\033[0;0m: Could not migrate instance")
            delete_instance()
            sys.exit(7)

# function to migrate the instance back to original compute node
def migrate_back():
    global flavor_id
    print("  |-- INFO: Instance will be migrated back to compute node now.")
    flavor_id = cloud.compute.get_server(vm_id).flavor["id"]
    jenkins_vm = cloud.compute.find_server("test-jenkins-2")
    cloud.compute.live_migrate_server("{}".format(vm_id), host=compute_node, force=True, block_migration=None)
    cloud.compute.wait_for_server(jenkins_vm, status="ACTIVE", failures=None, interval=2, wait=60)
    destination_hypervisor = cloud.compute.get_server("{}".format(vm_id)).hypervisor_hostname
    if destination_hypervisor in compute_node:
        print("  |-- INFO: Instance has been migrated back to original compute node {}".format(destination_hypervisor))
        ping_check()
        server_resize()
    else:
        print("  |-- \033[1;31;40mERROR\033[0;0m: Could not migrate instance")
        delete_instance()
        sys.exit(8)

# function to resize the instance
def server_resize():
    print("  |-- INFO: Instance will be resized now.")
    new_flavorid = cloud.compute.find_flavor(eval(new_flavor)).id
    try:
        cloud.compute.resize_server(vm_id, new_flavorid)
    except Exception as e:
        print("\n\n\033[1;31;40mERROR\033[0;0m: {}".format(e))
        delete_instance()
        sys.exit(1)
    for i in range(5):
        if cloud.compute.get_server(vm_id).status == "VERIFY_RESIZE":
            continue
        else:
            time.sleep(20)
            print("  |-- Sleeping for 20 sec before polling the instance status again.")
    new_flavor_id = cloud.compute.get_server(vm_id).flavor["id"]
    if new_flavor_id != flavor_id:
        #or cloud.compute.wait_for_server(jenkins_vm, status="RESIZED", failures=None, interval=2, wait=60):
        print("  |-- INFO: Instance has been resized successfully")
    else:
        print("\n\n\033[1;31;40mERROR\033[0;0m: Instance resizing has failed")
        delete_instance()
        sys.exit(9)

# function to delete the instance
def delete_instance():
    print("  |-- INFO: Deleting instance now.")
    jenkins_vm = cloud.compute.find_server("test-jenkins-2")        
    cloud.compute.delete_server(vm_id)
    try:
        cloud.compute.delete_server(vm_id)
    except Exception as e:
        print("\n\n\033[1;31;40mERROR\033[0;0m: {}".format(e))
        sys.exit(1)
    time.sleep(10)
    if cloud.compute.find_server("test-jenkins-2") == None:
        print("  |-- INFO: Instance was deleted successfully")
    else:
        print("\n\n\033[1;31;40mERROR\033[0;0m: Instance deletion failed")
        sys.exit(5) 
    
# main function  
def main():
    create_connection()
    import_config()
    az_check()
    boot_instance()
    live_migrate()
    delete_instance()

if __name__ == '__main__':
    main()
