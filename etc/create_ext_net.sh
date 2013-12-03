#!/bin/bash

keystone_url=$1
token_id=$(curl -X 'POST' http://$keystone_url:5000/v2.0/tokens -d '{"auth":{"passwordCredentials":{"username": "admin", "password":"admin"}}}' -H 'Content-type: application/json' | python -mjson.tool | grep id | awk '{print $2;}' | sed -n '1p' | grep -oP '"\K[^"\047]+(?=["\047])')

tenant_id=$(curl -H "X-Auth-Token:$token_id" http://$keystone_url:5000/v2.0/tenants | python -mjson.tool | grep id | awk '{print $2;}'| sed -n '1p' | grep -oP '"\K[^"\047]+(?=["\047])')
token_id2=$(curl -k -X 'POST' -v http://$keystone_url:5000/v2.0/tokens -d '{"auth":{"passwordCredentials":{"username": "admin", "password":"admin"}, "tenantId":'\""$tenant_id"\"'}}' -H 'Content-type: application/json' | awk '{print $8}' | grep -oP '"\K[^"\047]+(?=["\047])')
ex_net_id=$(curl -v -X 'POST' -H "X-Auth-Token:$token_id2"  http://$keystone_url:9696/v2.0/networks -d '{"network":{"name": "provider_network1", "provider:physical_network":"external", "router:external":true, "shared": false, "provider:network_type": "flat"}}' -H 'Content-type: application/json'  | python -mjson.tool | grep id | sed -n '1p' | awk '{print $2;}'|grep -oP '"\K[^"\047]+(?=["\047])')
echo external_net  $ex_net_id 
subnet=$(curl -v -X 'POST' -H "X-Auth-Token:$token_id2" http://$keystone_url:9696/v2.0/subnets -d '{"subnet":{"name": "provider_subnet1", "gateway_ip": "10.10.13.1", "dns_nameservers": ["10.22.96.1"],"network_id":'\""$ex_net_id"\"',"ip_version":4,"cidr":"10.10.13.0/24","allocation_pools":[{"start":"10.10.13.200","end":"10.10.13.230"}]}}' -H 'Content-type: application/json'  | python -mjson.tool)

sed -i "s/^public_network_id.*/public_network_id = $ex_net_id/"  tempest.conf
