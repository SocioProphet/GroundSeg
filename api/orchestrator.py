import json, os, time, psutil, shutil, copy, subprocess #, requests, socket, sys
from datetime import datetime
from flask import jsonify, send_file

from wireguard import Wireguard
from urbit_docker import UrbitDocker, default_pier_config
from minio_docker import MinIODocker
from updater_docker import WatchtowerDocker

class Orchestrator:
    
#
#   Variables
#
    config = {}
    _urbits = {}
    _minios = {}
    _watchtower = {}
    minIO_on = False
    gs_version = 'Beta-3.0.0'

#
#   init
#
    def __init__(self, config_file):
        # store config file location
        self.config_file = config_file

        # load existing or create new system.json
        self.config = self.load_config(config_file)

        # if first boot, set up keys
        if self.config['firstBoot']:
            self.reset_pubkey()
            self.config['firstBoot'] = False
        
        # save the latest config to file
        self.save_config()

        # start wireguard if anchor is registered
        self.wireguard = Wireguard(self.config)
        if self.config['wgRegistered']:
            self.wireguard.stop()
            self.wireguard.start()
            self.toggle_minios_off()
            self.toggle_minios_on()

        # load urbit ships
        self.load_urbits()

        # start auto updater
        self._watchtower = WatchtowerDocker(self.config['updateMode'])

    # Checks if system.json and all its fields exists, adds field if incomplete
    def load_config(self, config_file):
        cfg = {}
        try:
            with open(config_file) as f:
                cfg = json.load(f)
        except Exception as e:
            print(e)

        cfg = self.check_config_field(cfg,'firstBoot',True)
        cfg = self.check_config_field(cfg,'piers',[])
        cfg = self.check_config_field(cfg,'endpointUrl', 'api.startram.io')
        cfg = self.check_config_field(cfg,'apiVersion', 'v1')
        cfg = self.check_config_field(cfg,'wgRegistered', False)
        cfg = self.check_config_field(cfg,'updateMode','auto')

        cfg['gsVersion'] = self.gs_version

        # Remove reg_key from old configs
        if 'reg_key' in cfg:
            if cfg['reg_key'] != None:
                cfg['wgRegistered'] = True
                cfg['reg_key'] = None
        
        return cfg

    # Adds missing field to config
    def check_config_field(self, cfg, field, default):
        if not field in cfg:
            cfg[field] = default
        return cfg

    # Load urbit ships
    def load_urbits(self):
        for p in self.config['piers']:
            data = None
            with open(f'settings/pier/{p}.json') as f:
                data = json.load(f)

            self._urbits[p] = UrbitDocker(data)

            if data['minio_password'] != '':
                self._minios[p] = MinIODocker(data)
                self.toggle_minios_on()

#
#   Urbit Pier
#
    # Get all piers for home page
    def get_urbits(self):
        urbits= []

        for urbit in self._urbits.values():
            u = dict()
            u['name'] = urbit.pier_name
            u['running'] = urbit.is_running()
            u['url'] = f'http://{os.environ["HOST_HOSTNAME"]}.local:{urbit.config["http_port"]}'

            if(urbit.config['network']=='wireguard'):
                u['url'] = f"https://{urbit.config['wg_url']}"

            urbits.append(u)

        return {'urbits': urbits}

    # Get all details of Urbit ID
    def get_urbit(self, urbit_id):

        # Check if Urbit Pier exists
        urb = self._urbits.get(urbit_id)
        if(urb == None):
            return 400

        # Create query result
        u = dict()
        u['name'] = urb.pier_name
        u['running'] = urb.is_running()

        u['wgReg'] = self.config['wgRegistered']
        u['wgRunning'] = self.wireguard.is_running()
        u['timeNow'] = datetime.utcnow()
        u['frequency'] = urb.config['meld_frequency']

        u['remote'] = False
        u['urbitUrl'] = f'http://{os.environ["HOST_HOSTNAME"]}.local:{urb.config["http_port"]}'
        u['minIOUrl'] = ""
        u['minIOReg'] = True
        u['hasBucket'] = False

        if(urb.config['network'] == 'wireguard'):
            u['remote'] = True
            u['urbitUrl'] = f"https://{urb.config['wg_url']}"

        if self.config['wgRegistered']:
            u['minIOUrl'] = f"https://console.s3.{urb.config['wg_url']}"

        if urb.config['minio_password'] == '':
             u['minIOReg'] = False

        if urbit_id in self._minios:
            u['hasBucket'] = True

        return u

    # Handle POST request relating to Urbit ID
    def handle_urbit_post_request(self ,urbit_id, data):

        # Boot new Urbit
        if data['app'] == 'boot-new':
           x = self.boot_new_urbit(urbit_id, data.get('data'))
           if x == 0:
             return 200

        # Check if Urbit Pier exists
        urb = self._urbits.get(urbit_id)
        if urb == None:
            return 400

        # Urbit Pier requests
        if data['app'] == 'pier':
            if data['data'] == 'toggle':
                x = self.toggle_pier_power(urb)
                return x

            if data['data'] == '+code':
                x = self.get_urbit_code(urbit_id, urb)
                return x

            if data['data'] == 's3-update':
                x = self.set_minio_endpoint(urbit_id)
                return x

        # Wireguard requests
        if data['app'] == 'wireguard':
            if data['data'] == 'toggle':
                x = self.toggle_pier_network(urb)
                return x

        # MinIO requests
        if data['app'] == 'minio':
            pwd = data.get('password')
            if pwd != None:
                x = self.create_minio_admin_account(urbit_id, pwd)
                return x

            if data['data'] == 'export':
                x = self.export_minio_bucket(urbit_id)
                return x

        return 400

    # Toggle Pier on or off
    def toggle_pier_power(self, urb):

        if urb.is_running() == True:
            x = urb.stop()
            if x == 0:
                return 200
            return 400
        else:
            x = urb.start()
            if x == 0:
                return 200
            return 400
        
        return 400

    # Toggle Pier Wireguard connection on or off
    def toggle_pier_network(self, urb):

        wg_reg = self.config['wgRegistered']
        wg_is_running = self.wireguard.wg_docker.is_running()
        cfg = urb.config

        network = 'none'
        if cfg['network'] == 'none' and wg_reg and wg_is_running:
            network = 'wireguard'

        x = urb.set_network(network)
        if x == 0:
            return 200

        return 400
            
    # Create minIO admin acccount
    def create_minio_admin_account(self, patp, password):
        self._urbits[patp].config['minio_password'] = password
        self._minios[patp] = MinIODocker(self._urbits[patp].config)
        self.minIO_on = True

        return 200
    
    # Get +code from Urbit
    def get_urbit_code(self, patp, urb):
        code = ''
        addr = self.get_urbit_loopback_addr(patp)
        try:
            code = urb.get_code(addr)
        except Exception as e:
            print(e)

        return code
 
    # Get looback address of Urbit Pier
    def get_urbit_loopback_addr(self, patp):
        log = self.get_logs(patp).decode('utf-8').split('\n')[::-1]
        substr = 'http: loopback live on'

        for ln in log:
            if substr in ln:
                return str(ln.split(' ')[-1])

    # Boot new pier from key
    def boot_new_urbit(self, patp, key):
        if patp == None:
            return 400

        http_port, ames_port = self.get_open_urbit_ports()
        urb = copy.deepcopy(default_pier_config)

        urb['pier_name'] = patp
        urb['http_port'] = http_port
        urb['ames_port'] = ames_port

        with open(f'settings/pier/{patp}.json', 'w') as f:
            json.dump(urb, f, indent = 4)
    
        urbit = UrbitDocker(urb)
        urbit.add_key(key)

        x = self.add_urbit(patp, urbit)
        return x

    # Get unused ports for Urbit
    def get_open_urbit_ports(self):
        http_port = 8080
        ames_port = 34343

        for u in self._urbits.values():
            if(u.config['http_port'] >= http_port):
                http_port = u.config['http_port']
            if(u.config['ames_port'] >= ames_port):
                ames_port = u.config['ames_port']

        return http_port+1, ames_port+1

    # Add Urbit to list of Urbit
    def add_urbit(self, patp, urbit):
        self.config['piers'].append(patp)
        self._urbits[patp] = urbit

        self.register_urbit(patp)
        self.save_config()

        x = urbit.start()
        return x
 
    # Register Wireguard for Urbit
    def register_urbit(self, patp):
        
        # Todo: clean up
        endpoint = self.config['endpointUrl']
        api_version = self.config['apiVersion']
        url = f'https://{endpoint}/{api_version}'

        if self.config['wgRegistered']:
            self.anchor_config = self.wireguard.get_status(url)
            patp_reg = False

            if self.anchor_config != None:
                for ep in self.anchor_config['subdomains']:
                    if(patp in ep['url']):
                        print(f"{patp} already exists")
                        patp_reg = True

            if patp_reg == False:
                self.wireguard.register_service(f'{patp}','urbit',url)
                self.wireguard.register_service(f's3.{patp}','minio',url)

            self.anchor_config = self.wireguard.get_status(url)
            url = None
            http_port = None
            ames_port = None
            s3_port = None
            console_port = None

            print(self.anchor_config['subdomains'])
            pub_url = '.'.join(self.config['endpointUrl'].split('.')[1:])
            for ep in self.anchor_config['subdomains']:
                if(f'{patp}.{pub_url}' == ep['url']):
                    url = ep['url']
                    http_port = ep['port']
                elif(f'ames.{patp}.{pub_url}' == ep['url']):
                    ames_port = ep['port']
                elif(f'bucket.s3.{patp}.{pub_url}' == ep['url']):
                    s3_port = ep['port']
                elif(f'console.s3.{patp}.{pub_url}' == ep['url']):
                    console_port = ep['port']

            self._urbits[patp].set_wireguard_network(url, http_port, ames_port, s3_port, console_port)
            self.wireguard.start()

    # Update/Set Urbit S3 Endpoint
    def set_minio_endpoint(self, patp):
        ak, sk = self._minios[patp].make_service_account().split('\n')
        u = self._urbits[patp]

        endpoint = f"s3.{u.config['wg_url']}"
        bucket = 'bucket'
        lens_port = self.get_urbit_loopback_addr(patp)
        access_key = ak.split(' ')[-1]
        secret = sk.split(' ')[-1]

        try:
            x = u.set_minio_endpoint(endpoint,access_key,secret,bucket,lens_port)
            return 200

        except Exception as e:
            print(e)
        
        return 400

    # Export contents of minIO bucket
    def export_minio_bucket(self, patp):
        m = self._minios[patp]
    
        if(m==None):
            return 400
        
        file_name = f'bucket_{patp}.zip'
        bucket_path=f'/var/lib/docker/volumes/minio_{patp}/_data/bucket'
        shutil.make_archive(f'/app/tmp/bucket_{patp}', 'zip', bucket_path)

        return send_file(f'/app/tmp/{file_name}', download_name=file_name, as_attachment=True)


#
#   System Settings
#
    # Get all system information
    def get_system_settings(self):
        settings = dict()
        settings['wgReg'] = self.config['wgRegistered']
        settings['wgRunning'] = self.wireguard.is_running()
        settings['ram'] = psutil.virtual_memory().percent
        settings['cpu'] = psutil.cpu_percent(1)
        settings['temp'] = psutil.sensors_temperatures()['coretemp'][0].current
        settings['disk'] = shutil.disk_usage("/")
        settings['gsVersion'] = self.gs_version
        settings['updateMode'] = self.config['updateMode']
        settings['ethOnly'] = self.get_ethernet_status()
        settings['minio'] = self.minIO_on

        return {'system': settings}

    # Modify system settings
    def handle_module_post_request(self, module, data):

        # anchor module
        if module == 'anchor':
            if data['action'] == 'register':
                return self.register_device(data['key']) 

            if data['action'] == 'toggle':
                running = self.wireguard.is_running()
                if running:
                    return self.toggle_anchor_off()
                return self.toggle_anchor_on()

            if data['action'] == 'get-url':
                return self.config['endpointUrl']

            if data['action'] == 'change-url':
                return self.change_wireguard_url(data['url'])

        # watchtower module
        if module == 'watchtower':
            if data['action'] == 'toggle':
                return self.set_update_mode()

        # minIO module
        if module == 'minio':
            if data['action'] == 'reload':
                self.toggle_minios_off()
                self.toggle_minios_on()
                time.sleep(1)
                return 200

        return module

    # Check if wifi is disabled
    def get_ethernet_status(self):
        wifi_status = subprocess.Popen(['nmcli','radio','wifi'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        ws, stderr = wifi_status.communicate()

        if ws == b'enabled\n':
            return False
        return True

    # Starts Wireguard and all MinIO containers
    def toggle_anchor_on(self):
           self.wireguard.start()
           self.toggle_minios_on() 
           return 200

    # Stops Wireguard and all MinIO containers
    def toggle_anchor_off(self):
        for p in self._urbits.keys():
            if(self._urbits[p].config['network'] == 'wireguard'):
                 self.toggle_pier_network(self._urbits[p])

        self.toggle_minios_off()
        self.wireguard.stop()
        return 200

    # Toggle MinIO on
    def toggle_minios_on(self):
      for m in self._minios.values():
         m.start()
      self.minIO_on = True

    # Toggl MinIO off
    def toggle_minios_off(self):
      for m in self._minios.values():
         m.stop()
      self.minIO_on = False

    # Register device to an Anchor service using a key
    def register_device(self, reg_key):

        endpoint = self.config['endpointUrl']
        api_version = self.config['apiVersion']
        url = f'https://{endpoint}/{api_version}'

        x = self.wireguard.register_device(reg_key, url) 

        if x == None:
            return 400

        time.sleep(2)
        self.anchor_config = self.wireguard.get_status(url)

        if(self.anchor_config != None):
           print("starting wg")
           self.wireguard.start()
           self.config['wgRegistered'] = True
           time.sleep(2)
           
           print("reg urbits")
           for p in self.config['piers']:
              self.register_urbit(p)

           print("starting minIOs")
           self.toggle_minios_on()
           self.save_config()

           return 200
        return 400

    # Change Anchor endpoint URL
    def change_wireguard_url(self, url):
        self.config['endpointUrl'] = url
        self.config['wgRegistered'] = False
        self.toggle_anchor_off()
        self.reset_pubkey()
        self.save_config()
        if self.config['endpointUrl'] == url:
            return 200
        return 400

    # Toggle update mode
    def set_update_mode(self):
        if self.config['updateMode'] == 'auto':
            self.config['updateMode'] = 'off'
        else:
            self.config['updateMode'] = 'auto'

        self.save_config()
        self._watchtower.remove()
        self._watchtower = WatchtowerDocker(self.config['updateMode'])

        return 200


#
#   General
#

    def save_config(self):
        with open(self.config_file, 'w') as f:
            json.dump(self.config, f, indent = 4)

    # Reset Public and Private Keys
    def reset_pubkey(self):
        subprocess.run("wg genkey > privkey", shell=True)
        subprocess.run("cat privkey| wg pubkey | base64 -w 0 > pubkey", shell=True)

        # Load priv and pub key
        with open('pubkey') as f:
           self.config['pubkey'] = f.read().strip()
        with open('privkey') as f:
           self.config['privkey'] = f.read().strip()
        #clean up files
        subprocess.run("rm privkey pubkey", shell =True)
 
    # Get logs from docker container
    def get_logs(self, container):
        if container == 'wireguard':
            return self.wireguard.wg_docker.logs()
        if 'minio_' in container:
            return self._minios[container[6:]].logs()
        if container in self._urbits.keys():
            return self._urbits[container].logs()
        return ""

    # Custom jsonify
    def custom_jsonify(self, val):
        if type(val) is int:
            return jsonify(val)
        if type(val) is str:
            return jsonify(val)
        return val




#####################################################################################

    def getMinIOSecret(self, patp):
        x = self._urbits[patp].config['minio_password']
        return(x)

    def removeUrbit(self, patp):
        urb = self._urbits[patp]
        urb.removeUrbit()
        urb = self._urbits.pop(patp)
        
        time.sleep(2)

        if(patp in self._minios.keys()):
           minio = self._minios[patp]
           minio.removeMinIO()
           minio = self._minios.pop(patp)

        self.config['piers'].remove(patp)
        self.save_config()
