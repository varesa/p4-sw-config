#!/usr/bin/env python3

from flask import Flask, request, send_file
from ipaddress import IPv4Address
import io
import jinja2
import os
import tarfile
import tempfile
import yaml

app = Flask(__name__)


def get_peer(sw_vars: dict, peer_ip: str) -> (int, dict):
    """
    Filter the list of configured peers for the given IP address
    """

    for host_id, params in sw_vars['evpn_peers'].items():
        if peer_ip in params['underlay']:
            return host_id, params
    
    return None


def get_vars():
    """
    Generate a view of the configuration variables specific to the 
    client that connected.
    """

    with open('../vars.yaml', 'r') as f:
        sw_vars = yaml.safe_load(f)

    peer_ip = request.remote_addr
    peer_id, peer_params = get_peer(sw_vars, peer_ip)

    vars = {}

    vars['asn'] = peer_params['asn']
    vars['hostname'] = peer_params['name']
    vars['loopback'] = peer_params['overlay']
    for offset, side in enumerate(['a', 'b']):
        vars[f'localip_{side}'] = peer_params['underlay'][offset]
        vars[f'swip_{side}'] = str(IPv4Address(peer_params['underlay'][offset])-1)

    vars['vlans'] = sw_vars['vlans']
    for vlan_id, vlan in vars['vlans'].items():
        if 'host_base' in vlan.keys():
            vars['vlans'][vlan_id]['host_ip'] = str(IPv4Address(vlan['host_base']) + peer_id)
    
    return vars


def frr_config_perms(file: tarfile.TarInfo) -> tarfile.TarInfo:
    """
    Fix the ownership of the files going into the archive
    """

    file.uid = file.gid = 0
    file.uname = file.gname = "root"
    return file


@app.route("/frr")
def frr_config():
    vars = get_vars()
    template_names = os.listdir('frr')
    jinja_env = jinja2.Environment(loader=jinja2.FileSystemLoader('frr'))
    jinja_env.undefined = jinja2.StrictUndefined

    with tempfile.TemporaryDirectory() as temp:
        for template_name in template_names:
            template = jinja_env.get_template(template_name)
            with open(os.path.join(temp, template_name), 'w') as config:
                config.write(template.render(**vars))
        
        with tarfile.open(os.path.join(temp, 'frr.tar.gz'), 'w:gz') as archive:
            archive.add(temp, arcname='frr', filter=frr_config_perms)

        with open(os.path.join(temp, 'frr.tar.gz'), 'rb') as archive:
            # Copy into memory
            archive_bytes = io.BytesIO(archive.read())
            return send_file(archive_bytes, download_name='frr.tar.gz', mimetype='application/gzip')


@app.route("/nmstate")
def nmstate_config():
    vars = get_vars()

    jinja_env = jinja2.Environment(loader=jinja2.FileSystemLoader('.'))
    jinja_env.undefined = jinja2.StrictUndefined
    template = jinja_env.get_template('nmstate.j2')

    return template.render(**vars)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=50005)
